"""Blueprint do CRM (staff) -- Clientes, Leads e Casos. Irmão de
app/crm_staff_ops.py (Documentos/Pagamentos/Comunicações/Tarefas) --
blueprint separado (mesmo url_prefix) só pra manter os arquivos
independentes; ambos vivem sob /staff/crm.
"""
from __future__ import annotations

from datetime import date

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.crm_models import (AdSource, AuditSource, Case, CaseStatus, Client,
                             ClientDependent, ClientTier, CloseLossReason,
                             ContactChannel, Lead, LeadFollowUp, LeadQuality,
                             LeadSource, LeadStage, LeadTier, MaritalStatus,
                             PreferredLanguage, Priority, ProgressCategory,
                             ProgressStatus, ServiceCatalog, ServiceMode,
                             VisaDraftType)
from app.db import SessionLocal
from app.models import User
from app.services import audit_service
from app.services import concurrency_service
from app.services import crm_service as svc
from app.services import pipeline_stage_service

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

_PRIORITY_WEIGHT = {Priority.urgent: 0, Priority.high: 1, Priority.medium: 2, Priority.low: 3}


@crm_pipeline_bp.route("/casos")
def cases_kanban():
    # Ordenação dentro de cada coluna (Prompt Mestre, Fase 4, 2026-08-06) --
    # não existia nenhuma antes (ordem crua do banco); mais urgente
    # primeiro, empatando por prazo de serviço mais próximo.
    rows = SessionLocal.query(Case).all()
    rows.sort(key=lambda c: (
        _PRIORITY_WEIGHT.get(c.priority, 9),
        c.service_deadline or date.max,
    ))
    by_status: dict[CaseStatus, list[Case]] = {status: [] for status in CaseStatus}
    for c in rows:
        by_status[c.case_status].append(c)

    # Alternância Kanban/Tabela/Lista/Calendário (Prompt Mestre, Fase 4,
    # 2026-08-06) -- calendário usa service_deadline (prazo do serviço
    # contratado, o campo de data mais acionável de um Case).
    view = request.args.get("view", "kanban")
    if view not in ("kanban", "table", "list", "calendar"):
        view = "kanban"
    stage_labels = pipeline_stage_service.stage_labels("case_status")
    columns = [
        {"label": "Title", "value": lambda c: c.title,
         "url": lambda c: url_for("crm_pipeline.client_detail", client_id=c.client_id)},
        {"label": "Client", "value": lambda c: c.client.full_name},
        {"label": "Status", "value": lambda c: stage_labels.get(c.case_status.value, c.case_status.value.replace('_', ' ').title())},
        {"label": "Priority", "value": lambda c: c.priority.value.title()},
        {"label": "Deadline", "value": lambda c: (c.service_deadline.strftime("%m/%d/%Y") if c.service_deadline else "—")},
    ]
    calendar_grid = None
    if view == "calendar":
        from app.services.calendar_view import build_calendar_grid
        today = svc.today()
        year = svc.parse_int(request.args.get("year")) or today.year
        month = svc.parse_int(request.args.get("month")) or today.month
        calendar_grid = build_calendar_grid(rows, lambda c: c.service_deadline, year, month)

    return render_template(
        "crm_cases_kanban.html", by_status=by_status,
        statuses=pipeline_stage_service.ordered_members("case_status"),
        days_to_deadline=svc.days_to_deadline,
        stage_colors=pipeline_stage_service.stage_colors("case_status"),
        stage_labels=stage_labels,
        view=view, columns=columns, calendar_grid=calendar_grid, all_rows=rows)


@crm_pipeline_bp.route("/casos/<int:case_id>/status", methods=["POST"])
def case_status_update(case_id: int):
    case = SessionLocal.get(Case, case_id)
    if case is None:
        abort(404)
    new_status = svc.parse_enum(CaseStatus, request.form.get("case_status"))
    if new_status is None:
        flash("Invalid status.", "error")
        return redirect(request.referrer or url_for("crm_pipeline.cases_kanban"))
    old_status = case.case_status
    case.case_status = new_status
    if old_status != new_status:
        audit_service.log_change(
            "Case", case.id, "stage_change", field="case_status",
            old_value=old_status.value, new_value=new_status.value,
            description=f"Moved from {old_status.value} to {new_status.value}",
            user_id=current_user.id, source=AuditSource.manual)
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
    old_value = case.ds160_visa_type
    case.ds160_visa_type = svc.parse_enum(VisaDraftType, request.form.get("ds160_visa_type"))
    if old_value != case.ds160_visa_type:
        audit_service.log_change(
            "Case", case.id, "field_update", field="ds160_visa_type",
            old_value=old_value.value if old_value else None,
            new_value=case.ds160_visa_type.value if case.ds160_visa_type else None,
            user_id=current_user.id)
    SessionLocal.commit()
    flash("DS-160 draft updated.", "success")
    return redirect(request.referrer or url_for("crm_pipeline.client_detail", client_id=case.client_id))


# --------------------------------------------------------------------------
# Leads
# --------------------------------------------------------------------------

@crm_pipeline_bp.route("/leads")
def leads_kanban():
    # Ordenação dentro de cada coluna (Prompt Mestre, Fase 4, 2026-08-06) --
    # não existia nenhuma antes; lead mais recente primeiro dentro de cada
    # etapa, mesma convenção intuitiva de "o que chegou agora" no topo.
    rows = SessionLocal.query(Lead).order_by(Lead.created_at.desc()).all()
    by_stage: dict[LeadStage, list[Lead]] = {stage: [] for stage in LeadStage}
    for lead in rows:
        by_stage[lead.stage].append(lead)

    sources = {s.id: s for s in SessionLocal.query(LeadSource).all()}
    ad_sources = {a.id: a for a in SessionLocal.query(AdSource).all()}
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

    # "Leads por Ad Source" -- mesmo raciocínio acima, separado de "Lead
    # source" de propósito (pedido do usuário 2026-08-06: são dois campos
    # distintos -- Lead Source cobre também indicação/orgânico, Ad Source é
    # só a plataforma paga que gerou o lead).
    by_ad_source_name: dict[str, list[Lead]] = {}
    for lead in rows:
        name = ad_sources[lead.ad_source_id].name if lead.ad_source_id in ad_sources else "No ad source"
        by_ad_source_name.setdefault(name, []).append(lead)
    ad_source_counts = sorted(
        ((name, len(leads)) for name, leads in by_ad_source_name.items()),
        key=lambda item: item[1], reverse=True)
    max_ad_source_count = max((count for _, count in ad_source_counts), default=1)

    close_loss_reasons = SessionLocal.query(CloseLossReason).order_by(CloseLossReason.name).all()
    reasons = {r.id: r for r in close_loss_reasons}

    # Alternância Kanban/Tabela/Lista/Calendário (Prompt Mestre, Fase 4,
    # 2026-08-06) -- `columns` alimenta as visões Tabela/Lista (mesmos
    # dados já carregados acima, só uma forma diferente de olhar);
    # `calendar_grid` só é montado quando a visão pedida for calendário
    # (data de criação -- é o único campo de data sempre presente em
    # todo lead, diferente de proposal_at/closed_at/lost_at, opcionais).
    view = request.args.get("view", "kanban")
    if view not in ("kanban", "table", "list", "calendar"):
        view = "kanban"
    stage_labels = pipeline_stage_service.stage_labels("lead_stage")
    columns = [
        {"label": "Name", "value": lambda l: l.name, "url": lambda l: url_for("crm_pipeline.lead_detail", lead_id=l.id)},
        {"label": "Stage", "value": lambda l: stage_labels.get(l.stage.value, l.stage.value.replace('_', ' ').title())},
        {"label": "Source", "value": lambda l: sources[l.lead_source_id].name if l.lead_source_id in sources else "—"},
        {"label": "Quality", "value": lambda l: l.quality.value.title() if l.quality else "—"},
        {"label": "Owner", "value": lambda l: users[l.assigned_to_id].email if l.assigned_to_id in users else "—"},
        {"label": "Value", "value": lambda l: (f"${l.deal_value_cents / 100:,.2f}" if l.deal_value_cents else "—")},
        {"label": "Created", "value": lambda l: l.created_at.strftime("%m/%d/%Y")},
    ]
    calendar_grid = None
    if view == "calendar":
        from app.services.calendar_view import build_calendar_grid
        today = svc.today()
        year = svc.parse_int(request.args.get("year")) or today.year
        month = svc.parse_int(request.args.get("month")) or today.month
        calendar_grid = build_calendar_grid(rows, lambda l: l.created_at.date(), year, month)

    return render_template(
        "crm_leads_kanban.html", by_stage=by_stage,
        stages=pipeline_stage_service.ordered_members("lead_stage"),
        sources=sources, reasons=reasons, users=users, source_counts=source_counts, max_count=max_count,
        source_conversion=source_conversion,
        ad_source_counts=ad_source_counts, max_ad_source_count=max_ad_source_count,
        stage_colors=pipeline_stage_service.stage_colors("lead_stage"),
        stage_labels=stage_labels,
        close_loss_reasons=close_loss_reasons,
        view=view, columns=columns, calendar_grid=calendar_grid, all_rows=rows)


@crm_pipeline_bp.route("/leads/<int:lead_id>/stage", methods=["POST"])
def lead_stage_update(lead_id: int):
    lead = SessionLocal.get(Lead, lead_id)
    if lead is None:
        abort(404)
    new_stage = svc.parse_enum(LeadStage, request.form.get("stage"))
    if new_stage is None:
        flash("Invalid stage.", "error")
        return redirect(request.referrer or url_for("crm_pipeline.leads_kanban"))
    if new_stage == LeadStage.closed_won and lead.converted_client_id is None:
        # Fechar um lead sempre passa pela tela de conversão -- não dá pra
        # virar cliente/caso sem antes decidir service_mode e o título do
        # caso (ver lead_convert() abaixo).
        return redirect(url_for("crm_pipeline.lead_convert", lead_id=lead.id))
    if new_stage == LeadStage.closed_lost and lead.lost_at is None:
        # "Data da Desistência" -- pedido do usuário 2026-08-02, preenchida
        # automaticamente na primeira vez que o lead entra em closed_lost
        # (nunca sobrescrita depois, mesma convenção de closed_at em
        # convert_lead_to_client_and_case).
        lead.lost_at = svc.today()
    old_stage = lead.stage
    lead.stage = new_stage
    if old_stage != new_stage:
        audit_service.log_change(
            "Lead", lead.id, "stage_change", field="stage",
            old_value=old_stage.value, new_value=new_stage.value,
            description=f"Moved from {old_stage.value} to {new_stage.value}",
            user_id=current_user.id, source=AuditSource.manual)
    SessionLocal.commit()
    return redirect(request.referrer or url_for("crm_pipeline.leads_kanban"))


@crm_pipeline_bp.route("/leads/<int:lead_id>")
def lead_detail(lead_id: int):
    lead = SessionLocal.get(Lead, lead_id)
    if lead is None:
        abort(404)
    lead_sources = SessionLocal.query(LeadSource).order_by(LeadSource.name).all()
    contact_channels = SessionLocal.query(ContactChannel).order_by(ContactChannel.name).all()
    close_loss_reasons = SessionLocal.query(CloseLossReason).order_by(CloseLossReason.name).all()
    services = SessionLocal.query(ServiceCatalog).order_by(ServiceCatalog.name).all()
    interested_ids = set(svc.lead_interested_service_ids(lead.id))
    ad_sources = SessionLocal.query(AdSource).order_by(AdSource.name).all()
    related_case = SessionLocal.query(Case).filter_by(lead_id=lead.id).first()
    history = audit_service.get_history("Lead", lead.id)
    history_users = {u.id: u for u in SessionLocal.query(User).all()}

    from app.services import custom_fields_service as cfsvc
    custom_fields = cfsvc.active_fields("Lead")
    custom_values = cfsvc.values_for_entity("Lead", lead.id)

    return render_template(
        "crm_lead_detail.html", lead=lead, lead_sources=lead_sources, contact_channels=contact_channels,
        contact_channels_by_id={c.id: c for c in contact_channels},
        close_loss_reasons=close_loss_reasons, services=services, interested_ids=interested_ids,
        ad_sources=ad_sources, related_case=related_case,
        qualities=list(LeadQuality), tiers=list(LeadTier), stages=list(LeadStage),
        service_modes=list(ServiceMode), days_to_close=svc.days_to_close(lead),
        history=history, history_users=history_users, today_iso=svc.today().isoformat(),
        custom_fields=custom_fields, custom_values=custom_values,
        cf_options_for=cfsvc.options_for, cf_multi_selected=cfsvc.parse_multi_select)


LEAD_TRACKED_FIELDS = [
    "name", "contact_email", "contact_phone", "city_region", "notes",
    "contact_attempts", "lead_source_id", "ad_source_id", "contact_channel_id",
    "close_loss_reason_id", "quality", "tier", "interested_service_mode",
    "deal_value_cents", "first_contact_at", "proposal_at", "closed_at", "lost_at",
]


@crm_pipeline_bp.route("/leads/<int:lead_id>/salvar", methods=["POST"])
def lead_update(lead_id: int):
    lead = SessionLocal.get(Lead, lead_id)
    if lead is None:
        abort(404)

    name = request.form.get("name", "").strip()
    if not name:
        flash("Name is required.", "error")
        return redirect(url_for("crm_pipeline.lead_detail", lead_id=lead_id))

    before = {f: getattr(lead, f) for f in LEAD_TRACKED_FIELDS}

    lead.name = name
    lead.contact_email = request.form.get("contact_email", "").strip() or None
    lead.contact_phone = request.form.get("contact_phone", "").strip() or None
    lead.city_region = request.form.get("city_region", "").strip() or None
    lead.notes = request.form.get("notes", "").strip() or None
    lead.contact_attempts = svc.parse_int(request.form.get("contact_attempts"))
    lead.lead_source_id = svc.parse_int(request.form.get("lead_source_id"))
    lead.ad_source_id = svc.parse_int(request.form.get("ad_source_id"))
    lead.contact_channel_id = svc.parse_int(request.form.get("contact_channel_id"))
    lead.close_loss_reason_id = svc.parse_int(request.form.get("close_loss_reason_id"))
    lead.quality = svc.parse_enum(LeadQuality, request.form.get("quality"))
    lead.tier = svc.parse_enum(LeadTier, request.form.get("tier"))
    lead.interested_service_mode = svc.parse_enum(ServiceMode, request.form.get("interested_service_mode"))
    lead.deal_value_cents = svc.parse_dollars_to_cents(request.form.get("deal_value_dollars", ""))
    lead.first_contact_at = svc.parse_date(request.form.get("first_contact_at"))
    lead.proposal_at = svc.parse_date(request.form.get("proposal_at"))
    lead.closed_at = svc.parse_date(request.form.get("closed_at"))
    lead.lost_at = svc.parse_date(request.form.get("lost_at"))

    service_ids = [svc.parse_int(v) for v in request.form.getlist("interested_service_ids")]
    svc.set_lead_interested_services(lead.id, [s for s in service_ids if s is not None])

    changes = {f: (before[f], getattr(lead, f)) for f in LEAD_TRACKED_FIELDS}
    audit_service.log_field_changes("Lead", lead.id, changes, user_id=current_user.id)

    SessionLocal.commit()
    flash("Lead updated.", "success")
    return redirect(url_for("crm_pipeline.lead_detail", lead_id=lead_id))


@crm_pipeline_bp.route("/leads/<int:lead_id>/campos-personalizados", methods=["POST"])
def lead_custom_fields_save(lead_id: int):
    """Grava os valores dos Custom Fields (Prompt Mestre, Fase 5) pra este
    lead -- rota própria, mesmo motivo de sempre (não reaproveita
    lead_update, que grava TODOS os campos do lead de uma vez)."""
    from app.services import custom_fields_service as cfsvc

    lead = SessionLocal.get(Lead, lead_id)
    if lead is None:
        abort(404)
    fields = cfsvc.active_fields("Lead")
    before = cfsvc.values_for_entity("Lead", lead.id)
    cfsvc.save_values("Lead", lead.id, fields, request.form)
    SessionLocal.flush()
    after = cfsvc.values_for_entity("Lead", lead.id)
    for field in fields:
        if before.get(field.id) != after.get(field.id):
            audit_service.log_change(
                "Lead", lead.id, "field_update", field=f"custom:{field.key}",
                old_value=before.get(field.id), new_value=after.get(field.id),
                description=f"Custom field '{field.label}' updated", user_id=current_user.id)
    SessionLocal.commit()
    flash("Custom fields updated.", "success")
    return redirect(url_for("crm_pipeline.lead_detail", lead_id=lead_id))


@crm_pipeline_bp.route("/leads/<int:lead_id>/excluir", methods=["POST"])
def lead_delete(lead_id: int):
    lead = SessionLocal.get(Lead, lead_id)
    if lead is None:
        abort(404)
    from app.crm_models import LeadInterestedService
    audit_service.log_change("Lead", lead.id, "delete", description=f"Lead '{lead.name}' deleted",
                              user_id=current_user.id)
    SessionLocal.query(LeadInterestedService).filter_by(lead_id=lead_id).delete()
    SessionLocal.delete(lead)
    SessionLocal.commit()
    flash("Lead deleted.", "success")
    return redirect(url_for("crm_pipeline.leads_kanban"))


@crm_pipeline_bp.route("/leads/<int:lead_id>/follow-up/novo", methods=["POST"])
def lead_follow_up_new(lead_id: int):
    """Follow-up numerado -- pedido do usuário 2026-08-06, dentro do card
    do Lead. `follow_up_number` é sempre o próximo da sequência deste
    lead (1, 2, 3...), calculado aqui, nunca editável depois."""
    lead = SessionLocal.get(Lead, lead_id)
    if lead is None:
        abort(404)
    next_number = (max((f.follow_up_number for f in lead.follow_ups), default=0)) + 1
    SessionLocal.add(LeadFollowUp(
        lead_id=lead.id, follow_up_number=next_number,
        follow_up_date=svc.parse_date(request.form.get("follow_up_date")) or svc.today(),
        contact_channel_id=svc.parse_int(request.form.get("contact_channel_id")),
        notes=request.form.get("notes", "").strip() or None,
    ))
    audit_service.log_change("Lead", lead.id, "create", description=f"Follow-up #{next_number} added",
                              user_id=current_user.id)
    SessionLocal.commit()
    flash(f"Follow-up #{next_number} added.", "success")
    return redirect(url_for("crm_pipeline.lead_detail", lead_id=lead_id))


@crm_pipeline_bp.route("/leads/motivos/novo", methods=["POST"])
def close_loss_reason_new():
    """"Reason for not closing" -- lookup aberta, pedido do usuário
    2026-08-06: sempre possível adicionar um motivo novo."""
    name = request.form.get("name", "").strip()
    if not name:
        flash("Reason name is required.", "error")
        return redirect(request.referrer or url_for("crm_pipeline.leads_kanban"))
    if SessionLocal.query(CloseLossReason).filter_by(name=name).first() is not None:
        flash(f'"{name}" is already in the list.', "error")
        return redirect(request.referrer or url_for("crm_pipeline.leads_kanban"))
    SessionLocal.add(CloseLossReason(name=name))
    SessionLocal.commit()
    flash(f'"{name}" added to reasons.', "success")
    return redirect(request.referrer or url_for("crm_pipeline.leads_kanban"))


@crm_pipeline_bp.route("/leads/motivos/<int:reason_id>/renomear", methods=["POST"])
def close_loss_reason_rename(reason_id: int):
    reason = SessionLocal.get(CloseLossReason, reason_id)
    if reason is None:
        abort(404)
    name = request.form.get("name", "").strip()
    if not name:
        flash("Reason name is required.", "error")
        return redirect(request.referrer or url_for("crm_pipeline.leads_kanban"))
    reason.name = name
    SessionLocal.commit()
    flash("Reason updated.", "success")
    return redirect(request.referrer or url_for("crm_pipeline.leads_kanban"))


@crm_pipeline_bp.route("/leads/<int:lead_id>/converter", methods=["GET", "POST"])
def lead_convert(lead_id: int):
    lead = SessionLocal.get(Lead, lead_id)
    if lead is None:
        abort(404)

    duplicate_clients = svc.find_possible_duplicate_clients(lead)

    if request.method == "POST":
        service_mode = svc.parse_enum(ServiceMode, request.form.get("service_mode"))
        case_title = request.form.get("case_title", "").strip()
        if service_mode is None or not case_title:
            flash("Service tier and case title are required.", "error")
            return redirect(url_for("crm_pipeline.lead_convert", lead_id=lead.id))

        # Checagem de duplicidade (Prompt Mestre, Fase 6, 2026-08-06) --
        # se há um possível cliente já existente e o colaborador não
        # confirmou explicitamente que é gente diferente mesmo, bloqueia
        # a criação de um Client duplicado e volta pro formulário (que já
        # mostra os possíveis "match" e a opção de anexar a um deles).
        if duplicate_clients and request.form.get("confirm_duplicate") != "1":
            flash("Possible duplicate client found -- review below before creating a new one.", "error")
            return redirect(url_for("crm_pipeline.lead_convert", lead_id=lead.id))

        old_stage = lead.stage
        client, case = svc.convert_lead_to_client_and_case(
            lead, service_mode=service_mode, case_title=case_title)
        audit_service.log_change(
            "Lead", lead.id, "stage_change", field="stage",
            old_value=old_stage.value, new_value=lead.stage.value,
            description=f"Converted to Client #{client.id} / Case #{case.id}",
            user_id=current_user.id, source=AuditSource.manual)
        SessionLocal.commit()
        flash(f"Lead converted -- client and case created (#{case.id}).", "success")
        return redirect(url_for("crm_pipeline.client_detail", client_id=client.id))

    suggested_title = f"Caso — {lead.name}"
    return render_template(
        "crm_leads_kanban.html", convert_lead=lead, suggested_title=suggested_title,
        duplicate_clients=duplicate_clients,
        service_modes=list(ServiceMode), by_stage={}, stages=[], sources={}, reasons={}, users={},
        source_counts=[], max_count=1, source_conversion=[],
        ad_source_counts=[], max_ad_source_count=1, stage_colors={}, stage_labels={})


@crm_pipeline_bp.route("/leads/<int:lead_id>/anexar/<int:client_id>", methods=["POST"])
def lead_attach_to_client(lead_id: int, client_id: int):
    """Resolve a duplicidade apontada em lead_convert acima: em vez de
    criar um Client novo, anexa este lead como mais um Case do Client
    EXISTENTE escolhido pelo colaborador -- pedido do Prompt Mestre,
    Fase 6 (checagem de duplicidade), 2026-08-06."""
    lead = SessionLocal.get(Lead, lead_id)
    client = SessionLocal.get(Client, client_id)
    if lead is None or client is None:
        abort(404)

    service_mode = svc.parse_enum(ServiceMode, request.form.get("service_mode"))
    case_title = request.form.get("case_title", "").strip()
    if service_mode is None or not case_title:
        flash("Service tier and case title are required.", "error")
        return redirect(url_for("crm_pipeline.lead_convert", lead_id=lead.id))

    old_stage = lead.stage
    case = svc.attach_lead_to_existing_client(
        lead, client, service_mode=service_mode, case_title=case_title)
    audit_service.log_change(
        "Lead", lead.id, "stage_change", field="stage",
        old_value=old_stage.value, new_value=lead.stage.value,
        description=f"Attached to existing Client #{client.id} / new Case #{case.id}",
        user_id=current_user.id, source=AuditSource.manual)
    SessionLocal.commit()
    flash(f"Lead attached to {client.full_name} -- new case created (#{case.id}).", "success")
    return redirect(url_for("crm_pipeline.client_detail", client_id=client.id))


@crm_pipeline_bp.route("/leads/novo", methods=["GET", "POST"])
def lead_new():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Name is required.", "error")
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
        SessionLocal.flush()
        audit_service.log_change("Lead", lead.id, "create", description=f"Lead '{lead.name}' created",
                                  user_id=current_user.id)
        SessionLocal.commit()
        flash("Lead created.", "success")
        return redirect(url_for("crm_pipeline.leads_kanban"))

    lead_sources = SessionLocal.query(LeadSource).order_by(LeadSource.name).all()
    return render_template(
        "crm_leads_kanban.html", new_form=True, lead_sources=lead_sources, qualities=list(LeadQuality),
        by_stage={}, stages=[], sources={}, users={}, source_counts=[], max_count=1, source_conversion=[],
        ad_source_counts=[], max_ad_source_count=1, stage_colors={}, stage_labels={})


# --------------------------------------------------------------------------
# Clientes
# --------------------------------------------------------------------------

@crm_pipeline_bp.route("/clientes")
def clients_list():
    # Busca unificada com o filtro local (pedido do usuário 2026-08-06,
    # mesmo padrão .list-filter-input dos kanbans) -- não filtra mais no
    # servidor via `q`, a lista inteira vai pro client-side filtrar sem
    # round-trip. Já era o comportamento padrão sem `q` mesmo (nenhuma
    # paginação existia antes disso), então não piora o pior caso.
    clients = SessionLocal.query(Client).order_by(Client.full_name).all()

    open_case_counts: dict[int, int] = {}
    for case in SessionLocal.query(Case).filter(Case.case_status.in_(OPEN_CASE_STATUSES)).all():
        open_case_counts[case.client_id] = open_case_counts.get(case.client_id, 0) + 1

    return render_template(
        "crm_clients.html", clients=clients, open_case_counts=open_case_counts)


@crm_pipeline_bp.route("/clientes/novo", methods=["GET", "POST"])
def client_new():
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        if not full_name:
            flash("Name is required.", "error")
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
        flash("Client created.", "success")
        return redirect(url_for("crm_pipeline.client_detail", client_id=client.id))

    return render_template("crm_clients.html", new_form=True, tiers=list(ClientTier),
                            clients=[], open_case_counts={})


def _next_case_status(case: Case) -> CaseStatus | None:
    """Próxima etapa do funil depois da atual -- pedido do usuário
    2026-08-06: mostrar "etapa atual" + "próxima etapa" na ficha do
    cliente, não só o nome cru da etapa. Segue a mesma ordem customizável
    (drag-and-drop na tela de admin) que já rege o kanban de Cases -- ver
    app/services/pipeline_stage_service.py::ordered_members. None quando
    a etapa atual já é a última da lista."""
    ordered = pipeline_stage_service.ordered_members("case_status")
    try:
        idx = ordered.index(case.case_status)
    except ValueError:
        return None
    return ordered[idx + 1] if idx + 1 < len(ordered) else None


def _time_summary_for_case(case_id: int) -> dict | None:
    """Registro de dias/horários/tempo trabalhado no caso -- pedido do
    usuário 2026-08-06 ("na ficha do CRM no topo, eu quero que apareça o
    registro dias, horarios, e tempo trabalhado no caso"), a partir das
    Time Entries (app/planner_models.py::TimeEntry) atribuídas a este
    caso, de QUALQUER colaborador (não só o responsável). None quando
    nenhuma entrada aponta pra este caso ainda."""
    from app.planner_models import TimeEntry
    from app.services import planner_service as planner_svc

    entries = (
        SessionLocal.query(TimeEntry)
        .filter_by(case_id=case_id)
        .order_by(TimeEntry.started_at.desc())
        .all()
    )
    if not entries:
        return None
    total_seconds = sum(planner_svc.entry_duration_seconds(e) for e in entries)
    return {
        "entries": entries,
        "total_display": planner_svc.format_duration(total_seconds),
        "count": len(entries),
    }


@crm_pipeline_bp.route("/clientes/<int:client_id>")
def client_detail(client_id: int):
    client = SessionLocal.get(Client, client_id)
    if client is None:
        abort(404)
    pending_by_case = {case.id: svc.case_pending_documents(case) for case in client.cases}
    next_status_by_case = {case.id: _next_case_status(case) for case in client.cases}
    case_stage_labels = pipeline_stage_service.stage_labels("case_status")

    from app.services import custom_fields_service as cfsvc
    custom_fields = cfsvc.active_fields("Case")
    custom_values_by_case = {case.id: cfsvc.values_for_entity("Case", case.id) for case in client.cases}
    client_custom_fields = cfsvc.active_fields("Client")
    client_custom_values = cfsvc.values_for_entity("Client", client.id)
    time_summary = _time_summary_for_case(client.cases[0].id) if client.cases else None
    from app.services import planner_service as planner_svc

    # Pedido do usuário 2026-08-06: "uma parte pra registrar o último
    # contato com o cliente, se tiver algo pendente com o cliente".
    # last_contact = Communication mais recente (qualquer status).
    # pending_communications = todas com status != done -- "o que está
    # pendente" mostrado explicitamente, não só um contador.
    from app.crm_models import CommStatus, Communication
    client_comms = sorted(client.communications, key=lambda c: c.occurred_at, reverse=True)
    last_contact = client_comms[0] if client_comms else None
    pending_communications = [c for c in client_comms if c.status != CommStatus.done]

    return render_template(
        "crm_client_detail.html", client=client, pending_by_case=pending_by_case,
        progress_statuses=list(ProgressStatus), progress_categories=list(ProgressCategory),
        tiers=list(ClientTier), marital_statuses=list(MaritalStatus),
        preferred_languages=list(PreferredLanguage),
        priorities=list(Priority), staff_users=svc.staff_users(),
        next_status_by_case=next_status_by_case, case_stage_labels=case_stage_labels,
        time_summary=time_summary,
        entry_duration=planner_svc.entry_duration_seconds, format_duration=planner_svc.format_duration,
        last_contact=last_contact, pending_communications=pending_communications,
        custom_fields=custom_fields, custom_values_by_case=custom_values_by_case,
        cf_options_for=cfsvc.options_for, cf_multi_selected=cfsvc.parse_multi_select,
        client_custom_fields=client_custom_fields, client_custom_values=client_custom_values)


@crm_pipeline_bp.route("/clientes/<int:client_id>/excluir", methods=["POST"])
def client_delete(client_id: int):
    """Exclui um Client -- pedido do usuário 2026-08-06. Deliberadamente
    restrito a registros "vazios" (sem Case/Communication/Lead convertido
    ligado): a maioria dos 2000+ clientes reais deste banco tem histórico
    de caso/pagamento de verdade, e um hard-delete em cascata apagaria
    tudo isso silenciosamente -- o uso real desta ação é limpar um
    cadastro duplicado ou criado por engano. Intake/Credentials/Dependents
    têm cascade="all, delete-orphan" no relationship (Client acima) e saem
    junto automaticamente; qualquer outro vínculo raro (Financial Coaching,
    Planner) que a query abaixo não previu ainda esbarra no FK constraint
    do SQLite (PRAGMA foreign_keys=ON, ver app/db.py) -- por isso o
    IntegrityError abaixo tem um fallback genérico em vez de deixar
    estourar um erro 500."""
    client = SessionLocal.get(Client, client_id)
    if client is None:
        abort(404)

    blockers = []
    if client.cases:
        blockers.append(f"{len(client.cases)} case(s)")
    if client.communications:
        blockers.append(f"{len(client.communications)} communication(s)")
    converted_leads = SessionLocal.query(Lead).filter_by(converted_client_id=client.id).count()
    if converted_leads:
        blockers.append(f"{converted_leads} converted lead(s)")

    if blockers:
        flash(
            "Can't delete this client -- it still has " + ", ".join(blockers) +
            " linked to it. Remove/reassign those first.", "error")
        return redirect(url_for("crm_pipeline.client_detail", client_id=client_id))

    from sqlalchemy.exc import IntegrityError
    try:
        SessionLocal.delete(client)
        SessionLocal.commit()
    except IntegrityError:
        SessionLocal.rollback()
        flash(
            "Can't delete this client -- it's still referenced elsewhere in the system "
            "(e.g. Financial Coaching or Planner). Remove those links first.", "error")
        return redirect(url_for("crm_pipeline.client_detail", client_id=client_id))

    flash("Client deleted.", "success")
    return redirect(url_for("crm_pipeline.clients_list"))


@crm_pipeline_bp.route("/clientes/<int:client_id>/salvar", methods=["POST"])
def client_update(client_id: int):
    client = SessionLocal.get(Client, client_id)
    if client is None:
        abort(404)

    try:
        concurrency_service.checar_versao(client, request.form.get("version"))
    except concurrency_service.ConflitoEdicaoError:
        flash(
            "This client was edited by someone else while you had this page "
            "open. Reload the page to see their changes before saving yours.",
            "error")
        return redirect(url_for("crm_pipeline.client_detail", client_id=client_id))

    full_name = request.form.get("full_name", "").strip()
    if not full_name:
        flash("Name is required.", "error")
        return redirect(url_for("crm_pipeline.client_detail", client_id=client_id))

    client.full_name = full_name
    client.email = request.form.get("email", "").strip() or None
    client.personal_email_verified = request.form.get("personal_email_verified") == "on"
    client.us_phone = request.form.get("us_phone", "").strip() or None
    client.us_phone_has = bool(client.us_phone)
    client.us_phone_verified = request.form.get("us_phone_verified") == "on"
    client.home_phone = request.form.get("home_phone", "").strip() or None
    client.home_phone_has = bool(client.home_phone)
    client.us_address = request.form.get("us_address", "").strip() or None
    client.us_address_verified = request.form.get("us_address_verified") == "on"
    client.home_address = request.form.get("home_address", "").strip() or None
    client.city_country = request.form.get("city_country", "").strip() or None
    client.country_of_origin = request.form.get("country_of_origin", "").strip() or None
    client.preferred_language = svc.parse_enum(PreferredLanguage, request.form.get("preferred_language"))
    client.best_contact_time = request.form.get("best_contact_time", "").strip() or None

    client.dob = svc.parse_date(request.form.get("dob"))
    client.marital_status = svc.parse_enum(MaritalStatus, request.form.get("marital_status"))
    client.marriage_date = svc.parse_date(request.form.get("marriage_date"))
    client.has_dependents = request.form.get("has_dependents") == "on"
    client.n_dependents = svc.parse_int(request.form.get("n_dependents"))
    client.passport_expiration = svc.parse_date(request.form.get("passport_expiration"))

    client.current_status_visa = request.form.get("current_status_visa", "").strip() or None
    client.status_expiration = svc.parse_date(request.form.get("status_expiration"))
    client.resident_since = svc.parse_date(request.form.get("resident_since"))
    client.gc_expiration = svc.parse_date(request.form.get("gc_expiration"))

    client.tier = svc.parse_enum(ClientTier, request.form.get("tier"))

    concurrency_service.bump_versao(client)
    SessionLocal.commit()
    flash("Client updated.", "success")
    return redirect(url_for("crm_pipeline.client_detail", client_id=client_id))


@crm_pipeline_bp.route("/clientes/<int:client_id>/campos-personalizados", methods=["POST"])
def client_custom_fields_save(client_id: int):
    """Grava os valores dos Custom Fields (Prompt Mestre, Fase 5) pra este
    cliente -- rota própria, mesmo motivo de sempre (não reaproveita
    client_update, que grava um monte de campos do perfil de uma vez)."""
    from app.services import custom_fields_service as cfsvc

    client = SessionLocal.get(Client, client_id)
    if client is None:
        abort(404)
    fields = cfsvc.active_fields("Client")
    before = cfsvc.values_for_entity("Client", client.id)
    cfsvc.save_values("Client", client.id, fields, request.form)
    SessionLocal.flush()
    after = cfsvc.values_for_entity("Client", client.id)
    for field in fields:
        if before.get(field.id) != after.get(field.id):
            audit_service.log_change(
                "Client", client.id, "field_update", field=f"custom:{field.key}",
                old_value=before.get(field.id), new_value=after.get(field.id),
                description=f"Custom field '{field.label}' updated", user_id=current_user.id)
    SessionLocal.commit()
    flash("Custom fields updated.", "success")
    return redirect(url_for("crm_pipeline.client_detail", client_id=client_id))


@crm_pipeline_bp.route("/clientes/<int:client_id>/dependentes/novo", methods=["POST"])
def client_dependent_new(client_id: int):
    client = SessionLocal.get(Client, client_id)
    if client is None:
        abort(404)
    full_name = request.form.get("full_name", "").strip()
    if not full_name:
        flash("Dependent name is required.", "error")
        return redirect(url_for("crm_pipeline.client_detail", client_id=client_id))
    SessionLocal.add(ClientDependent(
        client_id=client.id, full_name=full_name,
        email=request.form.get("email", "").strip() or None,
        us_phone=request.form.get("us_phone", "").strip() or None,
    ))
    client.has_dependents = True
    SessionLocal.commit()
    flash("Dependent added.", "success")
    return redirect(url_for("crm_pipeline.client_detail", client_id=client_id))


@crm_pipeline_bp.route("/clientes/dependentes/<int:dependent_id>/salvar", methods=["POST"])
def client_dependent_update(dependent_id: int):
    dep = SessionLocal.get(ClientDependent, dependent_id)
    if dep is None:
        abort(404)
    full_name = request.form.get("full_name", "").strip()
    if not full_name:
        flash("Dependent name is required.", "error")
        return redirect(url_for("crm_pipeline.client_detail", client_id=dep.client_id))
    dep.full_name = full_name
    dep.email = request.form.get("email", "").strip() or None
    dep.us_phone = request.form.get("us_phone", "").strip() or None
    SessionLocal.commit()
    flash("Dependent updated.", "success")
    return redirect(url_for("crm_pipeline.client_detail", client_id=dep.client_id))


@crm_pipeline_bp.route("/clientes/dependentes/<int:dependent_id>/excluir", methods=["POST"])
def client_dependent_delete(dependent_id: int):
    dep = SessionLocal.get(ClientDependent, dependent_id)
    if dep is None:
        abort(404)
    client_id = dep.client_id
    SessionLocal.delete(dep)
    remaining = SessionLocal.query(ClientDependent).filter(
        ClientDependent.client_id == client_id, ClientDependent.id != dependent_id).count()
    if remaining == 0:
        client = SessionLocal.get(Client, client_id)
        client.has_dependents = False
    SessionLocal.commit()
    flash("Dependent removed.", "success")
    return redirect(url_for("crm_pipeline.client_detail", client_id=client_id))
