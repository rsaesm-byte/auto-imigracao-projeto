"""Blueprint do CRM (staff) -- Documentos, Pagamentos (ledger financeiro),
Comunicações e Tarefas. Irmão de app/crm_staff_pipeline.py (Clientes/Leads/
Casos) -- blueprint separado (mesmo url_prefix) só pra manter os arquivos
independentes; ambos vivem sob /staff/crm.
"""
from __future__ import annotations

from datetime import datetime, timezone

from flask import Blueprint, abort, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required

from app.crm_financial_models import FinancialClient
from app.crm_models import (Case, CaseMessage, CaseMessageAuthorRole,
                             CaseMessageStatus, CaseMessageType,
                             CaseProgressItem, CaseService, CaseStepLog,
                             Client, CommDirection, CommStatus, Communication,
                             ContactChannel, Currency, Document,
                             DocumentStatus, DocumentTranslation, DocumentType,
                             FeeType, PaymentDirection, PaymentLedgerEntry,
                             PaymentMethodLookup, PaymentStatus, Priority,
                             ProgressCategory, ProgressStatus, ServiceCatalog,
                             ServiceMode, ServiceRole, Task, TaskStatus,
                             TaskType, TranslationLanguage,
                             TranslationSpeedTier, Translator)
from app.db import SessionLocal
from app.models import User
from app.services import case_messages as case_messages_svc
from app.services import crm_service as svc

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
    return render_template(
        "crm_documents.html", case=case,
        document_types=list(DocumentType), translation_languages=list(TranslationLanguage),
        document_statuses=list(DocumentStatus), speed_tiers=list(TranslationSpeedTier),
        translators=SessionLocal.query(Translator).order_by(Translator.full_name).all(),
        currencies=list(Currency), translation_totals=translation_totals,
        staff_users=svc.staff_users())


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

    SessionLocal.add(Document(
        case_id=case.id, client_id=case.client_id, name=name,
        document_type=doc_type, translation_language=translation_language,
        requested_at=svc.today()))
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

    SessionLocal.query(CaseService).filter_by(case_id=case.id, role=ServiceRole.current).delete()
    SessionLocal.add(CaseService(case_id=case.id, service_id=service.id, role=ServiceRole.current))
    case.service_mode = tier
    SessionLocal.flush()
    svc.apply_service_procedure_checklist(case)
    SessionLocal.commit()
    flash("Case service updated.", "success")
    return redirect(url_for("crm_ops.case_procedure", case_id=case_id))


@crm_ops_bp.route("/casos/<int:case_id>/procedimento")
def case_procedure(case_id: int):
    from app.models import Payment
    from app.services.service_procedures import load_service_procedure

    case = SessionLocal.get(Case, case_id)
    if case is None:
        abort(404)

    current_cs = next((cs for cs in case.services if cs.role == ServiceRole.current), None)
    template = load_service_procedure(current_cs.service.slug) if current_cs and current_cs.service.slug else None
    done_steps = {log.step_name for log in case.step_log}
    payment = SessionLocal.query(Payment).filter_by(case_id=case.id, status="confirmed").first()

    services_with_slug = SessionLocal.query(ServiceCatalog).filter(
        ServiceCatalog.slug.is_not(None)).order_by(ServiceCatalog.name).all()

    return render_template(
        "crm_case_procedure.html", case=case, template=template, done_steps=done_steps,
        current_service=current_cs.service if current_cs else None, payment=payment,
        services_with_slug=services_with_slug,
        tiers=[m for m in ServiceMode if m != ServiceMode.self_service])


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
    else:
        SessionLocal.add(CaseStepLog(case_id=case.id, step_name=step_name))
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


@crm_ops_bp.route("/documentos/<int:document_id>/receber", methods=["POST"])
def document_receive(document_id: int):
    document = SessionLocal.get(Document, document_id)
    if document is None:
        abort(404)
    document.received_at = svc.today()
    SessionLocal.commit()
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
        document.status = status
        SessionLocal.commit()
    return redirect(url_for("crm_ops.case_documents", case_id=document.case_id))


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
    SessionLocal.commit()
    flash("Translation updated.", "success")
    return redirect(url_for("crm_ops.case_documents", case_id=document.case_id))


@crm_ops_bp.route("/documentos/<int:document_id>/traducao/finalizar", methods=["POST"])
def document_translation_finish(document_id: int):
    document = SessionLocal.get(Document, document_id)
    if document is None or document.translation is None:
        abort(404)
    svc.finish_review(document.translation)
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
    return render_template(
        "crm_payments.html", payments=rows, months=months, mes=mes, direcao=direcao,
        clients=clients, financial_clients=financial_clients, methods=methods,
        statuses=list(PaymentStatus))


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
        currencies=list(Currency), directions=list(PaymentDirection), statuses=list(PaymentStatus),
        payments=[], months=[], mes="", direcao="", clients={}, financial_clients={}, methods={})


@crm_ops_bp.route("/pagamentos/<int:payment_id>/status", methods=["POST"])
def payment_update_status(payment_id: int):
    entry = SessionLocal.get(PaymentLedgerEntry, payment_id)
    if entry is None:
        abort(404)
    entry.status = svc.parse_enum(PaymentStatus, request.form.get("status"), default=entry.status)
    if entry.status == PaymentStatus.paid and entry.payment_date is None:
        entry.payment_date = svc.today()
    SessionLocal.commit()
    return redirect(request.referrer or url_for("crm_ops.payments"))


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
        client_id=client_id_raw, follow_ups=False)


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
        client_id="", follow_ups=True)


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

        comm = Communication(
            client_id=client_id,
            case_id=svc.parse_int(request.form.get("case_id")),
            subject=subject,
            direction=svc.parse_enum(CommDirection, request.form.get("direction"),
                                      default=CommDirection.outbound),
            channel_id=svc.parse_int(request.form.get("channel_id")),
            summary=request.form.get("summary", "").strip() or None,
            next_followup_at=svc.parse_date(request.form.get("next_followup_at")),
            created_by_id=current_user.id,
        )
        SessionLocal.add(comm)
        SessionLocal.commit()
        flash("Communication logged.", "success")
        return redirect(url_for("crm_ops.communications"))

    clients = SessionLocal.query(Client).order_by(Client.full_name).all()
    channels = SessionLocal.query(ContactChannel).order_by(ContactChannel.name).all()
    return render_template(
        "crm_communications.html", new_form=True, clients_list=clients, channels_list=channels,
        directions=list(CommDirection), communications=[], clients={}, channels={}, client_id="",
        follow_ups=False)


# --------------------------------------------------------------------------
# Tarefas
# --------------------------------------------------------------------------

@crm_ops_bp.route("/tarefas")
def tasks():
    rows = SessionLocal.query(Task).order_by(Task.due_date.asc().nullslast()).all()
    by_status: dict[TaskStatus, list[Task]] = {status: [] for status in TaskStatus}
    for t in rows:
        by_status[t.status].append(t)
    cases = {c.id: c for c in SessionLocal.query(Case).all()}
    users = {u.id: u for u in SessionLocal.query(User).all()}
    return render_template(
        "crm_tasks.html", by_status=by_status, statuses=list(TaskStatus), cases=cases, users=users)


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
    task.status = svc.parse_enum(TaskStatus, request.form.get("status"), default=task.status)
    if task.status == TaskStatus.done and task.completed_at is None:
        task.completed_at = datetime.now(timezone.utc)
        task.pct_done = 100
    SessionLocal.commit()
    return redirect(request.referrer or url_for("crm_ops.tasks"))
