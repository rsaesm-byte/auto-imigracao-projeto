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

from sqlalchemy import Date, DateTime, ForeignKey, SmallInteger, Text
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


# --------------------------------------------------------------------------
# Vocabulário aberto -> lookup NOVO (só quando não existe equivalente já
# reusável em app/crm_models.py -- LeadSource/CloseLossReason/
# PaymentMethodLookup/IncomeSourceType são reusados diretamente, sem
# duplicar aqui)
# --------------------------------------------------------------------------

class FinancialGoal(Base):
    __tablename__ = "crm_financial_goals"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)


class FinancialChallenge(Base):
    __tablename__ = "crm_financial_challenges"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)


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
    progress_status: Mapped[FinancialProgressStatus] = mapped_column(
        SAEnum(FinancialProgressStatus), default=FinancialProgressStatus.not_started)
    homework_adherence: Mapped[HomeworkAdherenceLevel | None] = mapped_column(
        SAEnum(HomeworkAdherenceLevel), default=None)
    client_compliance: Mapped[ClientComplianceLevel | None] = mapped_column(
        SAEnum(ClientComplianceLevel), default=None)
    review_90day_status: Mapped[NinetyDayReviewStatus] = mapped_column(
        SAEnum(NinetyDayReviewStatus), default=NinetyDayReviewStatus.not_scheduled)
    continuity_program: Mapped[ContinuityProgram] = mapped_column(
        SAEnum(ContinuityProgram), default=ContinuityProgram.none)
    nps_score: Mapped[int | None] = mapped_column(default=None)
    # Reusa Priority (low/medium/high/urgent) em vez de um enum "Critical/
    # High/Medium/Low" próprio -- Notion mapeado: Critical == urgent aqui.
    priority_level: Mapped[Priority] = mapped_column(SAEnum(Priority), default=Priority.medium)
    current_focus_area: Mapped[FocusArea | None] = mapped_column(SAEnum(FocusArea), default=None)
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
