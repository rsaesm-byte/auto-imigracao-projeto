"""Blueprint do CRM (staff) -- Documentos, Pagamentos (ledger financeiro),
Comunicações e Tarefas. Irmão de app/crm_staff_pipeline.py (Clientes/Leads/
Casos) -- blueprint separado (mesmo url_prefix) só pra manter os arquivos
independentes; ambos vivem sob /staff/crm.
"""
from __future__ import annotations

from datetime import datetime, timezone

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.crm_financial_models import FinancialClient
from app.crm_models import (Case, Client, CommDirection, CommStatus,
                             Communication, ContactChannel, Currency,
                             Document, DocumentTranslation, DocumentType,
                             FeeType, PaymentDirection, PaymentLedgerEntry,
                             PaymentMethodLookup, PaymentStatus, Priority,
                             Task, TaskStatus, TaskType,
                             TranslationLanguage, TranslationStatus)
from app.db import SessionLocal
from app.models import User
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
    return render_template(
        "crm_documents.html", case=case,
        document_types=list(DocumentType), translation_languages=list(TranslationLanguage),
        translation_statuses=list(TranslationStatus), staff_users=svc.staff_users())


@crm_ops_bp.route("/casos/<int:case_id>/documentos/novo", methods=["POST"])
def case_document_new(case_id: int):
    case = SessionLocal.get(Case, case_id)
    if case is None:
        abort(404)
    name = request.form.get("name", "").strip()
    if not name:
        flash("Nome do documento é obrigatório.", "error")
        return redirect(url_for("crm_ops.case_documents", case_id=case_id))

    doc_type = svc.parse_enum(DocumentType, request.form.get("document_type"), default=DocumentType.other)
    translation_language = svc.parse_enum(TranslationLanguage, request.form.get("translation_language"))

    SessionLocal.add(Document(
        case_id=case.id, client_id=case.client_id, name=name,
        document_type=doc_type, translation_language=translation_language,
        requested_at=svc.today()))
    SessionLocal.commit()
    flash("Documento adicionado.", "success")
    return redirect(url_for("crm_ops.case_documents", case_id=case_id))


@crm_ops_bp.route("/documentos/<int:document_id>/receber", methods=["POST"])
def document_receive(document_id: int):
    document = SessionLocal.get(Document, document_id)
    if document is None:
        abort(404)
    document.received_at = svc.today()
    SessionLocal.commit()
    return redirect(url_for("crm_ops.case_documents", case_id=document.case_id))


@crm_ops_bp.route("/documentos/<int:document_id>/traducao", methods=["POST"])
def document_translation_save(document_id: int):
    document = SessionLocal.get(Document, document_id)
    if document is None:
        abort(404)

    translator_id = svc.parse_int(request.form.get("translator_id"))
    status = svc.parse_enum(TranslationStatus, request.form.get("status"), default=TranslationStatus.quoted)
    deadline = svc.parse_date(request.form.get("deadline"))

    if document.translation is None:
        document.translation = DocumentTranslation(
            document_id=document.id, translator_id=translator_id, status=status, deadline=deadline)
        SessionLocal.add(document.translation)
    else:
        document.translation.translator_id = translator_id
        document.translation.status = status
        document.translation.deadline = deadline
    SessionLocal.commit()
    flash("Tradução atualizada.", "success")
    return redirect(url_for("crm_ops.case_documents", case_id=document.case_id))


@crm_ops_bp.route("/documentos/<int:document_id>/traducao/finalizar", methods=["POST"])
def document_translation_finish(document_id: int):
    document = SessionLocal.get(Document, document_id)
    if document is None or document.translation is None:
        abort(404)
    svc.finish_review(document.translation)
    SessionLocal.commit()
    flash("Review finalizado.", "success")
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
            flash("Tipo de cliente inválido.", "error")
            return redirect(url_for("crm_ops.payment_new"))
        owner_id_raw = request.form.get(
            "owner_id_financial" if owner_type == "financial_client" else "owner_id_client", "")
        description = request.form.get("description", "").strip()
        amount_cents = svc.parse_dollars_to_cents(request.form.get("amount_dollars", ""))

        if not owner_id_raw or not description or amount_cents is None:
            flash("Cliente, descrição e valor são obrigatórios.", "error")
            return redirect(url_for("crm_ops.payment_new"))

        owner_id = svc.parse_int(owner_id_raw)
        if owner_id is None:
            flash("Cliente inválido.", "error")
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
        flash("Lançamento criado.", "success")
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
            flash("Cliente e assunto são obrigatórios.", "error")
            return redirect(url_for("crm_ops.communication_new"))

        client_id = svc.parse_int(client_id_raw)
        if client_id is None:
            flash("Cliente inválido.", "error")
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
        flash("Comunicação registrada.", "success")
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
            flash("Título é obrigatório.", "error")
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
        flash("Tarefa criada.", "success")
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
