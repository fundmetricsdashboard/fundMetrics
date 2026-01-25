import os
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

def configure_database(app):
    default_sqlite_path = "sqlite:///fundMetrics.db"

    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv(
        'DATABASE_URL',
        default_sqlite_path
    )
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    db.init_app(app)
