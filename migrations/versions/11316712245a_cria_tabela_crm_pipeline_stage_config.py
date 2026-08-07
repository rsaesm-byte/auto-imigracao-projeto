"""cria tabela crm_pipeline_stage_config

Revision ID: 11316712245a
Revises: e7f089f746b1
Create Date: 2026-08-06 10:51:06.423908

Contém só a tabela nova (app/crm_models.py::PipelineStageConfig). Mesmo
drift pré-existente já documentado na baseline (4182fc577a23) removido
daqui de propósito -- ver e7f089f746b1 pro mesmo raciocínio.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '11316712245a'
down_revision: Union[str, Sequence[str], None] = 'e7f089f746b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'crm_pipeline_stage_config',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('pipeline', sa.String(), nullable=False),
        sa.Column('stage_value', sa.String(), nullable=False),
        sa.Column('color', sa.String(), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('updated_by_user_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['updated_by_user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('pipeline', 'stage_value', name='uq_pipeline_stage'),
    )
    with op.batch_alter_table('crm_pipeline_stage_config', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_crm_pipeline_stage_config_pipeline'), ['pipeline'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('crm_pipeline_stage_config', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_crm_pipeline_stage_config_pipeline'))

    op.drop_table('crm_pipeline_stage_config')
