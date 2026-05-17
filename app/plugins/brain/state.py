"""In-memory pending state tracker for multi-turn conversations.

Stores incomplete actions waiting for user input (time, text, confirmation).
Lost on bot restart — user just re-sends their message. Safe.
"""

from typing import Any

_pending: dict[int, dict[str, Any]] = {}


def get(chat_id: int) -> dict[str, Any] | None:
    """Get pending state for a chat, or None."""
    return _pending.get(chat_id)


def set(chat_id: int, data: dict[str, Any]) -> None:
    """Set pending state for a chat."""
    _pending[chat_id] = data


def clear(chat_id: int) -> None:
    """Clear pending state for a chat."""
    _pending.pop(chat_id, None)


def has(chat_id: int) -> bool:
    """Check if a chat has pending state."""
    return chat_id in _pending
