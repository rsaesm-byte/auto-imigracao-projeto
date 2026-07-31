"""Painel interno da equipe (Saes Professional Team) -- pipeline de
aprovação de pagamentos em 4 abas (ver app/templates/staff_base.html):

- Aprovações Pendentes: Payment.status == "pending" -- comprovante
  enviado, aguardando a equipe conferir e aprovar.
- Aprovados: Payment.status == "confirmed" e ainda não finalized_at --
  pagamento aprovado, caso ainda em andamento.
- Finalizados: finalized_at preenchido -- caso encerrado (documentos
  entregues). Aprovados e Finalizados aceitam filtro de período
  (?range=15|30|month|all) via _filter_by_range() abaixo.
- Solicitar Review: finalized_at preenchido e review_requested ainda
  False -- fila de quem falta pedir avaliação (Google/etc).
- Preços: edita os valores de ServiceFee (app/models.py) usados por
  app/services/pricing.py -- reflete na hora em /servicos e /pacotes,
  sem precisar reiniciar o servidor (pedido do usuário, 2026-07-31:
  transparência de preço pro cliente + controle pra equipe).

Além das abas do pipeline, cada colaborador tem um "Perfil" próprio
(/staff/perfil -- foto, cargo, telefones, horário de trabalho, senha),
preenchido só pelo próprio usuário (ver profile()/update_profile()/
change_password() abaixo) -- login por e-mail OU username (ver
app/auth.py::login, app/models.py::User.username).

Só usuários com User.is_staff=True (ligado manualmente no banco, sem
fluxo de auto-cadastro) enxergam este painel; qualquer outro usuário
logado recebe 403. O login com a aba "Saes Professional Team" (ver
app/auth.py::login) já cai direto na aba Pendentes.

Separado do gate mais simples das Cartas Complementares do I-539
(FormSubmission.paid/paid_at, ver app/wizard.py::_cartas_case) -- esse
continua com sua própria lista (toggle_paid), mostrada dentro da aba
Pendentes só enquanto o caso estiver com paid=False."""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

from flask import Blueprint, abort, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required
from werkzeug.security import check_password_hash, generate_password_hash

from app.db import SessionLocal
from app.models import FormSubmission, Payment, User

staff_bp = Blueprint("staff", __name__, url_prefix="/staff")

ROOT = Path(__file__).resolve().parent.parent
PROFILE_PHOTOS_DIR = ROOT / "instance" / "staff_photos"
PROFILE_PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED_PHOTO_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


@staff_bp.before_request
@login_required
def _require_staff():
    if not current_user.is_staff:
        abort(403)


def _case_label(payment: Payment) -> str:
    from app.services.pricing import package_display_name
    from app.wizard import _form_display_name
    if payment.package_slug:
        return package_display_name(payment.package_slug)
    if payment.submission_id:
        sub = SessionLocal.get(FormSubmission, payment.submission_id)
        if sub is not None:
            return _form_display_name(sub.form_slug)
    return "—"


def _case_submissions(payment: Payment) -> list[FormSubmission]:
    """Todas as submissões pertencentes ao caso deste pagamento -- usado só
    para a equipe acessar os PDFs já preenchidos depois de confirmar (ver
    submission_pdf() abaixo). Para pacotes: todas as submissões do usuário
    com o mesmo package_slug. Para formulário avulso: a raiz (payment.
    submission_id) + seus dependentes diretos (I-539A, I-134 etc.) -- um
    nível só, suficiente para os casos hoje existentes."""
    if payment.package_slug:
        return (
            SessionLocal.query(FormSubmission)
            .filter_by(user_id=payment.user_id, package_slug=payment.package_slug)
            .order_by(FormSubmission.id)
            .all()
        )
    if payment.submission_id:
        root = SessionLocal.get(FormSubmission, payment.submission_id)
        if root is None:
            return []
        children = (
            SessionLocal.query(FormSubmission)
            .filter_by(parent_submission_id=root.id)
            .all()
        )
        return [root] + children
    return []


def _to_view_items(payment_rows: list[Payment]) -> list[dict]:
    items = []
    for p in payment_rows:
        client = SessionLocal.get(User, p.user_id)
        items.append({
            "payment": p,
            "client_email": client.email if client is not None else "—",
            "case_label": _case_label(p),
        })
    return items


RANGE_LABELS = {
    "15": "Últimos 15 dias",
    "30": "Últimos 30 dias",
    "month": "Este mês",
    "all": "Todos",
}


def _range_cutoff(range_key: str) -> datetime | None:
    """None significa "sem corte" (aba "Todos"). "month" é o mês
    calendário atual (dia 1 até agora) -- diferente de "30" (30 dias
    corridos para trás), de propósito, conforme pedido do usuário."""
    now = datetime.now(timezone.utc)
    if range_key == "15":
        return now - timedelta(days=15)
    if range_key == "30":
        return now - timedelta(days=30)
    if range_key == "month":
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return None


def _filter_by_range(payment_rows: list[Payment], date_attr: str, range_key: str) -> list[Payment]:
    cutoff = _range_cutoff(range_key)
    if cutoff is None:
        return payment_rows
    out = []
    for p in payment_rows:
        value = getattr(p, date_attr)
        if value is None:
            continue
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        if value >= cutoff:
            out.append(p)
    return out


@staff_bp.route("/")
def dashboard():
    return redirect(url_for("staff.pending"))


@staff_bp.route("/pendentes")
def pending():
    payment_rows = (
        SessionLocal.query(Payment)
        .filter_by(status="pending")
        .order_by(Payment.created_at.desc())
        .all()
    )
    cartas_cases = (
        SessionLocal.query(FormSubmission)
        .filter_by(form_slug="i-539-cartas", paid=False)
        .order_by(FormSubmission.updated_at.desc())
        .all()
    )
    return render_template(
        "staff_pending.html", active_tab="pending",
        payments=_to_view_items(payment_rows), cartas_cases=cartas_cases)


@staff_bp.route("/aprovados")
def approved():
    range_key = request.args.get("range", "all")
    payment_rows = (
        SessionLocal.query(Payment)
        .filter_by(status="confirmed", finalized_at=None)
        .order_by(Payment.confirmed_at.desc())
        .all()
    )
    payment_rows = _filter_by_range(payment_rows, "confirmed_at", range_key)
    return render_template(
        "staff_approved.html", active_tab="approved", range_key=range_key,
        range_labels=RANGE_LABELS, payments=_to_view_items(payment_rows))


@staff_bp.route("/finalizados")
def finalized():
    range_key = request.args.get("range", "all")
    payment_rows = (
        SessionLocal.query(Payment)
        .filter(Payment.finalized_at.is_not(None))
        .order_by(Payment.finalized_at.desc())
        .all()
    )
    payment_rows = _filter_by_range(payment_rows, "finalized_at", range_key)
    return render_template(
        "staff_finalized.html", active_tab="finalized", range_key=range_key,
        range_labels=RANGE_LABELS, payments=_to_view_items(payment_rows))


@staff_bp.route("/solicitar-review")
def review_queue():
    payment_rows = (
        SessionLocal.query(Payment)
        .filter(Payment.finalized_at.is_not(None), Payment.review_requested.is_(False))
        .order_by(Payment.finalized_at.desc())
        .all()
    )
    return render_template(
        "staff_review.html", active_tab="review", payments=_to_view_items(payment_rows))


@staff_bp.route("/pagamento/<int:submission_id>", methods=["POST"])
def toggle_paid(submission_id: int):
    submission = SessionLocal.get(FormSubmission, submission_id)
    if submission is None or submission.form_slug != "i-539-cartas":
        abort(404)
    submission.paid = not submission.paid
    submission.paid_at = datetime.now(timezone.utc) if submission.paid else None
    SessionLocal.commit()
    return redirect(url_for("staff.pending"))


@staff_bp.route("/pagamentos/<int:payment_id>")
def payment_detail(payment_id: int):
    payment = SessionLocal.get(Payment, payment_id)
    if payment is None:
        abort(404)
    client = SessionLocal.get(User, payment.user_id)
    return render_template(
        "staff_payment_detail.html", payment=payment,
        client_email=client.email if client is not None else "—",
        case_label=_case_label(payment), submissions=_case_submissions(payment))


@staff_bp.route("/formulario/<int:submission_id>/respostas")
def submission_answers(submission_id: int):
    """Visualização só-leitura das respostas do questionário -- diferente
    de submission_pdf() abaixo, funciona mesmo pra casos ainda na aba
    Pendentes, já que o cliente não consegue gerar o PDF final antes do
    pagamento ser aprovado (ver app/wizard.py::generate()); é assim que a
    equipe acessa "os formulários preenchidos" pra conferir antes de
    aprovar (pedido do usuário)."""
    from scripts.run_questionnaire import active_questions
    from app.wizard import _display_value, _load_questionnaire, _form_display_name

    submission = SessionLocal.get(FormSubmission, submission_id)
    if submission is None:
        abort(404)
    answers = submission.get_answers()
    qdata = _load_questionnaire(submission.form_slug)
    active = active_questions(qdata["questions"], answers)
    answered = []
    for q in active:
        if q["id"] not in answers:
            continue
        answered.append((q, _display_value(q, answers[q["id"]])))
    return render_template(
        "staff_submission_answers.html", submission=submission,
        form_name=_form_display_name(submission.form_slug), answered=answered)


@staff_bp.route("/pagamentos/<int:payment_id>/confirmar", methods=["POST"])
def confirm_payment(payment_id: int):
    payment = SessionLocal.get(Payment, payment_id)
    if payment is None:
        abort(404)
    payment.status = "confirmed"
    payment.confirmed_at = datetime.now(timezone.utc)
    payment.confirmed_by_user_id = current_user.id
    case_label = _case_label(payment)
    amount_display = f"${payment.amount_cents / 100:,.2f}"
    SessionLocal.commit()

    # Pedido do usuário (2026-07-31): ao aprovar, abrir o WhatsApp DIRETO
    # com o cliente (número que ele mesmo informou no checkout, ver
    # app/payment_gate.py), não o da Saes -- texto pronto que o staff ainda
    # pode editar antes de mandar. Se o pagamento é de antes desta coluna
    # existir (client_phone vazio), não tem pra quem abrir -- só volta pro
    # painel com um aviso.
    if not payment.client_phone:
        flash("Pagamento aprovado, mas este caso não tem telefone do cliente "
              "cadastrado (comprovante enviado antes desse campo existir).", "success")
        return redirect(request.referrer or url_for("staff.pending"))

    digits = re.sub(r"\D", "", payment.client_phone)
    first_name = (payment.client_name or "").split(" ")[0] or "there"
    message = (
        f"Hi {first_name}, this is the Saes Professional Services team. "
        f"We've confirmed your payment for {case_label} ({amount_display}). "
        f"You can now log in to generate and download your document(s). Thank you!"
    )
    return redirect(f"https://wa.me/{digits}?text={quote(message)}")


@staff_bp.route("/pagamentos/<int:payment_id>/finalizar", methods=["POST"])
def finalize_payment(payment_id: int):
    payment = SessionLocal.get(Payment, payment_id)
    if payment is None:
        abort(404)
    if payment.status != "confirmed":
        abort(400)
    payment.finalized_at = datetime.now(timezone.utc)
    SessionLocal.commit()
    flash("Caso marcado como finalizado.", "success")
    return redirect(request.referrer or url_for("staff.approved"))


@staff_bp.route("/pagamentos/<int:payment_id>/solicitar-review", methods=["POST"])
def request_review(payment_id: int):
    """Marca o "X" de review_requested (some da aba Solicitar Review) e
    abre o WhatsApp com o cliente já com uma mensagem pedindo avaliação --
    mesmo padrão de confirm_payment() acima: texto pronto, editável antes
    de enviar."""
    payment = SessionLocal.get(Payment, payment_id)
    if payment is None:
        abort(404)
    payment.review_requested = True
    case_label = _case_label(payment)
    SessionLocal.commit()

    if not payment.client_phone:
        flash("Marcado como solicitado, mas este caso não tem telefone do cliente cadastrado.", "success")
        return redirect(request.referrer or url_for("staff.review_queue"))

    digits = re.sub(r"\D", "", payment.client_phone)
    first_name = (payment.client_name or "").split(" ")[0] or "there"
    message = (
        f"Hi {first_name}, this is the Saes Professional Services team. "
        f"We hope everything went well with your {case_label}! If you have a "
        f"minute, we'd really appreciate a quick Google review: "
        f"https://maps.app.goo.gl/oLs5K41NwUkFyTyU6 . Thank you so much!"
    )
    return redirect(f"https://wa.me/{digits}?text={quote(message)}")


@staff_bp.route("/pagamentos/<int:payment_id>/comprovante")
def payment_proof(payment_id: int):
    payment = SessionLocal.get(Payment, payment_id)
    if payment is None or not payment.proof_path:
        abort(404)
    return send_file(payment.proof_path, as_attachment=True)


@staff_bp.route("/formulario/<int:submission_id>/pdf")
def submission_pdf(submission_id: int):
    """Download do PDF preenchido de qualquer cliente -- sem checagem de
    dono (ao contrário de wizard.download_pdf), só a checagem de is_staff
    já feita em _require_staff() acima. É o único jeito da equipe acessar
    o formulário depois de aprovar o pagamento (requisito do usuário:
    "poderá acessar os formulários preenchidos que foram pagos")."""
    submission = SessionLocal.get(FormSubmission, submission_id)
    if submission is None or not submission.filled_pdf_path:
        abort(404)
    return send_file(submission.filled_pdf_path, as_attachment=True)


@staff_bp.route("/precos")
def prices():
    from app.services.pricing import all_fees, package_display_name
    from app.wizard import _form_display_name

    grouped: dict[str, list[dict]] = {"individual": [], "in_package": [], "package": []}
    for fee in all_fees():
        label = package_display_name(fee.slug) if fee.kind == "package" else _form_display_name(fee.slug)
        grouped[fee.kind].append({"fee": fee, "label": label})
    return render_template("staff_prices.html", active_tab="prices", grouped=grouped)


@staff_bp.route("/precos/<int:fee_id>/atualizar", methods=["POST"])
def update_price(fee_id: int):
    from app.models import ServiceFee

    row = SessionLocal.get(ServiceFee, fee_id)
    if row is None:
        abort(404)
    raw = request.form.get("price_dollars", "").strip()
    if raw == "":
        price_cents = None
    else:
        try:
            price_cents = round(float(raw.replace(",", ".")) * 100)
        except ValueError:
            flash("Valor inválido.", "error")
            return redirect(url_for("staff.prices"))
    row.price_cents = price_cents
    row.updated_by_user_id = current_user.id
    SessionLocal.commit()
    flash("Preço atualizado.", "success")
    return redirect(url_for("staff.prices"))


@staff_bp.route("/perfil")
def profile():
    return render_template("staff_profile.html", active_tab="profile")


@staff_bp.route("/perfil/atualizar", methods=["POST"])
def update_profile():
    """Só o próprio usuário edita o próprio perfil -- current_user, sem
    parâmetro de user_id (pedido do usuário: "estas informações deverão
    ser preenchidas pelo usuário")."""
    user = SessionLocal.get(User, current_user.id)
    user.job_title = request.form.get("job_title", "").strip() or None
    user.personal_phone = request.form.get("personal_phone", "").strip() or None
    user.work_phone = request.form.get("work_phone", "").strip() or None
    user.work_hours = request.form.get("work_hours", "").strip() or None

    photo = request.files.get("photo")
    if photo is not None and photo.filename:
        ext = Path(photo.filename).suffix.lower()
        if ext not in ALLOWED_PHOTO_EXTENSIONS:
            flash("Foto inválida -- envie um PNG, JPG ou WEBP.", "error")
            return redirect(url_for("staff.profile"))
        # Remove qualquer foto antiga com extensão diferente antes de
        # salvar a nova -- senão ficaria lixo acumulado em instance/.
        for old in PROFILE_PHOTOS_DIR.glob(f"{user.id}.*"):
            old.unlink(missing_ok=True)
        dest = PROFILE_PHOTOS_DIR / f"{user.id}{ext}"
        photo.save(dest)
        user.photo_path = str(dest)

    SessionLocal.commit()
    flash("Perfil atualizado.", "success")
    return redirect(url_for("staff.profile"))


@staff_bp.route("/perfil/senha", methods=["POST"])
def change_password():
    user = SessionLocal.get(User, current_user.id)
    current_password = request.form.get("current_password", "")
    new_password = request.form.get("new_password", "")
    new_password_confirm = request.form.get("new_password_confirm", "")

    if not check_password_hash(user.password_hash, current_password):
        flash("Senha atual incorreta.", "error")
        return redirect(url_for("staff.profile"))
    if len(new_password) < 8:
        flash("A nova senha precisa ter pelo menos 8 caracteres.", "error")
        return redirect(url_for("staff.profile"))
    if new_password != new_password_confirm:
        flash("As senhas não coincidem.", "error")
        return redirect(url_for("staff.profile"))

    user.password_hash = generate_password_hash(new_password)
    SessionLocal.commit()
    flash("Senha alterada com sucesso.", "success")
    return redirect(url_for("staff.profile"))


@staff_bp.route("/perfil/foto/<int:user_id>")
def profile_photo(user_id: int):
    """Serve a foto de perfil de qualquer colaborador -- staff-only (ver
    _require_staff() acima), usada tanto na própria página de perfil
    quanto no avatar do cabeçalho (ver app/templates/staff_base.html)."""
    user = SessionLocal.get(User, user_id)
    if user is None or not user.photo_path:
        abort(404)
    return send_file(user.photo_path)
