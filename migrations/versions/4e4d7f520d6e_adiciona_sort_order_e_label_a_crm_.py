"""adiciona sort_order e label a crm_pipeline_stage_config

Revision ID: 4e4d7f520d6e
Revises: 11316712245a
Create Date: 2026-08-06 11:38:26.000000

Só as duas colunas novas (app/crm_models.py::PipelineStageConfig).
Mesmo drift pré-existente já documentado na baseline (4182fc577a23)
removido daqui de propósito -- ver e7f089f746b1 pro mesmo raciocínio.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4e4d7f520d6e'
down_revision: Union[str, Sequence[str], None] = '11316712245a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('crm_pipeline_stage_config', schema=None) as batch_op:
        batch_op.add_column(sa.Column('label', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('sort_order', sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('crm_pipeline_stage_config', schema=None) as batch_op:
        batch_op.drop_column('sort_order')
        batch_op.drop_column('label')
