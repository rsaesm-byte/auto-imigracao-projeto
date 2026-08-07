"""add task comments and recurrence

Revision ID: 818d181faaef
Revises: 2163dd3d8fde
Create Date: 2026-08-06 23:18:32.359774

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '818d181faaef'
down_revision: Union[str, Sequence[str], None] = '2163dd3d8fde'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'crm_task_comments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('task_id', sa.Integer(), nullable=False),
        sa.Column('author_id', sa.Integer(), nullable=True),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('attachment_path', sa.String(), nullable=True),
        sa.Column('attachment_name', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['author_id'], ['users.id']),
        sa.ForeignKeyConstraint(['task_id'], ['crm_tasks.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('crm_task_comments', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_crm_task_comments_task_id'), ['task_id'], unique=False)

    with op.batch_alter_table('crm_tasks', schema=None) as batch_op:
        batch_op.add_column(sa.Column('recurrence_interval_days', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('crm_tasks', schema=None) as batch_op:
        batch_op.drop_column('recurrence_interval_days')

    with op.batch_alter_table('crm_task_comments', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_crm_task_comments_task_id'))
    op.drop_table('crm_task_comments')
