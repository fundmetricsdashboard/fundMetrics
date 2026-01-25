import pandas as pd
from sqlalchemy import create_engine, text

# Path to your lookup file
csv_path = r"C:\Users\sengu\OneDrive\Documents\MFApp\isin_lookup.csv"

# Read the lookup CSV
lookup = pd.read_csv(csv_path)

# Connect to MySQL (adjust user/password/host/db)
engine = create_engine("mysql+pymysql://user:password@localhost:3306/investments")

with engine.begin() as conn:
    # Clear out old data
    conn.execute(text("TRUNCATE TABLE isin_lookup"))

    # Insert fresh data
    lookup.to_sql("isin_lookup", conn, if_exists="append", index=False)

print("✅ isin_lookup table refreshed from CSV")
