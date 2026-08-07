"""cria tabela crm_lead_follow_ups

Revision ID: 460694814161
Revises: d0f1c61ad3a7
Create Date: 2026-08-06 14:05:40.411646

Contém só a tabela nova (app/crm_models.py::LeadFollowUp). Mesmo drift
pré-existente já documentado na baseline removido daqui de propósito --
ver e7f089f746b1 pro mesmo raciocínio.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '460694814161'
down_revision: Union[str, Sequence[str], None] = 'd0f1c61ad3a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'crm_lead_follow_ups',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('lead_id', sa.Integer(), nullable=False),
        sa.Column('follow_up_number', sa.Integer(), nullable=False),
        sa.Column('follow_up_date', sa.Date(), nullable=False),
        sa.Column('contact_channel_id', sa.Integer(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['contact_channel_id'], ['crm_contact_channels.id'], ),
        sa.ForeignKeyConstraint(['lead_id'], ['crm_leads.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('crm_lead_follow_ups', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_crm_lead_follow_ups_lead_id'), ['lead_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('crm_lead_follow_ups', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_crm_lead_follow_ups_lead_id'))

    op.drop_table('crm_lead_follow_ups')
