"""financial planning fase 10: motivation board

Revision ID: 5602d05a597f
Revises: 1439a4f245aa
Create Date: 2026-08-07 18:38:25.820890

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5602d05a597f'
down_revision: Union[str, Sequence[str], None] = '1439a4f245aa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Só a tabela nova (app/financial_planning_models.py, Fase 10) -- o
    autogenerate detectou de novo a mesma pilha de drift pré-existente e
    não relacionado já vista em toda migração anterior desta sessão;
    removida manualmente pelo mesmo motivo. `create_table` puro, FK pra
    `financial_attachments` (Fase 2, já existia) sem criar ciclo.
    """
    op.create_table('financial_motivation_items',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('financial_workspace_id', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(), nullable=False),
    sa.Column('item_type', sa.Enum('quote', 'affirmation', 'goal', 'habit', 'reminder', name='motivationitemtype'), nullable=True),
    sa.Column('categories', sa.String(), nullable=True),
    sa.Column('image_attachment_id', sa.Integer(), nullable=True),
    sa.Column('favorite', sa.Boolean(), nullable=False),
    sa.Column('pinned', sa.Boolean(), nullable=False),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.Column('source_url', sa.String(), nullable=True),
    sa.Column('created_by_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['financial_workspace_id'], ['financial_workspaces.id'], ),
    sa.ForeignKeyConstraint(['image_attachment_id'], ['financial_attachments.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('financial_motivation_items', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_financial_motivation_items_financial_workspace_id'), ['financial_workspace_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('financial_motivation_items', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_financial_motivation_items_financial_workspace_id'))

    op.drop_table('financial_motivation_items')
