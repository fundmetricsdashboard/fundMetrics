

from models import db
from sqlalchemy.exc import IntegrityError

class ISINMapper(db.Model):
    """
    Table to map ISINs to AMFI scheme codes (used by MFAPI.in).
    """
    __tablename__ = "isin_scheme_map"

    id = db.Column(db.Integer, primary_key=True)
    isin = db.Column(db.String(20), unique=True, nullable=False)
    scheme_code = db.Column(db.String(20), nullable=False)
    scheme_name = db.Column(db.String(255))

    @staticmethod
    def get_scheme_code(isin: str):
        """
        Return scheme_code for a given ISIN if known, else None.
        """
        mapping = ISINMapper.query.filter_by(isin=isin).first()
        return mapping.scheme_code if mapping else None

    @staticmethod
    def add_mapping(isin: str, scheme_code: str, scheme_name: str = None):
        """
        Add a new ISIN → scheme_code mapping.
        """
        mapping = ISINMapper(isin=isin, scheme_code=scheme_code, scheme_name=scheme_name)
        db.session.add(mapping)
        try:
            db.session.commit()
            print(f"✅ Added mapping {isin} → {scheme_code}")
        except IntegrityError:
            db.session.rollback()
            print(f"⚠️ Mapping for {isin} already exists")

    @staticmethod
    def update_mapping(isin: str, scheme_code: str):
        """
        Update scheme_code for an existing ISIN.
        """
        mapping = ISINMapper.query.filter_by(isin=isin).first()
        if mapping:
            mapping.scheme_code = scheme_code
            db.session.commit()
            print(f"🔄 Updated mapping {isin} → {scheme_code}")
        else:
            print(f"⚠️ No mapping found for {isin}, use add_mapping instead")

    @staticmethod
    def ensure_scheme_code(isin: str, scheme_name: str = None):
        """
        Ensure a scheme_code exists for this ISIN.
        If not found, prompt the user to enter it.
        """
        scheme_code = ISINMapper.get_scheme_code(isin)
        if scheme_code:
            return scheme_code

        # Prompt user (CLI version — in a web app, replace with UI form)
        scheme_code = input(f"Enter scheme code for ISIN {isin} ({scheme_name or 'Unknown Scheme'}): ")
        ISINMapper.add_mapping(isin, scheme_code, scheme_name=scheme_name)
        return scheme_code
