import logging
import time
from collections import defaultdict

from app.config import settings

logger = logging.getLogger(__name__)

# Simple in-memory rate limiter: {chat_id: [timestamps]}
_rate_limit_buckets: dict[int, list[float]] = defaultdict(list)
RATE_LIMIT_WINDOW = 1.0  # seconds
RATE_LIMIT_MAX = 5  # max messages per window


def check_rate_limit(chat_id: int) -> bool:
    """Return True if request is allowed, False if rate-limited."""
    now = time.monotonic()
    timestamps = _rate_limit_buckets[chat_id]

    # Remove old timestamps outside the window
    _rate_limit_buckets[chat_id] = [t for t in timestamps if now - t < RATE_LIMIT_WINDOW]

    if len(_rate_limit_buckets[chat_id]) >= RATE_LIMIT_MAX:
        logger.warning("Rate limit exceeded for chat %s", chat_id)
        return False

    _rate_limit_buckets[chat_id].append(now)
    return True


def authorize_chat_id(chat_id: int) -> bool:
    """Check if a chat_id is allowed."""
    if not settings.allowed_chat_ids:
        return True  # No restrictions
    return chat_id in settings.allowed_chat_ids
