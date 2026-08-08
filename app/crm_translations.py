"""Blueprint do CRM (staff) -- aba "Translations": diretório de tradutores
(ficha própria por tradutor -- não é `User`/staff -- com histórico de
pagamentos) e as traduções em si, vistas por período (este mês, últimos
30 dias, mês anterior, todas por mês/ano). Irmã de app/crm_staff_ops.py
(Documentos/Pagamentos/Comunicações/Tarefas) -- blueprint próprio porque é
um domínio auto-contido (tradutores não existem em nenhum outro lugar do
CRM). Pedido do usuário, 2026-08-02.
"""
from __future__ import annotations

from datetime import date

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.crm_models import Case, Client, Currency, Document, DocumentStatus, DocumentTranslation, Translator
from app.db import SessionLocal
from app.models import User
from app.services import audit_service
from app.services import crm_service as svc
from app.services import pipeline_stage_service
from app.staff_permissions import require_area

crm_translations_bp = Blueprint("crm_translations", __name__, url_prefix="/staff/crm/traducoes")


@crm_translations_bp.before_request
@login_required
def _require_staff():
    if not current_user.is_staff:
        abort(403)
    require_area("crm")


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


@crm_translations_bp.route("/kanban")
def kanban():
    """Board Kanban dos documentos em fluxo de tradução -- reusa
    DocumentStatus (já unificado pra cobrir todo o funil de tradução, ver
    app/crm_models.py::DocumentStatus) e a mesma infra de drag-and-drop
    dos outros 3 kanbans (app/static/kanban-dnd.js), soltando num
    reaproveitamento de crm_ops.document_status_update em vez de uma rota
    nova. Só documentos com `translation_language` preenchido -- um
    documento comum (sem tradução) não pertence a este board."""
    # Ordenação dentro de cada coluna (Prompt Mestre, Fase 4, 2026-08-06) --
    # não existia nenhuma antes; deadline de entrega mais próximo primeiro
    # (documentos sem tradução cotada ainda, sem deadline, ficam por último).
    rows = (
        SessionLocal.query(Document)
        .filter(Document.translation_language.isnot(None))
        .all()
    )
    rows.sort(key=lambda d: (d.translation.deadline if d.translation and d.translation.deadline else date.max))
    by_status: dict[DocumentStatus, list[Document]] = {status: [] for status in DocumentStatus}
    for doc in rows:
        by_status[doc.status].append(doc)
    totals = {
        d.id: svc.translation_client_total_cents(d.translation)
        for d in rows if d.translation is not None
    }

    # Alternância Kanban/Tabela/Lista/Calendário (Prompt Mestre, Fase 4,
    # 2026-08-06) -- calendário usa o deadline de entrega da tradução.
    view = request.args.get("view", "kanban")
    if view not in ("kanban", "table", "list", "calendar"):
        view = "kanban"
    stage_labels = pipeline_stage_service.stage_labels("document_status")
    columns = [
        {"label": "Document", "value": lambda d: d.name,
         "url": lambda d: url_for("crm_ops.case_documents", case_id=d.case_id)},
        {"label": "Client", "value": lambda d: d.client.full_name},
        {"label": "Status", "value": lambda d: stage_labels.get(d.status.value, d.status.value.replace('_', ' ').title())},
        {"label": "Translator", "value": lambda d: (d.translation.translator.full_name if d.translation and d.translation.translator else "—")},
        {"label": "Deadline", "value": lambda d: (d.translation.deadline.strftime("%m/%d/%Y") if d.translation and d.translation.deadline else "—")},
        {"label": "Total", "value": lambda d: (f"${totals[d.id] / 100:,.2f}" if totals.get(d.id) is not None else "—")},
    ]
    calendar_grid = None
    if view == "calendar":
        from app.services.calendar_view import build_calendar_grid
        today = svc.today()
        year = svc.parse_int(request.args.get("year")) or today.year
        month = svc.parse_int(request.args.get("month")) or today.month
        calendar_grid = build_calendar_grid(
            rows, lambda d: (d.translation.deadline if d.translation else None), year, month)

    return render_template(
        "crm_translations_kanban.html", by_status=by_status,
        statuses=pipeline_stage_service.ordered_members("document_status"),
        stage_colors=pipeline_stage_service.stage_colors("document_status"),
        stage_labels=stage_labels,
        totals=totals, view=view, columns=columns, calendar_grid=calendar_grid, all_rows=rows)


@crm_translations_bp.route("/nova")
def find_case():
    """"Como eu adiciono uma tradução?" (pedido do usuário 2026-08-06) --
    uma tradução sempre começa num Document de um Case específico (ver
    document_translation_save em app/crm_staff_ops.py), então esta tela
    não cria nada sozinha: só ajuda a achar/escolher o Case certo e manda
    pra tela de Documentos dele, onde "Add document" já tem o seletor de
    idioma de tradução logo no topo -- sem isso, o único jeito de chegar
    lá era já saber navegar Clientes → cliente → Case → Documentos."""
    q = request.args.get("q", "").strip()
    cases = []
    if q:
        like = f"%{q}%"
        cases = (
            SessionLocal.query(Case)
            .join(Client, Case.client_id == Client.id)
            .filter(Client.full_name.ilike(like))
            .order_by(Client.full_name)
            .limit(30)
            .all()
        )
    return render_template("crm_translations_find_case.html", q=q, cases=cases)


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
    SessionLocal.flush()
    audit_service.log_change("Translator", translator.id, "create",
                              description=f"Translator '{full_name}' added", user_id=current_user.id)
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
    history = audit_service.get_history("Translator", translator.id)
    history_users = {u.id: u for u in SessionLocal.query(User).all()}
    return render_template(
        "crm_translator_detail.html", translator=translator, jobs=jobs, currencies=list(Currency),
        client_total_cents=svc.translation_client_total_cents,
        payout_usd_cents=svc.translation_payout_usd_cents,
        payout_translator_currency_cents=svc.translation_payout_translator_currency_cents,
        history=history, history_users=history_users)


TRANSLATOR_TRACKED_FIELDS = ["full_name", "address", "phone", "languages",
                             "payment_method", "bank_details", "currency"]


@crm_translations_bp.route("/tradutor/<int:translator_id>/salvar", methods=["POST"])
def translator_save(translator_id: int):
    translator = SessionLocal.get(Translator, translator_id)
    if translator is None:
        abort(404)
    before = {f: getattr(translator, f) for f in TRANSLATOR_TRACKED_FIELDS}

    translator.full_name = request.form.get("full_name", "").strip() or translator.full_name
    translator.address = request.form.get("address", "").strip() or None
    translator.phone = request.form.get("phone", "").strip() or None
    translator.languages = request.form.get("languages", "").strip() or None
    translator.payment_method = request.form.get("payment_method", "").strip() or None
    translator.bank_details = request.form.get("bank_details", "").strip() or None
    translator.currency = svc.parse_enum(Currency, request.form.get("currency"), default=translator.currency)

    changes = {f: (before[f], getattr(translator, f)) for f in TRANSLATOR_TRACKED_FIELDS}
    audit_service.log_field_changes("Translator", translator.id, changes, user_id=current_user.id)

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
    audit_service.log_change(
        "Translator", translator.id, "payment",
        description=f"Payment registered: ${amount_cents / 100:.2f}", user_id=current_user.id)
    SessionLocal.commit()
    flash("Payment registered.", "success")
    return redirect(url_for("crm_translations.translator_detail", translator_id=translator_id))
