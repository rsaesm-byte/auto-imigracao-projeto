"""Painel do cliente "Meu Caso" -- mostra o(s) Case(s) do CRM
(app/crm_models.py) vinculados ao usuário logado via Client.user_id, e
(pedido do usuário, 2026-08-02) a thread de mensagens (CaseMessage) de cada
caso -- forma interna de comunicação cliente/colaborador (mensagens,
feedback, solicitações internas, atualizações), centralizada aqui e no
detalhe do caso no painel staff (app/crm_staff_ops.py::case_messages).

Isolamento (o ponto mais sensível deste módulo): a busca do Client é SEMPRE
por `Client.user_id == current_user.id` -- a rota principal (meu_caso)
nunca aceita client_id/case_id vindo de querystring ou form. As duas rotas
novas que recebem um `case_id`/`message_id` na URL (para postar uma
mensagem ou baixar um anexo) verificam a posse do caso via `_owned_case()`
antes de qualquer outra coisa -- um cliente jamais acessa o caso de outro
cliente através daqui.
"""
from __future__ import annotations

from datetime import datetime, timezone

from flask import Blueprint, abort, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required

from app.crm_models import (Case, CaseContract, CaseMessage,
                             CaseMessageAuthorRole, CaseMessageStatus,
                             CaseMessageType, Client, ClientApprovalStatus,
                             ContractDocumentType, ContractStatus,
                             ContractTier, Document, DocumentStatus,
                             PaymentMethodLookup, Priority)
from app.db import SessionLocal
from app.services import audit_service
from app.services import case_documents as case_documents_svc
from app.services import case_messages as case_messages_svc
from app.services import crm_service as svc
from app.services.crm_service import (case_pending_documents, parse_date,
                                       parse_enum, parse_int,
                                       translation_client_price_per_page_cents,
                                       translation_client_total_cents)
from app.services.signatures import save_signature_png

crm_client_bp = Blueprint("crm_client", __name__)


def _client_for_current_user() -> Client | None:
    if not current_user.is_authenticated:
        return None
    return SessionLocal.query(Client).filter_by(user_id=current_user.id).first()


def _owned_case(case_id: int) -> Case:
    case = SessionLocal.get(Case, case_id)
    if case is None or case.client.user_id != current_user.id:
        abort(404)
    return case


@crm_client_bp.app_context_processor
def _inject_has_crm_case():
    # Blueprint.app_context_processor injeta contexto pra TODA a aplicação
    # (não só nas rotas deste blueprint) -- é assim que base.html decide
    # mostrar o link "Meu Caso" sem app/__init__.py precisar saber deste
    # módulo (o registro do blueprint em si é feito numa etapa separada).
    return {"has_crm_case": _client_for_current_user() is not None}


@crm_client_bp.route("/meu-caso")
@login_required
def meu_caso():
    from app.i18n import get_lang, t

    client = _client_for_current_user()
    if client is None:
        flash(t("my_case_none_yet"), "success")
        return redirect(url_for("wizard.dashboard"))

    from app.models import Payment, PostPaymentOnboarding
    from app.services.service_procedures import translate_document_label

    # Pedido do usuário 2026-08-06: cliente também vê o que está pendente
    # (não só a equipe) -- só as comunicações que o staff marcou
    # explicitamente "Notify the client" (notify_client=True) E ainda não
    # resolvidas (status != done). Sem notify_client, fica só como
    # anotação interna do staff, nunca aparece aqui.
    from app.crm_models import CommStatus
    pending_client_communications = [
        c for c in client.communications
        if c.notify_client and c.status != CommStatus.done
    ]
    pending_client_communications.sort(key=lambda c: c.occurred_at, reverse=True)

    lang = get_lang()

    from app.services import custom_fields_service as cfsvc
    client_visible_fields = [f for f in cfsvc.active_fields("Case") if f.client_visible]

    # Custom Fields no nível da CONTA (não por caso) -- pedido do usuário
    # 2026-08-06: estender Custom Fields pra Client também. Só os
    # marcados client_visible=True, sempre somente-leitura aqui.
    account_visible_fields = [f for f in cfsvc.active_fields("Client") if f.client_visible]
    account_custom_values = cfsvc.values_for_entity("Client", client.id)
    account_custom_fields = [
        {"label": f.label, "value": cfsvc.display_value(f, account_custom_values.get(f.id))}
        for f in account_visible_fields
    ]

    cases = []
    for case in client.cases:
        case_custom_values = cfsvc.values_for_entity("Case", case.id)
        gate_payment = (
            SessionLocal.query(Payment)
            .filter_by(case_id=case.id, status="confirmed")
            .order_by(Payment.id.desc())
            .first()
        )
        onboarding = (
            SessionLocal.query(PostPaymentOnboarding).filter_by(payment_id=gate_payment.id).first()
            if gate_payment is not None else None
        )
        cases.append({
            "case": case,
            "pending_documents": case_pending_documents(case),
            "messages": sorted(case.messages, key=lambda m: m.created_at, reverse=True),
            # Comprovante enviado no gate de pagamento (app/payment_gate.py)
            # ainda não confirmado pelo staff -- pedido do usuário
            # 2026-08-06: mostrar aqui, separado do banner de pending_payments
            # acima (que é sobre PaymentLedgerEntry, o financeiro do CRM).
            "gate_payment_pending": (
                SessionLocal.query(Payment)
                .filter_by(case_id=case.id, status="pending")
                .first()
                is not None
            ),
            # Checklist de documentos de apoio pós-pagamento (RequiredDocument,
            # ver app/onboarding.py) -- pedido do usuário 2026-08-06: ele só
            # aparecia numa tela separada (/pendencias, achável só por um
            # tile no /dashboard), nunca em Meu Caso, que é onde o cliente de
            # fato olha. Reaproveita as MESMAS rotas de upload/download já
            # existentes em app/onboarding.py (já checam payment.user_id ==
            # current_user.id sozinhas) -- só muda onde a lista é exibida.
            "onboarding": onboarding,
            "onboarding_documents": [
                {"doc": d, "label": translate_document_label(d.label, lang)}
                for d in (onboarding.documents if onboarding else [])
            ],
            # Custom Fields visíveis pro cliente (Prompt Mestre, Fase 5,
            # 2026-08-06) -- só os marcados client_visible=True em
            # /staff/crm/campos-personalizados, sempre somente-leitura aqui.
            "custom_fields": [
                {"label": f.label, "value": cfsvc.display_value(f, case_custom_values.get(f.id))}
                for f in client_visible_fields
            ],
        })
    recent_communications = sorted(
        client.communications, key=lambda c: c.occurred_at, reverse=True)[:5]

    return render_template(
        "meu_caso.html", client=client, cases=cases,
        recent_communications=recent_communications,
        pending_client_communications=pending_client_communications,
        message_types=list(CaseMessageType), priorities=list(Priority),
        account_custom_fields=account_custom_fields)


@crm_client_bp.route("/minhas-traducoes")
@login_required
def translations():
    """Aba "Translations" do cliente -- pedido do usuário 2026-08-02: mostra
    todo documento (de qualquer caso do cliente) que o staff já marcou
    como precisando de tradução (tem uma DocumentTranslation), com a(s)
    página(s), o preço por página do tier de velocidade escolhido, e o
    total do documento (páginas × preço) -- nenhum total gravado, sempre
    calculado (ver crm_service.py, mesma convenção do resto do CRM)."""
    client = _client_for_current_user()
    if client is None:
        abort(404)
    documents = [
        d for case in client.cases for d in case.documents
        if d.translation is not None
    ]

    # Itens do checklist de onboarding (RequiredDocument) marcados pelo
    # staff em Procedures -- pedido do usuário 2026-08-06: aparecem aqui
    # automaticamente, mesmo sem preço/tradutor definidos ainda (esse
    # sistema não tem a mesma infraestrutura de precificação por página do
    # Document/DocumentTranslation acima -- é só um aviso "sinalizado pra
    # tradução, a equipe vai te dar mais detalhes")."""
    from app.models import Payment, PostPaymentOnboarding

    flagged_checklist_items = []
    for case in client.cases:
        payment = SessionLocal.query(Payment).filter_by(case_id=case.id, status="confirmed").first()
        if payment is None:
            continue
        onboarding = SessionLocal.query(PostPaymentOnboarding).filter_by(payment_id=payment.id).first()
        if onboarding is None:
            continue
        for doc in onboarding.documents:
            if doc.needs_translation:
                flagged_checklist_items.append({"doc": doc, "case": case})

    return render_template(
        "meu_traducoes.html", client=client, documents=documents,
        flagged_checklist_items=flagged_checklist_items,
        client_total_cents=translation_client_total_cents,
        client_price_per_page_cents=translation_client_price_per_page_cents)


_TRANSLATION_APPROVAL_ACTIONS = {
    "approve": ClientApprovalStatus.approved,
    "changes": ClientApprovalStatus.changes_requested,
    "reject": ClientApprovalStatus.rejected,
}


@crm_client_bp.route("/minhas-traducoes/documentos/<int:document_id>/aprovacao", methods=["POST"])
@login_required
def translation_approval(document_id: int):
    """Cliente Aprova/Solicita alteração/Recusa um orçamento de tradução já
    cotado -- pedido do Prompt Mestre (Fase 7), 2026-08-06. Só permitido
    quando o staff já preencheu tier + páginas (o mesmo critério que a
    tela já usa pra decidir se mostra um total ou "pending pricing" --
    ver translation_client_total_cents em app/services/crm_service.py).
    Posse verificada via _owned_case(document.case_id), mesmo padrão do
    resto deste blueprint -- nunca por document_id/case_id cru."""
    document = SessionLocal.get(Document, document_id)
    if document is None or document.translation is None:
        abort(404)
    _owned_case(document.case_id)  # 404s if this document's case isn't the current client's

    if translation_client_total_cents(document.translation) is None:
        flash("This translation doesn't have a final quote yet.", "error")
        return redirect(url_for("crm_client.translations"))

    action = request.form.get("action", "")
    new_status = _TRANSLATION_APPROVAL_ACTIONS.get(action)
    if new_status is None:
        abort(400)

    note = request.form.get("note", "").strip() or None
    old_status = document.translation.client_approval_status
    document.translation.client_approval_status = new_status
    document.translation.client_approval_note = note
    document.translation.client_approval_at = datetime.now(timezone.utc)

    audit_service.log_change(
        "Document", document.id, "client_approval", field="client_approval_status",
        old_value=old_status, new_value=new_status,
        description=f"Client {new_status.value.replace('_', ' ')} the translation quote"
                     + (f": {note}" if note else ""),
        user_id=current_user.id)
    SessionLocal.commit()

    from app.services.notification_service import notify
    notify(
        "translation_client_response",
        title=f"Translation quote {new_status.value.replace('_', ' ')} — {document.name}",
        body=note or f"{document.client.full_name} responded to the translation quote.",
        url=url_for("crm_ops.case_documents", case_id=document.case_id),
    )

    flash("Thanks, we've recorded your response.", "success")
    return redirect(url_for("crm_client.translations"))


@crm_client_bp.route("/meu-caso/casos/<int:case_id>/mensagens", methods=["POST"])
@login_required
def case_message_new(case_id: int):
    from app.i18n import t

    case = _owned_case(case_id)
    body = request.form.get("body", "").strip()
    if not body:
        flash(t("my_case_msg_flash_empty"), "error")
        return redirect(url_for("crm_client.meu_caso"))

    attachment_path = None
    attachment_name = None
    file_storage = request.files.get("attachment")
    if file_storage is not None and file_storage.filename:
        try:
            attachment_path = case_messages_svc.save_attachment(file_storage)
            attachment_name = file_storage.filename
        except ValueError:
            flash(t("my_case_msg_flash_bad_ext"), "error")
            return redirect(url_for("crm_client.meu_caso"))

    SessionLocal.add(CaseMessage(
        case_id=case.id, client_id=case.client_id,
        message_type=parse_enum(CaseMessageType, request.form.get("message_type"), default=CaseMessageType.message),
        priority=parse_enum(Priority, request.form.get("priority"), default=Priority.medium),
        status=CaseMessageStatus.open, due_at=parse_date(request.form.get("due_at")),
        body=body, attachment_path=attachment_path, attachment_name=attachment_name,
        author_role=CaseMessageAuthorRole.client, created_by_id=current_user.id))
    SessionLocal.commit()

    from app.services.notification_service import notify
    notify(
        "message_new",
        title=f"New message — {case.client.full_name}",
        body=body[:140],
        url=url_for("crm_ops.case_messages", case_id=case.id),
    )

    flash(t("my_case_msg_flash_sent"), "success")
    return redirect(url_for("crm_client.meu_caso"))


@crm_client_bp.route("/meu-caso/mensagens/<int:message_id>/anexo")
@login_required
def message_attachment(message_id: int):
    message = SessionLocal.get(CaseMessage, message_id)
    if message is None or not message.attachment_path:
        abort(404)
    if message.case.client.user_id != current_user.id:
        abort(404)
    return send_file(message.attachment_path, download_name=message.attachment_name)


@crm_client_bp.route("/meu-caso/documentos/<int:document_id>/upload", methods=["POST"])
@login_required
def document_upload(document_id: int):
    """Cliente envia o arquivo de um Document pedido pela equipe
    ("Documentos do Caso", ver app/crm_staff_ops.py::case_document_new) --
    pedido do usuário 2026-08-06: até aqui só existia esse campo de upload
    pro checklist SEPARADO de onboarding (app/onboarding.py); aqui fecha a
    mesma lacuna pro pedido de documento avulso que o staff cria em
    qualquer caso. `received_at`/`status` avançam sozinhos -- staff não
    precisa mais clicar "Mark received" à parte quando o cliente já
    enviou o arquivo de verdade."""
    document = SessionLocal.get(Document, document_id)
    if document is None or document.client.user_id != current_user.id:
        abort(404)

    file_storage = request.files.get("file")
    if file_storage is None or not file_storage.filename:
        flash("Attach a file before sending.", "error")
        return redirect(url_for("crm_client.meu_caso"))
    try:
        document.file_path = case_documents_svc.save_case_document(file_storage)
    except ValueError:
        flash("Invalid file -- upload an image, PDF or Word document.", "error")
        return redirect(url_for("crm_client.meu_caso"))

    document.received_at = svc.today()
    document.status = DocumentStatus.in_review
    audit_service.log_change(
        "Document", document.id, "field_update", field="file_path",
        description=f"Client uploaded a file for '{document.name}'", user_id=current_user.id)
    SessionLocal.commit()

    from app.services.notification_service import notify
    notify(
        "document_received",
        title=f"Document received — {document.client.full_name}",
        body=document.name,
        url=url_for("crm_ops.case_documents", case_id=document.case_id),
    )

    flash("Document sent.", "success")
    return redirect(url_for("crm_client.meu_caso"))


@crm_client_bp.route("/meu-caso/documentos/<int:document_id>/arquivo")
@login_required
def document_file(document_id: int):
    """O cliente pode reabrir o arquivo que ele mesmo enviou -- nunca de
    outro cliente."""
    document = SessionLocal.get(Document, document_id)
    if document is None or not document.file_path:
        abort(404)
    if document.client.user_id != current_user.id:
        abort(404)
    return send_file(document.file_path)


def _owned_contract(contract_id: int) -> CaseContract:
    contract = SessionLocal.get(CaseContract, contract_id)
    if contract is None or contract.case.client.user_id != current_user.id:
        abort(404)
    return contract


@crm_client_bp.route("/meu-caso/contrato/<int:contract_id>")
@login_required
def contract_view(contract_id: int):
    """Tela de assinatura do cliente -- pedido do usuário 2026-08-02.
    Abrir esta página é o que transiciona not_started -> in_review (ver
    svc.open_contract_for_review, idempotente/nunca regride)."""
    from app.i18n import get_lang, t  # noqa: F401 (t usado no template via jinja global)
    from app.services.service_procedures import load_service_procedure, service_display_name
    from app.services.text_format import markdown_lite_to_html

    contract = _owned_contract(contract_id)
    svc.open_contract_for_review(contract)
    SessionLocal.commit()

    service_name = None
    tier_includes: list[str] = []
    tier_excludes: list[str] = []
    price_cents = None
    if contract.document_type == ContractDocumentType.service_contract and contract.service is not None:
        price_cents = svc.contract_price_cents(contract)
        lang = get_lang()
        service_name = service_display_name(contract.service.slug, lang)
        template = load_service_procedure(contract.service.slug)
        if template is not None:
            # `_pt`/`_es` suffix is this project's existing convention for
            # client-facing translated arrays (same pattern as `documents`/
            # `documents_pt`/`documents_es` on each phase) -- falls back to
            # the English key only if `lang` isn't pt/es (i.e. is "en").
            suffix = f"_{lang}" if lang in ("pt", "es") else ""
            base_field = "standard" if contract.tier == ContractTier.standard else "plus"
            tier_includes = template.get(f"{base_field}_includes{suffix}", [])
            tier_excludes = template.get(f"{base_field}_excludes{suffix}", [])

    # Termos gerais editáveis pelo staff (/staff/crm/contratos/termos, pedido
    # do usuário 2026-08-02) -- renderizados de markdown pro mesmo idioma da
    # sessão, com fallback pro inglês se o campo daquele idioma vier vazio.
    lang = get_lang()
    terms = svc.get_company_contract_terms()
    lang_suffix = lang if lang in ("pt", "es") else "en"
    general_terms_md = getattr(terms, f"general_terms_{lang_suffix}") or terms.general_terms_en
    if contract.document_type == ContractDocumentType.service_contract:
        general_terms_md += "\n- " + (getattr(terms, f"payment_separate_{lang_suffix}") or terms.payment_separate_en)
    general_terms_html = markdown_lite_to_html(general_terms_md)
    tc_intro_html = markdown_lite_to_html(getattr(terms, f"tc_intro_{lang_suffix}") or terms.tc_intro_en)

    payment_methods = SessionLocal.query(PaymentMethodLookup).order_by(PaymentMethodLookup.name).all()
    return render_template(
        "meu_contrato.html", contract=contract, client=contract.case.client, service_name=service_name,
        price_cents=price_cents, tier_includes=tier_includes, tier_excludes=tier_excludes,
        payment_methods=payment_methods, general_terms_html=general_terms_html, tc_intro_html=tc_intro_html)


@crm_client_bp.route("/meu-caso/contrato/<int:contract_id>/assinar", methods=["POST"])
@login_required
def contract_sign(contract_id: int):
    from app.i18n import t

    contract = _owned_contract(contract_id)
    if contract.status == ContractStatus.signed:
        return redirect(url_for("crm_client.contract_view", contract_id=contract_id))

    signature_path = save_signature_png(request.form.get("signature_data", ""))
    if signature_path is None:
        flash(t("contract_flash_signature_required"), "error")
        return redirect(url_for("crm_client.contract_view", contract_id=contract_id))

    payment_method_id = None
    if contract.document_type == ContractDocumentType.service_contract:
        payment_method_id = parse_int(request.form.get("payment_method_id"))
        if payment_method_id is None:
            flash(t("contract_flash_payment_method_required"), "error")
            return redirect(url_for("crm_client.contract_view", contract_id=contract_id))

    svc.sign_contract(
        contract, signature_image_path=signature_path, payment_method_id=payment_method_id,
        signer_ip=request.remote_addr)
    svc.create_payment_request_for_contract(contract)
    audit_service.log_change("Contract", contract.id, "signed",
                              description="Contract signed by client", user_id=current_user.id)
    SessionLocal.commit()
    flash(t("contract_flash_signed"), "success")
    return redirect(url_for("crm_client.contract_view", contract_id=contract_id))


@crm_client_bp.route("/meu-caso/contrato/<int:contract_id>/rejeitar", methods=["POST"])
@login_required
def contract_reject(contract_id: int):
    from app.i18n import t

    contract = _owned_contract(contract_id)
    if contract.status == ContractStatus.signed:
        return redirect(url_for("crm_client.contract_view", contract_id=contract_id))
    svc.reject_contract(contract)
    audit_service.log_change("Contract", contract.id, "rejected",
                              description="Contract rejected by client", user_id=current_user.id)
    SessionLocal.commit()
    flash(t("contract_flash_rejected"), "success")
    return redirect(url_for("crm_client.contract_view", contract_id=contract_id))
