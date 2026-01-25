import datetime
import requests
from bs4 import BeautifulSoup
import re
from sqlalchemy import case

# ===========================
# Date Normalization
# ===========================

def normalize_date(d):
    if isinstance(d, datetime.date) and not isinstance(d, datetime.datetime):
        return datetime.datetime.combine(d, datetime.datetime.min.time())
    elif isinstance(d, datetime.datetime):
        return d
    elif isinstance(d, str):
        try:
            return datetime.datetime.strptime(d, "%Y-%m-%d")
        except ValueError:
            return None
    else:
        return None


# ===========================
# Fund Name Formatter
# ===========================
def format_fund_name(name):
    if not name or not isinstance(name, str):
        return name

    preserve_caps = {'PSU', 'ETF', 'SIP', 'IDCW', 'NAV', 'FMP', 'GILT', 'REIT', 'NFO', 'FOF', 'ICICI', 'HDFC', 'UTI', 'ELSS', 'MNC', 'IDFC'}

    words = name.strip().lower().split()
    formatted = [
        word.upper() if word.upper() in preserve_caps else word.capitalize()
        for word in words
    ]
    return ' '.join(formatted)


# ===========================
# XIRR Calculation
# ===========================

def calculate_xirr(cash_flows, tol=1e-7, max_iter=100):
    """
    Deterministic XIRR using Newton–Raphson with economic guardrails.
    Returns decimal (e.g. 0.234 for 23.4%).
    """

    import datetime

    # Normalize flows
    flows = []
    for dt, amt in cash_flows:
        if isinstance(dt, datetime.datetime):
            dt = dt.date()
        elif isinstance(dt, str):
            try:
                dt = datetime.datetime.strptime(dt, "%Y-%m-%d").date()
            except ValueError:
                continue
        if not isinstance(dt, datetime.date):
            continue
        try:
            amt = float(amt)
        except (TypeError, ValueError):
            continue
        flows.append((dt, amt))

    if not flows or not any(a < 0 for _, a in flows) or not any(a > 0 for _, a in flows):
        return 0.0

    flows.sort(key=lambda x: x[0])
    d0 = flows[0][0]

    def npv(rate):
        total = 0.0
        for dt, amt in flows:
            days = (dt - d0).days
            # guard against invalid base
            if rate <= -0.999999:
                return float("inf")
            total += amt / ((1.0 + rate) ** (days / 365.0))
        return total

    def d_npv(rate):
        total = 0.0
        for dt, amt in flows:
            days = (dt - d0).days
            if rate <= -0.999999:
                return 0.0
            total += -(days/365.0) * amt / ((1.0 + rate) ** ((days/365.0) + 1))
        return total

    # Initial guess: CAGR of inflows vs outflows
    total_out = sum(-amt for _, amt in flows if amt < 0)
    total_in  = sum(amt for _, amt in flows if amt > 0)
    years = max((flows[-1][0] - d0).days / 365.0, 1e-6)
    guess = (total_in / total_out) ** (1.0 / years) - 1.0 if total_out > 0 else 0.1

    # clamp guess into safe domain
    rate = max(min(guess, 5.0), -0.9)

    for _ in range(max_iter):
        f = npv(rate)
        df = d_npv(rate)
        if abs(df) < 1e-12:
            break
        new_rate = rate - f / df
        # guard against complex or invalid jumps
        if isinstance(new_rate, complex):
            return 0.0
        if new_rate <= -0.999999:
            return 0.0
        if abs(new_rate - rate) < tol:
            rate = new_rate
            break
        # cap extreme jumps
        if abs(new_rate - rate) > 1.0:
            new_rate = rate + (1.0 if new_rate > rate else -1.0)
        rate = new_rate

    # Economic guardrail: enforce sign consistency
    net_gain = total_in - total_out
    if net_gain > 0 and rate < 0:
        return 0.0
    if net_gain < 0 and rate > 0:
        return 0.0

    return float(rate) if not isinstance(rate, complex) else 0.0



# ===========================
# Portfolio Holdings Calculator
# ===========================

from models import Investment, Fund, FundNAVHistory
from sqlalchemy import func

def get_portfolio_holdings(db, user_id):
    """
    Compute current holdings for a user:
    - net_units (buys - sells)
    - latest NAV from fund_nav_history
    - market_value
    - percentage of portfolio
    Returns a list of dicts.
    """

    # Step 1: aggregate net units per ISIN
    holdings = (
        db.session.query(
            Investment.isin,
            func.sum(
                case(
                    (Investment.transaction_type.ilike('buy'), Investment.units),
                    else_=-Investment.units
                )
            ).label('net_units')
        )
        .filter(Investment.user_id == user_id)
        .group_by(Investment.isin)
        .all()
    )

    results = []
    portfolio_total = 0

    # Step 2: fetch latest NAV for each ISIN
    for isin, net_units in holdings:
        if not isin or not net_units or net_units <= 0:
            continue

        latest_nav_lookup = (
            db.session.query(FundNAVHistory.nav_value, FundNAVHistory.nav_date)
            .filter(FundNAVHistory.isin == isin)
            .order_by(FundNAVHistory.nav_date.desc())
            .first()
        )

        if not latest_nav_lookup:
            continue

        latest_nav, nav_date = latest_nav_lookup
        market_value = float(net_units) * float(latest_nav)
        portfolio_total += market_value

        fund = Fund.query.filter_by(isin=isin).first()
        fund_name = fund.name if fund else isin

        results.append({
            "isin": isin,
            "fund_name": fund_name,
            "net_units": float(net_units),
            "latest_nav": float(latest_nav),
            "nav_date": nav_date,
            "market_value": market_value,
            "pct_of_portfolio": 0.0  # placeholder, fill after total known
        })

    # Step 3: compute percentages
    if portfolio_total > 0:
        for r in results:
            r["pct_of_portfolio"] = round((r["market_value"] / portfolio_total) * 100, 2)

    return results

# ======== FIFO returns plus XIRR=============

def calculate_fifo_returns(transactions, latest_nav, today=None):
    import datetime
    if today is None:
        today = datetime.date.today()

    txns = sorted(transactions, key=lambda t: t.date)

    buy_lots = []
    cash_flows = []

    for t in txns:
        if t.transaction_type.lower() == 'buy':
            buy_lots.append({
                'date': t.date.date() if isinstance(t.date, datetime.datetime) else t.date,
                'units': float(t.units or 0),
                'cost': float(t.amount or 0)
            })
            cash_flows.append((t.date, -float(t.amount or 0)))

        elif t.transaction_type.lower() == 'sell':
            units_to_sell = abs(float(t.units or 0))  # ✅ normalize units
            cash_flows.append((t.date, abs(float(t.amount or 0))))  # ✅ treat amount as inflow

            while units_to_sell > 0 and buy_lots:
                lot = buy_lots[0]
                if lot['units'] <= 0:
                    buy_lots.pop(0)
                    continue

                matched_units = min(lot['units'], units_to_sell)
                proportion = matched_units / lot['units']
                lot['cost'] -= lot['cost'] * proportion
                lot['units'] -= matched_units
                units_to_sell -= matched_units

                if lot['units'] <= 1e-9:
                    buy_lots.pop(0)

    remaining_units = sum(lot['units'] for lot in buy_lots)
    remaining_cost = sum(lot['cost'] for lot in buy_lots)

    # ===== Cost‑Weighted Holding Period (years) =====
    weighted_days_sum = 0.0
    total_cost = 0.0

    for lot in buy_lots:
        if lot["cost"] > 0:
            days_held = (today - lot["date"]).days
            weighted_days_sum += days_held * float(lot["cost"])
            total_cost += float(lot["cost"])

    holding_period_years = (weighted_days_sum / total_cost / 365.0) if total_cost > 0 else 0.0

    current_value = float(remaining_units) * float(latest_nav or 0)
    if current_value > 0:
        cash_flows.append((today, current_value))

    # Debug print
    #print(">>> DEBUG CASH FLOWS FEED to XIRR")
    #for dt, amt in sorted(cash_flows, key=lambda x: x[0]):
    #    print(f"   {dt}  {amt:+,.2f}")

    absolute_return = current_value - remaining_cost
    xirr_val = calculate_xirr(cash_flows) if cash_flows else 0.0

    return {
        "remaining_units": remaining_units,
        "cost_value": remaining_cost,
        "current_value": current_value,
        "absolute_return": absolute_return,
        "xirr": xirr_val,
        "cash_flows": cash_flows,     
        "remaining_lots": buy_lots,
        "holding_period": holding_period_years    
    }

