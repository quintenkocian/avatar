"""Seed (or re-seed) the Supabase ``faq`` table from ``knowledge/faq.jsonl``.

Per MORE.md #6, the Supabase ``faq`` table is the source of truth and
``knowledge/faq.jsonl`` is kept as the seed/backup. This script upserts every
seed row by id (so the FAQ numbers 1..N are preserved and the ``Qn`` shortcut /
``?q=N`` deep link keep resolving). Re-running is idempotent.

It also applies the markdown hygiene MORE.md calls out: identifiers whose
underscores would render as emphasis (e.g. ``OPENAI_API_KEY``) are wrapped in
inline backticks, and trailing "(a screenshot shows…)" image notes are dropped.
The current owner FAQ already happens to be clean, so these are no-ops here, but
they keep the seed robust for any owner.

Run:  cd backend && uv run python ../scripts/seed_faq.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from app import db  # noqa: E402  (after sys.path tweak)

FAQ_JSONL = REPO / "knowledge" / "faq.jsonl"

# Identifiers that should be inline-code so their underscores don't italicise.
_BARE_IDENT_RE = re.compile(r"(?<![`\w])([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)(?![`\w])")
# Trailing italic "(a screenshot shows ...)" style image notes that don't belong
# in a text FAQ.
_IMAGE_NOTE_RE = re.compile(r"\s*_\([^)]*(screenshot|image|illustrat)[^)]*\)_\s*$", re.I)


def clean(text: str) -> str:
    text = _IMAGE_NOTE_RE.sub("", text)
    text = _BARE_IDENT_RE.sub(r"`\1`", text)
    return text


def main() -> None:
    rows = []
    for line in FAQ_JSONL.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        rows.append(
            {
                "id": int(row["faq"]),
                "concise": str(row.get("query", "")),
                "question": clean(str(row.get("question", ""))),
                "answer": clean(str(row.get("answer", ""))),
            }
        )

    for row in rows:
        db.upsert_faq(row["id"], row["concise"], row["question"], row["answer"])

    stored = db.list_faqs()
    print(f"Seeded {len(rows)} FAQ rows; table now has {len(stored)}.")
    if stored:
        ids = [r["id"] for r in stored]
        print(f"ids: {min(ids)}..{max(ids)} ({len(ids)} total)")


if __name__ == "__main__":
    main()
