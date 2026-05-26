"""Context retriever — conversation memory layer for BrainPlugin.

Retrieves and compresses context from multiple sources:
1. Last N raw messages (chronological, unfiltered — both user + bot)
2. FTS5 search on past messages by keyword relevance
3. FTS5 search on saved notes

Strategy: recent context first, FTS5 fills remaining space.
"""

import logging
import re
from datetime import datetime, timedelta, timezone

from app.database import get_db

logger = logging.getLogger(__name__)

# Token budget (rough estimation: ~4 chars = 1 token for EN/ID)
_CHARS_PER_TOKEN = 4
_MAX_CONTEXT_TOKENS = 1500       # reserve 500+ for system + user msg + response
_MAX_CONTEXT_CHARS = _MAX_CONTEXT_TOKENS * _CHARS_PER_TOKEN  # ~6000
_MAX_RECENT_MSGS = 10            # last N messages to include
_MAX_MSG_CHARS = 500             # max chars per single message
_FTS_MESSAGE_LIMIT = 3
_FTS_NOTE_LIMIT = 2

WIB = timezone(timedelta(hours=7))


def _fmt_time(dt_str: str) -> str:
    """Format SQLite datetime to relative time string."""
    try:
        dt = datetime.fromisoformat(dt_str)
        local = dt.astimezone(WIB)
        now = datetime.now(WIB)
        diff = now - local

        if diff.total_seconds() < 60:
            return "just now"
        elif diff.total_seconds() < 3600:
            m = int(diff.total_seconds() / 60)
            return f"{m}m ago"
        elif diff.total_seconds() < 86400:
            h = int(diff.total_seconds() / 3600)
            return f"{h}h ago"
        else:
            return local.strftime("%a %d %b %H:%M")
    except (ValueError, TypeError):
        return dt_str


def _extract_keywords(text: str) -> str:
    """Extract meaningful keywords from user message for FTS5 query."""
    if not text:
        return ""

    # Remove markdown, URLs, emojis
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'[*_~`>\#]', '', text)
    text = re.sub(r'[^\w\s]', ' ', text)

    stop_words = {
        'a', 'an', 'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
        'of', 'with', 'by', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
        'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
        'should', 'may', 'might', 'can', 'shall', 'not', 'no', 'nor',
        'i', 'you', 'he', 'she', 'it', 'we', 'they', 'me', 'him', 'her', 'us', 'them',
        'my', 'your', 'his', 'its', 'our', 'their', 'this', 'that', 'these', 'those',
        'what', 'which', 'who', 'whom', 'how', 'when', 'where', 'why',
        'ya', 'yang', 'di', 'ke', 'dari', 'dan', 'atau', 'tapi', 'ini', 'itu',
        'saya', 'aku', 'kamu', 'dia', 'mereka', 'kami', 'kita',
        'ada', 'adalah', 'bisa', 'dapat', 'telah', 'sudah', 'belum',
        'akan', 'sedang', 'lagi', 'juga', 'saja', 'hanya',
    }

    words = text.lower().split()
    keywords = [w for w in words if len(w) > 2 and w not in stop_words]

    return ' '.join(f'{w}*' for w in keywords[:8])


def _truncate(text: str, max_chars: int) -> str:
    """Truncate with ellipsis."""
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def _compact_text(text: str, max_chars: int = _MAX_MSG_CHARS) -> str:
    """Compact a single message: single line, truncate if needed."""
    text = re.sub(r'\s+', ' ', text).strip()
    return _truncate(text, max_chars)


async def get_recent_messages(
    chat_id: int,
    limit: int = _MAX_RECENT_MSGS,
) -> list[str]:
    """Get last N messages chronologically. Unfiltered — all types (user, bot).

    Returns formatted strings like: "[5m ago] You: remind me tomorrow 9am"
    """
    db = await get_db()
    cursor = await db.execute(
        "SELECT text, type, username, created_at FROM messages "
        "WHERE chat_id = ? "
        "ORDER BY id DESC LIMIT ?",
        (chat_id, limit),
    )
    rows = list(reversed(await cursor.fetchall()))
    if not rows:
        return []

    result = []
    for r in rows:
        t = r["text"] or ""
        label = "You" if r["type"] == "user" else "Bot"
        time_str = _fmt_time(r["created_at"])
        text = _compact_text(t, _MAX_MSG_CHARS)
        result.append(f"[{time_str}] {label}: {text}")

    return result


async def search_fts_messages(
    chat_id: int,
    keywords: str,
    limit: int = _FTS_MESSAGE_LIMIT,
) -> list[dict]:
    """FTS5 search past messages (skip if no keywords)."""
    if not keywords:
        return []

    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id, text, type, username, created_at FROM messages_fts "
            "WHERE messages_fts MATCH ? AND chat_id = ? "
            "AND created_at >= datetime('now', '-48 hours') "
            "ORDER BY rank LIMIT ?",
            (keywords, chat_id, limit),
        )
        rows = await cursor.fetchall()
    except Exception as e:
        logger.warning("FTS5 messages search failed: %s", e)
        return []

    return [
        {
            "id": r["id"],
            "text": _compact_text(r["text"], 300),
            "type": r["type"] or "user",
            "username": r["username"] or ("Bot" if (r["type"] == "bot") else "User"),
            "time": _fmt_time(r["created_at"]),
        }
        for r in rows
    ]


async def search_notes(
    chat_id: int,
    keywords: str,
    limit: int = _FTS_NOTE_LIMIT,
) -> list[dict]:
    """FTS5 search saved notes."""
    if not keywords:
        return []

    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id, text, created_at FROM notes_fts "
            "WHERE notes_fts MATCH ? AND chat_id = ? "
            "ORDER BY rank LIMIT ?",
            (keywords, chat_id, limit),
        )
        rows = await cursor.fetchall()
    except Exception as e:
        logger.warning("FTS5 notes search failed: %s", e)
        return []

    return [
        {
            "id": r["id"],
            "text": _compact_text(r["text"], 300),
            "time": _fmt_time(r["created_at"]),
        }
        for r in rows
    ]


async def retrieve_context(
    chat_id: int,
    message_text: str,
    max_chars: int = _MAX_CONTEXT_CHARS,
) -> str:
    """Main entry point — retrieve and compress conversation context.

    Strategy:
    1. Last N raw messages (chronological, unfiltered) — ALWAYS included
    2. FTS5 search past messages by keyword relevance (supplement)
    3. FTS5 search saved notes (supplement, lowest priority)
    4. Compact to fit token budget
    """
    # Layer 1: Recent messages (chronological, raw, unfiltered)
    recent = await get_recent_messages(chat_id)

    # Layer 2: FTS5 on past messages + notes
    keywords = _extract_keywords(message_text)
    fts_msgs = await search_fts_messages(chat_id, keywords) if keywords else []
    fts_notes = await search_notes(chat_id, keywords) if keywords else []

    # ── Combine: recent messages first, FTS5 fills remaining space ──
    seen_texts = set()
    selected_parts = []

    # Priority 1: Recent messages (chronological order maintained)
    for msg in recent:
        key = msg[:80]
        if key not in seen_texts:
            seen_texts.add(key)
            selected_parts.append(msg)

    # Priority 2: FTS5-matched messages (supplement, skip if duplicate)
    for m in fts_msgs:
        key = m["text"][:80]
        if key not in seen_texts:
            seen_texts.add(key)
            label = "You" if m["type"] == "user" else "Bot"
            selected_parts.append(f"[{m['time']}] {label}: {m['text']}")

    # Priority 3: Notes (lowest priority)
    for n in fts_notes:
        key = n["text"][:80]
        if key not in seen_texts:
            seen_texts.add(key)
            selected_parts.append(f"[Note #{n['id']}, {n['time']}]: {n['text']}")

    if not selected_parts:
        return ""

    # ── Compact to fit budget ──
    combined = "\n\n".join(selected_parts)

    if len(combined) <= max_chars:
        return combined

    # Overflow: drop oldest messages until it fits
    parts = selected_parts
    while len(parts) > 1 and len("\n\n".join(parts)) > max_chars:
        parts = parts[1:]  # drop oldest

    result = "\n\n".join(parts)
    if len(result) > max_chars:
        result = result[: max_chars - 100] + "\n\n[context truncated...]"

    return result
