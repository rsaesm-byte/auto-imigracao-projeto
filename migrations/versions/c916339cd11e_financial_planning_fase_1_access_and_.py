"""financial planning fase 1: access and workspace

Revision ID: c916339cd11e
Revises: 44c687d10b77
Create Date: 2026-08-07 11:46:33.147515

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c916339cd11e'
down_revision: Union[str, Sequence[str], None] = '44c687d10b77'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    SAES_Financial_Planning_Master_Spec, Fase 1 (Acesso e Workspace) --
    o autogenerate também detectou a mesma pilha de drift pré-existente
    e não relacionado já vista nas migrações anteriores (44c687d10b77 e
    predecessoras); removida manualmente daqui pelo mesmo motivo
    (tratada à parte pelas funções `_ensure_*_column` em app/__init__.py).

    `server_default` nas colunas NOT NULL novas é necessário pra popular
    as linhas já existentes de `crm_financial_clients`/`users` (ambas
    não-vazias) -- o default do lado do Python já cobre linhas novas
    dali em diante.
    """
    op.create_table('financial_workspaces',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('financial_client_id', sa.Integer(), nullable=False),
    sa.Column('status', sa.Enum('not_eligible', 'eligible', 'active', 'paused', 'completed', 'cancelled', name='financialplanningstatus'), nullable=False),
    sa.Column('default_currency', sa.String(), nullable=False),
    sa.Column('timezone', sa.String(), nullable=True),
    sa.Column('budget_month_start_day', sa.SmallInteger(), nullable=False),
    sa.Column('created_by_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('deleted_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['financial_client_id'], ['crm_financial_clients.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('financial_workspaces', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_financial_workspaces_financial_client_id'), ['financial_client_id'], unique=True)

    # `crm_financial_clients` é referenciada por FK de várias outras
    # tabelas (crm_financial_client_*, crm_financial_tasks,
    # crm_coaching_sessions, financial_workspaces criada acima) --
    # adicionar as duas FKs novas abaixo força o modo batch do SQLite a
    # recriar a tabela inteira (SQLite não tem ALTER TABLE ADD
    # CONSTRAINT nativo), e recriar uma tabela-pai com FK ligada nela
    # falha com `foreign_keys=ON` (que app/db.py liga em toda conexão
    # nova). Desligado só durante este bloco, religado logo depois.
    op.execute("PRAGMA foreign_keys=OFF")
    with op.batch_alter_table('crm_financial_clients', schema=None) as batch_op:
        batch_op.add_column(sa.Column('financial_planning_enabled', sa.Boolean(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('financial_planning_status', sa.Enum('not_eligible', 'eligible', 'active', 'paused', 'completed', 'cancelled', name='financialplanningstatus'), nullable=False, server_default='not_eligible'))
        batch_op.add_column(sa.Column('financial_planning_plan', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('financial_planning_started_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('financial_planning_ends_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('financial_planning_enabled_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('financial_planning_enabled_by_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('financial_planning_disabled_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('financial_planning_disabled_by_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_crm_financial_clients_financial_planning_enabled'), ['financial_planning_enabled'], unique=False)
        batch_op.create_foreign_key('fk_crm_financial_clients_enabled_by', 'users', ['financial_planning_enabled_by_id'], ['id'])
        batch_op.create_foreign_key('fk_crm_financial_clients_disabled_by', 'users', ['financial_planning_disabled_by_id'], ['id'])
    op.execute("PRAGMA foreign_keys=ON")

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('financial_planning_manage_access', sa.Boolean(), nullable=False, server_default='0'))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('financial_planning_manage_access')

    op.execute("PRAGMA foreign_keys=OFF")
    with op.batch_alter_table('crm_financial_clients', schema=None) as batch_op:
        batch_op.drop_constraint('fk_crm_financial_clients_disabled_by', type_='foreignkey')
        batch_op.drop_constraint('fk_crm_financial_clients_enabled_by', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_crm_financial_clients_financial_planning_enabled'))
        batch_op.drop_column('financial_planning_disabled_by_id')
        batch_op.drop_column('financial_planning_disabled_at')
        batch_op.drop_column('financial_planning_enabled_by_id')
        batch_op.drop_column('financial_planning_enabled_at')
        batch_op.drop_column('financial_planning_ends_at')
        batch_op.drop_column('financial_planning_started_at')
        batch_op.drop_column('financial_planning_plan')
        batch_op.drop_column('financial_planning_status')
        batch_op.drop_column('financial_planning_enabled')
    op.execute("PRAGMA foreign_keys=ON")

    with op.batch_alter_table('financial_workspaces', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_financial_workspaces_financial_client_id'))

    op.drop_table('financial_workspaces')
