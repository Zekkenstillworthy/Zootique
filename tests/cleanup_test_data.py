"""Remove only round-two/round-three namespaced test rows from the live database."""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
load_dotenv(".env")

from app import create_app
from models import db


def _ids(sql: str) -> list:
    return [row[0] for row in db.session.execute(text(sql)).all()]


def cleanup() -> dict[str, int]:
    deleted: dict[str, int] = {}
    user_ids = _ids(
        "SELECT id FROM users WHERE email ILIKE '%cancellation-policy%' "
        "OR email ILIKE 'e2e-%'"
    )
    booking_ids = _ids(
        "SELECT id FROM bookings WHERE id ILIKE 'CANCEL-POLICY%' "
        "OR id ILIKE 'CP-%' OR id ILIKE 'E2E-%' OR id ILIKE 'e2e-%'"
    )
    zoo_ids = _ids(
        "SELECT id FROM zoos WHERE name ILIKE 'Cancellation Policy Zoo%' "
        "OR name ILIKE 'e2e-%'"
    )
    if not user_ids and not booking_ids and not zoo_ids:
        return deleted

    def execute(label: str, sql: str, values: dict) -> None:
        result = db.session.execute(text(sql), values)
        if result.rowcount:
            deleted[label] = result.rowcount

    if booking_ids:
        execute("booking_tickets_scans", "DELETE FROM booking_ticket_scans WHERE ticket_id IN (SELECT id FROM booking_tickets WHERE booking_id = ANY(:ids))", {"ids": booking_ids})
        execute("booking_tickets", "DELETE FROM booking_tickets WHERE booking_id = ANY(:ids)", {"ids": booking_ids})
        execute("loyalty_transactions", "DELETE FROM loyalty_transactions WHERE booking_id = ANY(:ids)", {"ids": booking_ids})
        execute("notifications", "DELETE FROM notifications WHERE booking_id = ANY(:ids)", {"ids": booking_ids})
        execute("booking_payments", "DELETE FROM booking_payments WHERE booking_id = ANY(:ids)", {"ids": booking_ids})
        execute("bookings", "DELETE FROM bookings WHERE id = ANY(:ids)", {"ids": booking_ids})
    if user_ids:
        execute("loyalty_transactions_for_users", "DELETE FROM loyalty_transactions WHERE account_id IN (SELECT id FROM loyalty_accounts WHERE user_id = ANY(:ids))", {"ids": user_ids})
        execute("loyalty_accounts", "DELETE FROM loyalty_accounts WHERE user_id = ANY(:ids)", {"ids": user_ids})
        execute("notifications_for_users", "DELETE FROM notifications WHERE user_id = ANY(:ids)", {"ids": user_ids})
        execute("booking_payments_for_users", "DELETE FROM booking_payments WHERE payer_user_id = ANY(:ids)", {"ids": user_ids})
        execute("users", "DELETE FROM users WHERE id = ANY(:ids)", {"ids": user_ids})
    if zoo_ids:
        for table in (
            "zoo_graph_configs", "zoo_layout_configs", "zoo_subscriptions",
            "zoo_zones", "services", "animals", "events", "promotions",
            "feedbacks", "staff_tasks", "park_rules", "trivia_questions",
            "zoos",
        ):
            column = "id" if table == "zoos" else "zoo_id"
            execute(table, f"DELETE FROM {table} WHERE {column} = ANY(:ids)", {"ids": zoo_ids})
    db.session.commit()
    return deleted


if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        print(cleanup())
