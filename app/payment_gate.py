"""Blueprint do gate de pagamento genérico (formulários avulsos e pacotes
vendidos pela Saes, conforme data/service_fees.json) -- não confundir com
o gate específico das Cartas Complementares do I-539 (FormSubmission.paid,
ver app/staff.py). Fluxo: cliente termina de preencher -> escolhe forma de
pagamento (Zelle/Venmo/Credit Card/Wire Transfer) -> anexa comprovante ->
sai um e-mail de notificação para a equipe (hoje só logado, ver
app/services/email_service.py) -> cliente é redirecionado pro WhatsApp da
empresa com uma mensagem pronta em inglês. app/wizard.py::generate()/
review() bloqueiam a geração do PDF enquanto o Payment não estiver
status=confirmed (marcado manualmente por um staff em /staff)."""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from flask import (Blueprint, abort, flash, redirect, render_template,
                    request, url_for)
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
        SessionLocal.commit()

        send_payment_notification_email(
            payment=payment, client_email=current_user.email,
            case_label=case.label, amount_display=amount_display)

        return redirect(_whatsapp_url(case.label_en, amount_display))

    return render_template(
        "payment_checkout.html", case=case, amount_display=amount_display,
        payment=payment, payment_content=payment_content)
