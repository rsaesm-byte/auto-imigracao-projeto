"""Weekly Planner (agenda pessoal do colaborador, bloqueio de horários
seg-dom) + time tracking estilo Clockify -- pedido do usuário, 2026-08-01.
Blueprint próprio, staff-only, mesmo guard `_require_staff` já usado em
app/staff.py/app/crm_staff_ops.py (não importado de lá de propósito --
convenção já estabelecida neste projeto de duplicar esse guard pequeno em
cada blueprint em vez de criar uma dependência entre eles)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.crm_models import Case, Client, Priority
from app.crm_staff_pipeline import OPEN_CASE_STATUSES
from app.db import SessionLocal
from app.models import User
from app.planner_models import PlannerBlock, Project, ProjectStatus, TimeEntry, TimeEntrySource
from app.services import crm_service as svc
from app.services import planner_service as planner_svc
from app.staff_permissions import require_area

planner_bp = Blueprint("planner", __name__, url_prefix="/staff")


@planner_bp.before_request
@login_required
def _require_staff():
    if not current_user.is_staff:
        abort(403)
    require_area("time_management")


def _parse_week_param() -> date:
    raw = request.args.get("week")
    if raw:
        try:
            return date.fromisoformat(raw)
        except ValueError:
            pass
    return datetime.now(timezone.utc).date()


def _parse_datetime_local(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


# --------------------------------------------------------------------------
# Weekly Planner -- personal week grid
# --------------------------------------------------------------------------

@planner_bp.route("/planner")
def planner_week():
    reference = _parse_week_param()
    monday = planner_svc.week_start(reference)
    days = [monday + timedelta(days=i) for i in range(7)]
    blocks = planner_svc.blocks_for_week(current_user.id, reference)
    blocks_by_day: dict[date, list[PlannerBlock]] = {d: [] for d in days}
    for b in blocks:
        blocks_by_day.setdefault(b.start_at.date(), []).append(b)

    clients = SessionLocal.query(Client).order_by(Client.full_name).all()
    projects = SessionLocal.query(Project).filter(
        Project.status.in_([ProjectStatus.active, ProjectStatus.on_hold])).order_by(Project.name).all()

    return render_template(
        "planner_week.html", active_tab="planner", days=days, blocks_by_day=blocks_by_day,
        monday=monday, prev_week=(monday - timedelta(days=7)).isoformat(),
        next_week=(monday + timedelta(days=7)).isoformat(), today=datetime.now(timezone.utc).date(),
        clients=clients, cases=SessionLocal.query(Case).order_by(Case.title).all(),
        projects=projects, block_type_options=planner_svc.block_type_options(), priorities=list(Priority))


@planner_bp.route("/planner/blocks", methods=["POST"])
def block_new():
    title = request.form.get("title", "").strip()
    start_at = _parse_datetime_local(request.form.get("start_at"))
    end_at = _parse_datetime_local(request.form.get("end_at"))
    if not title or start_at is None or end_at is None or end_at <= start_at:
        flash("Enter a title and a valid start/end time.", "error")
        return redirect(url_for("planner.planner_week", week=request.form.get("week", "")))

    block_type = planner_svc.resolve_block_type(
        request.form.get("block_type", "").strip(),
        request.form.get("custom_block_type"), current_user.id)
    if block_type is None:
        flash("Enter a name for the new type.", "error")
        return redirect(url_for("planner.planner_week", week=request.form.get("week", "")))

    SessionLocal.add(PlannerBlock(
        user_id=current_user.id, title=title, block_type=block_type,
        priority=svc.parse_enum(Priority, request.form.get("priority"), default=Priority.medium),
        client_id=svc.parse_int(request.form.get("client_id")),
        case_id=svc.parse_int(request.form.get("case_id")),
        project_id=svc.parse_int(request.form.get("project_id")),
        start_at=start_at, end_at=end_at,
        notes=request.form.get("notes", "").strip() or None))
    SessionLocal.commit()
    flash("Block added.", "success")
    return redirect(url_for("planner.planner_week", week=planner_svc.week_start(start_at.date()).isoformat()))


@planner_bp.route("/planner/blocks/<int:block_id>/salvar", methods=["POST"])
def block_edit(block_id: int):
    """Editar um bloco existente -- antes só dava pra completar/apagar,
    tinha que apagar e recriar pra corrigir qualquer campo. Mesma
    validação de block_new, mesma checagem de dono de block_complete/
    block_delete."""
    block = SessionLocal.get(PlannerBlock, block_id)
    if block is None or block.user_id != current_user.id:
        abort(404)

    title = request.form.get("title", "").strip()
    start_at = _parse_datetime_local(request.form.get("start_at"))
    end_at = _parse_datetime_local(request.form.get("end_at"))
    if not title or start_at is None or end_at is None or end_at <= start_at:
        flash("Enter a title and a valid start/end time.", "error")
        return redirect(url_for("planner.planner_week", week=request.form.get("week", "")))

    block_type = planner_svc.resolve_block_type(
        request.form.get("block_type", "").strip(),
        request.form.get("custom_block_type"), current_user.id)
    if block_type is None:
        flash("Enter a name for the new type.", "error")
        return redirect(url_for("planner.planner_week", week=request.form.get("week", "")))

    block.title = title
    block.block_type = block_type
    block.priority = svc.parse_enum(Priority, request.form.get("priority"), default=block.priority)
    block.client_id = svc.parse_int(request.form.get("client_id"))
    block.case_id = svc.parse_int(request.form.get("case_id"))
    block.project_id = svc.parse_int(request.form.get("project_id"))
    block.start_at = start_at
    block.end_at = end_at
    block.notes = request.form.get("notes", "").strip() or None
    SessionLocal.commit()
    flash("Block updated.", "success")
    return redirect(url_for("planner.planner_week", week=planner_svc.week_start(start_at.date()).isoformat()))


@planner_bp.route("/planner/blocks/<int:block_id>/complete", methods=["POST"])
def block_complete(block_id: int):
    block = SessionLocal.get(PlannerBlock, block_id)
    if block is None or block.user_id != current_user.id:
        abort(404)
    block.completed = not block.completed
    SessionLocal.commit()
    return redirect(url_for("planner.planner_week", week=planner_svc.week_start(block.start_at.date()).isoformat()))


@planner_bp.route("/planner/blocks/<int:block_id>/delete", methods=["POST"])
def block_delete(block_id: int):
    block = SessionLocal.get(PlannerBlock, block_id)
    if block is None or block.user_id != current_user.id:
        abort(404)
    week = planner_svc.week_start(block.start_at.date()).isoformat()
    SessionLocal.delete(block)
    SessionLocal.commit()
    flash("Block removed.", "success")
    return redirect(url_for("planner.planner_week", week=week))


# --------------------------------------------------------------------------
# Team view -- read-only week grid for every staff member
# --------------------------------------------------------------------------

@planner_bp.route("/planner/team")
def planner_team():
    reference = _parse_week_param()
    monday = planner_svc.week_start(reference)
    days = [monday + timedelta(days=i) for i in range(7)]
    staff_users = svc.staff_users()
    blocks = planner_svc.team_blocks_for_week([u.id for u in staff_users], reference)

    grid: dict[int, dict[date, list[PlannerBlock]]] = {u.id: {d: [] for d in days} for u in staff_users}
    for b in blocks:
        grid.setdefault(b.user_id, {}).setdefault(b.start_at.date(), []).append(b)

    return render_template(
        "planner_team.html", active_tab="planner", days=days, staff_users=staff_users, grid=grid,
        monday=monday, prev_week=(monday - timedelta(days=7)).isoformat(),
        next_week=(monday + timedelta(days=7)).isoformat(), today=datetime.now(timezone.utc).date())


# --------------------------------------------------------------------------
# Projects
# --------------------------------------------------------------------------

@planner_bp.route("/planner/projects")
def projects_list():
    projects = SessionLocal.query(Project).order_by(Project.status, Project.name).all()
    clients = SessionLocal.query(Client).order_by(Client.full_name).all()
    return render_template(
        "planner_projects.html", active_tab="planner", projects=projects, clients=clients,
        statuses=list(ProjectStatus), staff_users=svc.staff_users())


@planner_bp.route("/planner/projects/new", methods=["POST"])
def project_new():
    name = request.form.get("name", "").strip()
    if not name:
        flash("Project name is required.", "error")
        return redirect(url_for("planner.projects_list"))
    SessionLocal.add(Project(
        name=name, description=request.form.get("description", "").strip() or None,
        owner_id=svc.parse_int(request.form.get("owner_id")),
        client_id=svc.parse_int(request.form.get("client_id")),
        color=request.form.get("color", "").strip() or None))
    SessionLocal.commit()
    flash("Project created.", "success")
    return redirect(url_for("planner.projects_list"))


@planner_bp.route("/planner/projects/<int:project_id>/status", methods=["POST"])
def project_status_update(project_id: int):
    project = SessionLocal.get(Project, project_id)
    if project is None:
        abort(404)
    status = svc.parse_enum(ProjectStatus, request.form.get("status"))
    if status is not None:
        project.status = status
        SessionLocal.commit()
    return redirect(url_for("planner.projects_list"))


# --------------------------------------------------------------------------
# Time tracking (Clockify-like)
# --------------------------------------------------------------------------

@planner_bp.route("/time")
def time_list():
    from_raw = request.args.get("from")
    to_raw = request.args.get("to")
    today = datetime.now(timezone.utc).date()
    range_from = date.fromisoformat(from_raw) if from_raw else today.replace(day=1)
    range_to = date.fromisoformat(to_raw) if to_raw else today

    start_dt = datetime.combine(range_from, datetime.min.time())
    end_dt = datetime.combine(range_to, datetime.min.time()) + timedelta(days=1)
    entries = (
        SessionLocal.query(TimeEntry)
        .filter(TimeEntry.user_id == current_user.id, TimeEntry.started_at >= start_dt,
                TimeEntry.started_at < end_dt)
        .order_by(TimeEntry.started_at.desc())
        .all()
    )

    clients = {c.id: c for c in SessionLocal.query(Client).all()}
    projects = {p.id: p for p in SessionLocal.query(Project).all()}
    cases = {c.id: c for c in SessionLocal.query(Case).all()}
    # Só casos ABERTOS no seletor de atribuição -- pedido do usuário
    # 2026-08-06 ("atribuir a um caso EM ABERTO"). `cases` acima continua
    # com TODOS (fechados inclusive), usado por label_for()/total_by_label
    # pra uma entrada antiga ainda mostrar o nome certo mesmo se o caso já
    # tiver fechado depois.
    open_cases = [c for c in cases.values() if c.case_status in OPEN_CASE_STATUSES]
    open_cases.sort(key=lambda c: c.title)

    def label_for(entry: TimeEntry) -> str:
        if entry.client_id and entry.client_id in clients:
            return clients[entry.client_id].full_name
        if entry.project_id and entry.project_id in projects:
            return projects[entry.project_id].name
        if entry.case_id and entry.case_id in cases:
            return cases[entry.case_id].title
        return "—"

    total_by_label: dict[str, int] = {}
    for e in entries:
        label = label_for(e)
        total_by_label[label] = total_by_label.get(label, 0) + planner_svc.entry_duration_seconds(e)

    return render_template(
        "planner_time.html", active_tab="time", entries=entries, label_for=label_for,
        duration=planner_svc.entry_duration_seconds, format_duration=planner_svc.format_duration,
        total_by_label=sorted(total_by_label.items(), key=lambda kv: kv[1], reverse=True),
        range_from=range_from.isoformat(), range_to=range_to.isoformat(),
        clients=clients.values(), projects=projects.values(), cases=open_cases,
        running=planner_svc.running_entry_for(current_user.id))


@planner_bp.route("/time/start", methods=["POST"])
def time_start():
    entry = planner_svc.start_timer(
        current_user.id, description=request.form.get("description", "").strip() or None,
        client_id=svc.parse_int(request.form.get("client_id")),
        case_id=svc.parse_int(request.form.get("case_id")),
        project_id=svc.parse_int(request.form.get("project_id")),
        task_id=None)
    SessionLocal.commit()
    return redirect(request.referrer or url_for("planner.time_list"))


@planner_bp.route("/time/stop", methods=["POST"])
def time_stop():
    planner_svc.stop_timer(current_user.id)
    SessionLocal.commit()
    return redirect(request.referrer or url_for("planner.time_list"))


@planner_bp.route("/time/manual", methods=["POST"])
def time_manual():
    started_at = _parse_datetime_local(request.form.get("started_at"))
    ended_at = _parse_datetime_local(request.form.get("ended_at"))
    if started_at is None or ended_at is None or ended_at <= started_at:
        flash("Enter a valid start and end time.", "error")
        return redirect(url_for("planner.time_list"))

    SessionLocal.add(TimeEntry(
        user_id=current_user.id, description=request.form.get("description", "").strip() or None,
        client_id=svc.parse_int(request.form.get("client_id")),
        case_id=svc.parse_int(request.form.get("case_id")),
        project_id=svc.parse_int(request.form.get("project_id")),
        source=TimeEntrySource.manual, started_at=started_at, ended_at=ended_at))
    SessionLocal.commit()
    flash("Time entry logged.", "success")
    return redirect(url_for("planner.time_list"))


@planner_bp.route("/time/<int:entry_id>/salvar", methods=["POST"])
def time_entry_update(entry_id: int):
    """Edita uma entrada já existente -- pedido do usuário 2026-08-06:
    "possível clicar e editar e atribuir a um caso em aberto". Só o dono
    da entrada pode editar (mesmo padrão de isolamento de
    _owned_case/_owned_contract em app/crm_client.py, adaptado pra
    Time Entries -- cada colaborador só edita as próprias)."""
    entry = SessionLocal.get(TimeEntry, entry_id)
    if entry is None or entry.user_id != current_user.id:
        abort(404)

    started_at = _parse_datetime_local(request.form.get("started_at"))
    ended_at_raw = request.form.get("ended_at", "").strip()
    ended_at = _parse_datetime_local(ended_at_raw) if ended_at_raw else None
    if started_at is None or (ended_at is not None and ended_at <= started_at):
        flash("Enter a valid start (and, if set, a later end) time.", "error")
        return redirect(url_for("planner.time_list"))

    entry.description = request.form.get("description", "").strip() or None
    entry.client_id = svc.parse_int(request.form.get("client_id"))
    entry.case_id = svc.parse_int(request.form.get("case_id"))
    entry.project_id = svc.parse_int(request.form.get("project_id"))
    entry.started_at = started_at
    entry.ended_at = ended_at
    SessionLocal.commit()
    flash("Time entry updated.", "success")
    return redirect(request.referrer or url_for("planner.time_list"))
