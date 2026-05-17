import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.database import get_db

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def _check_reminders() -> None:
    """Poll for due reminders and fire them."""
    try:
        db = await get_db()
        cursor = await db.execute(
            "SELECT id, chat_id, user_id, text, remind_at FROM reminders "
            "WHERE remind_at <= ? AND fired = 0",
            (datetime.now(timezone.utc).isoformat(),),
        )
        rows = await cursor.fetchall()

        for row in rows:
            try:
                await _fire_reminder(row)
                await db.execute(
                    "UPDATE reminders SET fired = 1 WHERE id = ?", (row["id"],)
                )
            except Exception as e:
                logger.error("Failed to fire reminder %s: %s", row["id"], e)

        await db.commit()
    except Exception as e:
        logger.error("Reminder check failed: %s", e)


async def _fire_reminder(row) -> None:
    """Send a reminder notification via Telegram Bot API."""
    import httpx

    from app.config import settings

    url = f"https://api.telegram.org/bot{settings.telegram_token}/sendMessage"
    text = f"⏰ *Reminder:* {row['text']}"

    async with httpx.AsyncClient(timeout=10.0) as client:
        await client.post(
            url,
            json={
                "chat_id": row["chat_id"],
                "text": text,
                "parse_mode": "Markdown",
            },
        )


async def start_scheduler() -> None:
    """Start the APScheduler background scheduler."""
    scheduler.add_job(
        _check_reminders,
        "interval",
        seconds=30,
        id="check_reminders",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started")


async def stop_scheduler() -> None:
    """Gracefully stop the scheduler."""
    scheduler.shutdown(wait=False)
    logger.info("Scheduler stopped")
