import json
import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.database import get_db
from app.llm.base import LLMMessage
from app.llm.router import get_provider

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def _check_reminders() -> None:
    """Poll for due reminders and fire alerts + main reminders.

    Each reminder can have multiple alerts (e.g., 15min before, 5min before).
    The scheduler fires each alert when its time is reached, then fires the
    main reminder at remind_at.
    """
    try:
        db = await get_db()
        now = datetime.now(timezone.utc)

        # Get all active reminders
        cursor = await db.execute(
            "SELECT id, chat_id, user_id, text, remind_at, alerts, alerts_fired "
            "FROM reminders WHERE fired = 0",
        )
        rows = await cursor.fetchall()

        for row in rows:
            remind_at = datetime.fromisoformat(row["remind_at"])
            alerts_list: list[int] = json.loads(row["alerts"] or "[15, 5]")
            alerts_fired: int = row["alerts_fired"] or 0
            total_alerts = len(alerts_list)

            # Fire main reminder if past remind_at AND all alerts are done
            if now >= remind_at and alerts_fired >= total_alerts:
                await _fire_reminder(row)
                await db.execute(
                    "UPDATE reminders SET fired = 1 WHERE id = ?", (row["id"],)
                )
                logger.info(
                    "Reminder %s fired (main)", row["id"]
                )
                continue

            # Fire pending alerts
            for i in range(alerts_fired, total_alerts):
                alert_minutes = alerts_list[i]
                alert_time = remind_at - __import__("datetime").timedelta(minutes=alert_minutes)

                if now >= alert_time:
                    await _fire_alert(row, alert_minutes)
                    await db.execute(
                        "UPDATE reminders SET alerts_fired = ? WHERE id = ?",
                        (alerts_fired + 1, row["id"]),
                    )
                    logger.info(
                        "Reminder %s alert %dmin before fired", row["id"], alert_minutes
                    )
                    break  # Fire one alert per poll cycle

        await db.commit()
    except Exception as e:
        logger.error("Reminder check failed: %s", e)


async def _fire_reminder(row) -> None:
    """Send the main reminder notification."""
    import httpx
    from app.config import settings

    url = f"https://api.telegram.org/bot{settings.telegram_token}/sendMessage"

    # Try to generate a fun reminder message using LLM
    try:
        personality = getattr(settings, 'ai_personality', '') or "friendly"
        provider = get_provider()
        response = await provider.chat(
            messages=[
                LLMMessage(
                    role="system",
                    content=(
                        f"Personality: {personality}\n"
                        "Write a short, fun reminder message (max 2 sentences). "
                        "Be playful. Use emojis. The reminder is for: "
                    ),
                ),
                LLMMessage(role="user", content=row["text"]),
            ],
            max_tokens=100,
            timeout=8.0,
        )
        text = f"⏰ *Reminder:*\n{response.text}"
    except Exception:
        text = f"⏰ *Reminder:* {row['text']}"

    async with httpx.AsyncClient(timeout=10.0) as client:
        await client.post(
            url,
            json={"chat_id": row["chat_id"], "text": text, "parse_mode": "Markdown"},
        )


async def _fire_alert(row, minutes_before: int) -> None:
    """Send an alert notification before the main reminder."""
    import httpx
    from app.config import settings

    url = f"https://api.telegram.org/bot{settings.telegram_token}/sendMessage"

    time_str = f"{minutes_before} min" if minutes_before >= 1 else f"{int(minutes_before * 60)} sec"

    texts = {
        15: f"⏳ *15 minutes to go!*\n\n⏰ Reminder coming up: _{row['text']}_\nGet ready! 🏃",
        10: f"🔔 *10 minutes!*\n\nDon't forget: _{row['text']}_\nAlmost time! ⏰",
        5: f"⚡ *5 minutes left!*\n\n⚠️ _{row['text']}_\nBetter get moving! 🚀",
        1: f"🔥 *1 minute!*\n\n🚨 _{row['text']}_ 🚨\nIt's happening NOW!",
    }
    text = texts.get(minutes_before, f"🔔 *{time_str} before:* _{row['text']}_")

    async with httpx.AsyncClient(timeout=10.0) as client:
        await client.post(
            url,
            json={"chat_id": row["chat_id"], "text": text, "parse_mode": "Markdown"},
        )


async def start_scheduler() -> None:
    """Start the APScheduler background scheduler."""
    scheduler.add_job(
        _check_reminders,
        "interval",
        seconds=15,  # Check every 15s for more responsive alerts
        id="check_reminders",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started (15s interval, multi-alert enabled)")


async def stop_scheduler() -> None:
    """Gracefully stop the scheduler."""
    scheduler.shutdown(wait=False)
    logger.info("Scheduler stopped")
