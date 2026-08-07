"""add lead best_contact_time and interest_notes

Revision ID: 13b1e849ecaf
Revises: c9c72316523d
Create Date: 2026-08-06 18:07:43.776983

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '13b1e849ecaf'
down_revision: Union[str, Sequence[str], None] = 'c9c72316523d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('crm_leads', schema=None) as batch_op:
        batch_op.add_column(sa.Column('best_contact_time', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('interest_notes', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('crm_leads', schema=None) as batch_op:
        batch_op.drop_column('interest_notes')
        batch_op.drop_column('best_contact_time')
