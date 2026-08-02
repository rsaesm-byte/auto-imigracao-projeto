"""Blueprint do CRM (staff) -- aba "Translations": diretório de tradutores
(ficha própria por tradutor -- não é `User`/staff -- com histórico de
pagamentos) e as traduções em si, vistas por período (este mês, últimos
30 dias, mês anterior, todas por mês/ano). Irmã de app/crm_staff_ops.py
(Documentos/Pagamentos/Comunicações/Tarefas) -- blueprint próprio porque é
um domínio auto-contido (tradutores não existem em nenhum outro lugar do
CRM). Pedido do usuário, 2026-08-02.
"""
from __future__ import annotations

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.crm_models import Currency, DocumentTranslation, Translator
from app.db import SessionLocal
from app.services import crm_service as svc

crm_translations_bp = Blueprint("crm_translations", __name__, url_prefix="/staff/crm/traducoes")


@crm_translations_bp.before_request
@login_required
def _require_staff():
    if not current_user.is_staff:
        abort(403)


def _all_translations() -> list[DocumentTranslation]:
    return SessionLocal.query(DocumentTranslation).all()


@crm_translations_bp.route("/")
def dashboard():
    range_key = request.args.get("range", "this_month")
    all_translations = _all_translations()

    if range_key == "last_30_days":
        rows = svc.translations_last_30_days(all_translations)
    elif range_key == "previous_month":
        rows = svc.translations_previous_month(all_translations)
    elif range_key == "all":
        rows = None  # rendered as grouped_by_year below instead of a flat list
    else:
        range_key = "this_month"
        rows = svc.translations_this_month(all_translations)

    grouped_by_year = svc.group_translations_by_year_month(all_translations) if range_key == "all" else {}

    translators = SessionLocal.query(Translator).order_by(Translator.full_name).all()
    return render_template(
        "crm_translations_dashboard.html", translators=translators, range_key=range_key,
        rows=rows, grouped_by_year=grouped_by_year,
        client_total_cents=svc.translation_client_total_cents,
        payout_usd_cents=svc.translation_payout_usd_cents,
        payout_translator_currency_cents=svc.translation_payout_translator_currency_cents)


@crm_translations_bp.route("/tradutor/novo", methods=["POST"])
def translator_new():
    full_name = request.form.get("full_name", "").strip()
    if not full_name:
        flash("Name is required.", "error")
        return redirect(url_for("crm_translations.dashboard"))
    if SessionLocal.query(Translator).filter_by(full_name=full_name).first() is not None:
        flash("A translator with that name already exists.", "error")
        return redirect(url_for("crm_translations.dashboard"))

    translator = Translator(full_name=full_name)
    SessionLocal.add(translator)
    SessionLocal.commit()
    flash(f"{full_name} added.", "success")
    return redirect(url_for("crm_translations.translator_detail", translator_id=translator.id))


@crm_translations_bp.route("/tradutor/<int:translator_id>")
def translator_detail(translator_id: int):
    translator = SessionLocal.get(Translator, translator_id)
    if translator is None:
        abort(404)
    jobs = sorted(
        translator.translations, key=lambda t: t.requested_at or svc.today(), reverse=True)
    return render_template(
        "crm_translator_detail.html", translator=translator, jobs=jobs, currencies=list(Currency),
        client_total_cents=svc.translation_client_total_cents,
        payout_usd_cents=svc.translation_payout_usd_cents,
        payout_translator_currency_cents=svc.translation_payout_translator_currency_cents)


@crm_translations_bp.route("/tradutor/<int:translator_id>/salvar", methods=["POST"])
def translator_save(translator_id: int):
    translator = SessionLocal.get(Translator, translator_id)
    if translator is None:
        abort(404)
    translator.full_name = request.form.get("full_name", "").strip() or translator.full_name
    translator.address = request.form.get("address", "").strip() or None
    translator.phone = request.form.get("phone", "").strip() or None
    translator.languages = request.form.get("languages", "").strip() or None
    translator.payment_method = request.form.get("payment_method", "").strip() or None
    translator.bank_details = request.form.get("bank_details", "").strip() or None
    translator.currency = svc.parse_enum(Currency, request.form.get("currency"), default=translator.currency)
    SessionLocal.commit()
    flash("Translator profile updated.", "success")
    return redirect(url_for("crm_translations.translator_detail", translator_id=translator.id))


@crm_translations_bp.route("/tradutor/<int:translator_id>/pagamento", methods=["POST"])
def translator_payment_new(translator_id: int):
    translator = SessionLocal.get(Translator, translator_id)
    if translator is None:
        abort(404)
    amount_cents = svc.parse_dollars_to_cents(request.form.get("amount", ""))
    paid_at = svc.parse_date(request.form.get("paid_at"))
    if amount_cents is None or paid_at is None:
        flash("Amount and payment date are required.", "error")
        return redirect(url_for("crm_translations.translator_detail", translator_id=translator_id))

    svc.register_translator_payment(
        translator, amount_cents=amount_cents,
        currency=svc.parse_enum(Currency, request.form.get("currency"), default=translator.currency),
        paid_at=paid_at, document_translation_id=svc.parse_int(request.form.get("document_translation_id")),
        notes=request.form.get("notes", "").strip() or None)
    SessionLocal.commit()
    flash("Payment registered.", "success")
    return redirect(url_for("crm_translations.translator_detail", translator_id=translator_id))
