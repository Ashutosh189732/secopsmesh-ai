"""Wipe all incidents so a demo run starts from a clean slate.

Deletes every row from the `incidents` table via SQLAlchemy (not the raw
.db file) so it's safe to run whether or not the backend is currently
running - it uses the same engine/session the app uses, no file locking
games on a network drive. This project's Incident model uses a plain
INTEGER PRIMARY KEY (no explicit AUTOINCREMENT), so SQLite reuses ID 1 on
its own the moment the table is empty - the next incident created after
this script runs will be #1 again with no extra step needed.

Usage:
    python demo/reset_db.py
    python demo/reset_db.py --yes    # skip the confirmation prompt

Caveat: if any incident is currently mid-investigation (an orchestrator
background thread is running for it), deleting its row while that thread is
still writing evidence/root_cause/etc. back to it will make that write fail.
Safest to run this a minute or two after your last signal, once every
incident has either settled into parked/queued or finished investigating.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal  # noqa: E402
from app.models import Incident  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="Skip the confirmation prompt")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        count = db.query(Incident).count()
        if count == 0:
            print("incidents table is already empty - nothing to do.")
            return

        if not args.yes:
            reply = input(f"This will permanently delete {count} incident(s). Continue? [y/N] ")
            if reply.strip().lower() not in ("y", "yes"):
                print("Aborted.")
                return

        db.query(Incident).delete()
        db.commit()
    finally:
        db.close()

    print(f"Deleted {count} incident(s). Next incident created will be #1.")


if __name__ == "__main__":
    main()
