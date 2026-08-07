"""Fase 5 (Bills) do SAES_Financial_Planning_Master_Spec, 2026-08-07 --
definições de boleto recorrente (`Bill`) e a geração/gestão das
cobranças mensais (`BillPayment`) delas, mais o calendário e o resumo de
"vence em breve" que alimentam a página.

**Granularidade mensal, mesmo pra frequências que não são mensais --
limitação deliberada e documentada**: o modelo de "1 `BudgetPeriod` por
mês" já usado no Orçamento (Fase 4) é reaproveitado aqui como a unidade
de geração (`billing_month`). Pra `weekly`/`biweekly` isso significa
representar só UMA cobrança por mês em vez das 4-5 reais -- o motor
correto de recorrência sub-mensal é o Fase 6 (Recurring Transactions),
que ainda não existe. `quarterly`/`semiannual`/`annual` só geram cobrança
nos meses certos (calculado a partir de `start_date`, ou da data de
criação do Bill se não houver `start_date`). `custom` nunca gera
sozinho -- não dá pra adivinhar uma cadência arbitrária sem inventar
dado (regra do documento: "No fake production placeholders")."""
from __future__ import annotations

import calendar as _calendar
from datetime import date, datetime, timedelta, timezone

from app.crm_financial_models import FinancialWorkspace
from app.db import SessionLocal
from app.financial_planning_models import (Account, Bill, BillFrequency, BillPayment,
                                            BillPaymentStatus, BudgetCategory)
from app.services import audit_service
from app.services.financial_dashboard_service import _first_of_month, _first_of_next_month


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BillValidationError(ValueError):
    pass


# --------------------------------------------------------------------------
# Definição do boleto (Bill)
# --------------------------------------------------------------------------

def _check_account_ownership(account_id: int | None, workspace_id: int) -> None:
    if account_id is None:
        return
    account = SessionLocal.get(Account, account_id)
    if account is None or account.financial_workspace_id != workspace_id:
        raise BillValidationError("Account does not belong to this workspace.")


def _check_category_ownership(category_id: int | None, workspace_id: int) -> None:
    if category_id is None:
        return
    category = SessionLocal.get(BudgetCategory, category_id)
    if category is None or category.financial_workspace_id != workspace_id:
        raise BillValidationError("Budget category does not belong to this workspace.")


def list_bills(workspace: FinancialWorkspace, *, include_inactive: bool = False) -> list[Bill]:
    query = (
        SessionLocal.query(Bill).filter_by(financial_workspace_id=workspace.id)
        .filter(Bill.deleted_at.is_(None))
    )
    if not include_inactive:
        query = query.filter_by(active=True)
    return query.order_by(Bill.bill_name).all()


def create_bill(
    workspace: FinancialWorkspace, *, actor, bill_name: str,
    budget_category_id: int | None = None, default_amount_cents: int | None = None,
    due_day: int | None = None, frequency: BillFrequency = BillFrequency.monthly,
    default_payment_account_id: int | None = None, autopay: bool = False,
    start_date: date | None = None, end_date: date | None = None, notes: str | None = None,
) -> Bill:
    if not bill_name:
        raise BillValidationError("Bill name is required.")
    if due_day is not None and not (1 <= due_day <= 31):
        raise BillValidationError("Due day must be between 1 and 31.")
    _check_category_ownership(budget_category_id, workspace.id)
    _check_account_ownership(default_payment_account_id, workspace.id)

    bill = Bill(
        financial_workspace_id=workspace.id, bill_name=bill_name, budget_category_id=budget_category_id,
        default_amount_cents=default_amount_cents, due_day=due_day, frequency=frequency,
        default_payment_account_id=default_payment_account_id, autopay=autopay,
        start_date=start_date, end_date=end_date, notes=notes or None,
        created_by_id=getattr(actor, "id", None),
    )
    SessionLocal.add(bill)
    SessionLocal.commit()
    return bill


def soft_delete_bill(bill: Bill) -> None:
    """Exclusão lógica -- `BillPayment`s já gerados continuam intactos
    (histórico de pagamento não desaparece); só para de gerar cobranças
    novas dali pra frente."""
    bill.deleted_at = _utcnow()
    bill.active = False
    SessionLocal.commit()


# --------------------------------------------------------------------------
# Geração das cobranças mensais (BillPayment)
# --------------------------------------------------------------------------

def _due_date_for_month(bill: Bill, month_start: date) -> date:
    day = bill.due_day or 1
    last_day = _calendar.monthrange(month_start.year, month_start.month)[1]
    return date(month_start.year, month_start.month, min(day, last_day))


def _should_generate_for_month(bill: Bill, month_start: date) -> bool:
    if bill.frequency in (BillFrequency.monthly, BillFrequency.weekly, BillFrequency.biweekly):
        return True
    if bill.frequency == BillFrequency.custom:
        return False

    anchor = _first_of_month(bill.start_date or bill.created_at.date())
    months_diff = (month_start.year - anchor.year) * 12 + (month_start.month - anchor.month)
    if months_diff < 0:
        return False
    if bill.frequency == BillFrequency.quarterly:
        return months_diff % 3 == 0
    if bill.frequency == BillFrequency.semiannual:
        return months_diff % 6 == 0
    if bill.frequency == BillFrequency.annual:
        return months_diff % 12 == 0
    return False


def ensure_payments_for_month(workspace: FinancialWorkspace, *, for_date: date | None = None) -> list[BillPayment]:
    """Gera as `BillPayment`s do mês de `for_date` (padrão hoje) pra
    todo `Bill` ativo que ainda não tem cobrança gerada nesse mês --
    idempotente, chamado toda vez que a página de Bills/Calendar é
    aberta (mesmo padrão de `budget_service.get_or_create_current_period`),
    nunca duplica (`UniqueConstraint` em bill_id+billing_month)."""
    for_date = for_date or date.today()
    month_start = _first_of_month(for_date)
    created: list[BillPayment] = []

    for bill in list_bills(workspace):
        if bill.start_date and month_start < _first_of_month(bill.start_date):
            continue
        if bill.end_date and month_start > _first_of_month(bill.end_date):
            continue
        if not _should_generate_for_month(bill, month_start):
            continue
        existing = (
            SessionLocal.query(BillPayment)
            .filter_by(bill_id=bill.id, billing_month=month_start).first()
        )
        if existing is not None:
            continue
        payment = BillPayment(
            bill_id=bill.id, billing_month=month_start, amount_cents=bill.default_amount_cents or 0,
            status=BillPaymentStatus.upcoming, due_date=_due_date_for_month(bill, month_start),
        )
        SessionLocal.add(payment)
        created.append(payment)

    if created:
        SessionLocal.commit()
    return created


def display_status(payment: BillPayment, *, today: date | None = None) -> str:
    """Status pra exibição -- nunca sobrescreve o status gravado no
    banco (`upcoming`/`to_pay` viram "overdue" só na tela, quando a data
    de vencimento já passou; `paid`/`scheduled`/`skipped`/`cancelled`
    sempre aparecem como estão, são estados finais/explícitos)."""
    today = today or date.today()
    if payment.status in (BillPaymentStatus.upcoming, BillPaymentStatus.to_pay) and payment.due_date < today:
        return BillPaymentStatus.overdue.value
    return payment.status.value


def list_payments_for_month(workspace: FinancialWorkspace, *, for_date: date | None = None) -> list[dict]:
    for_date = for_date or date.today()
    month_start = _first_of_month(for_date)
    rows = (
        SessionLocal.query(BillPayment)
        .join(Bill, BillPayment.bill_id == Bill.id)
        .filter(Bill.financial_workspace_id == workspace.id)
        .filter(BillPayment.billing_month == month_start)
        .order_by(BillPayment.due_date).all()
    )
    return [{"payment": p, "bill": SessionLocal.get(Bill, p.bill_id)} for p in rows]


def payments_for_calendar(workspace: FinancialWorkspace, *, year: int, month: int) -> list[dict]:
    start = date(year, month, 1)
    end = _first_of_next_month(start) - timedelta(days=1)
    rows = (
        SessionLocal.query(BillPayment)
        .join(Bill, BillPayment.bill_id == Bill.id)
        .filter(Bill.financial_workspace_id == workspace.id)
        .filter(BillPayment.due_date >= start, BillPayment.due_date <= end)
        .order_by(BillPayment.due_date).all()
    )
    return [{"payment": p, "bill": SessionLocal.get(Bill, p.bill_id)} for p in rows]


def upcoming_within_days(workspace: FinancialWorkspace, *, days: int = 7, today: date | None = None) -> list[dict]:
    """Alimenta o banner "vence em breve" (§ "Notifications": "Bill due
    in 7/3/1 day(s)", "Bill due today", "Bill overdue") -- inclui também
    o que já venceu (due_date <= hoje), pra aparecer no mesmo lugar em
    vez de um sistema de notificação separado (o projeto não tem fila de
    envio/push -- isto é um banner calculado ao vivo na própria tela,
    não uma notificação entregue de verdade)."""
    today = today or date.today()
    horizon = today + timedelta(days=days)
    rows = (
        SessionLocal.query(BillPayment)
        .join(Bill, BillPayment.bill_id == Bill.id)
        .filter(Bill.financial_workspace_id == workspace.id)
        .filter(BillPayment.status.in_([BillPaymentStatus.upcoming, BillPaymentStatus.to_pay, BillPaymentStatus.scheduled]))
        .filter(BillPayment.due_date <= horizon)
        .order_by(BillPayment.due_date).all()
    )
    return [{"payment": p, "bill": SessionLocal.get(Bill, p.bill_id)} for p in rows]


# --------------------------------------------------------------------------
# Ações sobre uma cobrança (BillPayment)
# --------------------------------------------------------------------------

def mark_paid(
    payment: BillPayment, *, actor, paid_date: date | None = None,
    paid_from_account_id: int | None = None, confirmation_number: str | None = None,
) -> BillPayment:
    """Marca uma cobrança como paga. **Nunca cria uma `FinancialTransaction`
    automaticamente** -- o schema do documento não liga `bill_payments` a
    uma transação (só `paid_from_account_id`, sem `transaction_id`), e
    fazer isso automaticamente duplicaria o gasto no Dashboard/Orçamento
    se o cliente também lançar a despesa manualmente. O cliente lança a
    transação separadamente se quiser que ela conte no fluxo de caixa,
    do mesmo jeito que já faz hoje pra qualquer outra despesa."""
    if payment.status == BillPaymentStatus.paid:
        raise BillValidationError("This payment is already marked as paid.")
    bill = SessionLocal.get(Bill, payment.bill_id)
    _check_account_ownership(paid_from_account_id, bill.financial_workspace_id)

    payment.status = BillPaymentStatus.paid
    payment.paid_date = paid_date or date.today()
    payment.paid_from_account_id = paid_from_account_id
    payment.confirmation_number = confirmation_number or None

    audit_service.log_change(
        "BillPayment", payment.id, "bill_paid",
        description=f"Marked paid by {actor.email}" if actor else "Marked paid",
        user_id=getattr(actor, "id", None))
    SessionLocal.commit()
    return payment


def skip_payment(payment: BillPayment, *, actor) -> BillPayment:
    if payment.status == BillPaymentStatus.paid:
        raise BillValidationError("A paid payment cannot be skipped.")
    payment.status = BillPaymentStatus.skipped
    audit_service.log_change(
        "BillPayment", payment.id, "bill_skipped",
        description=f"Skipped by {actor.email}" if actor else "Skipped",
        user_id=getattr(actor, "id", None))
    SessionLocal.commit()
    return payment
