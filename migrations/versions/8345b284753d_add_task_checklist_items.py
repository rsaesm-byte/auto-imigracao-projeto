"""add task checklist items

Revision ID: 8345b284753d
Revises: 5882fed51e74
Create Date: 2026-08-06 21:45:42.534187

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8345b284753d'
down_revision: Union[str, Sequence[str], None] = '5882fed51e74'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'crm_task_checklist_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('task_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('done', sa.Boolean(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['task_id'], ['crm_tasks.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('crm_task_checklist_items', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_crm_task_checklist_items_task_id'), ['task_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('crm_task_checklist_items')
