"""add_sessions_table

Revision ID: c071b5e6644a
Revises: d3b421f6bdb7
Create Date: 2026-01-31 22:48:00.735634

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c071b5e6644a'
down_revision: Union[str, Sequence[str], None] = 'd3b421f6bdb7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create sessions table
    op.create_table('sessions',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('company_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    # Add company_id to annotations (if it doesn't exist, we assume it doesn't based on previous error)
    # We use batch mode implicitly or just add column (add column is supported in sqlite usually, alter column is not)
    # But adding NOT NULL without default fails. So we use server_default.
    with op.batch_alter_table('annotations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('company_id', sa.String(), nullable=False, server_default='test_company'))


def downgrade() -> None:
    op.drop_table('sessions')
    with op.batch_alter_table('annotations', schema=None) as batch_op:
        batch_op.drop_column('company_id')
