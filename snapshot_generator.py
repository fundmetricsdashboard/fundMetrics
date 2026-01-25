# snapshot_generator.py

import datetime
import calendar
from db_config import db
from models import Investment, Fund, FundNAVHistory, PortfolioSnapshot, User
from utils import calculate_fifo_returns


# ---------------------------------------------------------
# Generate cutoff dates (15th + month-end)
# ---------------------------------------------------------
def generate_cutoff_dates(years_back=10):
    """Generate 15th and month-end cutoff dates for the last N years."""
    today = datetime.date.today()
    start_date = today.replace(year=today.year - years_back)

    cutoffs = []
    curr = datetime.date(start_date.year, start_date.month, 1)
    end_month = datetime.date(today.year, today.month, 1)

    while curr <= end_month:
        y, m = curr.year, curr.month
        mid = datetime.date(y, m, 15)
        last = datetime.date(y, m, calendar.monthrange(y, m)[1])
        cutoffs.append(mid)
        cutoffs.append(last)

        curr = datetime.date(y + 1, 1, 1) if m == 12 else datetime.date(y, m + 1, 1)

    return cutoffs


# ---------------------------------------------------------
# NAV lookup for cutoff date
# ---------------------------------------------------------
def get_nav_for_cutoff(fund_id, cutoff):
    """Get NAV on or before cutoff; fallback to next 15 days."""
    nav_record = (
        FundNAVHistory.query
        .filter(
            FundNAVHistory.fund_id == fund_id,
            FundNAVHistory.nav_date <= cutoff
        )
        .order_by(FundNAVHistory.nav_date.desc())
        .first()
    )

    if nav_record:
        return float(nav_record.nav_value)

    # Fallback: next 15 days
    nav_record = (
        FundNAVHistory.query
        .filter(
            FundNAVHistory.fund_id == fund_id,
            FundNAVHistory.nav_date > cutoff,
            FundNAVHistory.nav_date <= cutoff + datetime.timedelta(days=15)
        )
        .order_by(FundNAVHistory.nav_date.asc())
        .first()
    )

    return float(nav_record.nav_value) if nav_record else None


# ---------------------------------------------------------
# PERSONAL SNAPSHOTS
# ---------------------------------------------------------
def generate_personal_snapshots(user_id, years_back=10):
    """Generate FIFO + NAV-history accurate snapshots for a single user."""

    # Delete old snapshots
    PortfolioSnapshot.query.filter_by(
        user_id=user_id,
        dashboard_type="personal"
    ).delete()
    db.session.commit()

    cutoffs = generate_cutoff_dates(years_back)

    # All funds the user has ever invested in
    funds = (
        Fund.query.join(Investment)
        .filter(Investment.user_id == user_id)
        .distinct()
        .all()
    )

    if not funds:
        return

    for cutoff in cutoffs:
        total_value = 0.0

        for fund in funds:
            # All transactions up to cutoff
            txns = (
                Investment.query
                .filter(
                    Investment.user_id == user_id,
                    Investment.fund_id == fund.id,
                    Investment.date <= cutoff
                )
                .order_by(Investment.date)
                .all()
            )

            if not txns:
                continue

            nav_value = get_nav_for_cutoff(fund.id, cutoff)
            if nav_value is None:
                continue

            result = calculate_fifo_returns(txns, nav_value, today=cutoff)
            total_value += result["current_value"]

        if total_value > 0:
            snap = PortfolioSnapshot(
                user_id=user_id,
                snapshot_date=cutoff,
                portfolio_value=round(total_value, 2),
                dashboard_type="personal"
            )
            db.session.add(snap)

    db.session.commit()


# ---------------------------------------------------------
# FAMILY SNAPSHOTS
# ---------------------------------------------------------
def generate_family_snapshots(family_id, years_back=10):
    """
    Generate family snapshots by aggregating all family members.
    Stored with family_id (not user_id) and dashboard_type='family'.
    """
    print(f"[SNAPSHOT] Generating family snapshots for family_id {family_id}")

    # Delete old family snapshots
    PortfolioSnapshot.query.filter_by(
        family_id=family_id,
        dashboard_type="family"
    ).delete()
    db.session.commit()

    # Get all family members
    family_members = User.query.filter_by(family_id=family_id).all()
    member_ids = [m.id for m in family_members]

    if not member_ids:
        print(f"[SNAPSHOT][WARN] No members in family_id {family_id}")
        return

    cutoffs = generate_cutoff_dates(years_back)

    # All funds touched by any family member
    funds = (
        Fund.query.join(Investment)
        .filter(Investment.user_id.in_(member_ids))
        .distinct()
        .all()
    )

    if not funds:
        print(f"[SNAPSHOT] No funds found for family_id {family_id}, skipping.")
        return

    for cutoff in cutoffs:
        total_value = 0.0

        for fund in funds:
            txns = (
                Investment.query
                .filter(
                    Investment.user_id.in_(member_ids),
                    Investment.fund_id == fund.id,
                    Investment.date <= cutoff
                )
                .order_by(Investment.date)
                .all()
            )

            if not txns:
                continue

            nav_value = get_nav_for_cutoff(fund.id, cutoff)
            if nav_value is None:
                continue

            result = calculate_fifo_returns(txns, nav_value, today=cutoff)
            total_value += result["current_value"]

        if total_value > 0:
            snap = PortfolioSnapshot(
                family_id=family_id,
                snapshot_date=cutoff,
                portfolio_value=round(total_value, 2),
                dashboard_type="family"
            )
            db.session.add(snap)

    db.session.commit()
    print(f"[SNAPSHOT] ✅ Family snapshots generated for family_id {family_id}")
