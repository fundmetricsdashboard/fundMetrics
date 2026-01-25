from sqlalchemy import func, text
from models import db, Fund, FundNAVHistory
from app import app  # import your Flask app

def backfill_fund_nav_history():
    print("[BACKFILL] Starting NAV history backfill...")

    # Build a map of fund name -> fund_id for quick lookups
    funds = db.session.query(Fund).all()
    fund_name_map = {f.name.lower().strip(): f.id for f in funds}

    inserted_count = 0
    skipped_count = 0

    # Fetch all raw NAV rows
    raw_rows = db.session.execute(
        text("""
            SELECT scheme_name, nav_date, nav_value
            FROM raw_nav_history
            ORDER BY nav_date ASC
        """)
    ).fetchall()

    for scheme_name, nav_date, nav_value in raw_rows:
        key = scheme_name.lower().strip()
        fund_id = fund_name_map.get(key)

        if not fund_id:
            skipped_count += 1
            continue

        # Check if this fund/date already exists in fund_nav_history
        exists = db.session.query(FundNAVHistory).filter_by(
            fund_id=fund_id,
            nav_date=nav_date
        ).first()

        if exists:
            skipped_count += 1
            continue

        # Insert new history row
        db.session.add(FundNAVHistory(
            fund_id=fund_id,
            nav_date=nav_date,
            nav_value=nav_value
        ))
        inserted_count += 1

    try:
        db.session.commit()
        print(f"[BACKFILL] Complete. Inserted: {inserted_count}, Skipped: {skipped_count}")
    except Exception as e:
        db.session.rollback()
        print(f"[BACKFILL] Error committing changes: {e}")

if __name__ == "__main__":
    with app.app_context():
        backfill_fund_nav_history()
