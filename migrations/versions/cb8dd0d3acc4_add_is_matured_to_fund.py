"""add is_matured to fund

Revision ID: cb8dd0d3acc4
Revises: 4e331fecb587
Create Date: 2026-01-02 01:21:23.627836

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'cb8dd0d3acc4'
down_revision = '4e331fecb587'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "fund",
        sa.Column("is_matured", sa.Boolean(), nullable=False, server_default=sa.text("false"))
    )


def downgrade():
    op.drop_column("fund", "is_matured")
