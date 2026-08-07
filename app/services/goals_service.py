"""Fase 7 (Goals & Savings) do SAES_Financial_Planning_Master_Spec,
2026-08-07 -- metas financeiras (com histórico de aportes), sinking
funds, e o Fundo de Emergência (calculado, sem tabela própria -- ver
docstring de `FinancialWorkspace.emergency_fund_target_months`,
app/crm_financial_models.py).

Fórmulas exatamente como o documento define (§8):
- `remaining`: max(target - current, 0).
- `progress`: current/target quando target > 0 (None senão, não divide
  por zero).
- `required_monthly_contribution`: remaining/meses_até_o_alvo quando há
  `target_date` no futuro (None senão).
- `estimated_completion_date`: hoje + (remaining / monthly_contribution)
  meses, quando o cliente já informou um ritmo de aporte mensal (None
  senão -- "derive from contribution pace", e a única pace que temos é
  a que o cliente declarou, não um histórico de verdade ainda).
- Fundo de emergência: `target = média de gastos Needs mensais × meses-
  alvo`; `months_covered = saldo da conta vinculada / média de gastos
  Needs mensais`.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app.crm_financial_models import FinancialWorkspace
from app.db import SessionLocal
from app.financial_planning_models import (Account, FinancialGoal, GoalContribution,
                                            GoalPriority, GoalStatus, SinkingFund)
from app.services import financial_dashboard_service as dash_svc
from app.services.financial_dashboard_service import _first_of_month, _first_of_next_month, _first_of_prev_month


class GoalValidationError(ValueError):
    pass


def _check_account_ownership(account_id: int | None, workspace_id: int) -> None:
    if account_id is None:
        return
    account = SessionLocal.get(Account, account_id)
    if account is None or account.financial_workspace_id != workspace_id:
        raise GoalValidationError("Account does not belong to this workspace.")


# --------------------------------------------------------------------------
# Financial Goals
# --------------------------------------------------------------------------

def list_goals(workspace: FinancialWorkspace, *, include_inactive: bool = False) -> list[FinancialGoal]:
    query = (
        SessionLocal.query(FinancialGoal).filter_by(financial_workspace_id=workspace.id)
        .filter(FinancialGoal.deleted_at.is_(None))
    )
    if not include_inactive:
        query = query.filter(FinancialGoal.status.in_([GoalStatus.active, GoalStatus.paused]))
    return query.order_by(FinancialGoal.target_date.is_(None), FinancialGoal.target_date).all()


def create_goal(
    workspace: FinancialWorkspace, *, actor, name: str, target_amount_cents: int,
    goal_type: str | None = None, target_date: date | None = None,
    monthly_contribution_cents: int | None = None, priority: GoalPriority = GoalPriority.medium,
    account_id: int | None = None, notes: str | None = None,
) -> FinancialGoal:
    if not name:
        raise GoalValidationError("Name is required.")
    if target_amount_cents is None or target_amount_cents <= 0:
        raise GoalValidationError("Target amount must be greater than zero.")
    _check_account_ownership(account_id, workspace.id)

    goal = FinancialGoal(
        financial_workspace_id=workspace.id, name=name, goal_type=goal_type or None,
        target_amount_cents=target_amount_cents, target_date=target_date,
        monthly_contribution_cents=monthly_contribution_cents, priority=priority,
        account_id=account_id, notes=notes or None, created_by_id=getattr(actor, "id", None),
    )
    SessionLocal.add(goal)
    SessionLocal.commit()
    return goal


def set_goal_status(goal: FinancialGoal, status: GoalStatus) -> FinancialGoal:
    goal.status = status
    SessionLocal.commit()
    return goal


def soft_delete_goal(goal: FinancialGoal) -> None:
    goal.deleted_at = datetime.now(timezone.utc)
    SessionLocal.commit()


def add_contribution(
    goal: FinancialGoal, *, amount_cents: int, contribution_date: date,
    from_account_id: int | None = None, notes: str | None = None,
) -> GoalContribution:
    if amount_cents is None or amount_cents == 0:
        raise GoalValidationError("Contribution amount cannot be zero.")
    _check_account_ownership(from_account_id, goal.financial_workspace_id)

    contribution = GoalContribution(
        goal_id=goal.id, amount_cents=amount_cents, contribution_date=contribution_date,
        from_account_id=from_account_id, notes=notes or None,
    )
    SessionLocal.add(contribution)
    goal.current_amount_cents += amount_cents
    if goal.status == GoalStatus.active and goal.current_amount_cents >= goal.target_amount_cents:
        goal.status = GoalStatus.completed
    SessionLocal.commit()
    return contribution


def list_contributions(goal: FinancialGoal) -> list[GoalContribution]:
    return (
        SessionLocal.query(GoalContribution).filter_by(goal_id=goal.id)
        .order_by(GoalContribution.contribution_date.desc(), GoalContribution.id.desc()).all()
    )


def goal_progress(goal: FinancialGoal, *, today: date | None = None) -> dict:
    today = today or date.today()
    remaining_cents = max(goal.target_amount_cents - goal.current_amount_cents, 0)
    progress = (goal.current_amount_cents / goal.target_amount_cents) if goal.target_amount_cents > 0 else None

    required_monthly_contribution_cents = None
    if goal.target_date and goal.target_date > today:
        months_until_target = (
            (goal.target_date.year - today.year) * 12 + (goal.target_date.month - today.month)
        )
        if goal.target_date.day < today.day:
            months_until_target -= 1
        if months_until_target > 0:
            required_monthly_contribution_cents = round(remaining_cents / months_until_target)

    estimated_completion_date = None
    if goal.monthly_contribution_cents and goal.monthly_contribution_cents > 0 and remaining_cents > 0:
        months_needed = -(-remaining_cents // goal.monthly_contribution_cents)  # ceil division
        estimated_completion_date = _add_months(today, months_needed)

    return {
        "remaining_cents": remaining_cents, "progress": progress,
        "required_monthly_contribution_cents": required_monthly_contribution_cents,
        "estimated_completion_date": estimated_completion_date,
    }


def _add_months(d: date, months: int) -> date:
    import calendar
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(d.day, last_day))


# --------------------------------------------------------------------------
# Sinking Funds
# --------------------------------------------------------------------------

def list_sinking_funds(workspace: FinancialWorkspace, *, include_inactive: bool = False) -> list[SinkingFund]:
    query = (
        SessionLocal.query(SinkingFund).filter_by(financial_workspace_id=workspace.id)
        .filter(SinkingFund.deleted_at.is_(None))
    )
    if not include_inactive:
        query = query.filter_by(active=True)
    return query.order_by(SinkingFund.target_date.is_(None), SinkingFund.target_date).all()


def create_sinking_fund(
    workspace: FinancialWorkspace, *, actor, name: str, target_amount_cents: int,
    current_amount_cents: int = 0, target_date: date | None = None,
    monthly_contribution_cents: int | None = None, account_id: int | None = None,
) -> SinkingFund:
    if not name:
        raise GoalValidationError("Name is required.")
    if target_amount_cents is None or target_amount_cents <= 0:
        raise GoalValidationError("Target amount must be greater than zero.")
    _check_account_ownership(account_id, workspace.id)

    fund = SinkingFund(
        financial_workspace_id=workspace.id, name=name, target_amount_cents=target_amount_cents,
        current_amount_cents=current_amount_cents or 0, target_date=target_date,
        monthly_contribution_cents=monthly_contribution_cents, account_id=account_id,
        created_by_id=getattr(actor, "id", None),
    )
    SessionLocal.add(fund)
    SessionLocal.commit()
    return fund


def update_sinking_fund_balance(fund: SinkingFund, *, current_amount_cents: int) -> SinkingFund:
    if current_amount_cents is None or current_amount_cents < 0:
        raise GoalValidationError("Current amount cannot be negative.")
    fund.current_amount_cents = current_amount_cents
    SessionLocal.commit()
    return fund


def soft_delete_sinking_fund(fund: SinkingFund) -> None:
    fund.deleted_at = datetime.now(timezone.utc)
    fund.active = False
    SessionLocal.commit()


# --------------------------------------------------------------------------
# Fundo de Emergência (calculado, sem tabela própria)
# --------------------------------------------------------------------------

def set_emergency_fund_settings(
    workspace: FinancialWorkspace, *, target_months: int | None, account_id: int | None,
) -> FinancialWorkspace:
    if target_months is not None and target_months <= 0:
        raise GoalValidationError("Target months must be greater than zero.")
    _check_account_ownership(account_id, workspace.id)
    workspace.emergency_fund_target_months = target_months
    workspace.emergency_fund_account_id = account_id
    SessionLocal.commit()
    return workspace


def average_needs_expenses_cents(workspace: FinancialWorkspace, *, months: int = 3, today: date | None = None) -> int:
    """Média dos gastos classificados como "needs" nos últimos `months`
    meses JÁ FECHADOS (exclui o mês corrente, ainda incompleto) -- evita
    que uma média puxada no dia 2 do mês pareça artificialmente baixa."""
    today = today or date.today()
    cursor = _first_of_month(today)
    total = 0
    for _ in range(months):
        cursor = _first_of_prev_month(cursor)
        end = _first_of_next_month(cursor) - timedelta(days=1)
        breakdown = dash_svc.needs_wants_savings_breakdown(workspace, start=cursor, end=end)
        total += breakdown["needs"]
    return round(total / months) if months else 0


def emergency_fund_summary(workspace: FinancialWorkspace, *, today: date | None = None) -> dict:
    """`None` pros campos calculados quando a configuração ainda não foi
    feita (sem meses-alvo ou sem conta vinculada) -- nunca mostra um
    número fingindo ser real sem os dois ingredientes."""
    avg_needs_cents = average_needs_expenses_cents(workspace, today=today)

    current_cents = None
    if workspace.emergency_fund_account_id:
        account = SessionLocal.get(Account, workspace.emergency_fund_account_id)
        if account is not None and account.deleted_at is None:
            current_cents = account.current_balance_cents

    target_cents = None
    if workspace.emergency_fund_target_months and avg_needs_cents:
        target_cents = avg_needs_cents * workspace.emergency_fund_target_months

    months_covered = None
    if current_cents is not None and avg_needs_cents:
        months_covered = current_cents / avg_needs_cents

    return {
        "avg_needs_expenses_cents": avg_needs_cents, "current_cents": current_cents,
        "target_cents": target_cents, "months_covered": months_covered,
        "target_months": workspace.emergency_fund_target_months,
        "account_id": workspace.emergency_fund_account_id,
    }
