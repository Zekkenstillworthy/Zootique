"""Service and promotion category catalogs."""

SERVICE_CATEGORIES = (
    ("Family Tour", "Family Tour"),
    ("Group Tour", "Group Tour"),
    ("Tour", "Tour"),
    ("Senior Citizen", "Senior Citizen"),
    ("Vip Experience", "Vip Experience"),
)

SERVICE_CATEGORY_VALUES = tuple(value for value, _ in SERVICE_CATEGORIES)

PROMOTION_CATEGORIES = (
    ("Family Tour", "Family Tour"),
    ("Group Tour", "Group Tour"),
    ("Tour", "Tour"),
    ("Senior Citizen", "Senior Citizen"),
    ("Vip Experience", "Vip Experience"),
    ("Valid For All", "Valid For All"),
)

PROMOTION_CATEGORY_VALUES = tuple(value for value, _ in PROMOTION_CATEGORIES)
SERVICE_STATUSES = ("Active", "Coming Soon")
