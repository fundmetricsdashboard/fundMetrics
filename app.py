from flask import Flask, request, render_template, redirect, url_for, jsonify, flash, session
from werkzeug.utils import secure_filename
import pandas as pd
import os
from sqlalchemy import func
from db_config import db
from models import User, Investment, Family, Fund, Category, SubCategory, PortfolioSnapshot, StagingInvestment, DeletionLog
from utils import calculate_xirr
from flask_migrate import Migrate
from datetime import datetime, date
from process_karvy_statement import process_karvy_statement
import requests, re
from bs4 import BeautifulSoup
from replay_sells import replay_sells
from flask_login import login_required, login_user, logout_user, current_user
from flask_mail import Message, Mail
from itsdangerous import URLSafeTimedSerializer
from dotenv import load_dotenv
load_dotenv()



# ===========================
# App Setup
# ===========================
app = Flask("fundMetrics")
app.secret_key = os.getenv('SECRET_KEY', 'your_secret_key')
serializer = URLSafeTimedSerializer(app.secret_key)
# ===========================
# Email (Outlook SMTP)
# ===========================
app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER')
app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT'))
app.config['MAIL_USE_TLS'] = os.getenv('MAIL_USE_TLS') == 'True'
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_DEFAULT_SENDER')

mail = Mail(app)

@app.route('/')
def index():
    return redirect(url_for('login'))

# ===========================
# Generate Reset token
# ===========================
def send_email(subject, recipients, body):
    msg = Message(subject, recipients=recipients)
    msg.body = body
    mail.send(msg)

def generate_reset_token(user_id):
    return serializer.dumps(user_id, salt='password-reset-salt')

def verify_reset_token(token, expiration=3600):
    try:
        user_id = serializer.loads(token, salt='password-reset-salt', max_age=expiration)
        return user_id
    except Exception:
        return None


# ===========================
# Flask‑Login Setup
# ===========================
from flask_login import LoginManager

login_manager = LoginManager()
login_manager.login_view = "login"   # redirect here if not logged in
login_manager.init_app(app)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

default_sqlite_path = "sqlite:///fundMetrics.db"

app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv(
    'DATABASE_URL',
    default_sqlite_path
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'fundMetrics_uploads'

migrate = Migrate(app, db)
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
from db_config import configure_database
configure_database(app)



# ===========================
# Blueprint Registration (final & safe)
# ===========================
try:
    from routes_dashboard import dashboard_bp
    from routes_dashboard_tables import dashboard_tables_bp
    from routes_family_dashboard import family_dashboard_bp

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(dashboard_tables_bp)
    app.register_blueprint(family_dashboard_bp)

except Exception as e:
    print(f"Blueprint warning: {e}")


# ===========================
# Upload Route
# ===========================
@app.route('/upload', methods=['GET', 'POST'])
@login_required 
def upload(): 
    # ❌ remove the 'user_id' not in session check entirely

    if request.method == 'POST':
        file = request.files.get('excel_file')
        if not file or file.filename == '':
            flash("No file selected.")
            return redirect(url_for('upload_center'))

        if file.filename.endswith('.xlsx'):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)

            # ✅ Detect registrar from filename
            registrar = None
            if "cams" in filename.lower():
                registrar = "CAMS"
            elif "karvy" in filename.lower():
                registrar = "Karvy"

            try:
                # Try Sheet1, fallback to first sheet
                try:
                    df = pd.read_excel(filepath, sheet_name="Sheet1")
                except ValueError:
                    df = pd.read_excel(filepath, sheet_name=0)

                df.columns = [col.strip() for col in df.columns]
                df = df.applymap(lambda x: str(x).strip() if pd.notnull(x) else x)

                session['preview_data'] = df.to_dict(orient='records')
                session['registrar'] = registrar

                return redirect(url_for('preview_upload'))

            except Exception as e:
                flash(f"❌ Error reading Excel file: {e}")
                return redirect(url_for('upload_center'))
        else:
            flash("Invalid file format. Please upload an .xlsx file.")
            return redirect(url_for('upload_center'))

    return render_template('upload_center.html')



# ===========================
# Upload Center
# ===========================
@app.route('/upload-center')
@login_required 
def upload_center(): 
    # Check if user has any investment data
    has_data = Investment.query.filter_by(user_id=current_user.id).count() > 0

    return render_template(
        'upload_center.html',
        user=current_user,
        has_data=has_data
    )


# ===========================
# Preview Route
# ===========================

@app.route('/preview-upload')
@login_required
def preview_upload():
    from models import StagingInvestment

    registrar = session.get('registrar')

    if not registrar:
        flash("❌ No registrar found. Please upload again.")
        return redirect(url_for('upload'))

    # If this is Karvy or CAMS, preview should come from STAGING
    if registrar in ("Karvy", "CAMS"):
        # ONLY check duplicates if clarification hasn't been done yet
        if not session.get("clarification_done"):
            # Check duplicates in staging
            dupes = (
                db.session.query(StagingInvestment.row_hash, func.count())
                .filter_by(user_id=current_user.id)
                .group_by(StagingInvestment.row_hash)
                .having(func.count() > 1)
                .all()
            )

            if dupes:
                session["duplicate_groups"] = [h for h, c in dupes]
                return redirect(url_for('clarify_duplicates'))

        # No duplicates OR clarification already done → load all staging rows for preview
        # No duplicates OR clarification already done → load all staging rows for preview
        print(f"[DEBUG preview-upload] clarification_done: {session.get('clarification_done')}")
        print(f"[DEBUG preview-upload] user_id: {current_user.id}")
        
        staging_rows = StagingInvestment.query.filter_by(
            user_id=current_user.id
        ).all()
        
        print(f"[DEBUG preview-upload] staging_rows found: {len(staging_rows)}")

        preview_data = []
        for r in staging_rows:
            preview_data.append({
                "date": r.date,
                "amount": r.amount,
                "units": r.units,
                "nav": r.nav,
                "isin": r.isin,
                "transaction_type": r.transaction_type,
                "source_file": r.source_file,
            })

        return render_template(
            'preview.html',
            preview_data=preview_data,
            registrar=registrar
        )

    # Non-Karvy (e.g. commodity) still uses session preview_data
    preview_data = session.get('preview_data')

    if not preview_data:
        flash("❌ No preview data found. Please upload again.")
        return redirect(url_for('upload'))

    return render_template(
        'preview.html',
        preview_data=preview_data,
        registrar=registrar
    )



@app.route('/clarify-duplicates')
@login_required
def clarify_duplicates():
    from models import StagingInvestment

    duplicate_groups = session.get("duplicate_groups", [])

    if not duplicate_groups:
        return redirect(url_for('preview_upload'))

    # Load all staging rows for this user
    staging_rows = StagingInvestment.query.filter_by(
        user_id=current_user.id
    ).all()

    # Group by row_hash
    grouped = {}
    for r in staging_rows:
        if r.row_hash in duplicate_groups:
            grouped.setdefault(r.row_hash, []).append(r)

    return render_template(
        'clarify_duplicates.html',
        duplicate_groups=duplicate_groups,
        grouped_staging=grouped
    )


# ===========================
# Preview Commodity Route
# ===========================
@app.route('/preview-upload-commodity')
@login_required 
def preview_upload_commodity():

    parsed_rows = session.get('preview_data')
    if not parsed_rows:
        flash("❌ No preview data found. Please upload again.")
        return redirect(url_for('upload'))

    preview_data_valid = []
    preview_data_missing_isin = []
    preview_data_unmapped = []

    for row in parsed_rows:
        isin = row.get('isin')
        if not isin or str(isin).strip() == "":
            preview_data_missing_isin.append(row)
            continue

        fund = Fund.query.filter_by(isin=isin).first()
        if not fund:
            preview_data_unmapped.append(row)
            continue

        preview_data_valid.append(row)

    return render_template(
        'preview.html',
        preview_data_valid=preview_data_valid,
        preview_data_missing_isin=preview_data_missing_isin,
        preview_data_unmapped=preview_data_unmapped,
        registrar=None  # commodity flow doesn’t need this
    )

# ===========================
# Upload Commodity Statement
# ===========================

@app.route('/upload-commodity-statement', methods=['POST'])
@login_required
def upload_commodity_statement():
    file = request.files.get('statement_file')
    if not file or file.filename == '':
        flash("No file selected.")
        return redirect(url_for('upload_center'))

    filepath = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(file.filename))
    file.save(filepath)

    from process_commodity_statement import process_commodity_statement

    session.pop("clarification_done", None)
    session.pop("duplicate_groups", None)

    preview_rows = process_commodity_statement(
        filepath=filepath,
        user_id=current_user.id,
        preview=True
    )

    session['registrar'] = "Commodity"

    return redirect(url_for('preview_upload'))


# ===========================
# Upload CAMS Statement
# ===========================

@app.route('/upload-cams-statement', methods=['POST'])
@login_required
def upload_cams_statement():
    # Always start with a clean staging table
    StagingInvestment.query.filter_by(user_id=current_user.id).delete()

    file = request.files.get('statement_file')
    if not file or file.filename == '':
        flash("No file selected.")
        return redirect(url_for('upload_center'))

    filepath = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(file.filename))
    file.save(filepath)

    try:
        from process_cams_statement import process_cams_statement

        # Clear old session flags
        session.pop("clarification_done", None)
        session.pop("duplicate_groups", None)

        preview_rows = process_cams_statement(
            filepath=filepath,
            user_id=current_user.id,
            preview=True
        )
        print(f"[DEBUG] Preview rows returned: {len(preview_rows)}")
        print(f"[DEBUG] Sample row: {preview_rows[0] if preview_rows else 'NONE'}")

        session['registrar'] = "CAMS"

        return redirect(url_for('preview_upload'))

    except Exception as e:
        flash(f"❌ Error reading CAMS statement: {e}")
        return redirect(url_for('upload_center'))



# ===========================
# Upload Karvy Statement
# ===========================

@app.route('/upload-karvy-statement', methods=['POST'])
@login_required
def upload_karvy_statement():
    file = request.files.get('statement_file')
    if not file or file.filename == '':
        flash("No file selected.")
        return redirect(url_for('upload_center'))

    filepath = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(file.filename))
    file.save(filepath)

    try:
        from process_karvy_statement import process_karvy_statement

        # Clear any old session flags from previous uploads
        session.pop("clarification_done", None)
        session.pop("duplicate_groups", None)

        # --- PREVIEW MODE: parse but do NOT insert ---
        preview_rows = process_karvy_statement(
            filepath=filepath,
            user_id=current_user.id,
            preview=True
        )

        # Store preview data in session
        session['registrar'] = "Karvy"

        return redirect(url_for('preview_upload'))

    except Exception as e:
        flash(f"❌ Error reading Karvy statement: {e}")
        return redirect(url_for('upload_center'))


# ===========================
# Confirm Staging (resolve duplicates ONLY)
# ===========================
@app.route('/confirm-staging', methods=['POST'])
@login_required
def confirm_staging():
    from models import StagingInvestment

    selected_ids = request.form.getlist("keep_raw_id")
    
    if not selected_ids:
        flash("Please select at least one row to keep.")
        return redirect(url_for('clarify_duplicates'))
    
    selected_ids = [int(x) for x in selected_ids]

    # Get the duplicate row_hashes from session
    duplicate_groups = session.get("duplicate_groups", [])

    # Delete ONLY the unselected rows from duplicate groups
    # Keep ALL non-duplicate rows + selected duplicate rows
    (
        StagingInvestment.query
        .filter(
            StagingInvestment.user_id == current_user.id,
            StagingInvestment.row_hash.in_(duplicate_groups),  # Only touch duplicate groups
            ~StagingInvestment.id.in_(selected_ids)  # Delete unselected ones
        )
        .delete(synchronize_session=False)
    )

    db.session.commit()

    # Mark clarification as complete to prevent loop
    session["clarification_done"] = True

    flash(f"✅ Kept {len(selected_ids)} selected transactions from duplicates. All unique transactions retained.")
    return redirect(url_for('preview_upload'))


# ===========================
# Confirm Upload (commit staging → Investment)
# ===========================
@app.route('/confirm-upload', methods=['POST'])
@login_required
def confirm_upload():
    from models import StagingInvestment, Fund, Investment

    staging_rows = StagingInvestment.query.filter_by(
        user_id=current_user.id
    ).all()

    if not staging_rows:
        flash("No pending rows to commit.")
        return redirect(url_for('upload_center'))

    inserted = 0

    for raw in staging_rows:
        fund = Fund.query.filter_by(isin=raw.isin).first()
        if not fund:
            continue  # or collect as skipped

        inv = Investment(
            user_id=raw.user_id,
            fund_id=fund.id,
            isin=raw.isin,
            transaction_type=raw.transaction_type,
            amount=raw.amount,
            nav=raw.nav,
            units=raw.units,
            date=raw.date, 
            source_file=raw.source_file,
            registrar=fund.registrar
        )
        db.session.add(inv)
        inserted += 1

    # Clear staging for this user
    StagingInvestment.query.filter_by(
        user_id=current_user.id
    ).delete()

    db.session.commit()

    # Clear session flags
    session.pop("clarification_done", None)
    session.pop("duplicate_groups", None)
    session.pop("registrar", None)

    try:
        from snapshot_generator import generate_personal_snapshots, generate_family_snapshots

        print(f"[UPLOAD] Generating snapshots for user {current_user.id}")
        generate_personal_snapshots(current_user.id)

        if current_user.family_id:
            print(f"[UPLOAD] Generating family snapshots for family {current_user.family_id}")
            generate_family_snapshots(current_user.family_id)

    except Exception as e:
        print(f"[ERROR] Snapshot generation failed: {e}")

    flash(f"✅ Upload confirmed. Inserted {inserted} transactions.")
    return redirect(url_for('dashboard_bp.dashboard', user_id=current_user.id))


# ===========================
# NAV Fetcher
# ===========================

def get_nav(url):
    try:
        response = requests.get(url, timeout=5)
        if response.status_code != 200:
            print(f"Error fetching NAV: Status code {response.status_code}")
            return None

        soup = BeautifulSoup(response.text, 'html.parser')
        nav_element = soup.find('span', {'id': 'nav-value'})  # Update selector if needed

        if nav_element:
            nav_text = nav_element.text.strip()
            match = re.search(r'[\d,.]+', nav_text)
            if match:
                return float(match.group().replace(',', ''))
            else:
                print("NAV value not found in text")
                return None
        else:
            print("NAV element not found")
            return None
    except Exception as e:
        print(f"Error fetching NAV: {e}")
        return None

# ===========================
# Date Normalization
# ===========================

def normalize_date(d):
    if isinstance(d, date):
        return datetime.combine(d, datetime.min.time())
    elif isinstance(d, datetime):
        return d
    elif isinstance(d, str):
        try:
            return datetime.strptime(d, "%Y-%m-%d")
        except ValueError:
            print(f"Invalid date string: {d}")
            return None
    else:
        print(f"Unrecognized date format: {d}")
        return None




# ===========================
# NAV Summary API
# ===========================
@app.route('/api/mutual-funds/nav-summary')
def nav_summary():
    try:
        investments = Investment.query.all()
        summary = []
        for inv in investments:
            fund = Fund.query.get(inv.fund_id)
            if fund and fund.sub_category and fund.sub_category.category:
                summary.append({
                    "fund_name": fund.name,
                    "nav": fund.latest_nav if fund else None,
                    "category": fund.sub_category.category.name,
                    "subcategory": fund.sub_category.name,
                    "plan_type": fund.plan_type,
                    "growth_type": fund.growth_type,
                    "amount": inv.amount,
                    "buy_date": inv.buy_date.strftime('%Y-%m-%d') if inv.buy_date else None,
                    "sell_date": inv.sell_date.strftime('%Y-%m-%d') if inv.sell_date else None,
                    "source_file": inv.source_file
                })
        return jsonify(summary)
    except Exception as e:
        return jsonify({'error': str(e)})

# ===========================
# Returns Calculation
# ===========================
@app.route('/user/<int:user_id>/fund/<int:fund_id>/returns')
def get_returns(user_id, fund_id):
    investments = Investment.query.filter_by(user_id=user_id, fund_id=fund_id).order_by(Investment.buy_date).all()
    if not investments:
        return jsonify({'error': 'No investments found'}), 404

    nav = get_nav(investments[0].fund.fund_url)
    if nav is None:
        return jsonify({'error': 'NAV fetch failed'}), 500

    buy_stack = []
    transactions = []

    for inv in investments:
        if not inv.sell_date:
            buy_stack.append({'units': inv.units, 'amount': inv.amount, 'date': inv.buy_date})
            continue

        remaining_units = inv.units
        while remaining_units > 0 and buy_stack:
            buy = buy_stack.pop(0)
            matched_units = min(buy['units'], remaining_units)
            buy_amount = -(buy['amount'] * matched_units / buy['units'])
            sell_amount = matched_units * nav

            transactions.append({'amount': buy_amount, 'date': buy['date']})
            transactions.append({'amount': sell_amount, 'date': inv.sell_date})

            remaining_units -= matched_units

            if buy['units'] > matched_units:
                buy_stack.insert(0, {
                    'units': buy['units'] - matched_units,
                    'amount': buy['amount'] * (buy['units'] - matched_units) / buy['units'],
                    'date': buy['date']
                })

    xirr_value = calculate_xirr(transactions)
    return jsonify({'Fund': fund_id, 'User': user_id, 'XIRR (%)': xirr_value})

# ===========================
# Portfolio History for Portfolio Evoluion
# ===========================

@app.route('/api/portfolio-history')
def portfolio_history_data():
    user_id = request.args.get('user_id', type=int)
    dashboard_type = request.args.get('dashboard_type', type=str)

    if not user_id:
        return jsonify({"error": "user_id is required"}), 400

    if not dashboard_type:
        return jsonify({"error": "dashboard_type is required"}), 400

    snapshots = (
        PortfolioSnapshot.query
        .filter_by(user_id=user_id, dashboard_type=dashboard_type)
        .order_by(PortfolioSnapshot.snapshot_date)
        .all()
    )

    data = [
        {
            "date": s.snapshot_date.strftime("%Y-%m-%d"),
            "value": float(s.portfolio_value)
        }
        for s in snapshots
    ]

    return jsonify(data)

# ===========================
# User Registration Route (Self Sign-Up)
# ===========================
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name'].strip()  # Username
        email = request.form['email']
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        is_family_member = bool(request.form.get('is_family_member'))
        family_name = request.form.get('family_name', '').strip()

        # Validation
        if not name or not email or not password:
            flash("❌ All fields are required.")
            return redirect(url_for('register'))

        if len(name) < 3 or len(name) > 20:
            flash("❌ Username must be between 3 and 20 characters.")
            return redirect(url_for('register'))

        if password != confirm_password:
            flash("❌ Passwords do not match.")
            return redirect(url_for('register'))

        if len(password) < 6:
            flash("❌ Password must be at least 6 characters long.")
            return redirect(url_for('register'))

        # If family member checkbox is checked, family name is required
        if is_family_member and not family_name:
            flash("❌ Please enter a family name or uncheck the family dashboard option.")
            return redirect(url_for('register'))

        # Check if user already exists
        existing_user = User.query.filter(
            (func.lower(User.name) == name.lower()) | (User.email == email)
        ).first()

        if existing_user:
            flash("❌ This username or email is already taken.")
            return redirect(url_for('register'))

        # Handle family
        family = None
        if is_family_member and family_name:
            # Check if family exists, otherwise create it
            family = Family.query.filter_by(name=family_name).first()
            if not family:
                family = Family(name=family_name)
                db.session.add(family)
                db.session.flush()  # Get the family ID

        # Create new user
        new_user = User(
            name=name,
            email=email,
            family_id=family.id if family else None,
            is_family_member=is_family_member
        )
        new_user.set_password(password)

        db.session.add(new_user)
        db.session.commit()

        if is_family_member and family_name:
            flash(f"✅ Account created successfully! You're now part of {family_name}. You can log in with username: {name}")
        else:
            flash(f"✅ Account created successfully! You can now log in with username: {name}")
        
        return redirect(url_for('login'))

    return render_template('register.html')

# ===========================
# Add User Route
# ===========================
@app.route('/add-user', methods=['GET', 'POST'])
@login_required  
def add_user():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        family_name = request.form.get('family_name')
        is_family_member = bool(request.form.get('is_family_member'))

        # Check if user already exists
        existing_user = User.query.filter(
            (User.name == name) | (User.email == email)
        ).first()

        if existing_user:
            flash(f"❌ User with this name or email already exists.")
            return redirect(url_for('add_user'))

        # Handle family
        family = None
        if family_name:
            family = Family.query.filter_by(name=family_name).first()
            if not family:
                family = Family(name=family_name)
                db.session.add(family)
                db.session.commit()

        # Create user
        user = User(
            name=name,
            email=email,
            family_id=family.id if family else None,
            is_family_member=is_family_member
        )
        user.set_password("changeme")  # or leave blank if you want them to set manually

        db.session.add(user)
        db.session.commit()

        flash(f"✅ User '{name}' added successfully.")
        return redirect(url_for('add_user'))

    return render_template('add_user.html')



# ===========================
# Login Route
# ===========================

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        name = request.form['name']
        password = request.form['password']
        dashboard_type = request.form.get('dashboard_type')

        user = User.query.filter(func.lower(User.name) == name.lower()).first()

        if user and user.check_password(password):
            # ✅ Use Flask-Login to log the user in
            login_user(user)

            # ✅ No more session['user_id'] for auth
            if dashboard_type == "family":
                return redirect(url_for('family_dashboard_bp.family_dashboard'))
            else:
                return redirect(url_for('dashboard_bp.dashboard', user_id=user.id))

        flash("❌ Invalid name or password.")
        return redirect(url_for('login'))

    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


# ===========================
# Change Password Route
# ===========================

@app.route('/change-password', methods=['GET', 'POST']) 
@login_required 
def change_password(): 
    if request.method == 'POST': 
        old_password = request.form['old_password'] 
        new_password = request.form['new_password'] 
        user = current_user

        if user and user.check_password(old_password):
            user.set_password(new_password)
            db.session.commit()
            flash("✅ Password updated successfully.")
        else:
            flash("❌ Incorrect current password.")

        return redirect(url_for('change_password'))

    return render_template('change_password.html')

# ===========================
# Reset Password Route
# ===========================

@app.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    if request.method == 'POST':
        name = request.form['name']
        user = User.query.filter(func.lower(User.name) == name.lower()).first()

        if not user:
            flash("❌ User not found.")
            return redirect(url_for('reset_password'))

        # Generate token
        token = generate_reset_token(user.id)

        # Build reset link
        reset_link = url_for('reset_with_token', token=token, _external=True)

        # Send email
        send_email(
            subject="fundMetrics Password Reset",
            recipients=[user.email],
            body=f"Hello {user.name},\n\nClick the link below to reset your password:\n{reset_link}\n\nThis link expires in 1 hour.\n\n– fundMetrics"
        )

        flash("📧 Password reset link sent to your email.")
        return redirect(url_for('login'))

    return render_template('reset_password.html')


@app.route('/reset/<token>', methods=['GET', 'POST'])
def reset_with_token(token):
    user_id = verify_reset_token(token)

    if not user_id:
        flash("❌ Invalid or expired reset link.")
        return redirect(url_for('reset_password'))

    user = User.query.get(user_id)

    if request.method == 'POST':
        new_password = request.form['new_password']
        user.set_password(new_password)
        db.session.commit()

        flash("✅ Password updated successfully.")
        return redirect(url_for('login'))

    return render_template('reset_with_token.html', user=user)


# ===========================
# Query list of Users
# ===========================
@app.route('/users')
def list_users():
    users = User.query.all()
    output = "<h2>Registered Users</h2><ul>"
    for user in users:
        output += f"<li>{user.name}</li>"
    output += "</ul>"
    return output


# ===========================
# Favicon for Browser Icon
# ===========================
from flask import send_from_directory

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(
        os.path.join(app.root_path, 'static', 'images'),
        'fundMetrics_favicon.ico',
        mimetype='image/vnd.microsoft.icon'
    )


# ===========================
# Run the App
# ===========================

if __name__ == '__main__':
    app.run(debug=True, use_reloader=False)



