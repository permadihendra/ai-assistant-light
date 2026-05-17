import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from app.llm.base import LLMMessage
from app.llm.prompts import BRAIN_SYSTEM_PROMPT
from app.llm.router import get_provider
from app.plugins.base import BotContext, Plugin, PluginRegistry

logger = logging.getLogger(__name__)

_LONG_MSG_THRESHOLD = 100  # chars — messages above this trigger smart parsing

# Regex fallback for malformed JSON
_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)
_ACTIONS_RE = re.compile(r'"actions"\s*:\s*\[.*?\]', re.DOTALL)

# ── Action → (plugin_name, command_template) mapping ────────────────────
_ACTION_MAP: dict[str, tuple[str, str | None]] = {
    "search": ("web_search", "/search {query}"),
    "remind_list": ("reminder", "/reminders"),
    "summarize": ("summarizer", "/summarize"),
    "ping": ("system", "/ping"),
    "help": ("system", "/help"),
    "status": ("system", "/status"),
    "pc_on": ("script_runner", "/run relay-poweron-pc.py"),
    "pc_off": ("script_runner", "/run relay-poweroff-pc.py"),
    "pc_status": ("script_runner", "/run ping-pc.sh"),
}

# Actions handled directly (no command routing needed)
_DIRECT_ACTIONS = {"chat", "note_save", "remind_create"}


class BrainPlugin(Plugin):
    """Handles non-command messages by routing to the right plugin.

    v3: Supports actions[] array — multiple actions from one API call.
    Long messages (>100 chars) trigger smart parsing for notes + reminders.
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

            actions = self._parse_actions(response.text)
            if not actions:
                return None

            return await self._route_actions(actions)

        except Exception as e:
            logger.error("Brain failed: %s", e, exc_info=True)
            return None

    # ── Provider ──────────────────────────────────────────────────────

    def _get_provider(self):
        try:
            return get_provider()
        except RuntimeError:
            return None

    # ── JSON parsing with fallbacks ────────────────────────────────────

    def _parse_actions(self, text: str) -> list[dict[str, Any]] | None:
        """Parse Gemini's response into a list of action dicts."""
        text = text.strip()

        # Try direct parse
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                if "actions" in data and isinstance(data["actions"], list):
                    return data["actions"]
                if "action" in data:
                    return [data]
        except json.JSONDecodeError:
            pass

        # Try regex for actions array
        match = re.search(r'"actions"\s*:\s*(\[.*?\])', text, re.DOTALL)
        if match:
            try:
                actions = json.loads(match.group(1))
                if isinstance(actions, list):
                    return actions
            except json.JSONDecodeError:
                pass

        # Try regex for single action object
        match = _JSON_RE.search(text)
        if match:
            try:
                data = json.loads(match.group())
                if isinstance(data, dict):
                    if "actions" in data and isinstance(data["actions"], list):
                        return data["actions"]
                    if "action" in data:
                        return [data]
            except json.JSONDecodeError:
                pass

        # Fallback: treat as chat
        return [{"action": "chat", "text": text[:500]}]

    # ── Routing engine ────────────────────────────────────────────────

    async def _route_actions(self, actions: list[dict[str, Any]]) -> str | None:
        """Execute each action and collect replies."""
        replies: list[str] = []

        for item in actions:
            if not isinstance(item, dict):
                continue
            action = item.pop("action", None) or item.pop("type", None)
            if not action:
                continue

            try:
                reply = await self._route_single(action, item)
                if reply:
                    replies.append(reply)
            except Exception as e:
                logger.error("Action '%s' failed: %s", action, e)

        if not replies:
            return None
        return "\n\n".join(replies)

    async def _route_single(self, action: str, params: dict[str, Any]) -> str | None:
        """Route a single action to the right handler."""
        ctx = self._original_ctx
        if not ctx:
            return None

        # ── Chat — return directly ──────────────────────────────
        if action == "chat":
            return params.get("text") or params.get("response") or "🤔"

        # ── Note save — call NotesPlugin directly ────────────────
        if action == "note_save":
            text = params.get("text", "") or ctx.message_text
            plugin = PluginRegistry.get().get_plugin("notes")
            if plugin:
                return await plugin.save_note(ctx.chat_id, text)
            return "📝 Note feature not available."

        # ── Remind create — call ReminderPlugin directly ─────────
        if action == "remind_create":
            return await self._handle_remind_create(params)

        # ── Command-based actions — rewrite and route ────────────
        mapping = _ACTION_MAP.get(action)
        if mapping:
            plugin_name, cmd_template = mapping
            if cmd_template:
                plugin = PluginRegistry.get().get_plugin(plugin_name)
                if not plugin:
                    return None
                try:
                    cmd_text = cmd_template.format(**params)
                except KeyError as e:
                    logger.debug("Missing param %s for action %s", e, action)
                    return None
                route_ctx = BotContext(
                    chat_id=ctx.chat_id,
                    user_id=ctx.user_id,
                    username=ctx.username,
                    message_text=cmd_text,
                    is_group=ctx.is_group,
                    raw_update=ctx.raw_update,
                )
                return await plugin.handle(route_ctx)

        logger.debug("Unknown brain action: %s", action)
        return None

    # ── Remind create — time parsing + multi-alert ──────────────

    async def _handle_remind_create(self, params: dict[str, Any]) -> str | None:
        """Create a reminder with smart time parsing and alerts."""
        from app.plugins.reminder.handler import ReminderPlugin, _parse_time

        text = params.get("text", "")
        time_str = params.get("time", "")
        alerts = params.get("alerts", [15, 5])

        if not text or not time_str:
            return "Need more details — what and when?"

        ctx = self._original_ctx
        if not ctx:
            return None

        # Try parsing the time
        remind_at = _parse_time(time_str)
        if not remind_at:
            # Try common natural language patterns
            remind_at = self._parse_natural_time(time_str)

        if not remind_at:
            return f"Hmm, couldn't figure out when '{time_str}' is. Try /remind for manual setup."

        if remind_at < datetime.now(timezone.utc):
            return "That time's already passed! 🕰️"

        # Ensure alerts is a valid list
        if not isinstance(alerts, list):
            alerts = [15, 5]

        plugin = PluginRegistry.get().get_plugin("reminder")
        if isinstance(plugin, ReminderPlugin):
            return await plugin.create_reminder(
                chat_id=ctx.chat_id,
                user_id=ctx.user_id,
                text=text,
                remind_at=remind_at,
                alerts=alerts,
            )

        return None

    def _parse_natural_time(self, text: str) -> datetime | None:
        """Fallback: parse fuzzy time strings like 'next monday', 'in 2 hours'."""
        from dateutil import parser as dateparser
        try:
            return dateparser.parse(text, default=datetime.now(timezone.utc))
        except (ImportError, ValueError):
            pass
        return None
