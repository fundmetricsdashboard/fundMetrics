# ===========================
# Delete Duplicate User Route
# change the name as required
# ===========================

from app import app, db
from models import User

with app.app_context():
    users = User.query.filter_by(name='Abhinav').order_by(User.id).all()
    for user in users[1:]:
        db.session.delete(user)
    db.session.commit()
    print(f"✅ Removed {len(users) - 1} duplicates.")
