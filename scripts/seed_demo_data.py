"""CLI wrapper for the fixture-backed sample-data rebuild."""

from __future__ import annotations

from pathlib import Path
import sys

# Allow running as `python scripts/seed_demo_data.py`.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import create_app
from services.demo_seed import seed


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()
    app = create_app()

    with app.app_context():
        stats = seed(dry_run=args.dry_run, reset=args.reset)
        if stats:
            print("Seed complete")
            for key, value in sorted(stats.items()):
                print(f"- {key}: created={value.created} updated={value.updated} deleted={value.deleted}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
