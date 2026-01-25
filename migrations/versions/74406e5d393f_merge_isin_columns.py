"""merge isin_regular_growth and isin_direct_growth into single isin"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '74406e5d393f'
down_revision = '4df259e856f7'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Add new unified column
    op.add_column('fund', sa.Column('isin', sa.String(length=20), nullable=True))

    # 2. Copy data from old columns into new one
    conn = op.get_bind()
    conn.execute(
        sa.text("""
            UPDATE fund
            SET isin = COALESCE(isin_regular_growth, isin_direct_growth)
        """)
    )

    # 3. Make new column NOT NULL and UNIQUE (MySQL requires existing_type)
    op.alter_column(
        'fund',
        'isin',
        existing_type=sa.String(length=20),
        nullable=False
    )
    op.create_unique_constraint('uq_fund_isin', 'fund', ['isin'])
    op.create_index('ix_fund_isin', 'fund', ['isin'])

    # 4. Drop old columns and indexes
    op.drop_index('ix_fund_isin_regular_growth', table_name='fund')
    op.drop_index('ix_fund_isin_direct_growth', table_name='fund')
    op.drop_column('fund', 'isin_regular_growth')
    op.drop_column('fund', 'isin_direct_growth')


def downgrade():
    # Recreate old columns
    op.add_column('fund', sa.Column('isin_regular_growth', sa.String(length=20), nullable=True))
    op.add_column('fund', sa.Column('isin_direct_growth', sa.String(length=20), nullable=True))

    conn = op.get_bind()
    conn.execute(
        sa.text("""
            UPDATE fund
            SET isin_regular_growth = isin
        """)
    )

    op.create_index('ix_fund_isin_regular_growth', 'fund', ['isin_regular_growth'])
    op.create_index('ix_fund_isin_direct_growth', 'fund', ['isin_direct_growth'])

    op.drop_index('ix_fund_isin', table_name='fund')
    op.drop_constraint('uq_fund_isin', 'fund', type_='unique')
    op.drop_column('fund', 'isin')
