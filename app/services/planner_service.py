"""Regras de negócio do Weekly Planner + time tracking (ver
app/planner_models.py). Mesma convenção do resto do CRM
(app/services/crm_service.py): campos calculados nunca viram coluna, e
funções aqui só alteram objetos em memória -- quem chama decide quando
commitar."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app.db import SessionLocal
from app.planner_models import BlockType, CustomBlockType, PlannerBlock, Project, TimeEntry, TimeEntrySource

NEW_BLOCK_TYPE_SENTINEL = "__new__"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def block_type_options() -> list[str]:
    """Built-in BlockType presets first, then any team-saved CustomBlockType
    not already covered by a preset (case-insensitive) -- the combined list
    offered in the Weekly Planner "Type" dropdown."""
    presets = [t.value for t in BlockType]
    seen = {p.lower() for p in presets}
    customs = SessionLocal.query(CustomBlockType).order_by(CustomBlockType.label).all()
    extra = [c.label for c in customs if c.label.lower() not in seen]
    return presets + extra


def resolve_block_type(selected: str, custom_label: str | None, user_id: int) -> str | None:
    """Turns the quick-add form's "Type" fields into the string to store on
    PlannerBlock.block_type. When the user didn't pick "+ Add new type...",
    just passes the selected value through. Otherwise validates/normalizes
    the typed label: reuses an existing preset or saved CustomBlockType
    (case-insensitive) if it already matches one, or saves a brand new
    CustomBlockType row -- so it shows up for the whole team next time
    (user request, 2026-08-02: "essa entrada deverá ficar salva na lista").
    Returns None when a new type was required but left blank."""
    if selected != NEW_BLOCK_TYPE_SENTINEL:
        return selected or BlockType.task.value

    label = (custom_label or "").strip()
    if not label:
        return None

    for preset in BlockType:
        if label.lower() in (preset.value.lower(), preset.value.replace("_", " ").lower()):
            return preset.value

    existing = (
        SessionLocal.query(CustomBlockType)
        .filter(CustomBlockType.label.ilike(label))
        .first()
    )
    if existing is not None:
        return existing.label

    SessionLocal.add(CustomBlockType(label=label, created_by_id=user_id))
    SessionLocal.flush()
    return label


def week_start(reference: date) -> date:
    """Monday of the week containing `reference`."""
    return reference - timedelta(days=reference.weekday())


def week_bounds(reference: date) -> tuple[datetime, datetime]:
    """(Monday 00:00, next Monday 00:00) as naive UTC datetimes, for
    range-filtering PlannerBlock.start_at."""
    start = datetime.combine(week_start(reference), datetime.min.time())
    return start, start + timedelta(days=7)


def blocks_for_week(user_id: int, reference: date) -> list[PlannerBlock]:
    start, end = week_bounds(reference)
    return (
        SessionLocal.query(PlannerBlock)
        .filter(PlannerBlock.user_id == user_id, PlannerBlock.start_at >= start, PlannerBlock.start_at < end)
        .order_by(PlannerBlock.start_at)
        .all()
    )


def team_blocks_for_week(user_ids: list[int], reference: date) -> list[PlannerBlock]:
    start, end = week_bounds(reference)
    if not user_ids:
        return []
    return (
        SessionLocal.query(PlannerBlock)
        .filter(PlannerBlock.user_id.in_(user_ids), PlannerBlock.start_at >= start, PlannerBlock.start_at < end)
        .order_by(PlannerBlock.start_at)
        .all()
    )


def running_entry_for(user_id: int) -> TimeEntry | None:
    return (
        SessionLocal.query(TimeEntry)
        .filter(TimeEntry.user_id == user_id, TimeEntry.ended_at.is_(None))
        .order_by(TimeEntry.started_at.desc())
        .first()
    )


def entry_duration_seconds(entry: TimeEntry, *, now: datetime | None = None) -> int:
    """Duração em segundos -- calculada na leitura, nunca gravada (mesma
    convenção de app/crm_models.py: campos "formula" não são coluna).
    Se `entry` ainda está rodando (ended_at is None), usa `now`."""
    end = entry.ended_at or now or _utcnow()
    started = entry.started_at
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return max(0, int((end - started).total_seconds()))


def format_duration(total_seconds: int) -> str:
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def start_timer(user_id: int, *, description: str | None, client_id: int | None,
                 case_id: int | None, project_id: int | None, task_id: int | None) -> TimeEntry:
    """Para o cronômetro atual (se houver) e inicia um novo -- só um
    TimeEntry "rodando" (ended_at NULL) por usuário por vez, igual ao
    Clockify real (pedido do usuário, 2026-08-01)."""
    now = _utcnow()
    current = running_entry_for(user_id)
    if current is not None:
        current.ended_at = now
    entry = TimeEntry(
        user_id=user_id, description=description, client_id=client_id, case_id=case_id,
        project_id=project_id, task_id=task_id, source=TimeEntrySource.timer, started_at=now)
    SessionLocal.add(entry)
    return entry


def stop_timer(user_id: int) -> TimeEntry | None:
    current = running_entry_for(user_id)
    if current is not None:
        current.ended_at = _utcnow()
    return current


def total_seconds_by(entries: list[TimeEntry], key_fn) -> dict:
    """Agrupa e soma a duração de uma lista de TimeEntry por uma chave
    arbitrária (ex.: por client_id, por project_id) -- usado no relatório."""
    totals: dict = {}
    now = _utcnow()
    for entry in entries:
        key = key_fn(entry)
        totals[key] = totals.get(key, 0) + entry_duration_seconds(entry, now=now)
    return totals
