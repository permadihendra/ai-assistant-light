import logging
import re
from datetime import datetime, timedelta, timezone

from app.database import get_db
from app.plugins.base import BotContext, Plugin

logger = logging.getLogger(__name__)

WIB = timezone(timedelta(hours=7))
MAX_ACTIVE_PER_CHAT = 20

# Regex patterns for time parsing
PATTERNS = [
    (r"^(\d+)s$", "seconds"),
    (r"^(\d+)m$", "minutes"),
    (r"^(\d+)h$", "hours"),
    (r"^tomorrow\s+(\d{1,2}):(\d{2})$", "tomorrow"),
    (r"^(\d{4}-\d{2}-\d{2})\s+(\d{1,2}):(\d{2})$", "date"),
    (r"^today(?:\s+(\d{1,2}):(\d{2}))?$", "today"),
    (r"^now$", "now"),
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
            h, m = int(match.group(1)), int(match.group(2))
            dt = datetime.now(WIB).replace(hour=h, minute=m, second=0, microsecond=0)
            dt += timedelta(days=1)
            return dt.astimezone(timezone.utc)
        elif kind == "date":
            date_str = match.group(1)
            h, m = int(match.group(2)), int(match.group(3))
            dt = datetime.strptime(date_str, "%Y-%m-%d").replace(
                hour=h, minute=m, tzinfo=WIB
            )
            return dt.astimezone(timezone.utc)
        elif kind == "today":
            now = datetime.now(WIB)
            if match.group(1) and match.group(2):
                h, m = int(match.group(1)), int(match.group(2))
            else:
                # Default to next hour
                h, m = now.hour + 1, 0
                if h >= 24:
                    h = 23
            dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
            return dt.astimezone(timezone.utc)
        elif kind == "now":
            return datetime.now(timezone.utc) + timedelta(minutes=1)

    return None


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

    async def _set_reminder(self, ctx: BotContext) -> str:
        # Parse: /remind <time> <message>
        rest = ctx.message_text[len("/remind "):].strip()
        if not rest:
            return "❓ Usage: `/remind 10m buy milk` or `/remind tomorrow 09:00 meeting`"

        # Split on first space to separate time from message
        parts = rest.split(maxsplit=1)
        if len(parts) < 2:
            return "❓ Usage: `/remind 10m buy milk`"

        time_str, message = parts
        remind_at = _parse_time(time_str)

        if remind_at is None:
            return (
                "❌ Could not parse time. Use formats:\n"
                "• `30s`, `10m`, `2h`\n"
                "• `tomorrow 09:00`\n"
                "• `2026-06-01 08:00`"
            )

        if remind_at < datetime.now(timezone.utc):
            return "❌ Time must be in the future."

        db = await get_db()

        # Check max active reminders per chat
        cursor = await db.execute(
            "SELECT COUNT(*) FROM reminders WHERE chat_id = ? AND fired = 0",
            (ctx.chat_id,),
        )
        row = await cursor.fetchone()
        if row and row[0] >= MAX_ACTIVE_PER_CHAT:
            return f"⚠️ Maximum {MAX_ACTIVE_PER_CHAT} active reminders per chat."

        cursor = await db.execute(
            "INSERT INTO reminders (chat_id, user_id, text, remind_at, alerts) VALUES (?, ?, ?, ?, ?)",
            (ctx.chat_id, ctx.user_id, message, remind_at.isoformat(), "[10]"),
        )
        reminder_id = cursor.lastrowid
        await db.commit()

        local_time = remind_at.astimezone(WIB)
        time_str = local_time.strftime("%A, %d %b %Y at %H:%M")

        return (
            f"✅ *Reminder #{reminder_id} set!*\n"
            f"📋 {message}\n"
            f"⏰ {time_str}\n"
            f"🔔 10min before"
        )

    async def create_reminder(
        self, chat_id: int, user_id: int, text: str, remind_at: datetime, alerts: list[int] | None = None
    ) -> str:
        """Direct API for BrainPlugin — skips command parsing. Returns reminder ID."""
        import json

        if remind_at < datetime.now(timezone.utc):
            return "❌ Time must be in the future."

        db = await get_db()
        cursor = await db.execute(
            "SELECT COUNT(*) FROM reminders WHERE chat_id = ? AND fired = 0",
            (chat_id,),
        )
        row = await cursor.fetchone()
        if row and row[0] >= MAX_ACTIVE_PER_CHAT:
            return f"⚠️ Maximum {MAX_ACTIVE_PER_CHAT} active reminders per chat."

        alerts_json = json.dumps(alerts or [10])
        cursor = await db.execute(
            "INSERT INTO reminders (chat_id, user_id, text, remind_at, alerts) VALUES (?, ?, ?, ?, ?)",
            (chat_id, user_id, text, remind_at.isoformat(), alerts_json),
        )
        reminder_id = cursor.lastrowid
        await db.commit()

        # Format time nicely
        local_time = remind_at.astimezone(WIB)
        time_str = local_time.strftime("%A, %d %b %Y at %H:%M")

        alert_str = ""
        if alerts:
            alert_str = "\n🔔 " + " + ".join(f"{m}min before" for m in alerts)

        return (
            f"✅ *Reminder #{reminder_id} set!*\n"
            f"📋 {text}\n"
            f"⏰ {time_str}{alert_str}"
        )

    async def _list_reminders(self, ctx: BotContext) -> str:
        db = await get_db()
        cursor = await db.execute(
            "SELECT id, text, remind_at FROM reminders "
            "WHERE chat_id = ? AND fired = 0 ORDER BY remind_at ASC",
            (ctx.chat_id,),
        )
        rows = await cursor.fetchall()

        if not rows:
            return "📭 No active reminders."

        lines = ["📋 *Your reminders:*"]
        for row in rows:
            dt = datetime.fromisoformat(row["remind_at"])
            lines.append(
                f"`{row['id']:>3}` — {row['text']} — <t:{int(dt.timestamp())}:R>"
            )

        return "\n".join(lines)

    async def _cancel_reminder(self, ctx: BotContext) -> str:
        try:
            reminder_id = int(ctx.message_text[len("/cancel "):].strip())
        except (ValueError, IndexError):
            return "❓ Usage: `/cancel <id>` — cancel a reminder by ID."

        db = await get_db()
        cursor = await db.execute(
            "SELECT id FROM reminders WHERE id = ? AND chat_id = ? AND fired = 0",
            (reminder_id, ctx.chat_id),
        )
        row = await cursor.fetchone()

        if not row:
            return "❌ Reminder not found or already fired."

        await db.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
        await db.commit()
        return f"✅ Cancelled reminder `{reminder_id}`."
