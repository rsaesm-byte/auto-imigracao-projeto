"""adiciona confirmation_notes a crm_payments_ledger

Revision ID: d0f1c61ad3a7
Revises: 80aa42ffc8ad
Create Date: 2026-08-06 13:35:21.894438
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd0f1c61ad3a7'
down_revision: Union[str, Sequence[str], None] = '80aa42ffc8ad'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('crm_payments_ledger', schema=None) as batch_op:
        batch_op.add_column(sa.Column('confirmation_notes', sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('crm_payments_ledger', schema=None) as batch_op:
        batch_op.drop_column('confirmation_notes')
