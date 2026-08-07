"""financial planning fase 6: recurring

Revision ID: 12acb47db395
Revises: 8bce6350b918
Create Date: 2026-08-07 13:57:35.463235

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '12acb47db395'
down_revision: Union[str, Sequence[str], None] = '8bce6350b918'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Só as 2 tabelas novas (app/financial_planning_models.py, Fase 6) --
    o autogenerate detectou de novo a mesma pilha de drift pré-existente
    e não relacionado já vista nas migrações anteriores; removida
    manualmente pelo mesmo motivo. Todas `create_table` puro, sem FK em
    tabela já existente.

    Nota: desta vez as tabelas foram criadas "de graça" no banco real
    por um caminho diferente do de sempre -- não um `create_app()`
    deliberado como sanity check, mas 2 scripts rápidos de consulta
    (`SessionLocal.query(FinancialClient)...`) rodados pra responder uma
    pergunta do usuário, DEPOIS que os models novos já estavam no
    arquivo mas ANTES da migração ser gerada. `create_app()` sempre
    chama `Base.metadata.create_all(engine)` por baixo -- não importa o
    motivo da chamada. Resolvido do mesmo jeito de sempre (tabelas
    vazias confirmadas, derrubadas manualmente, autogenerate rodado de
    novo). Lição reforçada de novo: qualquer `create_app()` contra o
    banco real, não só um sanity check explícito, é arriscado enquanto
    houver model novo não migrado ainda no arquivo.
    """
    op.create_table('financial_recurring_debits',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('financial_workspace_id', sa.Integer(), nullable=False),
    sa.Column('merchant', sa.String(), nullable=False),
    sa.Column('description', sa.String(), nullable=True),
    sa.Column('amount_cents', sa.Integer(), nullable=False),
    sa.Column('frequency', sa.Enum('weekly', 'biweekly', 'monthly', 'quarterly', 'semiannual', 'annual', 'custom', name='billfrequency'), nullable=False),
    sa.Column('next_charge_date', sa.Date(), nullable=True),
    sa.Column('budget_category_id', sa.Integer(), nullable=True),
    sa.Column('account_id', sa.Integer(), nullable=True),
    sa.Column('autopay', sa.Boolean(), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('review_status', sa.Enum('keep', 'review', 'cancel', name='reviewstatus'), nullable=False),
    sa.Column('cancelled_at', sa.DateTime(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_by_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('deleted_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['account_id'], ['financial_accounts.id'], ),
    sa.ForeignKeyConstraint(['budget_category_id'], ['financial_budget_categories.id'], ),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['financial_workspace_id'], ['financial_workspaces.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('financial_recurring_debits', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_financial_recurring_debits_deleted_at'), ['deleted_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_financial_recurring_debits_financial_workspace_id'), ['financial_workspace_id'], unique=False)

    op.create_table('financial_recurring_transactions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('financial_workspace_id', sa.Integer(), nullable=False),
    sa.Column('transaction_kind', sa.Enum('income', 'expense', 'savings_contribution', 'debt_payment', name='recurringtransactionkind'), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('amount_cents', sa.Integer(), nullable=False),
    sa.Column('frequency', sa.Enum('weekly', 'biweekly', 'monthly', 'quarterly', 'semiannual', 'annual', 'custom', name='billfrequency'), nullable=False),
    sa.Column('start_date', sa.Date(), nullable=False),
    sa.Column('end_date', sa.Date(), nullable=True),
    sa.Column('next_occurrence', sa.Date(), nullable=True),
    sa.Column('account_id', sa.Integer(), nullable=True),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_by_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('deleted_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['account_id'], ['financial_accounts.id'], ),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['financial_workspace_id'], ['financial_workspaces.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('financial_recurring_transactions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_financial_recurring_transactions_deleted_at'), ['deleted_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_financial_recurring_transactions_financial_workspace_id'), ['financial_workspace_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_financial_recurring_transactions_next_occurrence'), ['next_occurrence'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('financial_recurring_transactions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_financial_recurring_transactions_next_occurrence'))
        batch_op.drop_index(batch_op.f('ix_financial_recurring_transactions_financial_workspace_id'))
        batch_op.drop_index(batch_op.f('ix_financial_recurring_transactions_deleted_at'))

    op.drop_table('financial_recurring_transactions')
    with op.batch_alter_table('financial_recurring_debits', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_financial_recurring_debits_financial_workspace_id'))
        batch_op.drop_index(batch_op.f('ix_financial_recurring_debits_deleted_at'))

    op.drop_table('financial_recurring_debits')
