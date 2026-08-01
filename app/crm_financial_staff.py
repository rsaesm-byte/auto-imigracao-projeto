"""Blueprint do CRM (staff) -- Coaching Financeiro (Fase 2): kanban de
clientes por estágio do funil, tarefas de casa, sessões de coaching e
dashboard de KPIs mensais. Sibling de app/crm_staff_pipeline.py e
app/crm_staff_ops.py (Fase 1) -- mesmo url_prefix, arquivo próprio.
"""
from __future__ import annotations

from datetime import datetime, timezone

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.crm_financial_models import (CoachingSession, FinancialClient,
                                       FinancialClientStatus, FinancialTask,
                                       FinancialTaskCategory, ProgramType,
                                       SessionType, TaskDifficulty,
                                       TaskResponsibleParty)
from app.crm_models import PaymentStatus, Priority, TaskStatus
from app.db import SessionLocal
from app.models import User
from app.services import crm_financial_service as fsvc
from app.services import crm_service as svc

crm_financial_bp = Blueprint("crm_financial", __name__, url_prefix="/staff/crm/financeiro")


@crm_financial_bp.before_request
@login_required
def _require_staff():
    if not current_user.is_staff:
        abort(403)


# --------------------------------------------------------------------------
# Kanban de clientes
# --------------------------------------------------------------------------

@crm_financial_bp.route("/")
def clients_kanban():
    rows = SessionLocal.query(FinancialClient).all()
    by_status: dict[FinancialClientStatus, list[FinancialClient]] = {
        status: [] for status in FinancialClientStatus}
    for fc in rows:
        by_status[fc.client_status].append(fc)
    return render_template(
        "crm_financial_kanban.html", by_status=by_status, statuses=list(FinancialClientStatus),
        remaining_balance_cents=fsvc.remaining_balance_cents,
        sessions_remaining=fsvc.sessions_remaining)


@crm_financial_bp.route("/<int:financial_client_id>/status", methods=["POST"])
def client_status_update(financial_client_id: int):
    fc = SessionLocal.get(FinancialClient, financial_client_id)
    if fc is None:
        abort(404)
    new_status = svc.parse_enum(FinancialClientStatus, request.form.get("client_status"))
    if new_status is None:
        flash("Status inválido.", "error")
        return redirect(request.referrer or url_for("crm_financial.clients_kanban"))
    fc.client_status = new_status
    SessionLocal.commit()
    return redirect(request.referrer or url_for("crm_financial.clients_kanban"))


@crm_financial_bp.route("/novo", methods=["GET", "POST"])
def client_new():
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        if not full_name:
            flash("Nome é obrigatório.", "error")
            return redirect(url_for("crm_financial.client_new"))

        fc = FinancialClient(
            full_name=full_name,
            email=request.form.get("email", "").strip() or None,
            phone_number=request.form.get("phone_number", "").strip() or None,
            program_type=svc.parse_enum(ProgramType, request.form.get("program_type")),
            lead_source_id=svc.parse_int(request.form.get("lead_source_id")),
            first_contact_at=svc.today(),
        )
        SessionLocal.add(fc)
        SessionLocal.commit()
        flash("Cliente de coaching cadastrado.", "success")
        return redirect(url_for("crm_financial.client_detail", financial_client_id=fc.id))

    from app.crm_models import LeadSource
    sources = SessionLocal.query(LeadSource).order_by(LeadSource.name).all()
    return render_template(
        "crm_financial_client_new.html", sources=sources, program_types=list(ProgramType))


# --------------------------------------------------------------------------
# Detalhe do cliente -- perfil, sessões, tarefas, pagamento
# --------------------------------------------------------------------------

@crm_financial_bp.route("/<int:financial_client_id>")
def client_detail(financial_client_id: int):
    fc = SessionLocal.get(FinancialClient, financial_client_id)
    if fc is None:
        abort(404)
    users = {u.id: u for u in SessionLocal.query(User).all()}
    categories = SessionLocal.query(FinancialTaskCategory).order_by(FinancialTaskCategory.name).all()
    return render_template(
        "crm_financial_client_detail.html", fc=fc, users=users, categories=categories,
        amount_paid_cents=fsvc.amount_paid_cents(fc),
        remaining_balance_cents=fsvc.remaining_balance_cents(fc),
        payment_status=fsvc.financial_payment_status(fc),
        net_worth_cents=fsvc.net_worth_cents(fc),
        sessions_completed=fsvc.sessions_completed(fc),
        sessions_remaining=fsvc.sessions_remaining(fc),
        completion_pct=fsvc.completion_pct(fc),
        last_session_at=fsvc.last_session_at(fc),
        next_session_at=fsvc.next_session_at(fc),
        pending_tasks=fsvc.pending_financial_tasks(fc),
        homework_completion_pct=fsvc.homework_completion_pct,
        session_types=list(SessionType), staff_users=svc.staff_users())


@crm_financial_bp.route("/<int:financial_client_id>/sessoes/nova", methods=["POST"])
def session_new(financial_client_id: int):
    fc = SessionLocal.get(FinancialClient, financial_client_id)
    if fc is None:
        abort(404)

    next_number = (
        SessionLocal.query(CoachingSession).filter_by(financial_client_id=fc.id).count() + 1)
    raw_date = request.form.get("session_date", "")
    session_date = None
    if raw_date:
        try:
            session_date = datetime.fromisoformat(raw_date).replace(tzinfo=timezone.utc)
        except ValueError:
            session_date = None

    session = CoachingSession(
        financial_client_id=fc.id, session_number=next_number,
        session_type=svc.parse_enum(SessionType, request.form.get("session_type")),
        main_topic=request.form.get("main_topic", "").strip() or None,
        session_date=session_date,
        coach_id=svc.parse_int(request.form.get("coach_id")),
    )
    SessionLocal.add(session)
    SessionLocal.commit()
    flash("Sessão adicionada.", "success")
    return redirect(url_for("crm_financial.client_detail", financial_client_id=fc.id))


@crm_financial_bp.route("/sessoes/<int:session_id>/completar", methods=["POST"])
def session_complete(session_id: int):
    session = SessionLocal.get(CoachingSession, session_id)
    if session is None:
        abort(404)
    session.completed = True
    SessionLocal.commit()
    return redirect(url_for("crm_financial.client_detail", financial_client_id=session.financial_client_id))


@crm_financial_bp.route("/<int:financial_client_id>/tarefas/nova", methods=["POST"])
def task_new(financial_client_id: int):
    fc = SessionLocal.get(FinancialClient, financial_client_id)
    if fc is None:
        abort(404)

    task_name = request.form.get("task_name", "").strip()
    if not task_name:
        flash("Nome da tarefa é obrigatório.", "error")
        return redirect(url_for("crm_financial.client_detail", financial_client_id=fc.id))

    task = FinancialTask(
        financial_client_id=fc.id,
        coaching_session_id=svc.parse_int(request.form.get("coaching_session_id")),
        task_name=task_name,
        category_id=svc.parse_int(request.form.get("category_id")),
        priority=svc.parse_enum(Priority, request.form.get("priority"), default=Priority.medium),
        difficulty=svc.parse_enum(TaskDifficulty, request.form.get("difficulty")),
        responsible_party=svc.parse_enum(
            TaskResponsibleParty, request.form.get("responsible_party"),
            default=TaskResponsibleParty.client),
        due_date=svc.parse_date(request.form.get("due_date")),
    )
    SessionLocal.add(task)
    SessionLocal.commit()
    flash("Tarefa adicionada.", "success")
    return redirect(url_for("crm_financial.client_detail", financial_client_id=fc.id))


@crm_financial_bp.route("/tarefas/<int:task_id>/status", methods=["POST"])
def task_update_status(task_id: int):
    task = SessionLocal.get(FinancialTask, task_id)
    if task is None:
        abort(404)
    new_status = svc.parse_enum(TaskStatus, request.form.get("status"), default=task.status)
    task.status = new_status
    if new_status == TaskStatus.done and task.completed_at is None:
        task.completed_at = svc.today()
    SessionLocal.commit()
    return redirect(request.referrer or url_for(
        "crm_financial.client_detail", financial_client_id=task.financial_client_id))


# --------------------------------------------------------------------------
# KPIs mensais
# --------------------------------------------------------------------------

@crm_financial_bp.route("/kpis")
def kpis():
    today = svc.today()
    mes_raw = request.args.get("mes", "").strip()
    if mes_raw:
        try:
            year, month = (int(part) for part in mes_raw.split("-"))
        except ValueError:
            year, month = today.year, today.month
    else:
        year, month = today.year, today.month

    data = fsvc.monthly_financial_kpis(year, month)
    return render_template("crm_financial_kpis.html", kpis=data, mes=f"{year:04d}-{month:02d}")
