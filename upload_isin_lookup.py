import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from db_config import db
from models import Category, SubCategory, Fund

# --- CONFIG ---
CSV_FILE = "isin_lookup.csv"
DB_URL = "mysql+pymysql://root:Saisha%400711@127.0.0.1/investments" 

# --- SETUP ---
engine = create_engine(DB_URL)
Session = sessionmaker(bind=engine)
session = Session()

# --- LOAD CSV ---
df = pd.read_csv(CSV_FILE)

# --- PROCESS ROWS ---
for idx, row in df.iterrows():
    try:
        category_name = str(row["category"]).strip()
        subcategory_name = str(row["sub_category"]).strip()
        fund_name = str(row["name"]).strip()
        isin = str(row["isin"]).strip()
        fund_house = str(row["fund_house"]).strip()

        # --- Ensure Category ---
        category = session.query(Category).filter_by(name=category_name).first()
        if not category:
            category = Category(name=category_name)
            session.add(category)
            session.flush()

        # --- Ensure SubCategory ---
        subcat = (
            session.query(SubCategory)
            .filter_by(name=subcategory_name, category_id=category.id)
            .first()
        )
        if not subcat:
            subcat = SubCategory(name=subcategory_name, category_id=category.id)
            session.add(subcat)
            session.flush()

        # --- Ensure Fund ---
        fund = session.query(Fund).filter_by(isin=isin).first()
        if not fund:
            fund = Fund(
                name=fund_name,
                isin=isin,
                fund_house=fund_house,
                sub_category_id=subcat.id,
            )
            session.add(fund)

    except Exception as e:
        print(f"❌ Row {idx+1} failed: {e}")
        session.rollback()

# --- COMMIT ---
try:
    session.commit()
    print("✅ isin_lookup data loaded into Fund table successfully.")
except Exception as e:
    session.rollback()
    print(f"❌ Commit failed: {e}")
finally:
    session.close()
