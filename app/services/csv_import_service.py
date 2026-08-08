"""Fase 12 (Advanced Tools -- CSV Import) do SAES_Financial_Planning_
Master_Spec, 2026-08-07. Escopo confirmado com o usuário, fluxo completo
de 12 passos (verbatim do pedido):

1. Cliente seleciona a Account relacionada.
2. Faz upload do CSV.
3. Sistema detecta as colunas disponíveis.
4. Cliente confirma/mapeia Date, Description, Amount, Debit/Credit.
5. Sistema mostra preview antes da importação.
6. Sistema tenta classificar Income, Expense ou Transfer.
7. Sistema sugere categorias, mas não toma decisões irreversíveis sozinho.
8. Detecta possíveis transações duplicadas.
9. Cliente revisa e seleciona o que deseja importar.
10. Só depois da confirmação os registros são criados de verdade.
11. Gera relatório de sucesso/ignorados/duplicados/erros.
12. Registra a importação no audit log.

Diferente da "Notion Migration" do documento (ferramenta administrativa
separada, exclusiva pro staff -- não construída aqui).

Decisão de escopo pro passo 6 (Transfer): sugerir Transfer automaticamente
exigiria adivinhar a conta de destino/origem a partir só da descrição do
banco -- muito frágil, e classificar errado um Transfer o esconderia
silenciosamente de Income/Expense (risco real de integridade de dado).
Em vez disso: a sugestão automática é sempre Income (valor positivo) ou
Expense (valor negativo); "Transfer" fica disponível como reclassificação
MANUAL na tela de revisão (o cliente escolhe a conta de contrapartida na
hora), nunca uma sugestão automática -- consistente com "must not make
irreversible decisions automatically".
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime, timezone

from app.crm_financial_models import FinancialWorkspace
from app.db import SessionLocal
from app.financial_planning_models import (Account, CsvImportBatch, CsvImportRow,
                                            CsvImportRowStatus, CsvImportStatus,
                                            FinancialTransaction, TransactionType)
from app.services import audit_service
from app.services.financial_transactions_service import (TransactionValidationError,
                                                           create_transaction)

MAX_ROWS = 1000
_DATE_FORMATS = ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%m/%d/%y")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CsvImportValidationError(ValueError):
    pass


def _parse_date(raw: str) -> date | None:
    raw = (raw or "").strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _parse_amount(raw: str) -> int | None:
    """Devolve centavos SEM sinal (magnitude) -- a direção vem de
    `suggested_type`, mesma convenção de `FinancialTransaction.amount_cents`.
    `None` quando não dá pra converter (célula vazia, texto não-numérico)."""
    raw = (raw or "").strip()
    if not raw:
        return None
    negative = raw.startswith("(") and raw.endswith(")")
    if negative:
        raw = raw[1:-1]
    raw = raw.replace("$", "").replace(",", "").strip()
    if raw.startswith("-"):
        negative = True
        raw = raw[1:]
    try:
        value = float(raw)
    except ValueError:
        return None
    cents = round(value * 100)
    return -cents if negative else cents


# --------------------------------------------------------------------------
# Passos 1-3: upload + detecção de colunas
# --------------------------------------------------------------------------

def create_batch(workspace: FinancialWorkspace, *, actor, account: Account, filename: str, content: bytes) -> CsvImportBatch:
    if account.financial_workspace_id != workspace.id:
        raise CsvImportValidationError("Account does not belong to this workspace.")
    if not filename.lower().endswith(".csv"):
        raise CsvImportValidationError("Upload a .csv file.")

    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise CsvImportValidationError("Could not read the file as text -- export it as UTF-8 CSV.") from None

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise CsvImportValidationError("No columns detected -- the file appears to be empty.")
    rows = list(reader)
    if not rows:
        raise CsvImportValidationError("No data rows found in this file.")
    if len(rows) > MAX_ROWS:
        raise CsvImportValidationError(f"This file has {len(rows)} rows -- split it into files of {MAX_ROWS} or fewer.")

    batch = CsvImportBatch(
        financial_workspace_id=workspace.id, account_id=account.id, original_filename=filename,
        detected_columns=reader.fieldnames, status=CsvImportStatus.uploaded,
        created_by_id=getattr(actor, "id", None),
    )
    SessionLocal.add(batch)
    SessionLocal.flush()

    for i, raw in enumerate(rows, start=1):
        SessionLocal.add(CsvImportRow(batch_id=batch.id, row_number=i, raw_data=dict(raw)))
    SessionLocal.commit()
    return batch


# --------------------------------------------------------------------------
# Passo 4: mapeamento de colunas -> passos 6-8 (classificar/sugerir/duplicar)
# --------------------------------------------------------------------------

def _suggest_category_id(workspace: FinancialWorkspace, description: str) -> int | None:
    """Sugestão best-effort: se a descrição do CSV contém (ou é contida
    por) o `merchant_or_source` de alguma transação já categorizada neste
    workspace, reusa a categoria daquela transação. Nunca inventa uma
    categoria nova -- só reaproveita escolhas que o próprio cliente já
    fez antes."""
    if not description:
        return None
    description_lower = description.lower()
    candidates = (
        SessionLocal.query(FinancialTransaction)
        .filter(FinancialTransaction.financial_workspace_id == workspace.id,
                FinancialTransaction.merchant_or_source.isnot(None),
                FinancialTransaction.budget_category_id.isnot(None),
                FinancialTransaction.deleted_at.is_(None))
        .order_by(FinancialTransaction.transaction_date.desc()).limit(200).all()
    )
    for t in candidates:
        merchant_lower = t.merchant_or_source.lower()
        if merchant_lower in description_lower or description_lower in merchant_lower:
            return t.budget_category_id
    return None


def _find_duplicate(workspace: FinancialWorkspace, *, account_id: int, parsed_date: date,
                     amount_cents: int, suggested_type: TransactionType) -> FinancialTransaction | None:
    return (
        SessionLocal.query(FinancialTransaction)
        .filter(FinancialTransaction.financial_workspace_id == workspace.id,
                FinancialTransaction.account_id == account_id,
                FinancialTransaction.transaction_date == parsed_date,
                FinancialTransaction.amount_cents == amount_cents,
                FinancialTransaction.transaction_type == suggested_type,
                FinancialTransaction.deleted_at.is_(None))
        .first()
    )


def set_column_mapping(
    workspace: FinancialWorkspace, batch: CsvImportBatch, *, date_col: str,
    description_col: str, amount_col: str | None = None,
    debit_col: str | None = None, credit_col: str | None = None,
) -> CsvImportBatch:
    if not date_col or not description_col:
        raise CsvImportValidationError("Pick the Date and Description columns.")
    if not amount_col and not (debit_col and credit_col):
        raise CsvImportValidationError("Pick either a single Amount column, or both Debit and Credit columns.")
    if amount_col and (debit_col or credit_col):
        raise CsvImportValidationError("Pick either a single Amount column, or Debit/Credit -- not both.")

    batch.column_mapping = {
        "date": date_col, "description": description_col,
        "amount": amount_col, "debit": debit_col, "credit": credit_col,
    }
    batch.status = CsvImportStatus.mapped
    SessionLocal.commit()
    _process_rows(workspace, batch)
    return batch


def _process_rows(workspace: FinancialWorkspace, batch: CsvImportBatch) -> None:
    mapping = batch.column_mapping
    rows = SessionLocal.query(CsvImportRow).filter_by(batch_id=batch.id).all()

    for row in rows:
        parsed_date = _parse_date(row.raw_data.get(mapping["date"], ""))
        description = (row.raw_data.get(mapping["description"], "") or "").strip()

        if mapping["amount"]:
            amount_cents = _parse_amount(row.raw_data.get(mapping["amount"], ""))
            suggested_type = None
            if amount_cents is not None:
                suggested_type = TransactionType.expense if amount_cents < 0 else TransactionType.income
                amount_cents = abs(amount_cents)
        else:
            debit = _parse_amount(row.raw_data.get(mapping["debit"], ""))
            credit = _parse_amount(row.raw_data.get(mapping["credit"], ""))
            debit_present = debit is not None and debit != 0
            credit_present = credit is not None and credit != 0
            if debit_present and not credit_present:
                amount_cents, suggested_type = abs(debit), TransactionType.expense
            elif credit_present and not debit_present:
                amount_cents, suggested_type = abs(credit), TransactionType.income
            else:
                amount_cents, suggested_type = None, None

        row.parsed_date = parsed_date
        row.parsed_description = description or None
        row.parsed_amount_cents = amount_cents
        row.suggested_type = suggested_type
        row.is_duplicate = False
        row.duplicate_of_transaction_id = None
        row.parse_error = None
        row.status = CsvImportRowStatus.pending

        if parsed_date is None or amount_cents is None or suggested_type is None:
            row.parse_error = "Could not read a valid date/amount from this row with the current column mapping."
            row.status = CsvImportRowStatus.error
            continue

        row.suggested_category_id = _suggest_category_id(workspace, description)
        duplicate = _find_duplicate(
            workspace, account_id=batch.account_id, parsed_date=parsed_date,
            amount_cents=amount_cents, suggested_type=suggested_type)
        if duplicate is not None:
            row.is_duplicate = True
            row.duplicate_of_transaction_id = duplicate.id
            row.status = CsvImportRowStatus.duplicate

    SessionLocal.commit()


def list_rows(batch: CsvImportBatch) -> list[CsvImportRow]:
    return (
        SessionLocal.query(CsvImportRow).filter_by(batch_id=batch.id)
        .order_by(CsvImportRow.row_number.asc()).all()
    )


# --------------------------------------------------------------------------
# Passos 9-12: revisão, confirmação, relatório, auditoria
# --------------------------------------------------------------------------

def confirm_import(
    workspace: FinancialWorkspace, batch: CsvImportBatch, *, actor,
    selections: dict[int, dict],
) -> dict:
    """`selections` é `{row_id: {"import": bool, "type": TransactionType,
    "category_id": int|None, "transfer_counterpart_account_id": int|None}}`
    -- só linhas com `import=True` viram `FinancialTransaction` de
    verdade; as outras ficam `skipped` (ou continuam `duplicate`/`error`
    se já estavam assim). Cada linha é independente -- um erro numa não
    derruba as outras, tudo isso vira o relatório do passo 11."""
    if batch.status == CsvImportStatus.completed:
        raise CsvImportValidationError("This import has already been completed.")

    rows = list_rows(batch)
    for row in rows:
        selection = selections.get(row.id, {})
        wants_import = bool(selection.get("import")) and row.status != CsvImportRowStatus.error

        if not wants_import:
            if row.status == CsvImportRowStatus.pending:
                row.status = CsvImportRowStatus.skipped
            continue

        row_type = selection.get("type") or row.suggested_type
        category_id = selection.get("category_id") if selection.get("category_id") else row.suggested_category_id
        try:
            if row_type == TransactionType.transfer:
                counterpart_id = selection.get("transfer_counterpart_account_id")
                if not counterpart_id:
                    raise TransactionValidationError("Transfer rows need a counterpart account selected.")
                is_outflow = row.suggested_type == TransactionType.expense
                transfer_from = batch.account_id if is_outflow else counterpart_id
                transfer_to = counterpart_id if is_outflow else batch.account_id
                transaction = create_transaction(
                    workspace, actor=actor, transaction_type=TransactionType.transfer,
                    name=row.parsed_description or "Imported transfer", amount_cents=row.parsed_amount_cents,
                    transaction_date=row.parsed_date, transfer_from_account_id=transfer_from,
                    transfer_to_account_id=transfer_to, merchant_or_source=row.parsed_description,
                )
            else:
                transaction = create_transaction(
                    workspace, actor=actor, transaction_type=row_type,
                    name=row.parsed_description or "Imported transaction", amount_cents=row.parsed_amount_cents,
                    transaction_date=row.parsed_date, account_id=batch.account_id,
                    budget_category_id=category_id, merchant_or_source=row.parsed_description,
                )
            row.created_transaction_id = transaction.id
            row.status = CsvImportRowStatus.imported
        except TransactionValidationError as exc:
            row.parse_error = str(exc)
            row.status = CsvImportRowStatus.error

    batch.imported_count = sum(1 for r in rows if r.status == CsvImportRowStatus.imported)
    batch.skipped_count = sum(1 for r in rows if r.status == CsvImportRowStatus.skipped)
    batch.duplicate_count = sum(1 for r in rows if r.status == CsvImportRowStatus.duplicate)
    batch.error_count = sum(1 for r in rows if r.status == CsvImportRowStatus.error)
    batch.status = CsvImportStatus.completed
    batch.completed_at = _utcnow()

    audit_service.log_change(
        "CsvImportBatch", batch.id, "csv_import_completed",
        description=(
            f"CSV import '{batch.original_filename}' completed: "
            f"{batch.imported_count} imported, {batch.skipped_count} skipped, "
            f"{batch.duplicate_count} duplicates, {batch.error_count} errors."),
        user_id=getattr(actor, "id", None))
    SessionLocal.commit()

    return {
        "imported_count": batch.imported_count, "skipped_count": batch.skipped_count,
        "duplicate_count": batch.duplicate_count, "error_count": batch.error_count,
    }


def list_batches(workspace: FinancialWorkspace) -> list[CsvImportBatch]:
    return (
        SessionLocal.query(CsvImportBatch).filter_by(financial_workspace_id=workspace.id)
        .order_by(CsvImportBatch.created_at.desc()).all()
    )
