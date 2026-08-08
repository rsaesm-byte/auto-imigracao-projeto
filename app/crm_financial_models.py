"""Modelos do módulo de Coaching Financeiro (CRM Fase 2) -- Financial
Planning/Financial Tasks/Coaching Sessions do Notion original. Sibling de
`app/crm_models.py` (Fase 1, núcleo imigratório) -- arquivo próprio pra não
inchar ainda mais aquele módulo, mesma `Base`/convenções.

Decisões de modelagem confirmadas com o usuário nesta sessão:
- `FinancialClient` é uma entidade própria, não fundida com `Client`
  (imigração) -- no Notion original as duas linhas de negócio já são
  cadastros separados (nenhuma relação entre "Financial Planning" e
  "Customer" no ER original). `client_id` aqui é um link OPCIONAL pra
  quando a mesma pessoa também é cliente de imigração.
- Pagamentos do coaching reusam o MESMO `PaymentLedgerEntry` do módulo
  imigratório (`app/crm_models.py`) -- ganhou um `financial_client_id`
  opcional lá, em vez de duplicar o conceito de "Payments" que o Notion
  original tinha uma vez por linha de negócio.
- Cliente de coaching também tem login e um painel "Meu Plano Financeiro"
  (`app/crm_financial_client.py`), então `FinancialClient.user_id` existe
  igual a `Client.user_id`.

Como no módulo Fase 1: vocabulário fechado é `enum.Enum` (não tabela),
vocabulário aberto/editável reusa os lookups já existentes quando o
conceito é o mesmo (`LeadSource`, `CloseLossReason`, `PaymentMethodLookup`,
`IncomeSourceType`, todos em `app/crm_models.py`) -- só cria lookup novo
quando o Notion original não tinha equivalente nenhum no módulo
imigratório (`FinancialGoal`, `FinancialChallenge`, `FinancialTaskCategory`).

Vários campos do Notion original NÃO viram coluna aqui por serem puramente
calculados a partir de outras tabelas (implementados em
`app/services/crm_financial_service.py`): `Amount Paid` (soma do ledger),
`Payment Status` (derivado do ledger + prazos), `Sessions Completed`/
`Sessions Remaining` (contagem de `CoachingSession`), `Last/Next Session
Date` (min/max de `CoachingSession.session_date`), `Net Worth` (assets -
liabilities), `Is Converted`/`Conversion Status` (derivado de
`client_status`), `Completion %`, `Homework Completion` -- gravar
qualquer um desses como coluna reintroduziria a mesma dívida (formula
"travada" no valor de quando foi calculada) que o módulo Fase 1 já evitou.
"""
from __future__ import annotations

import enum
from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, ForeignKey, SmallInteger, Text, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.crm_models import MaritalStatus, PreferredLanguage, Priority, TaskStatus
from app.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------
# Vocabulário fechado -> enum (fixo, controlado pela lógica de negócio)
# --------------------------------------------------------------------------

class FinancialClientStatus(str, enum.Enum):
    new_lead = "new_lead"
    proposal_sent = "proposal_sent"
    consultation_scheduled = "consultation_scheduled"
    onboarding = "onboarding"
    active_6_sessions = "active_6_sessions"
    completed_program = "completed_program"
    lost_client = "lost_client"


class ProgramType(str, enum.Enum):
    financial_literacy = "financial_literacy"
    college_planning = "college_planning"
    emergency_fund = "emergency_fund"
    retirement_planning = "retirement_planning"
    investment_planning = "investment_planning"
    budget_planning = "budget_planning"
    debt_elimination = "debt_elimination"
    financial_planning = "financial_planning"
    financial_coaching = "financial_coaching"


class FinancialProgressStatus(str, enum.Enum):
    not_started = "not_started"
    on_track = "on_track"
    in_progress = "in_progress"
    needs_attention = "needs_attention"
    at_risk = "at_risk"
    completed = "completed"


class HomeworkAdherenceLevel(str, enum.Enum):
    high = "high"
    medium = "medium"
    low = "low"


class ClientComplianceLevel(str, enum.Enum):
    excellent = "excellent"
    good = "good"
    poor = "poor"
    non_compliant = "non_compliant"


class NinetyDayReviewStatus(str, enum.Enum):
    not_scheduled = "not_scheduled"
    scheduled = "scheduled"
    done = "done"
    declined = "declined"


class ContinuityProgram(str, enum.Enum):
    none = "none"
    maintenance_quarterly = "maintenance_quarterly"
    premium_monthly = "premium_monthly"
    advisory_on_demand = "advisory_on_demand"


class FocusArea(str, enum.Enum):
    budgeting = "budgeting"
    cash_flow_management = "cash_flow_management"
    credit_improvement = "credit_improvement"
    debt_reduction = "debt_reduction"
    education_savings = "education_savings"
    emergency_fund = "emergency_fund"
    family_financial_planning = "family_financial_planning"
    investments = "investments"
    retirement = "retirement"
    wealth_building = "wealth_building"


class HouseholdIncomeRange(str, enum.Enum):
    under_3000 = "under_3000"
    from_3000_5000 = "from_3000_5000"
    from_5001_10000 = "from_5001_10000"
    from_10001_15000 = "from_10001_15000"
    from_15001_20000 = "from_15001_20000"
    over_20000 = "over_20000"


class EmergencyFundStatus(str, enum.Enum):
    none = "none"
    less_1_month = "less_1_month"
    from_1_3_months = "from_1_3_months"
    from_3_6_months = "from_3_6_months"
    from_6_12_months = "from_6_12_months"
    more_12_months = "more_12_months"


class MeetingPlatform(str, enum.Enum):
    google_meet = "google_meet"
    whatsapp = "whatsapp"
    zoom = "zoom"
    microsoft_teams = "microsoft_teams"
    telegram = "telegram"
    other = "other"


class SessionType(str, enum.Enum):
    discovery_consultation = "discovery_consultation"
    financial_assessment = "financial_assessment"
    goal_setting = "goal_setting"
    cash_flow_review = "cash_flow_review"
    debt_reduction = "debt_reduction"
    credit_improvement = "credit_improvement"
    emergency_fund_planning = "emergency_fund_planning"
    investment_planning = "investment_planning"
    retirement_planning = "retirement_planning"
    insurance_review = "insurance_review"
    tax_planning = "tax_planning"
    estate_planning = "estate_planning"
    financial_education = "financial_education"
    progress_review = "progress_review"
    accountability_session = "accountability_session"
    strategy_review = "strategy_review"
    annual_review = "annual_review"
    follow_up = "follow_up"
    closing_session = "closing_session"


class TaskDifficulty(str, enum.Enum):
    easy = "easy"
    medium = "medium"
    hard = "hard"


class TaskResponsibleParty(str, enum.Enum):
    client = "client"
    coach = "coach"


class FinancialPlanningStatus(str, enum.Enum):
    """Status do módulo self-service "Financial Planning" (Fase 1 do
    SAES_Financial_Planning_Master_Spec, 2026-08-07) -- distinto de
    `FinancialClientStatus` acima, que é o FUNIL DE VENDA do coaching
    (lead -> proposta -> onboarding -> ...). Este enum descreve só o
    ACESSO ao workspace self-service (contas/orçamento/dívidas/metas
    que o próprio cliente alimenta, Fase 2 em diante) -- alguém pode
    estar `active` no funil de coaching e ainda `not_eligible` aqui, se
    o pacote contratado não incluir o módulo de tracking próprio."""
    not_eligible = "not_eligible"
    eligible = "eligible"
    active = "active"
    paused = "paused"
    completed = "completed"
    cancelled = "cancelled"


# --------------------------------------------------------------------------
# Vocabulário aberto -> lookup NOVO (só quando não existe equivalente já
# reusável em app/crm_models.py -- LeadSource/CloseLossReason/
# PaymentMethodLookup/IncomeSourceType são reusados diretamente, sem
# duplicar aqui)
# --------------------------------------------------------------------------

class FinancialGoal(Base):
    """`sort_order`/`deleted_at` (2026-08-07, pedido do usuário) --
    checkbox editável pelo painel (reordenar, renomear, adicionar,
    apagar) na ficha do cliente de coaching. Apagar é sempre exclusão
    LÓGICA -- clientes que já têm essa meta marcada continuam com o
    vínculo intacto (`FinancialClientGoal`), só some da lista de novas
    seleções."""
    __tablename__ = "crm_financial_goals"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
    sort_order: Mapped[int] = mapped_column(default=0)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)


class FinancialChallenge(Base):
    """Ver `FinancialGoal` -- mesma decisão (editável pelo painel,
    exclusão lógica)."""
    __tablename__ = "crm_financial_challenges"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
    sort_order: Mapped[int] = mapped_column(default=0)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)


class FinancialCoachingSelectOption(Base):
    """Os 7 selects de vocabulário fechado da ficha de coaching que
    viraram editáveis pelo painel (2026-08-08, item pendente do Prompt
    Mestre 1): Progress status, Priority, Homework adherence, Client
    compliance, 90-day review, Continuity program, Current focus area.
    Diferente de FinancialGoal/FinancialChallenge (uma tabela por lista,
    com FK de outra tabela apontando pra cada linha), estes 7 são
    single-select simples -- FinancialClient guarda o `name` escolhido
    direto como string, sem tabela de junção nem FK -- então UMA tabela
    genérica com `kind` como discriminador basta (evita 7 classes quase
    idênticas). `kind` é uma das chaves de
    app/crm_pipeline_settings.py::_FINANCIAL_SELECT_KINDS."""
    __tablename__ = "crm_financial_coaching_select_options"
    __table_args__ = (UniqueConstraint("kind", "name", name="uq_fc_select_option_kind_name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(index=True)
    name: Mapped[str]
    sort_order: Mapped[int] = mapped_column(default=0)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)


class FinancialTaskCategory(Base):
    __tablename__ = "crm_financial_task_categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)


# --------------------------------------------------------------------------
# Núcleo
# --------------------------------------------------------------------------

class FinancialClient(Base):
    __tablename__ = "crm_financial_clients"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), unique=True, default=None, index=True)
    # Link opcional pro cadastro de imigração (app/crm_models.py::Client) --
    # quando a mesma pessoa é cliente das duas linhas de negócio da Saes.
    client_id: Mapped[int | None] = mapped_column(
        ForeignKey("crm_clients.id"), default=None, index=True)

    full_name: Mapped[str]
    email: Mapped[str | None] = mapped_column(default=None, index=True)
    phone_number: Mapped[str | None] = mapped_column(default=None)
    dob: Mapped[date | None] = mapped_column(Date, default=None)
    marital_status: Mapped[MaritalStatus | None] = mapped_column(SAEnum(MaritalStatus), default=None)
    occupation: Mapped[str | None] = mapped_column(default=None)
    employer: Mapped[str | None] = mapped_column(default=None)
    preferred_language: Mapped[PreferredLanguage | None] = mapped_column(
        SAEnum(PreferredLanguage), default=None)

    # Funil / venda
    client_status: Mapped[FinancialClientStatus] = mapped_column(
        SAEnum(FinancialClientStatus), default=FinancialClientStatus.new_lead, index=True)
    lead_source_id: Mapped[int | None] = mapped_column(ForeignKey("crm_lead_sources.id"), default=None)
    first_contact_at: Mapped[date | None] = mapped_column(Date, default=None)
    proposal_at: Mapped[date | None] = mapped_column(Date, default=None)
    closed_at: Mapped[date | None] = mapped_column(Date, default=None)
    lost_deal_at: Mapped[date | None] = mapped_column(Date, default=None)
    loss_reason_id: Mapped[int | None] = mapped_column(ForeignKey("crm_close_loss_reasons.id"), default=None)
    acquisition_cost_cents: Mapped[int | None] = mapped_column(default=None)
    # Métrica operacional real (não derivável de outra tabela -- não temos
    # histórico de mensagens no banco, só a contagem que a equipe registra).
    messages_last_14_days: Mapped[int | None] = mapped_column(default=None)

    # Programa
    program_type: Mapped[ProgramType | None] = mapped_column(SAEnum(ProgramType), default=None)
    enrollment_at: Mapped[date | None] = mapped_column(Date, default=None)
    diagnostic_at: Mapped[date | None] = mapped_column(Date, default=None)
    # "Sessions Completed"/"Last Session Date"/"Next Session Date" do Notion
    # NÃO viram coluna -- são contagem/min/max sobre CoachingSession
    # (ver app/services/crm_financial_service.py). Só o Nº CONTRATADO fica
    # aqui, porque é um fato de venda, não algo derivável dos registros de
    # sessão.
    total_sessions_purchased: Mapped[int | None] = mapped_column(default=None)
    last_session_duration_minutes: Mapped[int | None] = mapped_column(default=None)
    target_completion_at: Mapped[date | None] = mapped_column(Date, default=None)
    # progress_status/homework_adherence/client_compliance/review_90day_status/
    # continuity_program/priority_level/current_focus_area viraram string
    # livre (2026-08-08, item pendente do Prompt Mestre 1) -- eram
    # SAEnum(...) fixo em Python, agora validados contra
    # FinancialCoachingSelectOption (staff-editável, ver
    # app/crm_pipeline_settings.py::financial_coaching_options). Coluna já
    # era VARCHAR no SQLite por baixo (Enum vira texto), então nenhum dado
    # existente muda de valor com esta troca -- só o Python para de exigir
    # um dos membros fixos do enum antigo. Os enums Python
    # (FinancialProgressStatus etc., acima) continuam existindo só pra
    # dar nome aos valores do seed inicial (_seed_financial_coaching_select_options
    # em app/__init__.py), nunca mais usados como tipo de coluna aqui.
    progress_status: Mapped[str] = mapped_column(default=FinancialProgressStatus.not_started.value)
    homework_adherence: Mapped[str | None] = mapped_column(default=None)
    client_compliance: Mapped[str | None] = mapped_column(default=None)
    review_90day_status: Mapped[str] = mapped_column(default=NinetyDayReviewStatus.not_scheduled.value)
    continuity_program: Mapped[str] = mapped_column(default=ContinuityProgram.none.value)
    nps_score: Mapped[int | None] = mapped_column(default=None)
    # Antes reusava o enum compartilhado Priority (low/medium/high/urgent) --
    # agora é a própria lista editável "Priority" deste módulo (item
    # pendente do Prompt Mestre 1), independente do Priority usado por
    # Leads/Tasks em outras partes do CRM (aquele enum não foi tocado).
    priority_level: Mapped[str] = mapped_column(default=Priority.medium.value)
    current_focus_area: Mapped[str | None] = mapped_column(default=None)
    wins_milestones: Mapped[str | None] = mapped_column(Text, default=None)
    action_plan: Mapped[str | None] = mapped_column(Text, default=None)
    recommended_solutions: Mapped[str | None] = mapped_column(Text, default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    financial_diagnosis_file_path: Mapped[str | None] = mapped_column(default=None)

    # Perfil financeiro
    household_income_range: Mapped[HouseholdIncomeRange | None] = mapped_column(
        SAEnum(HouseholdIncomeRange), default=None)
    monthly_household_income_cents: Mapped[int | None] = mapped_column(default=None)
    monthly_expenses_cents: Mapped[int | None] = mapped_column(default=None)
    emergency_fund_status: Mapped[EmergencyFundStatus | None] = mapped_column(
        SAEnum(EmergencyFundStatus), default=None)
    credit_score: Mapped[int | None] = mapped_column(default=None)
    total_assets_cents: Mapped[int | None] = mapped_column(default=None)
    total_liabilities_cents: Mapped[int | None] = mapped_column(default=None)
    cash_banking_cents: Mapped[int | None] = mapped_column(default=None)
    investments_cents: Mapped[int | None] = mapped_column(default=None)
    real_estate_cents: Mapped[int | None] = mapped_column(default=None)
    vehicles_cents: Mapped[int | None] = mapped_column(default=None)
    retirement_cents: Mapped[int | None] = mapped_column(default=None)
    business_ownership_value_cents: Mapped[int | None] = mapped_column(default=None)
    credit_card_debt_cents: Mapped[int | None] = mapped_column(default=None)

    # Pagamento -- "Amount Paid"/"Payment Status"/"Last Payment Date" do
    # Notion são calculados a partir de PaymentLedgerEntry
    # (financial_client_id), nunca gravados aqui. "Package Value" fica,
    # porque é o valor negociado/contratado -- um fato, não uma derivação.
    package_value_cents: Mapped[int | None] = mapped_column(default=None)

    # Acesso ao módulo self-service "Financial Planning" (Fase 1 do
    # SAES_Financial_Planning_Master_Spec, 2026-08-07) -- controla só se
    # o cliente VÊ o workspace no portal e pode alimentar seus próprios
    # dados (contas/orçamento/dívidas/metas, Fase 2 em diante). Nunca
    # apaga o workspace/dado financeiro ao desabilitar -- só esconde (ver
    # app/services/financial_planning_service.py::disable_access).
    financial_planning_enabled: Mapped[bool] = mapped_column(default=False, index=True)
    financial_planning_status: Mapped[FinancialPlanningStatus] = mapped_column(
        SAEnum(FinancialPlanningStatus), default=FinancialPlanningStatus.not_eligible)
    financial_planning_plan: Mapped[str | None] = mapped_column(default=None)
    financial_planning_started_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    financial_planning_ends_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    financial_planning_enabled_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    financial_planning_enabled_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), default=None)
    financial_planning_disabled_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    financial_planning_disabled_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    meeting_platforms: Mapped[list["FinancialClientMeetingPlatform"]] = relationship(
        back_populates="financial_client", cascade="all, delete-orphan")
    income_sources: Mapped[list["FinancialClientIncomeSource"]] = relationship(
        back_populates="financial_client", cascade="all, delete-orphan")
    goals: Mapped[list["FinancialClientGoal"]] = relationship(
        back_populates="financial_client", cascade="all, delete-orphan")
    challenges: Mapped[list["FinancialClientChallenge"]] = relationship(
        back_populates="financial_client", cascade="all, delete-orphan")
    tasks: Mapped[list["FinancialTask"]] = relationship(back_populates="financial_client")
    sessions: Mapped[list["CoachingSession"]] = relationship(
        back_populates="financial_client", order_by="CoachingSession.session_number")
    workspace: Mapped["FinancialWorkspace | None"] = relationship(
        back_populates="financial_client", uselist=False, cascade="all, delete-orphan")


class FinancialClientMeetingPlatform(Base):
    __tablename__ = "crm_financial_client_meeting_platforms"

    financial_client_id: Mapped[int] = mapped_column(
        ForeignKey("crm_financial_clients.id"), primary_key=True)
    platform: Mapped[MeetingPlatform] = mapped_column(SAEnum(MeetingPlatform), primary_key=True)

    financial_client: Mapped[FinancialClient] = relationship(back_populates="meeting_platforms")


class FinancialClientIncomeSource(Base):
    """Reusa IncomeSourceType (app/crm_models.py) -- mesma lista já serve
    pro intake de imigração e pro perfil financeiro do coaching."""
    __tablename__ = "crm_financial_client_income_sources"

    financial_client_id: Mapped[int] = mapped_column(
        ForeignKey("crm_financial_clients.id"), primary_key=True)
    income_source_type_id: Mapped[int] = mapped_column(
        ForeignKey("crm_income_source_types.id"), primary_key=True)

    financial_client: Mapped[FinancialClient] = relationship(back_populates="income_sources")


class FinancialClientGoal(Base):
    __tablename__ = "crm_financial_client_goals"

    financial_client_id: Mapped[int] = mapped_column(
        ForeignKey("crm_financial_clients.id"), primary_key=True)
    financial_goal_id: Mapped[int] = mapped_column(ForeignKey("crm_financial_goals.id"), primary_key=True)

    financial_client: Mapped[FinancialClient] = relationship(back_populates="goals")


class FinancialClientChallenge(Base):
    __tablename__ = "crm_financial_client_challenges"

    financial_client_id: Mapped[int] = mapped_column(
        ForeignKey("crm_financial_clients.id"), primary_key=True)
    financial_challenge_id: Mapped[int] = mapped_column(
        ForeignKey("crm_financial_challenges.id"), primary_key=True)

    financial_client: Mapped[FinancialClient] = relationship(back_populates="challenges")


class FinancialTask(Base):
    """`Task Completed` (checkbox) do Notion não vira coluna -- é
    `status == TaskStatus.done` (reusa o enum de app/crm_models.py, o
    mesmo usado pelas Tasks do módulo imigratório; `waiting_translation`
    simplesmente nunca é usado aqui)."""
    __tablename__ = "crm_financial_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    financial_client_id: Mapped[int] = mapped_column(
        ForeignKey("crm_financial_clients.id"), index=True)
    coaching_session_id: Mapped[int | None] = mapped_column(
        ForeignKey("crm_coaching_sessions.id"), default=None, index=True)

    task_name: Mapped[str]
    status: Mapped[TaskStatus] = mapped_column(SAEnum(TaskStatus), default=TaskStatus.not_started, index=True)
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("crm_financial_task_categories.id"), default=None)
    # Reusa Priority (low/medium/high/urgent) -- Notion mapeado:
    # Critical == urgent, mesma convenção de FinancialClient.priority_level.
    priority: Mapped[Priority] = mapped_column(SAEnum(Priority), default=Priority.medium)
    difficulty: Mapped[TaskDifficulty | None] = mapped_column(SAEnum(TaskDifficulty), default=None)
    responsible_party: Mapped[TaskResponsibleParty] = mapped_column(
        SAEnum(TaskResponsibleParty), default=TaskResponsibleParty.client)
    impact_score: Mapped[int | None] = mapped_column(SmallInteger, default=None)  # 0..10
    estimated_minutes: Mapped[int | None] = mapped_column(default=None)
    due_date: Mapped[date | None] = mapped_column(Date, default=None, index=True)
    completed_at: Mapped[date | None] = mapped_column(Date, default=None)
    coach_feedback: Mapped[str | None] = mapped_column(Text, default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    financial_client: Mapped[FinancialClient] = relationship(back_populates="tasks")
    coaching_session: Mapped["CoachingSession | None"] = relationship(back_populates="tasks")


class CoachingSession(Base):
    __tablename__ = "crm_coaching_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    financial_client_id: Mapped[int] = mapped_column(
        ForeignKey("crm_financial_clients.id"), index=True)

    session_number: Mapped[int]
    session_type: Mapped[SessionType | None] = mapped_column(SAEnum(SessionType), default=None)
    main_topic: Mapped[str | None] = mapped_column(default=None)
    session_date: Mapped[datetime | None] = mapped_column(DateTime, default=None, index=True)
    completed: Mapped[bool] = mapped_column(default=False)
    coach_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    financial_client: Mapped[FinancialClient] = relationship(back_populates="sessions")
    tasks: Mapped[list[FinancialTask]] = relationship(back_populates="coaching_session")


class FinancialWorkspace(Base):
    """Container 1:1 por FinancialClient com acesso habilitado ao módulo
    self-service "Financial Planning" (Fase 1 do
    SAES_Financial_Planning_Master_Spec, 2026-08-07) -- criado na hora em
    que um funcionário autorizado habilita o acesso
    (ver app/services/financial_planning_service.py::enable_access).
    Tabelas futuras (Fase 2 em diante -- accounts, financial_transactions,
    bills, debts, financial_goals etc.) apontam pra
    `financial_workspace_id`, não direto pro FinancialClient, seguindo o
    schema do documento mestre. `deleted_at` existe pro caso raro de
    precisar desfazer uma ativação por engano -- o fluxo normal de
    "parar de usar o módulo" é `status=cancelled`/`disable_access`, nunca
    apagar a linha (mesma disciplina de exclusão lógica já usada em
    app/document_storage_models.py)."""
    __tablename__ = "financial_workspaces"

    id: Mapped[int] = mapped_column(primary_key=True)
    financial_client_id: Mapped[int] = mapped_column(
        ForeignKey("crm_financial_clients.id"), unique=True, index=True)

    status: Mapped[FinancialPlanningStatus] = mapped_column(
        SAEnum(FinancialPlanningStatus), default=FinancialPlanningStatus.active)
    default_currency: Mapped[str] = mapped_column(default="USD")
    timezone: Mapped[str | None] = mapped_column(default=None)
    # Dia do mês em que o período de orçamento "vira" (Fase 4) -- 1-28
    # pra sempre existir em todo mês, mesmo fevereiro.
    budget_month_start_day: Mapped[int] = mapped_column(SmallInteger, default=1)

    # Fundo de Emergência (Fase 7) -- o documento define a fórmula
    # ("target = média de gastos Needs mensais × meses-alvo",
    # "months_covered = saldo atual / média Needs") mas NÃO define uma
    # tabela própria pra isto (só `financial_goals`/`sinking_funds`
    # existem) -- por isso vira 2 configurações aqui no workspace, não
    # uma tabela nova: quantos meses de gasto essencial o cliente quer
    # cobrir, e qual conta representa a reserva de emergência. O valor
    # (target/months_covered) é sempre CALCULADO na hora
    # (goals_service.emergency_fund_summary), nunca gravado -- se
    # recalcula sozinho conforme a média de gastos ou o saldo da conta
    # mudam, nunca fica desatualizado.
    #
    # `emergency_fund_account_id` É PROPOSITALMENTE sem `ForeignKey(...)`
    # -- `financial_accounts.financial_workspace_id` já referencia ESTA
    # tabela (`financial_workspaces`), então uma FK de volta daqui pra
    # `financial_accounts` criaria uma dependência circular entre as
    # duas tabelas (confirmado ao tentar: SQLAlchemy avisa "Cannot
    # correctly sort tables ... unresolvable cycles" e some com a
    # garantia de integridade referencial no create_all/migração).
    # Validado no service (`goals_service._check_account_ownership`)
    # antes de gravar, mesma disciplina já usada em
    # `app/crm_models.py::AuditLog.entity_type` (também sem FK, por
    # motivo parecido: referência que não pode travar o dono da tabela).
    emergency_fund_target_months: Mapped[int | None] = mapped_column(default=None)
    emergency_fund_account_id: Mapped[int | None] = mapped_column(default=None)

    country: Mapped[str | None] = mapped_column(default=None)
    # Onboarding guiado de 10 passos (item pendente do Prompt Mestre 2,
    # Fase 13 -- "Fluxo de onboarding" do documento mestre, seção 4):
    # `onboarding_current_step` é 1-10, `onboarding_completed_at` marca
    # quando o cliente terminou (ou pulou) -- ver
    # app/financial_workspace_client.py::onboarding_*. Workspaces
    # criados ANTES desta feature (2026-08-08) nascem já com
    # `onboarding_completed_at` preenchido na migração (ver
    # _backfill_financial_workspace_onboarding() em app/__init__.py) --
    # ninguém que já usa o módulo é forçado a passar pelo wizard.
    onboarding_current_step: Mapped[int] = mapped_column(SmallInteger, default=1)
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)

    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)

    financial_client: Mapped[FinancialClient] = relationship(back_populates="workspace")


class FinancialCoachingPackage(Base):
    """Pacotes de Financial Coaching (2026-08-08, pedido do usuário) --
    3 produtos fixos e distintos (Standard/Special/Semi-Annual), não
    tiers Standard/Plus de UM serviço como no catálogo de imigração
    (`app/crm_models.py::ServiceCatalog`). Deliberadamente uma tabela
    própria e separada de `ServiceCatalog`, não reaproveitada -- aquele
    catálogo é lido em vários lugares público-facing do lado de
    imigração (packages.py, payment_gate.py, seletor de serviço de
    Case) que não fazem sentido nenhum pra Financial Coaching (que não
    tem Case). Conteúdo rico (includes/excludes EN/PT/ES) fica em
    JSON próprio (`data/financial_coaching_packages/<slug>.json`,
    ver app/services/financial_coaching_packages.py), mesma separação
    preço-no-banco/conteúdo-em-JSON já usada pelos 15 "Pacotes
    Completos" de imigração."""
    __tablename__ = "crm_financial_coaching_packages"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(unique=True)
    name: Mapped[str]
    name_pt: Mapped[str]
    name_es: Mapped[str]
    price_cents: Mapped[int | None] = mapped_column(default=None)
    sessions_summary: Mapped[str | None] = mapped_column(default=None)
    sessions_summary_pt: Mapped[str | None] = mapped_column(default=None)
    sessions_summary_es: Mapped[str | None] = mapped_column(default=None)
    sort_order: Mapped[int] = mapped_column(default=0)

    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
