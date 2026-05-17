import json
import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.database import get_db

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def _check_reminders() -> None:
    """Fire due reminders + single alerts (default 10min before)."""
    try:
        db = await get_db()
        now = datetime.now(timezone.utc)

        cursor = await db.execute(
            "SELECT id, chat_id, user_id, text, remind_at, alerts, alerts_fired "
            "FROM reminders WHERE fired = 0",
        )
        rows = await cursor.fetchall()

        for row in rows:
            remind_at = datetime.fromisoformat(row["remind_at"])
            alerts_list: list[int] = json.loads(row["alerts"] or "[10]")
            alerts_fired: int = row["alerts_fired"] or 0
            total_alerts = len(alerts_list)

            # Main reminder
            if now >= remind_at and alerts_fired >= total_alerts:
                await _send(row, f"⏰ *Reminder:* {row['text']}")
                await db.execute(
                    "UPDATE reminders SET fired = 1 WHERE id = ?", (row["id"],)
                )
                logger.info("Reminder %s fired", row["id"])
                continue

            # Single alert before
            for i in range(alerts_fired, total_alerts):
                mins = alerts_list[i]
                alert_time = remind_at - timedelta(minutes=mins)
                if now >= alert_time:
                    msg = f"🔔 *{mins}min to go!*\n\n{row['text']}"
                    await _send(row, msg)
                    await db.execute(
                        "UPDATE reminders SET alerts_fired = ? WHERE id = ?",
                        (alerts_fired + 1, row["id"]),
                    )
                    logger.info("Reminder %s alert %dmin", row["id"], mins)
                    break

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
        seconds=30,
        id="check_reminders",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started (30s interval)")


async def stop_scheduler() -> None:
    """Gracefully stop the scheduler."""
    scheduler.shutdown(wait=False)
    logger.info("Scheduler stopped")
