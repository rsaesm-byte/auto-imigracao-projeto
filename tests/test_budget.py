"""Fase 4 (Orçamento) do SAES_Financial_Planning_Master_Spec, 2026-08-07 --
regra de orçamento (50/30/20 / percentual customizado), alocação por
categoria (budget vs actual, thresholds healthy/attention/over_budget),
e fechamento/reabertura de mês com snapshot protegido.
"""
from __future__ import annotations

from datetime import date

import pytest


@pytest.fixture()
def workspace(db, staff_user):
    from app.crm_financial_models import FinancialClient
    from app.services import financial_planning_service as fp_svc

    fc = FinancialClient(full_name="Cliente Orcamento Teste")
    db.add(fc)
    db.commit()
    return fp_svc.enable_access(fc, actor=staff_user)


# --------------------------------------------------------------------------
# Regra de orçamento
# --------------------------------------------------------------------------

def test_custom_percentage_rule_requires_100_percent_total(db, workspace):
    from app.financial_planning_models import BudgetRuleType
    from app.services import budget_service

    with pytest.raises(budget_service.BudgetValidationError):
        budget_service.set_budget_rule(
            workspace, rule_type=BudgetRuleType.custom_percentage,
            needs_percent=50, wants_percent=30, savings_percent=30)  # soma 110%


def test_custom_percentage_rule_saves_when_valid(db, workspace):
    from app.financial_planning_models import BudgetRuleType
    from app.services import budget_service

    rule = budget_service.set_budget_rule(
        workspace, rule_type=BudgetRuleType.custom_percentage,
        needs_percent=60, wants_percent=25, savings_percent=15)
    assert rule.needs_percent == 60 and rule.wants_percent == 25 and rule.savings_percent == 15


def test_fifty_thirty_twenty_targets(db, workspace):
    from app.financial_planning_models import BudgetRuleType
    from app.services import budget_service

    rule = budget_service.set_budget_rule(workspace, rule_type=BudgetRuleType.fifty_thirty_twenty)
    targets = budget_service.rule_targets_cents(rule, income_cents=500000)
    assert targets == {"needs": 250000, "wants": 150000, "savings": 100000}


def test_category_budget_rule_has_no_percentage_targets(db, workspace):
    from app.financial_planning_models import BudgetRuleType
    from app.services import budget_service

    rule = budget_service.set_budget_rule(workspace, rule_type=BudgetRuleType.category_budget)
    assert budget_service.rule_targets_cents(rule, income_cents=500000) is None


def test_no_rule_has_no_targets(db, workspace):
    from app.services import budget_service

    assert budget_service.rule_targets_cents(None, income_cents=500000) is None


# --------------------------------------------------------------------------
# Período / alocação / budget vs actual
# --------------------------------------------------------------------------

def test_get_or_create_current_period_is_idempotent(db, workspace):
    from app.services import budget_service

    p1 = budget_service.get_or_create_current_period(workspace, today=date(2026, 8, 7))
    p2 = budget_service.get_or_create_current_period(workspace, today=date(2026, 8, 20))
    assert p1.id == p2.id, "mesmo mês não pode criar 2 períodos"
    assert p1.period_start == date(2026, 8, 1)
    assert p1.period_end == date(2026, 8, 31)


def test_budget_vs_actual_thresholds(db, staff_user, workspace):
    from app.financial_planning_models import AccountType, BudgetCategory, TransactionType
    from app.services import budget_service
    from app.services import financial_accounts_service as accounts_svc
    from app.services import financial_transactions_service as tx_svc

    period = budget_service.get_or_create_current_period(workspace, today=date(2026, 8, 7))
    checking = accounts_svc.create_account(
        workspace, actor=staff_user, account_name="Checking", account_type=AccountType.checking)
    groceries = db.query(BudgetCategory).filter_by(financial_workspace_id=workspace.id, name="Groceries").first()
    housing = db.query(BudgetCategory).filter_by(financial_workspace_id=workspace.id, name="Housing").first()

    budget_service.set_allocation(period, groceries, planned_amount_cents=50000)  # healthy: 60% used
    budget_service.set_allocation(period, housing, planned_amount_cents=100000)  # over: 120% used

    tx_svc.create_transaction(
        workspace, actor=staff_user, transaction_type=TransactionType.expense, name="Food",
        amount_cents=30000, transaction_date=date(2026, 8, 7), account_id=checking.id,
        budget_category_id=groceries.id)
    tx_svc.create_transaction(
        workspace, actor=staff_user, transaction_type=TransactionType.expense, name="Rent",
        amount_cents=120000, transaction_date=date(2026, 8, 7), account_id=checking.id,
        budget_category_id=housing.id)

    rows = {r["category"].name: r for r in budget_service.budget_vs_actual(workspace, period)}
    assert rows["Groceries"]["threshold"] == "healthy"
    assert rows["Groceries"]["remaining_cents"] == 20000
    assert rows["Housing"]["threshold"] == "over_budget"
    assert rows["Housing"]["remaining_cents"] == -20000


def test_allocation_planned_amount_cannot_be_negative(db, workspace):
    from app.financial_planning_models import BudgetCategory
    from app.services import budget_service

    period = budget_service.get_or_create_current_period(workspace)
    groceries = db.query(BudgetCategory).filter_by(financial_workspace_id=workspace.id, name="Groceries").first()
    with pytest.raises(budget_service.BudgetValidationError):
        budget_service.set_allocation(period, groceries, planned_amount_cents=-100)


def test_set_allocation_upserts_not_duplicates(db, workspace):
    from app.financial_planning_models import BudgetAllocation, BudgetCategory
    from app.services import budget_service

    period = budget_service.get_or_create_current_period(workspace)
    groceries = db.query(BudgetCategory).filter_by(financial_workspace_id=workspace.id, name="Groceries").first()

    budget_service.set_allocation(period, groceries, planned_amount_cents=40000)
    budget_service.set_allocation(period, groceries, planned_amount_cents=45000)

    rows = db.query(BudgetAllocation).filter_by(budget_period_id=period.id, budget_category_id=groceries.id).all()
    assert len(rows) == 1
    assert rows[0].planned_amount_cents == 45000


# --------------------------------------------------------------------------
# Fechamento / reabertura de mês
# --------------------------------------------------------------------------

def test_close_period_creates_snapshot_and_locks_status(db, staff_user, workspace):
    from app.financial_planning_models import BudgetPeriodStatus
    from app.services import budget_service

    period = budget_service.get_or_create_current_period(workspace)
    snapshot = budget_service.close_period(workspace, period, actor=staff_user)

    assert period.status == BudgetPeriodStatus.closed
    assert period.closed_by_id == staff_user.id
    assert snapshot.budget_period_id == period.id
    assert "income_cents" in snapshot.snapshot_json


def test_close_period_twice_raises(db, staff_user, workspace):
    from app.services import budget_service

    period = budget_service.get_or_create_current_period(workspace)
    budget_service.close_period(workspace, period, actor=staff_user)
    with pytest.raises(budget_service.BudgetValidationError):
        budget_service.close_period(workspace, period, actor=staff_user)


def test_reopen_period_requires_closed_first(db, workspace):
    from app.services import budget_service

    period = budget_service.get_or_create_current_period(workspace)
    with pytest.raises(budget_service.BudgetValidationError):
        budget_service.reopen_period(period, actor=None)


def test_reopen_period_never_deletes_snapshot(db, staff_user, workspace):
    from app.financial_planning_models import BudgetPeriodStatus, FinancialMonthSnapshot
    from app.services import budget_service

    period = budget_service.get_or_create_current_period(workspace)
    snapshot = budget_service.close_period(workspace, period, actor=staff_user)
    snapshot_id = snapshot.id

    budget_service.reopen_period(period, actor=staff_user)

    assert period.status == BudgetPeriodStatus.reopened
    assert db.get(FinancialMonthSnapshot, snapshot_id) is not None


def test_close_and_reopen_are_audited(db, staff_user, workspace):
    from app.services import audit_service
    from app.services import budget_service

    period = budget_service.get_or_create_current_period(workspace)
    budget_service.close_period(workspace, period, actor=staff_user)
    budget_service.reopen_period(period, actor=staff_user)

    actions = [h.action for h in audit_service.get_history("BudgetPeriod", period.id)]
    assert "month_closed" in actions
    assert "month_reopened" in actions


# --------------------------------------------------------------------------
# Integração: rota real, cliente logado
# --------------------------------------------------------------------------

@pytest.fixture()
def financial_client_login(client, db, staff_user):
    from app.crm_financial_models import FinancialClient
    from app.models import User
    from app.services import financial_planning_service as fp_svc

    user = User(email="budgetclient@example.com", password_hash="x", is_staff=False, email_verified=True)
    db.add(user)
    db.commit()
    fc = FinancialClient(full_name="Cliente Orcamento HTTP", user_id=user.id)
    db.add(fc)
    db.commit()
    fp_svc.enable_access(fc, actor=staff_user)

    user_id = user.id
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True
    return client


def test_budget_page_renders(financial_client_login):
    resp = financial_client_login.get("/meu-plano-financeiro/workspace/orcamento")
    assert resp.status_code == 200
    assert b"Budget" in resp.data


def test_invalid_custom_rule_via_route_shows_error_not_crash(financial_client_login):
    resp = financial_client_login.post(
        "/meu-plano-financeiro/workspace/orcamento/regra",
        data={"rule_type": "custom_percentage", "needs_percent": "50", "wants_percent": "40", "savings_percent": "20"},
        follow_redirects=True)
    assert resp.status_code == 200
    assert b"100%" in resp.data


def test_close_month_via_route(financial_client_login, db):
    from app.crm_financial_models import FinancialClient
    from app.financial_planning_models import BudgetPeriodStatus

    resp = financial_client_login.post(
        "/meu-plano-financeiro/workspace/orcamento/fechar", follow_redirects=True)
    assert resp.status_code == 200
    assert b"snapshot" in resp.data

    fc = db.query(FinancialClient).filter_by(full_name="Cliente Orcamento HTTP").first()
    from app.services import budget_service
    period = budget_service.get_or_create_current_period(fc.workspace)
    assert period.status == BudgetPeriodStatus.closed
