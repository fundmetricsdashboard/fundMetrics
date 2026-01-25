import requests
import pandas as pd
from sqlalchemy import create_engine
from decimal import Decimal
from datetime import datetime

# --- DB connection ---
DB_URL = "mysql+pymysql://root:Saisha%400711@localhost/investments"
engine = create_engine(DB_URL)

# --- AMFI NAV data URL ---
AMFI_URL = "https://www.amfiindia.com/spages/NAVAll.txt"

def fetch_amfi_data():
    print("📥 Fetching NAV data from AMFI...")
    r = requests.get(AMFI_URL)
    r.raise_for_status()
    data = r.text
    return data

def parse_amfi_data(raw_text):
    print("🛠 Parsing NAV data...")
    lines = raw_text.strip().split("\n")
    # Skip header lines until we hit the actual data
    data_lines = []
    for line in lines:
        if ";" in line:
            data_lines.append(line.split(";"))
    df = pd.DataFrame(data_lines, columns=[
        "scheme_code", "scheme_name", "isin_div_payout", "isin_div_reinvestment",
        "nav", "repurchase_price", "sale_price", "date"
    ])
    return df

def filter_and_prepare(df):
    print("📅 Filtering to month-end and mid-month...")
    df["date"] = pd.to_datetime(df["date"], format="%d-%b-%Y", errors="coerce")
    df = df.dropna(subset=["date", "nav"])
    df["nav"] = df["nav"].astype(str)

    # Keep only 15th and last day of month
    df["day"] = df["date"].dt.day
    df["month_end_day"] = df["date"].dt.days_in_month
    df = df[(df["day"] == 15) | (df["day"] == df["month_end_day"])]

    # Assign nav_type
    df["nav_type"] = df.apply(lambda row: "mid_month" if row["day"] == 15 else "month_end", axis=1)

    # Prepare final DataFrame
    df_final = df[["scheme_code", "date", "nav", "nav_type"]].copy()
    df_final.rename(columns={"scheme_code": "fund_id", "date": "nav_date", "nav": "nav_value"}, inplace=True)

    # Convert nav_value to Decimal for precision
    df_final["nav_value"] = df_final["nav_value"].apply(lambda x: Decimal(x))

    return df_final

def insert_into_db(df):
    print(f"💾 Inserting {len(df)} rows into DB...")
    with engine.begin() as conn:
        for _, row in df.iterrows():
            try:
                conn.execute(
                    """
                    INSERT INTO fund_nav_history (fund_id, nav_date, nav_value, nav_type, created_at)
                    VALUES (%s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE nav_value = VALUES(nav_value), nav_type = VALUES(nav_type)
                    """,
                    (row["fund_id"], row["nav_date"], row["nav_value"], row["nav_type"], datetime.now())
                )
            except Exception as e:
                print(f"⚠️ Skipped row {row['fund_id']} {row['nav_date']}: {e}")

if __name__ == "__main__":
    raw = fetch_amfi_data()
    df = parse_amfi_data(raw)
    df_filtered = filter_and_prepare(df)
    insert_into_db(df_filtered)
    print("✅ NAV data load complete!")
