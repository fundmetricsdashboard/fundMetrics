import threading
import hashlib
from flask import Blueprint, request, redirect, url_for, flash, render_template, jsonify, current_app, session
from models import User, Investment, InvestmentHistory, Fund, FundNAVHistory, SubCategory, PortfolioSnapshot, DeletionLog, StagingInvestment
from datetime import datetime, date
from utils import calculate_xirr, format_fund_name, calculate_fifo_returns
from sqlalchemy import func
from sqlalchemy.orm import joinedload
from db_config import db

dashboard_tables_bp = Blueprint('dashboard_tables_bp', __name__)

# --- BACKGROUND WORKER HELPER ---
def trigger_background_snapshots(user_id, family_id):
    """
    Runs the heavy snapshot generation in a background thread
    so Cloudflare doesn't time out while waiting for a response.
    """
    app = current_app._get_current_object()
    
    def run_snapshots(app_instance, uid, fid):
        with app_instance.app_context():
            from snapshot_generator import generate_personal_snapshots, generate_family_snapshots
            generate_personal_snapshots(uid)
            if fid:
                generate_family_snapshots(fid)
                
    thread = threading.Thread(target=run_snapshots, args=(app, user_id, family_id))
    thread.start()
# ---------------------------------

@dashboard_tables_bp.route("/fund-search")
def fund_search():
    q = request.args.get("q", "").strip().lower()

    if not q:
        return jsonify({"results": []})

    results = (
        Fund.query
        .options(
            joinedload(Fund.sub_category).joinedload(SubCategory.category)
        )
        .filter(func.lower(Fund.name).like(f"%{q}%"))
        .order_by(Fund.name)
        .limit(20)
        .all()
    )

    payload = []
    for f in results:
        category_name = ""
        if f.sub_category and f.sub_category.category:
            category_name = f.sub_category.category.name

        payload.append({
            "id": f.id,
            "name": f.name,
            "category": category_name,
        })

    return jsonify({"results": payload})


# Add Transactions Route (Staging Pipeline) #
@dashboard_tables_bp.route("/add-transactions/<int:user_id>", methods=["GET", "POST"])
def add_transactions(user_id):
    user = User.query.get_or_404(user_id)

    if request.method == "POST":
        row_count = int(request.form.get("row_count", 0))
        
        # Clear any stale staging data for this user before starting
        StagingInvestment.query.filter_by(user_id=user.id).delete()

        for i in range(row_count):
            fund_id = request.form.get(f"fund_{i}")  
            fund_name = request.form.get(f"fund_name_{i}")  
            txn_type = request.form.get(f"txn_type_{i}")
            date_str = request.form.get(f"date_{i}")
            units = request.form.get(f"units_{i}")
            amount = request.form.get(f"amount_{i}")
            nav = request.form.get(f"nav_{i}")
            folio = request.form.get(f"folio_{i}")

            # Skip incomplete rows
            if not fund_id or not txn_type or not date_str:
                continue

            txn_date = datetime.strptime(date_str, "%Y-%m-%d").date()

            # Convert values to floats first
            amount = float(amount or 0)
            nav = float(nav or 0)
            units = float(units or 0)

            # Calculate units dynamically if they are missing
            if units == 0 and amount > 0 and nav > 0:
                units = amount / nav

            # Fetch fund FIRST, safely fallback if not found
            fund = Fund.query.get(int(fund_id))
            isin_value = fund.isin if fund else None
            
            # Generate a unique hash for deduplication logic on the preview screen
            raw_str = f"{fund_id}{txn_type}{date_str}{amount}{units}{nav}{folio}manual_entry"
            row_hash = hashlib.md5(raw_str.encode()).hexdigest()

            # ✅ Write to STAGING table, not the live Investment table
            stg = StagingInvestment(
                user_id=user.id,
                isin=isin_value,
                transaction_type=txn_type,
                date=txn_date,
                amount=amount,
                units=units,
                nav=nav,
                folio_number=folio,
                source_file="manual_entry",  # Matches confirm_deletion requirement
                row_hash=row_hash
            )
            db.session.add(stg)
            
        db.session.commit()

        # Clear old session flags, set registrar to Manual, and route to the universal preview
        session.pop("clarification_done", None)
        session.pop("duplicate_groups", None)
        session['registrar'] = "Manual"

        return redirect(url_for("preview_upload"))

    # GET request → render form
    return render_template("add_transactions.html", user=user, date=date)


@dashboard_tables_bp.route('/dashboard-tables/<int:user_id>', endpoint='dashboard_tables')
def dashboard_tables(user_id):
    user = User.query.get_or_404(user_id)
    investments = (
        Investment.query
        .filter_by(user_id=user.id)
        .order_by(Investment.date)
        .all()
    )

    # Group investments by fund
    fund_map = {}
    for inv in investments:
        fund_id = inv.fund_id
        if fund_id not in fund_map:
            fund_map[fund_id] = {
                'fund': inv.fund,
                'buys': [],
                'sells': [],
                'subcategory': inv.fund.sub_category,
                'category': inv.fund.sub_category.category if inv.fund.sub_category else None,
            }
        if inv.transaction_type.lower() == 'buy':
            fund_map[fund_id]['buys'].append(inv)
        elif inv.transaction_type.lower() == 'sell':
            fund_map[fund_id]['sells'].append(inv)

    fund_ids_in_txn = list(fund_map.keys())
    fund_rows = Fund.query.filter(Fund.id.in_(fund_ids_in_txn)).all()

    # Preload latest NAV by fund_id from FundNAVHistory
    latest_nav_by_fund = {}
    for f in fund_rows:
        nav_row = (
            db.session.query(FundNAVHistory.nav_value)
            .filter(FundNAVHistory.fund_id == f.id)
            .order_by(FundNAVHistory.nav_date.desc())
            .first()
        )
        if nav_row:
            latest_nav_by_fund[f.id] = float(nav_row[0])

    # Find the most recent NAV date across all funds in this user’s portfolio
    last_nav_date = (
        db.session.query(func.max(FundNAVHistory.nav_date))
        .filter(FundNAVHistory.fund_id.in_(fund_ids_in_txn))
        .scalar()
    )
    last_nav_str = last_nav_date.strftime("%d %b %Y") if last_nav_date else None

    # First pass: compute FIFO results per fund, filter out current_value <= 1000, accumulate total_current_value
    fund_results = []
    total_current_value = 0.0

    for data in fund_map.values():
        fund = data['fund']
        buys = data['buys']
        sells = data['sells']
        category = data['category']

        fund_txns = buys + sells
        if not fund_txns:
            continue

        latest_nav = latest_nav_by_fund.get(fund.id, 0.0)
        result = calculate_fifo_returns(fund_txns, latest_nav)

        current_value = result.get("current_value", 0.0) or 0.0

        # Skip very small holdings AND exclude from totals
        if current_value <= 1000:
            continue

        total_current_value += current_value

        fund_results.append({
            "fund": fund,
            "buys": buys,
            "sells": sells,
            "category": category,
            "result": result,
        })

    equity_investments, debt_investments, hybrid_investments, commodity_investments = [], [], [], []

    # Second pass: build summaries with holding_percent based on FIFO current_value and total_current_value
    for item in fund_results:
        fund = item["fund"]
        buys = item["buys"]
        sells = item["sells"]
        category = item["category"]
        result = item["result"]

        category_name = category.name if category else None
        current_value = result["current_value"]
        cost_value = result["cost_value"]

        holding_percent = (
            (current_value / total_current_value * 100.0)
            if total_current_value > 0
            else 0.0
        )

        summary = {
            'fund': fund,
            'net_amount': cost_value,
            'current_value': current_value,
            'holding_percent': holding_percent,
            'buy_date': min(b.date for b in buys) if buys else None,
            'sell_date': max(s.date for s in sells) if sells else None,
            'xirr': round(result["xirr"] * 100, 2) if result["xirr"] is not None else None,
            'holding_period': result["holding_period"],            
            'fund_display_name': format_fund_name(fund.name),
            'plan_type': (
                buys[0].plan_type
                if buys and buys[0].plan_type
                else ('Direct' if 'direct' in fund.name.lower() else 'Regular')
            ),
            'growth_type': (
                fund.growth_type
                or (
                    'Dividend'
                    if 'dividend' in fund.name.lower() or 'idcw' in fund.name.lower()
                    else 'Growth'
                )
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

    # Calculate totals for each category
    equity_total = sum(inv['current_value'] for inv in equity_investments)
    debt_total = sum(inv['current_value'] for inv in debt_investments)
    hybrid_total = sum(inv['current_value'] for inv in hybrid_investments)
    commodity_total = sum(inv['current_value'] for inv in commodity_investments)

    return render_template(
        'dashboard_tables.html',
        user=user,
        equity_investments=equity_investments,
        debt_investments=debt_investments,
        hybrid_investments=hybrid_investments,
        commodity_investments=commodity_investments,
        equity_total=equity_total,
        debt_total=debt_total,
        hybrid_total=hybrid_total,
        commodity_total=commodity_total,
        last_nav_update=last_nav_str,
    )


@dashboard_tables_bp.route(
    "/confirm-deletion/<int:user_id>/<string:registrar>",
    methods=["GET", "POST"],
    endpoint="confirm_deletion"
)
def confirm_deletion(user_id, registrar):
    user = User.query.get_or_404(user_id)

    if registrar not in {"CAMS", "Karvy", "Commodity", "Manual"}:
        flash("❌ Invalid deletion target.")
        return redirect(url_for("dashboard_tables_bp.dashboard_tables", user_id=user.id))

    if request.method == "POST":
        reason = request.form.get("reason", "").strip()
        if not reason:
            flash("❌ Please provide a reason for deletion.")
            return redirect(request.url)

        # 1. Identify which rows to delete based on source
        if registrar == "Manual":
            investments_to_delete = Investment.query.filter(
                Investment.user_id == user.id,
                Investment.source_file == "manual_entry"
            ).all()
        else:
            registrar_lower = registrar.lower()
            investments_to_delete = Investment.query.filter(
                Investment.user_id == user.id,
                (
                    (Investment.registrar == registrar) |
                    (func.lower(Investment.source_file).like(f"%{registrar_lower}%"))
                )
            ).all()

        if not investments_to_delete:
            flash(f"No {registrar} investments found to delete.")
            return redirect(url_for("upload_center"))

        # We must identify which specific funds are being affected
        affected_fund_ids = list(set([inv.fund_id for inv in investments_to_delete if inv.fund_id]))

        # Delete the raw investments
        for inv in investments_to_delete:
            db.session.delete(inv)

        # 2. Rebuild the InvestmentHistory (FIFO math) for affected funds
        # We must completely wipe and rebuild history ONLY for the funds whose buys/sells just changed
        histories_to_delete = InvestmentHistory.query.filter(
            InvestmentHistory.user_id == user.id,
            InvestmentHistory.fund_id.in_(affected_fund_ids)
        ).all()

        for hist in histories_to_delete:
            db.session.delete(hist)

        # Reconstruct the buy lots
        remaining_investments = Investment.query.filter(
            Investment.user_id == user.id,
            Investment.fund_id.in_(affected_fund_ids)
        ).order_by(Investment.date.asc()).all()

        for inv in remaining_investments:
            if inv.transaction_type.lower() == 'buy':
                buy_record = InvestmentHistory(
                    user_id=user.id,
                    fund_id=inv.fund_id,
                    tx_date=inv.date,
                    tx_type='BUY',
                    units=inv.units,
                    cost_per_unit=inv.nav if inv.nav else 0.0,
                    total_cost=float(inv.units) * float(inv.nav if inv.nav else 0.0),
                    units_remaining=inv.units
                )
                db.session.add(buy_record)

        # Process the remaining sells in chronological order
        db.session.commit() # Commit the buys so process_sell can find them
        
        from utils import process_sell
        for inv in remaining_investments:
            if inv.transaction_type.lower() == 'sell':
                try:
                    process_sell(
                        session=db.session,
                        user_id=user.id,
                        fund_id=inv.fund_id,
                        sell_date=inv.date,
                        sell_units=abs(float(inv.units)),
                        sell_price=float(inv.nav) if inv.nav else 0.0
                    )
                except ValueError as e:
                    # Log the error but don't crash if a sell now lacks sufficient buys
                    print(f"Error rebuilding history after deletion: {e}")

        # 4. Log deletion
        log = DeletionLog(
            user_id=user.id,
            registrar=registrar,
            reason=reason
        )
        db.session.add(log)
        db.session.commit()

        # 3. Force Snapshot Regeneration in background
        trigger_background_snapshots(user.id, user.family_id)

        flash(f"✅ Successfully deleted {len(investments_to_delete)} {registrar} records and rebuilt historical ledgers. Reason: {reason}. Snapshots updating in background.")
        return redirect(url_for("upload_center"))

    return render_template("confirm_deletion.html", user=user, registrar=registrar)