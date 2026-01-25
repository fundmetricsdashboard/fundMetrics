# seed_isin_mapper.py
from models import db, Fund
from isin_mapper import ISINMapper
from flask import Flask
import os

# Minimal Flask app context so SQLAlchemy works
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv(
    'DATABASE_URL',
    'mysql+pymysql://root:password@127.0.0.1/investments'
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

def seed_isin_mapper():
    with app.app_context():
        funds = Fund.query.all()
        for fund in funds:
            isin = fund.isin
            if not isin:
                continue

            scheme_code = ISINMapper.get_scheme_code(isin)
            if scheme_code:
                print(f"✅ Mapping exists: {isin} → {scheme_code}")
            else:
                # Prompt user for scheme code
                print(f"⚠️ No mapping found for {fund.name} ({isin})")
                scheme_code = input(f"Enter scheme code for {fund.name}: ").strip()
                if scheme_code:
                    ISINMapper.add_mapping(isin, scheme_code, scheme_name=fund.name)

if __name__ == "__main__":
    seed_isin_mapper()
