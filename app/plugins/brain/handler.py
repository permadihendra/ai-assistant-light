import json
import logging
import re
from typing import Any

from app.llm.base import LLMMessage
from app.llm.prompts import BRAIN_SYSTEM_PROMPT
from app.llm.router import get_provider
from app.plugins.base import BotContext, Plugin, PluginRegistry

logger = logging.getLogger(__name__)

# ── Action → (plugin_name, command_template) mapping ────────────────────
# The brain rewrites the user's message into a slash command and routes it
# to the target plugin. Zero duplication of plugin logic.
_ACTION_MAP: dict[str, tuple[str, str]] = {
    "search": ("web_search", "/search {query}"),
    "remind_create": ("reminder", "/remind {time} {text}"),
    "remind_list": ("reminder", "/reminders"),
    "summarize": ("summarizer", "/summarize"),
    "ping": ("system", "/ping"),
    "help": ("system", "/help"),
    "status": ("system", "/status"),
    "pc_on": ("script_runner", "/run relay-poweron-pc.py"),
    "pc_off": ("script_runner", "/run relay-poweroff-pc.py"),
    "pc_status": ("script_runner", "/run ping-pc.sh"),
}

# Regex fallback if Gemini returns malformed JSON
_JSON_RE = re.compile(r"\{(?:[^{}]|(?:\{[^{}]*\}))*\}")


class BrainPlugin(Plugin):
    """Handles non-command messages by routing them to the right plugin.

    Uses Gemini to classify intent into a structured JSON action, then
    routes to the appropriate plugin by rewriting BotContext.message_text
    as a slash command. This means every existing plugin works unchanged.
    """

    name = "brain"
    commands: list[str] = []
    description = "AI brain — understands natural language and routes to commands"

    def __init__(self) -> None:
        self._original_ctx: BotContext | None = None

    async def handle(self, ctx: BotContext) -> str | None:
        self._original_ctx = ctx
        provider = self._get_provider()
        if provider is None:
            return None

        try:
            response = await provider.chat(
                messages=[
                    LLMMessage(role="system", content=BRAIN_SYSTEM_PROMPT),
                    LLMMessage(role="user", content=ctx.message_text),
                ],
                max_tokens=512,
                timeout=15.0,
            )

            action, params = self._parse_response(response.text)
            return await self._route(action, params)

        except Exception as e:
            logger.error("Brain plugin failed: %s", e, exc_info=True)
            return None

    # ── Provider resolution ─────────────────────────────────────────

    def _get_provider(self):
        """Get the LLM provider, returning None if not configured."""
        try:
            return get_provider()
        except RuntimeError:
            return None

    # ── JSON parsing with fallback ───────────────────────────────────

    def _parse_response(self, text: str) -> tuple[str, dict[str, Any]]:
        """Parse Gemini's JSON response. Falls back to 'chat' action."""
        text = text.strip()

        # Try direct JSON parse
        try:
            data = json.loads(text)
            if isinstance(data, dict) and "action" in data:
                action = data.pop("action")
                return action, data
        except json.JSONDecodeError:
            pass

        # Try regex extraction of JSON object
        match = _JSON_RE.search(text)
        if match:
            try:
                data = json.loads(match.group())
                if isinstance(data, dict) and "action" in data:
                    action = data.pop("action")
                    return action, data
            except json.JSONDecodeError:
                pass

        # Fallback: treat entire response as chat text
        return "chat", {"text": text}

    # ── Routing engine ───────────────────────────────────────────────

    async def _route(self, action: str, params: dict[str, Any]) -> str | None:
        """Route the action to the appropriate plugin handler."""
        # Chat actions are handled directly by returning the LLM text
        if action == "chat":
            return params.get("text") or params.get("response") or "🤔"

        # Look up the action in the mapping
        mapping = _ACTION_MAP.get(action)
        if not mapping:
            logger.debug("Unknown brain action: %s", action)
            return params.get("text") or (
                "I'm not sure how to do that yet. Try /help to see my commands."
            )

        plugin_name, cmd_template = mapping
        plugin = PluginRegistry.get().get_plugin(plugin_name)
        if not plugin:
            logger.error("Plugin '%s' not found for action '%s'", plugin_name, action)
            return "⚠️ Internal error: plugin not found."

        # Build the command text from the template
        try:
            cmd_text = cmd_template.format(**params)
        except KeyError as e:
            logger.debug("Missing param %s for action %s", e, action)
            return "Could you be more specific? I need a bit more detail."

        # Create a new context with the rewritten command text
        route_ctx = BotContext(
            chat_id=self._original_ctx.chat_id,
            user_id=self._original_ctx.user_id,
            username=self._original_ctx.username,
            message_text=cmd_text,
            is_group=self._original_ctx.is_group,
            raw_update=self._original_ctx.raw_update,
        )

        try:
            return await plugin.handle(route_ctx)
        except Exception as e:
            logger.error(
                "Brain routing to '%s' failed: %s", plugin_name, e, exc_info=True
            )
            return "⚠️ Sorry, something went wrong while processing that."
