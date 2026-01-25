from flask import Blueprint, request, redirect, url_for, flash, render_template, jsonify
from models import User, Investment, InvestmentHistory, Fund, FundNAVHistory, SubCategory, PortfolioSnapshot, DeletionLog
from datetime import datetime, date
from utils import calculate_xirr, format_fund_name, calculate_fifo_returns
from sqlalchemy import func
from sqlalchemy.orm import joinedload
from db_config import db

dashboard_tables_bp = Blueprint('dashboard_tables_bp', __name__)

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


# Add Transactions Route #
@dashboard_tables_bp.route("/add-transactions/<int:user_id>", methods=["GET", "POST"])
def add_transactions(user_id):
    user = User.query.get_or_404(user_id)

    if request.method == "POST":
        row_count = int(request.form.get("row_count", 0))

        for i in range(row_count):
            fund_id = request.form.get(f"fund_{i}")  # hidden field from autocomplete
            fund_name = request.form.get(f"fund_name_{i}")  # visible text (not stored)
            txn_type = request.form.get(f"txn_type_{i}")
            date_str = request.form.get(f"date_{i}")
            units = request.form.get(f"units_{i}")
            amount = request.form.get(f"amount_{i}")
            nav = request.form.get(f"nav_{i}")
            plan_type = request.form.get(f"plan_type_{i}")
            registrar = fund.registrar
            folio = request.form.get(f"folio_{i}")
            source_file = request.form.get(f"source_file_{i}")

            # Skip incomplete rows
            if not fund_id or not txn_type or not date_str:
                continue

            txn_date = datetime.strptime(date_str, "%Y-%m-%d").date()

            # Fetch fund to get ISIN
            fund = Fund.query.get(int(fund_id))
            isin_value = fund.isin if fund else None

            inv = Investment(
                user_id=user.id,
                fund_id=int(fund_id),
                isin=isin_value,
                transaction_type=txn_type,
                date=txn_date,
                units=float(units or 0),
                amount=float(amount or 0),
                nav=float(nav or 0),
                plan_type=plan_type,
                registrar=registrar,
                folio_number=folio,
                source_file=source_file,
            )

            db.session.add(inv)

        db.session.commit()

        # --- NEW: Generate snapshots ---
        from snapshot_generator import generate_personal_snapshots, generate_family_snapshots
        generate_personal_snapshots(user.id)
        generate_family_snapshots(user.id)

        flash("Transactions added successfully.")
        return redirect(url_for("dashboard_tables_bp.dashboard_tables", user_id=user.id))


    # GET request → render form
    return render_template("add_transactions.html", user=user, date=date)

@dashboard_tables_bp.route("/preview-transactions", methods=["POST"])
def preview_transactions():
    """
    Build a preview list from the posted add-transactions form.
    Nothing is saved to DB here.
    """
    row_count = int(request.form.get("row_count", 0))
    preview_data = []

    for i in range(row_count):
        fund_id = request.form.get(f"fund_{i}")
        fund_name = request.form.get(f"fund_name_{i}")
        txn_type = request.form.get(f"txn_type_{i}")
        date_str = request.form.get(f"date_{i}")
        amount = request.form.get(f"amount_{i}")
        nav = request.form.get(f"nav_{i}")
        folio = request.form.get(f"folio_{i}")

        # Skip empty rows
        if not fund_id or not txn_type or not date_str:
            continue

        # Compute units
        units = None
        try:
            if amount and nav:
                units = float(amount) / float(nav)
        except:
            units = None

        preview_data.append({
            "fund_id": int(fund_id),
            "fund_name": fund_name,
            "txn_type": txn_type,
            "date": date_str,
            "amount": float(amount or 0),
            "nav": float(nav or 0),
            "units": units,
            "folio": folio
        })

    # Store in session for commit step
    from flask import session
    session["preview_data"] = preview_data

    return render_template(
        "preview_transactions.html",
        preview_data=preview_data
    )


@dashboard_tables_bp.route("/commit-transactions", methods=["POST"])
def commit_transactions():
    """
    Commit the previewed transactions into the Investment table.
    """
    from flask import session
    preview_data = session.get("preview_data", [])

    if not preview_data:
        flash("No preview data found.")
        return redirect(url_for("dashboard_tables_bp.add_transactions", user_id=session.get("user_id")))

    inserted = 0

    for row in preview_data:
        try:
            fund = Fund.query.get(row["fund_id"])
            isin_value = fund.isin if fund else None

            txn_date = datetime.strptime(row["date"], "%Y-%m-%d").date()

            inv = Investment(
                user_id=session.get("user_id"),
                fund_id=row["fund_id"],
                isin=isin_value,
                transaction_type=row["txn_type"],
                date=txn_date,
                amount=row["amount"],
                nav=row["nav"],
                units=row["units"],
                folio_number=row["folio"],
                plan_type="Direct" if "direct" in (fund.name or "").lower() else "Regular",
                registrar=fund.registrar,
                source_file="manual_entry"
            )

            db.session.add(inv)
            inserted += 1

        except Exception as e:
            print("Commit error:", e)
            db.session.rollback()
            db.session.begin_nested()

    db.session.commit()
    session.pop("preview_data", None)

    # Rebuild FIFO + snapshots after manual transaction entry
    from snapshot_generator import generate_personal_snapshots, generate_family_snapshots
    generate_personal_snapshots(session.get("user_id"))
    generate_family_snapshots(session.get("user_id"))

    flash(f"Successfully inserted {inserted} transactions.")
    return redirect(url_for("dashboard_tables_bp.dashboard_tables", user_id=session.get("user_id")))



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

    if registrar not in {"CAMS", "Karvy"}:
        flash("❌ Invalid registrar.")
        return redirect(url_for("dashboard_tables_bp.dashboard_tables", user_id=user.id))

    if request.method == "POST":
        reason = request.form.get("reason", "").strip()
        if not reason:
            flash("❌ Please provide a reason for deletion.")
            return redirect(request.url)

        # Normalize registrar for filename matching
        registrar_lower = registrar.lower()

        # 1️⃣ Delete investments by registrar OR source_file
        investments_to_delete = Investment.query.filter(
            Investment.user_id == user.id,
            (
                (Investment.registrar == registrar) |
                (func.lower(Investment.source_file).like(f"%{registrar_lower}%"))
            )
        ).all()

        investment_ids = [inv.id for inv in investments_to_delete]

        for inv in investments_to_delete:
            db.session.delete(inv)

        # 2️⃣ Delete FIFO rows tied to these investments
        histories_to_delete = InvestmentHistory.query.filter(
            InvestmentHistory.user_id == user.id,
            InvestmentHistory.fund_id.isnot(None)  # only delete FIFO for matched funds
        ).all()

        # Also delete FIFO rows where fund_id is NULL (CAMS rows often have NULL fund_id)
        histories_null = InvestmentHistory.query.filter(
            InvestmentHistory.user_id == user.id,
            InvestmentHistory.fund_id.is_(None)
        ).all()

        for hist in histories_to_delete + histories_null:
            db.session.delete(hist)

        # 3️⃣ Delete snapshots for this user (personal dashboard only)
        snapshots_to_delete = PortfolioSnapshot.query.filter(
            PortfolioSnapshot.user_id == user.id,
            PortfolioSnapshot.dashboard_type == "personal"
        ).all()

        for snap in snapshots_to_delete:
            db.session.delete(snap)

        # 4️⃣ Log deletion
        log = DeletionLog(
            user_id=user.id,
            registrar=registrar,
            reason=reason
        )
        db.session.add(log)

        deleted_count = (
            len(investments_to_delete)
            + len(histories_to_delete)
            + len(histories_null)
            + len(snapshots_to_delete)
        )

        db.session.commit()

        flash(
            f"✅ Reset {deleted_count} {registrar} records for user {user.id}. "
            f"Reason: {reason}"
        )

        return redirect(url_for("upload_center"))

    return render_template("confirm_deletion.html", user=user, registrar=registrar)
