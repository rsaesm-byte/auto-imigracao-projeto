"""financial planning fase 7: goals and savings

Revision ID: 13dfa58ee212
Revises: a43ad6a3818f
Create Date: 2026-08-07 15:45:29.317079

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '13dfa58ee212'
down_revision: Union[str, Sequence[str], None] = 'a43ad6a3818f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Só as 3 tabelas novas (app/financial_planning_models.py, Fase 7) e
    as 2 colunas novas em `financial_workspaces` (configuração do Fundo
    de Emergência, app/crm_financial_models.py) -- o autogenerate
    detectou de novo a mesma pilha de drift pré-existente e não
    relacionado já vista nas migrações anteriores; removida manualmente
    pelo mesmo motivo.

    Nota sobre `emergency_fund_account_id`: o model NÃO declara
    `ForeignKey` nesta coluna de propósito -- `financial_accounts.
    financial_workspace_id` já referencia `financial_workspaces`, e uma
    FK de volta daqui pra `financial_accounts` criaria uma dependência
    circular entre as duas tabelas (SQLAlchemy avisou "Cannot correctly
    sort tables ... unresolvable cycles" na primeira tentativa de gerar
    esta migração, com a FK declarada). Validado no service
    (`goals_service._check_account_ownership`), não no banco -- por
    isso as colunas novas em `financial_workspaces` saem como simples
    `ADD COLUMN` nullable, sem precisar do modo batch/PRAGMA foreign_keys
    OFF que a Fase 1 (c916339cd11e) precisou pra um caso parecido.
    """
    op.create_table('financial_goals',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('financial_workspace_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('goal_type', sa.String(), nullable=True),
    sa.Column('target_amount_cents', sa.Integer(), nullable=False),
    sa.Column('current_amount_cents', sa.Integer(), nullable=False),
    sa.Column('target_date', sa.Date(), nullable=True),
    sa.Column('monthly_contribution_cents', sa.Integer(), nullable=True),
    sa.Column('priority', sa.Enum('low', 'medium', 'high', name='goalpriority'), nullable=False),
    sa.Column('status', sa.Enum('active', 'paused', 'completed', 'cancelled', name='goalstatus'), nullable=False),
    sa.Column('account_id', sa.Integer(), nullable=True),
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
    with op.batch_alter_table('financial_goals', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_financial_goals_deleted_at'), ['deleted_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_financial_goals_financial_workspace_id'), ['financial_workspace_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_financial_goals_status'), ['status'], unique=False)

    op.create_table('financial_sinking_funds',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('financial_workspace_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('target_amount_cents', sa.Integer(), nullable=False),
    sa.Column('current_amount_cents', sa.Integer(), nullable=False),
    sa.Column('target_date', sa.Date(), nullable=True),
    sa.Column('monthly_contribution_cents', sa.Integer(), nullable=True),
    sa.Column('account_id', sa.Integer(), nullable=True),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('created_by_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('deleted_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['account_id'], ['financial_accounts.id'], ),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['financial_workspace_id'], ['financial_workspaces.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('financial_sinking_funds', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_financial_sinking_funds_deleted_at'), ['deleted_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_financial_sinking_funds_financial_workspace_id'), ['financial_workspace_id'], unique=False)

    op.create_table('financial_goal_contributions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('goal_id', sa.Integer(), nullable=False),
    sa.Column('amount_cents', sa.Integer(), nullable=False),
    sa.Column('contribution_date', sa.Date(), nullable=False),
    sa.Column('from_account_id', sa.Integer(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['from_account_id'], ['financial_accounts.id'], ),
    sa.ForeignKeyConstraint(['goal_id'], ['financial_goals.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('financial_goal_contributions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_financial_goal_contributions_contribution_date'), ['contribution_date'], unique=False)
        batch_op.create_index(batch_op.f('ix_financial_goal_contributions_goal_id'), ['goal_id'], unique=False)

    with op.batch_alter_table('financial_workspaces', schema=None) as batch_op:
        batch_op.add_column(sa.Column('emergency_fund_target_months', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('emergency_fund_account_id', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('financial_workspaces', schema=None) as batch_op:
        batch_op.drop_column('emergency_fund_account_id')
        batch_op.drop_column('emergency_fund_target_months')

    with op.batch_alter_table('financial_goal_contributions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_financial_goal_contributions_goal_id'))
        batch_op.drop_index(batch_op.f('ix_financial_goal_contributions_contribution_date'))

    op.drop_table('financial_goal_contributions')
    with op.batch_alter_table('financial_sinking_funds', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_financial_sinking_funds_financial_workspace_id'))
        batch_op.drop_index(batch_op.f('ix_financial_sinking_funds_deleted_at'))

    op.drop_table('financial_sinking_funds')
    with op.batch_alter_table('financial_goals', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_financial_goals_status'))
        batch_op.drop_index(batch_op.f('ix_financial_goals_financial_workspace_id'))
        batch_op.drop_index(batch_op.f('ix_financial_goals_deleted_at'))

    op.drop_table('financial_goals')
