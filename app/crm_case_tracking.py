"""Blueprint do CRM (staff) -- Case Tracking: acompanhamento pós-protocolo
de cada formulário/petição USCIS ligado a um Case (recibo, datas, próxima
checagem, RFE/NOID, correio físico vs. conta online). Irmão de
app/crm_staff_pipeline.py e app/crm_staff_ops.py -- blueprint próprio (mesmo
url_prefix /staff/crm) só pra manter os arquivos independentes.

Pedido do usuário, 2026-08-02: nova aba dentro do painel do colaborador,
linkando pra ficha de case/cliente. Um Case pode ter vários formulários
rastreados ao mesmo tempo (ex.: pacote de Green Card = I-130 + I-485 +
I-765 + I-131) -- por isso CaseTrackedForm é 1:N a partir de Case, não mais
colunas soltas nele (ver docstring do modelo em app/crm_models.py).
"""
from __future__ import annotations

from datetime import datetime, timezone

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.crm_models import (Case, CaseTrackedForm, ClientCredential,
                             CredentialService, FieldOffice, FilingMethod)
from app.db import SessionLocal
from app.models import User
from app.services import audit_service
from app.services import crm_service as svc
from app.services.text_format import markdown_lite_to_html
from app.staff_permissions import require_area

crm_tracking_bp = Blueprint("crm_tracking", __name__, url_prefix="/staff/crm/tracking")

# Links oficiais fixos (pedido do usuário, 2026-08-02) -- nunca guardados
# como coluna, sempre os mesmos para todo formulário rastreado.
USCIS_CASE_STATUS_URL = "https://egov.uscis.gov/"
USCIS_PROCESSING_TIMES_URL = "https://egov.uscis.gov/processing-times"
USCIS_FIELD_OFFICE_LOCATOR_URL = "https://www.uscis.gov/about-us/find-a-uscis-office/field-offices"
USPS_TRACKING_URL = "https://tools.usps.com/zip-code-lookup.htm"


@crm_tracking_bp.before_request
@login_required
def _require_staff():
    if not current_user.is_staff:
        abort(403)
    require_area("crm")


def _overdue(tracked: CaseTrackedForm) -> bool:
    return tracked.next_check_at is not None and tracked.next_check_at <= svc.today()


@crm_tracking_bp.route("/")
def dashboard():
    """A aba nova em si -- uma linha por formulário rastreado, em todos os
    casos, ordenada pela checagem mais urgente primeiro, linkando pra ficha
    de case e de cliente (pedido explícito do usuário)."""
    rows = SessionLocal.query(CaseTrackedForm).all()
    rows.sort(key=lambda t: (t.next_check_at is None, t.next_check_at or t.created_at.date()))

    field_offices = {fo.id: fo for fo in SessionLocal.query(FieldOffice).all()}
    overdue_count = sum(1 for t in rows if _overdue(t))
    rfe_count = sum(1 for t in rows if t.rfe_received)

    return render_template(
        "crm_tracking_dashboard.html", rows=rows, field_offices=field_offices,
        overdue_count=overdue_count, rfe_count=rfe_count, is_overdue=_overdue)


@crm_tracking_bp.route("/casos/<int:case_id>")
def case_tracking(case_id: int):
    case = SessionLocal.get(Case, case_id)
    if case is None:
        abort(404)

    field_offices = SessionLocal.query(FieldOffice).order_by(FieldOffice.name).all()
    uscis_credential = (
        SessionLocal.query(ClientCredential)
        .filter_by(client_id=case.client_id, service=CredentialService.uscis)
        .first()
    )
    notes_html = {t.id: markdown_lite_to_html(t.notes_markdown) for t in case.tracked_forms}
    processing_time = {t.id: svc.tracked_form_processing_time_days(t) for t in case.tracked_forms}
    tracked_history = {t.id: audit_service.get_history("CaseTrackedForm", t.id) for t in case.tracked_forms}
    history_users = {u.id: u for u in SessionLocal.query(User).all()}

    return render_template(
        "crm_case_tracking.html", case=case, field_offices=field_offices,
        filing_methods=list(FilingMethod), uscis_credential=uscis_credential,
        notes_html=notes_html, processing_time=processing_time, is_overdue=_overdue,
        uscis_case_status_url=USCIS_CASE_STATUS_URL,
        uscis_processing_times_url=USCIS_PROCESSING_TIMES_URL,
        uscis_field_office_url=USCIS_FIELD_OFFICE_LOCATOR_URL,
        usps_tracking_url=USPS_TRACKING_URL,
        tracked_history=tracked_history, history_users=history_users)


@crm_tracking_bp.route("/field-offices/novo", methods=["POST"])
def field_office_new():
    """"Adicionar field office além dos já listados" (pedido do usuário
    2026-08-06) -- FieldOffice é tabela de lookup aberta (não enum), mas
    até agora só era populada pelo seed inicial (data/crm_lookups.json),
    sem UI nenhuma pra crescer. Cada nova entrada fica salva na lista de
    verdade (nome único) e passa a aparecer no <select> de toda tela que
    usa field office (aqui, no dashboard de tracking, e futuramente em
    Case details -- ver app/crm_staff_ops.py::case_details_update)."""
    name = request.form.get("name", "").strip()
    if not name:
        flash("Field office name is required.", "error")
        return redirect(request.referrer or url_for("crm_tracking.dashboard"))

    existing = SessionLocal.query(FieldOffice).filter_by(name=name).first()
    if existing is not None:
        flash(f'"{name}" is already in the list.', "error")
        return redirect(request.referrer or url_for("crm_tracking.dashboard"))

    office = FieldOffice(name=name, address=request.form.get("address", "").strip() or None)
    SessionLocal.add(office)
    SessionLocal.flush()
    audit_service.log_change("FieldOffice", office.id, "create",
                              description=f"Field office '{name}' added", user_id=current_user.id)
    SessionLocal.commit()
    flash(f'"{name}" added to field offices.', "success")
    return redirect(request.referrer or url_for("crm_tracking.dashboard"))


def _apply_form(tracked: CaseTrackedForm) -> None:
    """Preenche `tracked` a partir de request.form -- compartilhado por
    tracking_new() (formulário novo) e tracking_save() (edição), já que os
    dois recebem exatamente os mesmos campos do mesmo card."""
    tracked.form_number = request.form.get("form_number", "").strip() or tracked.form_number
    tracked.application_type = request.form.get("application_type", "").strip() or None
    tracked.filing_method = svc.parse_enum(
        FilingMethod, request.form.get("filing_method"), default=FilingMethod.online)
    tracked.field_office_id = svc.parse_int(request.form.get("field_office_id"))

    tracked.receipt_number = request.form.get("receipt_number", "").strip() or None
    tracked.receipt_date = svc.parse_date(request.form.get("receipt_date"))
    tracked.finalized_at = svc.parse_date(request.form.get("finalized_at"))
    tracked.monitoring_started_at = svc.parse_date(request.form.get("monitoring_started_at"))
    tracked.approval_date = svc.parse_date(request.form.get("approval_date"))
    tracked.rfe_received = request.form.get("rfe_received") == "on"

    tracked.uscis_received_at = svc.parse_date(request.form.get("uscis_received_at"))
    tracked.expected_arrival_at = svc.parse_date(request.form.get("expected_arrival_at"))
    tracked.actual_arrival_at = svc.parse_date(request.form.get("actual_arrival_at"))
    tracked.usps_tracking_number = request.form.get("usps_tracking_number", "").strip() or None

    tracked.notes_markdown = request.form.get("notes_markdown", "").strip() or None


@crm_tracking_bp.route("/casos/<int:case_id>/novo", methods=["POST"])
def tracking_new(case_id: int):
    """Botão "+ Add form" -- só pede o número do formulário (e opcionalmente
    o tipo de aplicação); tudo o mais (filing method, field office) nasce
    clonado do último formulário já rastreado no caso, pedido explícito do
    usuário ("para ser rastreado com as mesmas informações e características
    do anterior"). Datas/recibo/checagem começam em branco -- são só do novo
    formulário, nunca copiadas -- e se editam depois pelo card normal."""
    case = SessionLocal.get(Case, case_id)
    if case is None:
        abort(404)

    form_number = request.form.get("form_number", "").strip()
    if not form_number:
        flash("Form number is required.", "error")
        return redirect(url_for("crm_tracking.case_tracking", case_id=case_id))

    previous = case.tracked_forms[-1] if case.tracked_forms else None
    tracked = CaseTrackedForm(
        case_id=case.id, form_number=form_number,
        filing_method=previous.filing_method if previous else FilingMethod.online,
        field_office_id=previous.field_office_id if previous else None,
        application_type=request.form.get("application_type", "").strip() or
        (previous.application_type if previous else None),
    )
    SessionLocal.add(tracked)
    SessionLocal.flush()
    audit_service.log_change("CaseTrackedForm", tracked.id, "create",
                              description=f"Now tracking {tracked.form_number}", user_id=current_user.id)
    SessionLocal.commit()
    flash(f"Now tracking {tracked.form_number}.", "success")
    return redirect(url_for("crm_tracking.case_tracking", case_id=case_id))


TRACKED_FORM_TRACKED_FIELDS = [
    "form_number", "application_type", "filing_method", "field_office_id", "receipt_number",
    "receipt_date", "finalized_at", "monitoring_started_at", "approval_date", "rfe_received",
    "uscis_received_at", "expected_arrival_at", "actual_arrival_at", "usps_tracking_number",
    "notes_markdown",
]


@crm_tracking_bp.route("/<int:tracked_id>/salvar", methods=["POST"])
def tracking_save(tracked_id: int):
    tracked = SessionLocal.get(CaseTrackedForm, tracked_id)
    if tracked is None:
        abort(404)
    before = {f: getattr(tracked, f) for f in TRACKED_FORM_TRACKED_FIELDS}
    _apply_form(tracked)
    changes = {f: (before[f], getattr(tracked, f)) for f in TRACKED_FORM_TRACKED_FIELDS}
    audit_service.log_field_changes("CaseTrackedForm", tracked.id, changes, user_id=current_user.id)
    SessionLocal.commit()
    flash(f"{tracked.form_number} updated.", "success")
    return redirect(url_for("crm_tracking.case_tracking", case_id=tracked.case_id))


@crm_tracking_bp.route("/<int:tracked_id>/checar", methods=["POST"])
def tracking_check(tracked_id: int):
    """Botão "Register check" -- grava o momento exato (data + hora) e
    agenda a próxima checagem para 7 dias depois (ver
    app/services/crm_service.py::register_tracked_form_check)."""
    tracked = SessionLocal.get(CaseTrackedForm, tracked_id)
    if tracked is None:
        abort(404)
    svc.register_tracked_form_check(tracked, now=datetime.now(timezone.utc))
    audit_service.log_change("CaseTrackedForm", tracked.id, "status_check",
                              description="Check registered — next check in 7 days", user_id=current_user.id)
    SessionLocal.commit()
    flash(f"Check registered for {tracked.form_number}. Next check in 7 days.", "success")
    return redirect(request.referrer or url_for("crm_tracking.case_tracking", case_id=tracked.case_id))


@crm_tracking_bp.route("/<int:tracked_id>/excluir", methods=["POST"])
def tracking_delete(tracked_id: int):
    tracked = SessionLocal.get(CaseTrackedForm, tracked_id)
    if tracked is None:
        abort(404)
    case_id = tracked.case_id
    audit_service.log_change("CaseTrackedForm", tracked.id, "delete",
                              description=f"{tracked.form_number} removed", user_id=current_user.id)
    SessionLocal.delete(tracked)
    SessionLocal.commit()
    flash("Tracked form removed.", "success")
    return redirect(url_for("crm_tracking.case_tracking", case_id=case_id))
