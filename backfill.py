# backfill.py
import datetime
from app import app                # import your Flask app object
from models import db, NavUpdateLog, FundNAVHistory

def backfill_logs(start_date, end_date):
    """
    Backfill NavUpdateLog entries between start_date and end_date.
    For each cutoff (1st and 16th), mark 'success' if NAVs exist on/after cutoff,
    otherwise mark 'fail'.
    """
    day = start_date
    cutoffs = []
    while day <= end_date:
        if day.day in (1, 16):
            cutoffs.append(day)
        day += datetime.timedelta(days=1)

    for cutoff in cutoffs:
        # Check if NAVs exist on/after cutoff
        has_nav = db.session.query(FundNAVHistory.id)\
            .filter(FundNAVHistory.nav_date >= cutoff)\
            .limit(1).first()

        status = "success" if has_nav else "fail"
        notes = "Backfilled based on NAV presence" if has_nav else "No NAV entries on/after cutoff"

        existing = NavUpdateLog.query.filter_by(scheduled_date=cutoff).first()
        if not existing:
            log = NavUpdateLog(scheduled_date=cutoff, status=status, notes=notes)
            db.session.add(log)
            print(f"Inserted log for {cutoff}: {status}")
        else:
            print(f"Log already exists for {cutoff}, skipping.")

    db.session.commit()


if __name__ == "__main__":
    # Run inside Flask app context
    with app.app_context():
        start_date = datetime.date(2025, 10, 15)   # backfill from mid-Oct
        end_date = datetime.date.today()
        backfill_logs(start_date, end_date)
