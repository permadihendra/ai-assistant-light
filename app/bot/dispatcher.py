import logging

from app.config import settings
from app.plugins.base import PluginRegistry

logger = logging.getLogger(__name__)


async def dispatch(update) -> str | None:
    """Route incoming messages to the right handler.

    Flow:
    1. Slash commands → resolved to plugin directly
    2. Free text → BrainPlugin (agentic flow)
    """
    message = update.message or update.edited_message
    if not message or not message.text:
        return None

    text = message.text.strip()
    chat_id = message.chat_id

    # ── Handle Telegram reply feature ─────────────────────────
    # If user is replying to a specific message, inject it as context
    reply_to = message.reply_to_message
    if reply_to and reply_to.text:
        reply_preview = reply_to.text[:200]
        reply_user = reply_to.from_user.first_name if reply_to.from_user else "User"
        text = f'[Replying to {reply_user}: "{reply_preview}"]\n{text}'

    # Build context for normal routing
    from app.bot.context import build_context
    ctx = build_context(update, text)

    # ── 1. Slash commands ────────────────────────────────────
    if text.startswith("/"):
        command = text.split()[0].split("@")[0].lower().lstrip("/")
        registry = PluginRegistry.get()
        plugin = registry.resolve(command)
        if plugin:
            if settings.allowed_chat_ids and ctx.chat_id not in settings.allowed_chat_ids:
                if command in ("run",):
                    return "⛔ You are not authorized to use this command."
            try:
                return await plugin.handle(ctx)
            except Exception as e:
                logger.error("Plugin '%s' failed: %s", plugin.name, e, exc_info=True)
                return f"⚠️ Error processing `/{command}`."
        return None

    # ── 2. Free text → BrainPlugin (agentic flow) ────────────
    registry = PluginRegistry.get()
    brain = registry.get_plugin("brain")
    if brain:
        try:
            reply = await brain.handle(ctx)
            return reply
        except Exception as e:
            logger.error("Brain failed: %s", e, exc_info=True)
    return None
