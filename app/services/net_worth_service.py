"""Fase 9 (Net Worth) do SAES_Financial_Planning_Master_Spec, 2026-08-07 --
saldo histórico de conta, métricas de patrimônio líquido, e o dado do
gráfico histórico (§11 "Net Worth: Assets, Liabilities, Net Worth").

Fórmula exatamente como o documento define (§8):
- `net_worth`: included asset/account balances - active debt balances.

Nenhuma tabela nova pra histórico de dívida -- o documento só define
`account_balance_snapshots` (contas), não um equivalente pra dívidas. O
histórico de PASSIVO é reconstruído a partir de dado que já existe
(`Debt.original_balance_cents` - pagamentos de principal até a data),
mesmo espírito "calculado na hora, nunca guardado 2x" já usado no Fundo de
Emergência (Fase 7) e na ordenação snowball/avalanche (Fase 8).
"""
from __future__ import annotations

from calendar import month_abbr
from datetime import date, datetime, timezone

from app.crm_financial_models import FinancialWorkspace
from app.db import SessionLocal
from app.financial_planning_models import (Account, AccountBalanceSnapshot, Debt, DebtPayment,
                                            DebtStatus, SnapshotSource)

_LIABILITY_STATUSES = (DebtStatus.active, DebtStatus.delinquent)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class NetWorthValidationError(ValueError):
    pass


# --------------------------------------------------------------------------
# Patrimônio atual
# --------------------------------------------------------------------------

def total_assets_cents(workspace: FinancialWorkspace) -> int:
    accounts = (
        SessionLocal.query(Account)
        .filter_by(financial_workspace_id=workspace.id, include_in_net_worth=True)
        .filter(Account.deleted_at.is_(None)).all()
    )
    return sum(a.current_balance_cents for a in accounts)


def total_liabilities_cents(workspace: FinancialWorkspace) -> int:
    debts = (
        SessionLocal.query(Debt)
        .filter_by(financial_workspace_id=workspace.id)
        .filter(Debt.deleted_at.is_(None), Debt.status.in_(_LIABILITY_STATUSES)).all()
    )
    return sum(d.current_balance_cents for d in debts)


def current_net_worth(workspace: FinancialWorkspace) -> dict:
    assets = total_assets_cents(workspace)
    liabilities = total_liabilities_cents(workspace)
    return {
        "assets_cents": assets, "liabilities_cents": liabilities,
        "net_worth_cents": assets - liabilities,
    }


# --------------------------------------------------------------------------
# Snapshots de saldo de conta
# --------------------------------------------------------------------------

def record_snapshot(
    account: Account, *, balance_cents: int, snapshot_date: date,
    source: SnapshotSource = SnapshotSource.manual, available_balance_cents: int | None = None,
) -> AccountBalanceSnapshot:
    snapshot = (
        SessionLocal.query(AccountBalanceSnapshot)
        .filter_by(account_id=account.id, snapshot_date=snapshot_date).first()
    )
    if snapshot is None:
        snapshot = AccountBalanceSnapshot(account_id=account.id, snapshot_date=snapshot_date)
        SessionLocal.add(snapshot)
    snapshot.balance_cents = balance_cents
    snapshot.available_balance_cents = available_balance_cents
    snapshot.source = source
    SessionLocal.commit()
    return snapshot


def list_snapshots(account: Account, *, limit: int = 12) -> list[AccountBalanceSnapshot]:
    return (
        SessionLocal.query(AccountBalanceSnapshot).filter_by(account_id=account.id)
        .order_by(AccountBalanceSnapshot.snapshot_date.desc()).limit(limit).all()
    )


def snapshot_month_close(workspace: FinancialWorkspace, *, snapshot_date: date) -> None:
    """Chamado por `budget_service.close_period` logo após fechar o mês --
    grava o saldo atual de cada conta ativa do workspace como um ponto
    histórico `month_close`, alimentando o gráfico de Net Worth com dado
    real conforme os meses vão sendo fechados (em vez de exigir que o
    cliente registre manualmente todo mês)."""
    accounts = (
        SessionLocal.query(Account).filter_by(financial_workspace_id=workspace.id)
        .filter(Account.deleted_at.is_(None)).all()
    )
    for account in accounts:
        record_snapshot(
            account, balance_cents=account.current_balance_cents, snapshot_date=snapshot_date,
            source=SnapshotSource.month_close, available_balance_cents=account.available_balance_cents)


# --------------------------------------------------------------------------
# Histórico (gráfico)
# --------------------------------------------------------------------------

def _debt_balance_as_of(debt: Debt, as_of: date) -> int:
    """Reconstrói o saldo ANDANDO PRA TRÁS a partir de `current_balance_
    cents` (a verdade de hoje) -- soma de volta o principal de todo
    pagamento feito DEPOIS de `as_of`. Deliberadamente não usa
    `original_balance_cents - pagamentos até a data` (a primeira versão
    fazia isso): esse cálculo, ANDANDO PRA FRENTE a partir do original,
    diverge da verdade quando um saldo foi ajustado sem passar por um
    `DebtPayment` de verdade (ex.: dívida cadastrada já com saldo
    parcialmente pago, sem histórico de pagamento pra explicar a
    diferença -- exatamente o caso da dívida "Student Loan" da conta
    demo, achado ao verificar este número ao vivo no Chrome). Ancorado em
    `current_balance_cents`, a reconstrução de HOJE é sempre exata por
    construção; sem nenhum pagamento registrado, o saldo é assumido
    constante pro passado (única suposição possível sem uma data de
    início explícita no schema -- melhor que divergir da verdade atual)."""
    payments_after = (
        SessionLocal.query(DebtPayment).filter_by(debt_id=debt.id)
        .filter(DebtPayment.payment_date > as_of).all()
    )
    principal_after_cents = sum(
        p.principal_amount_cents if p.principal_amount_cents is not None else p.amount_cents
        for p in payments_after)
    return debt.current_balance_cents + principal_after_cents


def net_worth_history(workspace: FinancialWorkspace, *, limit_points: int = 12) -> list[dict]:
    """Um ponto por data com pelo menos um snapshot de conta registrado
    (manual ou month_close) -- histórico só existe conforme snapshots vão
    sendo criados; lista vazia quando nenhum snapshot ainda existe
    (tratado como estado vazio na tela, nunca um gráfico inventado)."""
    account_ids = [
        a.id for a in SessionLocal.query(Account.id)
        .filter_by(financial_workspace_id=workspace.id, include_in_net_worth=True)
        .filter(Account.deleted_at.is_(None)).all()
    ]
    if not account_ids:
        return []

    dates = sorted({
        row[0] for row in SessionLocal.query(AccountBalanceSnapshot.snapshot_date)
        .filter(AccountBalanceSnapshot.account_id.in_(account_ids)).distinct().all()
    })
    dates = dates[-limit_points:]
    if not dates:
        return []

    debts = (
        SessionLocal.query(Debt).filter_by(financial_workspace_id=workspace.id)
        .filter(Debt.deleted_at.is_(None), Debt.status != DebtStatus.planned).all()
    )

    # Carry-forward: o saldo de cada conta na data X é o snapshot mais
    # recente <= X (nem toda conta tem um ponto em toda data do eixo).
    latest_by_account: dict[int, int] = {}
    rows = []
    for as_of in dates:
        day_snapshots = (
            SessionLocal.query(AccountBalanceSnapshot)
            .filter(AccountBalanceSnapshot.account_id.in_(account_ids),
                    AccountBalanceSnapshot.snapshot_date == as_of).all()
        )
        for snap in day_snapshots:
            latest_by_account[snap.account_id] = snap.balance_cents
        assets_cents = sum(latest_by_account.values())

        liabilities_cents = sum(_debt_balance_as_of(debt, as_of) for debt in debts)

        rows.append({
            "date": as_of, "label": f"{month_abbr[as_of.month]} {as_of.year}",
            "assets_cents": assets_cents, "liabilities_cents": liabilities_cents,
            "net_worth_cents": assets_cents - liabilities_cents,
        })
    return rows
