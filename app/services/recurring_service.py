"""Fase 6 (Recurring) do SAES_Financial_Planning_Master_Spec, 2026-08-07 --
agendas recorrentes que GERAM transação de verdade (`RecurringTransaction`)
e o registro de assinaturas/cobranças automáticas que só é auditado, nunca
gerado sozinho (`RecurringDebit` + "subscription analysis").

`RecurringTransaction` é o motor que resolve a limitação deixada em
aberto na Fase 5 (Bills só tem granularidade mensal) -- aqui a cadência é
respeitada de verdade (semanal soma 7 dias, quinzenal 14, mensal avança
por MÊS -- não por 30 dias fixos, pra não desalinhar do dia do mês)."""
from __future__ import annotations

import calendar as _calendar
from datetime import date, datetime, timedelta, timezone

from app.crm_financial_models import FinancialWorkspace
from app.db import SessionLocal
from app.financial_planning_models import (Account, BillFrequency, BudgetCategory,
                                            RecurringDebit, RecurringTransaction,
                                            RecurringTransactionKind, ReviewStatus,
                                            TransactionClassification, TransactionType)
from app.services import audit_service
from app.services import financial_transactions_service as tx_svc
from app.services.financial_transactions_service import TransactionValidationError


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RecurringValidationError(ValueError):
    pass


def _check_account_ownership(account_id: int | None, workspace_id: int) -> None:
    if account_id is None:
        return
    account = SessionLocal.get(Account, account_id)
    if account is None or account.financial_workspace_id != workspace_id:
        raise RecurringValidationError("Account does not belong to this workspace.")


def _check_category_ownership(category_id: int | None, workspace_id: int) -> None:
    if category_id is None:
        return
    category = SessionLocal.get(BudgetCategory, category_id)
    if category is None or category.financial_workspace_id != workspace_id:
        raise RecurringValidationError("Budget category does not belong to this workspace.")


def _add_months(d: date, months: int) -> date:
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    last_day = _calendar.monthrange(year, month)[1]
    return date(year, month, min(d.day, last_day))


def _advance(d: date, frequency: BillFrequency) -> date | None:
    """Próxima data a partir de `d` -- avança por MÊS (não por 30 dias
    fixos) pra mensal/trimestral/semestral/anual, preservando o dia do
    mês (truncado se o mês seguinte for mais curto, mesma regra de
    `bills_service._due_date_for_month`). `custom` nunca avança sozinho
    -- mesma decisão de `bills_service` pra frequência custom."""
    if frequency == BillFrequency.weekly:
        return d + timedelta(weeks=1)
    if frequency == BillFrequency.biweekly:
        return d + timedelta(weeks=2)
    if frequency == BillFrequency.monthly:
        return _add_months(d, 1)
    if frequency == BillFrequency.quarterly:
        return _add_months(d, 3)
    if frequency == BillFrequency.semiannual:
        return _add_months(d, 6)
    if frequency == BillFrequency.annual:
        return _add_months(d, 12)
    return None  # custom


# --------------------------------------------------------------------------
# Recurring Transactions
# --------------------------------------------------------------------------

def list_recurring_transactions(workspace: FinancialWorkspace, *, include_inactive: bool = False) -> list[RecurringTransaction]:
    query = (
        SessionLocal.query(RecurringTransaction).filter_by(financial_workspace_id=workspace.id)
        .filter(RecurringTransaction.deleted_at.is_(None))
    )
    if not include_inactive:
        query = query.filter_by(active=True)
    return query.order_by(RecurringTransaction.next_occurrence).all()


def create_recurring_transaction(
    workspace: FinancialWorkspace, *, actor, transaction_kind: RecurringTransactionKind,
    name: str, amount_cents: int, frequency: BillFrequency, start_date: date,
    end_date: date | None = None, account_id: int | None = None, notes: str | None = None,
) -> RecurringTransaction:
    if not name:
        raise RecurringValidationError("Name is required.")
    if amount_cents is None or amount_cents <= 0:
        raise RecurringValidationError("Amount must be greater than zero.")
    _check_account_ownership(account_id, workspace.id)

    recurring = RecurringTransaction(
        financial_workspace_id=workspace.id, transaction_kind=transaction_kind, name=name,
        amount_cents=amount_cents, frequency=frequency, start_date=start_date, end_date=end_date,
        # `custom` nunca gera sozinho -- nem a primeira ocorrência (mesma
        # regra de bills_service pra frequência custom); todas as outras
        # frequências começam a contar a partir de `start_date`.
        next_occurrence=(start_date if frequency != BillFrequency.custom else None),
        account_id=account_id, notes=notes or None,
        created_by_id=getattr(actor, "id", None),
    )
    SessionLocal.add(recurring)
    SessionLocal.flush()
    audit_service.log_change(
        "RecurringTransaction", recurring.id, "created", user_id=getattr(actor, "id", None),
        description=f"Recurring {transaction_kind.value} \"{name}\" added.")
    SessionLocal.commit()
    return recurring


def soft_delete_recurring_transaction(recurring: RecurringTransaction, *, actor=None) -> None:
    recurring.deleted_at = _utcnow()
    recurring.active = False
    audit_service.log_change(
        "RecurringTransaction", recurring.id, "deleted", user_id=getattr(actor, "id", None),
        description=f"Recurring transaction \"{recurring.name}\" removed.")
    SessionLocal.commit()


_KIND_TO_TRANSACTION_TYPE = {
    RecurringTransactionKind.income: TransactionType.income,
    RecurringTransactionKind.expense: TransactionType.expense,
    RecurringTransactionKind.savings_contribution: TransactionType.expense,
    RecurringTransactionKind.debt_payment: TransactionType.expense,
}


def generate_due_transactions(workspace: FinancialWorkspace, *, today: date | None = None) -> list:
    """Gera uma `FinancialTransaction` pra toda `RecurringTransaction`
    ativa cujo `next_occurrence` já chegou (idempotente por construção:
    depois de gerar, `next_occurrence` avança pra frente, então rodar de
    novo no mesmo dia não gera duplicata). Se a agenda tem `account_id`
    mas ele foi excluído nesse meio tempo, a ocorrência é pulada (não
    trava a geração das outras) -- fica pra próxima chamada depois que o
    cliente corrigir a conta."""
    today = today or date.today()
    created = []

    for recurring in list_recurring_transactions(workspace):
        while recurring.next_occurrence is not None and recurring.next_occurrence <= today:
            if recurring.end_date and recurring.next_occurrence > recurring.end_date:
                recurring.next_occurrence = None
                break
            if recurring.account_id is None:
                break  # sem conta pra lançar -- não gera, não avança

            classification = (
                TransactionClassification.savings
                if recurring.transaction_kind == RecurringTransactionKind.savings_contribution else None
            )
            try:
                transaction = tx_svc.create_transaction(
                    workspace, actor=None, transaction_type=_KIND_TO_TRANSACTION_TYPE[recurring.transaction_kind],
                    name=recurring.name, amount_cents=recurring.amount_cents,
                    transaction_date=recurring.next_occurrence, account_id=recurring.account_id,
                    classification=classification,
                    notes=f"Auto-generated from recurring schedule ({recurring.frequency.value}).",
                )
            except TransactionValidationError:
                break  # conta inválida por algum motivo -- não trava as outras agendas
            created.append(transaction)

            next_date = _advance(recurring.next_occurrence, recurring.frequency)
            if next_date is None or (recurring.end_date and next_date > recurring.end_date):
                recurring.next_occurrence = None
            else:
                recurring.next_occurrence = next_date

    if created:
        SessionLocal.commit()
    return created


# --------------------------------------------------------------------------
# Recurring Debits (assinaturas) -- só registro/análise, nunca gera transação
# --------------------------------------------------------------------------

def list_recurring_debits(workspace: FinancialWorkspace, *, include_inactive: bool = False) -> list[RecurringDebit]:
    query = (
        SessionLocal.query(RecurringDebit).filter_by(financial_workspace_id=workspace.id)
        .filter(RecurringDebit.deleted_at.is_(None))
    )
    if not include_inactive:
        query = query.filter_by(active=True)
    return query.order_by(RecurringDebit.merchant).all()


def create_recurring_debit(
    workspace: FinancialWorkspace, *, actor, merchant: str, description: str | None = None,
    amount_cents: int, frequency: BillFrequency = BillFrequency.monthly,
    next_charge_date: date | None = None, budget_category_id: int | None = None,
    account_id: int | None = None, autopay: bool = True, notes: str | None = None,
) -> RecurringDebit:
    if not merchant:
        raise RecurringValidationError("Merchant/service name is required.")
    if amount_cents is None or amount_cents <= 0:
        raise RecurringValidationError("Amount must be greater than zero.")
    _check_account_ownership(account_id, workspace.id)
    _check_category_ownership(budget_category_id, workspace.id)

    debit = RecurringDebit(
        financial_workspace_id=workspace.id, merchant=merchant, description=description or None,
        amount_cents=amount_cents, frequency=frequency, next_charge_date=next_charge_date,
        budget_category_id=budget_category_id, account_id=account_id, autopay=autopay,
        notes=notes or None, created_by_id=getattr(actor, "id", None),
    )
    SessionLocal.add(debit)
    SessionLocal.flush()
    audit_service.log_change(
        "RecurringDebit", debit.id, "created", user_id=getattr(actor, "id", None),
        description=f"Subscription/recurring debit \"{merchant}\" added.")
    SessionLocal.commit()
    return debit


def set_review_status(debit: RecurringDebit, review_status: ReviewStatus) -> RecurringDebit:
    """Marcar `cancel` é só a INTENÇÃO do cliente -- não desativa o
    registro nem some da análise. A assinatura continua contando como
    "ativa" (ainda está sendo cobrada de verdade) até o cliente
    confirmar que já cancelou de fato com o provedor e remover o item
    (`soft_delete_recurring_debit`, que aí sim desativa). Isso é o que
    permite `potential_monthly_savings_cents` mostrar quanto dá pra
    economizar cancelando o que já foi flagado, em vez de já ter
    desaparecido do total assim que marcado."""
    debit.review_status = review_status
    if review_status == ReviewStatus.cancel and debit.cancelled_at is None:
        debit.cancelled_at = _utcnow()
    SessionLocal.commit()
    return debit


def soft_delete_recurring_debit(debit: RecurringDebit, *, actor=None) -> None:
    debit.deleted_at = _utcnow()
    debit.active = False
    audit_service.log_change(
        "RecurringDebit", debit.id, "deleted", user_id=getattr(actor, "id", None),
        description=f"Subscription/recurring debit \"{debit.merchant}\" removed.")
    SessionLocal.commit()


_MONTHLY_MULTIPLIER = {
    BillFrequency.weekly: 52 / 12,
    BillFrequency.biweekly: 26 / 12,
    BillFrequency.monthly: 1.0,
    BillFrequency.quarterly: 1 / 3,
    BillFrequency.semiannual: 1 / 6,
    BillFrequency.annual: 1 / 12,
}


def _monthly_equivalent_cents(debit: RecurringDebit) -> int | None:
    """`None` pra `custom` -- não dá pra normalizar uma cadência
    arbitrária pra "por mês" sem inventar dado; esses itens aparecem na
    lista mas ficam de fora do total agregado."""
    multiplier = _MONTHLY_MULTIPLIER.get(debit.frequency)
    return round(debit.amount_cents * multiplier) if multiplier is not None else None


def subscription_summary(workspace: FinancialWorkspace) -> dict:
    """"Subscription analysis" (§11) -- custo mensal equivalente de tudo
    que está ativo, quebrado por `review_status`, e quanto dá pra
    economizar cancelando de verdade o que já foi marcado `cancel` (mas
    ainda está `active=True` -- marcar `cancel` aqui é uma INTENÇÃO, não
    a ação de cancelar de verdade com o provedor)."""
    debits = list_recurring_debits(workspace)
    by_status: dict[str, dict] = {
        s.value: {"count": 0, "monthly_cents": 0} for s in ReviewStatus
    }
    total_monthly_cents = 0
    excluded_custom_count = 0

    for debit in debits:
        monthly = _monthly_equivalent_cents(debit)
        bucket = by_status[debit.review_status.value]
        bucket["count"] += 1
        if monthly is None:
            excluded_custom_count += 1
            continue
        bucket["monthly_cents"] += monthly
        total_monthly_cents += monthly

    return {
        "total_active_monthly_cents": total_monthly_cents,
        "by_status": by_status,
        "potential_monthly_savings_cents": by_status[ReviewStatus.cancel.value]["monthly_cents"],
        "excluded_custom_count": excluded_custom_count,
    }
