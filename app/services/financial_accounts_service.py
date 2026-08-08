"""Fase 2 do SAES_Financial_Planning_Master_Spec -- CRUD de Account
("onde está meu dinheiro?"). Saldo é um valor que o CLIENTE informa/
atualiza manualmente (mesmo modelo do documento -- não é
contabilidade de partida dobrada derivada das transações; `current_
balance_cents` é editável direto, `FinancialTransaction` é só o
livro-razão de renda/despesa/transferência pro orçamento e fluxo de
caixa, os dois convivem sem um recalcular o outro)."""
from __future__ import annotations

from datetime import datetime, timezone

from app.crm_financial_models import FinancialWorkspace
from app.db import SessionLocal
from app.financial_planning_models import Account, AccountType
from app.services import audit_service


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def list_accounts(workspace: FinancialWorkspace, *, include_deleted: bool = False) -> list[Account]:
    query = SessionLocal.query(Account).filter_by(financial_workspace_id=workspace.id)
    if not include_deleted:
        query = query.filter(Account.deleted_at.is_(None))
    return query.order_by(Account.account_name).all()


def create_account(
    workspace: FinancialWorkspace, *, actor,
    account_name: str, account_type: AccountType, institution_name: str | None = None,
    nickname: str | None = None, last_four_digits: str | None = None,
    current_balance_cents: int = 0, available_balance_cents: int | None = None,
    currency: str = "USD", include_in_cash_flow: bool = True, include_in_net_worth: bool = True,
    notes: str | None = None,
) -> Account:
    account = Account(
        financial_workspace_id=workspace.id, account_name=account_name, account_type=account_type,
        institution_name=institution_name or None, nickname=nickname or None,
        last_four_digits=(last_four_digits or None), current_balance_cents=current_balance_cents,
        available_balance_cents=available_balance_cents, currency=currency,
        include_in_cash_flow=include_in_cash_flow, include_in_net_worth=include_in_net_worth,
        notes=notes or None, created_by_id=getattr(actor, "id", None),
    )
    SessionLocal.add(account)
    SessionLocal.flush()
    # Cobertura de auditoria pro CRUD de rotina do módulo (item pendente
    # do Prompt Mestre 2, Fase 13 -- antes só mudança de acesso/fechar-
    # reabrir mês/importação CSV eram auditados). `actor` aqui é o
    # PRÓPRIO cliente (self-service), não um colaborador -- AuditLog.
    # user_id é genérico pra qualquer User, então funciona igual.
    audit_service.log_change(
        "Account", account.id, "created", user_id=getattr(actor, "id", None),
        description=f"Account \"{account_name}\" added.")
    SessionLocal.commit()
    return account


def update_account(account: Account, **fields) -> Account:
    for key, value in fields.items():
        setattr(account, key, value)
    SessionLocal.commit()
    return account


def soft_delete_account(account: Account, *, actor=None) -> None:
    """Nunca DELETE de verdade -- pedido explícito do documento ("Do not
    silently delete/overwrite financial data"). Uma conta excluída some
    das listagens padrão mas continua acessível pra histórico/auditoria."""
    account.deleted_at = _utcnow()
    account.active = False
    audit_service.log_change(
        "Account", account.id, "deleted", user_id=getattr(actor, "id", None),
        description=f"Account \"{account.account_name}\" removed.")
    SessionLocal.commit()
