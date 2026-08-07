"""Blueprint do gate de pagamento genérico (formulários avulsos e pacotes
vendidos pela Saes, conforme data/service_fees.json) -- não confundir com
o gate específico das Cartas Complementares do I-539 (FormSubmission.paid,
ver app/staff.py). Fluxo: cliente termina de preencher -> escolhe forma de
pagamento (Zelle/Venmo/Credit Card/Wire Transfer) -> anexa comprovante ->
sai um e-mail de notificação para a equipe (hoje só logado, ver
app/services/email_service.py) -> cliente cai em submitted() (pedido do
usuário 2026-08-06): fica na própria interface do CRM/site vendo "pagamento
pendente de aprovação" e o WhatsApp da empresa abre sozinho numa NOVA aba
(com fallback de botão, caso o navegador bloqueie o popup), em vez do
antigo redirect direto que tirava o cliente do site inteiro.
app/wizard.py::generate()/review() bloqueiam a geração do PDF enquanto o
Payment não estiver status=confirmed (marcado manualmente por um staff em
/staff)."""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from flask import (Blueprint, abort, flash, redirect, render_template,
                    request, session, url_for)
from flask_login import current_user, login_required

from app.db import SessionLocal
from app.models import Payment

payment_gate_bp = Blueprint("payment_gate", __name__, url_prefix="/pagamento")

ROOT = Path(__file__).resolve().parent.parent
PROOFS_DIR = ROOT / "instance" / "payment_proofs"
PROOFS_DIR.mkdir(parents=True, exist_ok=True)

# Número de WhatsApp da Saes Professional Services (mesmo do Zelle, ver
# data/payment_methods.json) -- formato internacional sem símbolos, exigido
# pelo link wa.me.
WHATSAPP_NUMBER = "17815209935"

ALLOWED_PROOF_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".heic"}
METHOD_KEYS = ("zelle", "venmo", "credit_card", "wire")


def _find_payment(case) -> Payment | None:
    from app.services.pricing import find_payment_for_case
    return find_payment_for_case(case)


def _save_proof(file_storage) -> str:
    ext = Path(file_storage.filename).suffix.lower()
    if ext not in ALLOWED_PROOF_EXTENSIONS:
        raise ValueError("extensao_invalida")
    dest = PROOFS_DIR / f"{uuid.uuid4().hex}{ext}"
    file_storage.save(dest)
    return str(dest)


def _whatsapp_url(case_label_en: str, amount_display: str) -> str:
    # Sempre em inglês, independente do idioma do site -- pedido explícito
    # do usuário (mesma regra já aplicada às cartas do I-539, ver
    # scripts/generate_cartas_i539.py::draft_narrative_letter). Por isso
    # `case_label_en` tem que vir de PaymentCase.label_en, nunca de
    # PaymentCase.label (que segue o idioma da sessão).
    today = datetime.now().strftime("%m/%d/%Y")
    message = (
        f"Hello, this is {current_user.email}. I just submitted payment for "
        f"{case_label_en} ({amount_display}) on {today}. Attaching proof of "
        f"payment for your confirmation."
    )
    return f"https://wa.me/{WHATSAPP_NUMBER}?text={quote(message)}"


def _payment_methods_content() -> dict:
    from app.i18n import get_lang
    from app.payment_methods import _CONTENT_PATH, _localize
    raw = json.loads(_CONTENT_PATH.read_text(encoding="utf-8"))
    return _localize(raw, get_lang())


def _convert_lead_and_link_payment(payment: Payment, lead, *, service_mode, case_title: str,
                                    service_id: int | None = None):
    """Núcleo compartilhado: promove `lead` pra Client+Case (ver
    app/services/crm_service.py::convert_lead_to_client_and_case), liga o
    Case ao Payment (`payment.case_id`), opcionalmente registra qual
    ServiceCatalog foi contratado (`service_id`, só pra pacote
    profissional -- pacote DIY/self_service não tem CaseService), e
    dispara notify("payment_submitted"). Usado tanto por checkout() (DIY)
    quanto por checkout_lead() (profissional) abaixo."""
    from app.crm_models import CaseService, ServiceRole
    from app.services.crm_service import convert_lead_to_client_and_case
    from app.services.notification_service import notify

    client, new_case = convert_lead_to_client_and_case(
        lead, service_mode=service_mode, case_title=case_title, user_id=current_user.id)
    SessionLocal.flush()
    payment.case_id = new_case.id

    if service_id is not None:
        SessionLocal.add(CaseService(case_id=new_case.id, service_id=service_id, role=ServiceRole.current))

    notify(
        "payment_submitted",
        title=f"Payment submitted — {client.full_name}",
        body=case_title,
        url=url_for("crm_pipeline.client_detail", client_id=client.id),
    )
    return client, new_case


def _promote_lead_on_payment_submitted(payment: Payment, case) -> None:
    """Promove o Lead aberto desta compra DIY (criado ao "iniciar o
    pacote", ver app/packages.py::_get_or_create_diy_lead) pra Case assim
    que o cliente ENVIA o comprovante -- não espera a confirmação manual
    do staff (ver plano de compra self-service 2026-08-03: "pagamento
    enviado e aguardando aprovação" já deve aparecer no pipeline de
    Casos, não no de Leads). Sem Lead correspondente (ex.: compra avulsa
    de formulário único, fora do escopo desta rotina), não faz nada --
    app/staff.py::confirm_payment já cobre esse caso pelo caminho antigo
    (get_or_create_case_for_payment)."""
    if payment.case_id is not None:
        return  # já promovido (reenvio de comprovante do mesmo pagamento)
    if case.kind != "package":
        return

    from app.crm_models import Lead, LeadStage, ServiceMode

    lead = (
        SessionLocal.query(Lead)
        .filter(Lead.user_id == current_user.id, Lead.interested_package_slug == case.key)
        .filter(~Lead.stage.in_([LeadStage.closed_won, LeadStage.closed_lost]))
        .order_by(Lead.id.desc())
        .first()
    )
    if lead is None:
        return

    _convert_lead_and_link_payment(
        payment, lead, service_mode=ServiceMode.self_service, case_title=case.label)


@payment_gate_bp.route("/<int:submission_id>", methods=["GET", "POST"])
@login_required
def checkout(submission_id: int):
    from app.services.email_service import send_payment_notification_email
    from app.wizard import _get_owned_submission, _payment_case

    submission = _get_owned_submission(submission_id)
    case = _payment_case(submission)
    if case is None:
        abort(404)

    payment = _find_payment(case)
    if payment is not None and payment.status == "confirmed":
        flash("Pagamento já confirmado -- pode gerar o documento normalmente.", "success")
        return redirect(url_for("wizard.review", submission_id=submission.id))

    amount_display = f"${case.price_cents / 100:,.2f}"
    payment_content = _payment_methods_content()

    if request.method == "POST":
        method = request.form.get("method")
        proof = request.files.get("proof")
        client_name = request.form.get("client_name", "").strip()
        client_email = request.form.get("client_email", "").strip()
        client_phone = request.form.get("client_phone", "").strip()

        if not client_name or not client_email or not client_phone:
            flash("Preencha nome completo, e-mail e telefone.", "error")
            return render_template("payment_checkout.html", case=case, amount_display=amount_display,
                                   payment=payment, payment_content=payment_content)
        if method not in METHOD_KEYS:
            flash("Selecione uma forma de pagamento.", "error")
            return render_template("payment_checkout.html", case=case, amount_display=amount_display,
                                   payment=payment, payment_content=payment_content)
        if proof is None or not proof.filename:
            flash("Anexe o comprovante de pagamento.", "error")
            return render_template("payment_checkout.html", case=case, amount_display=amount_display,
                                   payment=payment, payment_content=payment_content)
        try:
            proof_path = _save_proof(proof)
        except ValueError:
            flash("Arquivo inválido -- envie uma imagem ou PDF do comprovante.", "error")
            return render_template("payment_checkout.html", case=case, amount_display=amount_display,
                                   payment=payment, payment_content=payment_content)

        if payment is None:
            payment = Payment(
                user_id=current_user.id,
                package_slug=case.key if case.kind == "package" else None,
                submission_id=int(case.key) if case.kind == "form" else None,
                amount_cents=case.price_cents,
            )
            SessionLocal.add(payment)
        payment.method = method
        payment.proof_path = proof_path
        payment.client_name = client_name
        payment.client_email = client_email
        payment.client_phone = client_phone
        payment.status = "pending"
        SessionLocal.flush()  # precisa do payment.id antes de promover o Lead
        _promote_lead_on_payment_submitted(payment, case)
        SessionLocal.commit()

        send_payment_notification_email(
            payment=payment, client_email=current_user.email,
            case_label=case.label, amount_display=amount_display)

        session["payment_submitted"] = {
            "case_label": case.label, "amount_display": amount_display,
            "whatsapp_url": _whatsapp_url(case.label_en, amount_display),
        }
        return redirect(url_for("payment_gate.submitted"))

    return render_template(
        "payment_checkout.html", case=case, amount_display=amount_display,
        payment=payment, payment_content=payment_content)


def _get_owned_lead(lead_id: int):
    from app.crm_models import Lead
    lead = SessionLocal.get(Lead, lead_id)
    if lead is None or lead.user_id != current_user.id:
        abort(404)
    return lead


def _lead_service_and_tier(lead):
    """Acha o ServiceCatalog e a chave do nível (standard/plus/plus_paper)
    escolhidos por este lead profissional -- ver
    app/packages.py::_get_or_create_professional_lead. `selected_price_cents`
    é o que desambigua Plus online vs. Plus papel (mesmo preço = mesmo
    nível; ver Lead.selected_price_cents em app/crm_models.py)."""
    from app.crm_models import LeadInterestedService, ServiceCatalog

    row = SessionLocal.query(LeadInterestedService).filter_by(lead_id=lead.id).first()
    if row is None:
        return None, None
    service = SessionLocal.get(ServiceCatalog, row.service_id)
    if service is None:
        return None, None

    if lead.selected_price_cents == service.base_price_cents:
        tier = "standard"
    elif lead.selected_price_cents == service.plus_price_paper_cents:
        tier = "plus_paper"
    else:
        tier = "plus"
    return service, tier


@payment_gate_bp.route("/servico/<int:lead_id>", methods=["GET", "POST"])
@login_required
def checkout_lead(lead_id: int):
    """Checkout do pacote profissional (Saes Standard/Plus) -- espelha
    checkout() acima, mas o "caso de pagamento" nasce de um Lead (ver
    app/packages.py::service_confirm) em vez de uma FormSubmission,
    porque estes serviços não têm PDF pro cliente preencher."""
    from app.crm_models import ServiceMode
    from app.services.email_service import send_payment_notification_email
    from app.services.pricing import PaymentCase

    lead = _get_owned_lead(lead_id)
    service, tier = _lead_service_and_tier(lead)
    if service is None or tier is None or lead.selected_price_cents is None:
        abort(404)

    from app.i18n import t
    tier_label = t(f"packages_pro_tier_{tier}")
    tier_label_en = {"standard": "Standard", "plus": "Plus", "plus_paper": "Plus (paper filing)"}[tier]
    case = PaymentCase(
        kind="professional", key=str(lead.id), price_cents=lead.selected_price_cents,
        label=f"{service.name} ({tier_label})", label_en=f"{service.name} ({tier_label_en})",
    )

    payment = _find_payment(case)
    if payment is not None and payment.status == "confirmed":
        flash("Pagamento já confirmado.", "success")
        return redirect(url_for("crm_client.meu_caso"))

    amount_display = f"${case.price_cents / 100:,.2f}"
    payment_content = _payment_methods_content()

    if request.method == "POST":
        method = request.form.get("method")
        proof = request.files.get("proof")
        client_name = request.form.get("client_name", "").strip()
        client_email = request.form.get("client_email", "").strip()
        client_phone = request.form.get("client_phone", "").strip()

        if not client_name or not client_email or not client_phone:
            flash("Preencha nome completo, e-mail e telefone.", "error")
            return render_template("payment_checkout.html", case=case, amount_display=amount_display,
                                   payment=payment, payment_content=payment_content)
        if method not in METHOD_KEYS:
            flash("Selecione uma forma de pagamento.", "error")
            return render_template("payment_checkout.html", case=case, amount_display=amount_display,
                                   payment=payment, payment_content=payment_content)
        if proof is None or not proof.filename:
            flash("Anexe o comprovante de pagamento.", "error")
            return render_template("payment_checkout.html", case=case, amount_display=amount_display,
                                   payment=payment, payment_content=payment_content)
        try:
            proof_path = _save_proof(proof)
        except ValueError:
            flash("Arquivo inválido -- envie uma imagem ou PDF do comprovante.", "error")
            return render_template("payment_checkout.html", case=case, amount_display=amount_display,
                                   payment=payment, payment_content=payment_content)

        if payment is None:
            payment = Payment(user_id=current_user.id, lead_id=lead.id, amount_cents=case.price_cents)
            SessionLocal.add(payment)
        payment.method = method
        payment.proof_path = proof_path
        payment.client_name = client_name
        payment.client_email = client_email
        payment.client_phone = client_phone
        payment.status = "pending"
        SessionLocal.flush()

        if payment.case_id is None:
            service_mode = ServiceMode.saes_standard if tier == "standard" else ServiceMode.saes_plus
            _convert_lead_and_link_payment(
                payment, lead, service_mode=service_mode, case_title=case.label, service_id=service.id)
        SessionLocal.commit()

        send_payment_notification_email(
            payment=payment, client_email=current_user.email,
            case_label=case.label, amount_display=amount_display)

        session["payment_submitted"] = {
            "case_label": case.label, "amount_display": amount_display,
            "whatsapp_url": _whatsapp_url(case.label_en, amount_display),
        }
        return redirect(url_for("payment_gate.submitted"))

    return render_template(
        "payment_checkout.html", case=case, amount_display=amount_display,
        payment=payment, payment_content=payment_content)


@payment_gate_bp.route("/enviado")
@login_required
def submitted():
    """Página de destino depois do envio do comprovante (checkout()/
    checkout_lead() acima) -- pedido do usuário 2026-08-06: fica na
    interface do site/CRM (não sai direto pro WhatsApp) e abre o WhatsApp
    da empresa numa nova aba via JS, com um botão de fallback caso o
    navegador bloqueie o popup. Os dados vêm da sessão (setados pelo POST
    de checkout, lidos uma única vez aqui via .pop) -- um GET direto nesta
    URL sem ter acabado de enviar um comprovante simplesmente volta pro
    painel."""
    data = session.pop("payment_submitted", None)
    if data is None:
        return redirect(url_for("wizard.dashboard"))
    return render_template("payment_submitted.html", **data)
