"""Blueprint do CRM (staff) -- Clientes, Leads e Casos. Irmão de
app/crm_staff_ops.py (Documentos/Pagamentos/Comunicações/Tarefas) --
blueprint separado (mesmo url_prefix) só pra manter os arquivos
independentes; ambos vivem sob /staff/crm.
"""
from __future__ import annotations

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.crm_models import (Case, CaseStatus, Client, ClientTier, Lead,
                             LeadQuality, LeadSource, LeadStage, ServiceMode,
                             VisaDraftType)
from app.db import SessionLocal
from app.models import User
from app.services import crm_service as svc

crm_pipeline_bp = Blueprint("crm_pipeline", __name__, url_prefix="/staff/crm")

OPEN_CASE_STATUSES = [
    s for s in CaseStatus
    if s not in (CaseStatus.approved, CaseStatus.denied, CaseStatus.gave_up, CaseStatus.lost)
]


@crm_pipeline_bp.before_request
@login_required
def _require_staff():
    if not current_user.is_staff:
        abort(403)


# --------------------------------------------------------------------------
# Casos
# --------------------------------------------------------------------------

@crm_pipeline_bp.route("/casos")
def cases_kanban():
    rows = SessionLocal.query(Case).all()
    by_status: dict[CaseStatus, list[Case]] = {status: [] for status in CaseStatus}
    for c in rows:
        by_status[c.case_status].append(c)
    return render_template(
        "crm_cases_kanban.html", by_status=by_status, statuses=list(CaseStatus),
        days_to_deadline=svc.days_to_deadline)


@crm_pipeline_bp.route("/casos/<int:case_id>/status", methods=["POST"])
def case_status_update(case_id: int):
    case = SessionLocal.get(Case, case_id)
    if case is None:
        abort(404)
    new_status = svc.parse_enum(CaseStatus, request.form.get("case_status"))
    if new_status is None:
        flash("Status inválido.", "error")
        return redirect(request.referrer or url_for("crm_pipeline.cases_kanban"))
    case.case_status = new_status
    SessionLocal.commit()
    return redirect(request.referrer or url_for("crm_pipeline.cases_kanban"))


@crm_pipeline_bp.route("/casos/<int:case_id>/ds160", methods=["POST"])
def case_ds160_gate_update(case_id: int):
    """Liga/desliga o gate do rascunho de DS-160 (app/wizard.py, form_slug
    "ds160") -- enquanto None, o cliente não vê nem consegue abrir esse
    questionário, mesmo sabendo a URL (ver wizard.start)."""
    case = SessionLocal.get(Case, case_id)
    if case is None:
        abort(404)
    case.ds160_visa_type = svc.parse_enum(VisaDraftType, request.form.get("ds160_visa_type"))
    SessionLocal.commit()
    flash("Rascunho DS-160 atualizado.", "success")
    return redirect(request.referrer or url_for("crm_pipeline.client_detail", client_id=case.client_id))


# --------------------------------------------------------------------------
# Leads
# --------------------------------------------------------------------------

@crm_pipeline_bp.route("/leads")
def leads_kanban():
    rows = SessionLocal.query(Lead).all()
    by_stage: dict[LeadStage, list[Lead]] = {stage: [] for stage in LeadStage}
    for lead in rows:
        by_stage[lead.stage].append(lead)

    sources = {s.id: s for s in SessionLocal.query(LeadSource).all()}
    users = {u.id: u for u in SessionLocal.query(User).all()}

    # "Leads por origem" e "Taxa de conversão por origem" -- 2 relatórios
    # simples em HTML/CSS puro (sem JS), agrupando em Python (a lista de
    # leads é pequena o bastante pra não precisar de SQL agregado aqui).
    by_source_name: dict[str, list[Lead]] = {}
    for lead in rows:
        name = sources[lead.lead_source_id].name if lead.lead_source_id in sources else "Sem origem"
        by_source_name.setdefault(name, []).append(lead)
    source_counts = sorted(
        ((name, len(leads)) for name, leads in by_source_name.items()),
        key=lambda item: item[1], reverse=True)
    max_count = max((count for _, count in source_counts), default=1)
    source_conversion = sorted(
        (
            (name, round(100 * sum(1 for l in leads if l.stage == LeadStage.closed_won) / len(leads)))
            for name, leads in by_source_name.items()
        ),
        key=lambda item: item[1], reverse=True)

    return render_template(
        "crm_leads_kanban.html", by_stage=by_stage, stages=list(LeadStage),
        sources=sources, users=users, source_counts=source_counts, max_count=max_count,
        source_conversion=source_conversion)


@crm_pipeline_bp.route("/leads/<int:lead_id>/stage", methods=["POST"])
def lead_stage_update(lead_id: int):
    lead = SessionLocal.get(Lead, lead_id)
    if lead is None:
        abort(404)
    new_stage = svc.parse_enum(LeadStage, request.form.get("stage"))
    if new_stage is None:
        flash("Estágio inválido.", "error")
        return redirect(request.referrer or url_for("crm_pipeline.leads_kanban"))
    if new_stage == LeadStage.closed_won and lead.converted_client_id is None:
        # Fechar um lead sempre passa pela tela de conversão -- não dá pra
        # virar cliente/caso sem antes decidir service_mode e o título do
        # caso (ver lead_convert() abaixo).
        return redirect(url_for("crm_pipeline.lead_convert", lead_id=lead.id))
    lead.stage = new_stage
    SessionLocal.commit()
    return redirect(request.referrer or url_for("crm_pipeline.leads_kanban"))


@crm_pipeline_bp.route("/leads/<int:lead_id>/converter", methods=["GET", "POST"])
def lead_convert(lead_id: int):
    lead = SessionLocal.get(Lead, lead_id)
    if lead is None:
        abort(404)

    if request.method == "POST":
        service_mode = svc.parse_enum(ServiceMode, request.form.get("service_mode"))
        case_title = request.form.get("case_title", "").strip()
        if service_mode is None or not case_title:
            flash("Modo de atendimento e título do caso são obrigatórios.", "error")
            return redirect(url_for("crm_pipeline.lead_convert", lead_id=lead.id))

        client, case = svc.convert_lead_to_client_and_case(
            lead, service_mode=service_mode, case_title=case_title)
        SessionLocal.commit()
        flash(f"Lead convertido -- cliente e caso criados (#{case.id}).", "success")
        return redirect(url_for("crm_pipeline.client_detail", client_id=client.id))

    suggested_title = f"Caso — {lead.name}"
    return render_template(
        "crm_leads_kanban.html", convert_lead=lead, suggested_title=suggested_title,
        service_modes=list(ServiceMode), by_stage={}, stages=[], sources={}, users={},
        source_counts=[], max_count=1, source_conversion=[])


@crm_pipeline_bp.route("/leads/novo", methods=["GET", "POST"])
def lead_new():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Nome é obrigatório.", "error")
            return redirect(url_for("crm_pipeline.lead_new"))

        lead = Lead(
            name=name,
            quality=svc.parse_enum(LeadQuality, request.form.get("quality")),
            lead_source_id=svc.parse_int(request.form.get("lead_source_id")),
            contact_email=request.form.get("contact_email", "").strip() or None,
            contact_phone=request.form.get("contact_phone", "").strip() or None,
            deal_value_cents=svc.parse_dollars_to_cents(request.form.get("deal_value_dollars", "")),
            first_contact_at=svc.today(),
        )
        SessionLocal.add(lead)
        SessionLocal.commit()
        flash("Lead criado.", "success")
        return redirect(url_for("crm_pipeline.leads_kanban"))

    lead_sources = SessionLocal.query(LeadSource).order_by(LeadSource.name).all()
    return render_template(
        "crm_leads_kanban.html", new_form=True, lead_sources=lead_sources, qualities=list(LeadQuality),
        by_stage={}, stages=[], sources={}, users={}, source_counts=[], max_count=1, source_conversion=[])


# --------------------------------------------------------------------------
# Clientes
# --------------------------------------------------------------------------

@crm_pipeline_bp.route("/clientes")
def clients_list():
    q = request.args.get("q", "").strip()
    query = SessionLocal.query(Client)
    if q:
        like = f"%{q}%"
        query = query.filter(
            (Client.full_name.ilike(like)) | (Client.email.ilike(like)))
    clients = query.order_by(Client.full_name).all()

    open_case_counts: dict[int, int] = {}
    for case in SessionLocal.query(Case).filter(Case.case_status.in_(OPEN_CASE_STATUSES)).all():
        open_case_counts[case.client_id] = open_case_counts.get(case.client_id, 0) + 1

    return render_template(
        "crm_clients.html", clients=clients, q=q, open_case_counts=open_case_counts)


@crm_pipeline_bp.route("/clientes/novo", methods=["GET", "POST"])
def client_new():
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        if not full_name:
            flash("Nome é obrigatório.", "error")
            return redirect(url_for("crm_pipeline.client_new"))

        client = Client(
            full_name=full_name,
            email=request.form.get("email", "").strip() or None,
            us_phone=request.form.get("us_phone", "").strip() or None,
            us_phone_has=bool(request.form.get("us_phone", "").strip()),
            tier=svc.parse_enum(ClientTier, request.form.get("tier")),
        )
        SessionLocal.add(client)
        SessionLocal.commit()
        flash("Cliente cadastrado.", "success")
        return redirect(url_for("crm_pipeline.client_detail", client_id=client.id))

    return render_template("crm_clients.html", new_form=True, tiers=list(ClientTier),
                            clients=[], q="", open_case_counts={})


@crm_pipeline_bp.route("/clientes/<int:client_id>")
def client_detail(client_id: int):
    client = SessionLocal.get(Client, client_id)
    if client is None:
        abort(404)
    pending_by_case = {case.id: svc.case_pending_documents(case) for case in client.cases}
    return render_template("crm_client_detail.html", client=client, pending_by_case=pending_by_case)
