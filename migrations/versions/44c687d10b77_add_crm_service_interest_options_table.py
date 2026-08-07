"""add crm_service_interest_options table

Revision ID: 44c687d10b77
Revises: bc215a7b6439
Create Date: 2026-08-07 10:03:06.488437

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '44c687d10b77'
down_revision: Union[str, Sequence[str], None] = 'bc215a7b6439'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Só a tabela nova (app/crm_models.py::ServiceInterestOption) -- o
    autogenerate detectou de novo a mesma pilha de drift pré-existente e
    não relacionado já vista nas duas migrações anteriores (bc215a7b6439,
    d7e9c0fc5377); removida manualmente pelo mesmo motivo (tratada à
    parte pelas funções `_ensure_*_column` em app/__init__.py).

    Sem dado semeado aqui -- o backfill dos ~25 itens que hoje moram em
    app/services/service_interests.py roda em app/__init__.py::
    _seed_service_interest_options() (só popula se a tabela estiver
    vazia, mesmo padrão de _seed_crm_lookups), não como parte desta
    migração de schema.
    """
    op.create_table('crm_service_interest_options',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('key', sa.String(), nullable=False),
    sa.Column('slug', sa.String(), nullable=True),
    sa.Column('is_group', sa.Boolean(), nullable=False),
    sa.Column('indent', sa.Boolean(), nullable=False),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('crm_service_interest_options', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_crm_service_interest_options_key'), ['key'], unique=True)
        batch_op.create_index(batch_op.f('ix_crm_service_interest_options_slug'), ['slug'], unique=False)
        batch_op.create_index(batch_op.f('ix_crm_service_interest_options_sort_order'), ['sort_order'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('crm_service_interest_options', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_crm_service_interest_options_sort_order'))
        batch_op.drop_index(batch_op.f('ix_crm_service_interest_options_slug'))
        batch_op.drop_index(batch_op.f('ix_crm_service_interest_options_key'))
    op.drop_table('crm_service_interest_options')
