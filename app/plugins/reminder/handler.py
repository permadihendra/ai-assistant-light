import json
import logging
import re
from datetime import datetime, timedelta, timezone

from app.database import get_db
from app.plugins.base import BotContext, Plugin

logger = logging.getLogger(__name__)

WIB = timezone(timedelta(hours=7))
MAX_ACTIVE_PER_CHAT = 20

# Regex patterns for time parsing — English + Indonesian
PATTERNS = [
    # ── Seconds / Minutes / Hours ──
    (r"^(\d+)s$", "seconds"),
    (r"^(\d+)m$", "minutes"),
    (r"^(\d+)h$", "hours"),
    (r"^(in|dalam|nanti)\s+(\d+)\s*(s|seconds?|detik)$", "in_seconds"),
    (r"^(in|dalam|nanti)\s+(\d+)\s*(m|minutes?|menit)$", "in_minutes"),
    (r"^(in|dalam|nanti)\s+(\d+)\s*(h|hours?|jam)$", "in_hours"),
    (r"^(\d+)\s*(jam|menit|detik)\s*(lagi)?$", "in_dur_id"),
    # ── Today / Now ──
    (r"^today(?:\s+(\d{1,2}):(\d{2}))?$", "today"),
    (r"^(?:hari\s+)?ini(?:\s+(\d{1,2})[:\.]?(\d{2}))?$", "today"),
    (r"^now$", "now"),
    (r"^sekarang$", "now"),
    # ── Tomorrow / Besok / Lusa ──
    (r"^tomorrow\s+(\d{1,2}):(\d{2})$", "tomorrow"),
    (r"^besok(?:\s+(\d{1,2})[:\.]?(\d{2}))?$", "tomorrow"),
    (r"^lusa(?:\s+(\d{1,2})[:\.]?(\d{2}))?$", "day_after"),
    # ── Day names ──
    (r"^(next\s+)?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)(?:\s+(\d{1,2}):(\d{2}))?$", "weekday"),
    (r"^(senin|selasa|rabu|kamis|jumat|sabtu|minggu)(?:\s+(depan))?(?:\s+(\d{1,2})[:\.]?(\d{2}))?$", "weekday_id"),
    # ── Specific dates ──
    (r"^(\d{4}-\d{2}-\d{2})\s+(\d{1,2}):(\d{2})$", "date"),
    (r"^(\d{2})/(\d{2})/(\d{4})\s+(\d{1,2})[:\.]?(\d{2})$", "ddmmyyyy"),
    # ── Just hour:minute (replies to 'Jam berapa?' prompts) ──
    (r"^(\d{1,2})[:\.](\d{2})$", "hourmin"),
    (r"^(\d{1,2})\s*(am|pm)$", "hour_am"),
]


def _parse_time(text: str) -> datetime | None:
    """Parse a time string into a UTC datetime."""
    text = text.strip().lower()
    for pattern, kind in PATTERNS:
        match = re.match(pattern, text)
        if not match:
            continue
        now = datetime.now(timezone.utc)
        if kind == "seconds":
            return now + timedelta(seconds=int(match.group(1)))
        elif kind == "minutes":
            return now + timedelta(minutes=int(match.group(1)))
        elif kind == "hours":
            return now + timedelta(hours=int(match.group(1)))
        elif kind == "tomorrow":
            # Default to 09:00 WIB if hour not specified (e.g. 'besok' without time)
            h = int(match.group(1)) if match.group(1) else 9
            m = int(match.group(2)) if match.group(2) else 0
            dt = datetime.now(WIB).replace(hour=h, minute=m, second=0, microsecond=0)
            dt += timedelta(days=1)
            return dt.astimezone(timezone.utc)
        elif kind == "date":
            date_str = match.group(1)
            h, m = int(match.group(2)), int(match.group(3))
            dt = datetime.strptime(date_str, "%Y-%m-%d").replace(hour=h, minute=m, tzinfo=WIB)
            return dt.astimezone(timezone.utc)
        elif kind == "today":
            now = datetime.now(WIB)
            if match.group(1) and match.group(2):
                h, m = int(match.group(1)), int(match.group(2))
            else:
                h, m = max(now.hour + 1, 9), 0  # next hour, at least 9AM
                if h >= 24:
                    h = 23
            dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
            return dt.astimezone(timezone.utc)
        elif kind == "now":
            return datetime.now(timezone.utc) + timedelta(minutes=1)
        elif kind == "day_after":
            dt = datetime.now(WIB) + timedelta(days=2)
            if match.group(1) and match.group(2):
                h, m = int(match.group(1)), int(match.group(2))
                dt = dt.replace(hour=h, minute=m, second=0, microsecond=0)
            return dt.astimezone(timezone.utc)
        elif kind == "ddmmyyyy":
            d, mo, y, h, mi = int(match.group(1)), int(match.group(2)), int(match.group(3)), int(match.group(4)), int(match.group(5))
            dt = datetime(y, mo, d, h, mi, tzinfo=WIB)
            return dt.astimezone(timezone.utc)
        elif kind == "hourmin":
            h, mi = int(match.group(1)), int(match.group(2))
            now = datetime.now(WIB)
            dt = now.replace(hour=h, minute=mi, second=0, microsecond=0)
            # If time already passed today, assume tomorrow
            if dt <= now:
                dt += timedelta(days=1)
            return dt.astimezone(timezone.utc)
        elif kind == "hour_am":
            h = int(match.group(1))
            if match.group(2).lower() == "pm" and h < 12:
                h += 12
            if match.group(2).lower() == "am" and h == 12:
                h = 0
            now = datetime.now(WIB)
            dt = now.replace(hour=h, minute=0, second=0, microsecond=0)
            if dt <= now:
                dt += timedelta(days=1)
            return dt.astimezone(timezone.utc)
        elif kind in ("in_seconds", "in_minutes", "in_hours"):
            val = int(match.group(2))
            if kind == "in_seconds":
                return now + timedelta(seconds=val)
            elif kind == "in_minutes":
                return now + timedelta(minutes=val)
            else:
                return now + timedelta(hours=val)
        elif kind == "in_dur_id":
            val = int(match.group(1))
            unit = match.group(2)
            if "detik" in unit:
                return now + timedelta(seconds=val)
            elif "menit" in unit:
                return now + timedelta(minutes=val)
            else:
                return now + timedelta(hours=val)
        elif kind == "weekday":
            day_name = match.group(2).lower()
            is_next = bool(match.group(1))
            days = ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"]
            target = days.index(day_name)
            now_wib = datetime.now(WIB)
            diff = target - now_wib.weekday()
            if diff <= 0 or is_next:
                diff += 7
            dt = now_wib + timedelta(days=diff)
            h = int(match.group(3)) if match.group(3) else 9
            m = int(match.group(4)) if match.group(4) else 0
            dt = dt.replace(hour=h, minute=m, second=0, microsecond=0)
            return dt.astimezone(timezone.utc)
        elif kind == "weekday_id":
            id_days = ["senin","selasa","rabu","kamis","jumat","sabtu","minggu"]
            target = id_days.index(match.group(1).lower())
            is_next = bool(match.group(2))
            now_wib = datetime.now(WIB)
            diff = target - now_wib.weekday()
            if diff <= 0 or is_next:
                diff += 7
            dt = now_wib + timedelta(days=diff)
            h = int(match.group(3)) if match.group(3) else 9
            m = int(match.group(4)) if match.group(4) else 0
            dt = dt.replace(hour=h, minute=m, second=0, microsecond=0)
            return dt.astimezone(timezone.utc)
    return None


def _fmt_time(dt: datetime) -> str:
    """Format a datetime to compact WIB time."""
    local = dt.astimezone(WIB)
    return local.strftime("%a %d %b · %H:%M WIB")


class ReminderPlugin(Plugin):
    name = "reminder"
    commands = ["remind", "reminders", "cancel"]
    description = "Set, list, and cancel reminders"

    async def handle(self, ctx: BotContext) -> str | None:
        text = ctx.message_text.strip()
        if text.startswith("/reminders"):
            return await self._list_reminders(ctx)
        if text.startswith("/cancel "):
            return await self._cancel_reminder(ctx)
        if text.startswith("/remind "):
            return await self._set_reminder(ctx)
        return None

    # ── CREATE via /remind ────────────────────────────────────────

    async def _set_reminder(self, ctx: BotContext) -> str:
        rest = ctx.message_text[len("/remind "):].strip()
        if not rest:
            return "❓ Usage: `/remind 10m buy milk`"

        parts = rest.split(maxsplit=1)
        if len(parts) < 2:
            return "❓ Usage: `/remind 10m buy milk`"

        time_str, message = parts
        remind_at = _parse_time(time_str)
        if remind_at is None:
            return "❌ Could not parse time. Use `30s`, `10m`, `2h`, `tomorrow 09:00`, or `2026-06-01 08:00`."
        if remind_at < datetime.now(timezone.utc):
            return "❌ Time must be in the future."

        db = await get_db()
        if await self._over_limit(db, ctx.chat_id):
            return f"⚠️ Max {MAX_ACTIVE_PER_CHAT} active reminders per chat."

        c = await db.execute(
            "INSERT INTO reminders (chat_id, user_id, text, remind_at, alerts) VALUES (?,?,?,?,?)",
            (ctx.chat_id, ctx.user_id, message, remind_at.strftime('%Y-%m-%d %H:%M:%S'), "[10]"),
        )
        rid = c.lastrowid
        await db.commit()

        return f"✅ Reminder #{rid}\n{message}\n⏰ {_fmt_time(remind_at)}"

    # ── CREATE via BrainPlugin (inserts source_text) ──────────────

    async def create_reminder(
        self, chat_id: int, user_id: int, text: str, remind_at: datetime,
        alerts: list[int] | None = None, source_text: str = "",
    ) -> str:
        if remind_at < datetime.now(timezone.utc):
            return "❌ Time must be in the future."

        db = await get_db()
        if await self._over_limit(db, chat_id):
            return f"⚠️ Max {MAX_ACTIVE_PER_CHAT} active reminders per chat."

        alerts_json = json.dumps(alerts or [10])
        c = await db.execute(
            "INSERT INTO reminders (chat_id, user_id, text, remind_at, alerts, source_text) VALUES (?,?,?,?,?,?)",
            (chat_id, user_id, text, remind_at.strftime('%Y-%m-%d %H:%M:%S'), alerts_json, source_text),
        )
        rid = c.lastrowid
        await db.commit()

        return f"✅ Reminder #{rid}\n{text}\n⏰ {_fmt_time(remind_at)}\n📎 /note {rid} for source"

    # ── LIST ──────────────────────────────────────────────────────

    async def _list_reminders(self, ctx: BotContext) -> str:
        db = await get_db()
        cursor = await db.execute(
            "SELECT id, text, remind_at FROM reminders "
            "WHERE chat_id = ? AND fired = 0 ORDER BY remind_at ASC",
            (ctx.chat_id,),
        )
        rows = await cursor.fetchall()

        if not rows:
            return "📭 No reminders"

        sep = "─" * 20
        blocks = []
        for r in rows:
            dt = datetime.fromisoformat(r["remind_at"])
            local = dt.astimezone(WIB)
            time_str = local.strftime("%a %d %b · %H:%M WIB")
            preview = r["text"]
            blocks.append(
                f"#{r['id']}  {preview}\n"
                f"  ⏰ {time_str}"
            )

        header = "📋 Reminders"
        hint = "/cancel <id> to remove"
        body = f"\n{sep}\n".join(blocks)

        return f"{header}\n{hint}\n{body}"

    # ── CANCEL ────────────────────────────────────────────────────

    async def _cancel_reminder(self, ctx: BotContext) -> str:
        try:
            rid = int(ctx.message_text[len("/cancel "):].strip())
        except (ValueError, IndexError):
            return "❓ Usage: `/cancel <id>`"

        db = await get_db()
        c = await db.execute("SELECT id FROM reminders WHERE id=? AND chat_id=? AND fired=0", (rid, ctx.chat_id))
        if not await c.fetchone():
            return "❌ Reminder not found or already fired."

        await db.execute("DELETE FROM reminders WHERE id=?", (rid,))
        await db.commit()
        return f"✅ Reminder #{rid} cancelled"

    # ── SOURCE (called by NotesPlugin or directly) ────────────────

    async def get_source(self, chat_id: int, reminder_id: int) -> str | None:
        """Return the source_text of a reminder, or None."""
        db = await get_db()
        c = await db.execute(
            "SELECT id, text, remind_at, source_text FROM reminders WHERE id=? AND chat_id=?",
            (reminder_id, chat_id),
        )
        r = await c.fetchone()
        if not r:
            return None

        lines = [f"📌 Reminder #{r['id']}"]
        lines.append(f"⏰ {_fmt_time(datetime.fromisoformat(r['remind_at']))}")
        lines.append(f"{r['text']}")

        src = (r["source_text"] or "").strip()
        if src:
            lines.append("")
            lines.append("*Original message:*")
            lines.append(f"> {src[:1000]}")
        else:
            lines.append("")
            lines.append("_No source message saved._")

        return "\n".join(lines)

    # ── HELPERS ───────────────────────────────────────────────────

    async def _over_limit(self, db, chat_id: int) -> bool:
        c = await db.execute("SELECT COUNT(*) FROM reminders WHERE chat_id=? AND fired=0", (chat_id,))
        r = await c.fetchone()
        return r and r[0] >= MAX_ACTIVE_PER_CHAT
