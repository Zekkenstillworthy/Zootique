from models import User, db


def assigned_facility_ids() -> set[int]:
    """Return the distinct facilities currently assigned to Zoo Admin accounts."""
    return {
        zoo_id
        for (zoo_id,) in db.session.query(User.zoo_id)
        .filter(User.role == "zoo_admin", User.zoo_id.isnot(None))
        .distinct()
        .all()
    }
