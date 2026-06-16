"""Delete the Supabase conversations created by the Playwright E2E run.

The Playwright suite records every conversation id it mints to
``test/screenshots/.e2e-conversations.txt``. This script reads that file and
deletes each conversation, then reports what remained. Run from the backend
venv so ``app.db`` (and its .env-backed credentials) is importable:

    cd backend && uv run python ../test/cleanup_e2e.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the backend package importable when run from the repo root or backend/.
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app import db  # noqa: E402

TRACK_FILE = REPO_ROOT / "test" / "screenshots" / ".e2e-conversations.txt"


def main() -> int:
    if not TRACK_FILE.exists():
        print(f"No tracking file at {TRACK_FILE}; nothing to clean.")
        return 0

    ids = sorted(
        {
            line.strip()
            for line in TRACK_FILE.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
    )
    if not ids:
        print("Tracking file is empty; nothing to clean.")
        return 0

    print(f"Deleting {len(ids)} E2E conversation(s) from Supabase...")
    remaining = 0
    for cid in ids:
        try:
            # Sweep both tables: a MORE archive spec may have moved a tracked
            # conversation into `archive`. Deleting from both is safe (a no-op
            # where the conversation isn't present).
            db.delete_conversation(cid, table=db.TABLE)
            db.delete_conversation(cid, table=db.ARCHIVE_TABLE)
            left = db.get_conversation(cid, table=db.TABLE)
            left += db.get_conversation(cid, table=db.ARCHIVE_TABLE)
            status = "ok" if not left else f"STILL HAS {len(left)} rows"
            if left:
                remaining += 1
            print(f"  {cid}  {status}")
        except Exception as exc:  # pragma: no cover - cleanup best effort
            remaining += 1
            print(f"  {cid}  ERROR: {exc}")

    if remaining:
        print(f"WARNING: {remaining} conversation(s) may not be fully cleaned.")
        return 1

    # Clear the tracking file so a re-run starts clean.
    TRACK_FILE.write_text("", encoding="utf-8")
    print("All E2E conversations deleted; tracking file cleared.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
