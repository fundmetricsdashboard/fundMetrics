from datetime import date
from nav_scheduler import nav_scheduler_job
from models import db, NavUpdateLog
from db_config import app  # Import your Flask app instance

if __name__ == "__main__":
    with app.app_context():  # <-- This is the fix
        print("🚀 Running NAV scheduler job manually...")
        nav_scheduler_job()

        print("\n📜 NAV Update Log (most recent entries):")
        logs = NavUpdateLog.query.order_by(NavUpdateLog.run_timestamp.desc()).limit(5).all()
        for log in logs:
            print(f"Date: {log.scheduled_date} | Status: {log.status} | Notes: {log.notes} | Run at: {log.run_timestamp}")
