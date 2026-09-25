"""Validate the applied fixture-backed sample dataset."""

from __future__ import annotations

from datetime import date
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import create_app
from models import Animal, Booking, BookingPayment, Event, Notification, Promotion, Service, Zoo, ZooZone, db
from scripts.sample_data.fixture import SAMPLE_ZOOS


def validate() -> list[str]:
    failures: list[str] = []
    fixtures = {z["name"]: z for z in SAMPLE_ZOOS}
    sample_names = set(fixtures)
    zoos = {z.name: z for z in Zoo.query.filter(Zoo.name.in_(sample_names)).all()}
    today = date.today()
    for name, fixture in fixtures.items():
        zoo = zoos.get(name)
        if not zoo:
            failures.append(f"missing zoo: {name}")
            continue
        zones = {z["name"]: z for z in fixture["zones"]}
        db_zones = {z.name: z for z in ZooZone.query.filter_by(zoo_id=zoo.id).all()}
        for animal in Animal.query.filter_by(zoo_id=zoo.id).all():
            if animal.habitat not in zones or zones[animal.habitat]["kind"] != "habitat":
                failures.append(f"{name}: animal {animal.name} is not in a habitat zone")
        for event in Event.query.filter_by(zoo_id=zoo.id).all():
            if event.location not in db_zones:
                failures.append(f"{name}: event {event.name} has unknown location {event.location}")
            try:
                if date.fromisoformat((event.time or "").split()[0]) <= today:
                    failures.append(f"{name}: event {event.name} is not in the future")
            except ValueError:
                failures.append(f"{name}: event {event.name} has invalid date {event.time}")
        service_ids = {s.id for s in Service.query.filter_by(zoo_id=zoo.id).all()}
        for booking in Booking.query.filter_by(zoo_id=zoo.id).all():
            if booking.service_id not in service_ids:
                failures.append(f"{name}: booking {booking.id} service is outside its zoo")
            try:
                booking_date = date.fromisoformat(booking.date)
                if booking.status in {"Pending", "Confirmed"} and booking_date < today:
                    failures.append(f"{name}: {booking.id} future status has past date")
                if booking.status in {"Completed", "Cancelled"} and booking_date >= today:
                    failures.append(f"{name}: {booking.id} completed/cancelled status has future date")
            except (TypeError, ValueError):
                failures.append(f"{name}: booking {booking.id} has invalid date")
            payments = BookingPayment.query.filter_by(booking_id=booking.id).all()
            if booking.payment_status == "paid":
                if not payments or abs(sum(float(p.amount) for p in payments if p.status == "paid") - float(booking.amount or 0)) > 0.01:
                    failures.append(f"{name}: paid booking {booking.id} payment total disagrees")
            for notification in Notification.query.filter_by(booking_id=booking.id).all():
                expected = f"Booking confirmed: {booking.service_name} on {booking.date} for PHP {booking.amount:.2f}."
                if notification.notification_type == "booking_confirmation" and notification.message != expected:
                    failures.append(f"{name}: notification disagrees for {booking.id}")
        promotions = Promotion.query.filter_by(zoo_id=zoo.id).all()
        if sum(1 for p in promotions if p.valid_until and date.fromisoformat(p.valid_until) >= today) < 2:
            failures.append(f"{name}: fewer than two active promotions")
        for model, rows in ((Animal, Animal.query.filter_by(zoo_id=zoo.id)), (Service, Service.query.filter_by(zoo_id=zoo.id))):
            for row in rows.all():
                if row.image_url and (row.image_url.startswith("http://") or row.image_url.startswith("https://")):
                    failures.append(f"{name}: remote image URL on {model.__name__} {row.name}")
                if row.image_url and not (ROOT / row.image_url.lstrip("/")).is_file():
                    failures.append(f"{name}: missing image file for {model.__name__} {row.name}")
    codes = [p.code for p in Promotion.query.filter(Promotion.zoo_id.isnot(None)).all()]
    if len(codes) != len(set(codes)):
        failures.append("promotion codes are not unique")
    if Event.query.filter(Event.zoo_id.is_(None)).count():
        failures.append("zoo-less events remain")
    if Booking.query.filter(Booking.zoo_id.is_(None)).count():
        failures.append("zoo-less bookings remain")
    return failures


def main() -> int:
    app = create_app()
    with app.app_context():
        failures = validate()
    if failures:
        print("SAMPLE DATA VALIDATION FAILED")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("SAMPLE DATA VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
