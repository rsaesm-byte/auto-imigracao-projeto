"""Regras de negócio do Coaching Financeiro (CRM Fase 2). Espelha
`app/services/crm_service.py` (Fase 1): campos calculados nunca gravados
como coluna (ver docstring de app/crm_financial_models.py) e
`monthly_financial_kpis()` substitui a tabela "Saes KPIs Mensal" do Notion
por uma função agregada -- KPI é dado derivado, não estado gravado.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from calendar import monthrange

from app.crm_financial_models import (CoachingSession, FinancialClient,
                                       FinancialClientStatus, FinancialTask)
from app.crm_models import PaymentLedgerEntry, PaymentStatus, TaskStatus
from app.db import SessionLocal

# Estágios do funil em que o lead ainda NÃO é um cliente pagante -- usado
# por is_converted() abaixo. "lost_client" também não conta como convertido,
# mesmo já tendo passado por outros estágios antes.
_NOT_CONVERTED_STATUSES = {
    FinancialClientStatus.new_lead, FinancialClientStatus.proposal_sent,
    FinancialClientStatus.consultation_scheduled, FinancialClientStatus.lost_client,
}


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    last_day = monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


# --------------------------------------------------------------------------
# Campos calculados por FinancialClient -- nunca gravados como coluna
# --------------------------------------------------------------------------

def is_converted(fc: FinancialClient) -> bool:
    return fc.client_status not in _NOT_CONVERTED_STATUSES


def days_to_close(fc: FinancialClient) -> int | None:
    if fc.first_contact_at is None or fc.closed_at is None:
        return None
    return (fc.closed_at - fc.first_contact_at).days


def net_worth_cents(fc: FinancialClient) -> int | None:
    if fc.total_assets_cents is None and fc.total_liabilities_cents is None:
        return None
    return (fc.total_assets_cents or 0) - (fc.total_liabilities_cents or 0)


def amount_paid_cents(fc: FinancialClient) -> int:
    """Soma dos lançamentos pagos no ledger reusado (ver
    app/crm_models.py::PaymentLedgerEntry.financial_client_id) -- nunca um
    "Amount Paid" gravado à parte, que poderia divergir do ledger real."""
    total = (
        SessionLocal.query(PaymentLedgerEntry)
        .filter_by(financial_client_id=fc.id, status=PaymentStatus.paid)
        .with_entities(PaymentLedgerEntry.amount_cents)
        .all()
    )
    return sum(row[0] for row in total)


def remaining_balance_cents(fc: FinancialClient) -> int | None:
    if fc.package_value_cents is None:
        return None
    return fc.package_value_cents - amount_paid_cents(fc)


def financial_payment_status(fc: FinancialClient) -> PaymentStatus | None:
    """Deriva um status simples a partir do ledger -- None quando não há
    pacote vendido ainda (nada pra avaliar)."""
    if not fc.package_value_cents:
        return None
    paid = amount_paid_cents(fc)
    if paid >= fc.package_value_cents:
        return PaymentStatus.paid
    if paid > 0:
        return PaymentStatus.partially_paid
    return PaymentStatus.pending


def last_payment_at(fc: FinancialClient) -> date | None:
    row = (
        SessionLocal.query(PaymentLedgerEntry.payment_date)
        .filter_by(financial_client_id=fc.id, status=PaymentStatus.paid)
        .filter(PaymentLedgerEntry.payment_date.is_not(None))
        .order_by(PaymentLedgerEntry.payment_date.desc())
        .first()
    )
    return row[0] if row else None


def sessions_completed(fc: FinancialClient) -> int:
    return SessionLocal.query(CoachingSession).filter_by(financial_client_id=fc.id, completed=True).count()


def sessions_remaining(fc: FinancialClient) -> int | None:
    if fc.total_sessions_purchased is None:
        return None
    return max(fc.total_sessions_purchased - sessions_completed(fc), 0)


def completion_pct(fc: FinancialClient) -> float | None:
    if not fc.total_sessions_purchased:
        return None
    return round(sessions_completed(fc) / fc.total_sessions_purchased * 100, 1)


def last_session_at(fc: FinancialClient) -> datetime | None:
    row = (
        SessionLocal.query(CoachingSession.session_date)
        .filter_by(financial_client_id=fc.id, completed=True)
        .filter(CoachingSession.session_date.is_not(None))
        .order_by(CoachingSession.session_date.desc())
        .first()
    )
    return row[0] if row else None


def next_session_at(fc: FinancialClient) -> datetime | None:
    row = (
        SessionLocal.query(CoachingSession.session_date)
        .filter_by(financial_client_id=fc.id, completed=False)
        .filter(CoachingSession.session_date.is_not(None))
        .order_by(CoachingSession.session_date.asc())
        .first()
    )
    return row[0] if row else None


def pending_financial_tasks(fc: FinancialClient) -> list[FinancialTask]:
    """Tarefas de casa ainda não concluídas -- alimenta tanto a tela do
    coach quanto o painel "Meu Plano Financeiro" do cliente."""
    return [t for t in fc.tasks if t.status != TaskStatus.done]


# --------------------------------------------------------------------------
# Campo calculado por CoachingSession
# --------------------------------------------------------------------------

def homework_completion_pct(session: CoachingSession) -> float | None:
    if not session.tasks:
        return None
    done = sum(1 for t in session.tasks if t.status == TaskStatus.done)
    return round(done / len(session.tasks) * 100, 1)


# --------------------------------------------------------------------------
# KPIs mensais -- substitui a tabela "Saes KPIs Mensal" do Notion (era uma
# linha por mês mantida manualmente via relation->rollup->formula). Aqui é
# uma consulta agregada sobre os dados já existentes, sem nenhum estado
# próprio pra manter sincronizado.
#
# Convenção de "mês" de cada métrica (o Notion original também não tinha
# uma regra explícita além de "atribuir o cliente ao mês certo" --
# aqui cada métrica usa a data que faz sentido pra ela):
# leads/conversão -> first_contact_at / closed_at; receita -> payment_date;
# clientes ativos/adesão -> snapshot atual (client_status agora, não do mês).
# --------------------------------------------------------------------------

def monthly_financial_kpis(year: int, month: int) -> dict:
    start, end = _month_bounds(year, month)

    number_of_leads = (
        SessionLocal.query(FinancialClient)
        .filter(FinancialClient.first_contact_at.between(start, end)).count()
    )
    closed_this_month = (
        SessionLocal.query(FinancialClient)
        .filter(FinancialClient.closed_at.between(start, end)).all()
    )
    leads_converted = sum(1 for fc in closed_this_month if is_converted(fc))
    conversion_rate = round(leads_converted / number_of_leads * 100, 1) if number_of_leads else None

    active_clients = (
        SessionLocal.query(FinancialClient)
        .filter_by(client_status=FinancialClientStatus.active_6_sessions).count()
    )

    revenue_cents = (
        SessionLocal.query(PaymentLedgerEntry)
        .filter(PaymentLedgerEntry.financial_client_id.is_not(None),
                PaymentLedgerEntry.status == PaymentStatus.paid,
                PaymentLedgerEntry.payment_date.between(start, end))
        .with_entities(PaymentLedgerEntry.amount_cents).all()
    )
    total_revenue_cents = sum(row[0] for row in revenue_cents)

    deal_values = [fc.package_value_cents for fc in closed_this_month if fc.package_value_cents]
    average_deal_size_cents = round(sum(deal_values) / len(deal_values)) if deal_values else None

    close_days = [days_to_close(fc) for fc in closed_this_month]
    close_days = [d for d in close_days if d is not None]
    average_days_to_close = round(sum(close_days) / len(close_days), 1) if close_days else None

    nps_values = [fc.nps_score for fc in closed_this_month if fc.nps_score is not None]
    nps_average = round(sum(nps_values) / len(nps_values), 1) if nps_values else None

    with_adherence = SessionLocal.query(FinancialClient).filter(
        FinancialClient.homework_adherence.is_not(None)).all()
    high_adherence = sum(1 for fc in with_adherence if fc.homework_adherence.value == "high")
    avg_homework_adherence_pct = (
        round(high_adherence / len(with_adherence) * 100, 1) if with_adherence else None)

    completed_program = SessionLocal.query(FinancialClient).filter_by(
        client_status=FinancialClientStatus.completed_program).all()
    with_continuity = sum(1 for fc in completed_program if fc.continuity_program.value != "none")
    continuity_adoption_rate = (
        round(with_continuity / len(completed_program) * 100, 1) if completed_program else None)

    return {
        "month": f"{year:04d}-{month:02d}",
        "number_of_leads": number_of_leads,
        "leads_converted": leads_converted,
        "conversion_rate_pct": conversion_rate,
        "active_clients": active_clients,
        "total_revenue_cents": total_revenue_cents,
        "average_deal_size_cents": average_deal_size_cents,
        "average_days_to_close": average_days_to_close,
        "nps_average": nps_average,
        "avg_homework_adherence_pct": avg_homework_adherence_pct,
        "continuity_adoption_rate_pct": continuity_adoption_rate,
    }
