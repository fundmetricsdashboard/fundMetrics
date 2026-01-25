import datetime
from flask import Blueprint, render_template, session, request, jsonify
from flask_login import current_user
from models import User, Investment, Fund, FundNAVHistory, StagingInvestment
from sqlalchemy import func, case, extract
from utils import calculate_xirr, format_fund_name, get_portfolio_holdings, calculate_fifo_returns
from db_config import db
from nav_loader import load_navs_for_fund_preview

dashboard_bp = Blueprint('dashboard_bp', __name__)

# ===========================
# Dashboard Main Route
# ===========================
@dashboard_bp.route("/dashboard/<int:user_id>", endpoint="dashboard")
def dashboard(user_id):
    user = User.query.get_or_404(user_id)
    has_data = Investment.query.filter_by(user_id=user_id).first()
    if not has_data:
        from flask import flash, redirect, url_for
        flash("Welcome! Please upload your first statement to get started.")
        return redirect(url_for('upload_center'))
    family_name = user.family.name if user.family else None
    session["user_id"] = user.id
    transactions = Investment.query.filter_by(user_id=user.id).order_by(Investment.date).all()

    fund_map = {}
    for txn in transactions:
        fund = txn.fund
        subcategory = fund.sub_category
        category = subcategory.category if subcategory else None

        if txn.fund_id not in fund_map:
            fund_map[txn.fund_id] = {
                'fund': fund,
                'buys': [],
                'sells': [],
                'subcategory': subcategory,
                'category': category
            }

        if txn.transaction_type == 'buy':
            fund_map[txn.fund_id]['buys'].append(txn)
        elif txn.transaction_type == 'sell':
            fund_map[txn.fund_id]['sells'].append(txn)

    equity_investments = []
    debt_investments = []
    hybrid_investments = []
    commodity_investments = []
    category_totals = {'Equity': 0, 'Debt': 0, 'Hybrid': 0, 'Commodity': 0}
    subcategory_totals = {}
    fund_house_totals = {}

    for data in fund_map.values():
        fund = data['fund']
        buys = data['buys']
        sells = data['sells']
        category_name = data['category'].name if data['category'] else None
        subcategory_name = data['subcategory'].name if data['subcategory'] else None

        # Use centralized FIFO returns calculator
        fund_txns = buys + sells
        nav_row = (
            db.session.query(FundNAVHistory.nav_value)
            .filter(FundNAVHistory.fund_id == fund.id)
            .order_by(FundNAVHistory.nav_date.desc())
            .first()
        )

        latest_nav = float(nav_row[0]) if nav_row else 0.0


        returns = calculate_fifo_returns(fund_txns, latest_nav)

        net_amount = sum(b.amount for b in buys) - sum(s.amount for s in sells)

        summary = {
            'fund': fund,
            'subcategory': data['subcategory'].name if data['subcategory'] else '—',
            'net_amount': net_amount,
            'current_value': returns["current_value"],
            'amount': returns["current_value"],
            'buy_date': min(b.date for b in buys) if buys else None,
            'sell_date': max(s.date for s in sells) if sells else None,
            'xirr': returns["xirr"],
            'fund_display_name': format_fund_name(fund.name),
            'plan_type': buys[0].plan_type if buys and buys[0].plan_type else (
                'Direct' if 'direct' in fund.name.lower() else 'Regular'
            ),       
        }


        if category_name == 'Equity':
            equity_investments.append(summary)
        elif category_name == 'Debt':
            debt_investments.append(summary)
        elif category_name == 'Hybrid':
            hybrid_investments.append(summary)
        elif category_name == 'Commodity':
            commodity_investments.append(summary)

        if returns["current_value"] <= 1000:
            continue

        if subcategory_name:
            if subcategory_name not in subcategory_totals:
                subcategory_totals[subcategory_name] = {'amount': 0, 'category': category_name}
            subcategory_totals[subcategory_name]['amount'] += returns["current_value"]

        fh_name = fund.fund_house or "Unknown"
        fund_house_totals[fh_name] = fund_house_totals.get(fh_name, 0) + returns["current_value"]




    # ===== Summary Card Calculations (transaction-driven, no silent exclusions) =====
    all_holdings = equity_investments + debt_investments + hybrid_investments + commodity_investments

    # Build comprehensive fund_meta: include all funds referenced in transactions
    fund_meta = {}

    # Collect all fund_ids from transactions
    fund_ids_in_txn = {t.fund_id for t in transactions if t.fund_id is not None}
    fund_rows = Fund.query.filter(Fund.id.in_(fund_ids_in_txn)).all()

    # Preload latest NAV by fund_id from FundNAVHistory
    latest_nav_by_isin = {}
    for f in fund_rows:
        nav_row = (
            db.session.query(FundNAVHistory.nav_value)
            .filter(FundNAVHistory.fund_id == f.id)
            .order_by(FundNAVHistory.nav_date.desc())
            .first()
        )
        if nav_row:
            latest_nav_by_isin[f.isin] = float(nav_row[0])


    # Build fund_meta with robust NAV fallback
    for f in fund_rows:
        name = getattr(f, "name", str(f.id))
        isin = getattr(f, "isin", None)
        nav_row = (
            db.session.query(FundNAVHistory.nav_value)
            .filter(FundNAVHistory.fund_id == f.id)
            .order_by(FundNAVHistory.nav_date.desc())
            .first()
        )
        latest_nav = float(nav_row[0]) if nav_row else 0.0

        if (latest_nav == 0.0) and isin and (isin in latest_nav_by_isin):
            latest_nav = latest_nav_by_isin[isin]
        fund_meta[f.id] = {
            "name": name,
            "isin": isin,
            "latest_nav": latest_nav,
        }


    # ===== Summary Card Calculations (transaction-driven, FIFO-only) =====

    summary_portfolio_value = 0.0
    summary_cost_value = 0.0
    summary_weighted_days_sum = 0.0
    summary_cash_flows = []
    today = datetime.date.today()
    summary_debug_rows = []

    txns_by_fund = {}
    for t in transactions:
        txns_by_fund.setdefault(t.fund_id, []).append(t)

    for fund_id, fund_txns in txns_by_fund.items():
        fm = fund_meta.get(fund_id)
        if fm:
            fund_name = fm["name"]
            latest_nav = fm["latest_nav"]
        else:
            fund = Fund.query.get(fund_id)
            fund_name = getattr(fund, "name", str(fund_id)) if fund else str(fund_id)
            isin = getattr(fund, "isin", None) if fund else None
            latest_nav = float(getattr(fund, "latest_nav", 0.0) or 0.0) if fund else 0.0
            if latest_nav == 0.0 and isin:
                nav_row = (
                    db.session.query(FundNAVHistory.nav_value)
                    .filter(FundNAVHistory.isin == isin)
                    .order_by(FundNAVHistory.nav_date.desc())
                    .first()
                )
                latest_nav = float(nav_row[0]) if nav_row else 0.0

        result = calculate_fifo_returns(fund_txns, latest_nav, today=today)

        # Collect cash flows for XIRR
        summary_cash_flows.extend(result.get("cash_flows", []))

        # Add synthetic inflow for current value of remaining units
        if result["remaining_units"] > 0:
            summary_cash_flows.append({
                "date": today,
                "amount": result["current_value"]
            })

        is_active = result["remaining_units"] > 0

        if is_active:
            summary_cost_value += float(result["cost_value"])
            summary_portfolio_value += float(result["current_value"])

        for lot in result["remaining_lots"]:
            if lot["cost"] > 0:
                days_held = (today - lot["date"]).days
                summary_weighted_days_sum += days_held * float(lot["cost"])

        info_units = sum(float(t.units or 0) for t in fund_txns)
        summary_debug_rows.append({
            "fund_id": fund_id,
            "fund_name": fund_name,
            "units": info_units,
            "nav": latest_nav,
            "market_value": float(result["current_value"]),
            "cost_value": float(result["cost_value"]) if is_active else 0.0,
            "remaining_units": float(result["remaining_units"]),
            "isin": fm["isin"] if fm else None,
        })

    summary_wt_avg_days = round(summary_weighted_days_sum / summary_cost_value, 0) if summary_cost_value else 0
    summary_xirr = calculate_xirr(summary_cash_flows) if summary_cash_flows else 0.0
    summary_appreciation = summary_portfolio_value - summary_cost_value

    # Percent holding for summary lists used by the investment table
    for inv in equity_investments + debt_investments + hybrid_investments + commodity_investments:
        cv = inv.get('current_value', 0.0)
        inv['percent_holding'] = (cv / summary_portfolio_value) * 100.0 if summary_portfolio_value else 0.0


    for row in summary_debug_rows:
        if summary_portfolio_value > 0 and row["market_value"] is not None:
            row["percent_holding"] = (row["market_value"] / summary_portfolio_value) * 100.0
        else:
            row["percent_holding"] = 0.0


    # ===== Bar Chart Calculations (transaction-driven, consistent with summary card) =====

    subcategory_totals = {}

    # Use the same investment summaries that already contain current_value
    for inv in equity_investments + debt_investments + hybrid_investments + commodity_investments:
        fund = inv['fund']
        if not fund or not fund.sub_category or not fund.sub_category.category:
            continue

        subcategory_name = fund.sub_category.name
        category_name = fund.sub_category.category.name
        current_value = inv['current_value']

        if category_name in ["Equity", "Debt", "Hybrid", "Commodity"]:
            subcategory_totals.setdefault(subcategory_name, {"amount": 0, "category": category_name})
            subcategory_totals[subcategory_name]["amount"] += current_value

    # Use the transaction-driven portfolio total as denominator
    grouped_subcategories = []
    for category in ["Equity", "Hybrid", "Debt", "Commodity"]:
        subcats = [
            {
                "subcategory": sub,
                "category": category,
                "amount": round(data["amount"], 2),
                "percent": round((data["amount"] / summary_portfolio_value) * 100, 1) if summary_portfolio_value else 0
            }
            for sub, data in subcategory_totals.items()
            if data["category"] == category
        ]
        subcats.sort(key=lambda x: x["amount"], reverse=True)
        grouped_subcategories.extend(subcats)


    # ===== Pie Chart Calculations (transaction-driven, consistent with summary card) =====

    category_totals = {'Equity': 0, 'Debt': 0, 'Hybrid': 0, 'Commodity': 0}

    # Build category totals from the same investment summaries
    for inv in equity_investments + debt_investments + hybrid_investments + commodity_investments:
        fund = inv['fund']
        if not fund or not fund.sub_category or not fund.sub_category.category:
            continue

        category_name = fund.sub_category.category.name
        current_value = inv['current_value']

        if category_name in category_totals:
            category_totals[category_name] += current_value

    # Use summary_portfolio_value as denominator
    category_labels, category_values, category_values_in_millions = [], [], []
    for cat, val in category_totals.items():
        if val > 0:
            category_labels.append(cat)
            category_values.append(round(val, 2))
            category_values_in_millions.append(round(val / 1_000_000, 2))

    debt_total = category_totals['Debt']
    equity_total = category_totals['Equity']
    hybrid_total = category_totals['Hybrid']
    commodity_total = category_totals['Commodity']

    debt_percent = (debt_total / summary_portfolio_value) * 100 if summary_portfolio_value else 0
    equity_percent = (equity_total / summary_portfolio_value) * 100 if summary_portfolio_value else 0
    hybrid_percent = (hybrid_total / summary_portfolio_value) * 100 if summary_portfolio_value else 0
    commodity_percent = (commodity_total / summary_portfolio_value) * 100 if summary_portfolio_value else 0

    fund_house_labels = list(fund_house_totals.keys())
    fund_house_values = [fund_house_totals[fh] for fh in fund_house_labels]
    fund_house_values_in_millions = [val / 1e6 for val in fund_house_values]

    investments = equity_investments + debt_investments + hybrid_investments + commodity_investments

    return render_template(
        'dashboard.html',
        user=user,
        family_name=family_name,
        equity_investments=equity_investments,
        debt_investments=debt_investments,
        hybrid_investments=hybrid_investments,
        commodity_investments=commodity_investments,
        category_labels=category_labels,
        category_values_in_millions=category_values_in_millions,
        category_full_values=category_values,
        grouped_subcategories=grouped_subcategories,
        debt_total=debt_total,
        equity_total=equity_total,
        hybrid_total=hybrid_total,
        commodity_total=commodity_total,
        investments=investments,
        debt_percent=debt_percent,
        equity_percent=equity_percent,
        hybrid_percent=hybrid_percent,
        commodity_percent=commodity_percent,
        # Summary card values (transaction-driven)
        summary_portfolio_value=summary_portfolio_value,
        summary_appreciation=summary_appreciation,
        summary_cost_value=summary_cost_value,
        summary_wt_avg_days=summary_wt_avg_days,
        summary_xirr=summary_xirr,
        # Pie chart values
        fund_house_labels=fund_house_labels,
        fund_house_values_in_millions=fund_house_values_in_millions,
        fund_house_full_values=fund_house_values,
    )



# ===== Portfolio Evolution =====

@dashboard_bp.route("/portfolio-history-data")
def portfolio_history_data():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify([])

    period_years = int(request.args.get("years", 3))
    today = datetime.date.today()
    start_date = today.replace(year=today.year - period_years)

    # Build cutoff dates (1st and 15th of each month)
    import calendar
    cutoffs = []
    curr = datetime.date(start_date.year, start_date.month, 1)
    end_month = datetime.date(today.year, today.month, 1)
    while curr <= end_month:
        y, m = curr.year, curr.month
        mid = datetime.date(y, m, 15)
        last = datetime.date(y, m, calendar.monthrange(y, m)[1])
        cutoffs.extend([mid, last])
        curr = datetime.date(y + 1, 1, 1) if m == 12 else datetime.date(y, m + 1, 1)

    points = []

    for cutoff in cutoffs:
        total_value = 0.0
        funds = Fund.query.join(Investment).filter(Investment.user_id == user_id).distinct().all()
        for fund in funds:
            txns = Investment.query.filter(
                Investment.user_id == user_id,
                Investment.fund_id == fund.id,
                Investment.date <= cutoff
            ).order_by(Investment.date).all()

            if not txns:
                continue

            nav_record = (FundNAVHistory.query
                .filter(FundNAVHistory.fund_id == fund.id,
                        FundNAVHistory.nav_date <= cutoff)
                .order_by(FundNAVHistory.nav_date.desc())
                .first())

            if not nav_record:
                nav_record = (FundNAVHistory.query
                    .filter(FundNAVHistory.fund_id == fund.id,
                            FundNAVHistory.nav_date > cutoff,
                            FundNAVHistory.nav_date <= cutoff + datetime.timedelta(days=15))
                    .order_by(FundNAVHistory.nav_date.asc())
                    .first())

            if not nav_record:
                continue

            result = calculate_fifo_returns(txns, nav_record.nav_value, today=cutoff)
            total_value += result["current_value"]

        points.append({
            "date": cutoff.strftime("%Y-%m-%d"),
            "value": round(total_value, 2)
        })

    points.sort(key=lambda x: x["date"])
    return jsonify(points)


# ===== Manual NAV load at preview =====

@dashboard_bp.route("/preview-sync-nav", methods=["POST"])
def preview_sync_nav():
    from nav_loader import load_navs_for_fund_preview
    from models import Fund, FundNAVHistory
    from flask import session, jsonify

    print(">>> ENTERED preview-sync-nav")

    registrar = session.get("registrar")

    # For CAMS/Karvy: get ISINs from staging table
    if registrar in ("Karvy", "CAMS"):
        isins = {
            r.isin for r in StagingInvestment.query
            .filter_by(user_id=current_user.id)
            .distinct(StagingInvestment.isin)
            .all()
            if r.isin
        }
    else:
        # For commodity: fallback to session
        preview_data = session.get("preview_data")
        if not preview_data:
            print(">>> ERROR: No preview data in session")
            return jsonify({
                "status": "error",
                "message": "No preview data found in session.",
                "synced": [],
                "errors": [],
                "nav_counts": {}
            })
        isins = {row.get("isin") for row in preview_data if row.get("isin")}

    print(">>> ISINs extracted:", isins)

    if not isins:
        return jsonify({
            "status": "error",
            "message": "No ISINs found to sync.",
            "synced": [],
            "errors": [],
            "nav_counts": {}
        })

    synced = []
    errors = []

    for isin in isins:
        print(">>> PROCESSING ISIN:", isin)

        fund = Fund.query.filter_by(isin=isin).first()
        print(">>> FUND LOOKUP RESULT:", fund)

        if not fund:
            msg = f"{isin}: Fund not found"
            errors.append(msg)
            print(">>> ERROR:", msg)
            continue

        try:
            print(">>> CALLING PREVIEW LOADER FOR:", isin)
            result = load_navs_for_fund_preview(fund)
            print(">>> PREVIEW LOADER RESULT:", isin, result)
            synced.append(isin)
        except Exception as e:
            msg = f"{isin}: {str(e)}"
            errors.append(msg)
            print(">>> EXCEPTION DURING NAV LOAD:", msg)

    nav_counts = {}
    for isin in isins:
        fund = Fund.query.filter_by(isin=isin).first()
        if fund:
            count = (
                db.session.query(FundNAVHistory)
                .filter(FundNAVHistory.fund_id == fund.id)
                .count()
            )
            nav_counts[isin] = count

    print(">>> NAV COUNTS:", nav_counts)

    status = "success" if not errors else "partial"

    print(">>> FINAL STATUS:", status)
    print(">>> SYNCED:", synced)
    print(">>> ERRORS:", errors)

    return jsonify({
        "status": status,
        "message": (
            f"NAV sync completed. "
            f"Updated: {len(synced)}, "
            f"Errors: {len(errors)}"
        ),
        "synced": synced,
        "errors": errors,
        "nav_counts": nav_counts
    })