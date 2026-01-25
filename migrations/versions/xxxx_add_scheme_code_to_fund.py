"""add scheme_code to fund

Revision ID: 123456789abc
Revises: <put_previous_revision_id_here>
Create Date: 2025-10-07 23:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '123456789abc'
down_revision = 'c7c7bff2841c'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('fund', sa.Column('scheme_code', sa.String(length=20), nullable=True))
    op.create_unique_constraint('uq_fund_scheme_code', 'fund', ['scheme_code'])


def downgrade():
    op.drop_constraint('uq_fund_scheme_code', 'fund', type_='unique')
    op.drop_column('fund', 'scheme_code')
