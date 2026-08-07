"""adiciona five_letters_encrypted e key_word_encrypted a crm_client_credentials

Revision ID: 2f4d688ece26
Revises: 4e4d7f520d6e
Create Date: 2026-08-06 12:00:00.000000

Só as duas colunas novas (app/crm_models.py::ClientCredential). O
autogenerate também queria dropar crm_clients.five_letters/key_word na
mesma migration -- não fiz isso aqui de propósito: 2 clientes reais têm
dado nessas colunas hoje, e ele precisa ser copiado (criptografado) pra
ClientCredential ANTES de qualquer DROP COLUMN. Ver
scripts/migrate_five_letters_keyword.py (cópia dos dados) e a migration
seguinte (dropa as colunas antigas, só depois da cópia confirmada).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2f4d688ece26'
down_revision: Union[str, Sequence[str], None] = '4e4d7f520d6e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('crm_client_credentials', schema=None) as batch_op:
        batch_op.add_column(sa.Column('five_letters_encrypted', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('key_word_encrypted', sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('crm_client_credentials', schema=None) as batch_op:
        batch_op.drop_column('key_word_encrypted')
        batch_op.drop_column('five_letters_encrypted')
