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
                             CaseMessageType, Client, ContractDocumentType,
                             ContractStatus, ContractTier, PaymentMethodLookup,
                             Priority)
from app.db import SessionLocal
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
    from app.i18n import t

    client = _client_for_current_user()
    if client is None:
        flash(t("my_case_none_yet"), "success")
        return redirect(url_for("wizard.dashboard"))

    cases = [
        {
            "case": case,
            "pending_documents": case_pending_documents(case),
            "messages": sorted(case.messages, key=lambda m: m.created_at, reverse=True),
        }
        for case in client.cases
    ]
    recent_communications = sorted(
        client.communications, key=lambda c: c.occurred_at, reverse=True)[:5]

    return render_template(
        "meu_caso.html", client=client, cases=cases,
        recent_communications=recent_communications,
        message_types=list(CaseMessageType), priorities=list(Priority))


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
    return render_template(
        "meu_traducoes.html", client=client, documents=documents,
        client_total_cents=translation_client_total_cents,
        client_price_per_page_cents=translation_client_price_per_page_cents)


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

    payment_methods = SessionLocal.query(PaymentMethodLookup).order_by(PaymentMethodLookup.name).all()
    return render_template(
        "meu_contrato.html", contract=contract, client=contract.case.client, service_name=service_name,
        price_cents=price_cents, tier_includes=tier_includes, tier_excludes=tier_excludes,
        payment_methods=payment_methods)


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
    SessionLocal.commit()
    flash(t("contract_flash_rejected"), "success")
    return redirect(url_for("crm_client.contract_view", contract_id=contract_id))
