"""Context retriever — conversation memory layer for BrainPlugin.

Retrieves and compresses context from multiple sources:
1. Recent user↔bot message pairs (filtered, deduplicated)
2. FTS5 search on past messages by keyword relevance
3. FTS5 search on saved notes

Smart token budgeting: filter noise → pair → prioritize → compact.
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
_MAX_PAIR_CHARS = 400            # max chars per single user/bot message
_MAX_PAIRS = 10                  # max pairs to include
_FTS_MESSAGE_LIMIT = 3
_FTS_NOTE_LIMIT = 2

WIB = timezone(timedelta(hours=7))

# Commands to filter out from context (noise)
_COMMAND_PATTERN = re.compile(r"^/(ping|help|start|status|health|remind|reminders|cancel|notes|note|search|summarize|lastsummary|run)\b")


def _is_noise(text: str) -> bool:
    """Check if a message is noise (commands, very short, test messages)."""
    if not text:
        return True
    t = text.strip()
    if not t:
        return True
    if _COMMAND_PATTERN.match(t):
        return True
    if t.lower() in ("hello", "hi", "test", "hai", "hallo", "hey"):
        return True
    return False


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


def _compact_text(text: str, max_chars: int = _MAX_PAIR_CHARS) -> str:
    """Compact a single message: single line, truncate if needed."""
    # Collapse multiple spaces/newlines into single space
    text = re.sub(r'\s+', ' ', text).strip()
    return _truncate(text, max_chars)


async def get_paired_messages(
    chat_id: int,
    max_pairs: int = _MAX_PAIRS,
) -> list[dict]:
    """Get meaningful user↔bot message pairs, filtering noise.

    Returns chronological pairs, each with user_msg and bot_response.
    Skips commands, short test messages, and unpaired orphans.
    """
    db = await get_db()
    cursor = await db.execute(
        "SELECT id, text, type, username, created_at FROM messages "
        "WHERE chat_id = ? "
        "ORDER BY id DESC LIMIT 200",  # ample window for pairing
        (chat_id,),
    )
    all_rows = list(reversed(await cursor.fetchall()))

    # Step 1: Filter noise but keep meaningful + bot messages
    filtered = []
    for r in all_rows:
        t = r["text"] or ""
        if r["type"] == "bot":
            filtered.append(r)  # always keep bot msgs
        elif not _is_noise(t):
            filtered.append(r)

    if not filtered:
        return []

    # Step 2: Pair user → bot sequences
    pairs = []
    current_pair = {"user": None, "bot": None, "user_time": None, "bot_time": None}

    for r in filtered:
        t = r["text"] or ""
        if r["type"] == "user" or r["type"] == "user":
            if current_pair["user"] is not None and current_pair["bot"] is not None:
                # Complete pair found — save and start new
                pairs.append({
                    "user_msg": current_pair["user"],
                    "bot_msg": current_pair["bot"],
                    "user_time": current_pair["user_time"],
                    "bot_time": current_pair["bot_time"],
                })
                current_pair = {"user": None, "bot": None, "user_time": None, "bot_time": None}
            current_pair["user"] = _compact_text(t)
            current_pair["user_time"] = r["created_at"]
        elif r["type"] == "bot":
            current_pair["bot"] = _compact_text(t)
            current_pair["bot_time"] = r["created_at"]

    # Flush last pair
    if current_pair["user"] is not None and current_pair["bot"] is not None:
        pairs.append({
            "user_msg": current_pair["user"],
            "bot_msg": current_pair["bot"],
            "user_time": current_pair["user_time"],
            "bot_time": current_pair["bot_time"],
        })

    # Take most recent N pairs
    pairs = pairs[-max_pairs:]

    # Format pairs
    result = []
    for p in pairs:
        pair_text = f"User [{_fmt_time(p['user_time'])}]: {p['user_msg']}\nBot [{_fmt_time(p['bot_time'])}]: {p['bot_msg']}"
        result.append(pair_text)

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
    1. Get paired user↔bot messages (filtered, no commands)
    2. FTS5 search past messages by keywords
    3. FTS5 search notes by keywords
    4. Prioritize: FTS5-matched pairs > latest pairs > notes
    5. Compact to fit budget
    """
    # Layer 1: Paired conversation (filtered + deduplicated)
    pairs = await get_paired_messages(chat_id)

    # Layer 2: FTS5 on past messages
    keywords = _extract_keywords(message_text)
    fts_msgs = await search_fts_messages(chat_id, keywords) if keywords else []
    fts_notes = await search_notes(chat_id, keywords) if keywords else []

    # ── Prioritize: FTS5-matched first, then most recent ──
    # Build set of already-included messages to avoid duplication
    seen_texts = set()

    selected_parts = []

    # Priority 1: FTS5-matched messages
    for m in fts_msgs:
        key = m["text"][:80]
        if key not in seen_texts:
            seen_texts.add(key)
            label = "You" if m["type"] == "user" else "Bot"
            selected_parts.append(f"[{m['time']}] {label}: {m['text']}")

    # Priority 2: Recent pairs (skip if already in FTS results)
    for pair in reversed(pairs):
        if len(selected_parts) >= 8:
            break
        # Check if this pair is already included
        pair_key = pair[:80]
        if pair_key not in seen_texts:
            seen_texts.add(pair_key)
            selected_parts.append(pair)

    # Priority 3: Notes
    for n in fts_notes:
        key = n["text"][:80]
        if key not in seen_texts:
            seen_texts.add(key)
            selected_parts.append(f"[Note #{n['id']}, {n['time']}]: {n['text']}")

    if not selected_parts:
        return ""

    # ── Compact to fit budget ───────────────────────────────
    combined = "\n\n".join(selected_parts)

    if len(combined) <= max_chars:
        return combined

    # Overflow: drop oldest items until it fits
    parts = selected_parts
    while len(parts) > 1 and len("\n\n".join(parts)) > max_chars:
        parts = parts[1:]  # drop oldest

    result = "\n\n".join(parts)
    if len(result) > max_chars:
        result = result[: max_chars - 100] + "\n\n[context truncated...]"

    return result
