"""Fase 12 (Advanced Tools) do SAES_Financial_Planning_Master_Spec,
2026-08-07 -- Smart Insights (§13), Forecasts, e Calculators.

Regras do §13, aplicadas em TUDO deste arquivo:
- Actual authorized client data only.
- Never invent values.
- Label projections as estimates.

Nenhuma tabela nova -- tudo aqui é derivado na hora a partir de dado que
já existe (mesmo espírito "calculado ao vivo" do Fundo de Emergência,
Fase 7, e da ordenação de dívidas, Fase 8). `all_insights` só devolve os
5 tipos de exemplo que o documento lista no §13 -- não inventa um 6º tipo
sem uma regra clara pra "nunca inventar valor".
"""
from __future__ import annotations

from calendar import month_abbr
from datetime import date, timedelta

from app.crm_financial_models import FinancialWorkspace
from app.db import SessionLocal
from app.financial_planning_models import BudgetPeriod
from app.services import budget_service as budget_svc
from app.services import debts_service as debts_svc
from app.services import financial_dashboard_service as dash_svc
from app.services import goals_service as goals_svc
from app.services import recurring_service as recurring_svc
from app.services.financial_dashboard_service import (_first_of_month, _first_of_next_month,
                                                        _first_of_prev_month)


# --------------------------------------------------------------------------
# Smart Insights (§13) -- os 5 tipos de exemplo do documento
# --------------------------------------------------------------------------

def category_movers(workspace: FinancialWorkspace, *, today: date | None = None, limit: int = 3) -> list[dict]:
    """"Dining expenses are X% higher/lower than last month" -- generalizado
    pra QUALQUER categoria do workspace (o documento usa "Dining" só como
    exemplo; as categorias são definidas por cliente, Fase 2, não uma
    lista fixa). Só entra categoria com gasto nos DOIS meses -- comparar
    contra zero dá um "infinito%" sem sentido."""
    today = today or date.today()
    this_start = _first_of_month(today)
    last_start = _first_of_prev_month(this_start)
    last_end = this_start - timedelta(days=1)

    this_month = {r["label"]: r["amount_cents"] for r in dash_svc.spending_by_category(workspace, start=this_start, end=today)}
    last_month = {r["label"]: r["amount_cents"] for r in dash_svc.spending_by_category(workspace, start=last_start, end=last_end)}

    movers = []
    for label, current_cents in this_month.items():
        previous_cents = last_month.get(label)
        if not previous_cents:
            continue
        pct_change = (current_cents - previous_cents) / previous_cents * 100
        movers.append({"label": label, "current_cents": current_cents, "previous_cents": previous_cents, "pct_change": pct_change})

    movers.sort(key=lambda m: abs(m["pct_change"]), reverse=True)
    return movers[:limit]


def budget_alerts(workspace: FinancialWorkspace, *, today: date | None = None) -> list[dict]:
    """"You have used X% of Entertainment budget" -- categorias no limiar
    attention/over_budget do período de orçamento ABERTO atual (mesma
    fórmula de `budget_service.budget_vs_actual`, Fase 4); lista vazia
    quando não há período aberto ou nenhuma categoria bateu o limiar."""
    today = today or date.today()
    period = (
        SessionLocal.query(BudgetPeriod)
        .filter_by(financial_workspace_id=workspace.id, period_start=_first_of_month(today)).first()
    )
    if period is None:
        return []
    rows = budget_svc.budget_vs_actual(workspace, period)
    return [r for r in rows if r["threshold"] in ("attention", "over_budget")]


def bills_due_soon(workspace: FinancialWorkspace, *, days: int = 7, today: date | None = None) -> dict:
    """"Bills totaling $X are due within seven days" -- reusa
    `bills_service.upcoming_within_days` (Fase 5) direto."""
    from app.services import bills_service as bills_svc
    upcoming = bills_svc.upcoming_within_days(workspace, days=days, today=today)
    return {"count": len(upcoming), "total_cents": sum(u["payment"].amount_cents for u in upcoming), "bills": upcoming}


def goal_pace_insights(workspace: FinancialWorkspace) -> list[dict]:
    """"At current contribution rate, goal may be reached in N months" --
    só metas ATIVAS com uma data estimada de conclusão de verdade (nunca
    mostra uma meta sem aporte configurado fingindo ter uma previsão)."""
    from app.financial_planning_models import GoalStatus
    insights = []
    for goal in goals_svc.list_goals(workspace):
        if goal.status != GoalStatus.active:
            continue
        progress = goals_svc.goal_progress(goal)
        if progress.get("estimated_completion_date"):
            insights.append({
                "goal_name": goal.name, "estimated_completion_date": progress["estimated_completion_date"],
                "remaining_cents": progress["remaining_cents"],
            })
    return insights


def subscriptions_annual_cost_cents(workspace: FinancialWorkspace) -> int:
    """"Recurring subscriptions total approximately $X/year" -- reusa
    `recurring_service.subscription_summary` (Fase 6), só multiplica o
    mensal já calculado por 12."""
    summary = recurring_svc.subscription_summary(workspace)
    return summary["total_active_monthly_cents"] * 12


def all_insights(workspace: FinancialWorkspace, *, today: date | None = None) -> dict:
    return {
        "category_movers": category_movers(workspace, today=today),
        "budget_alerts": budget_alerts(workspace, today=today),
        "bills_due_soon": bills_due_soon(workspace, today=today),
        "goal_pace": goal_pace_insights(workspace),
        "subscriptions_annual_cost_cents": subscriptions_annual_cost_cents(workspace),
    }


# --------------------------------------------------------------------------
# Forecasts -- rotulado como estimativa em todo lugar, pedido explícito
# do documento ("Label projections as estimates")
# --------------------------------------------------------------------------

def cash_flow_forecast(workspace: FinancialWorkspace, *, months_ahead: int = 3,
                        trailing_months: int = 3, today: date | None = None) -> dict:
    """Projeta os próximos `months_ahead` meses usando a média de renda/
    despesa dos últimos `trailing_months` meses JÁ FECHADOS (mesmo padrão
    de `goals_service.average_needs_expenses_cents`) -- nunca finge saber
    o futuro, só extrapola o padrão recente, disclosed como estimativa."""
    today = today or date.today()
    cursor = _first_of_month(today)
    total_income, total_expenses = 0, 0
    for _ in range(trailing_months):
        cursor = _first_of_prev_month(cursor)
        end = _first_of_next_month(cursor) - timedelta(days=1)
        total_income += dash_svc.monthly_income_cents(workspace, start=cursor, end=end)
        total_expenses += dash_svc.monthly_expenses_cents(workspace, start=cursor, end=end)

    avg_income_cents = round(total_income / trailing_months) if trailing_months else 0
    avg_expenses_cents = round(total_expenses / trailing_months) if trailing_months else 0
    avg_net_cents = avg_income_cents - avg_expenses_cents

    months = []
    cursor = _first_of_next_month(today)
    for i in range(months_ahead):
        months.append({
            "label": f"{month_abbr[cursor.month]} {cursor.year}",
            "income_cents": avg_income_cents, "expenses_cents": avg_expenses_cents,
            "net_cents": avg_net_cents, "cumulative_net_cents": avg_net_cents * (i + 1),
        })
        cursor = _first_of_next_month(cursor)

    return {
        "trailing_months": trailing_months, "avg_income_cents": avg_income_cents,
        "avg_expenses_cents": avg_expenses_cents, "avg_net_cents": avg_net_cents, "months": months,
    }


# --------------------------------------------------------------------------
# Calculators -- "what-if", sem precisar de uma Debt/Goal salva
# --------------------------------------------------------------------------

def debt_payoff_calculator(*, balance_cents: int, apr_bps: int, monthly_payment_cents: int,
                            today: date | None = None) -> dict | None:
    """Mesma matemática de `debts_service.payoff_projection` (Fase 8),
    só que sem precisar cadastrar uma dívida de verdade primeiro --
    "e se eu pagasse $X/mês nessa dívida de $Y a Z% de juros?". Reusa
    `debts_service._simulate_payoff` (extraído de `payoff_projection`
    nesta fase pra não duplicar a mesma lógica testada duas vezes)."""
    return debts_svc.simulate_payoff(
        balance_cents=balance_cents, apr_bps=apr_bps, monthly_payment_cents=monthly_payment_cents, today=today)


def goal_savings_calculator(*, target_amount_cents: int, current_amount_cents: int,
                             monthly_contribution_cents: int) -> dict | None:
    """"Quantos meses até bater a meta, nesse ritmo de aporte?" --
    mesma pergunta que `goals_service.goal_progress` responde pra uma
    meta já salva, aqui como calculadora avulsa. `None` quando o aporte
    não é positivo (nunca finge uma resposta pra "$0/mês")."""
    remaining_cents = max(target_amount_cents - current_amount_cents, 0)
    if remaining_cents == 0:
        return {"months_to_reach_target": 0}
    if monthly_contribution_cents <= 0:
        return None
    months = -(-remaining_cents // monthly_contribution_cents)  # teto (ceiling) sem importar math
    return {"months_to_reach_target": int(months), "remaining_cents": remaining_cents}
