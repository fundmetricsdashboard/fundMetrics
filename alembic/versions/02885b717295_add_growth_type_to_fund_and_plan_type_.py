"""Add growth_type to Fund and plan_type to Investment

Revision ID: 02885b717295
Revises: 0232f5951bee
Create Date: 2025-10-10 18:02:40.526606

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '02885b717295'
down_revision: Union[str, Sequence[str], None] = '0232f5951bee'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.add_column('fund', sa.Column('growth_type', sa.String(length=20), nullable=True))
    op.add_column('investment', sa.Column('plan_type', sa.String(length=20), nullable=True))

def downgrade():
    op.drop_column('investment', 'plan_type')
    op.drop_column('fund', 'growth_type')
