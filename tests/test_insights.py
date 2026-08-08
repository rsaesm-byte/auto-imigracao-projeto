"""Fase 12 (Advanced Tools) do SAES_Financial_Planning_Master_Spec,
2026-08-07 -- Smart Insights (§13), Forecasts, Calculators.
"""
from __future__ import annotations

from datetime import date

import pytest


@pytest.fixture()
def workspace(db, staff_user):
    from app.crm_financial_models import FinancialClient
    from app.services import financial_planning_service as fp_svc

    fc = FinancialClient(full_name="Cliente Insights Teste")
    db.add(fc)
    db.commit()
    return fp_svc.enable_access(fc, actor=staff_user)


@pytest.fixture()
def account(db, workspace, staff_user):
    from app.financial_planning_models import AccountType
    from app.services import financial_accounts_service as accounts_svc

    return accounts_svc.create_account(
        workspace, actor=staff_user, account_name="Checking", account_type=AccountType.checking)


# --------------------------------------------------------------------------
# Smart Insights
# --------------------------------------------------------------------------

def test_category_movers_requires_spending_in_both_months(db, workspace, account):
    from app.financial_planning_models import TransactionType
    from app.services import financial_insights_service as insights_svc
    from app.services import financial_transactions_service as tx_svc

    # Só julho -- não deve aparecer (sem base de comparação em agosto).
    tx_svc.create_transaction(
        workspace, actor=None, transaction_type=TransactionType.expense, name="Dining",
        amount_cents=10000, transaction_date=date(2026, 7, 15), account_id=account.id)

    movers = insights_svc.category_movers(workspace, today=date(2026, 8, 15))
    assert movers == []


def test_category_movers_computes_pct_change(db, workspace, account):
    from app.financial_planning_models import BudgetCategory, BudgetCategoryGroup, TransactionType
    from app.services import financial_insights_service as insights_svc
    from app.services import financial_transactions_service as tx_svc

    cat = BudgetCategory(financial_workspace_id=workspace.id, name="Dining", category_group=BudgetCategoryGroup.wants)
    db.add(cat)
    db.commit()

    tx_svc.create_transaction(
        workspace, actor=None, transaction_type=TransactionType.expense, name="Dining July",
        amount_cents=10000, transaction_date=date(2026, 7, 10), account_id=account.id, budget_category_id=cat.id)
    tx_svc.create_transaction(
        workspace, actor=None, transaction_type=TransactionType.expense, name="Dining Aug",
        amount_cents=15000, transaction_date=date(2026, 8, 10), account_id=account.id, budget_category_id=cat.id)

    movers = insights_svc.category_movers(workspace, today=date(2026, 8, 15))
    assert len(movers) == 1
    assert movers[0]["label"] == "Dining"
    assert movers[0]["pct_change"] == pytest.approx(50.0)


def test_budget_alerts_flags_categories_over_threshold(db, workspace, account):
    from app.financial_planning_models import BudgetCategory, BudgetCategoryGroup, TransactionType
    from app.services import budget_service, financial_insights_service as insights_svc
    from app.services import financial_transactions_service as tx_svc

    cat = BudgetCategory(financial_workspace_id=workspace.id, name="Housing", category_group=BudgetCategoryGroup.needs)
    db.add(cat)
    db.commit()
    period = budget_service.get_or_create_current_period(workspace, today=date(2026, 8, 15))
    budget_service.set_allocation(period, cat, planned_amount_cents=100000)
    tx_svc.create_transaction(
        workspace, actor=None, transaction_type=TransactionType.expense, name="Rent",
        amount_cents=95000, transaction_date=date(2026, 8, 5), account_id=account.id, budget_category_id=cat.id)

    alerts = insights_svc.budget_alerts(workspace, today=date(2026, 8, 15))
    assert len(alerts) == 1
    assert alerts[0]["threshold"] == "attention"


def test_budget_alerts_empty_without_open_period(db, workspace):
    from app.services import financial_insights_service as insights_svc

    assert insights_svc.budget_alerts(workspace, today=date(2026, 8, 15)) == []


def test_bills_due_soon_reuses_bills_service(db, workspace):
    from app.financial_planning_models import BillFrequency
    from app.services import bills_service, financial_insights_service as insights_svc

    bill = bills_service.create_bill(
        workspace, actor=None, bill_name="Internet", default_amount_cents=8000,
        due_day=10, frequency=BillFrequency.monthly)
    bills_service.ensure_payments_for_month(workspace, for_date=date(2026, 8, 1))

    result = insights_svc.bills_due_soon(workspace, days=7, today=date(2026, 8, 5))
    assert result["count"] == 1
    assert result["total_cents"] == 8000


def test_goal_pace_insights_only_active_goals_with_estimate(db, workspace):
    from app.financial_planning_models import GoalStatus
    from app.services import goals_service, financial_insights_service as insights_svc

    with_pace = goals_service.create_goal(
        workspace, actor=None, name="Vacation", target_amount_cents=120000, monthly_contribution_cents=10000)
    goals_service.create_goal(workspace, actor=None, name="No pace set", target_amount_cents=50000)
    cancelled = goals_service.create_goal(
        workspace, actor=None, name="Cancelled goal", target_amount_cents=50000, monthly_contribution_cents=5000)
    goals_service.set_goal_status(cancelled, GoalStatus.cancelled)

    insights = insights_svc.goal_pace_insights(workspace)
    assert [i["goal_name"] for i in insights] == ["Vacation"]


def test_subscriptions_annual_cost_multiplies_monthly_by_12(db, workspace):
    from app.financial_planning_models import BillFrequency
    from app.services import recurring_service, financial_insights_service as insights_svc

    recurring_service.create_recurring_debit(
        workspace, actor=None, merchant="Netflix", amount_cents=1500, frequency=BillFrequency.monthly)

    assert insights_svc.subscriptions_annual_cost_cents(workspace) == 1500 * 12


def test_all_insights_returns_all_five_keys(db, workspace):
    from app.services import financial_insights_service as insights_svc

    result = insights_svc.all_insights(workspace, today=date(2026, 8, 15))
    assert set(result.keys()) == {
        "category_movers", "budget_alerts", "bills_due_soon", "goal_pace", "subscriptions_annual_cost_cents"}


# --------------------------------------------------------------------------
# Forecasts
# --------------------------------------------------------------------------

def test_cash_flow_forecast_uses_trailing_closed_months_average(db, workspace, account):
    from app.financial_planning_models import TransactionType
    from app.services import financial_insights_service as insights_svc
    from app.services import financial_transactions_service as tx_svc

    for month, day in [(5, 1), (6, 1), (7, 1)]:
        tx_svc.create_transaction(
            workspace, actor=None, transaction_type=TransactionType.income, name="Paycheck",
            amount_cents=500000, transaction_date=date(2026, month, day), account_id=account.id)
        tx_svc.create_transaction(
            workspace, actor=None, transaction_type=TransactionType.expense, name="Rent",
            amount_cents=180000, transaction_date=date(2026, month, day), account_id=account.id)

    forecast = insights_svc.cash_flow_forecast(workspace, months_ahead=3, trailing_months=3, today=date(2026, 8, 15))
    assert forecast["avg_income_cents"] == 500000
    assert forecast["avg_expenses_cents"] == 180000
    assert forecast["avg_net_cents"] == 320000
    assert len(forecast["months"]) == 3
    assert forecast["months"][0]["label"] == "Sep 2026"
    assert forecast["months"][2]["cumulative_net_cents"] == 320000 * 3


# --------------------------------------------------------------------------
# Calculators
# --------------------------------------------------------------------------

def test_debt_payoff_calculator_matches_simulate_payoff(db):
    from app.services import financial_insights_service as insights_svc

    result = insights_svc.debt_payoff_calculator(
        balance_cents=100000, apr_bps=0, monthly_payment_cents=10000, today=date(2026, 1, 1))
    assert result["months_to_payoff"] == 10
    assert result["total_interest_cents"] == 0


def test_debt_payoff_calculator_none_when_payment_too_low(db):
    from app.services import financial_insights_service as insights_svc

    result = insights_svc.debt_payoff_calculator(
        balance_cents=1000000, apr_bps=2400, monthly_payment_cents=5000, today=date(2026, 1, 1))
    assert result is None


def test_goal_savings_calculator_computes_months():
    from app.services import financial_insights_service as insights_svc

    result = insights_svc.goal_savings_calculator(
        target_amount_cents=120000, current_amount_cents=20000, monthly_contribution_cents=10000)
    assert result["months_to_reach_target"] == 10


def test_goal_savings_calculator_zero_when_already_reached():
    from app.services import financial_insights_service as insights_svc

    result = insights_svc.goal_savings_calculator(
        target_amount_cents=100000, current_amount_cents=150000, monthly_contribution_cents=10000)
    assert result == {"months_to_reach_target": 0}


def test_goal_savings_calculator_none_without_positive_contribution():
    from app.services import financial_insights_service as insights_svc

    assert insights_svc.goal_savings_calculator(
        target_amount_cents=100000, current_amount_cents=0, monthly_contribution_cents=0) is None


# --------------------------------------------------------------------------
# Integração: rota real, cliente logado
# --------------------------------------------------------------------------

@pytest.fixture()
def financial_client_login(client, db, staff_user):
    from app.crm_financial_models import FinancialClient
    from app.models import User
    from app.services import financial_planning_service as fp_svc

    user = User(email="insightsclient@example.com", password_hash="x", is_staff=False, email_verified=True)
    db.add(user)
    db.commit()
    fc = FinancialClient(full_name="Cliente Insights HTTP", user_id=user.id)
    db.add(fc)
    db.commit()
    fp_svc.enable_access(fc, actor=staff_user)

    user_id = user.id
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True
    return client


def test_tools_page_renders(financial_client_login):
    resp = financial_client_login.get("/meu-plano-financeiro/workspace/ferramentas")
    assert resp.status_code == 200
    assert b"Tools" in resp.data


def test_debt_calculator_via_route(financial_client_login):
    resp = financial_client_login.get(
        "/meu-plano-financeiro/workspace/ferramentas",
        query_string={"calc": "debt", "balance": "1000", "apr": "0", "payment": "100"})
    assert resp.status_code == 200
    assert b"10" in resp.data
