"""Fase 3 (Dashboard) do SAES_Financial_Planning_Master_Spec, 2026-08-07
-- KPIs e dados de gráfico pra Visão Geral do workspace self-service.

Reusa `app/services/reports_service.py::PERIODS`/`period_range` (mesmo
seletor de período já usado na aba Reports do staff) em vez de duplicar
essa lógica só pra este módulo -- a própria docstring daquele arquivo já
diz que a função é genérica, não presa ao CRM de imigração.

Escopo desta fase: só o que dá pra calcular com o que já existe (Fase 1/2
-- contas e transações). KPIs/gráficos do documento que dependem de
módulos ainda não construídos (Bills/Fase 5, Debts/Fase 8, Financial
Goals/Fase 7, Budget allocations/Fase 4) ficam de fora aqui, documentados
-- não inventamos zero/placeholder fingindo ser dado real (regra
explícita do documento: "No fake production placeholders").
"""
from __future__ import annotations

from calendar import month_abbr
from datetime import date

from app.crm_financial_models import FinancialWorkspace
from app.db import SessionLocal
from app.financial_planning_models import (Account, BudgetCategory, FinancialTransaction,
                                            TransactionClassification, TransactionStatus,
                                            TransactionType)


def _completed_transactions(workspace: FinancialWorkspace, *, start: date, end: date,
                             transaction_type: TransactionType | None = None):
    query = (
        SessionLocal.query(FinancialTransaction)
        .filter_by(financial_workspace_id=workspace.id, status=TransactionStatus.completed)
        .filter(FinancialTransaction.deleted_at.is_(None))
        .filter(FinancialTransaction.transaction_date >= start, FinancialTransaction.transaction_date <= end)
    )
    if transaction_type is not None:
        query = query.filter(FinancialTransaction.transaction_type == transaction_type)
    return query.all()


def monthly_income_cents(workspace: FinancialWorkspace, *, start: date, end: date) -> int:
    return sum(t.amount_cents for t in _completed_transactions(
        workspace, start=start, end=end, transaction_type=TransactionType.income))


def monthly_expenses_cents(workspace: FinancialWorkspace, *, start: date, end: date) -> int:
    return sum(t.amount_cents for t in _completed_transactions(
        workspace, start=start, end=end, transaction_type=TransactionType.expense))


def savings_rate(workspace: FinancialWorkspace, *, start: date, end: date) -> float | None:
    """§8 do documento: `net_cash_flow / total_income` quando
    `total_income > 0`, senão `None` (não dá pra calcular uma taxa sobre
    renda zero -- mostrar "—" na tela, nunca 0% ou uma divisão por
    zero)."""
    income = monthly_income_cents(workspace, start=start, end=end)
    if income <= 0:
        return None
    expenses = monthly_expenses_cents(workspace, start=start, end=end)
    return (income - expenses) / income


def total_cash_cents(workspace: FinancialWorkspace) -> int:
    accounts = (
        SessionLocal.query(Account)
        .filter_by(financial_workspace_id=workspace.id, include_in_cash_flow=True)
        .filter(Account.deleted_at.is_(None)).all()
    )
    return sum(a.current_balance_cents for a in accounts)


def net_worth_cents(workspace: FinancialWorkspace) -> int:
    """`assets - liabilities` (§8) -- desde a Fase 9 (Net Worth, 2026-08-07)
    subtrai os passivos de verdade (dívidas ativas/inadimplentes, Fase 8)
    em vez de só somar os ativos; reusa `net_worth_service.
    current_net_worth` em vez de duplicar a fórmula aqui."""
    from app.services import net_worth_service
    return net_worth_service.current_net_worth(workspace)["net_worth_cents"]


def spending_by_category(workspace: FinancialWorkspace, *, start: date, end: date) -> list[dict]:
    expenses = _completed_transactions(workspace, start=start, end=end, transaction_type=TransactionType.expense)
    totals: dict[str, int] = {}
    for t in expenses:
        if t.budget_category_id:
            category = SessionLocal.get(BudgetCategory, t.budget_category_id)
            label = category.name if category else "Uncategorized"
        else:
            label = "Uncategorized"
        totals[label] = totals.get(label, 0) + t.amount_cents
    rows = [{"label": label, "amount_cents": amount} for label, amount in totals.items()]
    rows.sort(key=lambda r: r["amount_cents"], reverse=True)
    return rows


def needs_wants_savings_breakdown(workspace: FinancialWorkspace, *, start: date, end: date) -> dict:
    expenses = _completed_transactions(workspace, start=start, end=end, transaction_type=TransactionType.expense)
    breakdown = {"needs": 0, "wants": 0, "savings": 0, "unclassified": 0}
    for t in expenses:
        key = t.classification.value if t.classification else "unclassified"
        breakdown[key] = breakdown.get(key, 0) + t.amount_cents
    return breakdown


def account_distribution(workspace: FinancialWorkspace) -> list[dict]:
    accounts = (
        SessionLocal.query(Account)
        .filter_by(financial_workspace_id=workspace.id)
        .filter(Account.deleted_at.is_(None)).all()
    )
    rows = [{"label": a.nickname or a.account_name, "amount_cents": a.current_balance_cents} for a in accounts]
    rows.sort(key=lambda r: r["amount_cents"], reverse=True)
    return rows


def _first_of_month(d: date) -> date:
    return d.replace(day=1)


def _first_of_next_month(d: date) -> date:
    return date(d.year + 1, 1, 1) if d.month == 12 else date(d.year, d.month + 1, 1)


def _first_of_prev_month(d: date) -> date:
    return date(d.year - 1, 12, 1) if d.month == 1 else date(d.year, d.month - 1, 1)


def cash_flow_by_month(workspace: FinancialWorkspace, *, months: int = 6, today: date | None = None) -> list[dict]:
    """Últimos `months` meses (incluindo o atual), cada um com renda/
    despesa somadas -- alimenta os gráficos "Cash Flow" e "Income vs
    Expenses" (§11) de uma vez só. Mês corrente vai só até hoje (dado
    real disponível); meses fechados vão até o último dia do mês."""
    from datetime import timedelta

    today = today or date.today()
    month_starts = []
    cursor = _first_of_month(today)
    for _ in range(months):
        month_starts.append(cursor)
        cursor = _first_of_prev_month(cursor)
    month_starts.reverse()

    rows = []
    for start in month_starts:
        is_current_month = start.year == today.year and start.month == today.month
        end = today if is_current_month else _first_of_next_month(start) - timedelta(days=1)
        income = monthly_income_cents(workspace, start=start, end=end)
        expenses = monthly_expenses_cents(workspace, start=start, end=end)
        rows.append({
            "label": f"{month_abbr[start.month]} {start.year}",
            "income_cents": income, "expenses_cents": expenses, "net_cents": income - expenses,
        })
    return rows
