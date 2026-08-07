"""adiciona notes a crm_document_translations

Revision ID: 4f793030e267
Revises: c1926f006c3f
Create Date: 2026-08-06 12:30:00.000000

Só a coluna nova (app/crm_models.py::DocumentTranslation.notes). Mesmo
drift pré-existente já documentado na baseline removido daqui de
propósito -- ver e7f089f746b1 pro mesmo raciocínio.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4f793030e267'
down_revision: Union[str, Sequence[str], None] = 'c1926f006c3f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('crm_document_translations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('notes', sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('crm_document_translations', schema=None) as batch_op:
        batch_op.drop_column('notes')
