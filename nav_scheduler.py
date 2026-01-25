# nav_scheduler.py

import datetime
import time
from snapshot_generator import generate_personal_snapshots, generate_family_snapshots
from models import db, Fund, Investment, FundNAVHistory, NavUpdateLog, User
from nav_loader import load_all_funds, get_first_investment_date


# ---------------------------------------------------------
# Sleep until next 20:00
# ---------------------------------------------------------
def seconds_until(hour: int, minute: int = 0):
    now = datetime.datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    if target <= now:
        target = target + datetime.timedelta(days=1)

    return (target - now).total_seconds()


# ---------------------------------------------------------
# Cutoff helpers
# ---------------------------------------------------------
def get_last_15th(today: datetime.date) -> datetime.date:
    this_month_15 = today.replace(day=15)
    if today > this_month_15:
        return this_month_15
    else:
        first_this_month = today.replace(day=1)
        prev_month_last = first_this_month - datetime.timedelta(days=1)
        return prev_month_last.replace(day=15)


def get_last_month_end(today: datetime.date) -> datetime.date:
    first_this_month = today.replace(day=1)
    last_prev_month = first_this_month - datetime.timedelta(days=1)
    return last_prev_month


def get_relevant_cutoffs(today: datetime.date):
    return sorted({
        get_last_15th(today),
        get_last_month_end(today)
    })


# ---------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------
def already_successful(cutoff_date: datetime.date) -> bool:
    return NavUpdateLog.query.filter_by(
        scheduled_date=cutoff_date,
        status="success"
    ).first() is not None


def record_log(cutoff_date: datetime.date, status: str, notes: str = None):
    log = NavUpdateLog.query.filter_by(scheduled_date=cutoff_date).first()
    if not log:
        log = NavUpdateLog(scheduled_date=cutoff_date)
        db.session.add(log)
    log.status = status
    log.notes = notes
    db.session.commit()


# ---------------------------------------------------------
# Verify NAVs for all invested funds (investment-aware)
# ---------------------------------------------------------
def verify_cutoff_for_all_funds(cutoff_date: datetime.date) -> bool:
    invested_funds = (
        Fund.query
        .join(Investment, Investment.fund_id == Fund.id)
        .distinct()
        .all()
    )

    missing = []

    for fund in invested_funds:
        first_date = get_first_investment_date(fund.id)

        # Skip funds not yet purchased at this cutoff
        if cutoff_date < first_date:
            continue

        latest = (
            FundNAVHistory.query
            .filter(
                FundNAVHistory.fund_id == fund.id,
                FundNAVHistory.nav_date <= cutoff_date
            )
            .order_by(FundNAVHistory.nav_date.desc())
            .first()
        )

        if not latest:
            missing.append(fund.name)

    if missing:
        print(f"[VERIFY] Missing NAVs for cutoff {cutoff_date}:")
        for name in missing:
            print(f"   - {name}")
        return False

    print(f"[VERIFY] All invested funds have NAV ≤ cutoff {cutoff_date}")
    return True


# ---------------------------------------------------------
# One scheduler iteration
# ---------------------------------------------------------
def run_scheduler_once():
    today = datetime.date.today()
    print(f"\n[SCHEDULER] Today: {today}")

    cutoff_dates = get_relevant_cutoffs(today)
    print(f"[SCHEDULER] Relevant cutoffs: {', '.join(str(c) for c in cutoff_dates)}")

    for cutoff in cutoff_dates:
        print(f"\n[CHECK] Cutoff {cutoff}")

        if already_successful(cutoff):
            print(f"[SKIP] Already marked success for cutoff {cutoff}")
            continue

        print(f"[RUN] Loading NAVs to satisfy cutoff {cutoff}")
        try:
            load_all_funds()

            if verify_cutoff_for_all_funds(cutoff):
                record_log(cutoff, "success", "All invested funds have cutoff NAV")
                print(f"[OK] Logged success for cutoff {cutoff}")

                # 🔥 Generate snapshots for all users AFTER NAV update
                from snapshot_generator import generate_personal_snapshots, generate_family_snapshots
                from models import User, Family

                users = User.query.all()
                for u in users:
                    print(f"[SNAPSHOT] Generating personal snapshot for user {u.id}")
                    generate_personal_snapshots(u.id)

                families = Family.query.all()
                for fam in families:
                    print(f"[SNAPSHOT] Generating family snapshot for family {fam.id}")
                    generate_family_snapshots(fam.id)

            else:
                record_log(cutoff, "fail", "Some funds missing cutoff NAV")
                print(f"[WARN] Logged fail for cutoff {cutoff}")

        except Exception as e:
            record_log(cutoff, "fail", f"Exception during load: {e}")
            print(f"[ERROR] Exception while processing cutoff {cutoff}: {e}")


# ---------------------------------------------------------
# Main loop: run at 20:00 daily
# ---------------------------------------------------------
def main():
    while True:
        print("\n[SCHEDULER] Running scheduled check now")
        run_scheduler_once()

        sleep_seconds = seconds_until(20, 0)
        print(f"[SCHEDULER] Next run at 20:00, sleeping for {sleep_seconds/3600:.2f} hours")

        time.sleep(sleep_seconds)


if __name__ == "__main__":
    from app import app
    with app.app_context():
        main()
