"""Etapa de onboarding pós-pagamento: endereço completo nos EUA (com
complemento), e-mail do titular e dos dependentes, e upload de documentos
de apoio -- liberada automaticamente assim que um staff confirma o
pagamento (ver app/staff.py::confirm_payment,
app/models.py::PostPaymentOnboarding).

Client-facing, separado de app/staff.py (revisão dos documentos, aba
"Documentos") e de app/payment_gate.py (o checkout em si, etapa anterior).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import (Blueprint, abort, flash, redirect, render_template,
                    request, send_file, url_for)
from flask_login import current_user, login_required

from app.db import SessionLocal
from app.models import OnboardingDependent, Payment, PostPaymentOnboarding, RequiredDocument
from scripts.run_questionnaire import US_STATES

onboarding_bp = Blueprint("onboarding", __name__, url_prefix="/pendencias")

ROOT = Path(__file__).resolve().parent.parent
DOCUMENTS_DIR = ROOT / "instance" / "onboarding_documents"
DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED_DOCUMENT_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".heic"}

MAX_DEPENDENTS = 6


def _case_label(payment: Payment) -> str:
    """Versão própria e mínima de app/staff.py::_case_label -- duplicada de
    propósito (mesmo padrão já usado no CRM) pra este blueprint não
    depender de um módulo staff-only."""
    from app.services.pricing import package_display_name
    from app.wizard import _form_display_name
    if payment.package_slug:
        return package_display_name(payment.package_slug)
    if payment.submission_id:
        from app.models import FormSubmission
        sub = SessionLocal.get(FormSubmission, payment.submission_id)
        if sub is not None:
            return _form_display_name(sub.form_slug)
    return "—"


def _get_owned_onboarding(payment_id: int) -> tuple[Payment, PostPaymentOnboarding]:
    payment = SessionLocal.get(Payment, payment_id)
    if payment is None or payment.user_id != current_user.id:
        abort(404)
    onboarding = SessionLocal.query(PostPaymentOnboarding).filter_by(payment_id=payment.id).first()
    if onboarding is None:
        # Pagamento existe e é do usuário, mas ainda não foi confirmado
        # (ver confirm_payment -- é o que cria a linha de onboarding).
        abort(404)
    return payment, onboarding


def _sync_onboarding_to_crm(payment: Payment, onboarding: PostPaymentOnboarding,
                             dependents_data: list[dict]) -> None:
    """Grava direto no Client/ClientDependent do CRM o que o cliente acabou
    de preencher aqui -- pedido do usuário (2026-08-01): "isso... irá
    preencher automaticamente no card dele de serviços do pipeline da Saes
    Professional Team". Só roda quando o pagamento já está ligado a um
    Case (nem todo Payment tem -- ver Payment.case_id, app/models.py);
    silenciosamente não faz nada se não tiver, sem quebrar o fluxo de
    onboarding em si (que é o requisito principal desta tela)."""
    if payment.case_id is None:
        return
    from app.crm_models import Case, ClientDependent

    case = SessionLocal.get(Case, payment.case_id)
    if case is None:
        return
    client = case.client
    if onboarding.applicant_full_name:
        client.full_name = onboarding.applicant_full_name
    if onboarding.applicant_email:
        client.email = onboarding.applicant_email
    if onboarding.applicant_us_phone:
        client.us_phone = onboarding.applicant_us_phone
        client.us_phone_has = True
    address_parts = [onboarding.us_address_line1, onboarding.us_address_complement,
                      onboarding.us_city, onboarding.us_state, onboarding.us_zip]
    client.us_address = ", ".join(p for p in address_parts if p)

    SessionLocal.query(ClientDependent).filter_by(client_id=client.id).delete()
    for dep in dependents_data:
        SessionLocal.add(ClientDependent(
            client_id=client.id, full_name=dep["full_name"],
            email=dep["email"], us_phone=dep["us_phone"]))
    client.has_dependents = bool(dependents_data)
    client.n_dependents = len(dependents_data) or None
    SessionLocal.commit()


def _save_document(file_storage) -> str:
    ext = Path(file_storage.filename).suffix.lower()
    if ext not in ALLOWED_DOCUMENT_EXTENSIONS:
        raise ValueError("extensao_invalida")
    dest = DOCUMENTS_DIR / f"{uuid.uuid4().hex}{ext}"
    file_storage.save(dest)
    return str(dest)


@onboarding_bp.route("/<int:payment_id>", methods=["GET", "POST"])
@login_required
def detail(payment_id: int):
    payment, onboarding = _get_owned_onboarding(payment_id)

    if request.method == "POST" and request.form.get("action") == "save_address":
        onboarding.applicant_full_name = request.form.get("applicant_full_name", "").strip() or None
        onboarding.applicant_us_phone = request.form.get("applicant_us_phone", "").strip() or None
        onboarding.us_address_line1 = request.form.get("us_address_line1", "").strip() or None
        onboarding.us_address_complement = request.form.get("us_address_complement", "").strip() or None
        onboarding.us_city = request.form.get("us_city", "").strip() or None
        onboarding.us_state = request.form.get("us_state", "").strip() or None
        onboarding.us_zip = request.form.get("us_zip", "").strip() or None
        onboarding.applicant_email = request.form.get("applicant_email", "").strip() or None
        onboarding.address_confirmed = True

        SessionLocal.query(OnboardingDependent).filter_by(onboarding_id=onboarding.id).delete()
        dependents_data: list[dict] = []
        for i in range(1, MAX_DEPENDENTS + 1):
            name = request.form.get(f"dependent_{i}_name", "").strip()
            email = request.form.get(f"dependent_{i}_email", "").strip()
            phone = request.form.get(f"dependent_{i}_phone", "").strip()
            if name:
                SessionLocal.add(OnboardingDependent(
                    onboarding_id=onboarding.id, full_name=name,
                    email=email or None, us_phone=phone or None))
                dependents_data.append({"full_name": name, "email": email or None, "us_phone": phone or None})

        SessionLocal.commit()
        _sync_onboarding_to_crm(payment, onboarding, dependents_data)
        from app.i18n import t
        flash(t("onboarding_flash_address_saved"), "success")
        return redirect(url_for("onboarding.detail", payment_id=payment.id))

    dependents_by_slot = list(onboarding.dependents) + [None] * MAX_DEPENDENTS

    from app.i18n import get_lang
    from app.services.service_procedures import translate_document_label
    lang = get_lang()

    return render_template(
        "onboarding_detail.html", payment=payment, onboarding=onboarding,
        case_label=_case_label(payment), dependent_range=range(1, MAX_DEPENDENTS + 1),
        dependents_by_slot=dependents_by_slot, us_states=US_STATES,
        translate_label=lambda label: translate_document_label(label, lang))


@onboarding_bp.route("/documentos/<int:document_id>/upload", methods=["POST"])
@login_required
def upload_document(document_id: int):
    document = SessionLocal.get(RequiredDocument, document_id)
    if document is None:
        abort(404)
    onboarding = SessionLocal.get(PostPaymentOnboarding, document.onboarding_id)
    payment = SessionLocal.get(Payment, onboarding.payment_id)
    if payment is None or payment.user_id != current_user.id:
        abort(404)

    from app.i18n import t

    file_storage = request.files.get("file")
    if file_storage is None or not file_storage.filename:
        flash(t("onboarding_flash_no_file"), "error")
        return redirect(url_for("onboarding.detail", payment_id=payment.id))

    try:
        document.file_path = _save_document(file_storage)
    except ValueError:
        flash(t("onboarding_flash_bad_ext"), "error")
        return redirect(url_for("onboarding.detail", payment_id=payment.id))

    document.status = "uploaded"
    document.uploaded_at = datetime.now(timezone.utc)
    # Uma nova tentativa depois de reprovado limpa a observação antiga --
    # ela era sobre o arquivo anterior, não sobre este.
    document.staff_notes = None
    document.reviewed_by_id = None
    document.reviewed_at = None
    SessionLocal.commit()
    flash(t("onboarding_flash_uploaded"), "success")
    return redirect(url_for("onboarding.detail", payment_id=payment.id))


@onboarding_bp.route("/documentos/<int:document_id>/arquivo")
@login_required
def document_file(document_id: int):
    """O próprio cliente pode reabrir o arquivo que ele mesmo enviou (pra
    conferir antes/depois de reprovado) -- nunca de outro usuário."""
    document = SessionLocal.get(RequiredDocument, document_id)
    if document is None or not document.file_path:
        abort(404)
    onboarding = SessionLocal.get(PostPaymentOnboarding, document.onboarding_id)
    payment = SessionLocal.get(Payment, onboarding.payment_id)
    if payment is None or payment.user_id != current_user.id:
        abort(404)
    return send_file(document.file_path)
