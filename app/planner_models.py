"""Weekly Planner + time tracking (Clockify-like) -- pedido do usuário,
2026-08-01. Módulo próprio (separado de crm_models.py) porque é uma
ferramenta de produtividade PESSOAL do colaborador, não faz parte do
pipeline de imigração em si -- mesmo padrão de crm_financial_models.py
(linha de "negócio" separada, tabelas próprias, mas reusando enums/tabelas
do CRM onde faz sentido, ex. Priority, Client, Case).

Painel do colaborador é sempre inglês (ver
memory/feedback_staff_interface_english.md) -- todo enum e comentário
user-facing aqui segue em inglês; comentários de código (não visíveis)
continuam em português, convenção do projeto.

Campos calculados (duração de um TimeEntry) não são coluna -- computados
na leitura em app/services/planner_service.py, mesma convenção do resto
do CRM (ver app/crm_models.py, topo do arquivo)."""
from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.crm_models import Priority
from app.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ProjectStatus(str, enum.Enum):
    active = "active"
    on_hold = "on_hold"
    completed = "completed"
    archived = "archived"


class BlockType(str, enum.Enum):
    """Built-in preset block types -- always offered in the Weekly Planner
    dropdown. Not the only allowed values: a staff member can also type a
    custom one via "+ Add new type..." (see CustomBlockType below), so
    `PlannerBlock.block_type` itself is a plain string column, not this
    enum -- user request, 2026-08-02: "colocar uma entrada type (se nao
    estiver na lista) e essa entrada deverá ficar salva na lista"."""
    task = "task"
    meeting = "meeting"
    call = "call"
    focus_time = "focus_time"
    break_time = "break_time"
    out_of_office = "out_of_office"
    other = "other"


class CustomBlockType(Base):
    """A free-text block type a staff member typed once because it wasn't
    among the BlockType presets -- saved here so it shows up as a normal
    dropdown choice for the whole team afterward, instead of anyone having
    to retype it. Shared across staff (not per-user): keeps everyone using
    the same vocabulary rather than fragmenting it per person."""
    __tablename__ = "planner_custom_block_types"

    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(unique=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class TimeEntrySource(str, enum.Enum):
    timer = "timer"
    manual = "manual"


class Project(Base):
    """Internal project -- a new concept, deliberately separate from
    `Case` (CRM). May optionally reference a client, but doesn't have to
    (e.g. "Website Redesign", "Team Training") -- user request, 2026-08-01:
    "projeto... novo conceito, separado do Caso"."""
    __tablename__ = "planner_projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    description: Mapped[str | None] = mapped_column(Text, default=None)
    status: Mapped[ProjectStatus] = mapped_column(SAEnum(ProjectStatus), default=ProjectStatus.active, index=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None, index=True)
    client_id: Mapped[int | None] = mapped_column(ForeignKey("crm_clients.id"), default=None, index=True)
    color: Mapped[str | None] = mapped_column(default=None)  # hex, e.g. "#205B5B"
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    owner: Mapped["User | None"] = relationship()  # noqa: F821
    client: Mapped["Client | None"] = relationship()  # noqa: F821


class PlannerBlock(Base):
    """A time block on a staff member's personal weekly calendar -- user
    request (2026-08-01): "poderá bloquear blocos de tempos em todos os
    dias da semana de segunda a domingo". Optionally links to a CRM
    Client/Case, a Project, or a CRM Task for context -- none required,
    a block can just be unstructured "focus time"."""
    __tablename__ = "planner_blocks"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str]
    # Plain string, not SAEnum(BlockType) -- a block's type can be one of
    # the BlockType presets OR a saved CustomBlockType label (see above);
    # the enum alone can't express that, and SQLAlchemy's Enum type
    # rejects/crashes on read for any value outside it.
    block_type: Mapped[str] = mapped_column(default=BlockType.task.value, index=True)
    priority: Mapped[Priority] = mapped_column(SAEnum(Priority), default=Priority.medium)

    client_id: Mapped[int | None] = mapped_column(ForeignKey("crm_clients.id"), default=None, index=True)
    case_id: Mapped[int | None] = mapped_column(ForeignKey("crm_cases.id"), default=None, index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("planner_projects.id"), default=None, index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("crm_tasks.id"), default=None, index=True)

    start_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    end_at: Mapped[datetime] = mapped_column(DateTime)
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    completed: Mapped[bool] = mapped_column(default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    client: Mapped["Client | None"] = relationship()  # noqa: F821
    case: Mapped["Case | None"] = relationship()  # noqa: F821
    project: Mapped[Project | None] = relationship()
    task: Mapped["Task | None"] = relationship()  # noqa: F821


class TimeEntry(Base):
    """Clockify-style time entry -- user request (2026-08-01): "algo
    parecido com o clockify para marcação de tempo". `ended_at` is NULL
    while the timer is running (only one running entry per user at a
    time -- enforced in app/planner.py::start_timer, not here, per this
    project's convention of keeping business rules out of the model
    layer). `source` distinguishes a live timer from a manually logged
    entry -- both are supported per user request."""
    __tablename__ = "planner_time_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    description: Mapped[str | None] = mapped_column(default=None)

    client_id: Mapped[int | None] = mapped_column(ForeignKey("crm_clients.id"), default=None, index=True)
    case_id: Mapped[int | None] = mapped_column(ForeignKey("crm_cases.id"), default=None, index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("planner_projects.id"), default=None, index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("crm_tasks.id"), default=None, index=True)

    source: Mapped[TimeEntrySource] = mapped_column(SAEnum(TimeEntrySource), default=TimeEntrySource.timer)
    started_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, default=None, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    client: Mapped["Client | None"] = relationship()  # noqa: F821
    case: Mapped["Case | None"] = relationship()  # noqa: F821
    project: Mapped[Project | None] = relationship()
    task: Mapped["Task | None"] = relationship()  # noqa: F821
