# run_snapshots.py

from app import app
from snapshot_generator import (
    generate_personal_snapshots,
    generate_family_snapshots
)
from models import User, Family

with app.app_context():
    print("\n==============================")
    print("  Running Full Snapshot Rebuild")
    print("==============================\n")

    # -----------------------------------------
    # PERSONAL SNAPSHOTS
    # -----------------------------------------
    users = User.query.all()
    print(f"[INFO] Found {len(users)} users")

    for u in users:
        try:
            print(f"[PERSONAL] Generating snapshots for user {u.id} ({u.name})")
            generate_personal_snapshots(u.id)
        except Exception as e:
            print(f"[ERROR] Failed for user {u.id}: {e}")

    # -----------------------------------------
    # FAMILY SNAPSHOTS
    # -----------------------------------------
    families = Family.query.all()
    print(f"\n[INFO] Found {len(families)} families")

    for fam in families:
        try:
            print(f"[FAMILY] Generating snapshots for family {fam.id} ({fam.name})")
            generate_family_snapshots(fam.id)
        except Exception as e:
            print(f"[ERROR] Failed for family {fam.id}: {e}")

    print("\n==============================")
    print("  Snapshot Rebuild Complete")
    print("==============================\n")
