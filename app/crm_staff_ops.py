"""Blueprint do CRM (staff) -- Documentos, Pagamentos (ledger financeiro),
Comunicações e Tarefas. Irmão de app/crm_staff_pipeline.py (Clientes/Leads/
Casos) -- blueprint separado (mesmo url_prefix) só pra manter os arquivos
independentes; ambos vivem sob /staff/crm.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from flask import Blueprint, abort, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required

from app.crm_financial_models import FinancialClient
from app.crm_models import (AuditSource, Case, CaseMessage, CaseMessageAuthorRole,
                             CaseMessageStatus, CaseMessageType,
                             CaseProgressItem, CaseService, CaseStepLog,
                             Client, CommDirection, CommStatus, Communication,
                             ContactChannel, Currency, Document,
                             DocumentStatus, DocumentTranslation, DocumentType,
                             FeeType, FieldOffice, PaymentDirection, PaymentLedgerEntry,
                             PaymentLedgerFeeType, PaymentMethodLookup, PaymentStatus, Priority,
                             ProgressCategory, ProgressStatus, ServiceCatalog,
                             ServiceMode, ServiceRole, Task, TaskChecklistItem, TaskComment,
                             TaskStatus, TaskType, TranslationLanguage,
                             TranslationSpeedTier, Translator)
from app.db import SessionLocal
from app.models import User
from app.services import audit_service
from app.services import case_messages as case_messages_svc
from app.services import concurrency_service
from app.services import crm_service as svc
from app.services import pipeline_stage_service

crm_ops_bp = Blueprint("crm_ops", __name__, url_prefix="/staff/crm")


@crm_ops_bp.before_request
@login_required
def _require_staff():
    if not current_user.is_staff:
        abort(403)


# --------------------------------------------------------------------------
# Documentos
# --------------------------------------------------------------------------

@crm_ops_bp.route("/casos/<int:case_id>/documentos")
def case_documents(case_id: int):
    case = SessionLocal.get(Case, case_id)
    if case is None:
        abort(404)
    translation_totals = {
        d.id: {
            "client_total_cents": svc.translation_client_total_cents(d.translation),
            "client_price_per_page_cents": svc.translation_client_price_per_page_cents(d.translation.speed_tier),
            "payout_translator_currency_cents": svc.translation_payout_translator_currency_cents(d.translation),
            "payout_usd_cents": svc.translation_payout_usd_cents(d.translation),
        }
        for d in case.documents if d.translation is not None
    }
    document_history = {d.id: audit_service.get_history("Document", d.id) for d in case.documents}
    history_users = {u.id: u for u in SessionLocal.query(User).all()}
    return render_template(
        "crm_documents.html", case=case,
        document_types=list(DocumentType), translation_languages=list(TranslationLanguage),
        document_statuses=list(DocumentStatus), speed_tiers=list(TranslationSpeedTier),
        translators=SessionLocal.query(Translator).order_by(Translator.full_name).all(),
        currencies=list(Currency), translation_totals=translation_totals,
        staff_users=svc.staff_users(),
        document_history=document_history, history_users=history_users)


@crm_ops_bp.route("/casos/<int:case_id>/documentos/novo", methods=["POST"])
def case_document_new(case_id: int):
    case = SessionLocal.get(Case, case_id)
    if case is None:
        abort(404)
    name = request.form.get("name", "").strip()
    if not name:
        flash("Document name is required.", "error")
        return redirect(url_for("crm_ops.case_documents", case_id=case_id))

    doc_type = svc.parse_enum(DocumentType, request.form.get("document_type"), default=DocumentType.other)
    translation_language = svc.parse_enum(TranslationLanguage, request.form.get("translation_language"))

    doc = Document(
        case_id=case.id, client_id=case.client_id, name=name,
        document_type=doc_type, translation_language=translation_language,
        requested_at=svc.today())
    SessionLocal.add(doc)
    SessionLocal.flush()
    audit_service.log_change("Document", doc.id, "create",
                              description=f"Document '{name}' ({doc_type.value}) requested",
                              user_id=current_user.id)
    SessionLocal.commit()
    flash("Document added.", "success")
    return redirect(url_for("crm_ops.case_documents", case_id=case_id))


# --------------------------------------------------------------------------
# Acompanhamento (CaseProgressItem) -- rastreador de tarefas visível tanto
# pro staff (aqui, dentro do card do cliente em crm_client_detail.html)
# quanto pro cliente (app/crm_client.py::meu_caso). Cobre formulários,
# cartas, organização de documentos, solicitações internas etc. Pedido do
# usuário, 2026-08-02. Diferente de Task (staff-only) e CaseStepLog
# (log append-only sem estado "em andamento").
# --------------------------------------------------------------------------

@crm_ops_bp.route("/casos/<int:case_id>/acompanhamento/novo", methods=["POST"])
def case_progress_new(case_id: int):
    case = SessionLocal.get(Case, case_id)
    if case is None:
        abort(404)
    title = request.form.get("title", "").strip()
    if not title:
        flash("Title is required.", "error")
        return redirect(url_for("crm_pipeline.client_detail", client_id=case.client_id))

    SessionLocal.add(CaseProgressItem(
        case_id=case.id, title=title,
        category=svc.parse_enum(ProgressCategory, request.form.get("category"), default=ProgressCategory.other)))
    SessionLocal.commit()
    flash("Progress item added.", "success")
    return redirect(url_for("crm_pipeline.client_detail", client_id=case.client_id))


@crm_ops_bp.route("/acompanhamento/<int:item_id>/status", methods=["POST"])
def case_progress_status_update(item_id: int):
    item = SessionLocal.get(CaseProgressItem, item_id)
    if item is None:
        abort(404)
    status = svc.parse_enum(ProgressStatus, request.form.get("status"))
    if status is not None:
        item.status = status
        SessionLocal.commit()
    return redirect(request.referrer or url_for("crm_pipeline.client_detail", client_id=item.case.client_id))


@crm_ops_bp.route("/acompanhamento/<int:item_id>/excluir", methods=["POST"])
def case_progress_delete(item_id: int):
    item = SessionLocal.get(CaseProgressItem, item_id)
    if item is None:
        abort(404)
    client_id = item.case.client_id
    SessionLocal.delete(item)
    SessionLocal.commit()
    flash("Progress item removed.", "success")
    return redirect(url_for("crm_pipeline.client_detail", client_id=client_id))


# --------------------------------------------------------------------------
# Procedimento do caso -- serviço "Pacote Completo" (Saes Standard/Plus)
# atribuído + checklist de fases/passos do template (ver
# app/services/service_procedures.py). Irmã de case_documents() acima, mas
# um propósito diferente: aqui é o roteiro interno de como conduzir o
# processo; case_documents() é o rastreador de documentos/traduções do CRM.
# Pedido do usuário, 2026-08-01.
# --------------------------------------------------------------------------

@crm_ops_bp.route("/casos/<int:case_id>/servico", methods=["POST"])
def case_service_update(case_id: int):
    case = SessionLocal.get(Case, case_id)
    if case is None:
        abort(404)
    slug = request.form.get("service_slug", "").strip()
    tier = svc.parse_enum(ServiceMode, request.form.get("service_mode"))

    service = SessionLocal.query(ServiceCatalog).filter_by(slug=slug).first() if slug else None
    if service is None or tier is None or tier == ServiceMode.self_service:
        flash("Select a service and a service tier (Saes Standard/Plus).", "error")
        return redirect(url_for("crm_ops.case_procedure", case_id=case_id))

    old_service = next((cs.service.name for cs in case.services if cs.role == ServiceRole.current), None)
    old_mode = case.service_mode
    SessionLocal.query(CaseService).filter_by(case_id=case.id, role=ServiceRole.current).delete()
    SessionLocal.add(CaseService(case_id=case.id, service_id=service.id, role=ServiceRole.current))
    case.service_mode = tier
    SessionLocal.flush()
    svc.apply_service_procedure_checklist(case)
    audit_service.log_field_changes(
        "Case", case.id,
        {"service": (old_service, service.name),
         "service_mode": (old_mode.value if old_mode else None, tier.value)},
        user_id=current_user.id)
    SessionLocal.commit()
    flash("Case service updated.", "success")
    return redirect(url_for("crm_ops.case_procedure", case_id=case_id))


@crm_ops_bp.route("/casos/<int:case_id>/procedimento")
def case_procedure(case_id: int):
    from app.models import Payment, PostPaymentOnboarding
    from app.services.service_procedures import load_service_procedure

    case = SessionLocal.get(Case, case_id)
    if case is None:
        abort(404)

    current_cs = next((cs for cs in case.services if cs.role == ServiceRole.current), None)
    template = load_service_procedure(current_cs.service.slug) if current_cs and current_cs.service.slug else None
    done_steps = {log.step_name for log in case.step_log}
    payment = SessionLocal.query(Payment).filter_by(case_id=case.id, status="confirmed").first()
    # Fase 1 do checklist (RequiredDocument, ver app/onboarding.py) --
    # pedido do usuário 2026-08-06: staff marca aqui quais precisam de
    # tradução (checkbox), não só lê o texto cru do template (ver
    # required_document_translation_toggle abaixo e crm_case_procedure.html).
    onboarding = (
        SessionLocal.query(PostPaymentOnboarding).filter_by(payment_id=payment.id).first()
        if payment is not None else None
    )

    services_with_slug = SessionLocal.query(ServiceCatalog).filter(
        ServiceCatalog.slug.is_not(None)).order_by(ServiceCatalog.name).all()
    # date.min como fallback de ordenação -- nem todo PaymentLedgerEntry
    # tem payment_date preenchido (ex.: cobrança ainda pendente), e
    # comparar date com None estoura TypeError (não dá pra fazer isso no
    # filtro `sort` do Jinja, que não aceita uma key custom).
    case_payments = sorted(case.payments, key=lambda p: p.payment_date or date.min, reverse=True)
    history = audit_service.get_history("Case", case.id)
    history_users = {u.id: u for u in SessionLocal.query(User).all()}

    return render_template(
        "crm_case_procedure.html", case=case, template=template, done_steps=done_steps,
        current_service=current_cs.service if current_cs else None, payment=payment,
        onboarding=onboarding,
        case_payments=case_payments,
        services_with_slug=services_with_slug,
        tiers=[m for m in ServiceMode if m != ServiceMode.self_service],
        priorities=list(Priority), staff_users=svc.staff_users(),
        field_offices=SessionLocal.query(FieldOffice).order_by(FieldOffice.name).all(),
        history=history, history_users=history_users)


@crm_ops_bp.route("/documentos-requeridos/<int:document_id>/traducao", methods=["POST"])
def required_document_translation_toggle(document_id: int):
    """Marca/desmarca "precisa de tradução" num item do checklist de
    documentos de apoio (RequiredDocument, ver app/onboarding.py) --
    pedido do usuário 2026-08-06: staff marca aqui, em Procedures; o item
    passa a aparecer na aba "Translations" do cliente automaticamente
    (ver app/crm_client.py::translations()) e ele recebe uma notificação
    (mesmo widget da equipe, ver app/services/notification_service.py).
    Desmarcar não some retroativamente da história de notificações, só
    tira o item da lista de traduções pendentes dele."""
    from app.models import Payment, RequiredDocument

    document = SessionLocal.get(RequiredDocument, document_id)
    if document is None:
        abort(404)

    document.needs_translation = not document.needs_translation
    audit_service.log_change(
        "Document", document.id, "field_update", field="needs_translation",
        old_value=not document.needs_translation, new_value=document.needs_translation,
        description=f"Marked '{document.label}' as {'needing' if document.needs_translation else 'not needing'} translation",
        user_id=current_user.id)

    payment = SessionLocal.get(Payment, document.onboarding.payment_id)
    case = SessionLocal.get(Case, payment.case_id) if payment and payment.case_id else None
    if document.needs_translation and case is not None and case.client.user_id:
        from app.services.notification_service import notify
        notify(
            "translation_ready",
            title="Document flagged for translation",
            body=document.label,
            url=url_for("crm_client.translations"),
            recipient_user_id=case.client.user_id,
        )

    SessionLocal.commit()
    return redirect(request.referrer or url_for("crm_ops.case_procedure", case_id=case.id if case else 0))


CASE_DETAILS_TRACKED_FIELDS = [
    "priority", "responsible_id", "field_office_id", "receipt_number",
    "receipt_date", "service_deadline", "rfe_received", "google_drive_url", "notes",
]


@crm_ops_bp.route("/casos/<int:case_id>/detalhes", methods=["POST"])
def case_details_update(case_id: int):
    """Campos de execução do serviço que não têm nenhuma outra tela de
    edição -- prioridade, responsável, field office, nº/data de recibo,
    prazo, RFE, pasta do Google Drive e notas internas (pedido do usuário
    2026-08-06: campos do Case que já existem no banco mas nunca tiveram
    UI, ver app/crm_models.py::Case)."""
    case = SessionLocal.get(Case, case_id)
    if case is None:
        abort(404)

    try:
        concurrency_service.checar_versao(case, request.form.get("version"))
    except concurrency_service.ConflitoEdicaoError:
        flash(
            "This case was edited by someone else while you had this page "
            "open. Reload the page to see their changes before saving yours.",
            "error")
        return redirect(url_for("crm_ops.case_procedure", case_id=case_id))

    before = {f: getattr(case, f) for f in CASE_DETAILS_TRACKED_FIELDS}

    case.priority = svc.parse_enum(Priority, request.form.get("priority"), default=case.priority)
    case.responsible_id = svc.parse_int(request.form.get("responsible_id"))
    case.field_office_id = svc.parse_int(request.form.get("field_office_id"))
    case.receipt_number = request.form.get("receipt_number", "").strip() or None
    case.receipt_date = svc.parse_date(request.form.get("receipt_date"))
    case.service_deadline = svc.parse_date(request.form.get("service_deadline"))
    case.rfe_received = request.form.get("rfe_received") == "on"
    case.google_drive_url = request.form.get("google_drive_url", "").strip() or None
    case.notes = request.form.get("notes", "").strip() or None

    changes = {f: (before[f], getattr(case, f)) for f in CASE_DETAILS_TRACKED_FIELDS}
    audit_service.log_field_changes("Case", case.id, changes, user_id=current_user.id)

    concurrency_service.bump_versao(case)
    SessionLocal.commit()
    flash("Case details updated.", "success")
    return redirect(url_for("crm_ops.case_procedure", case_id=case_id))


@crm_ops_bp.route("/casos/<int:case_id>/notas", methods=["POST"])
def case_notes_update(case_id: int):
    """Campo de notas isolado, editável direto na ficha do cliente
    (crm_client_detail.html) -- pedido do usuário 2026-08-06. Rota
    PRÓPRIA (não reaproveita case_details_update acima) de propósito:
    aquela rota grava TODOS os 9 campos incondicionalmente a partir do
    form, então um formulário compacto que só tivesse "notes" apagaria os
    outros 8 -- mesmo bug de dado real já visto nesta sessão com
    client_update/lead_update."""
    case = SessionLocal.get(Case, case_id)
    if case is None:
        abort(404)
    old_notes = case.notes
    case.notes = request.form.get("notes", "").strip() or None
    if old_notes != case.notes:
        audit_service.log_change(
            "Case", case.id, "field_update", field="notes",
            old_value=old_notes, new_value=case.notes, user_id=current_user.id)
    SessionLocal.commit()
    flash("Case notes updated.", "success")
    return redirect(url_for("crm_pipeline.client_detail", client_id=case.client_id))


@crm_ops_bp.route("/casos/<int:case_id>/campos-personalizados", methods=["POST"])
def case_custom_fields_save(case_id: int):
    """Grava os valores dos Custom Fields (Prompt Mestre, Fase 5,
    2026-08-06) pra este case -- um form próprio, só com esses campos,
    mesmo motivo de `case_notes_update` acima (rota estreita, não a
    "salva tudo" de `case_details_update`)."""
    from app.services import custom_fields_service as cfsvc

    case = SessionLocal.get(Case, case_id)
    if case is None:
        abort(404)
    fields = cfsvc.active_fields("Case")
    before = cfsvc.values_for_entity("Case", case.id)
    cfsvc.save_values("Case", case.id, fields, request.form)
    SessionLocal.flush()
    after = cfsvc.values_for_entity("Case", case.id)
    for field in fields:
        if before.get(field.id) != after.get(field.id):
            audit_service.log_change(
                "Case", case.id, "field_update", field=f"custom:{field.key}",
                old_value=before.get(field.id), new_value=after.get(field.id),
                description=f"Custom field '{field.label}' updated", user_id=current_user.id)
    SessionLocal.commit()
    flash("Custom fields updated.", "success")
    return redirect(url_for("crm_pipeline.client_detail", client_id=case.client_id))


CASE_GLANCE_TRACKED_FIELDS = ["service_deadline", "responsible_id", "priority", "google_drive_url"]


@crm_ops_bp.route("/casos/<int:case_id>/resumo", methods=["POST"])
def case_glance_update(case_id: int):
    """Service Deadline/Responsible/Priority/Google Drive Folder -- pedido
    do usuário 2026-08-06: editáveis direto no topo da ficha do cliente
    ("Case at a glance"), não só na página Procedure. Rota própria (não
    reaproveita case_details_update) pelo mesmo motivo de case_notes_update
    acima: só toca estes 4 campos, nunca os outros 5 de
    case_details_update."""
    case = SessionLocal.get(Case, case_id)
    if case is None:
        abort(404)
    before = {f: getattr(case, f) for f in CASE_GLANCE_TRACKED_FIELDS}

    case.service_deadline = svc.parse_date(request.form.get("service_deadline"))
    case.responsible_id = svc.parse_int(request.form.get("responsible_id"))
    case.priority = svc.parse_enum(Priority, request.form.get("priority"), default=case.priority)
    case.google_drive_url = request.form.get("google_drive_url", "").strip() or None

    changes = {f: (before[f], getattr(case, f)) for f in CASE_GLANCE_TRACKED_FIELDS}
    audit_service.log_field_changes("Case", case.id, changes, user_id=current_user.id)

    SessionLocal.commit()
    flash("Case updated.", "success")
    return redirect(url_for("crm_pipeline.client_detail", client_id=case.client_id))


@crm_ops_bp.route("/casos/<int:case_id>/checagem-status", methods=["POST"])
def case_status_check_confirm(case_id: int):
    """"Confirm Case Status Check" (equivalente ao botão do Notion) --
    stamps Last Checked on hoje e agenda o próximo em
    DEFAULT_STATUS_CHECK_INTERVAL_DAYS dias. Existia como função de
    serviço (crm_service.py::confirm_case_status_check) desde a Fase 1,
    mas nunca tinha sido ligada a nenhuma rota."""
    case = SessionLocal.get(Case, case_id)
    if case is None:
        abort(404)
    svc.confirm_case_status_check(case)
    audit_service.log_change("Case", case.id, "status_check",
                              description="Status check confirmed", user_id=current_user.id)
    SessionLocal.commit()
    flash("Status check confirmed.", "success")
    return redirect(url_for("crm_ops.case_procedure", case_id=case_id))


@crm_ops_bp.route("/casos/<int:case_id>/submeter", methods=["POST"])
def case_submit_application(case_id: int):
    """"Submit Application" -- marca submission_date, process_status e
    case_status (crm_service.py::submit_application, mesma situação de
    case_status_check_confirm acima: existia sem rota)."""
    case = SessionLocal.get(Case, case_id)
    if case is None:
        abort(404)
    svc.submit_application(case)
    audit_service.log_change("Case", case.id, "submit_application",
                              description="Application marked as submitted", user_id=current_user.id)
    SessionLocal.commit()
    flash("Application marked as submitted.", "success")
    return redirect(url_for("crm_ops.case_procedure", case_id=case_id))


@crm_ops_bp.route("/casos/<int:case_id>/aprovar", methods=["POST"])
def case_register_approval(case_id: int):
    """"Register Approval" -- marca approval_date e fecha o caso como
    aprovado (crm_service.py::register_approval)."""
    case = SessionLocal.get(Case, case_id)
    if case is None:
        abort(404)
    svc.register_approval(case)
    audit_service.log_change("Case", case.id, "register_approval",
                              description="Case registered as approved", user_id=current_user.id)
    SessionLocal.commit()
    flash("Case registered as approved.", "success")
    return redirect(url_for("crm_ops.case_procedure", case_id=case_id))


@crm_ops_bp.route("/casos/<int:case_id>/procedimento/passo", methods=["POST"])
def case_step_toggle(case_id: int):
    case = SessionLocal.get(Case, case_id)
    if case is None:
        abort(404)
    step_name = request.form.get("step_name", "").strip()
    if not step_name:
        abort(400)
    existing = SessionLocal.query(CaseStepLog).filter_by(case_id=case.id, step_name=step_name).first()
    if existing is not None:
        SessionLocal.delete(existing)
        audit_service.log_change("Case", case.id, "step_unchecked",
                                  description=f"Step unchecked: {step_name}", user_id=current_user.id)
    else:
        SessionLocal.add(CaseStepLog(case_id=case.id, step_name=step_name))
        audit_service.log_change("Case", case.id, "step_checked",
                                  description=f"Step checked: {step_name}", user_id=current_user.id)
    SessionLocal.commit()
    return redirect(url_for("crm_ops.case_procedure", case_id=case_id))


@crm_ops_bp.route("/casos/<int:case_id>/mensagens")
def case_messages(case_id: int):
    """Thread de comunicação interna cliente/staff (CaseMessage) do caso --
    irmã de case_documents()/case_procedure() acima, mesmo padrão de página
    dedicada por caso. Espelha app/crm_client.py::meu_caso() do lado do
    cliente. Pedido do usuário, 2026-08-02."""
    case = SessionLocal.get(Case, case_id)
    if case is None:
        abort(404)
    messages = sorted(case.messages, key=lambda m: m.created_at, reverse=True)
    # CaseMessage.created_by_id não tem relationship ORM de propósito (mesmo
    # padrão de Communication.created_by_id acima) -- resolve os User aqui
    # numa única query em vez de um relationship cross-module.
    author_ids = {m.created_by_id for m in messages if m.created_by_id}
    authors = {u.id: u for u in SessionLocal.query(User).filter(User.id.in_(author_ids)).all()} if author_ids else {}
    return render_template(
        "crm_case_messages.html", case=case, messages=messages, authors=authors,
        message_types=list(CaseMessageType), priorities=list(Priority),
        statuses=list(CaseMessageStatus))


@crm_ops_bp.route("/casos/<int:case_id>/mensagens/novo", methods=["POST"])
def case_message_new(case_id: int):
    case = SessionLocal.get(Case, case_id)
    if case is None:
        abort(404)
    body = request.form.get("body", "").strip()
    if not body:
        flash("Enter a message before sending.", "error")
        return redirect(url_for("crm_ops.case_messages", case_id=case_id))

    attachment_path = None
    attachment_name = None
    file_storage = request.files.get("attachment")
    if file_storage is not None and file_storage.filename:
        try:
            attachment_path = case_messages_svc.save_attachment(file_storage)
            attachment_name = file_storage.filename
        except ValueError:
            flash("File format not allowed.", "error")
            return redirect(url_for("crm_ops.case_messages", case_id=case_id))

    SessionLocal.add(CaseMessage(
        case_id=case.id, client_id=case.client_id,
        message_type=svc.parse_enum(CaseMessageType, request.form.get("message_type"), default=CaseMessageType.message),
        priority=svc.parse_enum(Priority, request.form.get("priority"), default=Priority.medium),
        status=CaseMessageStatus.open, due_at=svc.parse_date(request.form.get("due_at")),
        body=body, attachment_path=attachment_path, attachment_name=attachment_name,
        author_role=CaseMessageAuthorRole.staff, created_by_id=current_user.id))
    SessionLocal.commit()
    flash("Message sent.", "success")
    return redirect(url_for("crm_ops.case_messages", case_id=case_id))


@crm_ops_bp.route("/mensagens/<int:message_id>/status", methods=["POST"])
def case_message_status_update(message_id: int):
    message = SessionLocal.get(CaseMessage, message_id)
    if message is None:
        abort(404)
    status = svc.parse_enum(CaseMessageStatus, request.form.get("status"))
    if status is not None:
        message.status = status
        SessionLocal.commit()
    return redirect(url_for("crm_ops.case_messages", case_id=message.case_id))


@crm_ops_bp.route("/mensagens/<int:message_id>/anexo")
def case_message_attachment(message_id: int):
    message = SessionLocal.get(CaseMessage, message_id)
    if message is None or not message.attachment_path:
        abort(404)
    return send_file(message.attachment_path, download_name=message.attachment_name)


@crm_ops_bp.route("/documentos/<int:document_id>/arquivo")
def document_file(document_id: int):
    """Staff abre o arquivo que o cliente enviou (ver
    app/crm_client.py::document_upload) -- mesmo arquivo, rota própria do
    lado do staff (sem checagem de user_id, só is_staff via
    before_request acima)."""
    document = SessionLocal.get(Document, document_id)
    if document is None or not document.file_path:
        abort(404)
    return send_file(document.file_path)


@crm_ops_bp.route("/documentos/<int:document_id>/receber", methods=["POST"])
def document_receive(document_id: int):
    document = SessionLocal.get(Document, document_id)
    if document is None:
        abort(404)
    document.received_at = svc.today()
    SessionLocal.commit()

    from app.services.notification_service import notify
    notify(
        "document_received",
        title=f"Document received — {document.case.client.full_name}",
        body=document.name,
        url=url_for("crm_ops.case_documents", case_id=document.case_id),
    )

    return redirect(url_for("crm_ops.case_documents", case_id=document.case_id))


@crm_ops_bp.route("/documentos/<int:document_id>/status", methods=["POST"])
def document_status_update(document_id: int):
    """Status unificado do documento (DocumentStatus, ver app/crm_models.py)
    -- pedido do usuário 2026-08-02, substitui a antiga barra de progresso
    0..10 (coluna `progress` mantida no banco, só não é mais lida por
    nenhuma tela)."""
    document = SessionLocal.get(Document, document_id)
    if document is None:
        abort(404)
    status = svc.parse_enum(DocumentStatus, request.form.get("status"))
    if status is not None:
        old_status = document.status
        document.status = status
        if old_status != status:
            audit_service.log_change(
                "Document", document.id, "stage_change", field="status",
                old_value=old_status.value, new_value=status.value,
                description=f"Moved from {old_status.value} to {status.value}",
                user_id=current_user.id, source=AuditSource.manual)
        SessionLocal.commit()
    return redirect(request.referrer or url_for("crm_ops.case_documents", case_id=document.case_id))


@crm_ops_bp.route("/documentos/<int:document_id>/traducao", methods=["POST"])
def document_translation_save(document_id: int):
    """Ficha de tradução do documento -- tradutor (diretório próprio,
    Translator, não User/staff), tier de velocidade cobrado do cliente,
    datas de solicitação/entrega, número de páginas, e os dois preços por
    página (na moeda do tradutor + em dólar). Nenhum total é gravado --
    ver app/services/crm_service.py::translation_client_total_cents e
    afins, calculados na leitura. Pedido do usuário 2026-08-02."""
    document = SessionLocal.get(Document, document_id)
    if document is None:
        abort(404)

    translator_id = svc.parse_int(request.form.get("translator_id"))
    speed_tier = svc.parse_enum(TranslationSpeedTier, request.form.get("speed_tier"))
    requested_at = svc.parse_date(request.form.get("requested_at"))
    delivered_at = svc.parse_date(request.form.get("delivered_at"))
    deadline = svc.parse_date(request.form.get("deadline"))
    page_count = svc.parse_int(request.form.get("page_count"))
    price_translator_currency = svc.parse_dollars_to_cents(request.form.get("price_per_page_translator_currency", ""))
    price_usd = svc.parse_dollars_to_cents(request.form.get("price_per_page_usd", ""))
    notes = request.form.get("notes", "").strip() or None

    translation_tracked_fields = [
        "translator_id", "speed_tier", "requested_at", "delivered_at", "deadline",
        "page_count", "price_per_page_translator_currency_cents", "price_per_page_usd_cents", "notes",
    ]
    is_new = document.translation is None
    before = ({f: None for f in translation_tracked_fields} if is_new
              else {f: getattr(document.translation, f) for f in translation_tracked_fields})

    if document.translation is None:
        document.translation = DocumentTranslation(document_id=document.id)
        SessionLocal.add(document.translation)

    document.translation.translator_id = translator_id
    document.translation.speed_tier = speed_tier
    document.translation.requested_at = requested_at
    document.translation.delivered_at = delivered_at
    document.translation.deadline = deadline
    document.translation.page_count = page_count
    document.translation.price_per_page_translator_currency_cents = price_translator_currency
    document.translation.price_per_page_usd_cents = price_usd
    document.translation.notes = notes

    if is_new:
        audit_service.log_change("Document", document.id, "create",
                                  description="Translation job created", user_id=current_user.id)
    else:
        changes = {f: (before[f], getattr(document.translation, f)) for f in translation_tracked_fields}
        audit_service.log_field_changes("Document", document.id, changes, user_id=current_user.id)

    SessionLocal.commit()
    flash("Translation updated.", "success")
    return redirect(url_for("crm_ops.case_documents", case_id=document.case_id))


@crm_ops_bp.route("/documentos/<int:document_id>/traducao/finalizar", methods=["POST"])
def document_translation_finish(document_id: int):
    document = SessionLocal.get(Document, document_id)
    if document is None or document.translation is None:
        abort(404)
    svc.finish_review(document.translation)
    audit_service.log_change("Document", document.id, "translation_finished",
                              description="Translation review finished", user_id=current_user.id)
    SessionLocal.commit()
    flash("Review finished.", "success")
    return redirect(url_for("crm_ops.case_documents", case_id=document.case_id))


# --------------------------------------------------------------------------
# Pagamentos (ledger financeiro)
# --------------------------------------------------------------------------

@crm_ops_bp.route("/pagamentos")
def payments():
    mes = request.args.get("mes", "").strip()
    direcao = request.args.get("direcao", "").strip()

    query = SessionLocal.query(PaymentLedgerEntry)
    if direcao in (PaymentDirection.receivable.value, PaymentDirection.payable.value):
        query = query.filter_by(direction=PaymentDirection(direcao))
    rows = query.order_by(PaymentLedgerEntry.payment_date.desc().nullslast(),
                           PaymentLedgerEntry.due_date.asc().nullslast()).all()

    if mes:
        grouped = svc.group_payments_by_month(rows)
        rows = grouped.get(mes, [])

    months = sorted({svc.month_key(p.payment_date) for p in
                      SessionLocal.query(PaymentLedgerEntry).filter(
                          PaymentLedgerEntry.payment_date.is_not(None)).all()}, reverse=True)

    clients = {c.id: c for c in SessionLocal.query(Client).all()}
    financial_clients = {fc.id: fc for fc in SessionLocal.query(FinancialClient).all()}
    methods = {m.id: m for m in SessionLocal.query(PaymentMethodLookup).all()}
    cases = {c.id: c for c in SessionLocal.query(Case).all()}
    return render_template(
        "crm_payments.html", payments=rows, months=months, mes=mes, direcao=direcao,
        clients=clients, financial_clients=financial_clients, methods=methods, cases=cases,
        statuses=list(PaymentStatus),
        payment_methods=SessionLocal.query(PaymentMethodLookup).order_by(PaymentMethodLookup.name).all(),
        fee_types=SessionLocal.query(FeeType).order_by(FeeType.name).all())


@crm_ops_bp.route("/pagamentos/metodos/novo", methods=["POST"])
def payment_method_new():
    """"Adicionar novo" (pedido do usuário 2026-08-06) -- PaymentMethodLookup
    é lookup aberta, mas nunca teve UI pra crescer além do seed inicial."""
    name = request.form.get("name", "").strip()
    if not name:
        flash("Payment method name is required.", "error")
        return redirect(request.referrer or url_for("crm_ops.payments"))
    if SessionLocal.query(PaymentMethodLookup).filter_by(name=name).first() is not None:
        flash(f'"{name}" is already in the list.', "error")
        return redirect(request.referrer or url_for("crm_ops.payments"))
    SessionLocal.add(PaymentMethodLookup(name=name))
    SessionLocal.commit()
    flash(f'"{name}" added to payment methods.', "success")
    return redirect(request.referrer or url_for("crm_ops.payments"))


@crm_ops_bp.route("/pagamentos/metodos/<int:method_id>/renomear", methods=["POST"])
def payment_method_rename(method_id: int):
    """Renomear preserva o id -- os 234 pagamentos reais que já referenciam
    payment_method_id continuam apontando pro registro certo, só o texto
    exibido muda (pedido do usuário: "os que já temos sejam editáveis")."""
    method = SessionLocal.get(PaymentMethodLookup, method_id)
    if method is None:
        abort(404)
    name = request.form.get("name", "").strip()
    if not name:
        flash("Payment method name is required.", "error")
        return redirect(request.referrer or url_for("crm_ops.payments"))
    method.name = name
    SessionLocal.commit()
    flash("Payment method updated.", "success")
    return redirect(request.referrer or url_for("crm_ops.payments"))


@crm_ops_bp.route("/pagamentos/taxas/nova", methods=["POST"])
def fee_type_new():
    name = request.form.get("name", "").strip()
    if not name:
        flash("Fee type name is required.", "error")
        return redirect(request.referrer or url_for("crm_ops.payments"))
    if SessionLocal.query(FeeType).filter_by(name=name).first() is not None:
        flash(f'"{name}" is already in the list.', "error")
        return redirect(request.referrer or url_for("crm_ops.payments"))
    SessionLocal.add(FeeType(name=name))
    SessionLocal.commit()
    flash(f'"{name}" added to fee types.', "success")
    return redirect(request.referrer or url_for("crm_ops.payments"))


@crm_ops_bp.route("/pagamentos/taxas/<int:fee_type_id>/renomear", methods=["POST"])
def fee_type_rename(fee_type_id: int):
    fee_type = SessionLocal.get(FeeType, fee_type_id)
    if fee_type is None:
        abort(404)
    name = request.form.get("name", "").strip()
    if not name:
        flash("Fee type name is required.", "error")
        return redirect(request.referrer or url_for("crm_ops.payments"))
    fee_type.name = name
    SessionLocal.commit()
    flash("Fee type updated.", "success")
    return redirect(request.referrer or url_for("crm_ops.payments"))


@crm_ops_bp.route("/pagamentos/novo", methods=["GET", "POST"])
def payment_new():
    """Ledger reusado pelas duas linhas de negócio (imigração e coaching
    financeiro, ver app/crm_models.py::PaymentLedgerEntry) -- `owner_type`
    decide se o lançamento vai em `client_id` ou `financial_client_id`;
    exatamente um dos dois é preenchido, nunca os dois nem nenhum."""
    if request.method == "POST":
        owner_type = request.form.get("owner_type", "client")
        if owner_type not in ("client", "financial_client"):
            # Nunca deixa cair no "senão" das duas atribuições abaixo e
            # criar um lançamento sem client_id NEM financial_client_id --
            # um POST malformado/adulterado é o único jeito de chegar aqui,
            # já que o <select> real só oferece esses 2 valores.
            flash("Invalid client type.", "error")
            return redirect(url_for("crm_ops.payment_new"))
        owner_id_raw = request.form.get(
            "owner_id_financial" if owner_type == "financial_client" else "owner_id_client", "")
        description = request.form.get("description", "").strip()
        amount_cents = svc.parse_dollars_to_cents(request.form.get("amount_dollars", ""))

        if not owner_id_raw or not description or amount_cents is None:
            flash("Client, description, and amount are required.", "error")
            return redirect(url_for("crm_ops.payment_new"))

        owner_id = svc.parse_int(owner_id_raw)
        if owner_id is None:
            flash("Invalid client.", "error")
            return redirect(url_for("crm_ops.payment_new"))

        entry = PaymentLedgerEntry(
            client_id=owner_id if owner_type == "client" else None,
            financial_client_id=owner_id if owner_type == "financial_client" else None,
            case_id=svc.parse_int(request.form.get("case_id")),
            description=description, amount_cents=amount_cents,
            currency=svc.parse_enum(Currency, request.form.get("currency"), default=Currency.usd),
            direction=svc.parse_enum(PaymentDirection, request.form.get("direction"),
                                      default=PaymentDirection.receivable),
            status=svc.parse_enum(PaymentStatus, request.form.get("status"), default=PaymentStatus.pending),
            due_date=svc.parse_date(request.form.get("due_date")),
        )
        SessionLocal.add(entry)
        SessionLocal.commit()
        flash("Entry created.", "success")
        return redirect(url_for("crm_ops.payments"))

    clients = SessionLocal.query(Client).order_by(Client.full_name).all()
    financial_clients_list = SessionLocal.query(FinancialClient).order_by(FinancialClient.full_name).all()
    return render_template(
        "crm_payments.html", new_form=True, clients_list=clients,
        financial_clients_list=financial_clients_list,
        cases_list=SessionLocal.query(Case).order_by(Case.title).all(),
        currencies=list(Currency), directions=list(PaymentDirection), statuses=list(PaymentStatus),
        payments=[], months=[], mes="", direcao="", clients={}, financial_clients={}, methods={},
        cases={}, payment_methods=[], fee_types=[])


@crm_ops_bp.route("/pagamentos/<int:payment_id>/status", methods=["POST"])
def payment_update_status(payment_id: int):
    entry = SessionLocal.get(PaymentLedgerEntry, payment_id)
    if entry is None:
        abort(404)
    old_status = entry.status
    entry.status = svc.parse_enum(PaymentStatus, request.form.get("status"), default=entry.status)
    if entry.status == PaymentStatus.paid and entry.payment_date is None:
        entry.payment_date = svc.today()
    if old_status != entry.status:
        audit_service.log_change(
            "PaymentLedgerEntry", entry.id, "field_update", field="status",
            old_value=old_status.value, new_value=entry.status.value, user_id=current_user.id)
    SessionLocal.commit()
    return redirect(request.referrer or url_for("crm_ops.payments"))


@crm_ops_bp.route("/pagamentos/<int:payment_id>")
def payment_detail(payment_id: int):
    """Ficha completa de um lançamento -- pedido do usuário 2026-08-06: até
    aqui só o status era editável (inline, na listagem); nenhum dos outros
    campos que já existiam no modelo (case, payment method, approved/
    reviewed by, discount, notes...) tinha UI nenhuma."""
    entry = SessionLocal.get(PaymentLedgerEntry, payment_id)
    if entry is None:
        abort(404)
    history = audit_service.get_history("PaymentLedgerEntry", entry.id)
    history_users = {u.id: u for u in SessionLocal.query(User).all()}
    return render_template(
        "crm_payment_detail.html", p=entry,
        clients_list=SessionLocal.query(Client).order_by(Client.full_name).all(),
        financial_clients_list=SessionLocal.query(FinancialClient).order_by(FinancialClient.full_name).all(),
        cases_list=SessionLocal.query(Case).order_by(Case.title).all(),
        currencies=list(Currency), directions=list(PaymentDirection), statuses=list(PaymentStatus),
        packages=list(ServiceMode), staff_users=svc.staff_users(),
        payment_methods=SessionLocal.query(PaymentMethodLookup).order_by(PaymentMethodLookup.name).all(),
        fee_types=SessionLocal.query(FeeType).order_by(FeeType.name).all(),
        selected_fee_type_ids={ft.fee_type_id for ft in entry.fee_types},
        history=history, history_users=history_users)


PAYMENT_LEDGER_TRACKED_FIELDS = [
    "client_id", "financial_client_id", "case_id", "description", "amount_cents", "currency",
    "direction", "status", "package", "payment_method_id", "invoice_date", "due_date", "payment_date",
    "approved_by_id", "reviewed_by_id", "discount_cents", "notes", "confirmation_id",
    "confirmation_notes", "paid_by",
]


@crm_ops_bp.route("/pagamentos/<int:payment_id>/salvar", methods=["POST"])
def payment_update(payment_id: int):
    entry = SessionLocal.get(PaymentLedgerEntry, payment_id)
    if entry is None:
        abort(404)

    before = {f: getattr(entry, f) for f in PAYMENT_LEDGER_TRACKED_FIELDS}
    before_fee_type_ids = {ft.fee_type_id for ft in entry.fee_types}

    owner_type = request.form.get("owner_type", "client")
    owner_id_raw = request.form.get(
        "owner_id_financial" if owner_type == "financial_client" else "owner_id_client", "")
    owner_id = svc.parse_int(owner_id_raw)
    description = request.form.get("description", "").strip()
    amount_cents = svc.parse_dollars_to_cents(request.form.get("amount_dollars", ""))
    if owner_id is None or not description or amount_cents is None:
        flash("Client, description, and amount are required.", "error")
        return redirect(url_for("crm_ops.payment_detail", payment_id=payment_id))

    entry.client_id = owner_id if owner_type == "client" else None
    entry.financial_client_id = owner_id if owner_type == "financial_client" else None
    entry.case_id = svc.parse_int(request.form.get("case_id"))
    entry.description = description
    entry.amount_cents = amount_cents
    entry.currency = svc.parse_enum(Currency, request.form.get("currency"), default=entry.currency)
    entry.direction = svc.parse_enum(PaymentDirection, request.form.get("direction"), default=entry.direction)
    entry.status = svc.parse_enum(PaymentStatus, request.form.get("status"), default=entry.status)
    if entry.status == PaymentStatus.paid and entry.payment_date is None:
        entry.payment_date = svc.today()
    entry.package = svc.parse_enum(ServiceMode, request.form.get("package"))
    entry.payment_method_id = svc.parse_int(request.form.get("payment_method_id"))

    entry.invoice_date = svc.parse_date(request.form.get("invoice_date"))
    entry.due_date = svc.parse_date(request.form.get("due_date"))
    entry.payment_date = svc.parse_date(request.form.get("payment_date")) or entry.payment_date
    entry.approved_by_id = svc.parse_int(request.form.get("approved_by_id"))
    entry.reviewed_by_id = svc.parse_int(request.form.get("reviewed_by_id"))
    entry.discount_cents = svc.parse_dollars_to_cents(request.form.get("discount_dollars", ""))
    entry.notes = request.form.get("notes", "").strip() or None

    entry.confirmation_id = request.form.get("confirmation_id", "").strip() or None
    entry.confirmation_notes = request.form.get("confirmation_notes", "").strip() or None
    entry.paid_by = request.form.get("paid_by", "").strip() or None

    file_storage = request.files.get("receipt")
    if file_storage is not None and file_storage.filename:
        from app.services.payment_receipts import save_receipt
        try:
            entry.receipt_file_path = save_receipt(file_storage)
            entry.receipt_file_name = file_storage.filename
        except ValueError:
            flash("Receipt file type not supported.", "error")
            return redirect(url_for("crm_ops.payment_detail", payment_id=payment_id))

    # Type of Fee Payment -- só faz sentido pra Payables (pedido do
    # usuário: "Se for Payables mostrar -> Type of Fee Payment"), mas
    # salva o que vier do form de qualquer forma; o form em si só manda
    # esses checkboxes quando a seção está visível (ver JS no template).
    fee_type_ids = {svc.parse_int(v) for v in request.form.getlist("fee_type_ids")}
    fee_type_ids.discard(None)
    SessionLocal.query(PaymentLedgerFeeType).filter_by(payment_id=entry.id).delete()
    for fee_type_id in fee_type_ids:
        SessionLocal.add(PaymentLedgerFeeType(payment_id=entry.id, fee_type_id=fee_type_id))

    changes = {f: (before[f], getattr(entry, f)) for f in PAYMENT_LEDGER_TRACKED_FIELDS}
    audit_service.log_field_changes("PaymentLedgerEntry", entry.id, changes, user_id=current_user.id)
    if before_fee_type_ids != fee_type_ids:
        audit_service.log_change(
            "PaymentLedgerEntry", entry.id, "field_update", field="fee_type_ids",
            old_value=sorted(before_fee_type_ids), new_value=sorted(fee_type_ids), user_id=current_user.id)

    SessionLocal.commit()
    flash("Payment updated.", "success")
    return redirect(url_for("crm_ops.payment_detail", payment_id=payment_id))


@crm_ops_bp.route("/pagamentos/<int:payment_id>/comprovante")
def payment_receipt_download(payment_id: int):
    entry = SessionLocal.get(PaymentLedgerEntry, payment_id)
    if entry is None or not entry.receipt_file_path:
        abort(404)
    return send_file(entry.receipt_file_path, download_name=entry.receipt_file_name or "receipt")


# --------------------------------------------------------------------------
# Comunicações
# --------------------------------------------------------------------------

@crm_ops_bp.route("/comunicacoes")
def communications():
    client_id_raw = request.args.get("client_id", "")
    client_id_filter = svc.parse_int(client_id_raw)
    query = SessionLocal.query(Communication)
    if client_id_filter is not None:
        query = query.filter_by(client_id=client_id_filter)
    rows = query.order_by(Communication.occurred_at.desc()).all()

    clients = {c.id: c for c in SessionLocal.query(Client).all()}
    channels = {ch.id: ch for ch in SessionLocal.query(ContactChannel).all()}
    return render_template(
        "crm_communications.html", communications=rows, clients=clients, channels=channels,
        client_id=client_id_raw, follow_ups=False, statuses=list(CommStatus))


@crm_ops_bp.route("/comunicacoes/follow-ups")
def communications_follow_ups():
    today = svc.today()
    rows = (
        SessionLocal.query(Communication)
        .filter(Communication.next_followup_at.is_not(None), Communication.next_followup_at >= today)
        .order_by(Communication.next_followup_at.asc())
        .all()
    )
    clients = {c.id: c for c in SessionLocal.query(Client).all()}
    channels = {ch.id: ch for ch in SessionLocal.query(ContactChannel).all()}
    return render_template(
        "crm_communications.html", communications=rows, clients=clients, channels=channels,
        client_id="", follow_ups=True, statuses=list(CommStatus))


@crm_ops_bp.route("/comunicacoes/novo", methods=["GET", "POST"])
def communication_new():
    if request.method == "POST":
        client_id_raw = request.form.get("client_id", "")
        subject = request.form.get("subject", "").strip()
        if not client_id_raw or not subject:
            flash("Client and subject are required.", "error")
            return redirect(url_for("crm_ops.communication_new"))

        client_id = svc.parse_int(client_id_raw)
        if client_id is None:
            flash("Invalid client.", "error")
            return redirect(url_for("crm_ops.communication_new"))

        notify_client = request.form.get("notify_client") == "on"
        comm = Communication(
            client_id=client_id,
            case_id=svc.parse_int(request.form.get("case_id")),
            subject=subject,
            direction=svc.parse_enum(CommDirection, request.form.get("direction"),
                                      default=CommDirection.outbound),
            channel_id=svc.parse_int(request.form.get("channel_id")),
            summary=request.form.get("summary", "").strip() or None,
            next_followup_at=svc.parse_date(request.form.get("next_followup_at")),
            notify_client=notify_client,
            created_by_id=current_user.id,
        )
        SessionLocal.add(comm)
        SessionLocal.flush()
        audit_service.log_change("Communication", comm.id, "create",
                                  description=f"Communication logged: {subject}", user_id=current_user.id)

        # Pedido do usuário 2026-08-06: "que ambas as partes sejam
        # notificadas, que mostre o que está pendente" -- notify_client já
        # existia no modelo mas nunca era lido nem acionava nada (só ficava
        # como dado morto). Aqui: cliente com login recebe a mesma
        # notificação privada (símbolo da Saes piscando, ver
        # app/client_notifications.py) que a equipe já tinha; sem login
        # (full_service sem conta), o checkbox só fica marcado pra
        # referência do staff -- não há pra quem notificar de verdade.
        client = SessionLocal.get(Client, client_id)
        if notify_client and client is not None and client.user_id:
            from app.services.notification_service import notify
            notify(
                "communication_pending",
                title=f"Update from Saes — {subject}",
                body=comm.summary,
                url=url_for("crm_client.meu_caso"),
                recipient_user_id=client.user_id,
            )

        SessionLocal.commit()
        flash("Communication logged.", "success")
        return redirect(url_for("crm_ops.communications"))

    clients = SessionLocal.query(Client).order_by(Client.full_name).all()
    channels = SessionLocal.query(ContactChannel).order_by(ContactChannel.name).all()
    return render_template(
        "crm_communications.html", new_form=True, clients_list=clients, channels_list=channels,
        directions=list(CommDirection), communications=[], clients={}, channels={}, client_id="",
        follow_ups=False)


@crm_ops_bp.route("/comunicacoes/<int:communication_id>/status", methods=["POST"])
def communication_status_update(communication_id: int):
    """Marca uma comunicação como resolvida (ou volta pra em andamento) --
    pedido do usuário 2026-08-06: sem isto, nada que fosse marcado
    "pendente" (status != done) jamais saía da lista de pendências do
    cliente/staff. Não existia rota nenhuma de edição de Communication
    além da criação até aqui."""
    comm = SessionLocal.get(Communication, communication_id)
    if comm is None:
        abort(404)
    new_status = svc.parse_enum(CommStatus, request.form.get("status"))
    if new_status is not None and new_status != comm.status:
        old_status = comm.status
        comm.status = new_status
        audit_service.log_change(
            "Communication", comm.id, "field_update", field="status",
            old_value=old_status.value, new_value=new_status.value, user_id=current_user.id)
        SessionLocal.commit()
    return redirect(request.referrer or url_for("crm_ops.communications"))


# --------------------------------------------------------------------------
# Tarefas
# --------------------------------------------------------------------------

_TASK_QUICK_FILTERS = ("mine", "today", "upcoming", "overdue")


@crm_ops_bp.route("/tarefas")
def tasks():
    rows = SessionLocal.query(Task).order_by(Task.due_date.asc().nullslast()).all()

    # Visualizações rápidas (Prompt Mestre, Seção 11: "Minhas tarefas;
    # Hoje; Próximas; Vencidas"), 2026-08-06 -- filtro sobre a mesma lista
    # já carregada, não uma query nova; combina com qualquer view
    # (Kanban/Tabela/Lista/Calendário) escolhida.
    quick_filter = request.args.get("filter", "")
    if quick_filter not in _TASK_QUICK_FILTERS:
        quick_filter = ""
    today_ = svc.today()
    if quick_filter == "mine":
        rows = [t for t in rows if t.responsible_id == current_user.id]
    elif quick_filter == "today":
        rows = [t for t in rows if t.due_date == today_]
    elif quick_filter == "upcoming":
        rows = [t for t in rows if t.due_date is not None and t.due_date > today_]
    elif quick_filter == "overdue":
        rows = [t for t in rows if t.due_date is not None and t.due_date < today_ and t.status != TaskStatus.done]

    by_status: dict[TaskStatus, list[Task]] = {status: [] for status in TaskStatus}
    for t in rows:
        by_status[t.status].append(t)
    cases = {c.id: c for c in SessionLocal.query(Case).all()}
    users = {u.id: u for u in SessionLocal.query(User).all()}

    # Alternância Kanban/Tabela/Lista/Calendário (Prompt Mestre, Fase 4,
    # 2026-08-06) -- calendário usa due_date.
    view = request.args.get("view", "kanban")
    if view not in ("kanban", "table", "list", "calendar"):
        view = "kanban"
    stage_labels = pipeline_stage_service.stage_labels("task_status")
    columns = [
        {"label": "Title", "value": lambda t: t.title,
         "url": lambda t: url_for("crm_ops.task_detail", task_id=t.id)},
        {"label": "Case", "value": lambda t: (cases[t.case_id].title if t.case_id in cases else "—")},
        {"label": "Owner", "value": lambda t: (users[t.responsible_id].email if t.responsible_id in users else "—")},
        {"label": "Priority", "value": lambda t: t.priority.value.title()},
        {"label": "Status", "value": lambda t: stage_labels.get(t.status.value, t.status.value.replace('_', ' ').title())},
        {"label": "Due", "value": lambda t: (t.due_date.strftime("%m/%d/%Y") if t.due_date else "—")},
    ]
    calendar_grid = None
    if view == "calendar":
        from app.services.calendar_view import build_calendar_grid
        today = svc.today()
        year = svc.parse_int(request.args.get("year")) or today.year
        month = svc.parse_int(request.args.get("month")) or today.month
        calendar_grid = build_calendar_grid(rows, lambda t: t.due_date, year, month)

    return render_template(
        "crm_tasks.html", by_status=by_status,
        statuses=pipeline_stage_service.ordered_members("task_status"), cases=cases, users=users,
        stage_colors=pipeline_stage_service.stage_colors("task_status"),
        stage_labels=stage_labels,
        view=view, columns=columns, calendar_grid=calendar_grid, all_rows=rows,
        quick_filter=quick_filter)


@crm_ops_bp.route("/tarefas/novo", methods=["GET", "POST"])
def task_new():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        if not title:
            flash("Title is required.", "error")
            return redirect(url_for("crm_ops.task_new"))

        task = Task(
            title=title,
            case_id=svc.parse_int(request.form.get("case_id")),
            task_type=svc.parse_enum(TaskType, request.form.get("task_type")),
            priority=svc.parse_enum(Priority, request.form.get("priority"), default=Priority.medium),
            responsible_id=svc.parse_int(request.form.get("responsible_id")),
            requested_by_id=current_user.id,
            due_date=svc.parse_date(request.form.get("due_date")),
        )
        SessionLocal.add(task)
        SessionLocal.flush()
        audit_service.log_change("Task", task.id, "create",
                                  description=f"Task '{title}' created", user_id=current_user.id)
        SessionLocal.commit()
        flash("Task created.", "success")
        return redirect(url_for("crm_ops.tasks"))

    cases = SessionLocal.query(Case).order_by(Case.title).all()
    return render_template(
        "crm_tasks.html", new_form=True, cases_list=cases, staff_users=svc.staff_users(),
        task_types=list(TaskType), priorities=list(Priority),
        by_status={}, statuses=[], cases={}, users={})


@crm_ops_bp.route("/tarefas/<int:task_id>/status", methods=["POST"])
def task_update_status(task_id: int):
    task = SessionLocal.get(Task, task_id)
    if task is None:
        abort(404)
    old_status = task.status
    task.status = svc.parse_enum(TaskStatus, request.form.get("status"), default=task.status)
    just_completed = task.status == TaskStatus.done and old_status != TaskStatus.done
    if task.status == TaskStatus.done and task.completed_at is None:
        task.completed_at = datetime.now(timezone.utc)
        task.pct_done = 100
    if old_status != task.status:
        audit_service.log_change(
            "Task", task.id, "stage_change", field="status",
            old_value=old_status.value, new_value=task.status.value,
            description=f"Moved from {old_status.value} to {task.status.value}",
            user_id=current_user.id, source=AuditSource.manual)

    # Recorrência (Prompt Mestre, Seção 11), 2026-08-06 -- disparada pelo
    # próprio evento de "marcar como concluída" (sem cron nenhum, ver
    # docstring de Task.recurrence_interval_days): cria a PRÓXIMA
    # ocorrência na hora, com o mesmo intervalo, pra continuar repetindo.
    if just_completed and task.recurrence_interval_days:
        next_due = (task.due_date or svc.today()) + timedelta(days=task.recurrence_interval_days)
        next_task = Task(
            title=task.title, case_id=task.case_id, task_type=task.task_type,
            priority=task.priority, responsible_id=task.responsible_id,
            requested_by_id=task.requested_by_id, due_date=next_due,
            notes=task.notes, recurrence_interval_days=task.recurrence_interval_days,
        )
        SessionLocal.add(next_task)
        SessionLocal.flush()
        audit_service.log_change(
            "Task", next_task.id, "create",
            description=f"Recurring task created from Task #{task.id} (repeats every "
                         f"{task.recurrence_interval_days} day(s))",
            user_id=current_user.id, source=AuditSource.automatic)

    SessionLocal.commit()
    return redirect(request.referrer or url_for("crm_ops.tasks"))


@crm_ops_bp.route("/tarefas/<int:task_id>")
def task_detail(task_id: int):
    """Ficha da tarefa -- não existia antes (só o card do Kanban e a troca
    de status), pedido do Prompt Mestre (Seção 11: "subtarefas,
    checklists... tempo registrado... por tarefa"). Tempo trabalhado
    reusa `TimeEntry.task_id` (já existia no model, só nunca tinha sido
    mostrado em lugar nenhum -- ver app/planner_models.py)."""
    from app.planner_models import TimeEntry
    from app.services import planner_service as planner_svc

    task = SessionLocal.get(Task, task_id)
    if task is None:
        abort(404)

    time_entries = (
        SessionLocal.query(TimeEntry).filter_by(task_id=task.id)
        .order_by(TimeEntry.started_at.desc()).all()
    )
    total_seconds = sum(planner_svc.entry_duration_seconds(e) for e in time_entries)

    history = audit_service.get_history("Task", task.id)
    history_users = {u.id: u for u in SessionLocal.query(User).all()}

    return render_template(
        "crm_task_detail.html", task=task, cases=SessionLocal.query(Case).order_by(Case.title).all(),
        staff_users=svc.staff_users(), task_types=list(TaskType), priorities=list(Priority),
        statuses=list(TaskStatus), time_entries=time_entries, total_seconds=total_seconds,
        entry_duration=planner_svc.entry_duration_seconds, format_duration=planner_svc.format_duration,
        history=history, history_users=history_users)


_TASK_TRACKED_FIELDS = ["title", "case_id", "task_type", "priority", "responsible_id", "due_date", "notes",
                         "recurrence_interval_days"]


@crm_ops_bp.route("/tarefas/<int:task_id>/salvar", methods=["POST"])
def task_save(task_id: int):
    task = SessionLocal.get(Task, task_id)
    if task is None:
        abort(404)
    before = {f: getattr(task, f) for f in _TASK_TRACKED_FIELDS}

    title = request.form.get("title", "").strip()
    if not title:
        flash("Title is required.", "error")
        return redirect(url_for("crm_ops.task_detail", task_id=task.id))

    task.title = title
    task.case_id = svc.parse_int(request.form.get("case_id"))
    task.task_type = svc.parse_enum(TaskType, request.form.get("task_type"))
    task.priority = svc.parse_enum(Priority, request.form.get("priority"), default=task.priority)
    task.responsible_id = svc.parse_int(request.form.get("responsible_id"))
    task.due_date = svc.parse_date(request.form.get("due_date"))
    task.notes = request.form.get("notes", "").strip() or None
    task.recurrence_interval_days = svc.parse_int(request.form.get("recurrence_interval_days"))

    changes = {f: (before[f], getattr(task, f)) for f in _TASK_TRACKED_FIELDS}
    audit_service.log_field_changes("Task", task.id, changes, user_id=current_user.id)

    SessionLocal.commit()
    flash("Task updated.", "success")
    return redirect(url_for("crm_ops.task_detail", task_id=task.id))


@crm_ops_bp.route("/tarefas/<int:task_id>/checklist", methods=["POST"])
def task_checklist_add(task_id: int):
    task = SessionLocal.get(Task, task_id)
    if task is None:
        abort(404)
    title = request.form.get("title", "").strip()
    if not title:
        return redirect(url_for("crm_ops.task_detail", task_id=task.id))

    next_position = len(task.checklist_items)
    SessionLocal.add(TaskChecklistItem(task_id=task.id, title=title, position=next_position))
    audit_service.log_change("Task", task.id, "checklist_add",
                              description=f"Checklist item added: {title}", user_id=current_user.id)
    SessionLocal.commit()
    return redirect(url_for("crm_ops.task_detail", task_id=task.id))


@crm_ops_bp.route("/tarefas/checklist/<int:item_id>/marcar", methods=["POST"])
def task_checklist_toggle(item_id: int):
    item = SessionLocal.get(TaskChecklistItem, item_id)
    if item is None:
        abort(404)
    item.done = not item.done
    audit_service.log_change(
        "Task", item.task_id, "checklist_toggle",
        description=f"Checklist item {'checked' if item.done else 'unchecked'}: {item.title}",
        user_id=current_user.id)
    SessionLocal.commit()
    return redirect(url_for("crm_ops.task_detail", task_id=item.task_id))


@crm_ops_bp.route("/tarefas/checklist/<int:item_id>/apagar", methods=["POST"])
def task_checklist_delete(item_id: int):
    item = SessionLocal.get(TaskChecklistItem, item_id)
    if item is None:
        abort(404)
    task_id = item.task_id
    audit_service.log_change("Task", task_id, "checklist_delete",
                              description=f"Checklist item removed: {item.title}", user_id=current_user.id)
    SessionLocal.delete(item)
    SessionLocal.commit()
    return redirect(url_for("crm_ops.task_detail", task_id=task_id))


@crm_ops_bp.route("/tarefas/<int:task_id>/comentarios", methods=["POST"])
def task_comment_new(task_id: int):
    """Thread de comentários da tarefa (Prompt Mestre, Seção 11:
    "Comentários... Anexos"), 2026-08-06 -- staff-only, mesmo padrão de
    anexo já usado em CaseMessage (app/services/case_messages.py)."""
    task = SessionLocal.get(Task, task_id)
    if task is None:
        abort(404)
    body = request.form.get("body", "").strip()
    if not body:
        flash("Comment can't be empty.", "error")
        return redirect(url_for("crm_ops.task_detail", task_id=task_id))

    attachment_path = None
    attachment_name = None
    file_storage = request.files.get("attachment")
    if file_storage is not None and file_storage.filename:
        try:
            attachment_path = case_messages_svc.save_attachment(file_storage)
            attachment_name = file_storage.filename
        except ValueError:
            flash("That file type isn't supported.", "error")
            return redirect(url_for("crm_ops.task_detail", task_id=task_id))

    SessionLocal.add(TaskComment(
        task_id=task.id, author_id=current_user.id, body=body,
        attachment_path=attachment_path, attachment_name=attachment_name))
    SessionLocal.commit()
    return redirect(url_for("crm_ops.task_detail", task_id=task_id))


@crm_ops_bp.route("/tarefas/comentarios/<int:comment_id>/anexo")
def task_comment_attachment(comment_id: int):
    comment = SessionLocal.get(TaskComment, comment_id)
    if comment is None or not comment.attachment_path:
        abort(404)
    return send_file(comment.attachment_path, download_name=comment.attachment_name)
