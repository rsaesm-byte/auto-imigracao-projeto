"""cria tabela crm_audit_log

Revision ID: e7f089f746b1
Revises: 4182fc577a23
Create Date: 2026-08-06 10:29:50.537665

Contém só a tabela nova (app/crm_models.py::AuditLog). O autogenerate
também detectou o mesmo drift pré-existente já documentado na baseline
(4182fc577a23) -- notion_page_id, mudança de tipo de service_mode,
alguns NOT NULL/índices não declarados formalmente. Removido daqui de
propósito: uma migration chamada "cria tabela crm_audit_log" não deve
também mexer em 7 outras tabelas sem relação nenhuma com isso.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7f089f746b1'
down_revision: Union[str, Sequence[str], None] = '4182fc577a23'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'crm_audit_log',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('entity_type', sa.String(), nullable=False),
        sa.Column('entity_id', sa.Integer(), nullable=False),
        sa.Column('action', sa.String(), nullable=False),
        sa.Column('field', sa.String(), nullable=True),
        sa.Column('old_value', sa.Text(), nullable=True),
        sa.Column('new_value', sa.Text(), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('source', sa.Enum('manual', 'automatic', 'integration', name='auditsource'), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('crm_audit_log', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_crm_audit_log_action'), ['action'], unique=False)
        batch_op.create_index(batch_op.f('ix_crm_audit_log_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_crm_audit_log_entity_id'), ['entity_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_crm_audit_log_entity_type'), ['entity_type'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('crm_audit_log', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_crm_audit_log_entity_type'))
        batch_op.drop_index(batch_op.f('ix_crm_audit_log_entity_id'))
        batch_op.drop_index(batch_op.f('ix_crm_audit_log_created_at'))
        batch_op.drop_index(batch_op.f('ix_crm_audit_log_action'))

    op.drop_table('crm_audit_log')
