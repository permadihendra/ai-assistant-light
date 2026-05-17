"""
One-time script to register the Telegram bot webhook.

Usage:
    uv run python -m app.bot.setup_webhook
"""

import asyncio
import logging

import httpx

from app.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

WEBHOOK_URL = f"{settings.telegram_webhook_url}/webhook"


async def setup_webhook() -> None:
    """Register the webhook with Telegram."""
    url = f"https://api.telegram.org/bot{settings.telegram_token}/setWebhook"

    payload: dict = {
        "url": WEBHOOK_URL,
        "max_connections": 10,
        "allowed_updates": ["message", "edited_message"],
    }

    if settings.telegram_webhook_secret:
        payload["secret_token"] = settings.telegram_webhook_secret

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(url, json=payload)
        data = resp.json()

        if data.get("ok"):
            logger.info("✅ Webhook registered: %s", WEBHOOK_URL)
            logger.info("Response: %s", data.get("description", ""))
        else:
            logger.error("❌ Failed to set webhook: %s", data.get("description", ""))
            raise SystemExit(1)


async def delete_webhook() -> None:
    """Remove the webhook."""
    url = f"https://api.telegram.org/bot{settings.telegram_token}/deleteWebhook"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url)
        data = resp.json()
        if data.get("ok"):
            logger.info("✅ Webhook deleted")
        else:
            logger.error("❌ Failed to delete webhook: %s", data.get("description", ""))


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--delete":
        asyncio.run(delete_webhook())
    else:
        asyncio.run(setup_webhook())
