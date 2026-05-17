import hmac
import json
import logging

from fastapi import APIRouter, Request, Response
from telegram import Update

from app.bot.dispatcher import dispatch, handle_callback
from app.bot.middlewares import check_rate_limit
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()


async def _send_telegram_message(chat_id: int, text: str, keyboard=None) -> None:
    """Send a message via Telegram Bot API using raw httpx.
    Falls back to plain text if markdown causes 400 error.
    """
    import httpx

    url = f"https://api.telegram.org/bot{settings.telegram_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
    }
    if keyboard:
        payload["reply_markup"] = json.loads(keyboard) if isinstance(keyboard, str) else keyboard

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, json=payload)
        # If markdown fails (400), retry as plain text
        if resp.status_code == 400:
            logger.warning("Markdown send failed, retrying as plain text")
            payload.pop("parse_mode", None)
            resp = await client.post(url, json=payload)
            if resp.status_code != 200:
                logger.error("Plain text send also failed: %s", resp.text)


async def _edit_message_text(chat_id: int, message_id: int, text: str, keyboard=None) -> None:
    """Edit a message's text and inline keyboard."""
    import httpx

    url = f"https://api.telegram.org/bot{settings.telegram_token}/editMessageText"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "Markdown",
    }
    if keyboard:
        payload["reply_markup"] = json.loads(keyboard) if isinstance(keyboard, str) else keyboard

    async with httpx.AsyncClient(timeout=10.0) as client:
        await client.post(url, json=payload)


async def _send_with_keyboard(chat_id: int, text: str, keyboard) -> None:
    """Send a message with an inline keyboard."""
    import httpx

    url = f"https://api.telegram.org/bot{settings.telegram_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "reply_markup": keyboard if isinstance(keyboard, dict) else json.loads(keyboard),
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        await client.post(url, json=payload)


@router.post("/webhook")
async def webhook(request: Request) -> Response:
    """Telegram webhook receiver."""
    body = await request.body()

    if settings.telegram_webhook_secret:
        received_token = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not received_token:
            logger.warning("Webhook request missing secret token")
            return Response(status_code=401)
        if not hmac.compare_digest(received_token, settings.telegram_webhook_secret):
            logger.warning("Webhook secret token mismatch")
            return Response(status_code=403)

    try:
        data = json.loads(body)
        update = Update.de_json(data, None)
    except Exception as e:
        logger.error("Failed to parse Telegram update: %s", e)
        return Response(status_code=200)

    if not update:
        return Response(status_code=200)

    # ── Handle callback queries (inline keyboard taps) ─────────
    if update.callback_query:
        cq = update.callback_query
        logger.info("Callback query %s from %s: %s", cq.id, cq.from_user.id, cq.data)

        reply, new_keyboard = await handle_callback(cq)
        if reply:
            if new_keyboard is not None:
                # Update the message with new text + keyboard
                await _edit_message_text(
                    cq.message.chat_id, cq.message.message_id, reply, new_keyboard
                )
            else:
                # Final reply — remove keyboard, send result
                await _edit_message_text(
                    cq.message.chat_id, cq.message.message_id, reply
                )
        return Response(status_code=200)

    # ── Handle text messages ────────────────────────────────────
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

    if not check_rate_limit(message.chat_id):
        await _send_telegram_message(
            message.chat_id, "⏱ Slow down! You're sending too many requests."
        )
        return Response(status_code=200)

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
