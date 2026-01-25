"""add investment_history table

Revision ID: 6c8efbcdc424
Revises: 02885b717295
Create Date: 2025-10-12 00:12:17.643411

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '6c8efbcdc424'
down_revision: Union[str, Sequence[str], None] = '02885b717295'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: create investment_history table."""
    op.create_table(
        'investment_history',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
        sa.Column('fund_id', sa.Integer(), sa.ForeignKey('fund.id'), nullable=False),
        sa.Column('tx_date', sa.Date(), nullable=False),
        sa.Column('tx_type', sa.String(length=20), nullable=False),  # 'BUY' or 'SELL'
        sa.Column('units', sa.Numeric(18, 6), nullable=False),
        sa.Column('cost_per_unit', sa.Numeric(18, 8), nullable=False),
        sa.Column('total_cost', sa.Numeric(18, 2), nullable=False),
        sa.Column('units_remaining', sa.Numeric(18, 6), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(),
                  onupdate=sa.func.now(), nullable=False),
        sa.CheckConstraint("tx_type IN ('BUY','SELL')", name='chk_tx_type_valid')
    )


def downgrade() -> None:
    """Downgrade schema: drop investment_history table."""
    op.drop_table('investment_history')
