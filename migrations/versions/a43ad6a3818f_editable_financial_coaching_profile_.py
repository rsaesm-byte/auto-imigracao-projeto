"""editable financial coaching profile options

Revision ID: a43ad6a3818f
Revises: 12acb47db395
Create Date: 2026-08-07 14:31:55.245060

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a43ad6a3818f'
down_revision: Union[str, Sequence[str], None] = '12acb47db395'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Só `sort_order`/`deleted_at` nas 3 tabelas de checkbox da ficha do
    cliente de Financial Coaching (Income sources/Financial goals/Main
    challenges) que viraram editáveis pelo painel -- pedido do usuário
    2026-08-07. O autogenerate detectou de novo a mesma pilha de drift
    pré-existente e não relacionada já vista nas migrações anteriores;
    removida manualmente pelo mesmo motivo.

    `sort_order` precisa de `server_default='0'` -- as 3 tabelas já têm
    linhas reais (seed inicial), e SQLite recusa adicionar coluna
    NOT NULL sem default quando a tabela não está vazia (o modo batch
    do Alembic recria a tabela copiando os dados, e a cópia falharia
    tentando gravar NULL numa coluna NOT NULL). Sem backfill explícito
    por linha: como o app já ordenava essas listas por `name`
    (alfabético) antes desta migração, e a nova ordem é
    `(sort_order, name)`, toda linha nascendo com `sort_order=0` empata
    e cai de volta no desempate por `name` -- a ordem visível não muda
    nada no momento em que a migração roda, só passa a ser reordenável
    depois.
    """
    with op.batch_alter_table('crm_financial_challenges', schema=None) as batch_op:
        batch_op.add_column(sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('deleted_at', sa.DateTime(), nullable=True))

    with op.batch_alter_table('crm_financial_goals', schema=None) as batch_op:
        batch_op.add_column(sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('deleted_at', sa.DateTime(), nullable=True))

    with op.batch_alter_table('crm_income_source_types', schema=None) as batch_op:
        batch_op.add_column(sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('deleted_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('crm_income_source_types', schema=None) as batch_op:
        batch_op.drop_column('deleted_at')
        batch_op.drop_column('sort_order')

    with op.batch_alter_table('crm_financial_goals', schema=None) as batch_op:
        batch_op.drop_column('deleted_at')
        batch_op.drop_column('sort_order')

    with op.batch_alter_table('crm_financial_challenges', schema=None) as batch_op:
        batch_op.drop_column('deleted_at')
        batch_op.drop_column('sort_order')
