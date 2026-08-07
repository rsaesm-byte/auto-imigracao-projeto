"""Agregações da aba Reports (pedido do usuário 2026-08-06): períodos
pré-definidos (semanal/quinzenal/mensal/último mês/últimos 6 meses
comparativo), quebra de Payments por tipo (Payable/Receivable), Leads por
source, e motivos de não-fechamento. Módulo próprio -- a lógica de
agregação não pertence nem a crm_service.py (que é sobre um Case/Lead
individual) nem a uma rota.
"""
from __future__ import annotations

from calendar import month_abbr
from datetime import date, timedelta

from app.crm_models import (Case, CaseService, CaseStatus, CloseLossReason,
                             Document, DocumentStatus, DocumentTranslation,
                             Lead, LeadSource, LeadStage, PaymentDirection,
                             PaymentLedgerEntry, ServiceRole, Task, TaskStatus,
                             Translator, TranslatorPayment)
from app.db import SessionLocal

PERIODS = {
    "week": "Last 7 days",
    "biweekly": "Last 14 days",
    "month": "This month",
    "last_month": "Last month",
    "last_6_months": "Last 6 months (comparison)",
}


def period_range(period: str, today: date | None = None) -> tuple[date, date]:
    """(start, end) inclusive -- `end` é sempre hoje, exceto "last_month"
    (mês fechado anterior)."""
    today = today or date.today()
    if period == "week":
        return today - timedelta(days=6), today
    if period == "biweekly":
        return today - timedelta(days=13), today
    if period == "last_month":
        first_of_this_month = today.replace(day=1)
        last_of_prev_month = first_of_this_month - timedelta(days=1)
        return last_of_prev_month.replace(day=1), last_of_prev_month
    if period == "last_6_months":
        first_of_this_month = today.replace(day=1)
        start_month = first_of_this_month
        for _ in range(5):
            start_month = (start_month - timedelta(days=1)).replace(day=1)
        return start_month, today
    # "month" (default): mês corrente até hoje
    return today.replace(day=1), today


def _payment_period_date(p: PaymentLedgerEntry) -> date | None:
    """Data usada pra decidir se um lançamento "aconteceu" dentro do
    período -- payment_date quando já foi pago, senão invoice_date
    (quando foi solicitado), senão a data de criação do registro."""
    return p.payment_date or p.invoice_date or p.created_at.date()


def payments_by_service(direction: PaymentDirection, start: date, end: date) -> list[dict]:
    """Quebra de Payments (Receivable OU Payable) por serviço contratado
    do Case vinculado -- pedido do usuário 2026-08-06: "receivable/
    payable type vc tem que puxar de acordo com o serviço contratado, por
    isso tem que ter a relação entre case e payment". Vem de Case ->
    CaseService (role=current) -> ServiceCatalog, usando
    PaymentLedgerEntry.case_id -- não de fee_types (esse continua
    existindo como campo na ficha do pagamento, só não é mais o que este
    gráfico usa pra nenhuma das duas direções). Pagamento sem case
    vinculado, ou case sem serviço atual definido, cai em "Uncategorized"
    (mesmo tratamento do resto do relatório: mostrar o que falta
    categorizar, não escondê-lo)."""
    entries = (
        SessionLocal.query(PaymentLedgerEntry)
        .filter(PaymentLedgerEntry.direction == direction)
        .all()
    )
    entries = [p for p in entries if start <= _payment_period_date(p) <= end]

    current_service_by_case: dict[int, str] = {
        cs.case_id: cs.service.name
        for cs in SessionLocal.query(CaseService).filter_by(role=ServiceRole.current).all()
    }

    totals: dict[str, int] = {}
    for p in entries:
        name = current_service_by_case.get(p.case_id, "Uncategorized") if p.case_id else "Uncategorized"
        totals[name] = totals.get(name, 0) + p.amount_cents

    return sorted(
        ({"label": k, "amount_cents": v} for k, v in totals.items()),
        key=lambda row: row["amount_cents"], reverse=True)


def leads_by_source(start: date, end: date) -> list[dict]:
    leads = SessionLocal.query(Lead).all()
    leads = [l for l in leads if l.created_at and start <= l.created_at.date() <= end]
    sources = {s.id: s.name for s in SessionLocal.query(LeadSource).all()}
    totals: dict[str, int] = {}
    for lead in leads:
        name = sources.get(lead.lead_source_id, "No source")
        totals[name] = totals.get(name, 0) + 1
    return sorted(
        ({"label": k, "count": v} for k, v in totals.items()),
        key=lambda row: row["count"], reverse=True)


def leads_missing_source() -> list[Lead]:
    """Leads sem Lead Source preenchido -- pedido do usuário: lista pro
    colaborador completar, pra entrarem no gráfico de sources. Não filtra
    por período de propósito: é uma lista de pendência de cadastro, não
    um relatório de atividade recente."""
    return (
        SessionLocal.query(Lead)
        .filter(Lead.lead_source_id.is_(None))
        .order_by(Lead.created_at.desc())
        .all()
    )


def lost_reasons(start: date, end: date) -> list[dict]:
    leads = (
        SessionLocal.query(Lead)
        .filter(Lead.stage == LeadStage.closed_lost)
        .all()
    )
    leads = [l for l in leads if l.lost_at and start <= l.lost_at <= end]
    reasons = {r.id: r.name for r in SessionLocal.query(CloseLossReason).all()}
    totals: dict[str, int] = {}
    for lead in leads:
        name = reasons.get(lead.close_loss_reason_id, "No reason on file")
        totals[name] = totals.get(name, 0) + 1
    return sorted(
        ({"label": k, "count": v} for k, v in totals.items()),
        key=lambda row: row["count"], reverse=True)


def monthly_comparison(months: int = 6) -> list[dict]:
    """Últimos N meses (mais antigo primeiro) -- total Payable vs
    Receivable por mês, pro gráfico comparativo."""
    today = date.today()
    month_starts = []
    cursor = today.replace(day=1)
    for _ in range(months):
        month_starts.append(cursor)
        cursor = (cursor - timedelta(days=1)).replace(day=1)
    month_starts.reverse()

    all_entries = SessionLocal.query(PaymentLedgerEntry).all()
    rows = []
    for i, start in enumerate(month_starts):
        end = (month_starts[i + 1] - timedelta(days=1)) if i + 1 < len(month_starts) else today
        payable = sum(
            p.amount_cents for p in all_entries
            if p.direction == PaymentDirection.payable and start <= _payment_period_date(p) <= end)
        receivable = sum(
            p.amount_cents for p in all_entries
            if p.direction == PaymentDirection.receivable and start <= _payment_period_date(p) <= end)
        rows.append({
            "label": f"{month_abbr[start.month]} {start.year}",
            "payable_cents": payable, "receivable_cents": receivable,
        })
    return rows


# --------------------------------------------------------------------------
# Novos tipos de relatório -- Prompt Mestre, Fase 9 ("Seção 15" da lista
# original: tradutor, atrasos, renovações), 2026-08-06.
# --------------------------------------------------------------------------

_CASE_ACTIVE_STATUSES = [
    s for s in CaseStatus
    if s not in (CaseStatus.approved, CaseStatus.denied, CaseStatus.gave_up, CaseStatus.lost)
]


def translator_report(start: date, end: date) -> list[dict]:
    """Um relatório de "quanto devemos a cada tradutor" -- pedido do
    documento mestre (relatório por tradutor), que hoje só existia
    espalhado na ficha individual de cada um (crm_translator_detail.html).
    `requested_at` decide se o trabalho "aconteceu" no período (mesma
    convenção de traduções por mês já usada em crm_service.py::
    translations_this_month e afins). Pago é filtrado por `paid_at`,
    somado separado na moeda do próprio tradutor (misturar moedas seria
    enganoso) -- mesma convenção de mostrar as 2 moedas lado a lado que já
    existe em translator_detail.html (payout_usd_cents +
    payout_translator_currency_cents)."""
    from app.services.crm_service import translation_client_total_cents, translation_payout_usd_cents

    translators = SessionLocal.query(Translator).order_by(Translator.full_name).all()
    rows = []
    for tr in translators:
        jobs = [j for j in tr.translations if j.requested_at and start <= j.requested_at <= end]
        if not jobs:
            continue
        payments = [
            p for p in tr.payments
            if start <= p.paid_at <= end and p.currency == tr.currency
        ]
        rows.append({
            "translator": tr,
            "jobs_count": len(jobs),
            "client_revenue_cents": sum(
                (translation_client_total_cents(j) or 0) for j in jobs),
            "payout_owed_usd_cents": sum(
                (translation_payout_usd_cents(j) or 0) for j in jobs),
            "paid_translator_currency_cents": sum(p.amount_cents for p in payments),
            "currency": tr.currency,
        })
    return sorted(rows, key=lambda r: r["payout_owed_usd_cents"], reverse=True)


def overdue_report(today_: date | None = None) -> dict:
    """"Atrasos" -- casos com prazo de serviço vencido, tarefas vencidas,
    traduções com entrega vencida. Diferente dos widgets do Dashboard
    (que só contam), aqui é a LISTA real, pra o relatório servir de
    checklist de ação (pedido do documento mestre: "relatório de
    atrasos")."""
    today_ = today_ or date.today()

    overdue_cases = (
        SessionLocal.query(Case)
        .filter(Case.service_deadline.isnot(None), Case.service_deadline < today_,
                Case.case_status.in_(_CASE_ACTIVE_STATUSES))
        .order_by(Case.service_deadline)
        .all()
    )
    overdue_tasks = (
        SessionLocal.query(Task)
        .filter(Task.due_date.isnot(None), Task.due_date < today_, Task.status != TaskStatus.done)
        .order_by(Task.due_date)
        .all()
    )
    overdue_translations = (
        SessionLocal.query(DocumentTranslation)
        .join(Document, DocumentTranslation.document_id == Document.id)
        .filter(DocumentTranslation.deadline.isnot(None), DocumentTranslation.deadline < today_,
                Document.status != DocumentStatus.completed)
        .order_by(DocumentTranslation.deadline)
        .all()
    )
    return {"cases": overdue_cases, "tasks": overdue_tasks, "translations": overdue_translations}


def renewals_report(days: int = 90, today_: date | None = None) -> list[Case]:
    """Casos cujo STATUS (não o serviço em si -- ver `Case.status_expire_on`,
    ex.: EAD/green card) vence dentro de `days` -- pedido do documento
    mestre ("relatório de renovações"). Ordenado pelo mais urgente
    primeiro."""
    today_ = today_ or date.today()
    horizon = today_ + timedelta(days=days)
    return (
        SessionLocal.query(Case)
        .filter(Case.status_expire_on.isnot(None), Case.status_expire_on >= today_,
                Case.status_expire_on <= horizon)
        .order_by(Case.status_expire_on)
        .all()
    )
