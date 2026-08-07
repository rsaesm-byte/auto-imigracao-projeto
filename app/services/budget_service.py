"""Fase 4 (Orçamento) do SAES_Financial_Planning_Master_Spec, 2026-08-07 --
regra de orçamento (50/30/20 ou percentual customizado), período mensal,
alocação planejada por categoria, e fechamento/reabertura de mês com
snapshot protegido (§9 "Month Close").

Fórmulas exatamente como o documento define (§8):
- `actual_spending`: soma de despesas completed por categoria/período.
- `remaining`: planned - actual.
- `progress`: actual / planned (None se planned <= 0 -- não divide por zero).
- thresholds: healthy <80%, attention 80%-<100%, over_budget >=100%.
- 50/30/20: needs=income*0.50, wants=income*0.30, savings=income*0.20.
- custom_percentage: os 3 percentuais precisam somar 100%.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from app.crm_financial_models import FinancialWorkspace
from app.db import SessionLocal
from app.financial_planning_models import (BudgetAllocation, BudgetCategory, BudgetPeriod,
                                            BudgetPeriodStatus, BudgetRule, BudgetRuleType,
                                            FinancialMonthSnapshot)
from app.services import audit_service
from app.services import financial_dashboard_service as dash_svc


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BudgetValidationError(ValueError):
    pass


# --------------------------------------------------------------------------
# Regra de orçamento
# --------------------------------------------------------------------------

def get_budget_rule(workspace: FinancialWorkspace) -> BudgetRule | None:
    return SessionLocal.query(BudgetRule).filter_by(financial_workspace_id=workspace.id).first()


def set_budget_rule(
    workspace: FinancialWorkspace, *, rule_type: BudgetRuleType,
    needs_percent: int | None = None, wants_percent: int | None = None, savings_percent: int | None = None,
) -> BudgetRule:
    if rule_type == BudgetRuleType.custom_percentage:
        if needs_percent is None or wants_percent is None or savings_percent is None:
            raise BudgetValidationError("Custom rules need Needs/Wants/Savings percentages.")
        if needs_percent + wants_percent + savings_percent != 100:
            raise BudgetValidationError("Needs + Wants + Savings percentages must add up to 100%.")
    else:
        needs_percent = wants_percent = savings_percent = None

    rule = get_budget_rule(workspace)
    if rule is None:
        rule = BudgetRule(financial_workspace_id=workspace.id)
        SessionLocal.add(rule)
    rule.rule_type = rule_type
    rule.needs_percent = needs_percent
    rule.wants_percent = wants_percent
    rule.savings_percent = savings_percent
    SessionLocal.commit()
    return rule


def rule_targets_cents(rule: BudgetRule | None, income_cents: int) -> dict | None:
    """`{needs, wants, savings}` em cents, ou `None` se não há regra
    percentual ativa (`category_budget`/`none`, ou sem regra nenhuma
    ainda) -- nesse caso o orçamento é só por categoria
    (`budget_vs_actual`), não por balde needs/wants/savings."""
    if rule is None or rule.rule_type == BudgetRuleType.none:
        return None
    if rule.rule_type == BudgetRuleType.fifty_thirty_twenty:
        return {
            "needs": round(income_cents * 0.50), "wants": round(income_cents * 0.30),
            "savings": round(income_cents * 0.20),
        }
    if rule.rule_type == BudgetRuleType.custom_percentage:
        return {
            "needs": round(income_cents * rule.needs_percent / 100),
            "wants": round(income_cents * rule.wants_percent / 100),
            "savings": round(income_cents * rule.savings_percent / 100),
        }
    return None  # category_budget


# --------------------------------------------------------------------------
# Período mensal
# --------------------------------------------------------------------------

def _month_bounds(d: date) -> tuple[date, date]:
    from app.services.financial_dashboard_service import _first_of_month, _first_of_next_month
    from datetime import timedelta
    start = _first_of_month(d)
    end = _first_of_next_month(start) - timedelta(days=1)
    return start, end


def get_or_create_current_period(workspace: FinancialWorkspace, *, today: date | None = None) -> BudgetPeriod:
    """Uma linha por (workspace, mês) -- nunca duplica: se já existe
    período pro mês de `today`, devolve o mesmo (fechado, reaberto ou
    aberto -- não força reabrir sozinho)."""
    today = today or date.today()
    start, end = _month_bounds(today)
    period = (
        SessionLocal.query(BudgetPeriod)
        .filter_by(financial_workspace_id=workspace.id, period_start=start).first()
    )
    if period is None:
        period = BudgetPeriod(financial_workspace_id=workspace.id, period_start=start, period_end=end)
        SessionLocal.add(period)
        SessionLocal.commit()
    return period


# --------------------------------------------------------------------------
# Alocação por categoria / Budget vs Actual
# --------------------------------------------------------------------------

def set_allocation(period: BudgetPeriod, category: BudgetCategory, *,
                    planned_amount_cents: int, rollover_enabled: bool = False,
                    notes: str | None = None) -> BudgetAllocation:
    if planned_amount_cents < 0:
        raise BudgetValidationError("Planned amount cannot be negative.")
    allocation = (
        SessionLocal.query(BudgetAllocation)
        .filter_by(budget_period_id=period.id, budget_category_id=category.id).first()
    )
    if allocation is None:
        allocation = BudgetAllocation(budget_period_id=period.id, budget_category_id=category.id)
        SessionLocal.add(allocation)
    allocation.planned_amount_cents = planned_amount_cents
    allocation.rollover_enabled = rollover_enabled
    allocation.notes = notes or None
    SessionLocal.commit()
    return allocation


def _progress_and_threshold(actual_cents: int, planned_cents: int) -> tuple[float | None, str | None]:
    if planned_cents <= 0:
        return None, None
    progress = actual_cents / planned_cents
    if progress >= 1.0:
        threshold = "over_budget"
    elif progress >= 0.8:
        threshold = "attention"
    else:
        threshold = "healthy"
    return progress, threshold


def budget_vs_actual(workspace: FinancialWorkspace, period: BudgetPeriod) -> list[dict]:
    """Uma linha por categoria com alocação neste período -- categoria
    sem alocação não aparece aqui (nada foi planejado pra ela, "budget
    vs actual" não tem o que comparar)."""
    allocations = SessionLocal.query(BudgetAllocation).filter_by(budget_period_id=period.id).all()
    actual_by_category = {
        row["label"]: row["amount_cents"]
        for row in dash_svc.spending_by_category(workspace, start=period.period_start, end=period.period_end)
    }
    rows = []
    for allocation in allocations:
        category = SessionLocal.get(BudgetCategory, allocation.budget_category_id)
        actual_cents = actual_by_category.get(category.name, 0) if category else 0
        progress, threshold = _progress_and_threshold(actual_cents, allocation.planned_amount_cents)
        rows.append({
            "category": category, "planned_cents": allocation.planned_amount_cents,
            "actual_cents": actual_cents, "remaining_cents": allocation.planned_amount_cents - actual_cents,
            "progress": progress, "threshold": threshold,
        })
    rows.sort(key=lambda r: r["category"].name if r["category"] else "")
    return rows


# --------------------------------------------------------------------------
# Fechamento de mês (§9)
# --------------------------------------------------------------------------

def close_period(workspace: FinancialWorkspace, period: BudgetPeriod, *, actor) -> FinancialMonthSnapshot:
    """Fecha o mês e grava um snapshot IMUTÁVEL dos números -- nunca
    recalculado depois, mesmo que transações antigas do período sejam
    editadas/apagadas dali pra frente (histórico protegido, §7/§9)."""
    if period.status == BudgetPeriodStatus.closed:
        raise BudgetValidationError("This period is already closed.")

    income_cents = dash_svc.monthly_income_cents(workspace, start=period.period_start, end=period.period_end)
    expenses_cents = dash_svc.monthly_expenses_cents(workspace, start=period.period_start, end=period.period_end)
    snapshot_data = {
        "period_start": period.period_start.isoformat(), "period_end": period.period_end.isoformat(),
        "income_cents": income_cents, "expenses_cents": expenses_cents,
        "net_cash_flow_cents": income_cents - expenses_cents,
        "spending_by_category": dash_svc.spending_by_category(
            workspace, start=period.period_start, end=period.period_end),
        "budget_vs_actual": [
            {"category": row["category"].name if row["category"] else None,
             "planned_cents": row["planned_cents"], "actual_cents": row["actual_cents"],
             "remaining_cents": row["remaining_cents"], "threshold": row["threshold"]}
            for row in budget_vs_actual(workspace, period)
        ],
    }

    now = _utcnow()
    period.status = BudgetPeriodStatus.closed
    period.closed_at = now
    period.closed_by_id = actor.id

    snapshot = FinancialMonthSnapshot(
        financial_workspace_id=workspace.id, budget_period_id=period.id,
        snapshot_json=snapshot_data, created_by_id=actor.id)
    SessionLocal.add(snapshot)

    audit_service.log_change(
        "BudgetPeriod", period.id, "month_closed",
        description=f"Month {period.period_start.isoformat()} closed by {actor.email}", user_id=actor.id)
    SessionLocal.commit()

    from app.services import net_worth_service
    net_worth_service.snapshot_month_close(workspace, snapshot_date=period.period_end)

    return snapshot


def reopen_period(period: BudgetPeriod, *, actor) -> None:
    """Nunca apaga o snapshot já gravado -- reabrir só muda o status,
    pra permitir editar transações do mês de novo; o snapshot continua
    sendo o registro histórico de como o mês estava no momento do
    fechamento original."""
    if period.status != BudgetPeriodStatus.closed:
        raise BudgetValidationError("Only a closed period can be reopened.")

    now = _utcnow()
    period.status = BudgetPeriodStatus.reopened
    period.reopened_at = now
    period.reopened_by_id = actor.id

    audit_service.log_change(
        "BudgetPeriod", period.id, "month_reopened",
        description=f"Month {period.period_start.isoformat()} reopened by {actor.email}", user_id=actor.id)
    SessionLocal.commit()
