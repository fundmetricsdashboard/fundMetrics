# nav_loader.py

import requests
from datetime import date, timedelta
from dateutil import parser
from decimal import Decimal
from calendar import monthrange
from sqlalchemy.exc import IntegrityError
from models import db, Fund, FundNAVHistory, Investment


# ---------------------------------------------------------
# Helper: earliest investment date for a fund
# ---------------------------------------------------------
def get_first_investment_date(fund_id):
    row = (
        Investment.query
        .filter_by(fund_id=fund_id)
        .order_by(Investment.date.asc())
        .first()
    )
    return row.date if row else None


# ---------------------------------------------------------
# Fetch full NAV history from MFAPI
# ---------------------------------------------------------
def fetch_nav_history(scheme_code: str):
    if not scheme_code:
        return []

    url = f"https://api.mfapi.in/mf/{scheme_code}"
    resp = requests.get(url, timeout=45)
    if resp.status_code != 200:
        print(f"[MFAPI] HTTP {resp.status_code} for scheme {scheme_code}")
        # Raise an exception so the route knows the API failed
        raise ConnectionError(f"MFAPI returned HTTP {resp.status_code}")

    data = resp.json() or {}
    return data.get("data", []) or []


# ---------------------------------------------------------
# Select cutoff NAVs (15th + month-end)
# ---------------------------------------------------------
def select_cutoff_navs(history):
    parsed = []
    for row in history:
        try:
            d = parser.parse(row["date"], dayfirst=True).date()
            v = Decimal(str(row["nav"]))
            parsed.append((d, v))
        except Exception:
            continue

    if not parsed:
        return []

    parsed.sort(key=lambda x: x[0], reverse=True)

    grouped = {}
    for d, v in parsed:
        grouped.setdefault((d.year, d.month), []).append((d, v))

    results = []

    for (year, month), rows in grouped.items():
        mid_cutoff = date(year, month, 15)
        end_cutoff = date(year, month, monthrange(year, month)[1])

        mid = next((r for r in rows if r[0] <= mid_cutoff), None)
        if mid:
            results.append(mid)

        end = next((r for r in rows if r[0] <= end_cutoff), None)
        if end:
            results.append(end)

    return sorted(results, key=lambda x: x[0])


# ---------------------------------------------------------
# Save NAVs (upsert) - REFACTORED FOR ATOMIC COMMITS
# ---------------------------------------------------------
def save_navs(fund: Fund, isin: str, cutoffs):
    for nav_date, nav_value in cutoffs:
        # Check memory/DB first to avoid IntegrityError
        existing = FundNAVHistory.query.filter_by(
            fund_id=fund.id,
            nav_date=nav_date,
            isin=isin,
        ).first()

        if existing:
            existing.nav_value = nav_value
        else:
            entry = FundNAVHistory(
                fund_id=fund.id,
                nav_date=nav_date,
                nav_value=nav_value,
                isin=isin,
                nav_type="growth",
            )
            db.session.add(entry)
            
    # Commit ONCE at the end of the loop
    try:
        db.session.commit()
        print(f"[SAVE SUCCESS] {fund.name}: All cutoffs saved atomically.")
    except Exception as e:
        db.session.rollback()
        print(f"[SAVE FAILED] {fund.name}: Rolling back due to {str(e)}")
        raise e  # Propagate to route to report the exact failure


# ---------------------------------------------------------
# Load NAVs for a single fund (investment-aware)
# ---------------------------------------------------------
def load_navs_for_fund(fund: Fund):
    if not fund.scheme_code:
        print(f"[SKIP:NO_SCHEME] {fund.id} {fund.name}")
        return

    first_date = get_first_investment_date(fund.id)
    if not first_date:
        print(f"[SKIP:NO_INVEST] {fund.id} {fund.name}")
        return
    print(f"[INFO] {fund.id} {fund.name} first_investment_date = {first_date}")

    history = fetch_nav_history(fund.scheme_code)
    print(f"[INFO] {fund.id} {fund.name} history_len = {len(history)}")
    if not history:
        print(f"[MFAPI EMPTY] {fund.id} {fund.name} scheme_code={fund.scheme_code}")
        return

    cutoffs = select_cutoff_navs(history)
    print(f"[INFO] {fund.id} {fund.name} cutoffs_len_before_filter = {len(cutoffs)}")

    filtered = [c for c in cutoffs if c[0] >= first_date]
    print(f"[INFO] {fund.id} {fund.name} cutoffs_len_after_filter = {len(filtered)}")
    cutoffs = filtered

    if not cutoffs:
        print(f"[NO CUTOFFS AFTER INVESTMENT] {fund.id} {fund.name}")
        return

    save_navs(fund, fund.isin, cutoffs)


# ---------------------------------------------------------
# Load NAVs for all invested funds
# ---------------------------------------------------------
def load_all_funds():
    # Only grab funds that exist in the user's investment ledger
    funds = (
        Fund.query
        .join(Investment, Investment.fund_id == Fund.id)
        .distinct()
        .all()
    )

    total = len(funds)
    print(f"[LOAD_ALL] Funds with investments: {total}")

    for idx, fund in enumerate(funds, start=1):
        print(f"\n[LOAD {idx}/{total}] {fund.name}")
        try:
            load_navs_for_fund(fund)
        except Exception as e:
            print(f"[ERROR] Failed to load {fund.name}: {e}")


# ---------------------------------------------------------
# Load NAVs for preview mode
# ---------------------------------------------------------
def load_navs_for_fund_preview(fund: Fund):
    if not fund.scheme_code:
        print(f"[SKIP:NO_SCHEME] {fund.id} {fund.name}")
        raise ValueError("Fund is missing scheme_code")

    history = fetch_nav_history(fund.scheme_code)
    if not history:
        print(f"[MFAPI EMPTY] {fund.id} {fund.name}")
        raise ValueError("MFAPI returned no history")

    cutoffs = select_cutoff_navs(history)
    if not cutoffs:
        print(f"[NO CUTOFFS] {fund.id} {fund.name}")
        raise ValueError("No valid date cutoffs found")

    save_navs(fund, fund.isin, cutoffs)
    return "OK"