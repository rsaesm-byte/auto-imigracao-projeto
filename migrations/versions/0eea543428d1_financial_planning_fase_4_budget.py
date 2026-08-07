"""financial planning fase 4: budget

Revision ID: 0eea543428d1
Revises: e8a11a090064
Create Date: 2026-08-07 12:56:33.049434

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0eea543428d1'
down_revision: Union[str, Sequence[str], None] = 'e8a11a090064'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Só as 4 tabelas novas (app/financial_planning_models.py, Fase 4) --
    o autogenerate detectou de novo a mesma pilha de drift pré-existente
    e não relacionado já vista nas migrações anteriores; removida
    manualmente pelo mesmo motivo. Todas `create_table` puro, sem FK em
    tabela já existente -- não bate no problema de recriação da
    migração da Fase 1 (c916339cd11e).

    Nota: o autogenerate quase não detectou estas 4 tabelas -- rodei
    `create_app()` (que chama `Base.metadata.create_all()`) antes de
    gerar esta migração, o que as criou "de graça" no banco de
    desenvolvimento primeiro. Precisei derrubar as 4 tabelas soltas e
    gerar de novo pra esta migração realmente conter os `create_table`.
    Mesma armadilha já documentada no Prompt Mestre (entrada da Fase 3/
    Dashboard) -- registrando de novo aqui como lembrete.
    """
    op.create_table('financial_budget_periods',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('financial_workspace_id', sa.Integer(), nullable=False),
    sa.Column('period_start', sa.Date(), nullable=False),
    sa.Column('period_end', sa.Date(), nullable=False),
    sa.Column('status', sa.Enum('open', 'closed', 'reopened', name='budgetperiodstatus'), nullable=False),
    sa.Column('closed_at', sa.DateTime(), nullable=True),
    sa.Column('closed_by_id', sa.Integer(), nullable=True),
    sa.Column('reopened_at', sa.DateTime(), nullable=True),
    sa.Column('reopened_by_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['closed_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['financial_workspace_id'], ['financial_workspaces.id'], ),
    sa.ForeignKeyConstraint(['reopened_by_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('financial_budget_periods', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_financial_budget_periods_financial_workspace_id'), ['financial_workspace_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_financial_budget_periods_period_start'), ['period_start'], unique=False)

    op.create_table('financial_budget_rules',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('financial_workspace_id', sa.Integer(), nullable=False),
    sa.Column('rule_type', sa.Enum('fifty_thirty_twenty', 'custom_percentage', 'category_budget', 'none', name='budgetruletype'), nullable=False),
    sa.Column('needs_percent', sa.Integer(), nullable=True),
    sa.Column('wants_percent', sa.Integer(), nullable=True),
    sa.Column('savings_percent', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['financial_workspace_id'], ['financial_workspaces.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('financial_budget_rules', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_financial_budget_rules_financial_workspace_id'), ['financial_workspace_id'], unique=True)

    op.create_table('financial_budget_allocations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('budget_period_id', sa.Integer(), nullable=False),
    sa.Column('budget_category_id', sa.Integer(), nullable=False),
    sa.Column('planned_amount_cents', sa.Integer(), nullable=False),
    sa.Column('rollover_enabled', sa.Boolean(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['budget_category_id'], ['financial_budget_categories.id'], ),
    sa.ForeignKeyConstraint(['budget_period_id'], ['financial_budget_periods.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('budget_period_id', 'budget_category_id', name='uq_budget_allocation_period_category')
    )
    with op.batch_alter_table('financial_budget_allocations', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_financial_budget_allocations_budget_category_id'), ['budget_category_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_financial_budget_allocations_budget_period_id'), ['budget_period_id'], unique=False)

    op.create_table('financial_month_snapshots',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('financial_workspace_id', sa.Integer(), nullable=False),
    sa.Column('budget_period_id', sa.Integer(), nullable=False),
    sa.Column('snapshot_json', sa.JSON(), nullable=False),
    sa.Column('created_by_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['budget_period_id'], ['financial_budget_periods.id'], ),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['financial_workspace_id'], ['financial_workspaces.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('financial_month_snapshots', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_financial_month_snapshots_budget_period_id'), ['budget_period_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_financial_month_snapshots_financial_workspace_id'), ['financial_workspace_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('financial_month_snapshots', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_financial_month_snapshots_financial_workspace_id'))
        batch_op.drop_index(batch_op.f('ix_financial_month_snapshots_budget_period_id'))

    op.drop_table('financial_month_snapshots')
    with op.batch_alter_table('financial_budget_allocations', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_financial_budget_allocations_budget_period_id'))
        batch_op.drop_index(batch_op.f('ix_financial_budget_allocations_budget_category_id'))

    op.drop_table('financial_budget_allocations')
    with op.batch_alter_table('financial_budget_rules', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_financial_budget_rules_financial_workspace_id'))

    op.drop_table('financial_budget_rules')
    with op.batch_alter_table('financial_budget_periods', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_financial_budget_periods_period_start'))
        batch_op.drop_index(batch_op.f('ix_financial_budget_periods_financial_workspace_id'))

    op.drop_table('financial_budget_periods')
