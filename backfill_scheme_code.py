import csv
from sqlalchemy import create_engine, text

# 1. Connect to your MySQL DB
engine = create_engine("mysql+pymysql://root:Saisha%400711@localhost/investments")

# 2. Parse AMFI NAV master file (pipe-delimited)
amfi_file = "NAVs.txt"  # path to AMFI master file

isin_to_scheme = {}
with open(amfi_file, "r", encoding="utf-8") as f:
    reader = csv.reader(f, delimiter=';')  # AMFI uses ';' as delimiter
    for row in reader:
        if len(row) < 3:
            continue
        scheme_code = row[0].strip()
        isin = row[1].strip()
        if scheme_code and isin:
            isin_to_scheme[isin] = scheme_code

print(f"Loaded {len(isin_to_scheme)} ISIN → scheme_code mappings")

# 3. Backfill into fund table
with engine.begin() as conn:
    for isin, scheme_code in isin_to_scheme.items():
        conn.execute(
            text("""
                UPDATE fund
                SET scheme_code = :scheme_code
                WHERE isin = :isin
                  AND (scheme_code IS NULL OR scheme_code = '')
            """),
            {"scheme_code": scheme_code, "isin": isin}
        )

print("Backfill complete.")
