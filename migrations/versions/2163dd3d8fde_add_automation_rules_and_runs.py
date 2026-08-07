"""add automation rules and runs

Revision ID: 2163dd3d8fde
Revises: 1e5f3ef21307
Create Date: 2026-08-06 23:01:49.888064

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2163dd3d8fde'
down_revision: Union[str, Sequence[str], None] = '1e5f3ef21307'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'crm_automation_rules',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('service_catalog_id', sa.Integer(), nullable=True),
        sa.Column('trigger_field', sa.Enum(
            'service_deadline', 'status_expire_on', 'approval_date', 'submission_date',
            name='automationtriggerfield'), nullable=False),
        sa.Column('offset_days', sa.Integer(), nullable=False),
        sa.Column('action_type', sa.Enum('create_task', 'notify_responsible', name='automationactiontype'), nullable=False),
        sa.Column('action_text', sa.String(), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('created_by_user_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['service_catalog_id'], ['crm_services_catalog.id']),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('crm_automation_rules', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_crm_automation_rules_active'), ['active'], unique=False)

    op.create_table(
        'crm_automation_runs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('rule_id', sa.Integer(), nullable=False),
        sa.Column('case_id', sa.Integer(), nullable=False),
        sa.Column('executed_at', sa.DateTime(), nullable=False),
        sa.Column('status', sa.Enum('success', 'error', name='automationrunstatus'), nullable=False),
        sa.Column('result_text', sa.Text(), nullable=True),
        sa.Column('error_text', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['rule_id'], ['crm_automation_rules.id']),
        sa.ForeignKeyConstraint(['case_id'], ['crm_cases.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('crm_automation_runs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_crm_automation_runs_rule_id'), ['rule_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_crm_automation_runs_case_id'), ['case_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_crm_automation_runs_executed_at'), ['executed_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('crm_automation_runs')
    op.drop_table('crm_automation_rules')
