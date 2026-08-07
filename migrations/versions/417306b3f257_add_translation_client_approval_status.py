"""add translation client approval status

Revision ID: 417306b3f257
Revises: 13b1e849ecaf
Create Date: 2026-08-06 18:26:14.209003

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '417306b3f257'
down_revision: Union[str, Sequence[str], None] = '13b1e849ecaf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('crm_document_translations', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'client_approval_status',
            sa.Enum('pending', 'approved', 'changes_requested', 'rejected', name='clientapprovalstatus'),
            nullable=False, server_default='pending'))
        batch_op.add_column(sa.Column('client_approval_note', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('client_approval_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('crm_document_translations', schema=None) as batch_op:
        batch_op.drop_column('client_approval_at')
        batch_op.drop_column('client_approval_note')
        batch_op.drop_column('client_approval_status')
