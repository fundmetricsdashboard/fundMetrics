from db_config import db
from datetime import datetime
from sqlalchemy import Numeric, CheckConstraint
from sqlalchemy import Enum
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin

REGISTRAR_TYPES = ('CAMS', 'Karvy')

class Family(db.Model):
    __tablename__ = 'family'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    users = db.relationship('User', back_populates='family')


class User(UserMixin, db.Model):
    __tablename__ = 'user'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    family_id = db.Column(db.Integer, db.ForeignKey('family.id'))
    is_family_member = db.Column(db.Boolean, default=False)
    email = db.Column(db.String(255), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    family = db.relationship('Family', back_populates='users')
    investments = db.relationship('Investment', back_populates='user')
    password_hash = db.Column(db.String(255)) 
    def set_password(self, password): 
        self.password_hash = generate_password_hash(password) 
    def check_password(self, password): 
        return check_password_hash(self.password_hash, password)


class Category(db.Model):
    __tablename__ = 'category'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    subcategories = db.relationship('SubCategory', back_populates='category', cascade='all, delete-orphan')


class SubCategory(db.Model):
    __tablename__ = 'sub_category'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'))
    category = db.relationship('Category', back_populates='subcategories')
    funds = db.relationship('Fund', back_populates='sub_category')


class Fund(db.Model):
    __tablename__ = 'fund'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    registrar = db.Column(Enum(*REGISTRAR_TYPES, name='registrar_types'), nullable=True)
    fund_url = db.Column(db.String(255))
    latest_nav = db.Column(Numeric(18, 8), nullable=True)
    fund_house = db.Column(db.String(255))
    isin = db.Column(db.String(20), unique=True, nullable=False)
    scheme_code = db.Column(db.String(20), unique=True, nullable=True)
    growth_type = db.Column(db.String(20), nullable=True)  # 'Growth' or 'Dividend'
    is_matured = db.Column(db.Boolean, default=False)
    sub_category_id = db.Column(db.Integer, db.ForeignKey('sub_category.id'))
    sub_category = db.relationship('SubCategory', back_populates='funds')
    investments = db.relationship('Investment', back_populates='fund')
    nav_history = db.relationship('FundNAVHistory', back_populates='fund')

    __table_args__ = (
        db.Index('ix_fund_isin', 'isin'),
    )


class FundNAVHistory(db.Model):
    __tablename__ = 'fund_nav_history'

    id = db.Column(db.Integer, primary_key=True)
    fund_id = db.Column(db.Integer, db.ForeignKey('fund.id'), nullable=False)
    nav_date = db.Column(db.Date, nullable=False)                     # NAV's effective date
    nav_value = db.Column(Numeric(18, 8), nullable=False)             # exact decimal precision
    isin = db.Column(db.String(20), nullable=False)                   # Official ISIN for this variant
    nav_type = db.Column(db.String(20), nullable=False)               # always 'growth'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    fund = db.relationship('Fund', back_populates='nav_history')

    __table_args__ = (
        db.UniqueConstraint('fund_id', 'nav_date', 'isin', name='uq_fund_nav_date_isin'),
        db.CheckConstraint("nav_type = 'growth'", name='chk_nav_type_growth_only'),
    )


class Investment(db.Model):
    __tablename__ = 'investment'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    fund_id = db.Column(db.Integer, db.ForeignKey('fund.id'), nullable=True)
    isin = db.Column(db.String(20), nullable=True)
    transaction_type = db.Column(db.String(20), nullable=False)
    amount = db.Column(Numeric(18, 2), nullable=False)
    nav = db.Column(Numeric(18, 8), nullable=True)
    units = db.Column(Numeric(18, 6), nullable=True)
    date = db.Column(db.Date, nullable=False)
    folio_number = db.Column(db.String(50), nullable=True)
    plan_type = db.Column(db.String(20), nullable=True)  # 'Direct' or 'Regular'
    source_file = db.Column(db.String(255), nullable=True)
    registrar = db.Column(Enum(*REGISTRAR_TYPES, name='registrar_types'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship('User', back_populates='investments')
    fund = db.relationship('Fund', back_populates='investments')

class StagingInvestment(db.Model):
    __tablename__ = "staging_investment"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    isin = db.Column(db.String(20), nullable=False)
    date = db.Column(db.Date, nullable=False)
    amount = db.Column(Numeric(18,2), nullable=False)
    units = db.Column(Numeric(18,6), nullable=False)
    nav = db.Column(Numeric(18,6), nullable=False)
    transaction_type = db.Column(db.String(20), nullable=False)
    source_file = db.Column(db.String(255))
    row_hash = db.Column(db.String(64), nullable=False)
    imported_at = db.Column(db.DateTime, default=datetime.utcnow)

class InvestmentHistory(db.Model):
    __tablename__ = 'investment_history'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    fund_id = db.Column(db.Integer, db.ForeignKey('fund.id'), nullable=False)

    tx_date = db.Column(db.Date, nullable=False)
    tx_type = db.Column(db.String(20), nullable=False)  # 'BUY' or 'SELL'

    units = db.Column(Numeric(18, 6), nullable=False)
    cost_per_unit = db.Column(Numeric(18, 8), nullable=False)
    total_cost = db.Column(Numeric(18, 2), nullable=False)

    units_remaining = db.Column(Numeric(18, 6), nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship('User', backref='investment_history')
    fund = db.relationship('Fund', backref='investment_history')

    __table_args__ = (
        db.CheckConstraint("tx_type IN ('BUY','SELL')", name='chk_tx_type_valid'),
    )


class NavUpdateLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    scheduled_date = db.Column(db.Date, nullable=False, unique=True)
    run_timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20))  # 'success' or 'fail'
    notes = db.Column(db.Text)
    

class DeletionLog(db.Model):
    __tablename__ = 'deletion_log'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    registrar = db.Column(db.String(20), nullable=False)
    reason = db.Column(db.Text, nullable=False)
    deleted_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref='deletion_logs')

class PortfolioSnapshot(db.Model):
    __tablename__ = 'portfolio_snapshot'

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    family_id = db.Column(db.Integer, nullable=True)

    snapshot_date = db.Column(db.Date, nullable=False)
    portfolio_value = db.Column(db.Float, nullable=False)
    dashboard_type = db.Column(db.String(20), nullable=False)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'snapshot_date', 'dashboard_type',
                            name='uq_user_snapshot_date'),
        db.UniqueConstraint('family_id', 'snapshot_date', 'dashboard_type',
                            name='uq_family_snapshot_date'),
        db.Index('ix_user_snapshot_lookup', 'user_id', 'snapshot_date'),
        db.Index('ix_family_snapshot_lookup', 'family_id', 'snapshot_date'),
    )

class PasswordResetToken(db.Model):
    __tablename__ = 'password_reset_token'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    token = db.Column(db.String(255), unique=True, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, default=False)

    user = db.relationship('User', backref='password_reset_tokens')



