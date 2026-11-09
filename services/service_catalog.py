"""Shared service and promotion categories."""

SERVICE_CATEGORIES = (
    ("Family Tour", "Family Tour"),
    ("Group Tour", "Group Tour"),
    ("Senior Citizen", "Senior Citizen"),
    ("Vip Experience", "Vip Experience"),
    ("Valid For All", "Valid For All"),
)

SERVICE_CATEGORY_VALUES = tuple(value for value, _ in SERVICE_CATEGORIES)
SERVICE_STATUSES = ("Active", "Coming Soon")
