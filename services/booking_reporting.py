from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from models import Booking, BookingTicketScan


REPORT_RANGES = {
    "today": "Today",
    "last_7_days": "Last 7 days",
    "this_month": "This month",
    "last_month": "Last month",
    "all_time": "All time",
}
REPORT_STATUSES = ("Unpaid", "Paid", "Checked in", "Finished", "Cancelled")
REVENUE_STATUSES = {"Paid", "Checked in", "Finished"}


def schedule_date(value) -> date | None:
    if not value:
        return None
    raw = str(value).strip()[:10]
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def report_period(key: str, today: date | None = None) -> tuple[date | None, date | None]:
    today = today or datetime.now(ZoneInfo("Asia/Manila")).date()
    if key == "today":
        return today, today
    if key == "last_7_days":
        return today - timedelta(days=6), today
    if key == "last_month":
        first_this_month = today.replace(day=1)
        last_month = first_this_month - timedelta(days=1)
        return last_month.replace(day=1), last_month
    if key == "all_time":
        return None, None
    return today.replace(day=1), today


def checked_in_booking_ids(zoo_id: int) -> set[str]:
    return {
        scan.booking_id
        for scan in BookingTicketScan.query.filter_by(zoo_id=zoo_id, result="checked_in").all()
        if scan.booking_id
    }


def report_bookings(zoo_id: int, range_key: str) -> list[Booking]:
    start, end = report_period(range_key)
    bookings = Booking.query.filter_by(zoo_id=zoo_id).all()
    checked_in_ids = checked_in_booking_ids(zoo_id)
    filtered = []
    for booking in bookings:
        booking._is_checked_in = booking.id in checked_in_ids
        booking._report_status = booking.derived_status
        booking._report_date = schedule_date(booking.date)
        if booking._report_date and (start is None or start <= booking._report_date <= end):
            filtered.append(booking)
    return filtered


def revenue_for_bookings(bookings: list[Booking]) -> float:
    return sum(
        float(booking.amount or 0)
        for booking in bookings
        if getattr(booking, "_report_status", booking.derived_status) in REVENUE_STATUSES
    )
