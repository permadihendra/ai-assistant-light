"""AgendaPlugin — daily agenda view over reminders table.

Agenda is a UI/UX layer over the same reminders table.
No separate storage. Reminders.fire = status:
  - fired=0: reminder pending (not yet fired by scheduler)
  - fired=1: reminder fired OR marked done by user

Agenda shows ALL items for a date, with visual ☐/☑ markers.
"""

import logging
from datetime import datetime, timedelta, timezone

from app.database import get_db
from app.plugins.base import BotContext, Plugin

logger = logging.getLogger(__name__)

WIB = timezone(timedelta(hours=7))
_SEP = "━" * 20


def _fmt_date(dt: datetime) -> str:
    """Format date with day name."""
    return dt.astimezone(WIB).strftime("%a %d %b %Y")


def _fmt_time_short(dt: datetime) -> str:
    """Format time as HH:MM WIB."""
    return dt.astimezone(WIB).strftime("%H:%M")


def _agenda_date(dt: datetime) -> str:
    """Get SQLite-compatible date string YYYY-MM-DD."""
    return dt.astimezone(WIB).strftime("%Y-%m-%d")


async def _query_agenda(chat_id: int, date_str: str) -> list[dict]:
    """Get ALL agenda items for a date, including done ones.
    
    Returns items with fired status so caller can show ☐/☑.
    """
    db = await get_db()
    cursor = await db.execute(
        "SELECT id, text, remind_at, fired FROM reminders "
        "WHERE chat_id = ? AND DATE(remind_at) = ? "
        "ORDER BY remind_at ASC",
        (chat_id, date_str),
    )
    rows = await cursor.fetchall()
    result = []
    for r in rows:
        dt = datetime.fromisoformat(r["remind_at"])
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        result.append({
            "id": r["id"],
            "text": r["text"],
            "time": _fmt_time_short(dt),
            "done": bool(r["fired"]),
        })
    return result


def _build_agenda_report(
    title: str,
    date_label: str,
    items: list[dict],
    is_today: bool = True,
) -> str:
    """Build formatted agenda report with ☐/☑ markers."""
    lines = [f"📋 {title}", _SEP, date_label, ""]

    if not items:
        lines.append("📭 No items" if is_today else "📭 Nothing scheduled")
        lines.append(_SEP)
        return "\n".join(lines)

    active_count = 0
    done_count = 0
    for item in items:
        if item.get("done"):
            done_count += 1
            lines.append(f"  ☑ {item['time']}  {item['text']}")
        else:
            active_count += 1
            lines.append(f"  ☐ {item['time']}  {item['text']}")

    total = active_count + done_count
    lines.append("")
    lines.append(_SEP)
    lines.append(f"📌 {total} items · {done_count} done")

    return "\n".join(lines)


async def _mark_done(chat_id: int, reminder_id: int) -> bool:
    """Mark a single agenda item as done. Returns True if found and marked."""
    db = await get_db()
    cursor = await db.execute(
        "UPDATE reminders SET fired = 1 WHERE id = ? AND chat_id = ? AND fired = 0",
        (reminder_id, chat_id),
    )
    await db.commit()
    return cursor.rowcount > 0


async def _mark_all_done(chat_id: int, date_str: str) -> int:
    """Mark all active items for a date as done. Returns count marked."""
    db = await get_db()
    cursor = await db.execute(
        "UPDATE reminders SET fired = 1 WHERE chat_id = ? AND fired = 0 AND DATE(remind_at) = ?",
        (chat_id, date_str),
    )
    await db.commit()
    return cursor.rowcount


async def _get_agenda_item(chat_id: int, reminder_id: int) -> dict | None:
    """Get a single agenda item details."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT id, text, remind_at, fired FROM reminders WHERE id = ? AND chat_id = ?",
        (reminder_id, chat_id),
    )
    return await cursor.fetchone()


async def _cleanup_past(chat_id: int) -> int:
    """Mark all items before today as done. Returns count."""
    today = _agenda_date(datetime.now(WIB))
    db = await get_db()
    cursor = await db.execute(
        "UPDATE reminders SET fired = 1 WHERE chat_id = ? AND fired = 0 AND DATE(remind_at) < ?",
        (chat_id, today),
    )
    await db.commit()
    return cursor.rowcount


async def _send_telegram(chat_id: int, text: str) -> None:
    """Send Telegram message via API."""
    import httpx
    from app.config import settings

    url = f"https://api.telegram.org/bot{settings.telegram_token}/sendMessage"
    async with httpx.AsyncClient(timeout=8.0) as client:
        await client.post(
            url,
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
        )


# ── Send functions for scheduler ─────────────────────────

async def send_today_agenda() -> None:
    """Send today's agenda to all active chats (called by scheduler at 06:00)."""
    chats = await _get_active_chats()
    for chat_id in chats:
        try:
            await _cleanup_past(chat_id)
            report = await get_today_agenda(chat_id)
            if report:
                await _send_telegram(chat_id, report)
            logger.info("Today's agenda sent to %s", chat_id)
        except Exception as e:
            logger.error("Failed to send today's agenda to %s: %s", chat_id, e)


async def send_tomorrow_agenda() -> None:
    """Send tomorrow's agenda to all active chats (called by scheduler at 16:00)."""
    chats = await _get_active_chats()
    for chat_id in chats:
        try:
            report = await get_tomorrow_agenda(chat_id)
            if report:
                await _send_telegram(chat_id, report)
            logger.info("Tomorrow's agenda sent to %s", chat_id)
        except Exception as e:
            logger.error("Failed to send tomorrow's agenda to %s: %s", chat_id, e)


async def _get_active_chats() -> set[int]:
    """Get chat IDs with active reminders."""
    db = await get_db()
    cursor = await db.execute("SELECT DISTINCT chat_id FROM reminders WHERE fired = 0")
    return {r["chat_id"] for r in await cursor.fetchall()}


# ── Public query functions (used by handler + scheduler) ──

async def get_today_agenda(chat_id: int) -> str | None:
    """Get today's agenda report."""
    now = datetime.now(WIB)
    today_str = _agenda_date(now)
    items = await _query_agenda(chat_id, today_str)
    return _build_agenda_report(
        "Today's Agenda",
        _fmt_date(now),
        items,
        is_today=True,
    )


async def get_tomorrow_agenda(chat_id: int) -> str | None:
    """Get tomorrow's agenda report."""
    now = datetime.now(WIB)
    tomorrow = now + timedelta(days=1)
    tomorrow_str = _agenda_date(tomorrow)
    items = await _query_agenda(chat_id, tomorrow_str)
    return _build_agenda_report(
        "Tomorrow's Agenda",
        _fmt_date(tomorrow),
        items,
        is_today=False,
    )


async def get_all_agenda(chat_id: int) -> str | None:
    """Get all future agenda (including done) grouped by date."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT id, text, remind_at, fired FROM reminders "
        "WHERE chat_id = ? AND remind_at >= datetime('now') "
        "ORDER BY remind_at ASC LIMIT 50",
        (chat_id,),
    )
    rows = await cursor.fetchall()

    if not rows:
        return "📭 No upcoming agenda."

    # Group by date
    from collections import defaultdict
    by_date = defaultdict(list)

    for r in rows:
        dt = datetime.fromisoformat(r["remind_at"])
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        date_key = _agenda_date(dt)
        by_date[date_key].append({
            "id": r["id"],
            "text": r["text"],
            "time": _fmt_time_short(dt),
            "datetime": dt,
            "done": bool(r["fired"]),
        })

    lines = ["📋 All Agenda", _SEP, ""]
    total = 0
    done_total = 0

    for date_key in sorted(by_date.keys()):
        items = by_date[date_key]
        dt = items[0]["datetime"]
        day_label = _fmt_date(dt)
        # Mark today/tomorrow
        now = datetime.now(WIB)
        today_key = _agenda_date(now)
        tomorrow_key = _agenda_date(now + timedelta(days=1))
        if date_key == today_key:
            day_label = f"📌 Today ({day_label})"
        elif date_key == tomorrow_key:
            day_label = f"⏰ Tomorrow ({day_label})"

        lines.append(day_label)
        for item in items:
            total += 1
            if item["done"]:
                done_total += 1
                lines.append(f"  ☑ {item['time']}  {item['text']}")
            else:
                lines.append(f"  ☐ {item['time']}  {item['text']}")
        lines.append("")

    active = total - done_total
    lines.append(_SEP)
    lines.append(f"📌 {total} items · {done_total} done")
    return "\n".join(lines)


async def mark_done_by_id(chat_id: int, reminder_id: int) -> str:
    """Mark an agenda item as done. Returns status message."""
    item = await _get_agenda_item(chat_id, reminder_id)
    if not item:
        return "❌ Agenda item not found or already done."
    if item["fired"]:
        return f"☑️ Item `{reminder_id}` already done."

    ok = await _mark_done(chat_id, reminder_id)
    return f"☑️ Agenda #{reminder_id} done" if ok else "❌ Could not mark done."


async def mark_done_all_today(chat_id: int) -> str:
    """Mark all today's items as done."""
    now = datetime.now(WIB)
    today_str = _agenda_date(now)
    count = await _mark_all_done(chat_id, today_str)
    return f"☑️ All {count} done" if count > 0 else "📭 No active items today."


# ── Plugin class ────────────────────────────────────────

class AgendaPlugin(Plugin):
    name = "agenda"
    commands = ["agenda", "done"]
    description = "Daily agenda — manage today, tomorrow, and all upcoming items"

    async def on_load(self) -> None:
        logger.info("AgendaPlugin loaded")

    async def handle(self, ctx: BotContext) -> str | None:
        text = ctx.message_text.strip()

        if text.startswith("/done all"):
            return await mark_done_all_today(ctx.chat_id)

        if text.startswith("/done "):
            try:
                rid = int(text[len("/done "):].strip())
                return await mark_done_by_id(ctx.chat_id, rid)
            except ValueError:
                # Not a number — try text search via FTS5
                return await self._done_by_text(ctx.chat_id, text[len("/done "):].strip())

        if text.startswith("/agenda all"):
            return await get_all_agenda(ctx.chat_id)

        if text.startswith("/agenda tomorrow"):
            return await get_tomorrow_agenda(ctx.chat_id)

        if text.startswith("/agenda today") or text.startswith("/agenda"):
            return await get_today_agenda(ctx.chat_id)

        return None

    async def _done_by_text(self, chat_id: int, search_text: str) -> str:
        """Mark done by matching text pattern via FTS5."""
        from app.plugins.brain.context import _extract_keywords
        keywords = _extract_keywords(search_text)
        if keywords:
            # Trigger cleanup of past items first
            cleaned = await _cleanup_past(chat_id)
            if cleaned:
                logger.info("Cleaned %d past items before text search", cleaned)
        return "❓ Could not find matching item. Use `/agenda` to see active items and `/done <id>` to mark."

    async def save_items(
        self,
        chat_id: int,
        user_id: int,
        date_str: str,
        items: list[dict],
        alerts: list[int] | None = None,
    ) -> str:
        """Save agenda items as reminders. Called by BrainPlugin."""
        from app.plugins.reminder.handler import ReminderPlugin
        from app.plugins.base import PluginRegistry

        plugin = PluginRegistry.get().get_plugin("reminder")
        if not isinstance(plugin, ReminderPlugin):
            return "❌ Reminder plugin not available."

        saved = 0
        errors = []
        for item in items:
            time_str = item.get("time", "09:00")
            text = item.get("text", "").strip()
            if not text:
                continue

            # Combine date + time → remind_at
            remind_at_str = f"{date_str} {time_str}:00"
            from datetime import datetime as dt
            try:
                remind_at = dt.strptime(remind_at_str, "%Y-%m-%d %H:%M:%S")
                remind_at = remind_at.replace(tzinfo=WIB).astimezone(timezone.utc)
            except ValueError:
                errors.append(f"Invalid time: {time_str}")
                continue

            result = await plugin.create_reminder(
                chat_id=chat_id,
                user_id=user_id,
                text=text,
                remind_at=remind_at,
                alerts=alerts or [10],
                source_text=text,
            )
            if result and "✅" in result:
                saved += 1
            else:
                errors.append(text)

        if saved == 0:
            return "❌ Failed to save agenda."

        msg = f"✅ *{saved} agenda item{'s' if saved > 1 else ''} saved!*"
        if errors:
            msg += f"\n⚠️ {len(errors)} item{'s' if len(errors) > 1 else ''} failed"
        return msg
