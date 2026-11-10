from __future__ import annotations

from datetime import datetime, timedelta

from models import Booking, LoyaltyAccount, LoyaltySetting, LoyaltyTransaction, User, db

BOOKING_EARN_POINTS = 100
POINTS_STEP = 100
PESO_PER_POINTS_STEP = 10


def get_settings() -> LoyaltySetting:
    setting = LoyaltySetting.query.first()
    if setting:
        return setting
    setting = LoyaltySetting()
    db.session.add(setting)
    db.session.flush()
    return setting


def get_account(user: User) -> LoyaltyAccount:
    account = LoyaltyAccount.query.filter_by(user_id=user.id).first()
    if account:
        return account
    account = LoyaltyAccount(user_id=user.id, balance=0)
    db.session.add(account)
    db.session.flush()
    return account


def record_transaction(*, user: User, points: int, transaction_type: str, description: str, booking_id: str | None = None) -> LoyaltyTransaction:
    if points == 0:
        raise ValueError("A loyalty transaction must contain non-zero points.")
    if transaction_type not in {"earn", "redeem", "adjust", "reverse"}:
        raise ValueError("Unsupported loyalty transaction type.")
    account = get_account(user)
    if account.balance + points < 0:
        raise ValueError("Loyalty balance cannot become negative.")
    settings = get_settings()
    expires_at = None
    if points > 0 and settings.expiration_days:
        expires_at = datetime.utcnow() + timedelta(days=settings.expiration_days)
    account.balance += points
    transaction = LoyaltyTransaction(
        account_id=account.id,
        points=points,
        transaction_type=transaction_type,
        description=description,
        booking_id=booking_id,
        expires_at=expires_at,
    )
    db.session.add(transaction)
    return transaction


def points_discount(points: int) -> float:
    """Return the fixed booking discount for a valid points amount."""
    if points < 0 or points % POINTS_STEP:
        raise ValueError("Redeemed points must be in steps of 100.")
    return (points // POINTS_STEP) * PESO_PER_POINTS_STEP


def award_booking_points(*, booking: Booking) -> bool:
    """Award the flat booking reward once when a booking becomes Finished."""
    if not booking.user_id or (booking.status or "").strip().lower() != "finished":
        return False
    existing = LoyaltyTransaction.query.filter_by(
        booking_id=booking.id,
        transaction_type="earn",
    ).first()
    if existing:
        return False
    record_transaction(
        user=booking.user,
        points=BOOKING_EARN_POINTS,
        transaction_type="earn",
        description=f"Finished booking reward for {booking.id}",
        booking_id=booking.id,
    )
    return True


def reverse_booking_points(*, booking: Booking, user: User | None = None) -> bool:
    """Reverse booking earn/redeem transactions once, including on deletion."""
    target_user = user or booking.user
    if not target_user:
        return False
    changed = False
    transactions = LoyaltyTransaction.query.filter_by(booking_id=booking.id).all()
    for transaction in transactions:
        if transaction.transaction_type == "earn" and transaction.points > 0:
            description = f"Earned points reversed for cancelled booking {booking.id}"
            exists = LoyaltyTransaction.query.filter_by(
                booking_id=booking.id,
                transaction_type="reverse",
                description=description,
            ).first()
            if not exists:
                record_transaction(
                    user=target_user,
                    points=-int(transaction.points),
                    transaction_type="reverse",
                    description=description,
                    booking_id=booking.id,
                )
                changed = True
        elif transaction.transaction_type == "redeem" and transaction.points < 0:
            description = f"Redeemed points returned for cancelled booking {booking.id}"
            exists = LoyaltyTransaction.query.filter_by(
                booking_id=booking.id,
                transaction_type="reverse",
                description=description,
            ).first()
            if not exists:
                record_transaction(
                    user=target_user,
                    points=abs(int(transaction.points)),
                    transaction_type="reverse",
                    description=description,
                    booking_id=booking.id,
                )
                changed = True
    return changed


def sync_booking_points_for_status(*, booking: Booking) -> bool:
    """Apply the one-time Finished reward or cancellation reversals."""
    status = (booking.status or "").strip().lower()
    if status == "finished":
        return award_booking_points(booking=booking)
    if status == "cancelled":
        return reverse_booking_points(booking=booking)
    return False
