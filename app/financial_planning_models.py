"""Fase 2 (Modelo de Dados Central) do SAES_Financial_Planning_Master_Spec,
2026-08-07 -- accounts, financial_transactions, budget_categories,
income_sources, financial_attachments. Arquivo próprio, separado de
app/crm_financial_models.py (aquele é "Financial COACHING": funil de
venda, sessões, homework -- um CRM de coaching; este é "Financial
PLANNING": o livro-razão pessoal que o PRÓPRIO CLIENTE alimenta, contas/
transações/orçamento/dívidas/metas). A auditoria da Fase 1 (2026-08-07)
já confirmou: são sistemas com sobreposição praticamente zero, exceto o
`FinancialWorkspace` (definido em crm_financial_models.py, 1:1 com
`FinancialClient`) que ancora tudo aqui via `financial_workspace_id`.

Convenções seguidas (mesmas do resto do projeto, decisão da auditoria):
- Dinheiro sempre `*_cents` inteiro, nunca float -- house convention já
  usada em todo o projeto, satisfaz o requisito do documento (NUMERIC/
  decimal ou unidade mínima inteira) sem introduzir um tipo novo.
- PK inteira autoincrement, não uuid -- o schema do documento usa uuid
  em todo lugar, mas nada neste projeto usa uuid como PK; manter a
  convenção existente em vez de introduzir uma nova só pra este módulo.
- `deleted_at` (exclusão lógica) em vez de DELETE de verdade em tudo que
  representa dado financeiro real do cliente -- pedido explícito do
  documento ("Do not silently delete/overwrite financial data").
"""
from __future__ import annotations

import enum
from datetime import date, datetime, timezone

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------
# Vocabulário fechado
# --------------------------------------------------------------------------

class AccountType(str, enum.Enum):
    checking = "checking"
    savings = "savings"
    money_market = "money_market"
    cash = "cash"
    other_bank_account = "other_bank_account"


class TransactionType(str, enum.Enum):
    income = "income"
    expense = "expense"
    transfer = "transfer"


class TransactionStatus(str, enum.Enum):
    projected = "projected"
    scheduled = "scheduled"
    completed = "completed"
    cancelled = "cancelled"


class TransactionClassification(str, enum.Enum):
    """50/30/20 (Fase 4, Orçamento) -- opcional em cada transação, pra já
    dar pro cliente classificar no momento do lançamento em vez de ter
    que voltar depois."""
    needs = "needs"
    wants = "wants"
    savings = "savings"


class PaymentMethodType(str, enum.Enum):
    """Como o CLIENTE pagou -- não confundir com
    app/crm_models.py::PaymentMethodLookup, que é como o CLIENTE paga A
    SAES (Zelle, cheque, etc. pelo serviço contratado). Conceito
    diferente, tabela diferente."""
    cash = "cash"
    debit_card = "debit_card"
    credit_card = "credit_card"
    check = "check"
    bank_transfer = "bank_transfer"
    other = "other"


class BudgetCategoryGroup(str, enum.Enum):
    needs = "needs"
    wants = "wants"
    savings = "savings"


class BudgetRuleType(str, enum.Enum):
    """Fase 4. `fifty_thirty_twenty`/`custom_percentage` dividem a RENDA
    do período em 3 baldes (needs/wants/savings) -- comparado contra o
    que as transações já classificam (`FinancialTransaction.
    classification`, Fase 2). `category_budget` ignora esses baldes e
    usa só `BudgetAllocation` por categoria. `none` = sem orçamento
    definido ainda (estado inicial)."""
    fifty_thirty_twenty = "fifty_thirty_twenty"
    custom_percentage = "custom_percentage"
    category_budget = "category_budget"
    none = "none"


class BudgetPeriodStatus(str, enum.Enum):
    open = "open"
    closed = "closed"
    reopened = "reopened"


class BillFrequency(str, enum.Enum):
    weekly = "weekly"
    biweekly = "biweekly"
    monthly = "monthly"
    quarterly = "quarterly"
    semiannual = "semiannual"
    annual = "annual"
    custom = "custom"


class BillPaymentStatus(str, enum.Enum):
    upcoming = "upcoming"
    to_pay = "to_pay"
    scheduled = "scheduled"
    paid = "paid"
    overdue = "overdue"
    skipped = "skipped"
    cancelled = "cancelled"


class RecurringTransactionKind(str, enum.Enum):
    income = "income"
    expense = "expense"
    savings_contribution = "savings_contribution"
    debt_payment = "debt_payment"


class ReviewStatus(str, enum.Enum):
    keep = "keep"
    review = "review"
    cancel = "cancel"


class GoalPriority(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"


class GoalStatus(str, enum.Enum):
    active = "active"
    paused = "paused"
    completed = "completed"
    cancelled = "cancelled"


class DebtType(str, enum.Enum):
    credit_card = "credit_card"
    personal_loan = "personal_loan"
    student_loan = "student_loan"
    auto_loan = "auto_loan"
    mortgage = "mortgage"
    line_of_credit = "line_of_credit"
    medical = "medical"
    installment_plan = "installment_plan"
    other = "other"


class PayoffStrategy(str, enum.Enum):
    snowball = "snowball"
    avalanche = "avalanche"
    custom = "custom"


class DebtStatus(str, enum.Enum):
    planned = "planned"
    active = "active"
    delinquent = "delinquent"
    paid_off = "paid_off"


# --------------------------------------------------------------------------
# Núcleo
# --------------------------------------------------------------------------

class Account(Base):
    """"Onde está meu dinheiro?" -- conta bancária/dinheiro em espécie
    real do cliente. NUNCA um catálogo genérico pra dívida/seguro/
    investimento (ver Debts, Fase 8, e o aviso explícito do documento em
    "Observações específicas sobre Accounts"). Nunca solicitar senha,
    PIN, resposta de segurança -- só `last_four_digits`, e mesmo esse é
    opcional."""
    __tablename__ = "financial_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    financial_workspace_id: Mapped[int] = mapped_column(
        ForeignKey("financial_workspaces.id"), index=True)

    account_name: Mapped[str]
    institution_name: Mapped[str | None] = mapped_column(default=None)
    account_type: Mapped[AccountType] = mapped_column(SAEnum(AccountType))
    nickname: Mapped[str | None] = mapped_column(default=None)
    last_four_digits: Mapped[str | None] = mapped_column(default=None)
    current_balance_cents: Mapped[int] = mapped_column(default=0)
    available_balance_cents: Mapped[int | None] = mapped_column(default=None)
    currency: Mapped[str] = mapped_column(default="USD")
    include_in_cash_flow: Mapped[bool] = mapped_column(default=True)
    include_in_net_worth: Mapped[bool] = mapped_column(default=True)
    active: Mapped[bool] = mapped_column(default=True)
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, default=None, index=True)


class BudgetCategory(Base):
    """Categoria de orçamento (usada por transações de despesa e, na
    Fase 4, por `budget_allocations`). `category_group` -- não `group`,
    palavra reservada em SQL (GROUP BY) que o SQLAlchemy até resolveria
    sozinho entre aspas, mas evitar de propósito."""
    __tablename__ = "financial_budget_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    financial_workspace_id: Mapped[int] = mapped_column(
        ForeignKey("financial_workspaces.id"), index=True)

    name: Mapped[str]
    category_group: Mapped[BudgetCategoryGroup] = mapped_column(SAEnum(BudgetCategoryGroup))
    parent_category_id: Mapped[int | None] = mapped_column(
        ForeignKey("financial_budget_categories.id"), default=None)
    icon: Mapped[str | None] = mapped_column(default=None)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    active: Mapped[bool] = mapped_column(default=True)
    sort_order: Mapped[int] = mapped_column(default=0)


class IncomeSource(Base):
    """Definição reutilizável de fonte de renda (ex.: "Salário — Acme
    Corp", recorrente, mensal) -- alimenta o Quick Add de renda; a
    transação de renda em si é sempre uma linha em
    `FinancialTransaction`, esta tabela só guarda o "modelo" reusável
    pra não redigitar tudo toda vez."""
    __tablename__ = "financial_income_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    financial_workspace_id: Mapped[int] = mapped_column(
        ForeignKey("financial_workspaces.id"), index=True)

    name: Mapped[str]
    # Texto aberto de propósito (select_or_custom no documento) -- lista
    # fechada engessaria fontes de renda que variam demais de cliente
    # pra cliente (salário, freelance, aluguel, pensão, ...).
    type: Mapped[str | None] = mapped_column(default=None)
    default_amount_cents: Mapped[int | None] = mapped_column(default=None)
    frequency: Mapped[str | None] = mapped_column(default=None)
    default_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("financial_accounts.id"), default=None)
    active: Mapped[bool] = mapped_column(default=True)
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class FinancialTransaction(Base):
    """Livro-razão normalizado de renda/despesa/transferência -- ver
    app/services/financial_transactions_service.py pelas regras de
    validação (transferência exige from/to distintos e nunca conta como
    renda/despesa; toda conta/categoria referenciada precisa pertencer
    ao MESMO workspace -- nunca só checado na UI, sempre no service,
    pedido explícito do documento: "Enforce tenant/client isolation on
    backend/database layers, not only in UI")."""
    __tablename__ = "financial_transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    financial_workspace_id: Mapped[int] = mapped_column(
        ForeignKey("financial_workspaces.id"), index=True)

    transaction_type: Mapped[TransactionType] = mapped_column(SAEnum(TransactionType), index=True)
    name: Mapped[str]
    amount_cents: Mapped[int]  # sempre positivo -- a direção vem de transaction_type, não do sinal
    currency: Mapped[str] = mapped_column(default="USD")
    transaction_date: Mapped[date] = mapped_column(Date, index=True)

    # Income/expense usam `account_id`; transfer usa os dois de baixo e
    # deixa `account_id` vazio (ver validação no service).
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("financial_accounts.id"), default=None, index=True)
    transfer_from_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("financial_accounts.id"), default=None)
    transfer_to_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("financial_accounts.id"), default=None)

    budget_category_id: Mapped[int | None] = mapped_column(
        ForeignKey("financial_budget_categories.id"), default=None, index=True)
    merchant_or_source: Mapped[str | None] = mapped_column(default=None)
    payment_method: Mapped[PaymentMethodType | None] = mapped_column(SAEnum(PaymentMethodType), default=None)
    classification: Mapped[TransactionClassification | None] = mapped_column(
        SAEnum(TransactionClassification), default=None)
    status: Mapped[TransactionStatus] = mapped_column(
        SAEnum(TransactionStatus), default=TransactionStatus.completed, index=True)
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, default=None, index=True)


class FinancialAttachment(Base):
    """Metadados de anexo (comprovante/recibo/extrato) -- bytes de
    verdade vivem no StorageBackend plugável (app/services/storage/,
    Seção 10 do CRM, construído mais cedo hoje) via `storage_key` opaca,
    nunca um caminho de disco aqui. Associação polimórfica simples
    (`record_type`/`record_id`, ex. "FinancialTransaction"/42) porque
    Fase 2 ainda não tem um dono fixo pra anexo -- Bills (Fase 5) vai
    reusar exatamente esta tabela pra recibo de pagamento de boleto, em
    vez de inventar uma tabela de anexo por módulo."""
    __tablename__ = "financial_attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    financial_workspace_id: Mapped[int] = mapped_column(
        ForeignKey("financial_workspaces.id"), index=True)
    record_type: Mapped[str] = mapped_column(index=True)
    record_id: Mapped[int] = mapped_column(index=True)

    storage_key: Mapped[str]
    original_filename: Mapped[str]
    mime_type: Mapped[str]
    file_size_bytes: Mapped[int]
    file_hash: Mapped[str | None] = mapped_column(default=None)

    uploaded_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)


# --------------------------------------------------------------------------
# Fase 4 (Orçamento) do SAES_Financial_Planning_Master_Spec, 2026-08-07
# --------------------------------------------------------------------------

class BudgetRule(Base):
    """A regra de orçamento do workspace -- UMA por workspace (não por
    período: é uma configuração que vale até o cliente trocar), pedido
    do documento (§4: "Budget method"). `needs_percent`/`wants_percent`/
    `savings_percent` só são usados quando `rule_type=custom_percentage`
    (`fifty_thirty_twenty` já tem os percentuais fixos em código, ver
    app/services/budget_service.py; `category_budget`/`none` os ignoram
    -- ver validação no service, "os 3 somam 100%" é regra do documento
    (§8), reforçada lá, não aqui."""
    __tablename__ = "financial_budget_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    financial_workspace_id: Mapped[int] = mapped_column(
        ForeignKey("financial_workspaces.id"), unique=True, index=True)

    rule_type: Mapped[BudgetRuleType] = mapped_column(SAEnum(BudgetRuleType), default=BudgetRuleType.none)
    needs_percent: Mapped[int | None] = mapped_column(default=None)
    wants_percent: Mapped[int | None] = mapped_column(default=None)
    savings_percent: Mapped[int | None] = mapped_column(default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class BudgetPeriod(Base):
    """Um mês de orçamento (§9, "Month Close"). `status` começa `open`;
    fechar (`close_period`, service) grava um `FinancialMonthSnapshot` e
    vira `closed` -- reabrir (`reopen_period`) vira `reopened`, sempre
    auditado (`AuditLog`), nunca silencioso (pedido explícito:
    "Reopen only with confirmation and audit"). Uma linha por (workspace,
    mês) -- `get_or_create_current_period` (service) garante isso, nunca
    duplica."""
    __tablename__ = "financial_budget_periods"

    id: Mapped[int] = mapped_column(primary_key=True)
    financial_workspace_id: Mapped[int] = mapped_column(
        ForeignKey("financial_workspaces.id"), index=True)

    period_start: Mapped[date] = mapped_column(Date, index=True)
    period_end: Mapped[date] = mapped_column(Date)
    status: Mapped[BudgetPeriodStatus] = mapped_column(SAEnum(BudgetPeriodStatus), default=BudgetPeriodStatus.open)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    closed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None)
    reopened_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    reopened_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class BudgetAllocation(Base):
    """Valor planejado por categoria, por período -- só faz sentido
    quando `BudgetRule.rule_type == category_budget` (ou como
    complemento livre em qualquer regra; o service não impede criar uma
    alocação mesmo com 50/30/20 ativo, só não é o principal ali)."""
    __tablename__ = "financial_budget_allocations"
    __table_args__ = (
        UniqueConstraint("budget_period_id", "budget_category_id", name="uq_budget_allocation_period_category"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    budget_period_id: Mapped[int] = mapped_column(ForeignKey("financial_budget_periods.id"), index=True)
    budget_category_id: Mapped[int] = mapped_column(ForeignKey("financial_budget_categories.id"), index=True)

    planned_amount_cents: Mapped[int]
    rollover_enabled: Mapped[bool] = mapped_column(default=False)
    notes: Mapped[str | None] = mapped_column(Text, default=None)


class FinancialMonthSnapshot(Base):
    """Snapshot protegido de um `BudgetPeriod` fechado (§9, "Create
    protected snapshot"; §7 do documento). `snapshot_json` guarda os
    números do mês NO MOMENTO do fechamento (renda/despesa/saldo por
    categoria) -- histórico imutável, nunca recalculado depois mesmo se
    transações antigas forem editadas/apagadas dali pra frente."""
    __tablename__ = "financial_month_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    financial_workspace_id: Mapped[int] = mapped_column(
        ForeignKey("financial_workspaces.id"), index=True)
    budget_period_id: Mapped[int] = mapped_column(ForeignKey("financial_budget_periods.id"), index=True)

    snapshot_json: Mapped[dict] = mapped_column(JSON)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


# --------------------------------------------------------------------------
# Fase 5 (Bills) do SAES_Financial_Planning_Master_Spec, 2026-08-07
# --------------------------------------------------------------------------

class Bill(Base):
    """Definição recorrente de um boleto (§4 "Bills") -- "aluguel",
    "internet", "seguro do carro". NÃO é uma cobrança individual (isso é
    `BillPayment`, um por mês de referência) -- `Bill` é o "molde" que o
    service usa pra gerar as cobranças do mês, do mesmo jeito que
    `IncomeSource` (Fase 2) é o molde reusável pra uma transação de
    renda. `budget_category_id` é uma FK pra `BudgetCategory` (em vez do
    texto livre `category varchar` do schema original do documento) --
    mesma categoria já usada em Transactions/Budget (Fase 2/4), evita uma
    segunda lista de categorias desalinhada da primeira."""
    __tablename__ = "financial_bills"

    id: Mapped[int] = mapped_column(primary_key=True)
    financial_workspace_id: Mapped[int] = mapped_column(
        ForeignKey("financial_workspaces.id"), index=True)

    bill_name: Mapped[str]
    budget_category_id: Mapped[int | None] = mapped_column(
        ForeignKey("financial_budget_categories.id"), default=None)
    default_amount_cents: Mapped[int | None] = mapped_column(default=None)
    due_day: Mapped[int | None] = mapped_column(default=None)  # 1-31
    frequency: Mapped[BillFrequency] = mapped_column(SAEnum(BillFrequency), default=BillFrequency.monthly)
    default_payment_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("financial_accounts.id"), default=None)
    autopay: Mapped[bool] = mapped_column(default=False)
    active: Mapped[bool] = mapped_column(default=True)
    start_date: Mapped[date | None] = mapped_column(Date, default=None)
    end_date: Mapped[date | None] = mapped_column(Date, default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, default=None, index=True)


class BillPayment(Base):
    """Uma cobrança individual de um `Bill`, pra um `billing_month`
    específico (1 por bill+mês -- `UniqueConstraint` abaixo, mesmo
    padrão de `BudgetPeriod` uma linha por workspace+mês). Gerada pelo
    service (`bills_service.ensure_payments_for_month`), nunca digitada
    manualmente pelo cliente -- só o STATUS e os campos de pagamento são
    editados depois. Recibo de pagamento (se o cliente anexar) fica em
    `FinancialAttachment` com `record_type="BillPayment"`/`record_id=id`
    -- reusa a mesma tabela polimórfica da Fase 2, sem FK direta aqui
    (documentado desde a Fase 2: "Bills vai reusar exatamente esta
    tabela")."""
    __tablename__ = "financial_bill_payments"
    __table_args__ = (
        UniqueConstraint("bill_id", "billing_month", name="uq_bill_payment_bill_month"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    bill_id: Mapped[int] = mapped_column(ForeignKey("financial_bills.id"), index=True)
    billing_month: Mapped[date] = mapped_column(Date, index=True)  # sempre dia 1 -- mesma convenção de BudgetPeriod.period_start

    amount_cents: Mapped[int]
    status: Mapped[BillPaymentStatus] = mapped_column(
        SAEnum(BillPaymentStatus), default=BillPaymentStatus.upcoming, index=True)
    due_date: Mapped[date] = mapped_column(Date, index=True)
    scheduled_date: Mapped[date | None] = mapped_column(Date, default=None)
    paid_date: Mapped[date | None] = mapped_column(Date, default=None)
    paid_from_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("financial_accounts.id"), default=None)
    confirmation_number: Mapped[str | None] = mapped_column(default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


# --------------------------------------------------------------------------
# Fase 6 (Recurring) do SAES_Financial_Planning_Master_Spec, 2026-08-07
# --------------------------------------------------------------------------

class RecurringTransaction(Base):
    """Agenda de renda/despesa/aporte de poupança/pagamento de dívida que
    se repete (§4 "Recurring Transactions"). Diferente de `Bill`
    (Fase 5), que só rastreia STATUS de cobrança (paga/pendente) sem
    tocar no livro-razão -- `RecurringTransaction` GERA de verdade uma
    `FinancialTransaction` a cada ocorrência (via
    `financial_transactions_service.create_transaction`, mesma
    validação de isolamento de tenant reusada). `frequency` reusa
    `BillFrequency` (Fase 5) -- mesmo vocabulário de cadência, sem
    inventar um enum irmão só pra este módulo, embora o schema do
    documento descreva o campo como texto livre em ambas as tabelas
    novas desta fase. `savings_contribution` gera uma despesa com
    `classification=savings` (mesmo campo já usado pelo gráfico Needs/
    Wants/Savings, Fase 3/4) -- não uma transferência de verdade, porque
    o schema só tem UM `account_id`, não from/to. `debt_payment` gera
    uma despesa sem vínculo com dívida nenhuma (Debts é Fase 8, ainda
    não existe) -- rastreia só a saída de caixa por enquanto."""
    __tablename__ = "financial_recurring_transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    financial_workspace_id: Mapped[int] = mapped_column(
        ForeignKey("financial_workspaces.id"), index=True)

    transaction_kind: Mapped[RecurringTransactionKind] = mapped_column(SAEnum(RecurringTransactionKind))
    name: Mapped[str]
    amount_cents: Mapped[int]
    frequency: Mapped[BillFrequency] = mapped_column(SAEnum(BillFrequency), default=BillFrequency.monthly)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date, default=None)
    next_occurrence: Mapped[date | None] = mapped_column(Date, default=None, index=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("financial_accounts.id"), default=None)
    active: Mapped[bool] = mapped_column(default=True)
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, default=None, index=True)


class RecurringDebit(Base):
    """Registro de assinatura/cobrança automática (§4 "Recurring
    Debits") -- ao contrário de `RecurringTransaction`, NÃO gera
    `FinancialTransaction` sozinho (o schema do documento não define
    uma tabela de instâncias pra isto, diferente de `bill_payments`). É
    uma lista de auditoria: "o que estou pagando de forma recorrente, e
    eu ainda quero isso?" -- `review_status` (keep/review/cancel)
    alimenta a "subscription analysis" (Fase 6, `subscriptions_service.
    subscription_summary`), que soma o custo mensal equivalente de tudo
    que está ativo e o quanto dá pra economizar cancelando o que já foi
    marcado `cancel`."""
    __tablename__ = "financial_recurring_debits"

    id: Mapped[int] = mapped_column(primary_key=True)
    financial_workspace_id: Mapped[int] = mapped_column(
        ForeignKey("financial_workspaces.id"), index=True)

    merchant: Mapped[str]
    description: Mapped[str | None] = mapped_column(default=None)
    amount_cents: Mapped[int]
    frequency: Mapped[BillFrequency] = mapped_column(SAEnum(BillFrequency), default=BillFrequency.monthly)
    next_charge_date: Mapped[date | None] = mapped_column(Date, default=None)
    budget_category_id: Mapped[int | None] = mapped_column(
        ForeignKey("financial_budget_categories.id"), default=None)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("financial_accounts.id"), default=None)
    autopay: Mapped[bool] = mapped_column(default=True)
    active: Mapped[bool] = mapped_column(default=True)
    review_status: Mapped[ReviewStatus] = mapped_column(SAEnum(ReviewStatus), default=ReviewStatus.keep)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, default=None, index=True)


# --------------------------------------------------------------------------
# Fase 7 (Goals & Savings) do SAES_Financial_Planning_Master_Spec, 2026-08-07
# --------------------------------------------------------------------------

class FinancialGoal(Base):
    """Meta financeira (§4 "Financial Goals") -- "viagem", "entrada da
    casa", "fundo de emergência" (`goal_type` é texto livre de propósito,
    igual ao schema do documento: `goal_type varchar`, vocabulário aberto
    demais pra travar num enum). `current_amount_cents` é incrementado
    por `GoalContribution` (histórico de aportes, abaixo) -- diferente
    de `Account.current_balance_cents` (editável direto), aqui o
    documento define uma tabela de histórico própria (`goal_contributions`),
    então current_amount é sempre a SOMA das contribuições, nunca editado
    à mão."""
    __tablename__ = "financial_goals"

    id: Mapped[int] = mapped_column(primary_key=True)
    financial_workspace_id: Mapped[int] = mapped_column(
        ForeignKey("financial_workspaces.id"), index=True)

    name: Mapped[str]
    goal_type: Mapped[str | None] = mapped_column(default=None)
    target_amount_cents: Mapped[int]
    current_amount_cents: Mapped[int] = mapped_column(default=0)
    target_date: Mapped[date | None] = mapped_column(Date, default=None)
    monthly_contribution_cents: Mapped[int | None] = mapped_column(default=None)
    priority: Mapped[GoalPriority] = mapped_column(SAEnum(GoalPriority), default=GoalPriority.medium)
    status: Mapped[GoalStatus] = mapped_column(SAEnum(GoalStatus), default=GoalStatus.active, index=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("financial_accounts.id"), default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, default=None, index=True)


class GoalContribution(Base):
    """Histórico de aportes de uma meta (§4 "Goal Contributions") --
    cada linha aqui incrementa `FinancialGoal.current_amount_cents` na
    hora da criação (`goals_service.add_contribution`). Nunca apagado
    nem editado -- é histórico financeiro; uma correção se lança como
    uma nova contribuição (negativa, se for pra reduzir), nunca
    reescrevendo o passado."""
    __tablename__ = "financial_goal_contributions"

    id: Mapped[int] = mapped_column(primary_key=True)
    goal_id: Mapped[int] = mapped_column(ForeignKey("financial_goals.id"), index=True)

    amount_cents: Mapped[int]
    contribution_date: Mapped[date] = mapped_column(Date, index=True)
    from_account_id: Mapped[int | None] = mapped_column(ForeignKey("financial_accounts.id"), default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class SinkingFund(Base):
    """Reserva pra despesa futura conhecida (§4 "Sinking Funds") --
    "troca de pneu em 8 meses", "IPTU de dezembro". Mais simples que
    `FinancialGoal` de propósito (sem prioridade/status/tipo -- o
    documento não pede isso pra sinking funds, só pra goals): o schema
    do documento não define uma tabela de histórico de aporte própria
    pra isto, então `current_amount_cents` é editável direto pelo
    cliente (mesma disciplina de `Account.current_balance_cents`,
    Fase 2 -- não é contabilidade de partida dobrada)."""
    __tablename__ = "financial_sinking_funds"

    id: Mapped[int] = mapped_column(primary_key=True)
    financial_workspace_id: Mapped[int] = mapped_column(
        ForeignKey("financial_workspaces.id"), index=True)

    name: Mapped[str]
    target_amount_cents: Mapped[int]
    current_amount_cents: Mapped[int] = mapped_column(default=0)
    target_date: Mapped[date | None] = mapped_column(Date, default=None)
    monthly_contribution_cents: Mapped[int | None] = mapped_column(default=None)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("financial_accounts.id"), default=None)
    active: Mapped[bool] = mapped_column(default=True)

    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, default=None, index=True)


# --------------------------------------------------------------------------
# Fase 8 (Debt Management) do SAES_Financial_Planning_Master_Spec, 2026-08-07
# --------------------------------------------------------------------------

class Debt(Base):
    """Registro unificado de dívida (§4 "Debts") -- cartão de crédito,
    financiamento, empréstimo estudantil, etc. `apr_bps` guarda a taxa
    em BASIS POINTS (19.99% = 1999), mesma disciplina de `*_cents` pra
    dinheiro -- nunca float, mas precisa de 2 casas decimais de verdade
    (taxa de juros real quase nunca é um número redondo).

    `payoff_strategy`/`custom_priority` existem no schema do documento
    por linha, mas a ORDENAÇÃO de verdade pro "Debt Payoff Plan"
    (snowball = saldo crescente, avalanche = APR decrescente) é uma
    escolha da TELA (query param, nunca salva -- mesmo espírito de
    "calculado na hora" do Fundo de Emergência, Fase 7), não por
    dívida -- `payoff_strategy` aqui é só informativo (qual método o
    cliente pensa nesta dívida especificamente); `custom_priority` é
    usado só quando a estratégia escolhida na tela é "custom"."""
    __tablename__ = "financial_debts"

    id: Mapped[int] = mapped_column(primary_key=True)
    financial_workspace_id: Mapped[int] = mapped_column(
        ForeignKey("financial_workspaces.id"), index=True)

    debt_name: Mapped[str]
    lender_name: Mapped[str | None] = mapped_column(default=None)
    debt_type: Mapped[DebtType] = mapped_column(SAEnum(DebtType), default=DebtType.other)
    original_balance_cents: Mapped[int | None] = mapped_column(default=None)
    current_balance_cents: Mapped[int]
    apr_bps: Mapped[int | None] = mapped_column(default=None)
    minimum_payment_cents: Mapped[int | None] = mapped_column(default=None)
    extra_monthly_payment_cents: Mapped[int | None] = mapped_column(default=None)
    due_day: Mapped[int | None] = mapped_column(default=None)
    payment_frequency: Mapped[BillFrequency] = mapped_column(SAEnum(BillFrequency), default=BillFrequency.monthly)
    payoff_strategy: Mapped[PayoffStrategy] = mapped_column(SAEnum(PayoffStrategy), default=PayoffStrategy.snowball)
    custom_priority: Mapped[int | None] = mapped_column(default=None)
    target_payoff_date: Mapped[date | None] = mapped_column(Date, default=None)
    status: Mapped[DebtStatus] = mapped_column(SAEnum(DebtStatus), default=DebtStatus.active, index=True)
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, default=None, index=True)


class DebtPayment(Base):
    """Pagamento de verdade feito numa dívida (§4 "Debt Payments") --
    histórico, nunca editado/apagado (mesma disciplina de
    `GoalContribution`, Fase 7). Se `principal_amount_cents` não vier
    informado, o service assume que o pagamento inteiro abateu o
    principal (simplificação disclosed -- sem o boleto/demonstrativo do
    credor, não dá pra saber a separação real principal/juros de cada
    parcela)."""
    __tablename__ = "financial_debt_payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    debt_id: Mapped[int] = mapped_column(ForeignKey("financial_debts.id"), index=True)

    amount_cents: Mapped[int]
    principal_amount_cents: Mapped[int | None] = mapped_column(default=None)
    interest_amount_cents: Mapped[int | None] = mapped_column(default=None)
    payment_date: Mapped[date] = mapped_column(Date, index=True)
    paid_from_account_id: Mapped[int | None] = mapped_column(ForeignKey("financial_accounts.id"), default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


# --------------------------------------------------------------------------
# Fase 9 (Net Worth) do SAES_Financial_Planning_Master_Spec, 2026-08-07
# --------------------------------------------------------------------------

class SnapshotSource(str, enum.Enum):
    manual = "manual"
    imported = "import"
    integration = "integration"
    month_close = "month_close"


class AccountBalanceSnapshot(Base):
    """Saldo histórico de uma conta numa data (§7 `account_balance_snapshots`,
    "Historical account balances for charts/reconciliation/net worth").
    `source` só produz `manual` (cliente registrando um saldo na tela) e
    `month_close` (gerado automaticamente pelo fechamento de mês, Fase 4 --
    `budget_service.close_period` chama `net_worth_service.
    snapshot_month_close` logo depois de fechar) neste sistema -- `import`/
    `integration` existem no vocabulário do documento mas não têm produtor
    (não há integração bancária aqui), mantidos só por completude do enum,
    mesmo padrão de `BillFrequency.custom` (existe no vocabulário, sem
    gerador automático).

    Uma linha por (conta, data) -- registrar de novo no mesmo dia
    corrige/substitui o valor daquele dia (upsert no service) em vez de
    duplicar; não é "apagar histórico", é o mesmo dia sendo re-registrado
    antes que o tempo passe, igual a editar uma alocação de orçamento no
    mesmo período."""
    __tablename__ = "financial_account_balance_snapshots"
    __table_args__ = (
        UniqueConstraint("account_id", "snapshot_date", name="uq_account_balance_snapshot_day"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("financial_accounts.id"), index=True)

    balance_cents: Mapped[int]
    available_balance_cents: Mapped[int | None] = mapped_column(default=None)
    snapshot_date: Mapped[date] = mapped_column(Date, index=True)
    source: Mapped[SnapshotSource] = mapped_column(SAEnum(SnapshotSource), default=SnapshotSource.manual)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
