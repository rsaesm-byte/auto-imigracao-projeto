"""financial planning fase 5: bills

Revision ID: 8bce6350b918
Revises: 0eea543428d1
Create Date: 2026-08-07 13:29:54.813639

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8bce6350b918'
down_revision: Union[str, Sequence[str], None] = '0eea543428d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Só as 2 tabelas novas (app/financial_planning_models.py, Fase 5) --
    o autogenerate detectou de novo a mesma pilha de drift pré-existente
    e não relacionado já vista nas migrações anteriores; removida
    manualmente pelo mesmo motivo. Todas `create_table` puro, sem FK em
    tabela já existente -- não bate no problema de recriação da
    migração da Fase 1 (c916339cd11e).

    Desta vez a modelagem nova foi verificada rodando a suíte pytest
    (banco isolado) ANTES de gerar esta migração, em vez de um
    `create_app()` direto contra o banco real -- a lição da Fase 4
    (0eea543428d1) foi aplicada aqui, sem repetir o problema.
    """
    op.create_table('financial_bills',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('financial_workspace_id', sa.Integer(), nullable=False),
    sa.Column('bill_name', sa.String(), nullable=False),
    sa.Column('budget_category_id', sa.Integer(), nullable=True),
    sa.Column('default_amount_cents', sa.Integer(), nullable=True),
    sa.Column('due_day', sa.Integer(), nullable=True),
    sa.Column('frequency', sa.Enum('weekly', 'biweekly', 'monthly', 'quarterly', 'semiannual', 'annual', 'custom', name='billfrequency'), nullable=False),
    sa.Column('default_payment_account_id', sa.Integer(), nullable=True),
    sa.Column('autopay', sa.Boolean(), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('start_date', sa.Date(), nullable=True),
    sa.Column('end_date', sa.Date(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_by_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('deleted_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['budget_category_id'], ['financial_budget_categories.id'], ),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['default_payment_account_id'], ['financial_accounts.id'], ),
    sa.ForeignKeyConstraint(['financial_workspace_id'], ['financial_workspaces.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('financial_bills', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_financial_bills_deleted_at'), ['deleted_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_financial_bills_financial_workspace_id'), ['financial_workspace_id'], unique=False)

    op.create_table('financial_bill_payments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('bill_id', sa.Integer(), nullable=False),
    sa.Column('billing_month', sa.Date(), nullable=False),
    sa.Column('amount_cents', sa.Integer(), nullable=False),
    sa.Column('status', sa.Enum('upcoming', 'to_pay', 'scheduled', 'paid', 'overdue', 'skipped', 'cancelled', name='billpaymentstatus'), nullable=False),
    sa.Column('due_date', sa.Date(), nullable=False),
    sa.Column('scheduled_date', sa.Date(), nullable=True),
    sa.Column('paid_date', sa.Date(), nullable=True),
    sa.Column('paid_from_account_id', sa.Integer(), nullable=True),
    sa.Column('confirmation_number', sa.String(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['bill_id'], ['financial_bills.id'], ),
    sa.ForeignKeyConstraint(['paid_from_account_id'], ['financial_accounts.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('bill_id', 'billing_month', name='uq_bill_payment_bill_month')
    )
    with op.batch_alter_table('financial_bill_payments', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_financial_bill_payments_bill_id'), ['bill_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_financial_bill_payments_billing_month'), ['billing_month'], unique=False)
        batch_op.create_index(batch_op.f('ix_financial_bill_payments_due_date'), ['due_date'], unique=False)
        batch_op.create_index(batch_op.f('ix_financial_bill_payments_status'), ['status'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('financial_bill_payments', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_financial_bill_payments_status'))
        batch_op.drop_index(batch_op.f('ix_financial_bill_payments_due_date'))
        batch_op.drop_index(batch_op.f('ix_financial_bill_payments_billing_month'))
        batch_op.drop_index(batch_op.f('ix_financial_bill_payments_bill_id'))

    op.drop_table('financial_bill_payments')
    with op.batch_alter_table('financial_bills', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_financial_bills_financial_workspace_id'))
        batch_op.drop_index(batch_op.f('ix_financial_bills_deleted_at'))

    op.drop_table('financial_bills')
