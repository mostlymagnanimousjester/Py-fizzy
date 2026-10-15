COLUMN_COLORS = [
    ("Blue", "var(--color-card-default)"),
    ("Gray", "var(--color-card-1)"),
    ("Tan", "var(--color-card-2)"),
    ("Yellow", "var(--color-card-3)"),
    ("Lime", "var(--color-card-4)"),
    ("Aqua", "var(--color-card-5)"),
    ("Violet", "var(--color-card-6)"),
    ("Purple", "var(--color-card-7)"),
    ("Pink", "var(--color-card-8)"),
]
COLOR_VALUES = {value for _, value in COLUMN_COLORS}
COLOR_NAMES = {value: name for name, value in COLUMN_COLORS}

POSTPONE_DAYS = (3, 7, 11, 30, 90, 365)
DEFAULT_POSTPONE_DAYS = 30

BUNDLE_FREQUENCIES = ("never", "every_few_hours", "daily", "weekly")

WEBHOOK_ACTIONS = (
    "card_assigned",
    "card_closed",
    "card_postponed",
    "card_auto_postponed",
    "card_board_changed",
    "card_published",
    "card_reopened",
    "card_sent_back_to_triage",
    "card_triaged",
    "card_unassigned",
    "comment_created",
)

PAGE_SIZE = 30
STALLED_DAYS = 14
