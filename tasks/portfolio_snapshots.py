from datetime import date, timedelta
from calendar import monthrange

from sqlalchemy import func

from db_config import db
from models import User, Fund, Investment, FundNAVHistory, PortfolioSnapshot
from utils import calculate_fifo_returns


def generate_snapshot_dates(start_year=None):
    """
    Generate mid-month (15th) and month-end dates
    from earliest Investment.date (or start_year) up to today.
    """
    if start_year is None:
        earliest = db.session.query(func.min(Investment.date)).scalar()
        if earliest is None:
            return []
        start_year = earliest.year

    dates = []
    end = date.today()
    current = date(start_year, 1, 1)

    while current <= end:
        y, m = current.year, current.month
        mid = date(y, m, 15)
        last_day = monthrange(y, m)[1]
        month_end = date(y, m, last_day)

        if mid <= end:
            dates.append(mid)
        if month_end <= end:
            dates.append(month_end)

        if m == 12:
            current = date(y + 1, 1, 1)
        else:
            current = date(y, m + 1, 1)

    return sorted(set(dates))


def calculate_portfolio_value_at_date(user_id, cutoff_date):
    """
    Calculate total portfolio value at a specific date for a user,
    using your existing FIFO engine.
    """
    funds = (
        Fund.query
        .join(Investment, Investment.fund_id == Fund.id)
        .filter(
            Investment.user_id == user_id,
            Investment.date <= cutoff_date
        )
        .distinct()
        .all()
    )

    total_value = 0.0

    for fund in funds:
        nav_record = (
            FundNAVHistory.query
            .filter(
                FundNAVHistory.fund_id == fund.id,
                FundNAVHistory.nav_date <= cutoff_date
            )
            .order_by(FundNAVHistory.nav_date.desc())
            .first()
        )

        if nav_record is None:
            nav_record = (
                FundNAVHistory.query
                .filter(
                    FundNAVHistory.fund_id == fund.id,
                    FundNAVHistory.nav_date > cutoff_date,
                    FundNAVHistory.nav_date <= cutoff_date + timedelta(days=15)
                )
                .order_by(FundNAVHistory.nav_date.asc())
                .first()
            )

        if nav_record is None:
            continue

        txns = (
            Investment.query
            .filter(
                Investment.user_id == user_id,
                Investment.fund_id == fund.id,
                Investment.date <= cutoff_date
            )
            .order_by(Investment.date)
            .all()
        )

        if not txns:
            continue

        result = calculate_fifo_returns(
            txns,
            float(nav_record.nav_value),
            today=cutoff_date
        )

        total_value += float(result["current_value"])

    return round(total_value, 2)


def rebuild_user_snapshots(user_id, start_year=None):
    """
    Rebuild all snapshots for a user.
    """
    dates = generate_snapshot_dates(start_year)
    if not dates:
        return

    PortfolioSnapshot.query.filter_by(user_id=user_id).delete()

    snapshots = []
    for cutoff_date in dates:
        value = calculate_portfolio_value_at_date(user_id, cutoff_date)
        if value > 0:
            snapshots.append(
                PortfolioSnapshot(
                    user_id=user_id,
                    snapshot_date=cutoff_date,
                    portfolio_value=value,
                )
            )

    if snapshots:
        db.session.bulk_save_objects(snapshots)
    db.session.commit()


def rebuild_all_snapshots():
    """
    Rebuild snapshots for all users.
    """
    users = User.query.all()
    for user in users:
        rebuild_user_snapshots(user.id)
