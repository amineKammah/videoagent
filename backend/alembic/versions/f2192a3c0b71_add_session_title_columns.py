"""add_session_title_columns

Revision ID: f2192a3c0b71
Revises: c071b5e6644a
Create Date: 2026-02-17 19:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f2192a3c0b71"
down_revision: Union[str, Sequence[str], None] = "c071b5e6644a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("sessions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("title", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("title_source", sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column("title_updated_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("sessions", schema=None) as batch_op:
        batch_op.drop_column("title_updated_at")
        batch_op.drop_column("title_source")
        batch_op.drop_column("title")
