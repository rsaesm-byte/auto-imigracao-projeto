"""financial planning fase 10: motivation item location

Revision ID: ee75e3d70039
Revises: 5602d05a597f
Create Date: 2026-08-07 18:50:47.804030

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ee75e3d70039'
down_revision: Union[str, Sequence[str], None] = '5602d05a597f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Só a coluna nova (`location`, pedido do usuário 2026-08-07, fora do
    campo original do documento) -- o autogenerate detectou de novo a
    mesma pilha de drift pré-existente e não relacionado já vista em toda
    migração anterior desta sessão; removida manualmente pelo mesmo
    motivo.
    """
    with op.batch_alter_table('financial_motivation_items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('location', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('financial_motivation_items', schema=None) as batch_op:
        batch_op.drop_column('location')
