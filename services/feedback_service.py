from __future__ import annotations

from datetime import datetime

from models import Feedback, User, Zoo, db


class FeedbackServiceError(Exception):
    pass


class FeedbackValidationError(FeedbackServiceError):
    pass


class FeedbackAuthorizationError(FeedbackServiceError):
    pass


def feedback_aliases_for_user(user: User | None) -> set[str]:
    aliases: set[str] = set()
    if not user:
        return aliases
    if user.full_name:
        aliases.add(user.full_name.strip())
    if user.email:
        aliases.add(user.email.strip())
    return aliases


def is_feedback_owned_by_user(feedback: Feedback, user: User) -> bool:
    if not feedback or not user:
        return False
    if getattr(feedback, "user_id", None):
        return feedback.user_id == user.id
    return (feedback.visitor_name or "").strip() in feedback_aliases_for_user(user)


def _validate_feedback_payload(*, zoo_id: int | None, rating: int | None, comment: str | None):
    if not zoo_id:
        raise FeedbackValidationError("Please select a zoo.")

    zoo = db.session.get(Zoo, zoo_id)
    if not zoo:
        raise FeedbackValidationError("Selected zoo was not found.")

    if not rating or rating < 1 or rating > 5:
        raise FeedbackValidationError("Please choose a rating from 1 to 5.")

    if not (comment or "").strip():
        raise FeedbackValidationError("Please write a short review comment.")

    return zoo


def create_visitor_feedback(*, user: User, zoo_id: int | None, rating: int | None, comment: str | None) -> Feedback:
    if not user:
        raise FeedbackAuthorizationError("A signed-in visitor is required.")
    if user.role != "visitor":
        raise FeedbackAuthorizationError("Only visitor accounts can create reviews.")

    _validate_feedback_payload(zoo_id=zoo_id, rating=rating, comment=comment)

    feedback = Feedback(
        zoo_id=zoo_id,
        user_id=user.id,
        visitor_name=(user.full_name or user.email or "Visitor"),
        rating=int(rating),
        comment=(comment or "").strip(),
        date=datetime.utcnow().strftime("%Y-%m-%d"),
        created_at=datetime.utcnow(),
    )
    db.session.add(feedback)
    db.session.commit()
    return feedback


def update_visitor_feedback(*, feedback: Feedback, user: User, zoo_id: int | None, rating: int | None, comment: str | None) -> Feedback:
    if not user:
        raise FeedbackAuthorizationError("A signed-in visitor is required.")
    if user.role != "visitor":
        raise FeedbackAuthorizationError("Only visitor accounts can update reviews.")
    if not feedback:
        raise FeedbackValidationError("Feedback not found.")
    if not is_feedback_owned_by_user(feedback, user):
        raise FeedbackAuthorizationError("You can only edit your own feedback.")

    _validate_feedback_payload(zoo_id=zoo_id, rating=rating, comment=comment)

    feedback.zoo_id = zoo_id
    feedback.user_id = user.id
    feedback.visitor_name = (user.full_name or user.email or feedback.visitor_name)
    feedback.rating = int(rating)
    feedback.comment = (comment or "").strip()
    feedback.date = datetime.utcnow().strftime("%Y-%m-%d")
    db.session.commit()
    return feedback


def delete_visitor_feedback(*, feedback: Feedback, user: User):
    if not user:
        raise FeedbackAuthorizationError("A signed-in visitor is required.")
    if not feedback:
        raise FeedbackValidationError("Feedback not found.")
    if not is_feedback_owned_by_user(feedback, user):
        raise FeedbackAuthorizationError("You can only delete your own feedback.")

    db.session.delete(feedback)
    db.session.commit()
