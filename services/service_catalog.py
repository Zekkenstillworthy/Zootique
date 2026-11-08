"""Shared service and promotion categories."""

SERVICE_CATEGORIES = (
    ("Tour", "Tour"),
    ("Feeding", "Feeding Experience"),
    ("Photography", "Photography Session"),
    ("Education", "Educational Program"),
    ("VIP", "VIP Experience"),
    ("Workshop", "Workshop"),
    ("Other", "Other"),
)

SERVICE_CATEGORY_VALUES = tuple(value for value, _ in SERVICE_CATEGORIES)
SERVICE_STATUSES = ("Active", "Coming Soon")
