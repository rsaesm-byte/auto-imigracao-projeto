"""add version column to crm_cases and crm_clients

Revision ID: bc215a7b6439
Revises: d7e9c0fc5377
Create Date: 2026-08-07 09:17:00.931031

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bc215a7b6439'
down_revision: Union[str, Sequence[str], None] = 'd7e9c0fc5377'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Só a coluna `version` em crm_cases/crm_clients (Seção 16/17,
    app/db.py::VersionedMixin) -- o autogenerate também detectou a mesma
    pilha de drift pré-existente e não relacionado já vista na migração
    anterior (d7e9c0fc5377); removida manualmente daqui pelo mesmo
    motivo (esse drift é tratado à parte pelas funções `_ensure_*_column`
    em app/__init__.py, não é seguro empacotar sem revisão própria).

    `server_default='1'` na criação da coluna é necessário pra popular as
    linhas já existentes (NOT NULL numa tabela não-vazia exige um valor);
    o default do lado do Python (`VersionedMixin.version`) já cobre as
    linhas novas dali em diante.
    """
    with op.batch_alter_table('crm_cases', schema=None) as batch_op:
        batch_op.add_column(sa.Column('version', sa.Integer(), nullable=False, server_default='1'))

    with op.batch_alter_table('crm_clients', schema=None) as batch_op:
        batch_op.add_column(sa.Column('version', sa.Integer(), nullable=False, server_default='1'))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('crm_clients', schema=None) as batch_op:
        batch_op.drop_column('version')

    with op.batch_alter_table('crm_cases', schema=None) as batch_op:
        batch_op.drop_column('version')
