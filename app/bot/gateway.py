import hmac
import logging

from fastapi import APIRouter, Request, Response
from telegram import Update

from app.bot.dispatcher import dispatch
from app.bot.middlewares import check_rate_limit
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()


async def _send_telegram_message(chat_id: int, text: str) -> None:
    """Send a message via Telegram Bot API using raw httpx."""
    import httpx

    url = f"https://api.telegram.org/bot{settings.telegram_token}/sendMessage"
    async with httpx.AsyncClient(timeout=10.0) as client:
        await client.post(
            url,
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown",
            },
        )


@router.post("/webhook")
async def webhook(request: Request) -> Response:
    """Telegram webhook receiver."""
    body = await request.body()

    # Verify webhook secret if configured
    if settings.telegram_webhook_secret:
        received_token = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not received_token:
            logger.warning("Webhook request missing secret token")
            return Response(status_code=401)
        # Constant-time comparison to prevent timing attacks
        if not hmac.compare_digest(received_token, settings.telegram_webhook_secret):
            logger.warning("Webhook secret token mismatch")
            return Response(status_code=403)

    # Parse update
    try:
        import json

        data = json.loads(body)
        update = Update.de_json(data, None)
    except Exception as e:
        logger.error("Failed to parse Telegram update: %s", e)
        return Response(status_code=200)

    if not update:
        return Response(status_code=200)

    message = update.message or update.edited_message
    if not message or not message.text:
        logger.debug("Received non-text update: %s", update.update_id)
        return Response(status_code=200)

    logger.info(
        "Update %s from chat %s: %s",
        update.update_id,
        message.chat_id,
        message.text[:100],
    )

    # Rate limiting
    if not check_rate_limit(message.chat_id):
        await _send_telegram_message(
            message.chat_id, "⏱ Slow down! You're sending too many requests."
        )
        return Response(status_code=200)

    # Dispatch to plugins
    reply = await dispatch(update)

    if reply:
        try:
            await _send_telegram_message(message.chat_id, reply)
            logger.info("Replied to %s: %.200s", message.chat_id, reply)
        except Exception as e:
            logger.error("Failed to send Telegram message: %s", e)

    return Response(status_code=200)


@router.get("/health")
async def health():
    return {"status": "ok", "provider": settings.llm_provider}
    # Never expose key values here
