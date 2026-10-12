from __future__ import annotations

from datetime import datetime, timedelta

from models import LoyaltyAccount, LoyaltySetting, LoyaltyTransaction, User, db


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
