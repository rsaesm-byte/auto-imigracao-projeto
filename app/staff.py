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

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, send_file, session, url_for
from flask_login import current_user, login_required
from werkzeug.security import check_password_hash, generate_password_hash

from app.db import SessionLocal
from app.models import FormSubmission, Payment, PostPaymentOnboarding, RequiredDocument, User
from app.services import audit_service

staff_bp = Blueprint("staff", __name__, url_prefix="/staff")


@staff_bp.app_context_processor
def _inject_staff_whatsapp_popup():
    # app_context_processor (não route_context_processor) porque o
    # colaborador pode ser mandado de volta pra QUALQUER página do painel
    # (request.referrer, ver confirm_payment() abaixo) -- staff_base.html
    # (usado por toda tela /staff) lê esta variável pra abrir o WhatsApp
    # numa nova aba. .pop() -- é um aviso de uso único, some no próximo
    # request mesmo que essa página específica não seja recarregada.
    return {"staff_open_whatsapp_url": session.pop("staff_open_whatsapp", None)}


ROOT = Path(__file__).resolve().parent.parent
PROFILE_PHOTOS_DIR = ROOT / "instance" / "staff_photos"
PROFILE_PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED_PHOTO_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


@staff_bp.before_request
@login_required
def _require_staff():
    if not current_user.is_staff:
        abort(403)


@staff_bp.context_processor
def _inject_pending_documents_count():
    """Contador usado no badge da aba "Documentos" (ver staff_base.html) --
    é assim que a equipe é "notificada" de novo documento enviado (pedido
    do usuário: "os colaboradores sejam notificados"), sem WhatsApp/e-mail
    automático."""
    count = SessionLocal.query(RequiredDocument).filter_by(status="uploaded").count()
    return {"pending_documents_count": count}


def _case_label(payment: Payment) -> str:
    # lang="en" sempre -- este rótulo só aparece no painel staff (sempre
    # inglês, ver memory/feedback_staff_interface_english.md) ou na
    # mensagem de WhatsApp pro cliente (já em inglês por padrão, ver
    # confirm_payment/request_review abaixo), nunca numa tela do cliente.
    from app.services.pricing import package_display_name
    from app.wizard import _form_display_name
    if payment.package_slug:
        return package_display_name(payment.package_slug, lang="en")
    if payment.submission_id:
        sub = SessionLocal.get(FormSubmission, payment.submission_id)
        if sub is not None:
            return _form_display_name(sub.form_slug, lang="en")
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
    "15": "Last 15 days",
    "30": "Last 30 days",
    "month": "This month",
    "all": "All",
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
    # Landing page pós-login da equipe -- pedido do Prompt Mestre (Fase 3,
    # 2026-08-06): "Dashboard" é a primeira "área principal" listada, e
    # login() (app/auth.py) já redireciona pra este endpoint desde antes
    # dessa reforma. Era um redirect direto pra "Pending Approvals";
    # agora aponta pro dashboard de widgets de verdade.
    return redirect(url_for("crm_dashboard.dashboard"))


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
    """"Completed" (ex-"Finalized") -- pedido do usuário 2026-08-06: não
    é mais sobre Payment.finalized_at (o gate de pagamento antigo, que
    exigia um clique manual à parte em "Mark as finalized"); agora reflete
    direto a ETAPA do Case no pipeline de Cases -- só aparece aqui quando
    o caso já está em Follow Up, Approved ou Denied (as 3 etapas "de
    encerramento" do funil, ver CaseStatus em app/crm_models.py)."""
    from app.crm_models import Case, CaseStatus

    target_statuses = [CaseStatus.follow_up, CaseStatus.approved, CaseStatus.denied]
    cases = (
        SessionLocal.query(Case)
        .filter(Case.case_status.in_(target_statuses))
        .order_by(Case.updated_at.desc())
        .all()
    )
    return render_template("staff_finalized.html", active_tab="finalized", cases=cases)


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
    history = audit_service.get_history("Payment", payment.id)
    history_users = {u.id: u for u in SessionLocal.query(User).all()}
    return render_template(
        "staff_payment_detail.html", payment=payment,
        client_email=client.email if client is not None else "—",
        case_label=_case_label(payment), submissions=_case_submissions(payment),
        history=history, history_users=history_users)


@staff_bp.route("/formulario/<int:submission_id>/respostas")
def submission_answers(submission_id: int):
    """Visualização só-leitura das respostas do questionário -- diferente
    de submission_pdf() abaixo, funciona mesmo pra casos ainda na aba
    Pendentes, já que o cliente não consegue gerar o PDF final antes do
    pagamento ser aprovado (ver app/wizard.py::generate()); é assim que a
    equipe acessa "os formulários preenchidos" pra conferir antes de
    aprovar (pedido do usuário)."""
    from flask import session as flask_session
    from scripts.run_questionnaire import active_questions
    from app.wizard import _display_value, _load_questionnaire, _form_display_name

    submission = SessionLocal.get(FormSubmission, submission_id)
    if submission is None:
        abort(404)
    answers = submission.get_answers()

    # _load_questionnaire/_display_value/_form_display_name are client-facing
    # helpers that follow the browser session's language (see app/i18n.py::
    # get_lang) -- the staff panel is always English (see memory/feedback_
    # staff_interface_english.md), so force it here regardless of whatever
    # language the staff member's own session happens to have, then restore.
    original_lang = flask_session.get("lang")
    flask_session["lang"] = "en"
    try:
        qdata = _load_questionnaire(submission.form_slug)
        active = active_questions(qdata["questions"], answers)
        answered = []
        for q in active:
            if q["id"] not in answers:
                continue
            answered.append((q, _display_value(q, answers[q["id"]])))
        form_name = _form_display_name(submission.form_slug)
    finally:
        if original_lang is None:
            flask_session.pop("lang", None)
        else:
            flask_session["lang"] = original_lang

    return render_template(
        "staff_submission_answers.html", submission=submission,
        form_name=form_name, answered=answered)


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
    audit_service.log_change("Payment", payment.id, "confirmed",
                              description=f"Payment confirmed — {case_label} ({amount_display})",
                              user_id=current_user.id)

    # Garante um Client+Case do CRM pra TODO pagamento confirmado, não só
    # pra quem já veio de um Lead convertido ou já teve um serviço
    # atribuído manualmente -- sem isso, "Meu Caso" (app/crm_client.py)
    # nunca aparece pra um cliente self-service comum. Pedido do usuário,
    # 2026-08-02. Idempotente: só cria quando este pagamento ainda não tem
    # um caso vinculado (payments antigos já linkados, ou de um fluxo que
    # já cria o caso antes, como o Lead, não são tocados aqui).
    if payment.case_id is None:
        from app.services import crm_service as svc
        new_case = svc.get_or_create_case_for_payment(payment, case_title=case_label)
        payment.case_id = new_case.id

    # Abre a etapa de onboarding (endereço nos EUA + checklist de
    # documentos, ver app/onboarding.py) assim que o pagamento é
    # confirmado -- vazia até o staff cadastrar os itens do checklist;
    # idempotente (nunca cria uma segunda linha pro mesmo Payment).
    if SessionLocal.query(PostPaymentOnboarding).filter_by(payment_id=payment.id).first() is None:
        SessionLocal.add(PostPaymentOnboarding(payment_id=payment.id))
    SessionLocal.flush()

    # Se o caso já tem um serviço "Pacote Completo" atribuído (ver
    # app/crm_staff_ops.py::case_service_update), popula o checklist de
    # documentos da Fase 1 automaticamente a partir do template (pedido do
    # usuário, 2026-08-01) -- idempotente, ver
    # crm_service.py::apply_service_procedure_checklist. O flush() acima é
    # necessário: sem ele, a query por status="confirmed" dentro dessa
    # função não veria a mudança feita em memória logo acima (a sessão
    # roda com autoflush=False, ver app/db.py).
    if payment.case_id is not None:
        from app.crm_models import Case
        from app.services import crm_service as svc
        case = SessionLocal.get(Case, payment.case_id)
        if case is not None:
            svc.apply_service_procedure_checklist(case)

    SessionLocal.commit()

    # Pedido do usuário (2026-07-31): ao aprovar, abrir o WhatsApp DIRETO
    # com o cliente (número que ele mesmo informou no checkout, ver
    # app/payment_gate.py), não o da Saes -- texto pronto que o staff ainda
    # pode editar antes de mandar. Se o pagamento é de antes desta coluna
    # existir (client_phone vazio), não tem pra quem abrir -- só volta pro
    # painel com um aviso.
    if not payment.client_phone:
        flash("Payment approved, but this case has no client phone number "
              "on file (proof submitted before this field existed).", "success")
        return redirect(request.referrer or url_for("staff.pending"))

    digits = re.sub(r"\D", "", payment.client_phone)
    first_name = (payment.client_name or "").split(" ")[0] or "there"
    message = (
        f"Hi {first_name}, this is the Saes Professional Services team. "
        f"We've confirmed your payment for {case_label} ({amount_display}). "
        f"You can now log in to generate and download your document(s). Thank you!"
    )
    # Pedido do usuário 2026-08-06: não navegar o colaborador pra fora do
    # painel -- fica em staff.pending/o referrer, e o WhatsApp abre sozinho
    # numa NOVA aba (ver staff_base.html + _inject_staff_whatsapp_popup
    # abaixo), mesmo tratamento dado ao cliente em app/payment_gate.py.
    session["staff_open_whatsapp"] = f"https://wa.me/{digits}?text={quote(message)}"
    flash(f"Payment approved — opening WhatsApp for {payment.client_name or 'the client'} in a new tab.", "success")
    return redirect(request.referrer or url_for("staff.pending"))


@staff_bp.route("/pagamentos/<int:payment_id>/finalizar", methods=["POST"])
def finalize_payment(payment_id: int):
    payment = SessionLocal.get(Payment, payment_id)
    if payment is None:
        abort(404)
    if payment.status != "confirmed":
        abort(400)
    payment.finalized_at = datetime.now(timezone.utc)
    audit_service.log_change("Payment", payment.id, "finalized",
                              description="Case marked as finalized", user_id=current_user.id)
    SessionLocal.commit()
    flash("Case marked as finalized.", "success")
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
    audit_service.log_change("Payment", payment.id, "review_requested",
                              description="Review requested from client", user_id=current_user.id)
    SessionLocal.commit()

    if not payment.client_phone:
        flash("Marked as requested, but this case has no client phone number on file.", "success")
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
    from app.crm_models import ServiceCatalog
    from app.services.pricing import all_fees, package_display_name
    from app.wizard import _form_display_name

    # Staff panel is always English (see memory/feedback_staff_interface_
    # english.md) -- force lang="en" regardless of the staff member's own
    # session language, unlike the public /servicos and /pacotes pages
    # that call these same helpers without a lang override.
    grouped: dict[str, list[dict]] = {"individual": [], "in_package": [], "package": []}
    priced_fees_json = []
    for fee in all_fees():
        label = (package_display_name(fee.slug, lang="en") if fee.kind == "package"
                 else _form_display_name(fee.slug, lang="en"))
        grouped[fee.kind].append({"fee": fee, "label": label})
        if fee.price_cents is not None:
            priced_fees_json.append({"id": fee.id, "label": label, "price_cents": fee.price_cents})

    # "Pacotes Completos" (Saes Standard/Plus full-service packages,
    # app/crm_models.py::ServiceCatalog) -- pedido do usuário 2026-08-02:
    # a mesma última-preço/última-mudança/porcentagem-em-massa que já
    # existia só pra ServiceFee acima passa a cobrir estes 15 também.
    full_packages = (
        SessionLocal.query(ServiceCatalog)
        .filter(ServiceCatalog.slug.is_not(None))
        .order_by(ServiceCatalog.name)
        .all()
    )
    for service in full_packages:
        # Cada tier com preço definido vira sua própria linha no preview
        # da porcentagem em massa -- pedido do usuário 2026-08-02: os
        # contratos reais mostraram que Standard/Plus Online/Plus Paper
        # são 3 valores independentes, não um preço só.
        for tier_label, cents in (
            ("Standard", service.base_price_cents),
            ("Plus (Online)", service.plus_price_cents),
            ("Plus (Paper)", service.plus_price_paper_cents),
        ):
            if cents is not None:
                priced_fees_json.append(
                    {"id": service.id, "label": f"{service.name} — {tier_label}", "price_cents": cents})

    from app.crm_models import AuditLog

    # Feed único combinando ServiceFee + ServiceCatalog -- pedido do
    # usuário 2026-08-06 (histórico de alterações em Prices). Uma tabela
    # com potencialmente dezenas de linhas (individual/in_package/package
    # + 15 pacotes completos) não comporta um botão de histórico por
    # linha sem reescrever _staff_price_table.html; um feed combinado no
    # topo da página cobre o mesmo pedido sem essa reforma.
    history = (
        SessionLocal.query(AuditLog)
        .filter(AuditLog.entity_type.in_(["ServiceFee", "ServiceCatalog"]))
        .order_by(AuditLog.created_at.desc())
        .limit(100)
        .all()
    )
    history_users = {u.id: u for u in SessionLocal.query(User).all()}

    return render_template(
        "staff_prices.html", active_tab="prices", grouped=grouped, priced_fees_json=priced_fees_json,
        full_packages=full_packages, history=history, history_users=history_users)


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
            flash("Invalid amount.", "error")
            return redirect(url_for("staff.prices"))
    old_cents = row.price_cents
    row.price_cents = price_cents
    row.updated_by_user_id = current_user.id
    if old_cents != price_cents:
        audit_service.log_change(
            "ServiceFee", row.id, "field_update", field="price_cents",
            old_value=None if old_cents is None else f"${old_cents / 100:.2f}",
            new_value=None if price_cents is None else f"${price_cents / 100:.2f}",
            user_id=current_user.id)
    SessionLocal.commit()
    flash("Price updated.", "success")
    return redirect(url_for("staff.prices"))


def _parse_dollars_or_none(raw: str) -> tuple[int | None, bool]:
    """Retorna (price_cents, ok) -- ok=False só quando o campo não estava
    vazio E não era um número válido (campo vazio é um None válido, "não
    definido")."""
    raw = raw.strip()
    if raw == "":
        return None, True
    try:
        return round(float(raw.replace(",", ".")) * 100), True
    except ValueError:
        return None, False


@staff_bp.route("/precos/pacote/<int:service_id>/atualizar", methods=["POST"])
def update_package_price(service_id: int):
    """Mesmo padrão de update_price() acima, para um "Pacote Completo"
    (ServiceCatalog) -- pedido do usuário 2026-08-02. Estes 15 serviços
    nunca tiveram uma tela de preço antes (base_price_cents sempre None
    desde o seed, ver app/__init__.py::_seed_saes_procedure_services).
    Três campos independentes (Standard / Plus Online / Plus Paper) --
    os contratos reais mostraram que nem todo serviço tem os 3 (alguns só
    têm Standard, outros têm Plus só quando o processo é feito em papel
    vs. online tem preços diferentes)."""
    from app.crm_models import ServiceCatalog

    row = SessionLocal.get(ServiceCatalog, service_id)
    if row is None or row.slug is None:
        abort(404)

    standard_cents, standard_ok = _parse_dollars_or_none(request.form.get("price_dollars_standard", ""))
    plus_cents, plus_ok = _parse_dollars_or_none(request.form.get("price_dollars_plus", ""))
    plus_paper_cents, plus_paper_ok = _parse_dollars_or_none(request.form.get("price_dollars_plus_paper", ""))
    if not (standard_ok and plus_ok and plus_paper_ok):
        flash("Invalid amount.", "error")
        return redirect(url_for("staff.prices"))

    def _fmt(cents):
        return None if cents is None else f"${cents / 100:.2f}"

    changes = {
        "base_price_cents": (_fmt(row.base_price_cents), _fmt(standard_cents)),
        "plus_price_cents": (_fmt(row.plus_price_cents), _fmt(plus_cents)),
        "plus_price_paper_cents": (_fmt(row.plus_price_paper_cents), _fmt(plus_paper_cents)),
    }
    row.base_price_cents = standard_cents
    row.plus_price_cents = plus_cents
    row.plus_price_paper_cents = plus_paper_cents
    row.updated_by_user_id = current_user.id
    row.updated_at = datetime.now(timezone.utc)
    audit_service.log_field_changes("ServiceCatalog", row.id, changes, user_id=current_user.id)
    SessionLocal.commit()
    flash("Price updated.", "success")
    return redirect(url_for("staff.prices"))


@staff_bp.route("/precos/aplicar-porcentagem", methods=["POST"])
def apply_price_percentage():
    """Bulk price adjustment -- pedido do usuário 2026-08-02: informa uma
    porcentagem (ex. 10 = +10%, -5 = -5%), o staff revisa o preview
    (calculado no JS a partir de `priced_fees_json`) e só quando confirma
    aqui é que todo `ServiceFee` E todo `ServiceCatalog` ("Pacotes
    Completos") com preço definido são recalculados e persistidos de uma
    vez ("aplica em tudo" -- pedido do usuário, estender a mesma lógica
    pros pacotes). Recalcula no servidor (não confia nos valores
    computados no preview do cliente) -- a porcentagem em si é o único
    dado que atravessa a rede."""
    from app.crm_models import ServiceCatalog
    from app.models import ServiceFee

    raw = request.form.get("percentage", "").strip()
    try:
        percentage = float(raw.replace(",", "."))
    except ValueError:
        flash("Invalid percentage.", "error")
        return redirect(url_for("staff.prices"))

    fee_rows = SessionLocal.query(ServiceFee).filter(ServiceFee.price_cents.is_not(None)).all()
    for row in fee_rows:
        old_cents = row.price_cents
        row.price_cents = round(row.price_cents * (1 + percentage / 100))
        row.updated_by_user_id = current_user.id
        audit_service.log_change(
            "ServiceFee", row.id, "field_update", field="price_cents",
            old_value=f"${old_cents / 100:.2f}", new_value=f"${row.price_cents / 100:.2f}",
            description=f"Bulk {percentage:+.1f}% price adjustment", user_id=current_user.id)

    package_rows = SessionLocal.query(ServiceCatalog).filter(
        ServiceCatalog.base_price_cents.is_not(None) | ServiceCatalog.plus_price_cents.is_not(None)
        | ServiceCatalog.plus_price_paper_cents.is_not(None)
    ).all()
    package_tiers_touched = 0
    for row in package_rows:
        tier_changes = {}
        if row.base_price_cents is not None:
            old = row.base_price_cents
            row.base_price_cents = round(row.base_price_cents * (1 + percentage / 100))
            tier_changes["base_price_cents"] = (f"${old / 100:.2f}", f"${row.base_price_cents / 100:.2f}")
            package_tiers_touched += 1
        if row.plus_price_cents is not None:
            old = row.plus_price_cents
            row.plus_price_cents = round(row.plus_price_cents * (1 + percentage / 100))
            tier_changes["plus_price_cents"] = (f"${old / 100:.2f}", f"${row.plus_price_cents / 100:.2f}")
            package_tiers_touched += 1
        if row.plus_price_paper_cents is not None:
            old = row.plus_price_paper_cents
            row.plus_price_paper_cents = round(row.plus_price_paper_cents * (1 + percentage / 100))
            tier_changes["plus_price_paper_cents"] = (f"${old / 100:.2f}", f"${row.plus_price_paper_cents / 100:.2f}")
            package_tiers_touched += 1
        row.updated_by_user_id = current_user.id
        row.updated_at = datetime.now(timezone.utc)
        for field, (old_v, new_v) in tier_changes.items():
            audit_service.log_change(
                "ServiceCatalog", row.id, "field_update", field=field, old_value=old_v, new_value=new_v,
                description=f"Bulk {percentage:+.1f}% price adjustment", user_id=current_user.id)

    SessionLocal.commit()
    total = len(fee_rows) + package_tiers_touched
    flash(f"Applied {percentage:+.1f}% to {total} price(s).", "success")
    return redirect(url_for("staff.prices"))


@staff_bp.route("/documentos")
def documents_list():
    """Um card por caso com onboarding pós-pagamento aberto (ver
    app/onboarding.py, criado automaticamente em confirm_payment() acima)
    -- ordenado pelos que têm documento aguardando revisão primeiro, pra
    equipe bater o olho e já ver o que precisa de atenção."""
    onboardings = SessionLocal.query(PostPaymentOnboarding).all()
    items = []
    for o in onboardings:
        payment = SessionLocal.get(Payment, o.payment_id)
        client = SessionLocal.get(User, payment.user_id) if payment is not None else None
        items.append({
            "onboarding": o,
            "payment": payment,
            "client_email": client.email if client is not None else "—",
            "case_label": _case_label(payment) if payment is not None else "—",
            "pending_review": sum(1 for d in o.documents if d.status == "uploaded"),
            "total_docs": len(o.documents),
        })
    items.sort(key=lambda item: item["pending_review"], reverse=True)
    return render_template("staff_documents.html", active_tab="documents", items=items)


@staff_bp.route("/documentos/<int:payment_id>")
def document_case_detail(payment_id: int):
    payment = SessionLocal.get(Payment, payment_id)
    if payment is None:
        abort(404)
    onboarding = SessionLocal.query(PostPaymentOnboarding).filter_by(payment_id=payment.id).first()
    if onboarding is None:
        abort(404)
    client = SessionLocal.get(User, payment.user_id)
    return render_template(
        "staff_document_case_detail.html", active_tab="documents", payment=payment,
        onboarding=onboarding, client_email=client.email if client is not None else "—",
        case_label=_case_label(payment))


@staff_bp.route("/documentos/<int:payment_id>/adicionar", methods=["POST"])
def document_item_new(payment_id: int):
    payment = SessionLocal.get(Payment, payment_id)
    if payment is None:
        abort(404)
    onboarding = SessionLocal.query(PostPaymentOnboarding).filter_by(payment_id=payment.id).first()
    if onboarding is None:
        abort(404)
    label = request.form.get("label", "").strip()
    if not label:
        flash("Enter the document name.", "error")
        return redirect(url_for("staff.document_case_detail", payment_id=payment.id))
    SessionLocal.add(RequiredDocument(onboarding_id=onboarding.id, label=label))
    SessionLocal.commit()
    flash("Document added to the checklist.", "success")
    return redirect(url_for("staff.document_case_detail", payment_id=payment.id))


@staff_bp.route("/documentos/item/<int:document_id>/arquivo")
def document_item_file(document_id: int):
    document = SessionLocal.get(RequiredDocument, document_id)
    if document is None or not document.file_path:
        abort(404)
    return send_file(document.file_path, as_attachment=True)


@staff_bp.route("/documentos/item/<int:document_id>/revisar", methods=["POST"])
def document_item_review(document_id: int):
    document = SessionLocal.get(RequiredDocument, document_id)
    if document is None:
        abort(404)
    action = request.form.get("action")
    if action not in ("approve", "reject"):
        abort(400)
    onboarding = SessionLocal.get(PostPaymentOnboarding, document.onboarding_id)
    document.status = "approved" if action == "approve" else "rejected"
    document.staff_notes = request.form.get("staff_notes", "").strip() or None
    document.reviewed_by_id = current_user.id
    document.reviewed_at = datetime.now(timezone.utc)
    SessionLocal.commit()
    flash("Document approved." if action == "approve" else "Document rejected.", "success")
    return redirect(url_for("staff.document_case_detail", payment_id=onboarding.payment_id))


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
            flash("Invalid photo -- upload a PNG, JPG, or WEBP.", "error")
            return redirect(url_for("staff.profile"))
        # Remove qualquer foto antiga com extensão diferente antes de
        # salvar a nova -- senão ficaria lixo acumulado em instance/.
        for old in PROFILE_PHOTOS_DIR.glob(f"{user.id}.*"):
            old.unlink(missing_ok=True)
        dest = PROFILE_PHOTOS_DIR / f"{user.id}{ext}"
        photo.save(dest)
        user.photo_path = str(dest)

    SessionLocal.commit()
    flash("Profile updated.", "success")
    return redirect(url_for("staff.profile"))


@staff_bp.route("/perfil/senha", methods=["POST"])
def change_password():
    user = SessionLocal.get(User, current_user.id)
    current_password = request.form.get("current_password", "")
    new_password = request.form.get("new_password", "")
    new_password_confirm = request.form.get("new_password_confirm", "")

    if not check_password_hash(user.password_hash, current_password):
        flash("Incorrect current password.", "error")
        return redirect(url_for("staff.profile"))
    if len(new_password) < 8:
        flash("The new password must be at least 8 characters long.", "error")
        return redirect(url_for("staff.profile"))
    if new_password != new_password_confirm:
        flash("Passwords don't match.", "error")
        return redirect(url_for("staff.profile"))

    user.password_hash = generate_password_hash(new_password)
    SessionLocal.commit()
    flash("Password changed successfully.", "success")
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


@staff_bp.route("/nav/salvar", methods=["POST"])
def nav_save():
    """"Edit navigation" mode (staff_base.html) posts the whole new layout
    here as JSON (fetch, not a plain form -- the payload is a nested list
    of slots, not flat form fields) whenever the collaborator drags a tab
    to reorder it or drops one tab onto another to group them.
    `scope` ("personal", default, or "global") decides whether this only
    affects the poster's own nav or becomes the org-wide default for
    every collaborator without their own override -- user request
    2026-08-02 ("Salvar para todos colaboradores ou Salvar apenas para
    mim")."""
    from app.staff_nav import save_layout

    payload = request.get_json(silent=True)
    scope = payload.get("scope") if payload else None
    scope = scope if scope in ("personal", "global") else "personal"
    if payload is None or not save_layout(current_user.id, payload.get("layout"), scope=scope):
        return jsonify({"ok": False, "error": "Invalid layout."}), 400
    SessionLocal.commit()
    return jsonify({"ok": True})


@staff_bp.route("/nav/resetar", methods=["POST"])
def nav_reset():
    """Reverts this collaborator's nav back to the default order/no groups
    -- just deletes their StaffNavLayout row, same convention as "no row"
    meaning "use the default" everywhere else in app/staff_nav.py."""
    from app.staff_nav import reset_layout

    reset_layout(current_user.id)
    SessionLocal.commit()
    flash("Navigation reset to default.", "success")
    return redirect(request.referrer or url_for("staff.pending"))
