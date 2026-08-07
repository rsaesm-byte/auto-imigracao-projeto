"""Fase 9 (Net Worth) do SAES_Financial_Planning_Master_Spec, 2026-08-07 --
saldo histórico de conta, métricas de patrimônio líquido (assets -
passivos ativos/inadimplentes), e o histórico reconstruído pro gráfico.
"""
from __future__ import annotations

from datetime import date

import pytest


@pytest.fixture()
def workspace(db, staff_user):
    from app.crm_financial_models import FinancialClient
    from app.services import financial_planning_service as fp_svc

    fc = FinancialClient(full_name="Cliente Net Worth Teste")
    db.add(fc)
    db.commit()
    return fp_svc.enable_access(fc, actor=staff_user)


@pytest.fixture()
def account(db, workspace, staff_user):
    from app.financial_planning_models import AccountType
    from app.services import financial_accounts_service as accounts_svc

    return accounts_svc.create_account(
        workspace, actor=staff_user, account_name="Checking", account_type=AccountType.checking,
        current_balance_cents=500000)


# --------------------------------------------------------------------------
# Patrimônio atual
# --------------------------------------------------------------------------

def test_current_net_worth_assets_only_without_debts(db, workspace, account):
    from app.services import net_worth_service

    result = net_worth_service.current_net_worth(workspace)
    assert result == {"assets_cents": 500000, "liabilities_cents": 0, "net_worth_cents": 500000}


def test_current_net_worth_subtracts_active_debts(db, workspace, account):
    from app.services import debts_service, net_worth_service

    debts_service.create_debt(workspace, actor=None, debt_name="Visa", current_balance_cents=150000)
    result = net_worth_service.current_net_worth(workspace)
    assert result == {"assets_cents": 500000, "liabilities_cents": 150000, "net_worth_cents": 350000}


def test_current_net_worth_excludes_planned_debts(db, workspace, account):
    from app.financial_planning_models import DebtStatus
    from app.services import debts_service, net_worth_service

    debt = debts_service.create_debt(workspace, actor=None, debt_name="Future mortgage", current_balance_cents=200000)
    debt.status = DebtStatus.planned
    db.commit()

    result = net_worth_service.current_net_worth(workspace)
    assert result["liabilities_cents"] == 0
    assert result["net_worth_cents"] == 500000


def test_current_net_worth_excludes_paid_off_debts(db, workspace, account):
    from app.services import debts_service, net_worth_service

    debt = debts_service.create_debt(workspace, actor=None, debt_name="Old card", current_balance_cents=10000)
    debts_service.record_payment(debt, amount_cents=10000, payment_date=date(2026, 8, 1))

    result = net_worth_service.current_net_worth(workspace)
    assert result["liabilities_cents"] == 0


def test_current_net_worth_excludes_account_not_marked_for_net_worth(db, workspace, staff_user):
    from app.financial_planning_models import AccountType
    from app.services import financial_accounts_service as accounts_svc
    from app.services import net_worth_service

    accounts_svc.create_account(
        workspace, actor=staff_user, account_name="Escrow (excluded)", account_type=AccountType.other_bank_account,
        current_balance_cents=999999, include_in_net_worth=False)

    result = net_worth_service.current_net_worth(workspace)
    assert result["assets_cents"] == 0


# --------------------------------------------------------------------------
# Snapshots
# --------------------------------------------------------------------------

def test_record_snapshot_creates_row(db, workspace, account):
    from app.financial_planning_models import SnapshotSource
    from app.services import net_worth_service

    snap = net_worth_service.record_snapshot(
        account, balance_cents=500000, snapshot_date=date(2026, 7, 1), source=SnapshotSource.manual)
    assert snap.balance_cents == 500000
    assert snap.source == SnapshotSource.manual


def test_record_snapshot_same_day_upserts_not_duplicates(db, workspace, account):
    from app.financial_planning_models import AccountBalanceSnapshot
    from app.services import net_worth_service

    net_worth_service.record_snapshot(account, balance_cents=400000, snapshot_date=date(2026, 7, 1))
    net_worth_service.record_snapshot(account, balance_cents=420000, snapshot_date=date(2026, 7, 1))

    rows = db.query(AccountBalanceSnapshot).filter_by(account_id=account.id).all()
    assert len(rows) == 1
    assert rows[0].balance_cents == 420000


def test_list_snapshots_orders_newest_first(db, workspace, account):
    from app.services import net_worth_service

    net_worth_service.record_snapshot(account, balance_cents=100000, snapshot_date=date(2026, 5, 1))
    net_worth_service.record_snapshot(account, balance_cents=200000, snapshot_date=date(2026, 6, 1))
    net_worth_service.record_snapshot(account, balance_cents=300000, snapshot_date=date(2026, 7, 1))

    snaps = net_worth_service.list_snapshots(account)
    assert [s.balance_cents for s in snaps] == [300000, 200000, 100000]


def test_snapshot_month_close_snapshots_every_active_account(db, workspace, staff_user, account):
    from app.financial_planning_models import AccountBalanceSnapshot, AccountType, SnapshotSource
    from app.services import financial_accounts_service as accounts_svc
    from app.services import net_worth_service

    second = accounts_svc.create_account(
        workspace, actor=staff_user, account_name="Savings", account_type=AccountType.savings,
        current_balance_cents=100000)

    net_worth_service.snapshot_month_close(workspace, snapshot_date=date(2026, 7, 31))

    rows = db.query(AccountBalanceSnapshot).filter_by(snapshot_date=date(2026, 7, 31)).all()
    assert {r.account_id: r.balance_cents for r in rows} == {account.id: 500000, second.id: 100000}
    assert all(r.source == SnapshotSource.month_close for r in rows)


def test_snapshot_month_close_skips_deleted_accounts(db, workspace, staff_user, account):
    from app.financial_planning_models import AccountBalanceSnapshot
    from app.services import financial_accounts_service as accounts_svc
    from app.services import net_worth_service

    accounts_svc.soft_delete_account(account)
    net_worth_service.snapshot_month_close(workspace, snapshot_date=date(2026, 7, 31))

    rows = db.query(AccountBalanceSnapshot).filter_by(account_id=account.id).all()
    assert rows == []


def test_close_budget_period_triggers_month_close_snapshot(db, workspace, staff_user, account):
    from app.financial_planning_models import AccountBalanceSnapshot, SnapshotSource
    from app.services import budget_service

    period = budget_service.get_or_create_current_period(workspace, today=date(2026, 7, 15))
    budget_service.close_period(workspace, period, actor=staff_user)

    snap = db.query(AccountBalanceSnapshot).filter_by(
        account_id=account.id, snapshot_date=period.period_end).first()
    assert snap is not None
    assert snap.source == SnapshotSource.month_close
    assert snap.balance_cents == 500000


# --------------------------------------------------------------------------
# Histórico
# --------------------------------------------------------------------------

def test_net_worth_history_empty_without_snapshots(db, workspace, account):
    from app.services import net_worth_service

    assert net_worth_service.net_worth_history(workspace) == []


def test_net_worth_history_carries_forward_and_reconstructs_debt(db, workspace, account):
    """Um snapshot em maio ($400k), outro em julho ($500k, sem snapshot
    em junho -- deve carregar o valor de maio pra junho). Uma dívida com
    original_balance_cents e um pagamento em junho -- o saldo histórico
    de maio deve ser MAIOR que o de julho, refletindo o pagamento."""
    from app.services import debts_service, net_worth_service

    net_worth_service.record_snapshot(account, balance_cents=400000, snapshot_date=date(2026, 5, 1))
    net_worth_service.record_snapshot(account, balance_cents=500000, snapshot_date=date(2026, 7, 1))

    debt = debts_service.create_debt(
        workspace, actor=None, debt_name="Loan", current_balance_cents=100000, original_balance_cents=100000)
    debts_service.record_payment(debt, amount_cents=20000, payment_date=date(2026, 6, 15))
    assert debt.current_balance_cents == 80000

    history = net_worth_service.net_worth_history(workspace)
    by_date = {row["date"]: row for row in history}

    assert by_date[date(2026, 5, 1)]["assets_cents"] == 400000
    assert by_date[date(2026, 5, 1)]["liabilities_cents"] == 100000  # antes do pagamento de junho
    assert by_date[date(2026, 7, 1)]["assets_cents"] == 500000
    assert by_date[date(2026, 7, 1)]["liabilities_cents"] == 80000  # depois do pagamento
    assert by_date[date(2026, 7, 1)]["net_worth_cents"] == 420000


def test_net_worth_history_debt_without_payments_is_flat_at_current_balance(db, workspace, account):
    """Sem nenhum `DebtPayment` registrado, não tem como reconstruir um
    saldo diferente pro passado -- assume constante em `current_balance_
    cents` pra todo ponto do histórico (nunca inventa um número maior via
    `original_balance_cents`, que poderia divergir da verdade -- ver
    docstring de `_debt_balance_as_of`)."""
    from app.services import debts_service, net_worth_service

    net_worth_service.record_snapshot(account, balance_cents=500000, snapshot_date=date(2026, 5, 1))
    net_worth_service.record_snapshot(account, balance_cents=500000, snapshot_date=date(2026, 7, 1))
    debts_service.create_debt(
        workspace, actor=None, debt_name="No history", current_balance_cents=90000, original_balance_cents=150000)

    history = net_worth_service.net_worth_history(workspace)
    assert all(row["liabilities_cents"] == 90000 for row in history)


def test_net_worth_history_today_always_matches_current_balance(db, workspace, account):
    """Ancorado em `current_balance_cents`: a reconstrução de HOJE tem
    que bater exatamente com o saldo atual, mesmo quando o saldo foi
    ajustado sem um `DebtPayment` correspondente (ex.: dívida cadastrada
    já parcialmente paga) -- achado ao verificar ao vivo no Chrome com a
    dívida "Student Loan" da conta demo, que tem exatamente esse
    formato de dado."""
    from app.services import debts_service, net_worth_service

    net_worth_service.record_snapshot(account, balance_cents=500000, snapshot_date=date(2026, 8, 1))
    debts_service.create_debt(
        workspace, actor=None, debt_name="Student Loan", current_balance_cents=1200000,
        original_balance_cents=1500000)  # $3,000 "paid" sem nenhum DebtPayment de verdade

    history = net_worth_service.net_worth_history(workspace)
    assert history[0]["liabilities_cents"] == 1200000  # bate com current_balance_cents, não com original


# --------------------------------------------------------------------------
# Integração: rota real, cliente logado
# --------------------------------------------------------------------------

@pytest.fixture()
def financial_client_login(client, db, staff_user):
    from app.crm_financial_models import FinancialClient
    from app.models import User
    from app.services import financial_planning_service as fp_svc

    user = User(email="networthclient@example.com", password_hash="x", is_staff=False, email_verified=True)
    db.add(user)
    db.commit()
    fc = FinancialClient(full_name="Cliente Net Worth HTTP", user_id=user.id)
    db.add(fc)
    db.commit()
    fp_svc.enable_access(fc, actor=staff_user)

    user_id = user.id
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True
    return client


def test_net_worth_page_renders(financial_client_login):
    resp = financial_client_login.get("/meu-plano-financeiro/workspace/patrimonio")
    assert resp.status_code == 200
    assert b"Net Worth" in resp.data


def test_record_snapshot_via_route(financial_client_login, db):
    from app.crm_financial_models import FinancialClient
    from app.financial_planning_models import Account, AccountBalanceSnapshot, AccountType
    from app.services import financial_accounts_service as accounts_svc

    fc = db.query(FinancialClient).filter_by(full_name="Cliente Net Worth HTTP").first()
    account = accounts_svc.create_account(
        fc.workspace, actor=None, account_name="Checking", account_type=AccountType.checking)
    account_id = account.id

    resp = financial_client_login.post(
        "/meu-plano-financeiro/workspace/patrimonio/snapshot",
        data={"account_id": str(account_id), "balance": "1234.56", "snapshot_date": "2026-08-01"},
        follow_redirects=True)
    assert resp.status_code == 200
    assert b"Balance snapshot recorded" in resp.data

    snap = db.query(AccountBalanceSnapshot).filter_by(account_id=account_id).first()
    assert snap.balance_cents == 123456
