import os
import pandas as pd
from sqlalchemy import func, text
from models import Fund, FundNAVHistory

# Synonym lists for flexible header matching
SCHEME_NAME_HEADERS = ["scheme name", "fund name", "scheme", "fund"]
NAV_HEADERS         = ["nav", "net asset value", "nav value"]
DATE_HEADERS        = ["date", "nav date", "valuation date"]

def find_column(df, possible_names):
    """Find the first column whose name matches any of the possible_names."""
    for col in df.columns:
        col_clean = str(col).strip().lower()
        if any(name in col_clean for name in possible_names):
            return col
    return None

def load_nav_file_for_date(session, nav_date):
    """
    Called from app.py as: load_nav_file_for_date(db.session, date.today())
    1. Reads the NAV Excel file from NAVs folder, specifically from 'Sheet1'.
    2. Auto-detects the header row.
    3. Inserts ALL rows into raw_nav_history.
    4. Updates fund.latest_nav and fund_nav_history for matched funds.
    """

    # Build file path inside NAVs folder
    nav_file_path = os.path.join("NAVs", f"nav_data_{nav_date}.xlsx")
    abs_path = os.path.abspath(nav_file_path)

    if not os.path.exists(abs_path):
        raise FileNotFoundError(f"NAV file not found: {abs_path}")

    print(f"[NAV UPDATE] Loading NAV data from {abs_path} for {nav_date}...")

    # Step 1: Read without headers from the correct sheet
    try:
        df_raw = pd.read_excel(abs_path, header=None, sheet_name="Sheet1")
    except Exception as e:
        raise RuntimeError(f"Error reading Excel file: {e}")

    # Step 2: Find the header row index
    header_row_idx = None
    for i, row in df_raw.iterrows():
        row_lower = [str(cell).strip().lower() for cell in row if pd.notnull(cell)]
        if any(any(keyword in cell for keyword in SCHEME_NAME_HEADERS + NAV_HEADERS) for cell in row_lower):
            header_row_idx = i
            break

    if header_row_idx is None:
        raise ValueError(f"Could not find a header row in {abs_path}")

    # Step 3: Re-read with the correct header row from the correct sheet
    df = pd.read_excel(abs_path, header=header_row_idx, sheet_name="Sheet1")
    df.columns = [str(c).strip() for c in df.columns]

    # Identify relevant columns using synonyms
    scheme_col = find_column(df, SCHEME_NAME_HEADERS)
    nav_col    = find_column(df, NAV_HEADERS)
    date_col   = find_column(df, DATE_HEADERS)

    if not scheme_col or not nav_col:
        raise ValueError(f"Required columns not found. Found columns: {df.columns.tolist()}")

    # Determine NAV date from file or use provided nav_date
    if date_col and pd.notnull(df[date_col].iloc[0]):
        try:
            file_nav_date = pd.to_datetime(df[date_col].iloc[0]).date()
        except Exception:
            file_nav_date = nav_date
    else:
        file_nav_date = nav_date

    print(f"[NAV UPDATE] Processing NAVs for date: {file_nav_date}")

    raw_inserted = 0
    updated_count = 0
    skipped_count = 0

    for _, row in df.iterrows():
        scheme_name = str(row[scheme_col]).strip()
        nav_value = row[nav_col]

        if not scheme_name or pd.isnull(nav_value):
            skipped_count += 1
            continue

        try:
            nav_value_float = float(nav_value)
        except ValueError:
            skipped_count += 1
            continue

        # 1. Insert into raw_nav_history for ALL schemes
        session.execute(
            text("""
                INSERT INTO raw_nav_history (scheme_name, nav_date, nav_value)
                VALUES (:scheme_name, :nav_date, :nav_value)
                ON DUPLICATE KEY UPDATE nav_value = VALUES(nav_value)
            """),
            {
                "scheme_name": scheme_name,
                "nav_date": file_nav_date,
                "nav_value": nav_value_float
            }
        )
        raw_inserted += 1

        # 2. If fund exists, update snapshot + history
        fund = session.query(Fund).filter(func.lower(Fund.name) == scheme_name.lower()).first()
        if fund:
            fund.latest_nav = nav_value_float
            session.add(FundNAVHistory(
                fund_id=fund.id,
                nav_date=file_nav_date,
                nav_value=nav_value_float
            ))
            updated_count += 1

    try:
        session.commit()
        print(f"[NAV UPDATE] Raw inserted/updated: {raw_inserted}, Funds updated: {updated_count}, Skipped: {skipped_count}")
    except Exception as e:
        session.rollback()
        print(f"[NAV UPDATE] Error committing changes: {e}")
