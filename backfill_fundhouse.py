import pandas as pd
from app import app, db
from models import Fund

with app.app_context():
    # Load the Excel file
    df = pd.read_excel(r"C:\Users\sengu\OneDrive\Documents\MFApp\Dummy Upload 2.xlsx", sheet_name="Sheet1")

    # Clean column names
    df.columns = [c.strip().lower() for c in df.columns]

    updated_count = 0
    for _, row in df.iterrows():
        fund_name = str(row['fund_name']).strip()
        fund_house = str(row['fund_house']).strip() if pd.notnull(row['fund_house']) else None

        if not fund_house:
            continue  # skip if no fund house in sheet

        fund = Fund.query.filter_by(name=fund_name).first()
        if fund:
            if not fund.fund_house or fund.fund_house != fund_house:
                fund.fund_house = fund_house
                updated_count += 1

    print(f"Updating {updated_count} funds...")
    db.session.commit()
    print("✅ Fund house values updated successfully.")
