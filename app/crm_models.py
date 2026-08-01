"""Modelos do CRM (Fase 1 / MVP) -- Clientes, Leads, Casos, Documentos,
Pagamentos (ledger financeiro), Comunicações e Tarefas.

Reimplementação relacional do CRM que a Saes Professional Services mantém
hoje no Notion (13 bancos, 57 views). Ver
`C:\\Users\\rsaes\\.claude\\plans\\staged-frolicking-naur.md` para o
raciocínio completo de normalização. Resumo das decisões de modelagem:

- Nomes de pessoa da equipe (Responsible/Approved by/Reviewed by/Coach/
  Attendees) NUNCA são texto livre -- são sempre FK para `users.id`
  (filtrando is_staff=True na UI). Contratar/desligar alguém da equipe
  nunca precisa mexer em schema, diferente do Notion original que tinha os
  nomes hardcoded como opções de select.
- Vocabulário fechado controlado pela lógica de negócio (kanbans,
  automações) é `enum.Enum` Python, não tabela: CaseStatus, ProcessStatus,
  TaskStatus, Priority, etc. Vocabulário aberto e editável pelo negócio
  (origem de lead, canal de contato, field office) é tabela de lookup em
  `app/crm_lookups.py`.
- Campos "formula"/"rollup" do Notion (Days to Deadline, Processing Time,
  Citizenship Window, Net Worth etc.) não existem aqui como coluna --
  são calculados na leitura em `app/services/crm_service.py`. Gravar um
  valor derivado é a própria causa da dívida de dados que o CRM atual tem
  (formula "trava" o valor no momento em que foi calculada).
- `Case` é a camada de orquestração acima do que já existia no site:
  `FormSubmission`/`Payment` (app/models.py) ganham um `case_id` opcional
  (ver app/__init__.py::_ensure_case_id_column) e continuam exatamente
  como eram -- este módulo nunca os substitui.
"""
from __future__ import annotations

import enum
from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, ForeignKey, SmallInteger, Text, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------
# Vocabulário fechado (muda junto com a lógica de negócio -> enum, não tabela)
# --------------------------------------------------------------------------

class PreferredLanguage(str, enum.Enum):
    pt = "pt"
    en = "en"
    es = "es"


class MaritalStatus(str, enum.Enum):
    single = "single"
    married = "married"
    divorced = "divorced"
    widowed = "widowed"


class ClientTier(str, enum.Enum):
    a = "A"
    b = "B"
    c = "C"
    d = "D"
    e = "E"


class CredentialService(str, enum.Enum):
    uscis = "uscis"
    embassy = "embassy"


class BestContactPeriod(str, enum.Enum):
    manha = "manha"
    tarde = "tarde"
    noite = "noite"


class MonthlyIncomeRange(str, enum.Enum):
    under_5k = "under_5k"
    from_5k_10k = "from_5k_10k"
    from_10k_15k = "from_10k_15k"
    over_15k = "over_15k"


class LeadStage(str, enum.Enum):
    new = "new"
    contacted = "contacted"
    qualified = "qualified"
    not_qualified = "not_qualified"
    proposal_sent = "proposal_sent"
    negotiation = "negotiation"
    closed_won = "closed_won"
    closed_lost = "closed_lost"


class LeadQuality(str, enum.Enum):
    hot = "hot"
    warm = "warm"
    cold = "cold"


class ServiceMode(str, enum.Enum):
    """Os dois modelos de negócio da Saes (confirmado com o usuário): o
    cliente conduz o próprio processo (produto Auto-Imigração de hoje) ou a
    equipe conduz o caso do início ao fim (o que o CRM do Notion existe
    para gerenciar)."""
    self_service = "self_service"
    full_service = "full_service"


class VisaDraftType(str, enum.Enum):
    """Controla o rascunho de DS-160 (app/wizard.py, form_slug "ds160") --
    a equipe marca aqui quando o caso é de fato um pedido de visto de
    turismo/negócios (B1/B2) ou estudante (F1/F2) contratado pelo cliente;
    até marcar, o cliente não vê nem consegue abrir esse questionário
    (gate no dashboard, ver wizard.dashboard/_ds160_gate_case)."""
    b1_b2 = "b1_b2"
    f1_f2 = "f1_f2"


class CaseStatus(str, enum.Enum):
    lead_capture = "lead_capture"
    onboarding = "onboarding"
    document_collection = "document_collection"
    preparation = "preparation"
    submission = "submission"
    follow_up = "follow_up"
    approved = "approved"
    denied = "denied"
    gave_up = "gave_up"
    lost = "lost"


class ProcessStatus(str, enum.Enum):
    intake = "intake"
    documents = "documents"
    preparation = "preparation"
    review = "review"
    ready_to_submit = "ready_to_submit"
    submitted = "submitted"
    post_submission = "post_submission"
    rfe_handling = "rfe_handling"
    decision = "decision"
    done = "done"


class Priority(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    urgent = "urgent"


class ServiceRole(str, enum.Enum):
    current = "current"
    previous = "previous"


class DocumentType(str, enum.Enum):
    passport = "passport"
    visa = "visa"
    bank_statement = "bank_statement"
    i20 = "i20"
    rfe_noid = "rfe_noid"
    translation_file = "translation_file"
    address_proof = "address_proof"
    birth_certificate = "birth_certificate"
    marriage_certificate = "marriage_certificate"
    terms_and_conditions = "terms_and_conditions"
    service_contract = "service_contract"
    other = "other"


class TranslationLanguage(str, enum.Enum):
    portuguese = "portuguese"
    english = "english"
    spanish = "spanish"
    other = "other"


class TranslationStatus(str, enum.Enum):
    quoted = "quoted"
    in_progress = "in_progress"
    review = "review"
    ready = "ready"


class Currency(str, enum.Enum):
    usd = "usd"
    brl = "brl"
    other = "other"


class PaymentDirection(str, enum.Enum):
    receivable = "receivable"
    payable = "payable"


class PaymentStatus(str, enum.Enum):
    pending = "pending"
    invoice_sent = "invoice_sent"
    partially_paid = "partially_paid"
    in_dispute = "in_dispute"
    paid = "paid"
    refunded = "refunded"
    written_off = "written_off"


class CommDirection(str, enum.Enum):
    outbound = "outbound"
    inbound = "inbound"


class CommStatus(str, enum.Enum):
    not_started = "not_started"
    in_progress = "in_progress"
    done = "done"


class TaskStatus(str, enum.Enum):
    not_started = "not_started"
    waiting_translation = "waiting_translation"
    in_progress = "in_progress"
    done = "done"


class TaskType(str, enum.Enum):
    case_review = "case_review"
    documents_review = "documents_review"
    meeting_client = "meeting_client"
    meeting_internal = "meeting_internal"
    meeting_saes_team = "meeting_saes_team"
    meeting_service_providers = "meeting_service_providers"
    personal_development = "personal_development"
    regular_task = "regular_task"
    translation_review = "translation_review"


class RequestType(str, enum.Enum):
    application_review = "application_review"
    ar11_coa = "ar11_coa"
    document_request = "document_request"
    documents_review_feedback = "documents_review_feedback"
    e_request = "e_request"
    fee_payment = "fee_payment"
    follow_up_client = "follow_up_client"
    i134 = "i134"
    internal_request = "internal_request"
    internal_task_review = "internal_task_review"
    invoice_request = "invoice_request"
    jotform = "jotform"
    letter_development = "letter_development"
    meeting = "meeting"
    payment_request = "payment_request"
    photo_organization = "photo_organization"
    print_request = "print_request"
    refund_request = "refund_request"
    reminder = "reminder"
    rfe_review = "rfe_review"
    school_application = "school_application"
    service_contract_change = "service_contract_change"
    service_development = "service_development"
    submission_request = "submission_request"
    supporting_documents_review = "supporting_documents_review"
    translation_review = "translation_review"


class ApplicationType(str, enum.Enum):
    ar11 = "ar11"
    certified_translation = "certified_translation"
    certified_translation_rmv = "certified_translation_rmv"
    citizenship = "citizenship"
    cos_b2 = "cos_b2"
    cos_f1 = "cos_f1"
    cos_f2 = "cos_f2"
    e_request = "e_request"
    eos = "eos"
    gc = "gc"
    gc_roc = "gc_roc"
    i290b = "i290b"
    i824 = "i824"
    k1_visa = "k1_visa"
    noid = "noid"
    reinstatement = "reinstatement"
    rfe = "rfe"


class MailingType(str, enum.Enum):
    express = "express"
    standard = "standard"


# --------------------------------------------------------------------------
# Vocabulário aberto/editável pelo negócio -> tabela de lookup
# (app/crm_lookups.py tem os helpers de leitura; seed em app/__init__.py)
# --------------------------------------------------------------------------

class LeadSource(Base):
    __tablename__ = "crm_lead_sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)


class AdSource(Base):
    __tablename__ = "crm_ad_sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)


class ContactChannel(Base):
    __tablename__ = "crm_contact_channels"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)


class FieldOffice(Base):
    __tablename__ = "crm_field_offices"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
    address: Mapped[str | None] = mapped_column(default=None)


class FeeType(Base):
    __tablename__ = "crm_fee_types"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)


class CloseLossReason(Base):
    __tablename__ = "crm_close_loss_reasons"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)


class IncomeSourceType(Base):
    __tablename__ = "crm_income_source_types"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)


class PaymentMethodLookup(Base):
    __tablename__ = "crm_payment_methods"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)


# --------------------------------------------------------------------------
# Núcleo
# --------------------------------------------------------------------------

class Client(Base):
    """Cadastro central de cliente. `user_id` só é preenchido quando o
    cliente também tem login no site (fluxo self_service de hoje) --
    permanece NULL para um lead/cliente cadastrado só pela equipe no
    fluxo full_service, antes (ou sem nunca ter) uma conta própria."""
    __tablename__ = "crm_clients"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), unique=True, default=None, index=True)

    full_name: Mapped[str]
    email: Mapped[str | None] = mapped_column(default=None, index=True)
    us_phone: Mapped[str | None] = mapped_column(default=None)
    us_phone_has: Mapped[bool] = mapped_column(default=False)
    home_phone: Mapped[str | None] = mapped_column(default=None)
    home_phone_has: Mapped[bool] = mapped_column(default=False)
    us_address: Mapped[str | None] = mapped_column(default=None)
    home_address: Mapped[str | None] = mapped_column(default=None)
    city_country: Mapped[str | None] = mapped_column(default=None)
    country_of_origin: Mapped[str | None] = mapped_column(default=None)
    preferred_language: Mapped[PreferredLanguage | None] = mapped_column(
        SAEnum(PreferredLanguage), default=None)
    best_contact_time: Mapped[str | None] = mapped_column(default=None)

    dob: Mapped[date | None] = mapped_column(Date, default=None)
    marital_status: Mapped[MaritalStatus | None] = mapped_column(
        SAEnum(MaritalStatus), default=None)
    marriage_date: Mapped[date | None] = mapped_column(Date, default=None)
    has_dependents: Mapped[bool] = mapped_column(default=False)
    n_dependents: Mapped[int | None] = mapped_column(default=None)
    passport_expiration: Mapped[date | None] = mapped_column(Date, default=None)

    current_status_visa: Mapped[str | None] = mapped_column(default=None)
    status_expiration: Mapped[date | None] = mapped_column(Date, default=None)
    resident_since: Mapped[date | None] = mapped_column(Date, default=None)
    gc_expiration: Mapped[date | None] = mapped_column(Date, default=None)

    tier: Mapped[ClientTier | None] = mapped_column(SAEnum(ClientTier), default=None)
    # Códigos internos de identificação/segurança usados pela equipe hoje
    # (5 Letters / Key Word no Notion) -- mantidos como estavam, sem
    # inventar um uso novo pra eles.
    five_letters: Mapped[str | None] = mapped_column(default=None)
    key_word: Mapped[str | None] = mapped_column(default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    intake: Mapped["ClientIntake | None"] = relationship(
        back_populates="client", cascade="all, delete-orphan", uselist=False)
    credentials: Mapped[list["ClientCredential"]] = relationship(
        back_populates="client", cascade="all, delete-orphan")
    cases: Mapped[list["Case"]] = relationship(back_populates="client")
    documents: Mapped[list["Document"]] = relationship(back_populates="client")
    communications: Mapped[list["Communication"]] = relationship(back_populates="client")


class ClientCredential(Base):
    """Credenciais USCIS/Embaixada -- SEMPRE criptografadas
    (app/services/crypto.py), nunca em texto puro. No Notion original isso
    era um `text` comum (dívida de segurança que o próprio documento
    mapeado sinaliza). Uma linha por (client, service)."""
    __tablename__ = "crm_client_credentials"
    __table_args__ = (UniqueConstraint("client_id", "service"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("crm_clients.id"), index=True)
    service: Mapped[CredentialService] = mapped_column(SAEnum(CredentialService))
    email_encrypted: Mapped[str | None] = mapped_column(Text, default=None)
    password_encrypted: Mapped[str | None] = mapped_column(Text, default=None)
    backup_code_encrypted: Mapped[str | None] = mapped_column(Text, default=None)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None)

    client: Mapped[Client] = relationship(back_populates="credentials")


class CredentialAccessLog(Base):
    """Log de auditoria: quem decriptou qual credencial e quando. Gravado
    toda vez que a tela dedicada de credenciais (app/crm_credentials.py) exibe um
    valor decriptado -- nunca em listagens/exports gerais."""
    __tablename__ = "crm_credential_access_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    credential_id: Mapped[int] = mapped_column(ForeignKey("crm_client_credentials.id"), index=True)
    accessed_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    accessed_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class ClientIntake(Base):
    """Respostas do questionário de intake (Jotform, hoje em PT-BR) --
    1:1 com Client. Selects "sujos" do Notion (horário em texto livre,
    faixa de renda com valor solto tipo "5500,00") viram enum/número aqui.

    Não duplica `Client.marital_status`/`has_dependents`/`n_dependents` --
    o Notion original tinha "Você é casado?"/"Possui dependentes?" também
    aqui (mesmo fato capturado 2x, por 2 fluxos diferentes, sem nenhuma
    reconciliação entre eles). `Client` é a fonte única e mantida pela
    equipe ao longo do caso; estes campos de intake só existem pra dados
    que o `Client` não tem equivalente (perfil financeiro inicial, como
    chegou até a Saes)."""
    __tablename__ = "crm_client_intake"

    client_id: Mapped[int] = mapped_column(ForeignKey("crm_clients.id"), primary_key=True)
    best_contact_period: Mapped[BestContactPeriod | None] = mapped_column(
        SAEnum(BestContactPeriod), default=None)
    money_problem: Mapped[str | None] = mapped_column(Text, default=None)
    monthly_income_range: Mapped[MonthlyIncomeRange | None] = mapped_column(
        SAEnum(MonthlyIncomeRange), default=None)
    desired_solutions: Mapped[str | None] = mapped_column(Text, default=None)
    how_found_us_id: Mapped[int | None] = mapped_column(ForeignKey("crm_lead_sources.id"), default=None)
    referral_name: Mapped[str | None] = mapped_column(default=None)
    previous_service: Mapped[str | None] = mapped_column(default=None)

    client: Mapped[Client] = relationship(back_populates="intake")


class ClientIntakeIncomeSource(Base):
    """M2M: fontes de renda declaradas no intake ("1 ou mais opções" no
    Notion)."""
    __tablename__ = "crm_client_intake_income_sources"

    client_id: Mapped[int] = mapped_column(ForeignKey("crm_client_intake.client_id"), primary_key=True)
    income_source_type_id: Mapped[int] = mapped_column(
        ForeignKey("crm_income_source_types.id"), primary_key=True)


class Lead(Base):
    __tablename__ = "crm_leads"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    stage: Mapped[LeadStage] = mapped_column(SAEnum(LeadStage), default=LeadStage.new, index=True)
    quality: Mapped[LeadQuality | None] = mapped_column(SAEnum(LeadQuality), default=None)
    lead_source_id: Mapped[int | None] = mapped_column(ForeignKey("crm_lead_sources.id"), default=None, index=True)
    ad_source_id: Mapped[int | None] = mapped_column(ForeignKey("crm_ad_sources.id"), default=None)
    contact_email: Mapped[str | None] = mapped_column(default=None)
    contact_phone: Mapped[str | None] = mapped_column(default=None)
    contact_channel_id: Mapped[int | None] = mapped_column(ForeignKey("crm_contact_channels.id"), default=None)
    deal_value_cents: Mapped[int | None] = mapped_column(default=None)
    first_contact_at: Mapped[date | None] = mapped_column(Date, default=None)
    proposal_at: Mapped[date | None] = mapped_column(Date, default=None)
    closed_at: Mapped[date | None] = mapped_column(Date, default=None)
    assigned_to_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None, index=True)
    close_loss_reason_id: Mapped[int | None] = mapped_column(ForeignKey("crm_close_loss_reasons.id"), default=None)
    # Preenchido quando o lead vira cliente de fato -- é a "conversão" que
    # no Notion era a relação Cases Pipeline; aqui aponta direto pro
    # Client resultante (o Case nasce a partir daqui, ver crm_service).
    converted_client_id: Mapped[int | None] = mapped_column(ForeignKey("crm_clients.id"), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    cases: Mapped[list["Case"]] = relationship(back_populates="lead")


class LeadInterestedService(Base):
    __tablename__ = "crm_lead_interested_services"

    lead_id: Mapped[int] = mapped_column(ForeignKey("crm_leads.id"), primary_key=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("crm_services_catalog.id"), primary_key=True)


class ServiceCatalog(Base):
    """Catálogo mestre de serviços -- funde `Services Catalog` e `Services`
    do Notion (as duas tinham nome/descrição/preço/payment-plans/tipo de
    documento quase idênticos; a diferença real ["é catálogo" vs "é linha
    contratada"] já é o papel de `CaseService`, não precisa de 2 tabelas)."""
    __tablename__ = "crm_services_catalog"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    base_price_cents: Mapped[int | None] = mapped_column(default=None)
    document_type: Mapped[DocumentType | None] = mapped_column(SAEnum(DocumentType), default=None)

    payment_plans: Mapped[list["ServicePaymentPlan"]] = relationship(
        back_populates="service", cascade="all, delete-orphan")


class ServicePaymentPlan(Base):
    """Parcelamento aceito para o serviço -- só o nº de parcelas.
    O valor de cada parcela é sempre `base_price_cents / installments`,
    calculado (ver crm_service.py), nunca guardado como texto canônico tipo
    "1x $2000" (era assim no Notion, duplicava o preço em outro formato)."""
    __tablename__ = "crm_service_payment_plans"
    __table_args__ = (UniqueConstraint("service_id", "installments"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("crm_services_catalog.id"), index=True)
    installments: Mapped[int] = mapped_column(SmallInteger)

    service: Mapped[ServiceCatalog] = relationship(back_populates="payment_plans")


class Case(Base):
    """Hub central -- um caso/processo imigratório. `service_mode` marca se
    é um cliente self_service (conduz o próprio processo, produto
    Auto-Imigração de hoje) ou full_service (a equipe conduz do início ao
    fim). `FormSubmission`/`Payment` (app/models.py) linkam aqui via
    `case_id` opcional -- nenhum dos dois é duplicado ou substituído."""
    __tablename__ = "crm_cases"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("crm_clients.id"), index=True)
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("crm_leads.id"), default=None, index=True)

    title: Mapped[str]
    service_mode: Mapped[ServiceMode] = mapped_column(SAEnum(ServiceMode), index=True)
    case_status: Mapped[CaseStatus] = mapped_column(
        SAEnum(CaseStatus), default=CaseStatus.lead_capture, index=True)
    process_status: Mapped[ProcessStatus] = mapped_column(
        SAEnum(ProcessStatus), default=ProcessStatus.intake, index=True)
    priority: Mapped[Priority] = mapped_column(SAEnum(Priority), default=Priority.medium)
    # "Go to Next Step" do Notion (Can the next step be done?) -- gate
    # manual que o responsável liga quando o caso está pronto para avançar.
    ready_for_next_step: Mapped[bool] = mapped_column(default=False)
    # Gate do rascunho de DS-160 (ver VisaDraftType acima) -- None até a
    # equipe marcar; enquanto None, o cliente não vê o questionário no
    # dashboard nem consegue abrir /forms/ds160/start (app/wizard.py).
    ds160_visa_type: Mapped[VisaDraftType | None] = mapped_column(SAEnum(VisaDraftType), default=None)

    responsible_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None, index=True)
    field_office_id: Mapped[int | None] = mapped_column(ForeignKey("crm_field_offices.id"), default=None)

    receipt_number: Mapped[str | None] = mapped_column(default=None)
    receipt_date: Mapped[date | None] = mapped_column(Date, default=None)
    submission_date: Mapped[date | None] = mapped_column(Date, default=None)
    approval_date: Mapped[date | None] = mapped_column(Date, default=None)
    denial_reason: Mapped[str | None] = mapped_column(Text, default=None)
    service_deadline: Mapped[date | None] = mapped_column(Date, default=None, index=True)
    status_expire_on: Mapped[date | None] = mapped_column(Date, default=None)
    monitoring_started_at: Mapped[date | None] = mapped_column(Date, default=None)
    next_check_at: Mapped[date | None] = mapped_column(Date, default=None)
    last_checked_at: Mapped[date | None] = mapped_column(Date, default=None)
    rfe_received: Mapped[bool] = mapped_column(default=False)
    contract_signed: Mapped[bool] = mapped_column(default=False)
    terms_accepted: Mapped[bool] = mapped_column(default=False)
    google_drive_url: Mapped[str | None] = mapped_column(default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    client: Mapped[Client] = relationship(back_populates="cases")
    lead: Mapped[Lead | None] = relationship(back_populates="cases")
    services: Mapped[list["CaseService"]] = relationship(back_populates="case", cascade="all, delete-orphan")
    documents: Mapped[list["Document"]] = relationship(back_populates="case")
    step_log: Mapped[list["CaseStepLog"]] = relationship(
        back_populates="case", cascade="all, delete-orphan", order_by="CaseStepLog.done_at")
    payments: Mapped[list["PaymentLedgerEntry"]] = relationship(back_populates="case")
    communications: Mapped[list["Communication"]] = relationship(back_populates="case")
    tasks: Mapped[list["Task"]] = relationship(back_populates="case")


class CaseService(Base):
    __tablename__ = "crm_case_services"
    __table_args__ = (UniqueConstraint("case_id", "service_id", "role"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("crm_cases.id"), index=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("crm_services_catalog.id"), index=True)
    role: Mapped[ServiceRole] = mapped_column(SAEnum(ServiceRole), default=ServiceRole.current)

    case: Mapped[Case] = relationship(back_populates="services")
    service: Mapped[ServiceCatalog] = relationship()


class CaseStepLog(Base):
    """Histórico append-only dos passos do caso -- substitui o
    `Current Step` multi-select do Notion (~45 valores possíveis, mas só
    guardava o estado atual, sem histórico de quando cada passo foi feito).
    `step_name` é texto livre de propósito: a lista de passos operacionais
    muda com frequência conforme o processo evolui, não é vocabulário
    fixo do produto como CaseStatus/ProcessStatus."""
    __tablename__ = "crm_case_step_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("crm_cases.id"), index=True)
    step_name: Mapped[str]
    done_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    case: Mapped[Case] = relationship(back_populates="step_log")


class Document(Base):
    __tablename__ = "crm_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("crm_cases.id"), index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("crm_clients.id"), index=True)

    name: Mapped[str]
    document_type: Mapped[DocumentType] = mapped_column(SAEnum(DocumentType), default=DocumentType.other)
    translation_language: Mapped[TranslationLanguage | None] = mapped_column(
        SAEnum(TranslationLanguage), default=None)
    progress: Mapped[int] = mapped_column(SmallInteger, default=0)  # 0..10, checado em crm_service
    requested_at: Mapped[date | None] = mapped_column(Date, default=None)
    received_at: Mapped[date | None] = mapped_column(Date, default=None)
    file_path: Mapped[str | None] = mapped_column(default=None)
    gdrive_url: Mapped[str | None] = mapped_column(default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    case: Mapped[Case] = relationship(back_populates="documents")
    client: Mapped[Client] = relationship(back_populates="documents")
    translation: Mapped["DocumentTranslation | None"] = relationship(
        back_populates="document", cascade="all, delete-orphan", uselist=False)


class DocumentTranslation(Base):
    """Extensão 1:1 de Document -- só existe para documentos que precisam
    de tradução. Substitui o banco externo "Translations/Review Tracker"
    do Notion (inacessível pelo conector, referenciado só via rollup)."""
    __tablename__ = "crm_document_translations"

    document_id: Mapped[int] = mapped_column(ForeignKey("crm_documents.id"), primary_key=True)
    translator_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None, index=True)
    status: Mapped[TranslationStatus] = mapped_column(SAEnum(TranslationStatus), default=TranslationStatus.quoted)
    deadline: Mapped[date | None] = mapped_column(Date, default=None)

    document: Mapped[Document] = relationship(back_populates="translation")


class PaymentLedgerEntry(Base):
    """Ledger financeiro completo (a receber + a pagar) -- diferente do
    `Payment` em app/models.py, que é só o gate de checkout (comprovante ->
    aprovação) do próprio site. `gate_payment_id` linka as duas quando é a
    mesma transação, pra nunca contar a mesma cobrança 2x nos relatórios.

    Reusado também pelo módulo de Coaching Financeiro (Fase 2,
    app/crm_financial_models.py::FinancialClient) via `financial_client_id`
    -- em vez de duplicar o conceito de "Payments" uma vez por linha de
    negócio (era assim no Notion original). Exatamente um entre
    `client_id`/`financial_client_id` deve estar preenchido -- verificado
    na camada de aplicação (app/services/crm_service.py,
    app/services/crm_financial_service.py), não como CHECK constraint no
    banco, para ficar consistente com o resto deste projeto (nenhuma outra
    invariante entre colunas é forçada por CHECK aqui)."""
    __tablename__ = "crm_payments_ledger"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int | None] = mapped_column(ForeignKey("crm_cases.id"), default=None, index=True)
    client_id: Mapped[int | None] = mapped_column(ForeignKey("crm_clients.id"), default=None, index=True)
    financial_client_id: Mapped[int | None] = mapped_column(
        ForeignKey("crm_financial_clients.id"), default=None, index=True)
    gate_payment_id: Mapped[int | None] = mapped_column(ForeignKey("payments.id"), default=None, unique=True)

    description: Mapped[str]
    amount_cents: Mapped[int]
    currency: Mapped[Currency] = mapped_column(SAEnum(Currency), default=Currency.usd)
    direction: Mapped[PaymentDirection] = mapped_column(SAEnum(PaymentDirection), index=True)
    status: Mapped[PaymentStatus] = mapped_column(SAEnum(PaymentStatus), default=PaymentStatus.pending, index=True)
    payment_method_id: Mapped[int | None] = mapped_column(ForeignKey("crm_payment_methods.id"), default=None)
    package_id: Mapped[int | None] = mapped_column(ForeignKey("crm_services_catalog.id"), default=None)

    invoice_date: Mapped[date | None] = mapped_column(Date, default=None)
    due_date: Mapped[date | None] = mapped_column(Date, default=None, index=True)
    payment_date: Mapped[date | None] = mapped_column(Date, default=None, index=True)
    approved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None)
    reviewed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None)
    discount_cents: Mapped[int | None] = mapped_column(default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    case: Mapped[Case | None] = relationship(back_populates="payments")
    fee_types: Mapped[list["PaymentLedgerFeeType"]] = relationship(
        back_populates="payment", cascade="all, delete-orphan")


class PaymentLedgerFeeType(Base):
    __tablename__ = "crm_payment_ledger_fee_types"

    payment_id: Mapped[int] = mapped_column(ForeignKey("crm_payments_ledger.id"), primary_key=True)
    fee_type_id: Mapped[int] = mapped_column(ForeignKey("crm_fee_types.id"), primary_key=True)

    payment: Mapped[PaymentLedgerEntry] = relationship(back_populates="fee_types")


class Communication(Base):
    __tablename__ = "crm_communications"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("crm_clients.id"), index=True)
    case_id: Mapped[int | None] = mapped_column(ForeignKey("crm_cases.id"), default=None, index=True)

    subject: Mapped[str]
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    direction: Mapped[CommDirection] = mapped_column(SAEnum(CommDirection))
    channel_id: Mapped[int | None] = mapped_column(ForeignKey("crm_contact_channels.id"), default=None)
    status: Mapped[CommStatus] = mapped_column(SAEnum(CommStatus), default=CommStatus.not_started)
    next_followup_at: Mapped[date | None] = mapped_column(Date, default=None, index=True)
    notify_client: Mapped[bool] = mapped_column(default=False)
    summary: Mapped[str | None] = mapped_column(Text, default=None)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    client: Mapped[Client] = relationship(back_populates="communications")
    case: Mapped[Case | None] = relationship(back_populates="communications")


class Task(Base):
    __tablename__ = "crm_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int | None] = mapped_column(ForeignKey("crm_cases.id"), default=None, index=True)
    title: Mapped[str]

    status: Mapped[TaskStatus] = mapped_column(SAEnum(TaskStatus), default=TaskStatus.not_started, index=True)
    priority: Mapped[Priority] = mapped_column(SAEnum(Priority), default=Priority.medium)
    pct_done: Mapped[int] = mapped_column(SmallInteger, default=0)  # 0..100
    task_type: Mapped[TaskType | None] = mapped_column(SAEnum(TaskType), default=None)
    request_type: Mapped[RequestType | None] = mapped_column(SAEnum(RequestType), default=None)
    application_type: Mapped[ApplicationType | None] = mapped_column(SAEnum(ApplicationType), default=None)
    mailing_type: Mapped[MailingType | None] = mapped_column(SAEnum(MailingType), default=None)

    responsible_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None, index=True)
    requested_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None)

    due_date: Mapped[date | None] = mapped_column(Date, default=None, index=True)
    meeting_date: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    submission_date: Mapped[date | None] = mapped_column(Date, default=None)
    expected_delivery_date: Mapped[date | None] = mapped_column(Date, default=None)
    received_date: Mapped[date | None] = mapped_column(Date, default=None)

    notes: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    case: Mapped[Case | None] = relationship(back_populates="tasks")
    attendees: Mapped[list["TaskAttendee"]] = relationship(back_populates="task", cascade="all, delete-orphan")


class TaskAttendee(Base):
    __tablename__ = "crm_task_attendees"

    task_id: Mapped[int] = mapped_column(ForeignKey("crm_tasks.id"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)

    task: Mapped[Task] = relationship(back_populates="attendees")
