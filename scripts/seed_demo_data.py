"""Seed demo data into Postgres.

This script is intentionally idempotent: it only inserts rows when the relevant
tables/sections are empty.

Usage:
    python scripts/seed_demo_data.py

Requires:
    - DATABASE_URL env var (same as running the app)
"""

from __future__ import annotations

from pathlib import Path
import sys

# Allow running as `python scripts/seed_demo_data.py`.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import create_app
from services.demo_seed import ensure_demo_data


def main() -> int:
    app = create_app()

    with app.app_context():
        stats = ensure_demo_data(allow_create_tables=True)

        print("Seed complete")
        for key in sorted(stats.keys()):
            s = stats[key]
            print(f"- {key}: created={s.created} skipped={s.skipped}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
