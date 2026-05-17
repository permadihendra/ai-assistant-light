import logging

from app.config import settings
from app.plugins.base import PluginRegistry

logger = logging.getLogger(__name__)


async def dispatch(update) -> str | None:
    """Map an incoming Telegram update to the correct plugin handler."""
    message = update.message or update.edited_message
    if not message or not message.text:
        return None

    text = message.text.strip()

    # Check if it's a command
    if not text.startswith("/"):
        return None

    # Extract the command name (strip / and any @botusername suffix)
    command = text.split()[0].split("@")[0].lower().lstrip("/")

    # Resolve command to a plugin
    registry = PluginRegistry.get()
    plugin = registry.resolve(command)

    if plugin is None:
        return None

    # Build context and handle
    from app.bot.context import build_context

    ctx = build_context(update, text)

    # Authorization check
    if settings.allowed_chat_ids and ctx.chat_id not in settings.allowed_chat_ids:
        if command in ("run",):
            return "⛔ You are not authorized to use this command."
        # Other commands are allowed in any chat, but we still check later

    try:
        reply = await plugin.handle(ctx)
        return reply
    except Exception as e:
        logger.error(
            "Plugin '%s' failed for command '%s': %s",
            plugin.name,
            command,
            e,
            exc_info=True,
        )
        return f"⚠️ An error occurred while processing `/{command}`."
