"""Fase 12 (Advanced Tools -- CSV Import) do SAES_Financial_Planning_
Master_Spec, 2026-08-07 -- fluxo completo: upload, detecção/mapeamento de
colunas, sugestão de tipo/categoria, duplicatas, revisão/confirmação,
relatório, auditoria.
"""
from __future__ import annotations

from datetime import date

import pytest


@pytest.fixture()
def workspace(db, staff_user):
    from app.crm_financial_models import FinancialClient
    from app.services import financial_planning_service as fp_svc

    fc = FinancialClient(full_name="Cliente CSV Import Teste")
    db.add(fc)
    db.commit()
    return fp_svc.enable_access(fc, actor=staff_user)


@pytest.fixture()
def account(db, workspace, staff_user):
    from app.financial_planning_models import AccountType
    from app.services import financial_accounts_service as accounts_svc

    return accounts_svc.create_account(
        workspace, actor=staff_user, account_name="Checking", account_type=AccountType.checking)


_SIMPLE_CSV = (
    "Date,Description,Amount\n"
    "08/05/2026,Paycheck,5000.00\n"
    "08/06/2026,Grocery Store,-120.50\n"
).encode("utf-8")

_DEBIT_CREDIT_CSV = (
    "Date,Description,Debit,Credit\n"
    "08/05/2026,Paycheck,,5000.00\n"
    "08/06/2026,Grocery Store,120.50,\n"
).encode("utf-8")


# --------------------------------------------------------------------------
# Upload (passos 1-3)
# --------------------------------------------------------------------------

def test_create_batch_rejects_non_csv_filename(db, workspace, account):
    from app.services import csv_import_service

    with pytest.raises(csv_import_service.CsvImportValidationError):
        csv_import_service.create_batch(
            workspace, actor=None, account=account, filename="statement.txt", content=_SIMPLE_CSV)


def test_create_batch_rejects_account_from_another_workspace(db, workspace, staff_user):
    from app.crm_financial_models import FinancialClient
    from app.financial_planning_models import AccountType
    from app.services import financial_accounts_service as accounts_svc
    from app.services import financial_planning_service as fp_svc
    from app.services import csv_import_service

    other_fc = FinancialClient(full_name="Outro Cliente CSV")
    db.add(other_fc)
    db.commit()
    other_ws = fp_svc.enable_access(other_fc, actor=staff_user)
    other_account = accounts_svc.create_account(
        other_ws, actor=staff_user, account_name="Other Checking", account_type=AccountType.checking)

    with pytest.raises(csv_import_service.CsvImportValidationError):
        csv_import_service.create_batch(
            workspace, actor=None, account=other_account, filename="statement.csv", content=_SIMPLE_CSV)


def test_create_batch_rejects_empty_file(db, workspace, account):
    from app.services import csv_import_service

    with pytest.raises(csv_import_service.CsvImportValidationError):
        csv_import_service.create_batch(
            workspace, actor=None, account=account, filename="statement.csv",
            content="Date,Description,Amount\n".encode("utf-8"))


def test_create_batch_rejects_too_many_rows(db, workspace, account):
    from app.services import csv_import_service

    big_csv = "Date,Description,Amount\n" + "\n".join(
        f"08/0{(i % 9) + 1}/2026,Row {i},1.00" for i in range(csv_import_service.MAX_ROWS + 1))
    with pytest.raises(csv_import_service.CsvImportValidationError):
        csv_import_service.create_batch(
            workspace, actor=None, account=account, filename="statement.csv", content=big_csv.encode("utf-8"))


def test_create_batch_detects_columns_and_stores_rows(db, workspace, account):
    from app.services import csv_import_service

    batch = csv_import_service.create_batch(
        workspace, actor=None, account=account, filename="statement.csv", content=_SIMPLE_CSV)
    assert batch.detected_columns == ["Date", "Description", "Amount"]
    rows = csv_import_service.list_rows(batch)
    assert len(rows) == 2
    assert rows[0].raw_data == {"Date": "08/05/2026", "Description": "Paycheck", "Amount": "5000.00"}


# --------------------------------------------------------------------------
# Mapeamento (passo 4) e processamento (passos 6-8)
# --------------------------------------------------------------------------

def test_set_column_mapping_requires_date_and_description(db, workspace, account):
    from app.services import csv_import_service

    batch = csv_import_service.create_batch(
        workspace, actor=None, account=account, filename="statement.csv", content=_SIMPLE_CSV)
    with pytest.raises(csv_import_service.CsvImportValidationError):
        csv_import_service.set_column_mapping(workspace, batch, date_col="", description_col="Description", amount_col="Amount")


def test_set_column_mapping_requires_amount_or_debit_credit(db, workspace, account):
    from app.services import csv_import_service

    batch = csv_import_service.create_batch(
        workspace, actor=None, account=account, filename="statement.csv", content=_SIMPLE_CSV)
    with pytest.raises(csv_import_service.CsvImportValidationError):
        csv_import_service.set_column_mapping(workspace, batch, date_col="Date", description_col="Description")


def test_set_column_mapping_rejects_both_amount_and_debit_credit(db, workspace, account):
    from app.services import csv_import_service

    batch = csv_import_service.create_batch(
        workspace, actor=None, account=account, filename="statement.csv", content=_DEBIT_CREDIT_CSV)
    with pytest.raises(csv_import_service.CsvImportValidationError):
        csv_import_service.set_column_mapping(
            workspace, batch, date_col="Date", description_col="Description",
            amount_col="Debit", debit_col="Debit", credit_col="Credit")


def test_single_amount_column_classifies_by_sign(db, workspace, account):
    from app.financial_planning_models import TransactionType
    from app.services import csv_import_service

    batch = csv_import_service.create_batch(
        workspace, actor=None, account=account, filename="statement.csv", content=_SIMPLE_CSV)
    csv_import_service.set_column_mapping(
        workspace, batch, date_col="Date", description_col="Description", amount_col="Amount")

    rows = csv_import_service.list_rows(batch)
    assert rows[0].suggested_type == TransactionType.income
    assert rows[0].parsed_amount_cents == 500000
    assert rows[0].parsed_date == date(2026, 8, 5)
    assert rows[1].suggested_type == TransactionType.expense
    assert rows[1].parsed_amount_cents == 12050


def test_debit_credit_columns_classify_correctly(db, workspace, account):
    from app.financial_planning_models import TransactionType
    from app.services import csv_import_service

    batch = csv_import_service.create_batch(
        workspace, actor=None, account=account, filename="statement.csv", content=_DEBIT_CREDIT_CSV)
    csv_import_service.set_column_mapping(
        workspace, batch, date_col="Date", description_col="Description", debit_col="Debit", credit_col="Credit")

    rows = csv_import_service.list_rows(batch)
    assert rows[0].suggested_type == TransactionType.income
    assert rows[0].parsed_amount_cents == 500000
    assert rows[1].suggested_type == TransactionType.expense
    assert rows[1].parsed_amount_cents == 12050


def test_unparseable_row_marked_as_error(db, workspace, account):
    from app.financial_planning_models import CsvImportRowStatus
    from app.services import csv_import_service

    bad_csv = "Date,Description,Amount\nnot-a-date,Mystery,not-a-number\n".encode("utf-8")
    batch = csv_import_service.create_batch(
        workspace, actor=None, account=account, filename="statement.csv", content=bad_csv)
    csv_import_service.set_column_mapping(
        workspace, batch, date_col="Date", description_col="Description", amount_col="Amount")

    rows = csv_import_service.list_rows(batch)
    assert rows[0].status == CsvImportRowStatus.error
    assert rows[0].parse_error


def test_duplicate_detection_flags_matching_existing_transaction(db, workspace, account):
    from app.financial_planning_models import CsvImportRowStatus, TransactionType
    from app.services import csv_import_service
    from app.services import financial_transactions_service as tx_svc

    tx_svc.create_transaction(
        workspace, actor=None, transaction_type=TransactionType.income, name="Existing paycheck",
        amount_cents=500000, transaction_date=date(2026, 8, 5), account_id=account.id)

    batch = csv_import_service.create_batch(
        workspace, actor=None, account=account, filename="statement.csv", content=_SIMPLE_CSV)
    csv_import_service.set_column_mapping(
        workspace, batch, date_col="Date", description_col="Description", amount_col="Amount")

    rows = csv_import_service.list_rows(batch)
    assert rows[0].status == CsvImportRowStatus.duplicate
    assert rows[1].status == CsvImportRowStatus.pending  # não bate com nada existente


def test_category_suggestion_reuses_past_transaction_category(db, workspace, account):
    from app.financial_planning_models import BudgetCategory, BudgetCategoryGroup, TransactionType
    from app.services import csv_import_service
    from app.services import financial_transactions_service as tx_svc

    cat = BudgetCategory(financial_workspace_id=workspace.id, name="Groceries", category_group=BudgetCategoryGroup.needs)
    db.add(cat)
    db.commit()
    tx_svc.create_transaction(
        workspace, actor=None, transaction_type=TransactionType.expense, name="Groceries",
        amount_cents=5000, transaction_date=date(2026, 7, 1), account_id=account.id,
        merchant_or_source="Grocery Store", budget_category_id=cat.id)

    batch = csv_import_service.create_batch(
        workspace, actor=None, account=account, filename="statement.csv", content=_SIMPLE_CSV)
    csv_import_service.set_column_mapping(
        workspace, batch, date_col="Date", description_col="Description", amount_col="Amount")

    rows = csv_import_service.list_rows(batch)
    assert rows[1].parsed_description == "Grocery Store"
    assert rows[1].suggested_category_id == cat.id


# --------------------------------------------------------------------------
# Confirmação (passos 9-12)
# --------------------------------------------------------------------------

def test_confirm_import_creates_transactions_for_selected_rows(db, workspace, account):
    from app.financial_planning_models import CsvImportRowStatus, FinancialTransaction
    from app.services import csv_import_service

    batch = csv_import_service.create_batch(
        workspace, actor=None, account=account, filename="statement.csv", content=_SIMPLE_CSV)
    csv_import_service.set_column_mapping(
        workspace, batch, date_col="Date", description_col="Description", amount_col="Amount")
    rows = csv_import_service.list_rows(batch)

    selections = {r.id: {"import": True, "type": r.suggested_type, "category_id": None,
                          "transfer_counterpart_account_id": None} for r in rows}
    report = csv_import_service.confirm_import(workspace, batch, actor=None, selections=selections)

    assert report["imported_count"] == 2
    assert report["error_count"] == 0
    created = db.query(FinancialTransaction).filter_by(financial_workspace_id=workspace.id).all()
    assert len(created) == 2
    for row in csv_import_service.list_rows(batch):
        assert row.status == CsvImportRowStatus.imported
        assert row.created_transaction_id is not None


def test_confirm_import_skips_unselected_rows(db, workspace, account):
    from app.financial_planning_models import CsvImportRowStatus
    from app.services import csv_import_service

    batch = csv_import_service.create_batch(
        workspace, actor=None, account=account, filename="statement.csv", content=_SIMPLE_CSV)
    csv_import_service.set_column_mapping(
        workspace, batch, date_col="Date", description_col="Description", amount_col="Amount")
    rows = csv_import_service.list_rows(batch)

    selections = {rows[0].id: {"import": True, "type": rows[0].suggested_type},
                  rows[1].id: {"import": False}}
    report = csv_import_service.confirm_import(workspace, batch, actor=None, selections=selections)

    assert report["imported_count"] == 1
    assert report["skipped_count"] == 1


def test_confirm_import_duplicate_row_can_be_force_imported(db, workspace, account):
    from app.services import csv_import_service
    from app.services import financial_transactions_service as tx_svc
    from app.financial_planning_models import TransactionType

    tx_svc.create_transaction(
        workspace, actor=None, transaction_type=TransactionType.income, name="Existing paycheck",
        amount_cents=500000, transaction_date=date(2026, 8, 5), account_id=account.id)

    batch = csv_import_service.create_batch(
        workspace, actor=None, account=account, filename="statement.csv", content=_SIMPLE_CSV)
    csv_import_service.set_column_mapping(
        workspace, batch, date_col="Date", description_col="Description", amount_col="Amount")
    rows = csv_import_service.list_rows(batch)
    duplicate_row = rows[0]
    assert duplicate_row.status.value == "duplicate"

    selections = {duplicate_row.id: {"import": True, "type": duplicate_row.suggested_type},
                  rows[1].id: {"import": False}}
    report = csv_import_service.confirm_import(workspace, batch, actor=None, selections=selections)
    assert report["imported_count"] == 1  # cliente escolheu importar mesmo assim


def test_confirm_import_transfer_requires_counterpart_account(db, workspace, account):
    from app.financial_planning_models import CsvImportRowStatus, TransactionType
    from app.services import csv_import_service

    batch = csv_import_service.create_batch(
        workspace, actor=None, account=account, filename="statement.csv", content=_SIMPLE_CSV)
    csv_import_service.set_column_mapping(
        workspace, batch, date_col="Date", description_col="Description", amount_col="Amount")
    rows = csv_import_service.list_rows(batch)

    selections = {rows[0].id: {"import": True, "type": TransactionType.transfer, "transfer_counterpart_account_id": None},
                  rows[1].id: {"import": False}}
    report = csv_import_service.confirm_import(workspace, batch, actor=None, selections=selections)
    assert report["error_count"] == 1
    assert csv_import_service.list_rows(batch)[0].status == CsvImportRowStatus.error


def test_confirm_import_transfer_with_counterpart_creates_transfer(db, workspace, account, staff_user):
    from app.financial_planning_models import AccountType, TransactionType
    from app.services import csv_import_service
    from app.services import financial_accounts_service as accounts_svc

    savings = accounts_svc.create_account(
        workspace, actor=staff_user, account_name="Savings", account_type=AccountType.savings)

    batch = csv_import_service.create_batch(
        workspace, actor=None, account=account, filename="statement.csv", content=_SIMPLE_CSV)
    csv_import_service.set_column_mapping(
        workspace, batch, date_col="Date", description_col="Description", amount_col="Amount")
    rows = csv_import_service.list_rows(batch)
    # rows[1] é expense (saiu da conta) -- vira transfer_from=account, transfer_to=savings
    selections = {rows[0].id: {"import": False},
                  rows[1].id: {"import": True, "type": TransactionType.transfer,
                               "transfer_counterpart_account_id": savings.id}}
    report = csv_import_service.confirm_import(workspace, batch, actor=None, selections=selections)
    assert report["imported_count"] == 1


def test_confirm_import_writes_audit_log(db, workspace, account, staff_user):
    from app.crm_models import AuditLog
    from app.services import csv_import_service

    batch = csv_import_service.create_batch(
        workspace, actor=None, account=account, filename="statement.csv", content=_SIMPLE_CSV)
    csv_import_service.set_column_mapping(
        workspace, batch, date_col="Date", description_col="Description", amount_col="Amount")
    csv_import_service.confirm_import(workspace, batch, actor=staff_user, selections={})

    entry = db.query(AuditLog).filter_by(entity_type="CsvImportBatch", entity_id=batch.id).first()
    assert entry is not None


def test_confirm_import_twice_raises(db, workspace, account):
    from app.services import csv_import_service

    batch = csv_import_service.create_batch(
        workspace, actor=None, account=account, filename="statement.csv", content=_SIMPLE_CSV)
    csv_import_service.set_column_mapping(
        workspace, batch, date_col="Date", description_col="Description", amount_col="Amount")
    csv_import_service.confirm_import(workspace, batch, actor=None, selections={})

    with pytest.raises(csv_import_service.CsvImportValidationError):
        csv_import_service.confirm_import(workspace, batch, actor=None, selections={})


# --------------------------------------------------------------------------
# Integração: rota real, cliente logado
# --------------------------------------------------------------------------

@pytest.fixture()
def financial_client_login(client, db, staff_user):
    from app.crm_financial_models import FinancialClient
    from app.models import User
    from app.services import financial_planning_service as fp_svc

    user = User(email="csvclient@example.com", password_hash="x", is_staff=False, email_verified=True)
    db.add(user)
    db.commit()
    fc = FinancialClient(full_name="Cliente CSV HTTP", user_id=user.id)
    db.add(fc)
    db.commit()
    fp_svc.enable_access(fc, actor=staff_user)

    user_id = user.id
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True
    return client


def test_csv_import_full_flow_via_routes(financial_client_login, db):
    from app.crm_financial_models import FinancialClient
    from app.financial_planning_models import AccountType, FinancialTransaction
    from app.services import financial_accounts_service as accounts_svc

    fc = db.query(FinancialClient).filter_by(full_name="Cliente CSV HTTP").first()
    account = accounts_svc.create_account(
        fc.workspace, actor=None, account_name="Checking", account_type=AccountType.checking)
    account_id = account.id

    resp = financial_client_login.get("/meu-plano-financeiro/workspace/importar-csv")
    assert resp.status_code == 200

    import io as _io
    resp = financial_client_login.post(
        "/meu-plano-financeiro/workspace/importar-csv/novo",
        data={"account_id": str(account_id), "file": (_io.BytesIO(_SIMPLE_CSV), "statement.csv")},
        content_type="multipart/form-data", follow_redirects=True)
    assert resp.status_code == 200
    assert b"Map Columns" in resp.data or b"map" in resp.data.lower()

    from app.financial_planning_models import CsvImportBatch
    batch = db.query(CsvImportBatch).filter_by(account_id=account_id).first()
    batch_id = batch.id

    resp = financial_client_login.post(
        f"/meu-plano-financeiro/workspace/importar-csv/{batch_id}/mapear",
        data={"date_col": "Date", "description_col": "Description", "amount_col": "Amount"},
        follow_redirects=True)
    assert resp.status_code == 200

    from app.services import csv_import_service
    batch = db.get(CsvImportBatch, batch_id)
    rows = csv_import_service.list_rows(batch)
    form_data = {}
    for row in rows:
        form_data[f"row_{row.id}_import"] = "1"
        form_data[f"row_{row.id}_type"] = row.suggested_type.value

    resp = financial_client_login.post(
        f"/meu-plano-financeiro/workspace/importar-csv/{batch_id}/confirmar",
        data=form_data, follow_redirects=True)
    assert resp.status_code == 200
    assert b"Import Report" in resp.data

    created = db.query(FinancialTransaction).filter_by(financial_workspace_id=fc.workspace.id).all()
    assert len(created) == 2


def test_csv_import_batch_from_another_workspace_is_404(financial_client_login, db, staff_user):
    from app.crm_financial_models import FinancialClient
    from app.financial_planning_models import AccountType
    from app.models import User
    from app.services import financial_accounts_service as accounts_svc
    from app.services import financial_planning_service as fp_svc
    from app.services import csv_import_service

    staff_user = db.query(User).filter_by(email="staff@example.com").first()
    other_fc = FinancialClient(full_name="Outro Cliente CSV Rota")
    db.add(other_fc)
    db.commit()
    other_ws = fp_svc.enable_access(other_fc, actor=staff_user)
    other_account = accounts_svc.create_account(
        other_ws, actor=staff_user, account_name="Other Checking", account_type=AccountType.checking)
    other_batch = csv_import_service.create_batch(
        other_ws, actor=None, account=other_account, filename="statement.csv", content=_SIMPLE_CSV)

    resp = financial_client_login.get(f"/meu-plano-financeiro/workspace/importar-csv/{other_batch.id}/revisar")
    assert resp.status_code == 404
