"""Fase 8 (Debt Management) do SAES_Financial_Planning_Master_Spec,
2026-08-07 -- registro unificado de dívida, histórico de pagamentos,
ordenação snowball/avalanche/custom, e o simulador de quitação
(amortização simples: saldo/APR/mínimo/extra).

Fórmulas exatamente como o documento define (§8):
- `paid_amount`: max(original - current, 0).
- `progress`: paid_amount/original quando original > 0.
- `snowball_order`: saldo atual crescente.
- `avalanche_order`: APR decrescente.
- `payoff_projection`: "amortization simulation using balance/APR/
  minimum/extra" -- simulação mês a mês por dívida (não um "waterfall"
  entre dívidas -- rolar o pagamento de uma dívida quitada pra próxima
  não está nesta fase; a ordenação já ajuda o cliente a escolher POR
  ONDE começar, o "quanto sobra pra próxima" fica pra uma fase
  seguinte se pedido).
"""
from __future__ import annotations

import calendar as _calendar
from datetime import date, datetime, timezone

from app.crm_financial_models import FinancialWorkspace
from app.db import SessionLocal
from app.financial_planning_models import (Account, Debt, DebtPayment, DebtStatus, DebtType,
                                            PayoffStrategy)

_MAX_PROJECTION_MONTHS = 600  # 50 anos -- teto de segurança contra pagamento que nunca quita


class DebtValidationError(ValueError):
    pass


def _check_account_ownership(account_id: int | None, workspace_id: int) -> None:
    if account_id is None:
        return
    account = SessionLocal.get(Account, account_id)
    if account is None or account.financial_workspace_id != workspace_id:
        raise DebtValidationError("Account does not belong to this workspace.")


def _add_months(d: date, months: int) -> date:
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    last_day = _calendar.monthrange(year, month)[1]
    return date(year, month, min(d.day, last_day))


# --------------------------------------------------------------------------
# Debts
# --------------------------------------------------------------------------

def list_debts(workspace: FinancialWorkspace, *, include_inactive: bool = False) -> list[Debt]:
    query = (
        SessionLocal.query(Debt).filter_by(financial_workspace_id=workspace.id)
        .filter(Debt.deleted_at.is_(None))
    )
    if not include_inactive:
        query = query.filter(Debt.status != DebtStatus.paid_off)
    return query.order_by(Debt.debt_name).all()


def create_debt(
    workspace: FinancialWorkspace, *, actor, debt_name: str, current_balance_cents: int,
    lender_name: str | None = None, debt_type: DebtType = DebtType.other,
    original_balance_cents: int | None = None, apr_bps: int | None = None,
    minimum_payment_cents: int | None = None, extra_monthly_payment_cents: int | None = None,
    due_day: int | None = None, target_payoff_date: date | None = None,
    custom_priority: int | None = None, notes: str | None = None,
) -> Debt:
    if not debt_name:
        raise DebtValidationError("Debt name is required.")
    if current_balance_cents is None or current_balance_cents < 0:
        raise DebtValidationError("Current balance cannot be negative.")
    if due_day is not None and not (1 <= due_day <= 31):
        raise DebtValidationError("Due day must be between 1 and 31.")

    debt = Debt(
        financial_workspace_id=workspace.id, debt_name=debt_name, lender_name=lender_name or None,
        debt_type=debt_type, original_balance_cents=original_balance_cents,
        current_balance_cents=current_balance_cents, apr_bps=apr_bps,
        minimum_payment_cents=minimum_payment_cents, extra_monthly_payment_cents=extra_monthly_payment_cents,
        due_day=due_day, target_payoff_date=target_payoff_date, custom_priority=custom_priority,
        notes=notes or None, created_by_id=getattr(actor, "id", None),
    )
    SessionLocal.add(debt)
    SessionLocal.commit()
    return debt


def soft_delete_debt(debt: Debt) -> None:
    debt.deleted_at = datetime.now(timezone.utc)
    SessionLocal.commit()


def record_payment(
    debt: Debt, *, amount_cents: int, payment_date: date, principal_amount_cents: int | None = None,
    interest_amount_cents: int | None = None, paid_from_account_id: int | None = None,
    notes: str | None = None,
) -> DebtPayment:
    if amount_cents is None or amount_cents <= 0:
        raise DebtValidationError("Payment amount must be greater than zero.")
    _check_account_ownership(paid_from_account_id, debt.financial_workspace_id)

    principal = principal_amount_cents if principal_amount_cents is not None else amount_cents
    payment = DebtPayment(
        debt_id=debt.id, amount_cents=amount_cents, principal_amount_cents=principal_amount_cents,
        interest_amount_cents=interest_amount_cents, payment_date=payment_date,
        paid_from_account_id=paid_from_account_id, notes=notes or None,
    )
    SessionLocal.add(payment)
    debt.current_balance_cents = max(debt.current_balance_cents - principal, 0)
    if debt.current_balance_cents == 0:
        debt.status = DebtStatus.paid_off
    SessionLocal.commit()
    return payment


def list_payments(debt: Debt) -> list[DebtPayment]:
    return (
        SessionLocal.query(DebtPayment).filter_by(debt_id=debt.id)
        .order_by(DebtPayment.payment_date.desc(), DebtPayment.id.desc()).all()
    )


def debt_progress(debt: Debt) -> dict:
    if not debt.original_balance_cents:
        return {"paid_amount_cents": None, "progress": None}
    paid_amount_cents = max(debt.original_balance_cents - debt.current_balance_cents, 0)
    progress = paid_amount_cents / debt.original_balance_cents
    return {"paid_amount_cents": paid_amount_cents, "progress": progress}


def payoff_projection(debt: Debt, *, today: date | None = None) -> dict | None:
    """`None` quando não dá pra projetar de verdade -- sem pagamento
    mensal configurado, ou o pagamento nem cobre os juros (nunca quita
    nesse ritmo). Nunca finge um número."""
    today = today or date.today()
    if debt.current_balance_cents <= 0:
        return {"months_to_payoff": 0, "total_interest_cents": 0, "payoff_date": today}

    monthly_payment = (debt.minimum_payment_cents or 0) + (debt.extra_monthly_payment_cents or 0)
    if monthly_payment <= 0:
        return None

    monthly_rate = (debt.apr_bps or 0) / 10_000 / 12  # bps (1999 = 19.99%) -> fração anual -> taxa mensal
    balance = debt.current_balance_cents
    total_interest_cents = 0
    months = 0
    while balance > 0 and months < _MAX_PROJECTION_MONTHS:
        interest = round(balance * monthly_rate)
        payment = min(monthly_payment, balance + interest)
        principal = payment - interest
        if principal <= 0:
            return None  # pagamento não cobre nem os juros -- nunca quita nesse ritmo
        balance -= principal
        total_interest_cents += interest
        months += 1

    if balance > 0:
        return None  # excedeu o teto de segurança (50 anos)

    return {
        "months_to_payoff": months, "total_interest_cents": total_interest_cents,
        "payoff_date": _add_months(today, months),
    }


def ordered_debts(workspace: FinancialWorkspace, *, strategy: PayoffStrategy = PayoffStrategy.snowball) -> list[Debt]:
    """Ordem de ataque pro "Debt Payoff Plan" -- calculada na hora a
    partir da lista de dívidas ativas, nunca salva (mesmo espírito do
    Fundo de Emergência, Fase 7): trocar a estratégia na tela reordena
    sozinho, sem precisar editar cada dívida."""
    debts = [d for d in list_debts(workspace) if d.status in (DebtStatus.active, DebtStatus.delinquent)]
    if strategy == PayoffStrategy.avalanche:
        return sorted(debts, key=lambda d: -(d.apr_bps or 0))
    if strategy == PayoffStrategy.custom:
        return sorted(debts, key=lambda d: (d.custom_priority is None, d.custom_priority or 0))
    return sorted(debts, key=lambda d: d.current_balance_cents)


def workspace_debt_summary(workspace: FinancialWorkspace) -> dict:
    debts = list_debts(workspace)
    return {
        "total_balance_cents": sum(d.current_balance_cents for d in debts),
        "total_minimum_payment_cents": sum(d.minimum_payment_cents or 0 for d in debts),
        "count": len(debts),
    }
