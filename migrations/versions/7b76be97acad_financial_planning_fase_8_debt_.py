"""financial planning fase 8: debt management

Revision ID: 7b76be97acad
Revises: 13dfa58ee212
Create Date: 2026-08-07 16:08:23.377012

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7b76be97acad'
down_revision: Union[str, Sequence[str], None] = '13dfa58ee212'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Só as 2 tabelas novas (app/financial_planning_models.py, Fase 8) --
    o autogenerate detectou de novo a mesma pilha de drift pré-existente
    e não relacionado já vista nas migrações anteriores; removida
    manualmente pelo mesmo motivo. Todas `create_table` puro, sem FK em
    tabela já existente.
    """
    op.create_table('financial_debts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('financial_workspace_id', sa.Integer(), nullable=False),
    sa.Column('debt_name', sa.String(), nullable=False),
    sa.Column('lender_name', sa.String(), nullable=True),
    sa.Column('debt_type', sa.Enum('credit_card', 'personal_loan', 'student_loan', 'auto_loan', 'mortgage', 'line_of_credit', 'medical', 'installment_plan', 'other', name='debttype'), nullable=False),
    sa.Column('original_balance_cents', sa.Integer(), nullable=True),
    sa.Column('current_balance_cents', sa.Integer(), nullable=False),
    sa.Column('apr_bps', sa.Integer(), nullable=True),
    sa.Column('minimum_payment_cents', sa.Integer(), nullable=True),
    sa.Column('extra_monthly_payment_cents', sa.Integer(), nullable=True),
    sa.Column('due_day', sa.Integer(), nullable=True),
    sa.Column('payment_frequency', sa.Enum('weekly', 'biweekly', 'monthly', 'quarterly', 'semiannual', 'annual', 'custom', name='billfrequency'), nullable=False),
    sa.Column('payoff_strategy', sa.Enum('snowball', 'avalanche', 'custom', name='payoffstrategy'), nullable=False),
    sa.Column('custom_priority', sa.Integer(), nullable=True),
    sa.Column('target_payoff_date', sa.Date(), nullable=True),
    sa.Column('status', sa.Enum('planned', 'active', 'delinquent', 'paid_off', name='debtstatus'), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_by_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('deleted_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['financial_workspace_id'], ['financial_workspaces.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('financial_debts', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_financial_debts_deleted_at'), ['deleted_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_financial_debts_financial_workspace_id'), ['financial_workspace_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_financial_debts_status'), ['status'], unique=False)

    op.create_table('financial_debt_payments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('debt_id', sa.Integer(), nullable=False),
    sa.Column('amount_cents', sa.Integer(), nullable=False),
    sa.Column('principal_amount_cents', sa.Integer(), nullable=True),
    sa.Column('interest_amount_cents', sa.Integer(), nullable=True),
    sa.Column('payment_date', sa.Date(), nullable=False),
    sa.Column('paid_from_account_id', sa.Integer(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['debt_id'], ['financial_debts.id'], ),
    sa.ForeignKeyConstraint(['paid_from_account_id'], ['financial_accounts.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('financial_debt_payments', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_financial_debt_payments_debt_id'), ['debt_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_financial_debt_payments_payment_date'), ['payment_date'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('financial_debt_payments', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_financial_debt_payments_payment_date'))
        batch_op.drop_index(batch_op.f('ix_financial_debt_payments_debt_id'))

    op.drop_table('financial_debt_payments')
    with op.batch_alter_table('financial_debts', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_financial_debts_status'))
        batch_op.drop_index(batch_op.f('ix_financial_debts_financial_workspace_id'))
        batch_op.drop_index(batch_op.f('ix_financial_debts_deleted_at'))

    op.drop_table('financial_debts')
