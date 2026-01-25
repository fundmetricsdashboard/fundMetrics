import sys
import os
import pandas as pd
from datetime import datetime
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from models import Fund, FundNAVHistory  # adjust import path if needed

# ===== Database setup =====
# Replace with your actual DB URI
DATABASE_URI = "sqlite:///mfapp.db"
engine = create_engine(DATABASE_URI)
Session = sessionmaker(bind=engine)

def update_nav_from_excel(file_path: str):
    """
    Reads NAV data from the given Excel file and updates the FundNAVHistory table.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"NAV file not found: {file_path}")

    print(f"[{datetime.now()}] Reading NAV data from {file_path}...")
    df = pd.read_excel(file_path)

    # Expected columns: adjust if your Excel macro outputs different names
    expected_cols = {"Fund Name", "ISIN", "Date", "NAV"}
    if not expected_cols.issubset(df.columns):
        raise ValueError(f"Excel file missing required columns. Found: {df.columns}")

    # Normalize data
    df["Date"] = pd.to_datetime(df["Date"]).dt.date
    df["NAV"] = pd.to_numeric(df["NAV"], errors="coerce")

    session = Session()
    updates, inserts, skipped = 0, 0, 0

    try:
        for _, row in df.iterrows():
            isin = str(row["ISIN"]).strip()
            nav_date = row["Date"]
            nav_value = row["NAV"]

            if pd.isna(nav_value):
                skipped += 1
                continue

            fund = session.query(Fund).filter_by(isin=isin).first()
            if not fund:
                skipped += 1
                continue

            existing_nav = (
                session.query(FundNAVHistory)
                .filter_by(fund_id=fund.id, nav_date=nav_date)
                .first()
            )

            if existing_nav:
                if existing_nav.nav != nav_value:
                    existing_nav.nav = nav_value
                    updates += 1
            else:
                new_nav = FundNAVHistory(
                    fund_id=fund.id,
                    nav_date=nav_date,
                    nav=nav_value
                )
                session.add(new_nav)
                inserts += 1

        session.commit()
        print(f"[{datetime.now()}] NAV update complete: {inserts} inserted, {updates} updated, {skipped} skipped.")

    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()

# ===== CLI entry point =====
if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python bulk_nav_update.py <path_to_nav_excel>")
        sys.exit(1)

    excel_path = sys.argv[1]
    update_nav_from_excel(excel_path)
