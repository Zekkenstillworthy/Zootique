"""
Zoo Admin and Staff Notification Service.
Dispatches real-time alerts to Zoo Admins and Staff whenever there is
visitor activity (new booking, payment, cancellation, review/feedback) in their zoo.
"""
from datetime import datetime
from models import Notification, User, db


def notify_zoo_team(
    *,
    zoo_id: int | None,
    notification_type: str,
    message: str,
    booking_id: str | None = None,
    dedupe_prefix: str | None = None,
    commit: bool = True
) -> list[Notification]:
    """
    Sends a targeted notification to all Zoo Admins and Zoo Staff members
    belonging to the given zoo_id.
    """
    if not zoo_id:
        return []

    # Find all active admin and staff accounts for this specific zoo
    team_members = User.query.filter(
        User.zoo_id == zoo_id,
        User.role.in_(['zoo_admin', 'animal_farm_admin', 'admin', 'zoo_staff', 'staff']),
    ).all()

    created_notifs = []
    now = datetime.utcnow()
    prefix = dedupe_prefix or f"zoo-{notification_type}"

    for member in team_members:
        dedupe_key = f"{prefix}:{booking_id or 'act'}:{member.id}"
        # Ensure no duplicates
        existing = Notification.query.filter_by(dedupe_key=dedupe_key).first()
        if not existing:
            notif = Notification(
                user_id=member.id,
                booking_id=booking_id,
                notification_type=notification_type,
                message=message,
                dedupe_key=dedupe_key,
                created_at=now,
            )
            db.session.add(notif)
            created_notifs.append(notif)

    if commit and created_notifs:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()

    return created_notifs
