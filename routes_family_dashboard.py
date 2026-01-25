# routes_family_dashboard.py

from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for, flash
from datetime import datetime, timedelta, date
from models import db, User, Investment, Fund, FundNAVHistory
from utils import calculate_xirr, calculate_fifo_returns, format_fund_name
from flask_login import current_user, login_required


family_dashboard_bp = Blueprint(
    "family_dashboard_bp",
    __name__,
    template_folder="../templates"
)

# ---------------------------------------------------------
# Helper: Aggregate FIFO results for all users in a family
# ---------------------------------------------------------
def aggregate_family_investments(family_users):
    user_ids = [u.id for u in family_users]

    # Fetch all investments for all users in the family
    investments = (
        Investment.query
        .filter(Investment.user_id.in_(user_ids))
        .order_by(Investment.date)
        .all()
    )

    # Group transactions by fund
    txns_by_fund = {}
    for inv in investments:
        txns_by_fund.setdefault(inv.fund_id, []).append(inv)

    aggregated = {}
    today = date.today()

    # For summary-level XIRR
    summary_cash_flows = []
    summary_portfolio_value = 0.0
    summary_cost_value = 0.0
    summary_weighted_days_sum = 0.0

    for fund_id, txns in txns_by_fund.items():
        fund = Fund.query.get(fund_id)
        if not fund:
            continue

        # NAV fallback identical to main dashboard
        nav_row = (
            db.session.query(FundNAVHistory.nav_value)
            .filter(FundNAVHistory.fund_id == fund.id)
            .order_by(FundNAVHistory.nav_date.desc())
            .first()
        )

        latest_nav = float(nav_row[0]) if nav_row else 0.0


        # FIFO calculation identical to main dashboard
        result = calculate_fifo_returns(txns, latest_nav, today=today)

        # Add cash flows for portfolio-level XIRR
        summary_cash_flows.extend(result.get("cash_flows", []))

        # Synthetic inflow per fund (identical to main dashboard)
        if result["remaining_units"] > 0:
            summary_cash_flows.append({
                "date": today,
                "amount": result["current_value"]
            })

        # Weighted days identical to main dashboard
        for lot in result["remaining_lots"]:
            if lot["cost"] > 0:
                days_held = (today - lot["date"]).days
                summary_weighted_days_sum += days_held * float(lot["cost"])

        # Portfolio totals identical to main dashboard
        summary_cost_value += float(result["cost_value"])
        summary_portfolio_value += float(result["current_value"])

        aggregated[fund_id] = {
            "fund": fund,
            "fund_display_name": format_fund_name(fund.name),
            "subcategory": fund.sub_category.name if fund.sub_category else "—",
            "category": fund.sub_category.category.name if fund.sub_category and fund.sub_category.category else "Unknown",
            "plan_type": txns[0].plan_type if txns and txns[0].plan_type else (
                "Direct" if "direct" in fund.name.lower() else "Regular"
            ),
            "units": float(result["remaining_units"]),
            "cost_value": float(result["cost_value"]),
            "current_value": float(result["current_value"]),
            "xirr": result["xirr"],  # per-fund XIRR identical to main dashboard
            "transactions": result["cash_flows"],
        }

    # Final portfolio-level metrics identical to main dashboard
    summary_wt_avg_days = round(summary_weighted_days_sum / summary_cost_value, 0) if summary_cost_value else 0
    summary_xirr = calculate_xirr(summary_cash_flows) if summary_cash_flows else 0.0
    summary_appreciation = summary_portfolio_value - summary_cost_value

    return (aggregated, 
        summary_portfolio_value, 
        summary_cost_value, 
        summary_appreciation, 
        summary_wt_avg_days, 
        summary_xirr
    )
# ---------------------------------------------------------
# Helper: Category-level pie chart
# ---------------------------------------------------------
def build_family_category_breakup(aggregated):
    category_totals = {}

    for data in aggregated.values():
        cat = data["category"]
        category_totals.setdefault(cat, 0)
        category_totals[cat] += data["current_value"]

    labels = list(category_totals.keys())
    full_values = list(category_totals.values())
    values_in_millions = [v / 1e6 for v in full_values]

    return labels, values_in_millions, full_values


# ---------------------------------------------------------
# Helper: Subcategory bar chart
# ---------------------------------------------------------
def build_family_subcategory_breakup(aggregated):
    subcat_totals = {}
    total_value = sum(d["current_value"] for d in aggregated.values()) or 1

    for data in aggregated.values():
        sub = data["subcategory"]
        cat = data["category"]

        subcat_totals.setdefault(sub, {
            "subcategory": sub,
            "category": cat,
            "amount": 0
        })
        subcat_totals[sub]["amount"] += data["current_value"]

    # Compute percentages
    for v in subcat_totals.values():
        v["percent"] = (v["amount"] / total_value) * 100

    # Manual category priority
    category_priority = {
        "Debt": 1,
        "Equity": 2,
        "Commodity": 3
    }

    # Deterministic multi-level sort
    sorted_list = sorted(
        subcat_totals.values(),
        key=lambda x: (
            category_priority.get(x["category"], 999),
            x["amount"]
        )
    )

    return sorted_list


# ---------------------------------------------------------
# Helper: Top 5 holdings
# ---------------------------------------------------------
def build_family_top5(aggregated):
    rows = []
    total_value = sum(d["current_value"] for d in aggregated.values()) or 1

    for data in aggregated.values():
        rows.append({
            "fund_display_name": data["fund_display_name"],
            "subcategory": data["subcategory"],
            "plan_type": data["plan_type"],
            "amount": data["current_value"],
            "percent_holding": (data["current_value"] / total_value) * 100,
            "xirr": data["xirr"],
            "fund": data["fund"]
        })

    rows.sort(key=lambda x: x["amount"], reverse=True)
    return rows[:5]


# ---------------------------------------------------------
# Helper: Weighted average days
# ---------------------------------------------------------
def compute_family_weighted_days(aggregated):
    total_cost = sum(d["cost_value"] for d in aggregated.values()) or 1
    today = date.today()

    weighted_sum = 0

    for data in aggregated.values():
        for tx in data["transactions"]:
            if isinstance(tx, dict):
                tx_date = tx["date"]
                tx_amount = tx["amount"]
            elif isinstance(tx, (tuple, list)) and len(tx) == 2:
                tx_date = tx[0]
                tx_amount = tx[1]
            else:
                continue

            days = (today - tx_date).days
            weighted_sum += tx_amount * days

    return abs(weighted_sum / total_cost)


# ---------------------------------------------------------
# Family Dashboard - Last NAV Update table
# ---------------------------------------------------------
@family_dashboard_bp.route("/last-nav-update")
@login_required
def last_nav_update():
    import datetime
    now = datetime.datetime.now()

    family_users = User.query.filter_by(family_id=current_user.family_id).all()
    family_user_ids = [u.id for u in family_users]

    invested_funds = (
        Fund.query
        .join(Investment, Investment.fund_id == Fund.id)
        .filter(Investment.user_id.in_(family_user_ids))
        .distinct()
        .all()
    )


    rows = []

    for fund in invested_funds:
        latest_nav_entry = (
            FundNAVHistory.query
            .filter_by(fund_id=fund.id)
            .order_by(FundNAVHistory.nav_date.desc())
            .first()
        )

        formatted_name = format_fund_name(fund.name or "")

        rows.append({
            "fund_name": formatted_name,
            "isin": fund.isin,
            "latest_nav_date": latest_nav_entry.nav_date if latest_nav_entry else None,
            "latest_nav_value": latest_nav_entry.nav_value if latest_nav_entry else None,
        })

    return render_template("lastNAVupdate.html", rows=rows, now=now)


# ---------------------------------------------------------
# Family Dashboard Route
# ---------------------------------------------------------
@family_dashboard_bp.route("/family")
@login_required
def family_dashboard():
    user = current_user

    # Fetch all users in the same family
    family_users = User.query.filter_by(family_id=user.family_id).all()
    if not family_users:
        return render_template("family_dashboard.html", empty=True)

    # ---------------------------------------------------------
    # 1. AGGREGATION (IDENTICAL TO MAIN DASHBOARD LOGIC)
    # ---------------------------------------------------------
    (
        aggregated,
        family_portfolio_value,
        family_cost_value,
        family_appreciation,
        family_wt_avg_days,
        family_xirr
    ) = aggregate_family_investments(family_users)
    family_category_labels, family_category_values_in_millions, family_category_full_values = \
        build_family_category_breakup(aggregated)
    family_grouped_subcategories = build_family_subcategory_breakup(aggregated)

    # ---------------------------------------------------------
    # 2. CATEGORY BREAKUP (IDENTICAL TO MAIN DASHBOARD)
    # ---------------------------------------------------------
    category_totals = {}
    for data in aggregated.values():
        category = data["category"]
        category_totals.setdefault(category, 0.0)
        category_totals[category] += data["current_value"]

    category_breakup = []
    for category, amount in category_totals.items():
        percent = (amount / family_portfolio_value * 100) if family_portfolio_value else 0
        category_breakup.append({
            "category": category,
            "amount": round(amount, 2),
            "percent": round(percent, 2)
        })

    category_breakup.sort(key=lambda x: x["percent"], reverse=True)

    # ---------------------------------------------------------
    # 3. SUBCATEGORY BREAKUP (IDENTICAL TO MAIN DASHBOARD)
    # ---------------------------------------------------------
    subcategory_totals = {}
    for data in aggregated.values():
        subcat = data["subcategory"]
        subcategory_totals.setdefault(subcat, 0.0)
        subcategory_totals[subcat] += data["current_value"]

    subcategory_breakup = []
    for subcat, amount in subcategory_totals.items():
        percent = (amount / family_portfolio_value * 100) if family_portfolio_value else 0
        subcategory_breakup.append({
            "subcategory": subcat,
            "amount": round(amount, 2),
            "percent": round(percent, 2)
        })

    subcategory_breakup.sort(key=lambda x: x["percent"], reverse=True)

    # ---------------------------------------------------------
    # 4. TOP 5 HOLDINGS (IDENTICAL TO MAIN DASHBOARD)
    # ---------------------------------------------------------
    top_holdings = build_family_top5(aggregated)

    family_xirr_display = round(family_xirr * 100, 2) if family_xirr else 0

    # ---------------------------------------------------------
    # 5. RENDER TEMPLATE
    # ---------------------------------------------------------
    return render_template(
        "family_dashboard.html",
        user=current_user,        
        family_users=family_users,
        aggregated=aggregated,
        family_portfolio_value=round(family_portfolio_value, 2),
        family_cost_value=round(family_cost_value, 2),
        family_appreciation=round(family_appreciation, 2),
        family_wt_avg_days=family_wt_avg_days,
        family_xirr=family_xirr_display,
        category_breakup=category_breakup,
        subcategory_breakup=subcategory_breakup,
        top_holdings=top_holdings,
        family_id=current_user.family_id,
        family_category_labels=family_category_labels,
        family_category_values_in_millions=family_category_values_in_millions,
        family_category_full_values=family_category_full_values,
        family_grouped_subcategories=family_grouped_subcategories,

    )

# ---------------------------------------------------------
# API: Family Portfolio History (for Chart.js)
# ---------------------------------------------------------

@family_dashboard_bp.route("/family-portfolio-history")
@login_required
def family_portfolio_history():
    from models import PortfolioSnapshot
    from sqlalchemy import func
    from datetime import date

    family_id = current_user.family_id
    if not family_id:
        # No family → fall back to empty for now (or later: personal snapshots)
        return jsonify([])

    years = request.args.get("years", 3, type=int)
    cutoff_date = date.today().replace(year=date.today().year - years)

    snapshots = (
        db.session.query(
            PortfolioSnapshot.snapshot_date,
            func.sum(PortfolioSnapshot.portfolio_value).label("total_value")
        )
        .filter(
            PortfolioSnapshot.family_id == family_id,
            PortfolioSnapshot.dashboard_type == "family",
            PortfolioSnapshot.snapshot_date >= cutoff_date
        )
        .group_by(PortfolioSnapshot.snapshot_date)
        .order_by(PortfolioSnapshot.snapshot_date)
        .all()
    )

    return jsonify([
        {
            "date": snap.snapshot_date.strftime("%Y-%m-%d"),
            "value": float(snap.total_value)
        }
        for snap in snapshots
    ])

