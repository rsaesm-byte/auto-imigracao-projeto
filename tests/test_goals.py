"""Fase 7 (Goals & Savings) do SAES_Financial_Planning_Master_Spec,
2026-08-07 -- metas financeiras com histórico de aportes, sinking
funds, e o Fundo de Emergência (calculado a partir da média de gastos
"needs" + saldo de uma conta vinculada, sem tabela própria).
"""
from __future__ import annotations

from datetime import date

import pytest


@pytest.fixture()
def workspace(db, staff_user):
    from app.crm_financial_models import FinancialClient
    from app.services import financial_planning_service as fp_svc

    fc = FinancialClient(full_name="Cliente Goals Teste")
    db.add(fc)
    db.commit()
    return fp_svc.enable_access(fc, actor=staff_user)


@pytest.fixture()
def account(db, workspace, staff_user):
    from app.financial_planning_models import AccountType
    from app.services import financial_accounts_service as accounts_svc

    return accounts_svc.create_account(
        workspace, actor=staff_user, account_name="Checking", account_type=AccountType.checking,
        current_balance_cents=300000)


# --------------------------------------------------------------------------
# Financial Goals
# --------------------------------------------------------------------------

def test_create_goal_requires_name(db, workspace):
    from app.services import goals_service

    with pytest.raises(goals_service.GoalValidationError):
        goals_service.create_goal(workspace, actor=None, name="", target_amount_cents=100000)


def test_create_goal_requires_positive_target(db, workspace):
    from app.services import goals_service

    with pytest.raises(goals_service.GoalValidationError):
        goals_service.create_goal(workspace, actor=None, name="Trip", target_amount_cents=0)


def test_create_goal_rejects_account_from_another_workspace(db, workspace, staff_user):
    from app.crm_financial_models import FinancialClient
    from app.financial_planning_models import AccountType
    from app.services import financial_accounts_service as accounts_svc
    from app.services import financial_planning_service as fp_svc
    from app.services import goals_service

    other_fc = FinancialClient(full_name="Outro Cliente Goals")
    db.add(other_fc)
    db.commit()
    other_ws = fp_svc.enable_access(other_fc, actor=staff_user)
    other_account = accounts_svc.create_account(
        other_ws, actor=staff_user, account_name="Other Checking", account_type=AccountType.checking)

    with pytest.raises(goals_service.GoalValidationError):
        goals_service.create_goal(
            workspace, actor=None, name="Trip", target_amount_cents=100000, account_id=other_account.id)


def test_add_contribution_increments_current_amount(db, workspace, account):
    from app.services import goals_service

    goal = goals_service.create_goal(workspace, actor=None, name="Trip", target_amount_cents=100000)
    goals_service.add_contribution(
        goal, amount_cents=20000, contribution_date=date(2026, 8, 1), from_account_id=account.id)
    assert goal.current_amount_cents == 20000


def test_add_contribution_zero_amount_rejected(db, workspace):
    from app.services import goals_service

    goal = goals_service.create_goal(workspace, actor=None, name="Trip", target_amount_cents=100000)
    with pytest.raises(goals_service.GoalValidationError):
        goals_service.add_contribution(goal, amount_cents=0, contribution_date=date.today())


def test_add_contribution_auto_completes_goal_at_target(db, workspace):
    from app.financial_planning_models import GoalStatus
    from app.services import goals_service

    goal = goals_service.create_goal(workspace, actor=None, name="Trip", target_amount_cents=50000)
    goals_service.add_contribution(goal, amount_cents=50000, contribution_date=date.today())
    assert goal.status == GoalStatus.completed


def test_goal_progress_remaining_and_ratio(db, workspace):
    from app.services import goals_service

    goal = goals_service.create_goal(workspace, actor=None, name="Trip", target_amount_cents=100000)
    goals_service.add_contribution(goal, amount_cents=25000, contribution_date=date.today())

    progress = goals_service.goal_progress(goal, today=date(2026, 8, 7))
    assert progress["remaining_cents"] == 75000
    assert progress["progress"] == 0.25


def test_goal_progress_required_monthly_contribution(db, workspace):
    from app.services import goals_service

    goal = goals_service.create_goal(
        workspace, actor=None, name="Trip", target_amount_cents=120000, target_date=date(2026, 12, 1))
    progress = goals_service.goal_progress(goal, today=date(2026, 8, 1))
    # 4 meses até dezembro, 1200.00 restante -> 300.00/mês
    assert progress["required_monthly_contribution_cents"] == 30000


def test_goal_progress_no_required_contribution_without_target_date(db, workspace):
    from app.services import goals_service

    goal = goals_service.create_goal(workspace, actor=None, name="Trip", target_amount_cents=100000)
    progress = goals_service.goal_progress(goal, today=date(2026, 8, 1))
    assert progress["required_monthly_contribution_cents"] is None


def test_goal_progress_estimated_completion_date(db, workspace):
    from app.services import goals_service

    goal = goals_service.create_goal(
        workspace, actor=None, name="Trip", target_amount_cents=100000, monthly_contribution_cents=25000)
    progress = goals_service.goal_progress(goal, today=date(2026, 8, 1))
    # 1000.00 restante / 250.00 por mês = 4 meses
    assert progress["estimated_completion_date"] == date(2026, 12, 1)


def test_set_goal_status(db, workspace):
    from app.financial_planning_models import GoalStatus
    from app.services import goals_service

    goal = goals_service.create_goal(workspace, actor=None, name="Trip", target_amount_cents=100000)
    goals_service.set_goal_status(goal, GoalStatus.paused)
    assert goal.status == GoalStatus.paused


def test_soft_delete_goal(db, workspace):
    from app.services import goals_service

    goal = goals_service.create_goal(workspace, actor=None, name="Trip", target_amount_cents=100000)
    goals_service.soft_delete_goal(goal)
    assert goal.deleted_at is not None


# --------------------------------------------------------------------------
# Sinking Funds
# --------------------------------------------------------------------------

def test_create_sinking_fund_requires_positive_target(db, workspace):
    from app.services import goals_service

    with pytest.raises(goals_service.GoalValidationError):
        goals_service.create_sinking_fund(workspace, actor=None, name="Property tax", target_amount_cents=0)


def test_update_sinking_fund_balance_rejects_negative(db, workspace):
    from app.services import goals_service

    fund = goals_service.create_sinking_fund(workspace, actor=None, name="Property tax", target_amount_cents=100000)
    with pytest.raises(goals_service.GoalValidationError):
        goals_service.update_sinking_fund_balance(fund, current_amount_cents=-100)


def test_update_sinking_fund_balance(db, workspace):
    from app.services import goals_service

    fund = goals_service.create_sinking_fund(workspace, actor=None, name="Property tax", target_amount_cents=100000)
    goals_service.update_sinking_fund_balance(fund, current_amount_cents=45000)
    assert fund.current_amount_cents == 45000


def test_soft_delete_sinking_fund(db, workspace):
    from app.services import goals_service

    fund = goals_service.create_sinking_fund(workspace, actor=None, name="Property tax", target_amount_cents=100000)
    goals_service.soft_delete_sinking_fund(fund)
    assert fund.deleted_at is not None
    assert fund.active is False


# --------------------------------------------------------------------------
# Fundo de Emergência
# --------------------------------------------------------------------------

def test_average_needs_expenses_cents(db, workspace, account, staff_user):
    from app.financial_planning_models import BudgetCategory, TransactionClassification, TransactionType
    from app.services import financial_transactions_service as tx_svc
    from app.services import goals_service

    housing = db.query(BudgetCategory).filter_by(financial_workspace_id=workspace.id, name="Housing").first()
    # 3 meses fechados (maio, junho, julho) com $1000 de needs cada, hoje = agosto
    for month in (5, 6, 7):
        tx_svc.create_transaction(
            workspace, actor=staff_user, transaction_type=TransactionType.expense, name="Rent",
            amount_cents=100000, transaction_date=date(2026, month, 5), account_id=account.id,
            budget_category_id=housing.id, classification=TransactionClassification.needs)

    avg = goals_service.average_needs_expenses_cents(workspace, months=3, today=date(2026, 8, 7))
    assert avg == 100000


def test_emergency_fund_summary_none_when_not_configured(db, workspace):
    from app.services import goals_service

    summary = goals_service.emergency_fund_summary(workspace, today=date(2026, 8, 7))
    assert summary["target_cents"] is None
    assert summary["current_cents"] is None
    assert summary["months_covered"] is None


def test_emergency_fund_summary_computes_target_and_months_covered(db, workspace, account, staff_user):
    from app.financial_planning_models import BudgetCategory, TransactionClassification, TransactionType
    from app.services import financial_transactions_service as tx_svc
    from app.services import goals_service

    housing = db.query(BudgetCategory).filter_by(financial_workspace_id=workspace.id, name="Housing").first()
    for month in (5, 6, 7):
        tx_svc.create_transaction(
            workspace, actor=staff_user, transaction_type=TransactionType.expense, name="Rent",
            amount_cents=100000, transaction_date=date(2026, month, 5), account_id=account.id,
            budget_category_id=housing.id, classification=TransactionClassification.needs)

    goals_service.set_emergency_fund_settings(workspace, target_months=6, account_id=account.id)
    summary = goals_service.emergency_fund_summary(workspace, today=date(2026, 8, 7))

    assert summary["avg_needs_expenses_cents"] == 100000
    assert summary["target_cents"] == 600000  # 6 * $1000
    assert summary["current_cents"] == 300000  # saldo da conta (fixture)
    assert summary["months_covered"] == 3.0  # 300000 / 100000


def test_set_emergency_fund_settings_rejects_non_positive_months(db, workspace, account):
    from app.services import goals_service

    with pytest.raises(goals_service.GoalValidationError):
        goals_service.set_emergency_fund_settings(workspace, target_months=0, account_id=account.id)


# --------------------------------------------------------------------------
# Integração: rota real, cliente logado
# --------------------------------------------------------------------------

@pytest.fixture()
def financial_client_login(client, db, staff_user):
    from app.crm_financial_models import FinancialClient
    from app.models import User
    from app.services import financial_planning_service as fp_svc

    user = User(email="goalsclient@example.com", password_hash="x", is_staff=False, email_verified=True)
    db.add(user)
    db.commit()
    fc = FinancialClient(full_name="Cliente Goals HTTP", user_id=user.id)
    db.add(fc)
    db.commit()
    fp_svc.enable_access(fc, actor=staff_user)

    user_id = user.id
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True
    return client


def test_goals_page_renders(financial_client_login):
    resp = financial_client_login.get("/meu-plano-financeiro/workspace/metas")
    assert resp.status_code == 200
    assert b"Financial Goals" in resp.data


def test_add_goal_via_route(financial_client_login, db):
    resp = financial_client_login.post(
        "/meu-plano-financeiro/workspace/metas/nova",
        data={"name": "New Laptop", "target_amount": "1500.00"}, follow_redirects=True)
    assert resp.status_code == 200
    assert b"New Laptop" in resp.data

    from app.crm_financial_models import FinancialClient
    from app.financial_planning_models import FinancialGoal
    fc = db.query(FinancialClient).filter_by(full_name="Cliente Goals HTTP").first()
    assert db.query(FinancialGoal).filter_by(financial_workspace_id=fc.workspace.id, name="New Laptop").count() == 1


def test_sinking_funds_page_renders(financial_client_login):
    resp = financial_client_login.get("/meu-plano-financeiro/workspace/fundos")
    assert resp.status_code == 200
    assert b"Sinking Funds" in resp.data


def test_emergency_fund_page_renders(financial_client_login):
    resp = financial_client_login.get("/meu-plano-financeiro/workspace/fundo-emergencia")
    assert resp.status_code == 200
    assert b"Emergency Fund" in resp.data
