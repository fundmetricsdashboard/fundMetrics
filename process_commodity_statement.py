import os
import hashlib
import pandas as pd
from db_config import db
from models import Fund, StagingInvestment

def process_commodity_statement(filepath, user_id, preview=False):
    # --- NEW FILE READING LOGIC ---
    filename = filepath.lower()
    
    if filename.endswith('.csv'):
        df = pd.read_csv(filepath)
    elif filename.endswith(('.xls', '.xlsx')):
        df = pd.read_excel(filepath, engine='openpyxl')
    else:
        raise ValueError("Unsupported file format. Please upload a .csv or .xlsx file.")
    # ------------------------------

    # Convert columns to strings before stripping/lowering to prevent CSV errors
    df.columns = [str(c).strip().lower() for c in df.columns]

    parsed_rows = []
    skipped = []
    inserted = 0

    if preview:
        StagingInvestment.query.filter_by(user_id=user_id).delete()

    for _, row in df.iterrows():
        try:
            # Safely handle CSV empty cells (NaN)
            raw_isin = row.get("isin")
            if pd.notna(raw_isin) and str(raw_isin).strip().upper() != 'NONE':
                isin = str(raw_isin).strip().upper()
            else:
                isin = None

            if not isin:
                skipped.append(("missing ISIN", str(row.to_dict())))
                continue

            fund = Fund.query.filter_by(isin=isin).first()
            if not fund:
                skipped.append((isin, "fund not found"))
                continue

            txn_date = pd.to_datetime(row.get("date"), dayfirst=True).date()
            txn_type = str(row.get("transaction_type")).lower() if pd.notna(row.get("transaction_type")) else ""
            units = float(row.get("quantity"))
            nav = float(row.get("price"))
            amount = float(row.get("amount"))
            source_file = os.path.basename(filepath)

            row_hash = hashlib.sha256(
                f"{user_id}|{isin}|{txn_date}|{amount}|{units}|{nav}".encode()
            ).hexdigest()

            staging = StagingInvestment(
                user_id=user_id,
                isin=isin,
                date=txn_date,
                amount=amount,
                units=units,
                nav=nav,
                transaction_type=txn_type,
                source_file=source_file,
                row_hash=row_hash
            )
            db.session.add(staging)
            inserted += 1

            parsed_rows.append({
                "isin": isin,
                "date": txn_date.strftime("%Y-%m-%d"),
                "transaction_type": txn_type,
                "units": units,
                "nav": nav,
                "amount": amount,
                "source_file": source_file
            })

        except Exception as e:
            skipped.append(("parse error", str(e)))
            continue

    db.session.commit()

    if preview:
        return parsed_rows

    return {"inserted": inserted, "skipped": skipped}