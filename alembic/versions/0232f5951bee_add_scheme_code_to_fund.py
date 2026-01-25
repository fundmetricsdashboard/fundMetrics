"""add scheme_code to fund

Revision ID: 0232f5951bee
Revises: 4df259e856f7
Create Date: 2025-10-07 23:32:52.897773

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0232f5951bee'
down_revision: Union[str, Sequence[str], None] = '4df259e856f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.add_column('fund', sa.Column('scheme_code', sa.String(length=20), nullable=True))
    op.create_unique_constraint('uq_fund_scheme_code', 'fund', ['scheme_code'])

def downgrade():
    op.drop_constraint('uq_fund_scheme_code', 'fund', type_='unique')
    op.drop_column('fund', 'scheme_code')
