import json
import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.database import get_db

logger = logging.getLogger(__name__)

WIB = timezone(timedelta(hours=7))

scheduler = AsyncIOScheduler()


def _mins_until(dt: datetime) -> int:
    """Calculate remaining minutes from now until dt. Clamped to 0."""
    diff = (dt - datetime.now(timezone.utc)).total_seconds()
    return max(0, int(diff // 60))


def _fmt_time(dt: datetime) -> str:
    """Format a datetime to readable WIB time."""
    local = dt.astimezone(WIB)
    return local.strftime("%a, %d %b %Y at %H:%M")


async def _check_reminders() -> None:
    """Fire due reminders + alerts.
    
    Runs every 5 minutes. Uses actual remaining time in messages
    so even if a reminder fires a few minutes late, the message
    shows accurate "X minutes to go" instead of a stale label.
    """
    try:
        db = await get_db()
        now = datetime.now(timezone.utc)

        # Only load reminders due within the next 2 hours
        # (prevents scanning 100s of future reminders every cycle)
        cursor = await db.execute(
            "SELECT id, chat_id, user_id, text, remind_at, alerts, alerts_fired "
            "FROM reminders "
            "WHERE fired = 0 AND remind_at <= datetime('now', '+2 hours') "
            "LIMIT 50",
        )
        rows = await cursor.fetchall()

        for row in rows:
            remind_at = datetime.fromisoformat(row["remind_at"])
            alerts_list: list[int] = json.loads(row["alerts"] or "[10]")
            alerts_fired: int = row["alerts_fired"] or 0
            total_alerts = len(alerts_list)

            # Main reminder
            if now >= remind_at and alerts_fired >= total_alerts:
                await _send(
                    row,
                    f"⏰ *Reminder:* {row['text']}"
                    f"\n📅 _Originally at {_fmt_time(remind_at)}_",
                )
                await db.execute(
                    "UPDATE reminders SET fired = 1 WHERE id = ?", (row["id"],)
                )
                logger.info("Reminder %s fired", row["id"])
                continue

            # Alerts before reminder — use actual remaining time
            for i in range(alerts_fired, total_alerts):
                mins = alerts_list[i]
                alert_time = remind_at - timedelta(minutes=mins)
                if now >= alert_time:
                    actual_min = min(mins, _mins_until(remind_at))
                    if actual_min <= 0:
                        actual_min = 1  # "1min to go" > "0min to go"
                    plural = "s" if actual_min > 1 else ""
                    msg = (
                        f"🔔 *{actual_min} min{plural} to go!*\n\n"
                        f"{row['text']}"
                    )
                    await _send(row, msg)
                    await db.execute(
                        "UPDATE reminders SET alerts_fired = ? WHERE id = ?",
                        (alerts_fired + 1, row["id"]),
                    )
                    logger.info("Reminder %s alert ~%dmin", row["id"], actual_min)
                    break

        # Cleanup: auto-delete reminders fired more than 7 days ago
        cursor2 = await db.execute(
            "DELETE FROM reminders WHERE fired = 1 "
            "AND remind_at < datetime('now', '-7 days')",
        )
        if cursor2.rowcount > 0:
            logger.info("Cleaned up %d expired reminders", cursor2.rowcount)

        await db.commit()
    except Exception as e:
        logger.error("Reminder check failed: %s", e)


async def _send(row, text: str) -> None:
    """Send a Telegram message."""
    import httpx
    from app.config import settings

    url = f"https://api.telegram.org/bot{settings.telegram_token}/sendMessage"
    async with httpx.AsyncClient(timeout=8.0) as client:
        await client.post(
            url,
            json={"chat_id": row["chat_id"], "text": text, "parse_mode": "Markdown"},
        )


async def start_scheduler() -> None:
    """Start the background scheduler."""
    scheduler.add_job(
        _check_reminders,
        "interval",
        minutes=5,
        id="check_reminders",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started (5min interval)")


async def stop_scheduler() -> None:
    """Gracefully stop the scheduler."""
    scheduler.shutdown(wait=False)
    logger.info("Scheduler stopped")
