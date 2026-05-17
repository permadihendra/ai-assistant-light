import logging

from app.config import settings
from app.plugins.base import PluginRegistry

logger = logging.getLogger(__name__)


async def dispatch(update) -> str | None:
    """Map an incoming Telegram update to the correct handler.

    - Slash commands → matched to their plugin via PluginRegistry.resolve()
    - Free text → routed to the BrainPlugin for LLM understanding
    """
    message = update.message or update.edited_message
    if not message or not message.text:
        return None

    text = message.text.strip()

    # Build context (used by both command and brain paths)
    from app.bot.context import build_context

    ctx = build_context(update, text)

    # ── Non-command messages → BrainPlugin ────────────────
    if not text.startswith("/"):
        registry = PluginRegistry.get()
        brain = registry.get_plugin("brain")
        if brain:
            try:
                reply = await brain.handle(ctx)
                if reply:
                    return reply
            except Exception as e:
                logger.error("Brain plugin failed: %s", e, exc_info=True)
        return None

    # ── Slash commands → resolve to plugin ────────────────
    # Extract the command name (strip / and any @botusername suffix)
    command = text.split()[0].split("@")[0].lower().lstrip("/")

    # Resolve command to a plugin
    registry = PluginRegistry.get()
    plugin = registry.resolve(command)

    if plugin is None:
        return None

    # Authorization: only /run is restricted to ALLOWED_CHAT_IDS
    if settings.allowed_chat_ids and ctx.chat_id not in settings.allowed_chat_ids:
        if command in ("run",):
            return "⛔ You are not authorized to use this command."

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
