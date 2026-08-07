"""Blueprint do CRM (staff) -- Coaching Financeiro (Fase 2): kanban de
clientes por estágio do funil, tarefas de casa, sessões de coaching e
dashboard de KPIs mensais. Sibling de app/crm_staff_pipeline.py e
app/crm_staff_ops.py (Fase 1) -- mesmo url_prefix, arquivo próprio.
"""
from __future__ import annotations

from datetime import datetime, timezone

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.crm_financial_models import (ClientComplianceLevel, CoachingSession,
                                       ContinuityProgram, EmergencyFundStatus,
                                       FinancialChallenge, FinancialClient,
                                       FinancialClientChallenge,
                                       FinancialClientGoal,
                                       FinancialClientIncomeSource,
                                       FinancialClientMeetingPlatform,
                                       FinancialClientStatus, FinancialGoal,
                                       FinancialProgressStatus, FinancialTask,
                                       FinancialTaskCategory, FocusArea,
                                       HomeworkAdherenceLevel,
                                       HouseholdIncomeRange, MeetingPlatform,
                                       NinetyDayReviewStatus, ProgramType,
                                       SessionType, TaskDifficulty,
                                       TaskResponsibleParty)
from app.crm_models import (AuditSource, IncomeSourceType, MaritalStatus,
                             PreferredLanguage, PaymentStatus, Priority,
                             TaskStatus)
from app.db import SessionLocal
from app.models import User
from app.services import audit_service
from app.services import crm_financial_service as fsvc
from app.services import crm_service as svc
from app.services import financial_planning_service as fp_svc
from app.services import pipeline_stage_service

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
    # Ordenação dentro de cada coluna (Prompt Mestre, Fase 4, 2026-08-06) --
    # não existia nenhuma antes; sem created_at neste model, o id (ordem de
    # criação) é o proxy mais recente primeiro.
    rows = SessionLocal.query(FinancialClient).order_by(FinancialClient.id.desc()).all()
    by_status: dict[FinancialClientStatus, list[FinancialClient]] = {
        status: [] for status in FinancialClientStatus}
    for fc in rows:
        by_status[fc.client_status].append(fc)

    # Alternância Kanban/Tabela/Lista/Calendário (Prompt Mestre, Fase 4,
    # 2026-08-06) -- calendário usa enrollment_at (data de inscrição no
    # programa, o campo de data mais estável deste model).
    view = request.args.get("view", "kanban")
    if view not in ("kanban", "table", "list", "calendar"):
        view = "kanban"
    stage_labels = pipeline_stage_service.stage_labels("financial_client_status")

    def _balance_display(fc):
        cents = fsvc.remaining_balance_cents(fc)
        return f"${cents / 100:,.2f}" if cents is not None else "—"

    columns = [
        {"label": "Name", "value": lambda fc: fc.full_name,
         "url": lambda fc: url_for("crm_financial.client_detail", financial_client_id=fc.id)},
        {"label": "Status", "value": lambda fc: stage_labels.get(fc.client_status.value, fc.client_status.value.replace('_', ' ').title())},
        {"label": "Program", "value": lambda fc: (fc.program_type.value.replace('_', ' ').title() if fc.program_type else "—")},
        {"label": "Balance", "value": _balance_display},
        {"label": "Enrolled", "value": lambda fc: (fc.enrollment_at.strftime("%m/%d/%Y") if fc.enrollment_at else "—")},
    ]
    calendar_grid = None
    if view == "calendar":
        from app.services.calendar_view import build_calendar_grid
        today = svc.today()
        year = svc.parse_int(request.args.get("year")) or today.year
        month = svc.parse_int(request.args.get("month")) or today.month
        calendar_grid = build_calendar_grid(rows, lambda fc: fc.enrollment_at, year, month)

    return render_template(
        "crm_financial_kanban.html", by_status=by_status,
        statuses=pipeline_stage_service.ordered_members("financial_client_status"),
        remaining_balance_cents=fsvc.remaining_balance_cents,
        sessions_remaining=fsvc.sessions_remaining,
        stage_colors=pipeline_stage_service.stage_colors("financial_client_status"),
        stage_labels=stage_labels,
        view=view, columns=columns, calendar_grid=calendar_grid, all_rows=rows)


@crm_financial_bp.route("/<int:financial_client_id>/status", methods=["POST"])
def client_status_update(financial_client_id: int):
    fc = SessionLocal.get(FinancialClient, financial_client_id)
    if fc is None:
        abort(404)
    new_status = svc.parse_enum(FinancialClientStatus, request.form.get("client_status"))
    if new_status is None:
        flash("Invalid status.", "error")
        return redirect(request.referrer or url_for("crm_financial.clients_kanban"))
    old_status = fc.client_status
    fc.client_status = new_status
    if old_status != new_status:
        audit_service.log_change(
            "FinancialClient", fc.id, "stage_change", field="client_status",
            old_value=old_status.value, new_value=new_status.value,
            description=f"Moved from {old_status.value} to {new_status.value}",
            user_id=current_user.id, source=AuditSource.manual)
    SessionLocal.commit()
    return redirect(request.referrer or url_for("crm_financial.clients_kanban"))


@crm_financial_bp.route("/novo", methods=["GET", "POST"])
def client_new():
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        if not full_name:
            flash("Name is required.", "error")
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
        SessionLocal.flush()
        audit_service.log_change("FinancialClient", fc.id, "create",
                                  description=f"Coaching client '{full_name}' created", user_id=current_user.id)
        SessionLocal.commit()
        flash("Coaching client created.", "success")
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
    history = audit_service.get_history("FinancialClient", fc.id)
    return render_template(
        "crm_financial_client_detail.html", fc=fc, users=users, categories=categories,
        history=history, history_users=users,
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


@crm_financial_bp.route("/<int:financial_client_id>/financial-planning/habilitar", methods=["POST"])
def financial_planning_enable(financial_client_id: int):
    """Fase 1 do SAES_Financial_Planning_Master_Spec -- liga o acesso ao
    módulo self-service (contas/orçamento/dívidas/metas, Fase 2 em
    diante) pra este cliente de coaching. Exige a permissão
    `financial_planning_manage_access`, não só `is_staff` (já checado
    pelo `before_request` do blueprint) -- é uma ação sensível sobre
    acesso a dado financeiro, igual o documento mestre pede."""
    if not current_user.financial_planning_manage_access:
        abort(403)
    fc = SessionLocal.get(FinancialClient, financial_client_id)
    if fc is None:
        abort(404)
    fp_svc.enable_access(fc, actor=current_user)
    flash("Financial Planning access enabled.", "success")
    return redirect(url_for("crm_financial.client_detail", financial_client_id=financial_client_id))


@crm_financial_bp.route("/<int:financial_client_id>/financial-planning/desabilitar", methods=["POST"])
def financial_planning_disable(financial_client_id: int):
    if not current_user.financial_planning_manage_access:
        abort(403)
    fc = SessionLocal.get(FinancialClient, financial_client_id)
    if fc is None:
        abort(404)
    fp_svc.disable_access(fc, actor=current_user)
    flash("Financial Planning access disabled. No financial data was deleted.", "success")
    return redirect(url_for("crm_financial.client_detail", financial_client_id=financial_client_id))


def _sync_checkbox_set(model, fk_column: str, other_column: str, financial_client_id: int,
                        selected_ids: list[int]) -> None:
    """Substitui o conjunto inteiro de uma relação M2M (ver
    app/crm_financial_models.py -- meeting_platforms/income_sources/goals/
    challenges) pelos ids marcados no formulário: apaga tudo que já
    existia pra este cliente e recria só o que veio marcado. Mais simples
    e sem risco de duplicata do que tentar comparar diff a diff."""
    SessionLocal.query(model).filter_by(**{fk_column: financial_client_id}).delete()
    for value in selected_ids:
        SessionLocal.add(model(**{fk_column: financial_client_id, other_column: value}))


FINANCIAL_CLIENT_TRACKED_FIELDS = [
    "full_name", "email", "phone_number", "dob", "marital_status", "occupation", "employer",
    "preferred_language", "package_value_cents", "total_sessions_purchased", "enrollment_at",
    "diagnostic_at", "target_completion_at", "progress_status", "homework_adherence",
    "client_compliance", "review_90day_status", "continuity_program", "nps_score", "priority_level",
    "current_focus_area", "wins_milestones", "action_plan", "recommended_solutions", "notes",
    "household_income_range", "monthly_household_income_cents", "monthly_expenses_cents",
    "emergency_fund_status", "credit_score", "total_assets_cents", "total_liabilities_cents",
    "cash_banking_cents", "investments_cents", "real_estate_cents", "vehicles_cents",
    "retirement_cents", "business_ownership_value_cents", "credit_card_debt_cents",
]


# `value|replace('_',' ')|title` (usado pra todo enum nesta tela) quebra
# nestes dois -- os valores têm dígito-sublinhado-dígito representando
# uma FAIXA numérica ("from_1_3_months"), não palavras separadas; o
# replace cego vira "From 1 3 Months" (perde o traço da faixa). Rótulo
# explícito só pra estes dois, os demais enums desta tela não têm esse
# problema (nenhum outro combina números com underscore).
HOUSEHOLD_INCOME_RANGE_LABELS = {
    HouseholdIncomeRange.under_3000: "Under $3,000",
    HouseholdIncomeRange.from_3000_5000: "$3,000 – $5,000",
    HouseholdIncomeRange.from_5001_10000: "$5,001 – $10,000",
    HouseholdIncomeRange.from_10001_15000: "$10,001 – $15,000",
    HouseholdIncomeRange.from_15001_20000: "$15,001 – $20,000",
    HouseholdIncomeRange.over_20000: "Over $20,000",
}
EMERGENCY_FUND_STATUS_LABELS = {
    EmergencyFundStatus.none: "None",
    EmergencyFundStatus.less_1_month: "Less than 1 month",
    EmergencyFundStatus.from_1_3_months: "1–3 months",
    EmergencyFundStatus.from_3_6_months: "3–6 months",
    EmergencyFundStatus.from_6_12_months: "6–12 months",
    EmergencyFundStatus.more_12_months: "More than 12 months",
}


@crm_financial_bp.route("/<int:financial_client_id>/perfil", methods=["GET", "POST"])
def client_profile_edit(financial_client_id: int):
    fc = SessionLocal.get(FinancialClient, financial_client_id)
    if fc is None:
        abort(404)

    if request.method == "POST":
        before = {f: getattr(fc, f) for f in FINANCIAL_CLIENT_TRACKED_FIELDS}

        fc.full_name = request.form.get("full_name", "").strip() or fc.full_name
        fc.email = request.form.get("email", "").strip() or None
        fc.phone_number = request.form.get("phone_number", "").strip() or None
        fc.dob = svc.parse_date(request.form.get("dob"))
        fc.marital_status = svc.parse_enum(MaritalStatus, request.form.get("marital_status"))
        fc.occupation = request.form.get("occupation", "").strip() or None
        fc.employer = request.form.get("employer", "").strip() or None
        fc.preferred_language = svc.parse_enum(PreferredLanguage, request.form.get("preferred_language"))

        fc.package_value_cents = svc.parse_dollars_to_cents(request.form.get("package_value_dollars", ""))
        fc.total_sessions_purchased = svc.parse_int(request.form.get("total_sessions_purchased"))
        fc.enrollment_at = svc.parse_date(request.form.get("enrollment_at"))
        fc.diagnostic_at = svc.parse_date(request.form.get("diagnostic_at"))
        fc.target_completion_at = svc.parse_date(request.form.get("target_completion_at"))
        fc.progress_status = svc.parse_enum(
            FinancialProgressStatus, request.form.get("progress_status"),
            default=FinancialProgressStatus.not_started)
        fc.homework_adherence = svc.parse_enum(HomeworkAdherenceLevel, request.form.get("homework_adherence"))
        fc.client_compliance = svc.parse_enum(ClientComplianceLevel, request.form.get("client_compliance"))
        fc.review_90day_status = svc.parse_enum(
            NinetyDayReviewStatus, request.form.get("review_90day_status"),
            default=NinetyDayReviewStatus.not_scheduled)
        fc.continuity_program = svc.parse_enum(
            ContinuityProgram, request.form.get("continuity_program"), default=ContinuityProgram.none)
        fc.nps_score = svc.parse_int(request.form.get("nps_score"))
        fc.priority_level = svc.parse_enum(Priority, request.form.get("priority_level"), default=Priority.medium)
        fc.current_focus_area = svc.parse_enum(FocusArea, request.form.get("current_focus_area"))
        fc.wins_milestones = request.form.get("wins_milestones", "").strip() or None
        fc.action_plan = request.form.get("action_plan", "").strip() or None
        fc.recommended_solutions = request.form.get("recommended_solutions", "").strip() or None
        fc.notes = request.form.get("notes", "").strip() or None

        fc.household_income_range = svc.parse_enum(
            HouseholdIncomeRange, request.form.get("household_income_range"))
        fc.monthly_household_income_cents = svc.parse_dollars_to_cents(
            request.form.get("monthly_household_income_dollars", ""))
        fc.monthly_expenses_cents = svc.parse_dollars_to_cents(request.form.get("monthly_expenses_dollars", ""))
        fc.emergency_fund_status = svc.parse_enum(EmergencyFundStatus, request.form.get("emergency_fund_status"))
        fc.credit_score = svc.parse_int(request.form.get("credit_score"))
        fc.total_assets_cents = svc.parse_dollars_to_cents(request.form.get("total_assets_dollars", ""))
        fc.total_liabilities_cents = svc.parse_dollars_to_cents(request.form.get("total_liabilities_dollars", ""))
        fc.cash_banking_cents = svc.parse_dollars_to_cents(request.form.get("cash_banking_dollars", ""))
        fc.investments_cents = svc.parse_dollars_to_cents(request.form.get("investments_dollars", ""))
        fc.real_estate_cents = svc.parse_dollars_to_cents(request.form.get("real_estate_dollars", ""))
        fc.vehicles_cents = svc.parse_dollars_to_cents(request.form.get("vehicles_dollars", ""))
        fc.retirement_cents = svc.parse_dollars_to_cents(request.form.get("retirement_dollars", ""))
        fc.business_ownership_value_cents = svc.parse_dollars_to_cents(
            request.form.get("business_ownership_value_dollars", ""))
        fc.credit_card_debt_cents = svc.parse_dollars_to_cents(request.form.get("credit_card_debt_dollars", ""))

        platforms = [svc.parse_enum(MeetingPlatform, v) for v in request.form.getlist("meeting_platforms")]
        SessionLocal.query(FinancialClientMeetingPlatform).filter_by(financial_client_id=fc.id).delete()
        for platform in platforms:
            if platform is not None:
                SessionLocal.add(FinancialClientMeetingPlatform(financial_client_id=fc.id, platform=platform))

        income_source_ids = [i for i in (svc.parse_int(v) for v in request.form.getlist("income_sources"))
                              if i is not None]
        _sync_checkbox_set(FinancialClientIncomeSource, "financial_client_id", "income_source_type_id",
                            fc.id, income_source_ids)

        goal_ids = [i for i in (svc.parse_int(v) for v in request.form.getlist("financial_goals"))
                    if i is not None]
        _sync_checkbox_set(FinancialClientGoal, "financial_client_id", "financial_goal_id", fc.id, goal_ids)

        challenge_ids = [i for i in (svc.parse_int(v) for v in request.form.getlist("financial_challenges"))
                          if i is not None]
        _sync_checkbox_set(FinancialClientChallenge, "financial_client_id", "financial_challenge_id",
                            fc.id, challenge_ids)

        changes = {f: (before[f], getattr(fc, f)) for f in FINANCIAL_CLIENT_TRACKED_FIELDS}
        audit_service.log_field_changes("FinancialClient", fc.id, changes, user_id=current_user.id)

        SessionLocal.commit()
        flash("Profile updated.", "success")
        return redirect(url_for("crm_financial.client_detail", financial_client_id=fc.id))

    selected_platforms = {p.platform for p in fc.meeting_platforms}
    selected_income_sources = {s.income_source_type_id for s in fc.income_sources}
    selected_goals = {g.financial_goal_id for g in fc.goals}
    selected_challenges = {c.financial_challenge_id for c in fc.challenges}

    return render_template(
        "crm_financial_client_profile.html", fc=fc,
        marital_statuses=list(MaritalStatus), languages=list(PreferredLanguage),
        progress_statuses=list(FinancialProgressStatus),
        homework_levels=list(HomeworkAdherenceLevel), compliance_levels=list(ClientComplianceLevel),
        review_statuses=list(NinetyDayReviewStatus), continuity_programs=list(ContinuityProgram),
        priorities=list(Priority), focus_areas=list(FocusArea),
        income_ranges=list(HouseholdIncomeRange), emergency_fund_statuses=list(EmergencyFundStatus),
        income_range_labels=HOUSEHOLD_INCOME_RANGE_LABELS, emergency_fund_labels=EMERGENCY_FUND_STATUS_LABELS,
        meeting_platforms=list(MeetingPlatform), selected_platforms=selected_platforms,
        income_source_types=(
            SessionLocal.query(IncomeSourceType).filter(IncomeSourceType.deleted_at.is_(None))
            .order_by(IncomeSourceType.sort_order, IncomeSourceType.name).all()),
        selected_income_sources=selected_income_sources,
        financial_goals=(
            SessionLocal.query(FinancialGoal).filter(FinancialGoal.deleted_at.is_(None))
            .order_by(FinancialGoal.sort_order, FinancialGoal.name).all()),
        selected_goals=selected_goals,
        financial_challenges=(
            SessionLocal.query(FinancialChallenge).filter(FinancialChallenge.deleted_at.is_(None))
            .order_by(FinancialChallenge.sort_order, FinancialChallenge.name).all()),
        selected_challenges=selected_challenges)


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
    audit_service.log_change("FinancialClient", fc.id, "create",
                              description=f"Session #{next_number} added", user_id=current_user.id)
    SessionLocal.commit()
    flash("Session added.", "success")
    return redirect(url_for("crm_financial.client_detail", financial_client_id=fc.id))


@crm_financial_bp.route("/sessoes/<int:session_id>/completar", methods=["POST"])
def session_complete(session_id: int):
    session = SessionLocal.get(CoachingSession, session_id)
    if session is None:
        abort(404)
    session.completed = True
    audit_service.log_change("FinancialClient", session.financial_client_id, "field_update",
                              description=f"Session #{session.session_number} marked completed",
                              user_id=current_user.id)
    SessionLocal.commit()
    return redirect(url_for("crm_financial.client_detail", financial_client_id=session.financial_client_id))


@crm_financial_bp.route("/<int:financial_client_id>/tarefas/nova", methods=["POST"])
def task_new(financial_client_id: int):
    fc = SessionLocal.get(FinancialClient, financial_client_id)
    if fc is None:
        abort(404)

    task_name = request.form.get("task_name", "").strip()
    if not task_name:
        flash("Task name is required.", "error")
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
    audit_service.log_change("FinancialClient", fc.id, "create",
                              description=f"Task '{task_name}' added", user_id=current_user.id)
    SessionLocal.commit()
    flash("Task added.", "success")
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
