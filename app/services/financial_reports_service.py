"""Fase 11 (Reports) do SAES_Financial_Planning_Master_Spec, 2026-08-07 --
Monthly Financial Summary (§12), com todos os 12 campos que o documento
lista pra este relatório específico, comparação com o período anterior,
e exportação CSV/PDF.

Escopo, decidido antes de codar (§18 desta fase só diz "monthly reports,
comparisons, exports"): o documento nomeia 11 tipos de relatório (§12
"Tipos"), mas só dá o detalhamento completo de campos pra UM deles --
"Monthly Financial Summary". Os outros 10 (Income/Expense/Budget/Cash
Flow/Savings/Debt/Bill Payment/Recurring Expenses/Net Worth/Financial
Goal Report) já têm cada um sua própria tela com dado real e ao vivo
(Budget→/orcamento, Bills→/contas-a-pagar, Debts→/dividas, Goals→/metas,
Net Worth→/patrimonio, Recurring→/recorrentes) -- construir mais 10
telas de "relatório imprimível" separadas seria escopo repetido, não
uma entrega nova. Esta fase entrega o que É novo: o resumo mensal
cruzando todas as áreas num documento só, com comparação de período e
exportação -- e §13 (Smart Insights) fica pra Fase 12, não esta.
"""
from __future__ import annotations

import csv
import io
from datetime import date, timedelta

from app.crm_financial_models import FinancialWorkspace
from app.db import SessionLocal
from app.financial_planning_models import (Bill, BillPayment, BillPaymentStatus, BudgetPeriod, Debt,
                                            DebtPayment, FinancialGoal, GoalContribution, SavedReportView)
from app.services import budget_service as budget_svc
from app.services import financial_dashboard_service as dash_svc
from app.services import net_worth_service as networth_svc
from app.services.formatting import format_percent, format_usd

PERIODS = {
    "this_month": "This Month",
    "last_month": "Last Month",
    "last_3_months": "Last 3 Months",
    "last_6_months": "Last 6 Months",
    "ytd": "Year to Date",
    "last_12_months": "Last 12 Months",
}


def _first_of_month(d: date) -> date:
    return d.replace(day=1)


def _months_back(d: date, months: int) -> date:
    month_index = d.month - 1 - months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)


def period_range(period: str, *, today: date | None = None) -> tuple[date, date]:
    """(start, end) inclusive. "Custom" não tem uma entrada aqui de
    propósito -- vem direto do formulário (start/end), validado na
    rota."""
    today = today or date.today()
    if period == "last_month":
        last_of_prev = _first_of_month(today) - timedelta(days=1)
        return _first_of_month(last_of_prev), last_of_prev
    if period == "last_3_months":
        return _months_back(today, 2), today
    if period == "last_6_months":
        return _months_back(today, 5), today
    if period == "ytd":
        return date(today.year, 1, 1), today
    if period == "last_12_months":
        return _months_back(today, 11), today
    return _first_of_month(today), today  # "this_month" (padrão)


def previous_period_range(start: date, end: date) -> tuple[date, date]:
    """Janela imediatamente anterior, do MESMO TAMANHO (em dias) --
    regra única pra qualquer período (mês corrente, últimos 3/6/12
    meses, YTD, ou um custom qualquer), em vez de uma regra por tipo de
    período. Simples e previsível, disclosed na própria tela como "vs.
    previous N days"."""
    length = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=length - 1)
    return prev_start, prev_end


# --------------------------------------------------------------------------
# Monthly Financial Summary (§12)
# --------------------------------------------------------------------------

def _debt_reduction_cents(workspace: FinancialWorkspace, *, start: date, end: date) -> int:
    payments = (
        SessionLocal.query(DebtPayment).join(Debt, DebtPayment.debt_id == Debt.id)
        .filter(Debt.financial_workspace_id == workspace.id)
        .filter(DebtPayment.payment_date >= start, DebtPayment.payment_date <= end).all()
    )
    return sum(p.principal_amount_cents if p.principal_amount_cents is not None else p.amount_cents
               for p in payments)


def _goal_contributions_cents(workspace: FinancialWorkspace, *, start: date, end: date) -> int:
    contributions = (
        SessionLocal.query(GoalContribution).join(FinancialGoal, GoalContribution.goal_id == FinancialGoal.id)
        .filter(FinancialGoal.financial_workspace_id == workspace.id)
        .filter(GoalContribution.contribution_date >= start, GoalContribution.contribution_date <= end).all()
    )
    return sum(c.amount_cents for c in contributions)


def _bills_paid_and_overdue(workspace: FinancialWorkspace, *, start: date, end: date) -> dict:
    payments = (
        SessionLocal.query(BillPayment).join(Bill, BillPayment.bill_id == Bill.id)
        .filter(Bill.financial_workspace_id == workspace.id)
        .filter(BillPayment.due_date >= start, BillPayment.due_date <= end).all()
    )
    _not_yet_settled = (BillPaymentStatus.paid, BillPaymentStatus.skipped, BillPaymentStatus.cancelled)
    paid = sum(1 for p in payments if p.status == BillPaymentStatus.paid)
    overdue = sum(1 for p in payments if p.status not in _not_yet_settled and p.due_date < date.today())
    return {"bills_paid_count": paid, "bills_overdue_count": overdue}


def _budget_performance(workspace: FinancialWorkspace, *, start: date, end: date) -> list[dict] | None:
    """Só faz sentido quando o período pedido cabe DENTRO de um único mês
    calendário (BudgetPeriod é sempre mensal) -- `None` (não `[]`) pra
    período custom cruzando meses, disclosed na tela em vez de fingir um
    resultado vazio. Não exige que o período cubra o mês INTEIRO -- "This
    Month" (que sempre termina hoje, não no fim do mês) precisa mostrar
    Budget Performance normalmente, igual à própria tela /orcamento (que
    também sempre usa o mês inteiro do `BudgetPeriod`, não o dia de
    hoje) -- achado testando "This Month" ao vivo e vendo a ressalva
    aparecer quando não devia."""
    same_calendar_month = start.year == end.year and start.month == end.month
    if not same_calendar_month:
        return None
    period = SessionLocal.query(BudgetPeriod).filter_by(
        financial_workspace_id=workspace.id, period_start=_first_of_month(start)).first()
    if period is None:
        return None
    return budget_svc.budget_vs_actual(workspace, period)


def monthly_summary(workspace: FinancialWorkspace, *, start: date, end: date) -> dict:
    income_cents = dash_svc.monthly_income_cents(workspace, start=start, end=end)
    expenses_cents = dash_svc.monthly_expenses_cents(workspace, start=start, end=end)
    savings_cents = income_cents - expenses_cents
    savings_rate = (savings_cents / income_cents) if income_cents > 0 else None

    net_worth_end = networth_svc.net_worth_as_of(workspace, end)
    net_worth_start = networth_svc.net_worth_as_of(workspace, start - timedelta(days=1))
    net_worth_change_cents = (
        net_worth_end["net_worth_cents"] - net_worth_start["net_worth_cents"]
        if net_worth_end is not None and net_worth_start is not None else None)

    bills = _bills_paid_and_overdue(workspace, start=start, end=end)

    return {
        "start": start, "end": end,
        "income_cents": income_cents, "expenses_cents": expenses_cents,
        "savings_cents": savings_cents, "savings_rate": savings_rate,
        "budget_performance": _budget_performance(workspace, start=start, end=end),
        "debt_reduction_cents": _debt_reduction_cents(workspace, start=start, end=end),
        "goal_contributions_cents": _goal_contributions_cents(workspace, start=start, end=end),
        "net_worth_change_cents": net_worth_change_cents,
        "bills_paid_count": bills["bills_paid_count"], "bills_overdue_count": bills["bills_overdue_count"],
        "largest_expense_categories": dash_svc.spending_by_category(workspace, start=start, end=end)[:5],
    }


def monthly_summary_with_comparison(workspace: FinancialWorkspace, *, start: date, end: date) -> dict:
    current = monthly_summary(workspace, start=start, end=end)
    prev_start, prev_end = previous_period_range(start, end)
    previous = monthly_summary(workspace, start=prev_start, end=prev_end)
    current["previous"] = previous
    current["previous_period_label"] = f"{prev_start.strftime('%m/%d/%Y')} – {prev_end.strftime('%m/%d/%Y')}"
    return current


# --------------------------------------------------------------------------
# Exportação
# --------------------------------------------------------------------------

def to_csv_bytes(summary: dict) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Monthly Financial Summary", f"{summary['start'].isoformat()} to {summary['end'].isoformat()}"])
    writer.writerow([])
    writer.writerow(["Metric", "Value"])
    writer.writerow(["Income", format_usd(summary["income_cents"])])
    writer.writerow(["Expenses", format_usd(summary["expenses_cents"])])
    writer.writerow(["Savings", format_usd(summary["savings_cents"])])
    writer.writerow(["Savings Rate", format_percent(summary["savings_rate"] * 100) if summary["savings_rate"] is not None else "—"])
    writer.writerow(["Debt Reduction", format_usd(summary["debt_reduction_cents"])])
    writer.writerow(["Goal Contributions", format_usd(summary["goal_contributions_cents"])])
    writer.writerow(["Net Worth Change", format_usd(summary["net_worth_change_cents"]) if summary["net_worth_change_cents"] is not None else "not enough history"])
    writer.writerow(["Bills Paid", summary["bills_paid_count"]])
    writer.writerow(["Bills Overdue", summary["bills_overdue_count"]])
    writer.writerow([])
    writer.writerow(["Largest Expense Categories"])
    for row in summary["largest_expense_categories"]:
        writer.writerow([row["label"], format_usd(row["amount_cents"])])
    if summary.get("budget_performance") is not None:
        writer.writerow([])
        writer.writerow(["Budget Performance", "Planned", "Actual", "Remaining"])
        for row in summary["budget_performance"]:
            writer.writerow([
                row["category"].name if row["category"] else "—",
                format_usd(row["planned_cents"]), format_usd(row["actual_cents"]), format_usd(row["remaining_cents"])])
    return buffer.getvalue().encode("utf-8")


def render_pdf_bytes(summary: dict) -> bytes:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    y = height - 60

    def line(text: str, *, size: int = 11, bold: bool = False, gap: int = 18):
        nonlocal y
        pdf.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        pdf.drawString(50, y, text)
        y -= gap

    line("Monthly Financial Summary", size=16, bold=True, gap=24)
    line(f"{summary['start'].strftime('%m/%d/%Y')} – {summary['end'].strftime('%m/%d/%Y')}", gap=24)

    line(f"Income: {format_usd(summary['income_cents'])}")
    line(f"Expenses: {format_usd(summary['expenses_cents'])}")
    line(f"Savings: {format_usd(summary['savings_cents'])}")
    rate = format_percent(summary["savings_rate"] * 100) if summary["savings_rate"] is not None else "—"
    line(f"Savings Rate: {rate}")
    line(f"Debt Reduction: {format_usd(summary['debt_reduction_cents'])}")
    line(f"Goal Contributions: {format_usd(summary['goal_contributions_cents'])}")
    nw = format_usd(summary["net_worth_change_cents"]) if summary["net_worth_change_cents"] is not None else "not enough history"
    line(f"Net Worth Change: {nw}")
    line(f"Bills Paid: {summary['bills_paid_count']}")
    line(f"Bills Overdue: {summary['bills_overdue_count']}")

    y -= 10
    line("Largest Expense Categories", bold=True, gap=18)
    for row in summary["largest_expense_categories"]:
        line(f"  {row['label']}: {format_usd(row['amount_cents'])}")

    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


# --------------------------------------------------------------------------
# Saved views (Fase 12 -- "saved views", ver docstring de SavedReportView)
# --------------------------------------------------------------------------

def list_saved_views(workspace: FinancialWorkspace) -> list[SavedReportView]:
    return (
        SessionLocal.query(SavedReportView).filter_by(financial_workspace_id=workspace.id)
        .order_by(SavedReportView.created_at.desc()).all()
    )


def create_saved_view(
    workspace: FinancialWorkspace, *, actor, name: str, period: str,
    custom_start: date | None = None, custom_end: date | None = None,
) -> SavedReportView:
    view = SavedReportView(
        financial_workspace_id=workspace.id, name=name, period=period,
        custom_start=custom_start if period == "custom" else None,
        custom_end=custom_end if period == "custom" else None,
        created_by_id=getattr(actor, "id", None),
    )
    SessionLocal.add(view)
    SessionLocal.commit()
    return view


def delete_saved_view(view: SavedReportView) -> None:
    SessionLocal.delete(view)
    SessionLocal.commit()
