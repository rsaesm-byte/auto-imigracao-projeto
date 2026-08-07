"""remove five_letters e key_word de crm_clients (migrados pra credentials)

Revision ID: c1926f006c3f
Revises: 2f4d688ece26
Create Date: 2026-08-06 12:20:26.401549

Só roda depois que os 2 clientes reais que tinham valor nessas colunas
(#1876, #1903) foram copiados e verificados em
ClientCredential.five_letters_encrypted/key_word_encrypted -- ver
revisão anterior (2f4d688ece26) e o script de cópia rodado manualmente
entre as duas migrations. downgrade() recria as colunas vazias (não
reverte a criptografia -- ver observação no próprio downgrade).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c1926f006c3f'
down_revision: Union[str, Sequence[str], None] = '2f4d688ece26'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # crm_clients tem ~15 tabelas apontando pra ele por FK (crm_cases,
    # crm_documents, crm_leads.converted_client_id, ...) -- o modo batch do
    # SQLite recria a tabela inteira (cria uma cópia, DROP na antiga,
    # RENAME na nova) e o DROP TABLE falha com "FOREIGN KEY constraint
    # failed" se `PRAGMA foreign_keys` estiver ON durante a operação (está,
    # ver app/db.py -- liga em toda conexão nova). Desliga só durante esta
    # migration, religa depois.
    op.execute("PRAGMA foreign_keys=OFF")
    with op.batch_alter_table('crm_clients', schema=None) as batch_op:
        batch_op.drop_column('five_letters')
        batch_op.drop_column('key_word')
    op.execute("PRAGMA foreign_keys=ON")


def downgrade() -> None:
    # Recria as colunas vazias -- NÃO descriptografa de volta os 2 valores
    # migrados (o texto puro original não é reconstruído automaticamente;
    # se algum dia for preciso reverter de verdade, decriptar
    # ClientCredential.five_letters_encrypted/key_word_encrypted na mão).
    op.execute("PRAGMA foreign_keys=OFF")
    with op.batch_alter_table('crm_clients', schema=None) as batch_op:
        batch_op.add_column(sa.Column('five_letters', sa.VARCHAR(), nullable=True))
        batch_op.add_column(sa.Column('key_word', sa.VARCHAR(), nullable=True))
    op.execute("PRAGMA foreign_keys=ON")
