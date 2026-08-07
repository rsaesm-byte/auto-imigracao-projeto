"""add staff dashboard layout

Revision ID: 5882fed51e74
Revises: 417306b3f257
Create Date: 2026-08-06 18:58:44.130897

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5882fed51e74'
down_revision: Union[str, Sequence[str], None] = '417306b3f257'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'staff_dashboard_layouts',
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('visible_widgets_json', sa.Text(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('user_id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('staff_dashboard_layouts')
