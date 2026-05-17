"""Inline keyboard time picker for Telegram.

3-step flow: period → hour → minutes.
Fallback: user can type time directly instead of tapping buttons.
"""

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger(__name__)

# ── Callback data format ─────────────────────────────────────────────
# pick_hour_9       → user picked hour 9
# pick_minute_15    → user picked minute 15
# pick_period_morn  → user picked morning period
# pick_done         → user confirmed
# pick_cancel       → user cancelled

CALLBACK_PREFIX = "brain_pick_"


def build_period_keyboard() -> InlineKeyboardMarkup:
    """Step 1: Ask which part of the day."""
    kb = [
        [
            InlineKeyboardButton("🌅 06:00 - 12:00", callback_data=f"{CALLBACK_PREFIX}period_morn"),
            InlineKeyboardButton("☀️ 12:00 - 18:00", callback_data=f"{CALLBACK_PREFIX}period_aft"),
        ],
        [
            InlineKeyboardButton("🌙 18:00 - 00:00", callback_data=f"{CALLBACK_PREFIX}period_eve"),
            InlineKeyboardButton("⌨️ Type it", callback_data=f"{CALLBACK_PREFIX}type"),
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data=f"{CALLBACK_PREFIX}cancel")],
    ]
    return InlineKeyboardMarkup(kb)


def build_hour_keyboard(period: str) -> InlineKeyboardMarkup:
    """Step 2: Ask which hour based on period."""
    ranges = {
        "morn": range(6, 13),
        "aft": range(12, 19),
        "eve": list(range(18, 24)) + list(range(0, 6)),
    }
    hours = ranges.get(period, range(6, 24))

    rows = []
    row = []
    for h in hours:
        label = f"{h:02d}:00"
        row.append(InlineKeyboardButton(label, callback_data=f"{CALLBACK_PREFIX}hour_{h}"))
        if len(row) >= 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("❌ Cancel", callback_data=f"{CALLBACK_PREFIX}cancel")])
    return InlineKeyboardMarkup(rows)


def build_minute_keyboard() -> InlineKeyboardMarkup:
    """Step 3: Ask minutes (in 15min intervals)."""
    kb = [
        [
            InlineKeyboardButton(":00", callback_data=f"{CALLBACK_PREFIX}min_00"),
            InlineKeyboardButton(":15", callback_data=f"{CALLBACK_PREFIX}min_15"),
            InlineKeyboardButton(":30", callback_data=f"{CALLBACK_PREFIX}min_30"),
            InlineKeyboardButton(":45", callback_data=f"{CALLBACK_PREFIX}min_45"),
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data=f"{CALLBACK_PREFIX}cancel")],
    ]
    return InlineKeyboardMarkup(kb)


def build_confirm_keyboard() -> InlineKeyboardMarkup:
    """Final confirmation after time is selected."""
    kb = [
        [
            InlineKeyboardButton("✅ Yes", callback_data=f"{CALLBACK_PREFIX}done"),
            InlineKeyboardButton("❌ No", callback_data=f"{CALLBACK_PREFIX}cancel"),
        ]
    ]
    return InlineKeyboardMarkup(kb)


def is_picker_callback(data: str) -> bool:
    """Check if a callback data belongs to our picker."""
    return data.startswith(CALLBACK_PREFIX)


def parse_callback(data: str) -> tuple[str, str | None]:
    """Parse callback data into (action, value).

    Returns: ("hour", "9") or ("minute", "15") or ("cancel", None)
    """
    rest = data[len(CALLBACK_PREFIX):]

    if rest.startswith("period_"):
        return ("period", rest[7:])  # morn, aft, eve
    if rest.startswith("hour_"):
        return ("hour", rest[5:])
    if rest.startswith("min_"):
        return ("minute", rest[4:])
    if rest == "done":
        return ("done", None)
    if rest == "cancel":
        return ("cancel", None)
    if rest == "type":
        return ("type", None)

    return ("unknown", rest)
