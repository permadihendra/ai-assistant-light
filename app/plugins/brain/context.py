"""Context retriever — conversation memory layer for BrainPlugin.

Retrieves and compresses context from multiple sources:
1. Recent messages (sliding window)
2. FTS5 search on past messages by keyword relevance
3. FTS5 search on saved notes
4. Recent summaries

Then formats, ranks, and compresses to fit token budget.
Used by BrainPlugin before calling the LLM.
"""

import logging
import re
from datetime import datetime, timedelta, timezone

from app.database import get_db

logger = logging.getLogger(__name__)

# Token budget (rough estimation: ~4 chars = 1 token for English/Indonesian)
_CHARS_PER_TOKEN = 4
_MAX_CONTEXT_TOKENS = 2048
_RECENT_MESSAGE_COUNT = 20
_FTS_MESSAGE_LIMIT = 5
_FTS_NOTE_LIMIT = 3
_TIME_LIMIT_HOURS = 48  # only search messages from last 48h for FTS

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
    """Extract meaningful keywords from user message for FTS5 query.
    
    Strips common stop words and very short terms.
    Returns a space-joined string suitable for FTS5 MATCH.
    """
    if not text:
        return ""

    # Remove markdown, URLs, emojis
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'[*_~`>\#]', '', text)
    text = re.sub(r'[^\w\s]', ' ', text)

    # Tokenize and filter
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

    # FTS5 prefix matching: append * for partial matches
    return ' '.join(f'{w}*' for w in keywords[:8])  # max 8 keywords


async def get_recent_messages(chat_id: int, limit: int = _RECENT_MESSAGE_COUNT) -> list[dict]:
    """Get most recent messages for a chat."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT id, text, username, created_at FROM messages "
        "WHERE chat_id = ? ORDER BY created_at DESC LIMIT ?",
        (chat_id, limit),
    )
    rows = await cursor.fetchall()
    # Return in chronological order
    return [
        {
            "id": r["id"],
            "text": r["text"],
            "username": r["username"] or "User",
            "time": _fmt_time(r["created_at"]),
        }
        for r in reversed(rows)
    ]


async def search_messages(
    chat_id: int,
    keywords: str,
    limit: int = _FTS_MESSAGE_LIMIT,
) -> list[dict]:
    """FTS5 search past messages in this chat by keywords."""
    if not keywords:
        return []

    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id, text, username, created_at FROM messages_fts "
            "WHERE messages_fts MATCH ? AND chat_id = ? "
            "AND created_at >= datetime('now', ?) "
            "ORDER BY rank LIMIT ?",
            (keywords, chat_id, f'-{_TIME_LIMIT_HOURS} hours', limit),
        )
        rows = await cursor.fetchall()
    except Exception as e:
        logger.warning("FTS5 messages search failed (maybe no data yet): %s", e)
        return []

    return [
        {
            "id": r["id"],
            "text": r["text"],
            "username": r["username"] or "User",
            "time": _fmt_time(r["created_at"]),
        }
        for r in rows
    ]


async def search_notes(
    chat_id: int,
    keywords: str,
    limit: int = _FTS_NOTE_LIMIT,
) -> list[dict]:
    """FTS5 search saved notes by keywords."""
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
        logger.warning("FTS5 notes search failed (maybe no data yet): %s", e)
        return []

    return [
        {
            "id": r["id"],
            "text": r["text"],
            "time": _fmt_time(r["created_at"]),
        }
        for r in rows
    ]


async def get_recent_summary(chat_id: int) -> str | None:
    """Get the most recent summary for this chat."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT summary, created_at FROM summaries "
        "WHERE chat_id = ? ORDER BY created_at DESC LIMIT 1",
        (chat_id,),
    )
    row = await cursor.fetchone()
    if row:
        return f"[Chat summary from {_fmt_time(row['created_at'])}]: {row['summary']}"
    return None


def _truncate_text(text: str, max_chars: int) -> str:
    """Truncate text to max_chars, adding ellipsis if needed."""
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def _compress_context(
    recent_msgs_text: str,
    fts_results_text: str,
    max_tokens: int = _MAX_CONTEXT_TOKENS,
) -> str:
    """Compress context parts to fit within token budget.
    
    Priority: recent messages > FTS results > notes
    If overflow, truncate FTS results first, then oldest recent messages.
    """
    max_chars = max_tokens * _CHARS_PER_TOKEN
    recent_len = len(recent_msgs_text)

    if recent_len + len(fts_results_text) <= max_chars:
        return f"{recent_msgs_text}\n{fts_results_text}" if fts_results_text else recent_msgs_text

    # Need to compress: keep all recent messages, truncate FTS results
    available_for_fts = max_chars - recent_len - 50  # buffer
    if available_for_fts > 100:
        compressed_fts = _truncate_text(fts_results_text, available_for_fts)
    else:
        compressed_fts = ""

    # If recent alone still overflows, truncate oldest messages from recent
    if recent_len > max_chars - 50:
        compressed_recent = _truncate_text(recent_msgs_text, max_chars - 200)
        return compressed_recent + "\n\n[context truncated...]"

    return (
        f"{recent_msgs_text}\n{compressed_fts}" if compressed_fts else recent_msgs_text
    )


async def retrieve_context(
    chat_id: int,
    message_text: str,
    max_tokens: int = _MAX_CONTEXT_TOKENS,
) -> str:
    """Main entry point — retrieve and compress conversation context.
    
    Returns a formatted string suitable for LLM system prompt injection.
    Empty string if no context available.
    """
    # Layer 1: Recent messages (always included)
    recent = await get_recent_messages(chat_id)

    # Layer 2-3: FTS5 search (only if there are keywords)
    keywords = _extract_keywords(message_text)
    fts_msgs = []
    fts_notes = []
    summary = None

    if keywords:
        fts_msgs = await search_messages(chat_id, keywords)
        fts_notes = await search_notes(chat_id, keywords)

    # Layer 4: Summary (include only if many recent messages)
    if len(recent) >= 10:
        summary = await get_recent_summary(chat_id)

    # ── Format recent messages ──────────────────────────
    if recent:
        recent_parts = []
        for msg in recent:
            t = _truncate_text(msg["text"], 200)
            recent_parts.append(f"[{msg['time']}] {msg['username']}: {t}")
        recent_text = "── Recent messages ──\n" + "\n".join(recent_parts)
    else:
        recent_text = ""

    # ── Format FTS results ──────────────────────────────
    fts_parts = []

    # Deduplicate with recent messages
    recent_ids = {m["id"] for m in recent}

    if fts_msgs:
        unique_fts = [m for m in fts_msgs if m["id"] not in recent_ids]
        if unique_fts:
            parts = []
            for m in unique_fts:
                t = _truncate_text(m["text"], 300)
                parts.append(f"[{m['time']}] {m['username']}: {t}")
            fts_parts.append("── Related past messages ──\n" + "\n".join(parts))

    if fts_notes:
        parts = []
        for n in fts_notes:
            t = _truncate_text(n["text"], 300)
            parts.append(f"[Note #{n['id']}, {n['time']}]: {t}")
        fts_parts.append("── From your notes ──\n" + "\n".join(parts))

    if summary:
        fts_parts.append(summary)

    fts_text = "\n\n".join(fts_parts)

    # ── Compress to fit budget ──────────────────────────
    return _compress_context(recent_text, fts_text, max_tokens)
