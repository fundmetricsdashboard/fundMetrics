import os
import hashlib
import pandas as pd
from db_config import db
from models import Fund, StagingInvestment


def process_cams_statement(filepath, user_id, batch_id=None, preview=False):
    """
    Updated CAMS parser aligned with Karvy parser logic.
    Uses actual CAMS file headers:
    FundName, Date, Transaction, ISIN, Amount, Units, Price, FolioNo
    """

    # --- NEW FILE READING LOGIC ---
    filename = filepath.lower()
    
    if filename.endswith('.csv'):
        df = pd.read_csv(filepath)
    elif filename.endswith(('.xls', '.xlsx')):
        df = pd.read_excel(filepath, engine='openpyxl')
    else:
        raise ValueError("Unsupported file format. Please upload a .csv or .xlsx file.")
    # ------------------------------

    # Convert columns to strings before stripping to prevent errors with empty/weird CSV headers
    df.columns = [str(c).strip() for c in df.columns]

    parsed_rows = []
    skipped = []
    inserted = 0

    if preview:
        StagingInvestment.query.filter_by(user_id=user_id, batch_id=batch_id).delete()

    txn_map = {
        "purchase": "buy",
        "additional purchase": "buy",
        "sys. investment": "buy",
        "switch in": "buy",
        "online purchase": "buy",
        "new purchase": "buy",
        "purchase(nav dt": "buy",
        "lateral shift in": "buy",
        "switch over in": "buy",
        "buy": "buy",

        "redemption": "sell",
        "redemption(nav dt": "sell",
        "switch out": "sell",
        "lateral shift out": "sell",
        "switch over out": "sell",
        "sell": "sell"
    }

    for _, row in df.iterrows():
        try:
            # Correct headers
            isin = str(row.get("ISIN")).strip().upper() if pd.notna(row.get("ISIN")) else None
            scheme_name = str(row.get("FundName")).strip() if pd.notna(row.get("FundName")) else None

            if not isin or isin == 'NONE':
                skipped.append((isin, scheme_name, "missing ISIN"))
                continue

            fund = Fund.query.filter_by(isin=isin).first()
            if not fund:
                skipped.append((isin, scheme_name, "fund not found"))
                continue

            # Transaction classification
            desc = str(row.get("Transaction")).lower() if pd.notna(row.get("Transaction")) else ""
            txn_type = None

            for key, value in txn_map.items():
                if key in desc:
                    txn_type = value
                    break

            if not txn_type:
                skipped.append((isin, scheme_name, "non-financial event"))
                continue

            # Strict parsing
            txn_date = pd.to_datetime(row.get("Date")).date()
            amount = float(row.get("Amount"))
            units = float(row.get("Units"))
            nav = float(row.get("Price"))
            folio = str(row.get("FolioNo"))
            source_file = os.path.basename(filepath)

            row_hash = hashlib.sha256(
                f"{user_id}|{isin}|{txn_date}|{amount}|{units}|{nav}".encode()
            ).hexdigest()

            staging = StagingInvestment(
                user_id=user_id,
                batch_id=batch_id,
                isin=isin,
                date=txn_date,
                amount=amount,
                units=units,
                nav=nav,
                transaction_type=txn_type,
                source_file=source_file,
                row_hash=row_hash,
                folio_number=folio
            )
            db.session.add(staging)
            inserted += 1

            parsed_rows.append({
                "isin": isin,
                "scheme_name": scheme_name,
                "transaction_type": txn_type,
                "date": txn_date.strftime('%Y-%m-%d'),
                "amount": amount,
                "units": units,
                "nav": nav,
                "folio": folio,
                "source_file": source_file
            })

        except Exception as e:
            skipped.append((row.get("ISIN"), row.get("FundName"), f"parse error: {e}"))
            continue

    db.session.commit()

    if preview:
        return parsed_rows

    return {"inserted": inserted, "skipped": skipped}