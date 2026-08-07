"""Fase 3 (Dashboard) do SAES_Financial_Planning_Master_Spec, 2026-08-07 --
KPIs e dados de gráfico calculados só com o que existe (Fase 1/2: contas
e transações). Cobre os cálculos (app/services/financial_dashboard_service.py)
e a rota real via HTTP.
"""
from __future__ import annotations

from datetime import date

import pytest


@pytest.fixture()
def workspace(db, staff_user):
    from app.crm_financial_models import FinancialClient
    from app.services import financial_planning_service as fp_svc

    fc = FinancialClient(full_name="Cliente Dashboard Teste")
    db.add(fc)
    db.commit()
    return fp_svc.enable_access(fc, actor=staff_user)


# --------------------------------------------------------------------------
# Unitário: app/services/financial_dashboard_service.py
# --------------------------------------------------------------------------

def test_kpis_with_no_data_are_zero_or_none(db, workspace):
    import app.services.financial_dashboard_service as dash_svc

    today = date.today()
    assert dash_svc.monthly_income_cents(workspace, start=today, end=today) == 0
    assert dash_svc.monthly_expenses_cents(workspace, start=today, end=today) == 0
    assert dash_svc.savings_rate(workspace, start=today, end=today) is None, (
        "sem renda, a taxa de poupança não pode ser calculada (nem 0%, nem erro)")
    assert dash_svc.total_cash_cents(workspace) == 0
    assert dash_svc.net_worth_cents(workspace) == 0
    assert dash_svc.spending_by_category(workspace, start=today, end=today) == []
    assert dash_svc.account_distribution(workspace) == []


def test_kpis_with_income_and_expenses(db, staff_user, workspace):
    import app.services.financial_dashboard_service as dash_svc
    from app.financial_planning_models import AccountType, TransactionType
    from app.services import financial_accounts_service as accounts_svc
    from app.services import financial_transactions_service as tx_svc

    checking = accounts_svc.create_account(
        workspace, actor=staff_user, account_name="Checking", account_type=AccountType.checking,
        current_balance_cents=200000)
    today = date.today()
    tx_svc.create_transaction(
        workspace, actor=staff_user, transaction_type=TransactionType.income,
        name="Paycheck", amount_cents=400000, transaction_date=today, account_id=checking.id)
    tx_svc.create_transaction(
        workspace, actor=staff_user, transaction_type=TransactionType.expense,
        name="Rent", amount_cents=150000, transaction_date=today, account_id=checking.id)

    assert dash_svc.monthly_income_cents(workspace, start=today, end=today) == 400000
    assert dash_svc.monthly_expenses_cents(workspace, start=today, end=today) == 150000
    rate = dash_svc.savings_rate(workspace, start=today, end=today)
    assert rate == pytest.approx((400000 - 150000) / 400000)
    assert dash_svc.total_cash_cents(workspace) == 200000
    assert dash_svc.net_worth_cents(workspace) == 200000


def test_spending_by_category_groups_and_sorts_descending(db, staff_user, workspace):
    import app.services.financial_dashboard_service as dash_svc
    from app.financial_planning_models import AccountType, BudgetCategory, TransactionType
    from app.services import financial_accounts_service as accounts_svc
    from app.services import financial_transactions_service as tx_svc

    checking = accounts_svc.create_account(
        workspace, actor=staff_user, account_name="Checking", account_type=AccountType.checking)
    groceries = db.query(BudgetCategory).filter_by(financial_workspace_id=workspace.id, name="Groceries").first()
    housing = db.query(BudgetCategory).filter_by(financial_workspace_id=workspace.id, name="Housing").first()
    today = date.today()

    tx_svc.create_transaction(
        workspace, actor=staff_user, transaction_type=TransactionType.expense, name="Rent",
        amount_cents=150000, transaction_date=today, account_id=checking.id, budget_category_id=housing.id)
    tx_svc.create_transaction(
        workspace, actor=staff_user, transaction_type=TransactionType.expense, name="Food",
        amount_cents=30000, transaction_date=today, account_id=checking.id, budget_category_id=groceries.id)
    tx_svc.create_transaction(
        workspace, actor=staff_user, transaction_type=TransactionType.expense, name="Misc",
        amount_cents=5000, transaction_date=today, account_id=checking.id)

    rows = dash_svc.spending_by_category(workspace, start=today, end=today)
    assert [r["label"] for r in rows] == ["Housing", "Groceries", "Uncategorized"]
    assert rows[0]["amount_cents"] == 150000


def test_needs_wants_savings_breakdown(db, staff_user, workspace):
    import app.services.financial_dashboard_service as dash_svc
    from app.financial_planning_models import (AccountType, TransactionClassification,
                                                 TransactionType)
    from app.services import financial_accounts_service as accounts_svc
    from app.services import financial_transactions_service as tx_svc

    checking = accounts_svc.create_account(
        workspace, actor=staff_user, account_name="Checking", account_type=AccountType.checking)
    today = date.today()

    tx_svc.create_transaction(
        workspace, actor=staff_user, transaction_type=TransactionType.expense, name="Rent",
        amount_cents=150000, transaction_date=today, account_id=checking.id,
        classification=TransactionClassification.needs)
    tx_svc.create_transaction(
        workspace, actor=staff_user, transaction_type=TransactionType.expense, name="Movies",
        amount_cents=4000, transaction_date=today, account_id=checking.id,
        classification=TransactionClassification.wants)
    tx_svc.create_transaction(
        workspace, actor=staff_user, transaction_type=TransactionType.expense, name="Misc",
        amount_cents=1000, transaction_date=today, account_id=checking.id)

    breakdown = dash_svc.needs_wants_savings_breakdown(workspace, start=today, end=today)
    assert breakdown["needs"] == 150000
    assert breakdown["wants"] == 4000
    assert breakdown["savings"] == 0
    assert breakdown["unclassified"] == 1000


def test_cash_flow_by_month_covers_requested_months_and_labels_them(db, workspace):
    import app.services.financial_dashboard_service as dash_svc

    rows = dash_svc.cash_flow_by_month(workspace, months=6, today=date(2026, 8, 15))
    assert len(rows) == 6
    assert rows[-1]["label"] == "Aug 2026"
    assert rows[0]["label"] == "Mar 2026"


def test_cash_flow_by_month_handles_year_boundary(db, workspace):
    import app.services.financial_dashboard_service as dash_svc

    rows = dash_svc.cash_flow_by_month(workspace, months=6, today=date(2026, 2, 10))
    labels = [r["label"] for r in rows]
    assert labels == ["Sep 2025", "Oct 2025", "Nov 2025", "Dec 2025", "Jan 2026", "Feb 2026"]


def test_transfers_never_appear_as_income_or_expense_in_kpis(db, staff_user, workspace):
    import app.services.financial_dashboard_service as dash_svc
    from app.financial_planning_models import AccountType, TransactionType
    from app.services import financial_accounts_service as accounts_svc
    from app.services import financial_transactions_service as tx_svc

    checking = accounts_svc.create_account(
        workspace, actor=staff_user, account_name="Checking", account_type=AccountType.checking)
    savings = accounts_svc.create_account(
        workspace, actor=staff_user, account_name="Savings", account_type=AccountType.savings)
    today = date.today()
    tx_svc.create_transaction(
        workspace, actor=staff_user, transaction_type=TransactionType.transfer, name="To savings",
        amount_cents=50000, transaction_date=today,
        transfer_from_account_id=checking.id, transfer_to_account_id=savings.id)

    assert dash_svc.monthly_income_cents(workspace, start=today, end=today) == 0
    assert dash_svc.monthly_expenses_cents(workspace, start=today, end=today) == 0


# --------------------------------------------------------------------------
# Integração: rota real, cliente logado
# --------------------------------------------------------------------------

def test_dashboard_route_renders_for_client_with_access(app, db, staff_user):
    from app.crm_financial_models import FinancialClient
    from app.models import User
    from app.services import financial_planning_service as fp_svc

    user = User(email="dashclient@example.com", password_hash="x", is_staff=False, email_verified=True)
    db.add(user)
    db.commit()
    fc = FinancialClient(full_name="Dashboard HTTP Client", user_id=user.id)
    db.add(fc)
    db.commit()
    fp_svc.enable_access(fc, actor=staff_user)
    user_id = user.id

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True

    resp = client.get("/meu-plano-financeiro/workspace/resumo")
    assert resp.status_code == 200
    assert b"Financial Overview" in resp.data
    assert b"Cash Flow" in resp.data
