import os
import pandas as pd
import hashlib
from db_config import db
from models import Fund, StagingInvestment


def process_karvy_statement(filepath, user_id, preview=False):
    """
    Karvy statement parser.

    preview=True:
        - Clears old staging rows for this user
        - Parses file
        - Inserts ALL valid rows into staging_investment
        - Returns parsed rows for UI

    preview=False:
        - Same parsing logic
        - Inserts into staging (not Investment)
        - Returns inserted/skipped counts
    """

    # Load Excel
    df = pd.read_excel(filepath, sheet_name="Sheet1")
    df.columns = [c.strip() for c in df.columns]

    parsed_rows = []
    skipped = []
    inserted = 0

    # Clear old staging rows in preview mode
    if preview:
        StagingInvestment.query.filter_by(user_id=user_id).delete()

    # Transaction description mapping
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

        "redemption": "sell",
        "redemption(nav dt": "sell",
        "switch out": "sell",
        "lateral shift out": "sell",
        "switch over out": "sell"
    }


    for _, row in df.iterrows():
        try:
            isin = str(row.get("SchemeISIN")).strip().upper() if row.get("SchemeISIN") else None
            scheme_name = str(row.get("Scheme Description")).strip() if row.get("Scheme Description") else None

            # Missing ISIN → skip
            if not isin:
                skipped.append((isin, scheme_name, "missing ISIN"))
                continue

            fund = Fund.query.filter_by(isin=isin).first()
            if not fund:
                skipped.append((isin, scheme_name, "fund not found"))
                continue

            # Classify transaction
            desc = str(row.get("Transaction Description")).lower()
            txn_type = None

            for key, value in txn_map.items():
                if key in desc:
                    txn_type = value
                    break

            # Skip IDCW payout, IDCW reinvestment, address updates, etc.
            if not txn_type:
                skipped.append((isin, scheme_name, "non-financial event"))
                continue

            # Parse fields
            txn_date = pd.to_datetime(row.get("Transaction Date"), dayfirst=True).date()
            amount = float(row.get("Amount"))
            units = float(row.get("Units"))
            nav = float(row.get("NAV"))
            folio = str(row.get("Account Number"))
            source_file = os.path.basename(filepath)

            # Build row hash for duplicate detection
            row_hash = hashlib.sha256(
                f"{user_id}|{isin}|{txn_date}|{amount}|{units}|{nav}".encode()
            ).hexdigest()

            # Insert into staging (preview OR commit mode)
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

            # Add to parsed_rows for UI preview
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
            skipped.append((row.get("SchemeISIN"), row.get("Scheme Description"), f"parse error: {e}"))
            continue

    # Commit staging rows
    db.session.commit()

    # Preview mode returns parsed rows
    if preview:
        return parsed_rows

    # Commit mode returns summary
    return {
        "inserted": inserted,
        "skipped": skipped
    }
