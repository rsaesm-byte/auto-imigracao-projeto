"""add custom field definitions and values

Revision ID: 1e5f3ef21307
Revises: 8345b284753d
Create Date: 2026-08-06 22:10:25.144411

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1e5f3ef21307'
down_revision: Union[str, Sequence[str], None] = '8345b284753d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'crm_custom_field_definitions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('entity_type', sa.String(), nullable=False),
        sa.Column('key', sa.String(), nullable=False),
        sa.Column('label', sa.String(), nullable=False),
        sa.Column('field_type', sa.Enum(
            'short_text', 'long_text', 'number', 'currency', 'percent', 'date',
            'checkbox', 'single_select', 'multi_select', name='customfieldtype'), nullable=False),
        sa.Column('required', sa.Boolean(), nullable=False),
        sa.Column('default_value', sa.Text(), nullable=True),
        sa.Column('options_json', sa.Text(), nullable=True),
        sa.Column('client_visible', sa.Boolean(), nullable=False),
        sa.Column('archived', sa.Boolean(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('created_by_user_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('entity_type', 'key'),
    )
    with op.batch_alter_table('crm_custom_field_definitions', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_crm_custom_field_definitions_archived'), ['archived'], unique=False)
        batch_op.create_index(
            batch_op.f('ix_crm_custom_field_definitions_entity_type'), ['entity_type'], unique=False)

    op.create_table(
        'crm_custom_field_values',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('field_id', sa.Integer(), nullable=False),
        sa.Column('entity_type', sa.String(), nullable=False),
        sa.Column('entity_id', sa.Integer(), nullable=False),
        sa.Column('value_text', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['field_id'], ['crm_custom_field_definitions.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('field_id', 'entity_type', 'entity_id'),
    )
    with op.batch_alter_table('crm_custom_field_values', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_crm_custom_field_values_entity_id'), ['entity_id'], unique=False)
        batch_op.create_index(
            batch_op.f('ix_crm_custom_field_values_entity_type'), ['entity_type'], unique=False)
        batch_op.create_index(
            batch_op.f('ix_crm_custom_field_values_field_id'), ['field_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('crm_custom_field_values')
    op.drop_table('crm_custom_field_definitions')
