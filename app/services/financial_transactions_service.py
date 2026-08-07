"""Fase 2 do SAES_Financial_Planning_Master_Spec -- CRUD de
FinancialTransaction, com as 3 regras de negócio que o documento marca
como obrigatórias (§7): transferência nunca conta como renda/despesa;
transferência exige conta de origem e destino, e as duas têm que ser
diferentes; toda conta/categoria referenciada precisa pertencer ao MESMO
workspace de quem está lançando (isolamento de tenant reforçado aqui, no
service -- backend, não só UI, pedido explícito do documento)."""
from __future__ import annotations

from datetime import date, datetime, timezone

from app.crm_financial_models import FinancialWorkspace
from app.db import SessionLocal
from app.financial_planning_models import (Account, BudgetCategory, FinancialTransaction,
                                            PaymentMethodType, TransactionClassification,
                                            TransactionStatus, TransactionType)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TransactionValidationError(ValueError):
    """Levantado por `create_transaction`/`update_transaction` quando a
    combinação de campos viola uma regra do documento -- a rota deve
    pegar isto e mostrar a mensagem pro usuário, nunca deixar a
    transação inválida ser gravada."""


def _check_account_ownership(account_id: int | None, workspace_id: int) -> None:
    if account_id is None:
        return
    account = SessionLocal.get(Account, account_id)
    if account is None or account.financial_workspace_id != workspace_id:
        raise TransactionValidationError("Account does not belong to this workspace.")


def _check_category_ownership(category_id: int | None, workspace_id: int) -> None:
    if category_id is None:
        return
    category = SessionLocal.get(BudgetCategory, category_id)
    if category is None or category.financial_workspace_id != workspace_id:
        raise TransactionValidationError("Budget category does not belong to this workspace.")


def _validate_accounts_for_type(
    transaction_type: TransactionType, account_id: int | None,
    transfer_from_account_id: int | None, transfer_to_account_id: int | None,
) -> None:
    if transaction_type == TransactionType.transfer:
        if transfer_from_account_id is None or transfer_to_account_id is None:
            raise TransactionValidationError("Transfers require both a source and a destination account.")
        if transfer_from_account_id == transfer_to_account_id:
            raise TransactionValidationError("Transfer source and destination accounts must be different.")
    else:
        if account_id is None:
            raise TransactionValidationError("Income and expense transactions require an account.")
        if transfer_from_account_id is not None or transfer_to_account_id is not None:
            raise TransactionValidationError("Only transfers use source/destination accounts.")


def create_transaction(
    workspace: FinancialWorkspace, *, actor,
    transaction_type: TransactionType, name: str, amount_cents: int, transaction_date: date,
    account_id: int | None = None, transfer_from_account_id: int | None = None,
    transfer_to_account_id: int | None = None, budget_category_id: int | None = None,
    merchant_or_source: str | None = None, payment_method: PaymentMethodType | None = None,
    classification: TransactionClassification | None = None,
    status: TransactionStatus = TransactionStatus.completed, notes: str | None = None,
) -> FinancialTransaction:
    if amount_cents <= 0:
        raise TransactionValidationError("Amount must be greater than zero.")
    _validate_accounts_for_type(transaction_type, account_id, transfer_from_account_id, transfer_to_account_id)
    _check_account_ownership(account_id, workspace.id)
    _check_account_ownership(transfer_from_account_id, workspace.id)
    _check_account_ownership(transfer_to_account_id, workspace.id)
    _check_category_ownership(budget_category_id, workspace.id)
    if transaction_type == TransactionType.transfer and budget_category_id is not None:
        raise TransactionValidationError("Transfers do not count as income or expenses and cannot have a budget category.")

    transaction = FinancialTransaction(
        financial_workspace_id=workspace.id, transaction_type=transaction_type, name=name,
        amount_cents=amount_cents, transaction_date=transaction_date, account_id=account_id,
        transfer_from_account_id=transfer_from_account_id, transfer_to_account_id=transfer_to_account_id,
        budget_category_id=budget_category_id, merchant_or_source=merchant_or_source or None,
        payment_method=payment_method, classification=classification, status=status,
        notes=notes or None, created_by_id=getattr(actor, "id", None),
    )
    SessionLocal.add(transaction)
    SessionLocal.commit()
    return transaction


def list_transactions(
    workspace: FinancialWorkspace, *, include_deleted: bool = False, limit: int | None = None,
) -> list[FinancialTransaction]:
    query = SessionLocal.query(FinancialTransaction).filter_by(financial_workspace_id=workspace.id)
    if not include_deleted:
        query = query.filter(FinancialTransaction.deleted_at.is_(None))
    query = query.order_by(FinancialTransaction.transaction_date.desc(), FinancialTransaction.id.desc())
    if limit:
        query = query.limit(limit)
    return query.all()


def soft_delete_transaction(transaction: FinancialTransaction) -> None:
    transaction.deleted_at = _utcnow()
    SessionLocal.commit()


def net_cash_flow_cents(workspace: FinancialWorkspace, *, start: date, end: date) -> int:
    """`total_income - total_expenses` no período (§8 Monthly Summary) --
    só transações `completed` contam (`projected`/`scheduled` são
    planejamento, não fluxo de caixa real ainda; `cancelled` nunca
    contou). Transfers nunca entram na soma (regra do documento)."""
    rows = (
        SessionLocal.query(FinancialTransaction)
        .filter_by(financial_workspace_id=workspace.id, status=TransactionStatus.completed)
        .filter(FinancialTransaction.deleted_at.is_(None))
        .filter(FinancialTransaction.transaction_date >= start, FinancialTransaction.transaction_date <= end)
        .filter(FinancialTransaction.transaction_type != TransactionType.transfer)
        .all()
    )
    total = 0
    for t in rows:
        total += t.amount_cents if t.transaction_type == TransactionType.income else -t.amount_cents
    return total
