"""Aba Dashboard (Prompt Mestre, Fase 3 -- "criar um dashboard
personalizável"), 2026-08-06. Cada widget é {key, title, value, format,
url}: `value` já vem pronto pra exibir (int/dólar-em-centavos/string),
`format` diz ao template como formatá-lo, `url` é pra onde o widget leva
quando clicado ("Clicar nos indicadores para abrir os registros
correspondentes", pedido explícito do documento).

Dois grupos de widget:
- "period" -- dependem do seletor de período (reusa app/services/
  reports_service.py::PERIODS/period_range, mesmo vocabulário de período
  já usado na aba Reports, pra não inventar um segundo).
- "live" -- estado atual, sempre "agora" (ex.: tarefas vencidas, cases
  ativos) -- não faz sentido period Contextualizar um "quantos estão
  atrasados AGORA".

Cada compute function recebe (start, end) mesmo quando não usa (widgets
"live" ignoram os dois argumentos) -- assinatura uniforme, mais simples
que ramificar por grupo na hora de chamar.
"""
from __future__ import annotations

from datetime import date, timedelta

import json

from app.crm_models import (Case, CaseService, CaseStatus, ClientApprovalStatus,
                             Communication, CommStatus, Document, DocumentStatus,
                             DocumentTranslation, Lead, LeadStage, PaymentDirection,
                             PaymentLedgerEntry, PaymentStatus, ServiceRole, Task,
                             TaskStatus)
from app.db import SessionLocal
from app.models import StaffDashboardLayout
from app.services import reports_service as rsvc
from app.services.crm_service import today, translation_client_total_cents

CASE_ACTIVE_STATUSES = [
    s for s in CaseStatus
    if s not in (CaseStatus.approved, CaseStatus.denied, CaseStatus.gave_up, CaseStatus.lost)
]


def _leads_new(start: date, end: date) -> dict:
    count = SessionLocal.query(Lead).filter(
        Lead.created_at >= start, Lead.created_at < end + timedelta(days=1)).count()
    return {"value": count}


def _leads_unanswered(start: date, end: date) -> dict:
    count = SessionLocal.query(Lead).filter(Lead.stage == LeadStage.new).count()
    return {"value": count}


def _proposals_sent(start: date, end: date) -> dict:
    count = SessionLocal.query(Lead).filter(
        Lead.stage == LeadStage.proposal_sent,
        Lead.proposal_at.isnot(None), Lead.proposal_at >= start, Lead.proposal_at <= end).count()
    return {"value": count}


def _deals_won(start: date, end: date) -> dict:
    count = SessionLocal.query(Lead).filter(
        Lead.stage == LeadStage.closed_won,
        Lead.closed_at.isnot(None), Lead.closed_at >= start, Lead.closed_at <= end).count()
    return {"value": count}


def _deals_lost(start: date, end: date) -> dict:
    count = SessionLocal.query(Lead).filter(
        Lead.stage == LeadStage.closed_lost,
        Lead.lost_at.isnot(None), Lead.lost_at >= start, Lead.lost_at <= end).count()
    return {"value": count}


def _cases_active(start: date, end: date) -> dict:
    count = SessionLocal.query(Case).filter(Case.case_status.in_(CASE_ACTIVE_STATUSES)).count()
    return {"value": count}


def _cases_near_deadline(start: date, end: date) -> dict:
    horizon = today() + timedelta(days=14)
    count = SessionLocal.query(Case).filter(
        Case.service_deadline.isnot(None), Case.service_deadline >= today(),
        Case.service_deadline <= horizon, Case.case_status.in_(CASE_ACTIVE_STATUSES)).count()
    return {"value": count}


def _services_expiring(start: date, end: date) -> dict:
    """`Case.status_expire_on` -- vencimento do status em si (ex.: EAD,
    green card), campo diferente de `service_deadline` (prazo do
    SERVIÇO contratado) -- os dois aparecem como widgets separados de
    propósito, mesma distinção que já existe no modelo."""
    horizon = today() + timedelta(days=60)
    count = SessionLocal.query(Case).filter(
        Case.status_expire_on.isnot(None), Case.status_expire_on >= today(),
        Case.status_expire_on <= horizon).count()
    return {"value": count}


def _documents_pending(start: date, end: date) -> dict:
    count = SessionLocal.query(Document).filter(Document.status != DocumentStatus.completed).count()
    return {"value": count}


def _translations_awaiting_quote(start: date, end: date) -> dict:
    count = SessionLocal.query(Document).filter(
        Document.status == DocumentStatus.translation_quote_requested).count()
    return {"value": count}


def _translations_awaiting_approval(start: date, end: date) -> dict:
    rows = SessionLocal.query(DocumentTranslation).filter(
        DocumentTranslation.client_approval_status == ClientApprovalStatus.pending).all()
    count = sum(1 for r in rows if translation_client_total_cents(r) is not None)
    return {"value": count}


def _translations_overdue(start: date, end: date) -> dict:
    count = SessionLocal.query(DocumentTranslation).join(
        Document, DocumentTranslation.document_id == Document.id
    ).filter(
        DocumentTranslation.deadline.isnot(None), DocumentTranslation.deadline < today(),
        Document.status != DocumentStatus.completed).count()
    return {"value": count}


def _tasks_overdue(start: date, end: date) -> dict:
    count = SessionLocal.query(Task).filter(
        Task.due_date.isnot(None), Task.due_date < today(), Task.status != TaskStatus.done).count()
    return {"value": count}


def _tasks_today(start: date, end: date) -> dict:
    count = SessionLocal.query(Task).filter(
        Task.due_date == today(), Task.status != TaskStatus.done).count()
    return {"value": count}


def _clients_need_follow_up(start: date, end: date) -> dict:
    count = (
        SessionLocal.query(Communication.client_id)
        .filter(Communication.status != CommStatus.done,
                Communication.next_followup_at.isnot(None), Communication.next_followup_at <= today())
        .distinct().count()
    )
    return {"value": count}


def _revenue_expected(start: date, end: date) -> dict:
    total = sum(
        p.amount_cents for p in SessionLocal.query(PaymentLedgerEntry).filter(
            PaymentLedgerEntry.direction == PaymentDirection.receivable,
            PaymentLedgerEntry.status.in_(
                [PaymentStatus.pending, PaymentStatus.invoice_sent, PaymentStatus.partially_paid])).all())
    return {"value": total}


def _revenue_confirmed(start: date, end: date) -> dict:
    entries = SessionLocal.query(PaymentLedgerEntry).filter(
        PaymentLedgerEntry.direction == PaymentDirection.receivable,
        PaymentLedgerEntry.status == PaymentStatus.paid).all()
    total = sum(
        p.amount_cents for p in entries
        if start <= (p.payment_date or p.invoice_date or p.created_at.date()) <= end)
    return {"value": total}


def _lead_conversion(start: date, end: date) -> dict:
    won = SessionLocal.query(Lead).filter(
        Lead.stage == LeadStage.closed_won,
        Lead.closed_at.isnot(None), Lead.closed_at >= start, Lead.closed_at <= end).count()
    lost = SessionLocal.query(Lead).filter(
        Lead.stage == LeadStage.closed_lost,
        Lead.lost_at.isnot(None), Lead.lost_at >= start, Lead.lost_at <= end).count()
    total = won + lost
    pct = round(100 * won / total) if total else None
    return {"value": pct}


def _avg_closing_time(start: date, end: date) -> dict:
    leads = SessionLocal.query(Lead).filter(
        Lead.stage == LeadStage.closed_won, Lead.closed_at.isnot(None),
        Lead.closed_at >= start, Lead.closed_at <= end).all()
    days = [(l.closed_at - l.created_at.date()).days for l in leads if l.created_at]
    avg = round(sum(days) / len(days)) if days else None
    return {"value": avg}


def _leads_by_source(start: date, end: date) -> dict:
    return {"rows": rsvc.leads_by_source(start, end)[:6]}


def _cases_by_service(start: date, end: date) -> dict:
    current_service_by_case: dict[int, str] = {
        cs.case_id: cs.service.name
        for cs in SessionLocal.query(CaseService).filter_by(role=ServiceRole.current).all()
    }
    totals: dict[str, int] = {}
    for case in SessionLocal.query(Case).filter(Case.case_status.in_(CASE_ACTIVE_STATUSES)).all():
        name = current_service_by_case.get(case.id, "Uncategorized")
        totals[name] = totals.get(name, 0) + 1
    rows = sorted(
        ({"label": k, "count": v} for k, v in totals.items()), key=lambda r: r["count"], reverse=True)
    return {"rows": rows[:6]}


def _recent_activity(start: date, end: date) -> dict:
    from app.crm_models import AuditLog
    from app.models import User
    rows = SessionLocal.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(8).all()
    users = {u.id: (u.username or u.email) for u in SessionLocal.query(User).all()}
    return {"rows": [
        {"description": r.description or f"{r.action} on {r.entity_type} #{r.entity_id}",
         "user": users.get(r.user_id, "System") if r.user_id else "System",
         "created_at": r.created_at}
        for r in rows
    ]}


# key -> {title, group ("period"|"live"), kind ("stat"|"money"|"pct"|"days"|"list"),
#         compute, endpoint (url_for target, no args) or None}
WIDGETS: dict[str, dict] = {
    "leads_new": {"title": "New leads", "group": "period", "kind": "stat",
                  "compute": _leads_new, "endpoint": "crm_pipeline.leads_kanban"},
    "leads_unanswered": {"title": "Leads with no response yet", "group": "live", "kind": "stat",
                          "compute": _leads_unanswered, "endpoint": "crm_pipeline.leads_kanban"},
    "proposals_sent": {"title": "Proposals sent", "group": "period", "kind": "stat",
                        "compute": _proposals_sent, "endpoint": "crm_pipeline.leads_kanban"},
    "deals_won": {"title": "Deals won", "group": "period", "kind": "stat",
                  "compute": _deals_won, "endpoint": "crm_pipeline.leads_kanban"},
    "deals_lost": {"title": "Deals lost", "group": "period", "kind": "stat",
                   "compute": _deals_lost, "endpoint": "crm_pipeline.leads_kanban"},
    "cases_active": {"title": "Active cases", "group": "live", "kind": "stat",
                      "compute": _cases_active, "endpoint": "crm_pipeline.cases_kanban"},
    "cases_near_deadline": {"title": "Cases near deadline (14 days)", "group": "live", "kind": "stat",
                             "compute": _cases_near_deadline, "endpoint": "crm_pipeline.cases_kanban"},
    "services_expiring": {"title": "Services expiring soon (60 days)", "group": "live", "kind": "stat",
                           "compute": _services_expiring, "endpoint": "crm_pipeline.cases_kanban"},
    "documents_pending": {"title": "Pending documents", "group": "live", "kind": "stat",
                           "compute": _documents_pending, "endpoint": "staff.documents_list"},
    "translations_awaiting_quote": {"title": "Translations awaiting a quote", "group": "live", "kind": "stat",
                                     "compute": _translations_awaiting_quote, "endpoint": "crm_translations.kanban"},
    "translations_awaiting_approval": {"title": "Translations awaiting client approval", "group": "live",
                                        "kind": "stat", "compute": _translations_awaiting_approval,
                                        "endpoint": "crm_translations.kanban"},
    "translations_overdue": {"title": "Overdue translations", "group": "live", "kind": "stat",
                              "compute": _translations_overdue, "endpoint": "crm_translations.kanban"},
    "tasks_overdue": {"title": "Overdue tasks", "group": "live", "kind": "stat",
                       "compute": _tasks_overdue, "endpoint": "crm_ops.tasks"},
    "tasks_today": {"title": "Tasks due today", "group": "live", "kind": "stat",
                     "compute": _tasks_today, "endpoint": "crm_ops.tasks"},
    "clients_need_follow_up": {"title": "Clients needing follow-up", "group": "live", "kind": "stat",
                                "compute": _clients_need_follow_up, "endpoint": "crm_ops.communications_follow_ups"},
    "revenue_expected": {"title": "Expected revenue (open receivables)", "group": "live", "kind": "money",
                          "compute": _revenue_expected, "endpoint": "crm_ops.payments"},
    "revenue_confirmed": {"title": "Confirmed revenue", "group": "period", "kind": "money",
                           "compute": _revenue_confirmed, "endpoint": "crm_ops.payments"},
    "lead_conversion": {"title": "Lead conversion rate", "group": "period", "kind": "pct",
                         "compute": _lead_conversion, "endpoint": "crm_pipeline.leads_kanban"},
    "avg_closing_time": {"title": "Average time to close (days)", "group": "period", "kind": "days",
                          "compute": _avg_closing_time, "endpoint": "crm_pipeline.leads_kanban"},
    "leads_by_source": {"title": "Leads by source", "group": "period", "kind": "list",
                         "compute": _leads_by_source, "endpoint": "crm_reports.dashboard"},
    "cases_by_service": {"title": "Active cases by service", "group": "live", "kind": "list",
                          "compute": _cases_by_service, "endpoint": "crm_pipeline.cases_kanban"},
    "recent_activity": {"title": "Recent activity", "group": "live", "kind": "activity",
                         "compute": _recent_activity, "endpoint": None},
}

# Ordem padrão pra quem nunca customizou (StaffDashboardLayout ainda não
# existe pra esse user_id) -- todos visíveis, nesta ordem.
DEFAULT_WIDGET_ORDER: list[str] = list(WIDGETS.keys())


def compute_widgets(widget_keys: list[str], period: str) -> list[dict]:
    """Computa só os widgets pedidos (a ordem/visibilidade já resolvida
    pelo chamador), na ordem dada -- widgets "period" usam o período
    escolhido, "live" ignoram (sempre "agora")."""
    start, end = rsvc.period_range(period)
    out = []
    for key in widget_keys:
        spec = WIDGETS.get(key)
        if spec is None:
            continue
        result = spec["compute"](start, end)
        out.append({
            "key": key, "title": spec["title"], "kind": spec["kind"], "group": spec["group"],
            "endpoint": spec["endpoint"], **result,
        })
    return out


def resolve_visible_widgets(user_id: int) -> list[str]:
    """Ordem + visibilidade dos widgets pra este colaborador -- sem linha
    salva ainda (nunca customizou), todos os widgets aparecem, na ordem
    de `WIDGETS` acima. Uma vez que o colaborador salva uma lista, ela é
    a fonte da verdade tal como está -- uma chave ausente fica oculta de
    propósito (é assim que "Ocultar widget" é implementado, ver docstring
    do model StaffDashboardLayout) até ele mesmo escolher reexibir pelo
    seletor "+ Add widget"; diferente do nav (app/staff_nav.py), aqui uma
    chave nova no registro NÃO é auto-adicionada de volta pra quem já
    ocultou coisas de propósito."""
    row = SessionLocal.get(StaffDashboardLayout, user_id)
    if row is None:
        return list(DEFAULT_WIDGET_ORDER)
    try:
        saved = json.loads(row.visible_widgets_json)
    except (json.JSONDecodeError, TypeError):
        return list(DEFAULT_WIDGET_ORDER)
    if not isinstance(saved, list):
        return list(DEFAULT_WIDGET_ORDER)

    return [k for k in saved if isinstance(k, str) and k in WIDGETS]


def save_visible_widgets(user_id: int, keys: list[str]) -> None:
    """Grava a ordem/visibilidade -- uma chave AUSENTE da lista fica
    oculta (ver docstring do model StaffDashboardLayout). Não faz
    SessionLocal.commit() sozinha, mesma convenção do resto de
    app/services/ -- quem chama decide."""
    cleaned = [k for k in keys if k in WIDGETS]
    row = SessionLocal.get(StaffDashboardLayout, user_id)
    if row is None:
        row = StaffDashboardLayout(user_id=user_id, visible_widgets_json=json.dumps(cleaned))
        SessionLocal.add(row)
    else:
        row.visible_widgets_json = json.dumps(cleaned)
