"""Fase 2 (Modelo de Dados Central) do SAES_Financial_Planning_Master_Spec,
2026-08-07 -- accounts, transações (com as regras de validação do
documento: transferência nunca conta como renda/despesa, exige contas de
origem/destino distintas, e toda conta/categoria referenciada precisa
pertencer ao MESMO workspace), categorias, e o seed de categorias
padrão que `enable_access` (Fase 1) passou a fazer.
"""
from __future__ import annotations

from datetime import date

import pytest


@pytest.fixture()
def workspace(db, staff_user):
    """FinancialClient + FinancialWorkspace habilitado, via o mesmo
    fluxo real de app/services/financial_planning_service.py::
    enable_access (não cria a linha à mão) -- assim os testes de Fase 2
    também cobrem, de brinde, que o seed de categorias padrão da Fase 1
    realmente roda."""
    from app.crm_financial_models import FinancialClient
    from app.services import financial_planning_service as fp_svc

    fc = FinancialClient(full_name="Cliente Fase 2 Teste")
    db.add(fc)
    db.commit()
    return fp_svc.enable_access(fc, actor=staff_user)


# --------------------------------------------------------------------------
# enable_access -- seed de categorias padrão (Fase 1 estendida na Fase 2)
# --------------------------------------------------------------------------

def test_enable_access_seeds_default_categories(db, workspace):
    from app.financial_planning_models import BudgetCategory

    categories = db.query(BudgetCategory).filter_by(financial_workspace_id=workspace.id).all()
    assert len(categories) == len(fp_default_categories())
    assert {c.name for c in categories} >= {"Housing", "Savings", "Emergency Fund"}


def fp_default_categories():
    from app.services.financial_planning_service import _DEFAULT_CATEGORIES
    return _DEFAULT_CATEGORIES


# --------------------------------------------------------------------------
# Unitário: app/services/financial_accounts_service.py
# --------------------------------------------------------------------------

def test_create_and_list_accounts(db, staff_user, workspace):
    from app.financial_planning_models import AccountType
    from app.services import financial_accounts_service as accounts_svc

    accounts_svc.create_account(
        workspace, actor=staff_user, account_name="Chase Checking", account_type=AccountType.checking,
        current_balance_cents=150000)
    accounts_svc.create_account(
        workspace, actor=staff_user, account_name="Ally Savings", account_type=AccountType.savings,
        current_balance_cents=500000)

    accounts = accounts_svc.list_accounts(workspace)
    assert len(accounts) == 2
    assert {a.account_name for a in accounts} == {"Chase Checking", "Ally Savings"}


def test_soft_delete_account_hides_from_default_listing_but_keeps_row(db, staff_user, workspace):
    from app.financial_planning_models import Account, AccountType
    from app.services import financial_accounts_service as accounts_svc

    account = accounts_svc.create_account(
        workspace, actor=staff_user, account_name="Cash", account_type=AccountType.cash)
    account_id = account.id

    accounts_svc.soft_delete_account(account)

    assert account_id not in [a.id for a in accounts_svc.list_accounts(workspace)]
    still_there = db.get(Account, account_id)
    assert still_there is not None and still_there.deleted_at is not None


# --------------------------------------------------------------------------
# Unitário: app/services/financial_transactions_service.py -- regras
# --------------------------------------------------------------------------

def test_transfer_requires_two_distinct_accounts(db, staff_user, workspace):
    from app.financial_planning_models import AccountType, TransactionType
    from app.services import financial_accounts_service as accounts_svc
    from app.services import financial_transactions_service as tx_svc

    checking = accounts_svc.create_account(
        workspace, actor=staff_user, account_name="Checking", account_type=AccountType.checking)

    with pytest.raises(tx_svc.TransactionValidationError):
        tx_svc.create_transaction(
            workspace, actor=staff_user, transaction_type=TransactionType.transfer,
            name="Move to savings", amount_cents=10000, transaction_date=date.today(),
            transfer_from_account_id=checking.id, transfer_to_account_id=checking.id)

    with pytest.raises(tx_svc.TransactionValidationError):
        tx_svc.create_transaction(
            workspace, actor=staff_user, transaction_type=TransactionType.transfer,
            name="Move to savings", amount_cents=10000, transaction_date=date.today(),
            transfer_from_account_id=checking.id, transfer_to_account_id=None)


def test_income_and_expense_require_an_account(db, staff_user, workspace):
    from app.financial_planning_models import TransactionType
    from app.services import financial_transactions_service as tx_svc

    with pytest.raises(tx_svc.TransactionValidationError):
        tx_svc.create_transaction(
            workspace, actor=staff_user, transaction_type=TransactionType.income,
            name="Paycheck", amount_cents=200000, transaction_date=date.today())


def test_transaction_rejects_account_from_a_different_workspace(db, staff_user):
    from app.crm_financial_models import FinancialClient
    from app.financial_planning_models import AccountType, TransactionType
    from app.services import financial_accounts_service as accounts_svc
    from app.services import financial_planning_service as fp_svc
    from app.services import financial_transactions_service as tx_svc

    fc_a = FinancialClient(full_name="Cliente A")
    fc_b = FinancialClient(full_name="Cliente B")
    db.add_all([fc_a, fc_b])
    db.commit()
    workspace_a = fp_svc.enable_access(fc_a, actor=staff_user)
    workspace_b = fp_svc.enable_access(fc_b, actor=staff_user)

    account_in_b = accounts_svc.create_account(
        workspace_b, actor=staff_user, account_name="B's checking", account_type=AccountType.checking)

    with pytest.raises(tx_svc.TransactionValidationError):
        tx_svc.create_transaction(
            workspace_a, actor=staff_user, transaction_type=TransactionType.income,
            name="Paycheck", amount_cents=200000, transaction_date=date.today(),
            account_id=account_in_b.id)


def test_transfers_are_excluded_from_net_cash_flow(db, staff_user, workspace):
    from app.financial_planning_models import AccountType, TransactionType
    from app.services import financial_accounts_service as accounts_svc
    from app.services import financial_transactions_service as tx_svc

    checking = accounts_svc.create_account(
        workspace, actor=staff_user, account_name="Checking", account_type=AccountType.checking)
    savings = accounts_svc.create_account(
        workspace, actor=staff_user, account_name="Savings", account_type=AccountType.savings)

    today = date.today()
    tx_svc.create_transaction(
        workspace, actor=staff_user, transaction_type=TransactionType.income,
        name="Paycheck", amount_cents=300000, transaction_date=today, account_id=checking.id)
    tx_svc.create_transaction(
        workspace, actor=staff_user, transaction_type=TransactionType.expense,
        name="Rent", amount_cents=120000, transaction_date=today, account_id=checking.id)
    tx_svc.create_transaction(
        workspace, actor=staff_user, transaction_type=TransactionType.transfer,
        name="To savings", amount_cents=50000, transaction_date=today,
        transfer_from_account_id=checking.id, transfer_to_account_id=savings.id)

    net = tx_svc.net_cash_flow_cents(workspace, start=today, end=today)
    assert net == 300000 - 120000, "a transferência não pode entrar na conta de fluxo de caixa"


def test_soft_deleted_transaction_excluded_from_listing(db, staff_user, workspace):
    from app.financial_planning_models import AccountType, TransactionType
    from app.services import financial_accounts_service as accounts_svc
    from app.services import financial_transactions_service as tx_svc

    checking = accounts_svc.create_account(
        workspace, actor=staff_user, account_name="Checking", account_type=AccountType.checking)
    tx = tx_svc.create_transaction(
        workspace, actor=staff_user, transaction_type=TransactionType.expense,
        name="Groceries", amount_cents=8000, transaction_date=date.today(), account_id=checking.id)

    tx_svc.soft_delete_transaction(tx)

    assert tx.id not in [t.id for t in tx_svc.list_transactions(workspace)]


# --------------------------------------------------------------------------
# Integração: rotas reais, cliente logado (não staff)
# --------------------------------------------------------------------------

@pytest.fixture()
def financial_client_login(client, db, staff_user):
    """Loga como o CLIENTE dono de um FinancialClient com o módulo
    self-service já habilitado -- não confundir com `logged_in_client`
    (conftest.py), que loga como staff."""
    from app.crm_financial_models import FinancialClient
    from app.models import User
    from app.services import financial_planning_service as fp_svc

    user = User(email="finclient@example.com", password_hash="x", is_staff=False, email_verified=True)
    db.add(user)
    db.commit()

    fc = FinancialClient(full_name="Cliente HTTP Teste", user_id=user.id)
    db.add(fc)
    db.commit()
    fp_svc.enable_access(fc, actor=staff_user)

    user_id = user.id
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True
    return client


def _http_financial_client(db):
    from app.crm_financial_models import FinancialClient
    return db.query(FinancialClient).filter_by(full_name="Cliente HTTP Teste").first()


def test_client_can_view_workspace(financial_client_login, db):
    resp = financial_client_login.get("/meu-plano-financeiro/workspace/")
    assert resp.status_code == 200
    assert b"Financial Workspace" in resp.data


def test_client_without_enabled_access_is_redirected(client, db, staff_user):
    """Cliente sem `financial_planning_enabled` (nunca habilitado, ou
    desabilitado depois) não pode ver a página -- redireciona com
    mensagem, sem erro cru."""
    from app.crm_financial_models import FinancialClient
    from app.models import User

    user = User(email="nofinance@example.com", password_hash="x", is_staff=False, email_verified=True)
    db.add(user)
    db.commit()
    fc = FinancialClient(full_name="Cliente Sem Acesso", user_id=user.id)
    db.add(fc)
    db.commit()

    user_id = user.id
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True

    resp = client.get("/meu-plano-financeiro/workspace/", follow_redirects=True)
    assert resp.status_code == 200
    assert b"not available" in resp.data


def test_client_can_add_account_via_route(financial_client_login, db):
    from app.financial_planning_models import Account

    resp = financial_client_login.post(
        "/meu-plano-financeiro/workspace/contas/nova",
        data={"account_name": "Chase Checking", "account_type": "checking", "current_balance": "1500.50"},
        follow_redirects=True)
    assert resp.status_code == 200

    fc = _http_financial_client(db)
    accounts = db.query(Account).filter_by(financial_workspace_id=fc.workspace.id).all()
    assert len(accounts) == 1
    assert accounts[0].account_name == "Chase Checking"
    assert accounts[0].current_balance_cents == 150050


def test_client_can_add_transaction_via_route(financial_client_login, db):
    from app.financial_planning_models import Account, FinancialTransaction

    financial_client_login.post(
        "/meu-plano-financeiro/workspace/contas/nova",
        data={"account_name": "Checking", "account_type": "checking"}, follow_redirects=True)

    fc = _http_financial_client(db)
    account = db.query(Account).filter_by(financial_workspace_id=fc.workspace.id).first()
    account_id = account.id

    resp = financial_client_login.post(
        "/meu-plano-financeiro/workspace/transacoes/nova",
        data={
            "transaction_type": "expense", "name": "Groceries", "amount": "82.35",
            "transaction_date": date.today().isoformat(), "account_id": str(account_id),
        },
        follow_redirects=True)
    assert resp.status_code == 200

    fc = _http_financial_client(db)
    transactions = db.query(FinancialTransaction).filter_by(financial_workspace_id=fc.workspace.id).all()
    assert len(transactions) == 1
    assert transactions[0].amount_cents == 8235


def test_client_invalid_transfer_via_route_shows_error_not_crash(financial_client_login, db):
    resp = financial_client_login.post(
        "/meu-plano-financeiro/workspace/transacoes/nova",
        data={
            "transaction_type": "transfer", "name": "Bad transfer", "amount": "10.00",
            "transaction_date": date.today().isoformat(),
        },
        follow_redirects=True)
    assert resp.status_code == 200
    assert b"source and a destination account" in resp.data
