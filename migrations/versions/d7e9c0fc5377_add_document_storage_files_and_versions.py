"""add document storage files and versions

Revision ID: d7e9c0fc5377
Revises: 818d181faaef
Create Date: 2026-08-07 08:57:46.511551

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd7e9c0fc5377'
down_revision: Union[str, Sequence[str], None] = '818d181faaef'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Só as duas tabelas novas da Seção 10 (app/document_storage_models.py)
    -- o autogenerate também detectou uma pilha de drift pré-existente e
    não relacionado (colunas notion_page_id, tipo de service_mode,
    NOT NULL em colunas antigas) que foi removida manualmente daqui; esse
    drift já vem sendo tratado à parte pelas funções `_ensure_*_column`
    em app/__init__.py e não é seguro empacotar junto de uma migração
    sem revisão própria.
    """
    op.create_table('document_storage_files',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('caso_id', sa.Integer(), nullable=False),
    sa.Column('tipo_documento', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('deleted_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['caso_id'], ['crm_cases.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('document_storage_files', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_document_storage_files_caso_id'), ['caso_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_document_storage_files_deleted_at'), ['deleted_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_document_storage_files_tipo_documento'), ['tipo_documento'], unique=False)

    op.create_table('document_storage_versions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('documento_id', sa.Integer(), nullable=False),
    sa.Column('numero_versao', sa.Integer(), nullable=False),
    sa.Column('is_current', sa.Boolean(), nullable=False),
    sa.Column('storage_key', sa.String(length=255), nullable=False),
    sa.Column('nome_original', sa.String(length=255), nullable=False),
    sa.Column('mime_type', sa.String(length=127), nullable=False),
    sa.Column('tamanho_bytes', sa.Integer(), nullable=False),
    sa.Column('hash', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['documento_id'], ['document_storage_files.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('documento_id', 'numero_versao', name='uq_document_storage_versao_numero')
    )
    with op.batch_alter_table('document_storage_versions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_document_storage_versions_documento_id'), ['documento_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_document_storage_versions_hash'), ['hash'], unique=False)
        batch_op.create_index(batch_op.f('ix_document_storage_versions_is_current'), ['is_current'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('document_storage_versions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_document_storage_versions_is_current'))
        batch_op.drop_index(batch_op.f('ix_document_storage_versions_hash'))
        batch_op.drop_index(batch_op.f('ix_document_storage_versions_documento_id'))
    op.drop_table('document_storage_versions')

    with op.batch_alter_table('document_storage_files', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_document_storage_files_tipo_documento'))
        batch_op.drop_index(batch_op.f('ix_document_storage_files_deleted_at'))
        batch_op.drop_index(batch_op.f('ix_document_storage_files_caso_id'))
    op.drop_table('document_storage_files')
