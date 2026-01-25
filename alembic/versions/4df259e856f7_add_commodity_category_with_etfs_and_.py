"""add Commodity category with ETFs and Bullion subcategories"""

from alembic import op
import sqlalchemy as sa
revision = '4df259e856f7'
down_revision = 'bcb17ef00f03'
branch_labels = None
depends_on = None

def upgrade():
    conn = op.get_bind()
    conn.execute(sa.text("INSERT INTO category (name) VALUES (:name)"), {"name": "Commodity"})
    commodity_id = conn.execute(sa.text("SELECT id FROM category WHERE name = :name"), {"name": "Commodity"}).scalar()
    conn.execute(sa.text("INSERT INTO sub_category (name, category_id) VALUES (:name, :cat_id)"), {"name": "ETFs", "cat_id": commodity_id})
    conn.execute(sa.text("INSERT INTO sub_category (name, category_id) VALUES (:name, :cat_id)"), {"name": "Bullion", "cat_id": commodity_id})

def downgrade():
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM sub_category WHERE name IN ('ETFs','Bullion')"))
    conn.execute(sa.text("DELETE FROM category WHERE name = :name"), {"name": "Commodity"})
