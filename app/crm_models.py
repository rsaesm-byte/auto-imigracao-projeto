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

from app.db import Base, VersionedMixin


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


class LeadTier(str, enum.Enum):
    """Classificação manual de 1 a 5 estrelas (pedido do usuário,
    2026-08-02: "⭐, ⭐⭐, ⭐⭐⭐, ⭐⭐⭐⭐, ⭐⭐⭐⭐⭐") -- deliberadamente um campo
    à parte de `LeadQuality` (hot/warm/cold, já existente e usado no
    formulário de criação rápida): são duas escalas diferentes que o
    negócio pediu para conviver, não uma substituição uma da outra."""
    star_1 = "star_1"
    star_2 = "star_2"
    star_3 = "star_3"
    star_4 = "star_4"
    star_5 = "star_5"


class ServiceMode(str, enum.Enum):
    """Os modelos de negócio da Saes (confirmado com o usuário, 2026-08-01):
    o cliente conduz o próprio processo (produto Auto-Imigração "Faça Você
    Mesmo") ou a equipe conduz o caso do início ao fim -- nesse caso, em um
    de dois níveis de atendimento ("Pacotes Completos"): Saes Standard ou
    Saes Plus (acompanhamento até aprovação, RFE/AR-11/E-Request/ligações
    à USCIS sem custo adicional, impressão e envio inclusos). Standard e
    Plus cobrem os mesmos serviços do catálogo -- a diferença é nível de
    atendimento do caso, não uma lista de serviços diferente."""
    self_service = "self_service"
    saes_standard = "saes_standard"
    saes_plus = "saes_plus"


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


class FilingMethod(str, enum.Enum):
    paper = "paper"
    online = "online"


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
    """Superseded by `DocumentStatus` below (user request 2026-08-02: one
    unified status vocabulary per document, covering translation states
    too) -- kept defined only so any historical `DocumentTranslation.status`
    value already in the database still deserializes; no longer written by
    any route."""
    quoted = "quoted"
    in_progress = "in_progress"
    review = "review"
    ready = "ready"


class DocumentStatus(str, enum.Enum):
    """Unified per-document status -- replaces the old 0..10 `progress`
    slider (kept as a column for backward compatibility, just unused by
    any current UI) and the separate translation-only `TranslationStatus`
    above. Covers both plain documents and documents that need
    translation, since from the client's point of view it's the same
    single status line. User request 2026-08-02."""
    pending = "pending"
    in_review = "in_review"
    awaiting_document = "awaiting_document"
    additional_info_needed = "additional_info_needed"
    translation_quote_requested = "translation_quote_requested"
    awaiting_translation = "awaiting_translation"
    reviewing_translation = "reviewing_translation"
    completed = "completed"


class TranslationSpeedTier(str, enum.Enum):
    """Client-facing pricing tier for a translation job -- decoupled from
    whatever the Saes pays the translator (see DocumentTranslation below).
    Prices themselves live in app/services/crm_service.py::
    TRANSLATION_SPEED_PRICING, not here (this enum is just the vocabulary;
    the $ amount is business logic that can change without a migration)."""
    rush = "rush"
    standard = "standard"


class ClientApprovalStatus(str, enum.Enum):
    """Cliente pode Aprovar/Solicitar alteração/Recusar um orçamento de
    tradução já cotado (staff preencheu speed_tier + page_count) -- pedido
    do Prompt Mestre (Fase 7), implementado 2026-08-06. Independente de
    DocumentStatus/pipeline: aprovar o orçamento não move o documento
    sozinho no kanban, é só o cliente confirmando o preço (o staff decide
    quando avançar o estágio, vendo esse status)."""
    pending = "pending"
    approved = "approved"
    changes_requested = "changes_requested"
    rejected = "rejected"


class ProgressCategory(str, enum.Enum):
    """What kind of work item a CaseProgressItem ("Acompanhamento") tracks
    -- user request 2026-08-02: "formulários, cartas, organização dos
    documentos de suporte, solicitações internas etc."."""
    form = "form"
    letter = "letter"
    document_organization = "document_organization"
    internal_request = "internal_request"
    other = "other"


class ProgressStatus(str, enum.Enum):
    """Status vocabulary for CaseProgressItem -- deliberately its own enum,
    not reusing TaskStatus (that one is for the staff-only Task model,
    different vocabulary and never client-visible). User request
    2026-08-02, exact 6 values requested."""
    not_started = "not_started"
    in_progress = "in_progress"
    awaiting_document_or_info = "awaiting_document_or_info"
    in_review = "in_review"
    ready_to_finalize = "ready_to_finalize"
    completed = "completed"


class ContractDocumentType(str, enum.Enum):
    """Which document a CaseContract signature request is for -- the
    service contract itself (tied to a specific ServiceCatalog "Pacote
    Completo" + tier) or the general Terms & Conditions (no service tie,
    signed once). User request 2026-08-02."""
    service_contract = "service_contract"
    terms_and_conditions = "terms_and_conditions"


class ContractTier(str, enum.Enum):
    """Which priced tier this contract quotes -- mirrors the 3
    independent price points ServiceCatalog now has (see its docstring),
    since Plus itself splits into Online/Paper pricing in the real
    contracts."""
    standard = "standard"
    plus_online = "plus_online"
    plus_paper = "plus_paper"


class ContractStatus(str, enum.Enum):
    """Lifecycle of a contract signature request -- exact 4 values
    requested by the user 2026-08-02 ("não começado, em análise (quando o
    cliente abriu mas não assinou), assinado ou rejeitado")."""
    not_started = "not_started"
    in_review = "in_review"
    signed = "signed"
    rejected = "rejected"


class Currency(str, enum.Enum):
    usd = "usd"
    brl = "brl"
    cop = "cop"
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
    """`sort_order`/`deleted_at` (2026-08-07, pedido do usuário) --
    checkbox editável pelo painel na ficha do cliente de coaching
    (reordenar/renomear/adicionar/apagar). Apagar é sempre exclusão
    lógica, mesma disciplina de `FinancialGoal`/`FinancialChallenge`
    (app/crm_financial_models.py)."""
    __tablename__ = "crm_income_source_types"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
    sort_order: Mapped[int] = mapped_column(default=0)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)


class PaymentMethodLookup(Base):
    __tablename__ = "crm_payment_methods"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)


# --------------------------------------------------------------------------
# Núcleo
# --------------------------------------------------------------------------

class Client(Base, VersionedMixin):
    """Cadastro central de cliente. `user_id` só é preenchido quando o
    cliente também tem login no site (fluxo self_service de hoje) --
    permanece NULL para um lead/cliente cadastrado só pela equipe no
    fluxo full_service, antes (ou sem nunca ter) uma conta própria.

    `VersionedMixin` (app/db.py): detecção de edição simultânea, hoje só
    checada por `crm_pipeline.client_update` (o formulário grande "Client
    info" -- ver app/services/concurrency_service.py). As rotas menores
    (dependentes, custom fields) ainda não checam a versão."""
    __tablename__ = "crm_clients"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), unique=True, default=None, index=True)

    full_name: Mapped[str]
    email: Mapped[str | None] = mapped_column(default=None, index=True)
    personal_email_verified: Mapped[bool] = mapped_column(default=False)
    us_phone: Mapped[str | None] = mapped_column(default=None)
    us_phone_has: Mapped[bool] = mapped_column(default=False)
    us_phone_verified: Mapped[bool] = mapped_column(default=False)
    home_phone: Mapped[str | None] = mapped_column(default=None)
    home_phone_has: Mapped[bool] = mapped_column(default=False)
    us_address: Mapped[str | None] = mapped_column(default=None)
    # Marcado manualmente pelo staff quando confirma aquele dado direto com
    # o cliente (telefone, endereço nos EUA, e-mail pessoal) -- pedido do
    # usuário 2026-08-06: um "check mark" ao lado de cada um na ficha do
    # cliente. Não reabre sozinho quando o valor muda (fica a critério do
    # staff perceber e desmarcar de novo).
    us_address_verified: Mapped[bool] = mapped_column(default=False)
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
    # five_letters/key_word (5 Letters / Key Word do Notion) viviam aqui em
    # texto puro até 2026-08-06 -- movidos e criptografados pra
    # ClientCredential.five_letters_encrypted/key_word_encrypted
    # (service=embassy), pedido do usuário: são códigos de verificação de
    # segurança usados com a Embaixada, não dado de identificação geral.

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    intake: Mapped["ClientIntake | None"] = relationship(
        back_populates="client", cascade="all, delete-orphan", uselist=False)
    credentials: Mapped[list["ClientCredential"]] = relationship(
        back_populates="client", cascade="all, delete-orphan")
    cases: Mapped[list["Case"]] = relationship(back_populates="client")
    documents: Mapped[list["Document"]] = relationship(back_populates="client")
    communications: Mapped[list["Communication"]] = relationship(back_populates="client")
    dependents: Mapped[list["ClientDependent"]] = relationship(
        back_populates="client", cascade="all, delete-orphan")


class ClientDependent(Base):
    """Dados de contato por dependente -- normaliza o que antes só existia
    como contador (`Client.has_dependents`/`n_dependents`). Preenchido pelo
    próprio cliente na tela de onboarding pós-pagamento (app/onboarding.py,
    campo telefone/e-mail por dependente) e sincronizado aqui direto
    (pedido do usuário, 2026-08-01: "atualiza Client/Case diretamente")."""
    __tablename__ = "crm_client_dependents"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("crm_clients.id"), index=True)
    full_name: Mapped[str]
    email: Mapped[str | None] = mapped_column(default=None)
    us_phone: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    client: Mapped[Client] = relationship(back_populates="dependents")


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
    # "5 Letters" / "Key Word" do Notion -- códigos de verificação de
    # segurança usados em ligações com a Embaixada, não com o USCIS.
    # Viviam como coluna de texto puro em Client (five_letters/key_word)
    # até 2026-08-06 -- movidos pra cá e criptografados a pedido do
    # usuário ("devem ir dentro de credentials em embassy"), mesmo
    # tratamento de segurança do resto desta tabela. Só usados/exibidos
    # quando service=embassy (ver app/crm_credentials.py), mas moram aqui
    # (não num par de colunas só-embassy) pra reusar a mesma estrutura
    # genérica de reveal/audit-log de qualquer outra credencial.
    five_letters_encrypted: Mapped[str | None] = mapped_column(Text, default=None)
    key_word_encrypted: Mapped[str | None] = mapped_column(Text, default=None)
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
    # "Data da Desistência" -- pedido do usuário 2026-08-02: distinto de
    # `closed_at` (que só marca um fechamento GANHO, ver
    # crm_service.convert_lead_to_client_and_case). Preenchido quando o
    # stage vira closed_lost (ver crm_staff_pipeline.lead_stage_update).
    lost_at: Mapped[date | None] = mapped_column(Date, default=None)
    # "Número de tentativas" -- contador manual de tentativas de contato,
    # incrementado/editado pelo colaborador na tela de edição do lead.
    contact_attempts: Mapped[int | None] = mapped_column(default=None)
    # "Cidade/Região" -- texto livre (não é um lookup fechado como
    # ContactChannel/LeadSource, região não é vocabulário fixo do produto).
    city_region: Mapped[str | None] = mapped_column(default=None)
    # "Melhor horário para contato" -- pedido do usuário 2026-08-06, campo
    # do formulário público de interesse inicial (ver app/lead_intake.py).
    best_contact_time: Mapped[str | None] = mapped_column(default=None)
    # Lista crua dos serviços marcados no formulário público de interesse
    # (app/lead_intake.py) -- inclui os SEM ServiceCatalog correspondente
    # (Tradução Juramentada, E-REQUEST etc., ver
    # app/services/service_interests.py), que por isso não viram
    # LeadInterestedService nenhum. Campo próprio, distinto de `notes`
    # (que é anotação livre do STAFF, não o que o próprio lead preencheu).
    interest_notes: Mapped[str | None] = mapped_column(Text, default=None)
    # "Anotações" -- markdown livre, mesmo conversor hand-rolled já usado em
    # CaseTrackedForm.notes_markdown (app/services/text_format.py).
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    # "Interessado em" -- pedido do usuário 2026-08-02: distinto do serviço
    # específico (ver LeadInterestedService abaixo, "Serviço que está
    # interessado") -- este é o MODELO de atendimento que o lead está
    # considerando (fazer sozinho vs. equipe Standard/Plus), mesmo enum
    # ServiceMode já usado em Case.service_mode em todo o resto do CRM.
    interested_service_mode: Mapped[ServiceMode | None] = mapped_column(SAEnum(ServiceMode), default=None)
    # "Lead Tier" (1 a 5 estrelas) -- ver LeadTier acima.
    tier: Mapped[LeadTier | None] = mapped_column(SAEnum(LeadTier), default=None)
    # Conta de login que gerou este lead automaticamente ao selecionar um
    # pacote (ver app/packages.py) -- None para leads criados manualmente
    # pelo staff, como sempre foi até aqui. É como achamos "o lead aberto
    # deste cliente" pra não duplicar em cliques repetidos e pra promover
    # pro Case certo quando o pagamento é enviado (app/payment_gate.py).
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None, index=True)
    # Pacote "Faça Você Mesmo" (data/packages.json) que gerou este lead --
    # paralelo a LeadInterestedService abaixo, que cobre os pacotes
    # profissionais (ServiceCatalog). Os dois nunca coexistem no mesmo lead.
    interested_package_slug: Mapped[str | None] = mapped_column(default=None)
    # Preço exato (em centavos) que o cliente escolheu ao confirmar um
    # pacote profissional -- Standard/Plus/Plus-Papel resolvem pro mesmo
    # `interested_service_mode` (saes_plus cobre Plus online E Plus papel),
    # então isso é o que desambigua qual dos dois preços cobrar no checkout
    # (ver app/payment_gate.py::checkout_lead). None para leads de pacote DIY.
    selected_price_cents: Mapped[int | None] = mapped_column(default=None)
    assigned_to_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None, index=True)
    close_loss_reason_id: Mapped[int | None] = mapped_column(ForeignKey("crm_close_loss_reasons.id"), default=None)
    # Preenchido quando o lead vira cliente de fato -- é a "conversão" que
    # no Notion era a relação Cases Pipeline; aqui aponta direto pro
    # Client resultante (o Case nasce a partir daqui, ver crm_service).
    converted_client_id: Mapped[int | None] = mapped_column(ForeignKey("crm_clients.id"), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    cases: Mapped[list["Case"]] = relationship(back_populates="lead")
    follow_ups: Mapped[list["LeadFollowUp"]] = relationship(
        back_populates="lead", cascade="all, delete-orphan", order_by="LeadFollowUp.follow_up_number")


class LeadFollowUp(Base):
    """Follow-up numerado por lead -- pedido do usuário 2026-08-06, dentro
    do card do Lead: "Follow up Number, Date, Channel, Notes". Não existia
    antes (Communication já cobre comunicação por Case/Client, mas não por
    Lead ainda não convertido). `follow_up_number` é sequencial por lead
    (1, 2, 3...), calculado na criação (ver crm_staff_pipeline.py), não
    editável depois -- é só a ordem em que os follow-ups aconteceram."""
    __tablename__ = "crm_lead_follow_ups"

    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("crm_leads.id"), index=True)
    follow_up_number: Mapped[int]
    follow_up_date: Mapped[date] = mapped_column(Date, default=date.today)
    contact_channel_id: Mapped[int | None] = mapped_column(ForeignKey("crm_contact_channels.id"), default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    lead: Mapped[Lead] = relationship(back_populates="follow_ups")


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
    # Preço do nível "Saes Plus" -- pedido do usuário 2026-08-02, extraído
    # dos contratos reais em Downloads/Contratos: cada um dos 15 "Pacotes
    # Completos" tem um preço Standard (`base_price_cents`) E um preço
    # Plus distinto (geralmente maior, cobre tradução/RFE/mailing/case
    # tracking inclusos) -- um único preço não bastava, já que
    # `Case.service_mode` (ServiceMode.saes_standard/saes_plus) já
    # modelava os dois níveis como conceitos de primeira classe.
    plus_price_cents: Mapped[int | None] = mapped_column(default=None)
    # Preço "Plus" quando o processo é feito em papel/correio -- vários dos
    # 15 contratos reais cobram um valor MAIOR pro Plus em papel do que
    # pro Plus online (cobre impressão/montagem/postagem), ex.: EOS Plus
    # online $975 vs. Plus papel $1.100. Quando None, `plus_price_cents`
    # já é o único preço Plus (nem todo serviço tem essa distinção --
    # GC Consular, K-1 e alguns outros não têm "processo online" no
    # sentido de conta USCIS, então só têm um preço Plus).
    plus_price_paper_cents: Mapped[int | None] = mapped_column(default=None)
    document_type: Mapped[DocumentType | None] = mapped_column(SAEnum(DocumentType), default=None)
    # Chave estável (ex.: "eos_b2", "cos_to_f1") que liga este catálogo a um
    # template de procedimento em data/service_procedures/<slug>.json (ver
    # app/services/service_procedures.py) -- só preenchida pros 15 serviços
    # "Pacotes Completos" (Saes Standard/Plus); NULL para entradas antigas
    # sem procedimento formal ainda.
    slug: Mapped[str | None] = mapped_column(unique=True, index=True, default=None)
    # Auditoria de preço, mesmo par de colunas que ServiceFee (app/models.py)
    # já tinha -- pedido do usuário 2026-08-02: "mesma lógica" (último
    # preço praticado / data da última mudança / ajuste em massa por
    # porcentagem) também pros 15 "Pacotes Completos", que até então não
    # tinham UI de preço nenhuma (base_price_cents sempre None).
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, default=None, onupdate=_utcnow)
    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None)

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


class Case(Base, VersionedMixin):
    """Hub central -- um caso/processo imigratório. `service_mode` marca se
    é um cliente self_service (conduz o próprio processo, produto
    Auto-Imigração de hoje) ou full_service (a equipe conduz do início ao
    fim). `FormSubmission`/`Payment` (app/models.py) linkam aqui via
    `case_id` opcional -- nenhum dos dois é duplicado ou substituído.

    `VersionedMixin` (app/db.py): detecção de edição simultânea, hoje só
    checada por `crm_ops.case_details_update` (o formulário "Case
    details" -- ver app/services/concurrency_service.py). As outras
    rotas que escrevem em Case (notas, resumo, custom fields, mudança de
    status, ...) ainda não checam nem incrementam a versão -- escopo
    definido pelo usuário 2026-08-07 como só o formulário principal por
    entidade nesta primeira passada."""
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
    messages: Mapped[list["CaseMessage"]] = relationship(
        back_populates="case", cascade="all, delete-orphan", order_by="CaseMessage.created_at.desc()")
    tracked_forms: Mapped[list["CaseTrackedForm"]] = relationship(
        back_populates="case", cascade="all, delete-orphan", order_by="CaseTrackedForm.created_at")
    progress_items: Mapped[list["CaseProgressItem"]] = relationship(
        back_populates="case", cascade="all, delete-orphan", order_by="CaseProgressItem.created_at")
    contracts: Mapped[list["CaseContract"]] = relationship(
        back_populates="case", cascade="all, delete-orphan", order_by="CaseContract.created_at.desc()")


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


class CaseProgressItem(Base):
    """Client-visible task/progress tracker per case ("Acompanhamento",
    user request 2026-08-02) -- covers forms, letters, supporting-document
    organization, internal requests, etc. Deliberately separate from
    `Task` (staff-only operational scheduling -- meetings, internal
    reviews -- never shown to the client) and from `CaseStepLog` (an
    append-only "step done" audit trail with no notion of an in-progress
    state). Shown both on the client's "Meu Caso" page (read-only) and on
    the collaborator's client/case card (full CRUD)."""
    __tablename__ = "crm_case_progress_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("crm_cases.id"), index=True)

    title: Mapped[str]
    category: Mapped[ProgressCategory] = mapped_column(SAEnum(ProgressCategory), default=ProgressCategory.other)
    status: Mapped[ProgressStatus] = mapped_column(
        SAEnum(ProgressStatus), default=ProgressStatus.not_started, index=True)
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    case: Mapped[Case] = relationship(back_populates="progress_items")


class Document(Base):
    __tablename__ = "crm_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("crm_cases.id"), index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("crm_clients.id"), index=True)

    name: Mapped[str]
    document_type: Mapped[DocumentType] = mapped_column(SAEnum(DocumentType), default=DocumentType.other)
    translation_language: Mapped[TranslationLanguage | None] = mapped_column(
        SAEnum(TranslationLanguage), default=None)
    status: Mapped[DocumentStatus] = mapped_column(SAEnum(DocumentStatus), default=DocumentStatus.pending, index=True)
    progress: Mapped[int] = mapped_column(SmallInteger, default=0)  # 0..10 -- superseded by `status` above, kept as-is (no UI reads it anymore)
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


class Translator(Base):
    """Diretório próprio de tradutores terceirizados -- NÃO um `User` do
    site (tradutores não fazem login aqui). Pré-cadastrados só pelo nome
    via seed idempotente (app/__init__.py::_seed_translators, pedido do
    usuário 2026-08-02: Rodrigo, Ricardo, Helio, Lucia, Samuel Eduardo) --
    os demais campos ficam em branco até o staff completar a ficha.
    `currency` é a moeda em que ESTE tradutor é pago (peso colombiano,
    Real, etc. -- ver Currency acima), usada como padrão ao lançar uma
    nova tradução dele."""
    __tablename__ = "crm_translators"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(unique=True)
    address: Mapped[str | None] = mapped_column(default=None)
    phone: Mapped[str | None] = mapped_column(default=None)
    languages: Mapped[str | None] = mapped_column(default=None)
    payment_method: Mapped[str | None] = mapped_column(default=None)
    bank_details: Mapped[str | None] = mapped_column(Text, default=None)
    currency: Mapped[Currency] = mapped_column(SAEnum(Currency), default=Currency.usd)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    translations: Mapped[list["DocumentTranslation"]] = relationship(back_populates="translator")
    payments: Mapped[list["TranslatorPayment"]] = relationship(
        back_populates="translator", cascade="all, delete-orphan", order_by="TranslatorPayment.paid_at.desc()")


class TranslatorPayment(Base):
    """Histórico de pagamentos feitos a um tradutor -- registro manual do
    staff (não um gateway de pagamento de verdade), pedido do usuário
    2026-08-02 ("registros de pagamentos anteriores"). `document_translation_id`
    é opcional -- um pagamento pode cobrir várias traduções de uma vez,
    então não força 1:1 com um documento específico."""
    __tablename__ = "crm_translator_payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    translator_id: Mapped[int] = mapped_column(ForeignKey("crm_translators.id"), index=True)
    document_translation_id: Mapped[int | None] = mapped_column(
        ForeignKey("crm_document_translations.document_id"), default=None)

    amount_cents: Mapped[int]
    currency: Mapped[Currency] = mapped_column(SAEnum(Currency), default=Currency.usd)
    paid_at: Mapped[date] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    translator: Mapped[Translator] = relationship(back_populates="payments")


class DocumentTranslation(Base):
    """Extensão 1:1 de Document -- só existe para documentos que precisam
    de tradução. Substitui o banco externo "Translations/Review Tracker"
    do Notion (inacessível pelo conector, referenciado só via rollup).

    Dois valores monetários desacoplados de propósito (pedido do usuário
    2026-08-02): o que a Saes PAGA ao tradutor
    (`price_per_page_translator_currency_cents`, na moeda dele -- ver
    `Translator.currency`) não é o que a Saes COBRA do cliente
    (`speed_tier`, que decide o preço por página em dólar via
    app/services/crm_service.py::TRANSLATION_SPEED_PRICING -- $32/página
    em 1-2 dias úteis ou $30/página em 3-4 dias úteis). Nenhum total é
    gravado como coluna -- página × preço é sempre calculado na leitura
    (app/services/crm_service.py), mesma convenção do resto deste módulo
    (ver docstring do topo do arquivo)."""
    __tablename__ = "crm_document_translations"

    document_id: Mapped[int] = mapped_column(ForeignKey("crm_documents.id"), primary_key=True)
    translator_id: Mapped[int | None] = mapped_column(ForeignKey("crm_translators.id"), default=None, index=True)
    speed_tier: Mapped[TranslationSpeedTier | None] = mapped_column(SAEnum(TranslationSpeedTier), default=None)

    requested_at: Mapped[date | None] = mapped_column(Date, default=None)
    delivered_at: Mapped[date | None] = mapped_column(Date, default=None)
    page_count: Mapped[int | None] = mapped_column(default=None)

    price_per_page_translator_currency_cents: Mapped[int | None] = mapped_column(default=None)
    price_per_page_usd_cents: Mapped[int | None] = mapped_column(default=None)

    deadline: Mapped[date | None] = mapped_column(Date, default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    # Aprovação do cliente sobre o orçamento cotado (ver ClientApprovalStatus
    # acima) -- pedido do Prompt Mestre (Fase 7), 2026-08-06.
    client_approval_status: Mapped[ClientApprovalStatus] = mapped_column(
        SAEnum(ClientApprovalStatus), default=ClientApprovalStatus.pending)
    client_approval_note: Mapped[str | None] = mapped_column(Text, default=None)
    client_approval_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)

    document: Mapped[Document] = relationship(back_populates="translation")
    translator: Mapped[Translator | None] = relationship(back_populates="translations")


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
    # "Pacote" pedido do usuário 2026-08-06 (Accessible/Saes Standard/Saes
    # Plus) -- era `package_id` (FK morta pra ServiceCatalog, nunca usada
    # por nenhuma rota, 0 linhas reais preenchidas, ver git history) até
    # essa data. Vira enum porque é o mesmo nível de atendimento já
    # modelado em Case.service_mode/Lead.interested_service_mode em todo
    # o resto do CRM -- não é o catálogo de serviços específico.
    package: Mapped[ServiceMode | None] = mapped_column(SAEnum(ServiceMode), default=None)

    invoice_date: Mapped[date | None] = mapped_column(Date, default=None)
    due_date: Mapped[date | None] = mapped_column(Date, default=None, index=True)
    payment_date: Mapped[date | None] = mapped_column(Date, default=None, index=True)
    approved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None)
    reviewed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None)
    discount_cents: Mapped[int | None] = mapped_column(default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)  # notas gerais/desconto ("valor do desconto, etc")
    # Campos de confirmação de pagamento -- pedido do usuário 2026-08-06,
    # nenhum dos quatro existia antes. `confirmation_notes` é distinto de
    # `notes` acima de propósito (pedido explícito: "Notes para desconto"
    # separado de "Payment Additional Notes").
    confirmation_id: Mapped[str | None] = mapped_column(default=None)
    confirmation_notes: Mapped[str | None] = mapped_column(Text, default=None)
    paid_by: Mapped[str | None] = mapped_column(default=None)  # nome de quem pagou -- texto livre, não é um User/staff
    receipt_file_path: Mapped[str | None] = mapped_column(default=None)
    receipt_file_name: Mapped[str | None] = mapped_column(default=None)  # nome original do arquivo, pro download (ver app/services/payment_receipts.py)

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


class CaseMessageType(str, enum.Enum):
    message = "message"
    feedback = "feedback"
    internal_request = "internal_request"
    update = "update"
    document_request = "document_request"
    other = "other"


class CaseMessageStatus(str, enum.Enum):
    open = "open"
    in_progress = "in_progress"
    resolved = "resolved"


class CaseMessageAuthorRole(str, enum.Enum):
    client = "client"
    staff = "staff"


class CaseMessage(Base):
    """Two-way in-app communication thread on a Case, visible to BOTH the
    client ("Meu Caso") and staff (case detail, /staff/crm) -- deliberately
    a separate table from `Communication` above, which is a staff-only
    internal contact log (calls/emails made OUTSIDE the system, never
    authored by the client). User request, 2026-08-02: "uma forma interna
    de comunicação entre cliente/colaborador... para ficar tudo
    centralizado dentro do card do cliente e do serviço que está em
    andamento" -- covers messages, feedback, internal requests, status
    updates, or any pending item, each with its own type/priority/status/
    deadline/optional file attachment. `author_role` records who wrote it
    (client vs. staff) since either side can start a thread entry here."""
    __tablename__ = "crm_case_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("crm_cases.id"), index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("crm_clients.id"), index=True)

    message_type: Mapped[CaseMessageType] = mapped_column(
        SAEnum(CaseMessageType), default=CaseMessageType.message)
    priority: Mapped[Priority] = mapped_column(SAEnum(Priority), default=Priority.medium)
    status: Mapped[CaseMessageStatus] = mapped_column(
        SAEnum(CaseMessageStatus), default=CaseMessageStatus.open, index=True)
    due_at: Mapped[date | None] = mapped_column(Date, default=None)

    body: Mapped[str] = mapped_column(Text)
    attachment_path: Mapped[str | None] = mapped_column(default=None)
    attachment_name: Mapped[str | None] = mapped_column(default=None)

    author_role: Mapped[CaseMessageAuthorRole] = mapped_column(SAEnum(CaseMessageAuthorRole))
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    case: Mapped[Case] = relationship(back_populates="messages")
    client: Mapped[Client] = relationship()


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
    # Recorrência (Prompt Mestre, Seção 11), 2026-08-06 -- de propósito o
    # jeito mais simples possível: "repete a cada N dias", sem cron
    # nenhum. Quando uma tarefa com isto preenchido é marcada `done`
    # (ver crm_staff_ops.py::task_update_status), a PRÓXIMA ocorrência é
    # criada na hora, disparada pelo próprio evento -- não por um
    # scheduler rodando em segundo plano (mesma decisão consciente de
    # não adicionar infraestrutura de cron só pra isso, ver Automations).
    recurrence_interval_days: Mapped[int | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    case: Mapped[Case | None] = relationship(back_populates="tasks")
    attendees: Mapped[list["TaskAttendee"]] = relationship(back_populates="task", cascade="all, delete-orphan")
    checklist_items: Mapped[list["TaskChecklistItem"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="TaskChecklistItem.position")
    comments: Mapped[list["TaskComment"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="TaskComment.created_at")


class TaskAttendee(Base):
    __tablename__ = "crm_task_attendees"

    task_id: Mapped[int] = mapped_column(ForeignKey("crm_tasks.id"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)

    task: Mapped[Task] = relationship(back_populates="attendees")


class TaskChecklistItem(Base):
    """Subtarefa/item de checklist dentro de uma Task -- pedido do Prompt
    Mestre (Seção 11, "subtarefas, checklists... por tarefa"), 2026-08-06.
    Deliberadamente simples (só título + feito/não feito + posição) --
    não é uma segunda Task recursiva, é só um passo dentro de uma."""
    __tablename__ = "crm_task_checklist_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("crm_tasks.id"), index=True)
    title: Mapped[str]
    done: Mapped[bool] = mapped_column(default=False)
    position: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    task: Mapped[Task] = relationship(back_populates="checklist_items")


class TaskComment(Base):
    """Thread de comentários de uma Task (Prompt Mestre, Seção 11:
    "Comentários... Anexos"), 2026-08-06. Staff-only, igual à Task em si
    (nunca visível pro cliente -- diferente de `CaseMessage`, que é a
    thread cliente/staff de um Case). Anexo opcional reusa a mesma
    infraestrutura de upload já usada em CaseMessage (ver
    app/services/case_messages.py::save_attachment -- mesma pasta,
    mesmas extensões permitidas, sem duplicar código)."""
    __tablename__ = "crm_task_comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("crm_tasks.id"), index=True)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None)
    body: Mapped[str] = mapped_column(Text)
    attachment_path: Mapped[str | None] = mapped_column(default=None)
    attachment_name: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    task: Mapped[Task] = relationship(back_populates="comments")


class CaseTrackedForm(Base):
    """One USCIS form/petition being post-filing tracked within a Case --
    deliberately its own child table, not more columns on `Case` (which
    already has receipt_number/approval_date/etc. of its own, unused by any
    UI so far, modeling a single-form case). A bundle like a Green Card
    filing needs several forms tracked side by side under ONE case (I-130,
    I-485, I-765, I-131), each with its own receipt/dates/checks -- a flat
    column can't hold 4 values, so this is 1:N off `Case` instead. New
    tab, user request 2026-08-02 ("Case tracking" inside the collaborator
    panel).

    `filing_method` decides which extra fields matter in the UI: `paper`
    filings track the physical mail (USPS tracking number, predicted vs.
    actual arrival at USCIS); `online` filings instead show the client's
    USCIS account credentials (`ClientCredential`, service=uscis, reached
    via app/crm_credentials.py -- never duplicated here, always the same
    reveal-on-click + audit-logged screen)."""
    __tablename__ = "crm_case_tracked_forms"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("crm_cases.id"), index=True)

    form_number: Mapped[str]
    application_type: Mapped[str | None] = mapped_column(default=None)
    filing_method: Mapped[FilingMethod] = mapped_column(SAEnum(FilingMethod), default=FilingMethod.online)
    field_office_id: Mapped[int | None] = mapped_column(ForeignKey("crm_field_offices.id"), default=None)

    receipt_number: Mapped[str | None] = mapped_column(default=None)
    receipt_date: Mapped[date | None] = mapped_column(Date, default=None)
    finalized_at: Mapped[date | None] = mapped_column(Date, default=None)
    monitoring_started_at: Mapped[date | None] = mapped_column(Date, default=None)
    approval_date: Mapped[date | None] = mapped_column(Date, default=None)
    rfe_received: Mapped[bool] = mapped_column(default=False)

    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    next_check_at: Mapped[date | None] = mapped_column(Date, default=None)

    # Paper filings only (left NULL for online filings -- gated in the UI
    # by `filing_method`, not enforced at the DB level, same convention as
    # the rest of this module).
    uscis_received_at: Mapped[date | None] = mapped_column(Date, default=None)
    expected_arrival_at: Mapped[date | None] = mapped_column(Date, default=None)
    actual_arrival_at: Mapped[date | None] = mapped_column(Date, default=None)
    usps_tracking_number: Mapped[str | None] = mapped_column(default=None)

    # Free-form markdown notes for this tracked form -- rendered read-only
    # via app/services/text_format.py::markdown_lite_to_html (hand-rolled,
    # same convention as scripts/generate_cartas_i539.py's own minimal
    # markdown-ish converter, to avoid a new dependency for this one field).
    notes_markdown: Mapped[str | None] = mapped_column(Text, default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    case: Mapped[Case] = relationship(back_populates="tracked_forms")
    field_office: Mapped[FieldOffice | None] = relationship()


class CaseContract(Base):
    """A contract signature request -- either the service contract for a
    specific "Pacote Completo" + tier, or the general Terms & Conditions.
    Rendered to the client in their own site language (PT/EN/ES) with
    their real contact info and the real system price for the selected
    tier filled in, captured via an on-screen signature pad (a simulated
    signature for UX/record-keeping, NOT a certified e-signature service
    like DocuSign). User request 2026-08-02: new staff "Contracts" tab,
    client-facing signing flow, auto payment request after signing.

    `status` starts `not_started` the moment staff creates the request;
    flips to `in_review` the first time the client opens the signing page
    (never flips back); ends at `signed` or `rejected`. Only one of
    `signed_at`/`rejected_at` is ever set."""
    __tablename__ = "crm_case_contracts"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("crm_cases.id"), index=True)
    document_type: Mapped[ContractDocumentType] = mapped_column(SAEnum(ContractDocumentType))
    # Só preenchido pra document_type=service_contract -- qual "Pacote
    # Completo" e qual dos 3 preços (Standard/Plus Online/Plus Paper) foi
    # cotado neste contrato. NULL pra Terms & Conditions (não tem preço).
    service_catalog_id: Mapped[int | None] = mapped_column(ForeignKey("crm_services_catalog.id"), default=None)
    tier: Mapped[ContractTier | None] = mapped_column(SAEnum(ContractTier), default=None)

    status: Mapped[ContractStatus] = mapped_column(
        SAEnum(ContractStatus), default=ContractStatus.not_started, index=True)

    requested_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    requested_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)

    signed_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    signature_image_path: Mapped[str | None] = mapped_column(default=None)
    selected_payment_method_id: Mapped[int | None] = mapped_column(ForeignKey("crm_payment_methods.id"), default=None)
    signer_ip: Mapped[str | None] = mapped_column(default=None)

    rejected_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    rejected_reason: Mapped[str | None] = mapped_column(Text, default=None)

    # Preenchido quando a assinatura dispara automaticamente uma
    # solicitação de pagamento (ver app/services/crm_service.py) -- link
    # pro lançamento criado, pra nunca criar 2 solicitações da mesma
    # assinatura se a rota rodar de novo por engano.
    payment_ledger_entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("crm_payments_ledger.id"), default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    case: Mapped[Case] = relationship(back_populates="contracts")
    service: Mapped[ServiceCatalog | None] = relationship()
    payment_method: Mapped[PaymentMethodLookup | None] = relationship()


class CompanyContractTerms(Base):
    """O texto dos "Termos Gerais" que aparece em TODO contrato do cliente
    (Standard/Plus de qualquer serviço, e também os Termos e Condições
    autônomos) -- singleton (sempre id=1), mesma convenção de
    `StaffNavGlobalLayout` (app/models.py). Pedido do usuário 2026-08-02:
    "visualizar os contratos de cada serviço e alterar o contrato da
    empresa por lá, exemplos termos etc, antes de disponibilizar o
    contrato para os clientes" -- antes deste modelo, este texto vivia
    fixo em app/translations/{pt,en,es}.json (contract_term_no_legal_advice/
    no_guarantee/refund/payment_separate/contract_terms_body), sem nenhuma
    tela pra editar sem mexer direto no arquivo.

    Cada campo é markdown livre (app/services/text_format.py::
    markdown_lite_to_html, mesmo conversor de CaseTrackedForm.notes_markdown),
    não mais uma lista fixa de 3-4 frases -- dá ao staff controle total do
    texto, não só permissão pra editar item por item de uma lista fechada.
    `general_terms_*` aparece em QUALQUER contrato; `payment_separate_*` só
    quando document_type=service_contract (contrato tem preço); `tc_intro_*`
    só quando document_type=terms_and_conditions -- mesma condicionalidade
    que já existia no template antes de virar editável (ver
    app/templates/meu_contrato.html)."""
    __tablename__ = "crm_company_contract_terms"

    id: Mapped[int] = mapped_column(primary_key=True)
    general_terms_en: Mapped[str] = mapped_column(Text)
    general_terms_pt: Mapped[str] = mapped_column(Text)
    general_terms_es: Mapped[str] = mapped_column(Text)
    payment_separate_en: Mapped[str] = mapped_column(Text)
    payment_separate_pt: Mapped[str] = mapped_column(Text)
    payment_separate_es: Mapped[str] = mapped_column(Text)
    tc_intro_en: Mapped[str] = mapped_column(Text)
    tc_intro_pt: Mapped[str] = mapped_column(Text)
    tc_intro_es: Mapped[str] = mapped_column(Text)

    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None)


class Notification(Base):
    """Notificação em tempo real (quase) pro painel do colaborador --
    widget estilo "Dynamic Island" (app/templates/_notification_widget.html,
    app/static/notifications.js) que consulta app/staff_notifications.py
    por polling. `kind` é texto livre de propósito (não enum): a lista de
    eventos que disparam notificação cresce com o tempo (hoje: lead_new,
    payment_submitted, document_received, message_new -- ver
    app/services/notification_service.py::notify), então travar num enum
    forçaria uma migração de schema a cada novo tipo de evento. `read_at`
    é global (compartilhado pela equipe toda, não por usuário) -- decisão
    deliberada pra não precisar de tabela de junção numa equipe pequena."""
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(index=True)
    title: Mapped[str]
    body: Mapped[str | None] = mapped_column(Text, default=None)
    url: Mapped[str | None] = mapped_column(default=None)
    # None (padrão) = aviso pra equipe toda, comportamento original acima.
    # Preenchido = privado para ESSE usuário (pedido do usuário 2026-08-06:
    # cliente recebe notificação -- ex. tradução disponível -- no mesmo
    # widget da equipe, mas só ele pode ver/ler a dele). app/staff_notifications.py
    # e o novo app/client_notifications.py filtram cada um pro seu escopo
    # (staff: recipient_user_id IS NULL; cliente: == current_user.id) --
    # nunca vazam entre si.
    recipient_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), default=None, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)


class AuditSource(str, enum.Enum):
    manual = "manual"
    automatic = "automatic"
    integration = "integration"


class AuditLog(Base):
    """Histórico/auditoria genérico por registro (reforma do CRM, Fase 0 --
    ver pedido do usuário seção 11 "Histórico e Auditoria"). Uma linha por
    mudança de campo (ou por ação sem campo específico, ex.: criação,
    exclusão, mudança de etapa do kanban, comentário, upload).

    Deliberadamente separado de `Notification` (que é sobre avisar alguém
    agora) e de `CaseStepLog`/`CredentialAccessLog` (que são históricos
    especializados de um fluxo específico, e continuam existindo como
    estão) -- este é o log cross-entidade genérico que faltava (ver
    auditoria da Fase 1 da reforma: só existiam os dois casos pontuais
    acima).

    `entity_type` é o nome da classe do modelo (ex.: "Lead", "Case",
    "Client") como string, não FK -- um log de auditoria precisa
    sobreviver mesmo que o registro referenciado seja excluído
    (exclusão lógica é o padrão preferido, mas nem toda tabela tem isso
    ainda). `field=None` representa uma ação sobre o registro inteiro
    (criação, exclusão, mudança de etapa) em vez de um campo específico;
    nesse caso `description` carrega o resumo legível (ex.: "moveu de
    Novo para Qualificado"). `user_id` é nulo quando a mudança veio de
    uma automação sem usuário associado (`source=automatic`).

    Escrita apenas -- nenhuma rota edita ou apaga uma linha de AuditLog.
    `services/audit_service.py::log_change()` nunca chama commit() (mesma
    convenção do resto de app/services/): quem chama decide."""
    __tablename__ = "crm_audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(index=True)
    entity_id: Mapped[int] = mapped_column(index=True)
    action: Mapped[str] = mapped_column(index=True)
    field: Mapped[str | None] = mapped_column(default=None)
    old_value: Mapped[str | None] = mapped_column(Text, default=None)
    new_value: Mapped[str | None] = mapped_column(Text, default=None)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    source: Mapped[AuditSource] = mapped_column(SAEnum(AuditSource), default=AuditSource.manual)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)


class CustomFieldType(str, enum.Enum):
    """Prompt Mestre, Fase 5 ("Tipos de propriedades") -- subconjunto dos
    23 tipos listados no documento. De propósito: só os que dá pra
    implementar bem com um único `value_text` (ver CustomFieldValue) sem
    precisar de infraestrutura nova (upload de arquivo, motor de fórmula,
    relação com outra tabela) -- esses ficam fora desta primeira versão."""
    short_text = "short_text"
    long_text = "long_text"
    number = "number"
    currency = "currency"
    percent = "percent"
    date = "date"
    checkbox = "checkbox"
    single_select = "single_select"
    multi_select = "multi_select"


class CustomFieldDefinition(Base):
    """Campo personalizado definido pelo staff (Prompt Mestre, Fase 5),
    2026-08-06 -- "criar uma área administrativa para gerenciar
    propriedades dos bancos de dados". `entity_type` é texto livre (mesma
    convenção do AuditLog acima) -- hoje só "Case" tem UI ligada, mas o
    modelo já é genérico o bastante pra outras entidades no futuro sem
    migração nova. `key` é o identificador interno estável (nunca muda
    depois de criado, mesmo se `label` for renomeado) -- é o que
    `CustomFieldValue.field_id` referencia via FK, então não precisa
    duplicar aqui; existe como coluna própria só pra facilitar achar o
    campo certo por código/relatório futuro sem depender do id numérico.
    `options_json` só é usado por single_select/multi_select (lista de
    strings). Exclusão lógica antes da permanente (pedido explícito do
    documento): `archived=True` primeiro, exclusão de verdade só depois
    (ver crm_custom_fields.py::field_delete, que recusa apagar sem estar
    arquivado)."""
    __tablename__ = "crm_custom_field_definitions"
    __table_args__ = (UniqueConstraint("entity_type", "key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(index=True)
    key: Mapped[str]
    label: Mapped[str]
    field_type: Mapped[CustomFieldType] = mapped_column(SAEnum(CustomFieldType))
    required: Mapped[bool] = mapped_column(default=False)
    default_value: Mapped[str | None] = mapped_column(Text, default=None)
    options_json: Mapped[str | None] = mapped_column(Text, default=None)
    client_visible: Mapped[bool] = mapped_column(default=False)
    archived: Mapped[bool] = mapped_column(default=False, index=True)
    position: Mapped[int] = mapped_column(default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None)


class CustomFieldValue(Base):
    """Valor de um campo personalizado pra um registro específico --
    padrão EAV (entity-attribute-value) de propósito: cada `CaseStatus`/
    `Client`/etc. real continua sem nenhuma coluna nova no banco por campo
    criado -- criar/apagar um campo personalizado nunca é uma migração.
    `entity_id` aponta pro registro (hoje só `Case.id`, mesma convenção de
    `entity_type` do AuditLog -- não é FK de verdade de propósito, pra não
    prender este model a uma tabela só). Sempre texto (`value_text`) --
    number/currency/percent/date guardam a representação em string e são
    convertidos na leitura (app/services/custom_fields_service.py), multi_select
    guarda um JSON de lista; nunca uma coluna tipada por tipo (impediria um
    campo mudar de tipo sem migração, o oposto do que essa feature promete)."""
    __tablename__ = "crm_custom_field_values"
    __table_args__ = (UniqueConstraint("field_id", "entity_type", "entity_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    field_id: Mapped[int] = mapped_column(ForeignKey("crm_custom_field_definitions.id"), index=True)
    entity_type: Mapped[str] = mapped_column(index=True)
    entity_id: Mapped[int] = mapped_column(index=True)
    value_text: Mapped[str | None] = mapped_column(Text, default=None)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    field: Mapped[CustomFieldDefinition] = relationship()


class AutomationTriggerField(str, enum.Enum):
    """Qual data do Case o gatilho observa -- subconjunto dos "eventos do
    ciclo" citados no Prompt Mestre (Seção 7), os 4 mais acionáveis:
    prazo do serviço contratado, vencimento do status atual (ex.: EAD),
    data de aprovação, data de submissão."""
    service_deadline = "service_deadline"
    status_expire_on = "status_expire_on"
    approval_date = "approval_date"
    submission_date = "submission_date"


class AutomationActionType(str, enum.Enum):
    """As 2 ações da lista "Automações possíveis" do documento que dão
    pra fazer sem infraestrutura nova (sem envio de e-mail em massa, sem
    sistema de campanha/segmento) -- ver docstring de AutomationRule."""
    create_task = "create_task"
    notify_responsible = "notify_responsible"


class AutomationRunStatus(str, enum.Enum):
    success = "success"
    error = "error"


class AutomationRule(Base):
    """Regra de automação de ciclo de vida (Prompt Mestre, Seção 7:
    "acompanhamento pós-venda baseado no ciclo de cada serviço... não
    deixar prazos legais fixos diretamente no código, criar modelos
    configuráveis"), 2026-08-06. Escopo reduzido de propósito frente ao
    documento inteiro (que pede templates de e-mail, segmentos de
    marketing, sugestão de próximo serviço -- nenhum desses tem
    infraestrutura no projeto ainda): aqui só "dispare uma ação X dias
    antes/depois de uma data do caso", com 2 ações possíveis.

    `offset_days` negativo = X dias ANTES de `trigger_field`; positivo =
    X dias DEPOIS. `service_catalog_id=None` -- regra vale pra qualquer
    Case; preenchido -- só pros casos com esse serviço como atual
    (CaseService.role=current). `action_text` é o título da tarefa ou da
    notificação -- aceita o placeholder literal "{case}" (substituído
    pelo título do Case na hora de disparar, ver automation_service.py).

    "Interromper quando o cliente já tiver contratado o próximo serviço"
    (pedido do documento) é tratado de forma simples: a regra só
    considera casos com `case_status` numa lista de status "ativos" (não
    approved/denied/gave_up/lost) -- ver `_ACTIVE_STATUSES` em
    automation_service.py."""
    __tablename__ = "crm_automation_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    service_catalog_id: Mapped[int | None] = mapped_column(ForeignKey("crm_services_catalog.id"), default=None)
    trigger_field: Mapped[AutomationTriggerField] = mapped_column(SAEnum(AutomationTriggerField))
    offset_days: Mapped[int] = mapped_column(default=0)
    action_type: Mapped[AutomationActionType] = mapped_column(SAEnum(AutomationActionType))
    action_text: Mapped[str]
    active: Mapped[bool] = mapped_column(default=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None)

    service: Mapped["ServiceCatalog | None"] = relationship()
    runs: Mapped[list["AutomationRun"]] = relationship(
        back_populates="rule", cascade="all, delete-orphan", order_by="AutomationRun.executed_at.desc()")


class AutomationRun(Base):
    """Histórico de execução (pedido explícito do documento: "Toda
    automação deve possuir: Histórico; Status; Data da execução;
    Resultado; Erros"). Uma linha por (regra, caso) que de fato disparou
    -- `status=success` aqui é o que impede a regra de disparar de novo
    pro mesmo caso (ver automation_service.py::_already_ran); uma linha
    `error` NÃO bloqueia nova tentativa, pra não travar a regra pra
    sempre por causa de uma falha pontual."""
    __tablename__ = "crm_automation_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("crm_automation_rules.id"), index=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("crm_cases.id"), index=True)
    executed_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    status: Mapped[AutomationRunStatus] = mapped_column(SAEnum(AutomationRunStatus))
    result_text: Mapped[str | None] = mapped_column(Text, default=None)
    error_text: Mapped[str | None] = mapped_column(Text, default=None)

    rule: Mapped[AutomationRule] = relationship(back_populates="runs")
    case: Mapped[Case] = relationship()


class PipelineStageConfig(Base):
    """Metadados administráveis por etapa de um pipeline (Fase 4 da reforma
    do CRM: "colunas visualmente identificáveis", "definir cor",
    "descrição"). Deliberadamente NÃO substitui o `enum.Enum` que cada
    pipeline usa como vocabulário fechado (CaseStatus, LeadStage,
    TaskStatus, DocumentStatus, FinancialClientStatus) -- isso exigiria
    reescrever toda a lógica de negócio, automações e gates que comparam
    contra esses enums (ex.: o gate de DS-160 em app/crm_staff_pipeline.py
    depende de `case.ds160_visa_type`, não do texto do status), risco alto
    demais pra essa fase. Esta tabela é só uma camada de personalização
    visual/documental POR CIMA do enum: uma linha aqui pode existir ou não
    para cada `(pipeline, stage_value)`; quando não existe, a UI cai de
    volta pra cor automática por posição (ver .crm-kanban-col:nth-of-type
    em app/static/style.css) e nenhuma descrição.

    `active=False` é só informativo por enquanto (mostra um aviso na tela
    de administração) -- não impede ninguém de mover um card pra essa
    etapa, porque isso exigiria validar contra esta tabela em cada uma das
    4 rotas de mudança de status, o que effectivamente tornaria esta
    tabela uma segunda fonte de verdade sobre vocabulário válido, correndo
    o risco de os dois (enum + esta tabela) ficarem dessincronizados. Ver
    app/crm_pipeline_settings.py."""
    __tablename__ = "crm_pipeline_stage_config"
    __table_args__ = (UniqueConstraint("pipeline", "stage_value", name="uq_pipeline_stage"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    pipeline: Mapped[str] = mapped_column(index=True)
    stage_value: Mapped[str]
    color: Mapped[str | None] = mapped_column(default=None)
    label: Mapped[str | None] = mapped_column(default=None)  # sobrescreve o texto exibido (crm_badge label=); o stage_value/enum em si não muda
    description: Mapped[str | None] = mapped_column(Text, default=None)
    active: Mapped[bool] = mapped_column(default=True)
    sort_order: Mapped[int | None] = mapped_column(default=None)  # posição customizada (drag-and-drop na tela de admin); None = ordem original do enum
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None)


class ServiceInterestOption(Base):
    """Item (ou cabeçalho de seção) da lista "qual desses serviços você
    tem interesse" do formulário público de interesse inicial
    (_lead_intake_form.html, app/lead_intake.py) -- pedido do usuário
    2026-08-07: reordenar, renomear, adicionar e apagar pelo painel do
    colaborador. Substitui a constante `SERVICE_INTEREST_OPTIONS` que
    existia hardcoded em app/services/service_interests.py (esse módulo
    virou só um conjunto de leituras por cima desta tabela).

    `key` é o valor do checkbox (`<input name="services"
    value="{{ opt.key }}">`) e o sufixo da chave de tradução
    (`service_interest_{key}`, ver app/translations/*.json) -- gerado
    uma vez ao criar o item (a partir do slug do serviço vinculado, ou
    de um slug do rótulo se nenhum serviço for vinculado) e nunca mais
    editável depois: Leads antigos guardam essas chaves em
    `Lead.interest_notes`/`session["lead_intake"]["keys"]" durante o
    fluxo de cadastro, então trocar `key` depois de criado quebraria um
    fluxo em andamento no meio do carrinho. O RÓTULO (o texto mostrado)
    continua morando nos arquivos de tradução, não numa coluna aqui --
    ver app/i18n.py::set_translation/delete_translation.

    `slug`, se preenchido, precisa bater com um `ServiceCatalog.slug`
    real -- é o que liga a resposta do visitante a um serviço de verdade
    (ver app/lead_intake.py::start(), LeadInterestedService). Itens sem
    correspondência no catálogo ainda (ex.: "Planejamento Financeiro",
    que é outra linha de negócio inteira) ficam com slug=None -- o texto
    de interesse ainda é gravado, só não vira um relacionamento
    estruturado.

    `is_group`: linha é só um cabeçalho visual de seção (sem checkbox
    próprio), ex. "Mudança de Status" agrupando F1/F2/B2 logo abaixo
    (marcados com `indent=True`). `sort_order` é uma lista única e FLAT
    -- cabeçalhos e itens juntos, na ordem visual real (mesma ideia de
    PipelineStageConfig.sort_order acima)."""
    __tablename__ = "crm_service_interest_options"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(unique=True, index=True)
    slug: Mapped[str | None] = mapped_column(default=None, index=True)
    is_group: Mapped[bool] = mapped_column(default=False)
    indent: Mapped[bool] = mapped_column(default=False)
    sort_order: Mapped[int] = mapped_column(default=0, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
