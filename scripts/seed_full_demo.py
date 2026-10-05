"""Compatibility wrapper for the fixture-backed sample-data rebuild."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import create_app
from services.demo_seed import seed


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild the tagged Zootique sample dataset.")
    parser.add_argument("--force", action="store_true", help="Compatibility alias for --reset.")
    parser.add_argument("--reset", action="store_true", help="Apply the reset and rebuild transaction.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned changes without writing.")
    args = parser.parse_args()
    app = create_app()
    with app.app_context():
        seed(dry_run=args.dry_run, reset=args.reset or args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
