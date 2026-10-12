from __future__ import annotations

from calendar import month_abbr
from datetime import date, datetime, timedelta

from models import Booking, Feedback, ZooGraphConfig, db


GRAPH_CHART_TYPES = {"bar", "line"}
GRAPH_DATA_SOURCES = {"bookings", "revenue", "visitors", "ratings"}
GRAPH_DATE_RANGES = {"last_3_months", "last_6_months", "last_12_months"}
GRAPH_GROUPS = {"month"}


def validate_graph_config(*, name: str, chart_type: str, data_source: str, date_range: str, group_by: str) -> None:
    if not name or len(name) > 120:
        raise ValueError("Graph name is required and must be 120 characters or fewer.")
    if chart_type not in GRAPH_CHART_TYPES:
        raise ValueError("Unsupported graph chart type.")
    if data_source not in GRAPH_DATA_SOURCES:
        raise ValueError("Unsupported graph data source.")
    if date_range not in GRAPH_DATE_RANGES:
        raise ValueError("Unsupported graph date range.")
    if group_by not in GRAPH_GROUPS:
        raise ValueError("Unsupported graph grouping.")


def build_graph_data(config: ZooGraphConfig, *, today: date | None = None) -> dict:
    today = today or date.today()
    months = {"last_3_months": 3, "last_6_months": 6, "last_12_months": 12}[config.date_range]
    first_month = (today.replace(day=1) - timedelta(days=months * 31)).replace(day=1)
    labels = []
    cursor = first_month
    for _ in range(months):
        labels.append(f"{month_abbr[cursor.month]} {cursor.year}")
        cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)

    values = [0.0] * len(labels)
    if config.data_source in {"bookings", "revenue", "visitors"}:
        rows = Booking.query.filter(Booking.zoo_id == config.zoo_id).all()
        for booking in rows:
            try:
                booking_date = datetime.strptime(str(booking.date), "%Y-%m-%d").date()
            except (TypeError, ValueError):
                continue
            key = f"{month_abbr[booking_date.month]} {booking_date.year}"
            if key not in labels:
                continue
            index = labels.index(key)
            if config.data_source == "revenue":
                values[index] += float(booking.amount or 0)
            elif config.data_source == "visitors":
                values[index] += int(booking.guests or 0)
            else:
                values[index] += 1
    else:
        rows = Feedback.query.filter(Feedback.zoo_id == config.zoo_id).all()
        counts = [0] * len(labels)
        for feedback in rows:
            created = feedback.created_at.date() if feedback.created_at else None
            if not created:
                continue
            key = f"{month_abbr[created.month]} {created.year}"
            if key in labels:
                index = labels.index(key)
                values[index] += float(feedback.rating or 0)
                counts[index] += 1
        values = [round(value / counts[index], 2) if counts[index] else 0 for index, value in enumerate(values)]

    return {"labels": labels, "values": values, "source": config.data_source, "chart_type": config.chart_type}


def save_graph_config(*, zoo_id: int, config: ZooGraphConfig | None = None, **values) -> ZooGraphConfig:
    validate_graph_config(**values)
    target = config or ZooGraphConfig(zoo_id=zoo_id)
    if config is None:
        db.session.add(target)
    target.name = values["name"]
    target.chart_type = values["chart_type"]
    target.data_source = values["data_source"]
    target.date_range = values["date_range"]
    target.group_by = values["group_by"]
    target.filters = values.get("filters") or {}
    target.is_visible = bool(values.get("is_visible", True))
    return target
