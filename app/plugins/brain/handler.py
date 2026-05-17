from collections import defaultdict
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from app.llm.base import LLMMessage
from app.llm.prompts import BRAIN_SYSTEM_PROMPT
from app.llm.router import get_provider
from app.plugins.base import BotContext, Plugin, PluginRegistry
from app.plugins.brain import state as pending_state

logger = logging.getLogger(__name__)

_LONG_MSG_THRESHOLD = 100
_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)

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

# Actions that need validation before execution
_DIRECT_ACTIONS = {"chat", "note_save", "remind_create"}

# Required params per action
_REQUIRED_PARAMS: dict[str, list[str]] = {
    "remind_create": ["text", "time"],
    "note_save": ["text"],
    "search": ["query"],
}


class BrainPlugin(Plugin):
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
                max_tokens=2048,
                timeout=30.0,
            )

            actions = self._parse_actions(response.text)
            if not actions:
                return _acknowledge_long(ctx.message_text)

            return await self._validate_and_route(ctx, actions)

        except Exception as e:
            logger.error("Brain failed: %s", e, exc_info=True)
            # Acknowledge so user knows message wasn't lost
            return _acknowledge_long(ctx.message_text)

    # ── Provider ──────────────────────────────────────────────────────

    def _get_provider(self):
        try:
            return get_provider()
        except RuntimeError:
            return None

    # ── JSON parsing ──────────────────────────────────────────────────

    def _parse_actions(self, text: str) -> list[dict[str, Any]] | None:
        text = text.strip()

        # Strip markdown code fences — Gemini sometimes wraps JSON in ```json ... ```
        text = re.sub(r"```(?:json)?\s*(.*?)\s*```", r"\1", text, flags=re.DOTALL).strip()
        # Also strip inline backtick wrapping
        text = re.sub(r"^`(.*)`$", r"\1", text.strip())

        try:
            data = json.loads(text)
            if isinstance(data, list):
                return data  # Raw array of actions
            if isinstance(data, dict):
                if "actions" in data and isinstance(data["actions"], list):
                    return data["actions"]
                if "action" in data:
                    return [data]
        except json.JSONDecodeError:
            pass

        match = re.search(r'"actions"\s*:\s*(\[.*?\])', text, re.DOTALL)
        if match:
            try:
                actions = json.loads(match.group(1))
                if isinstance(actions, list):
                    return actions
            except json.JSONDecodeError:
                pass

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

        # All parsing failed — return None so caller shows acknowledgment
        return None

    # ── Validation + Routing ─────────────────────────────────────────

    async def _validate_and_route(self, ctx: BotContext, actions: list[dict]) -> str | None:
        """Validate all actions first. If missing params, ask user. Else confirm."""
        validated = []
        missing = []

        for item in actions:
            action = item.get("action") or item.get("type", "")
            params = {k: v for k, v in item.items() if k not in ("action", "type")}

            # Chat actions pass through immediately
            if action == "chat":
                return params.get("text") or params.get("response") or "🤔"

            # Check required params
            required = _REQUIRED_PARAMS.get(action, [])
            missing_params = [p for p in required if not params.get(p)]

            if missing_params:
                missing.append((action, missing_params, params))
            else:
                validated.append(item)

        # ── Missing params? Ask user ──────────────────────────
        if missing:
            return await self._handle_missing_params(ctx, missing)

        # ── All valid → show confirmation ─────────────────────
        if not validated:
            return "🤔 Not sure what to do with that."

        # Single action that doesn't need confirmation (no side effects)
        single = validated[0]
        s_action = single.get("action", "")
        if s_action in ("search", "ping", "help", "status", "pc_status"):
            return await self._route_single(s_action, single)

        # Everything else → show preview + ask confirm
        preview_lines = ["Here's what I'll do:", ""]

        # Group reminders by date, keep non-reminder items separate
        remind_items: list[dict] = []
        other_items: list[dict] = []
        for item in validated:
            if item.get("action") == "remind_create":
                remind_items.append(item)
            else:
                other_items.append(item)

        # Group reminders by date prefix
        by_day = defaultdict(list)
        for item in remind_items:
            day = item.get("time", "?").split(" ")[0] if " " in item.get("time", "") else item.get("time", "?")
            by_day[day].append(item)

        # Show non-reminder items first (notes, pc, etc)
        for item in other_items:
            a = item.get("action", "")
            if a == "note_save":
                t = item.get("text", "")[:60]
                preview_lines.append(f"📝 Save note: {t}")
            elif a in ("pc_on", "pc_off"):
                preview_lines.append("💻 " + ("Turn ON PC" if a == "pc_on" else "Turn OFF PC"))
            else:
                preview_lines.append(f"• {a}: {item.get('text', '')}")

        if other_items and remind_items:
            preview_lines.append("")

        # Show reminders grouped by day
        for day, items in sorted(by_day.items()):
            preview_lines.append(f"📅 {day}")
            for item in items:
                t = item.get("text", "")
                tm = item.get("time", "?").split(" ")[-1] if " " in item.get("time", "") else "?"
                preview_lines.append(f"   ⏰ {tm} - {t}")
            preview_lines.append("")

        total = len(remind_items) + len(other_items)
        preview_lines.append(f"Total: {total} item{'s' if total > 1 else ''}")
        preview_lines.append("Reply 'yes' to confirm, 'no' to cancel.")

        # Store in pending state — attach source_text to each action
        for item in validated:
            item["source_text"] = ctx.message_text

        pending_state.set(ctx.chat_id, {
            "actions": validated,
            "stage": "confirm",
            "original_text": ctx.message_text,
        })

        return "\n".join(preview_lines)

    # ── Missing params handler ────────────────────────────────────────

    async def _handle_missing_params(
        self, ctx: BotContext, missing: list[tuple[str, list[str], dict]]
    ) -> str:
        """Handle actions with missing parameters by asking the user."""
        action, missing_params, params = missing[0]

        # Build a sensible question
        if action == "remind_create":
            if "time" in missing_params and "text" in missing_params:
                return Ask.question(ctx, {}, "remind_create")
            elif "time" in missing_params:
                return Ask.question(ctx, params, "remind_create_time")
            elif "text" in missing_params:
                return Ask.question(ctx, params, "remind_create_text")

        if action == "note_save":
            return Ask.question(ctx, {}, "note_save")

        if action == "search":
            return Ask.question(ctx, {}, "search")

        return "I need a bit more info. Can you clarify?"

    # ── Route single action (called from dispatcher for pending confirm) ─

    async def _route_single(self, action: str, params: dict[str, Any]) -> str | None:
        """Route a single action to the right handler."""
        ctx = self._original_ctx
        if not ctx:
            return None

        if action == "chat":
            return params.get("text") or "🤔"

        if action == "note_save":
            text = params.get("text", "") or (ctx.message_text if ctx else "")
            plugin = PluginRegistry.get().get_plugin("notes")
            if plugin:
                return await plugin.save_note(ctx.chat_id, text)
            return "📝 Note feature not available."

        if action == "remind_create":
            return await self._handle_remind_create(params)

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

    # ── Remind create ────────────────────────────────────────────────

    async def _handle_remind_create(self, params: dict[str, Any]) -> str | None:
        from app.plugins.reminder.handler import ReminderPlugin, _parse_time

        text = params.get("text", "")
        time_str = params.get("time", "")
        alerts = params.get("alerts", [10])
        source_text = params.get("source_text", "")

        if not text or not time_str:
            logger.debug("Missing text or time for remind: text=%s time=%s", text, time_str)
            return None

        ctx = self._original_ctx
        if not ctx:
            logger.debug("No original context for remind")
            return None

        remind_at = _parse_time(time_str)
        if not remind_at:
            remind_at = self._parse_natural_time(time_str)

        if not remind_at:
            logger.debug("Could not parse time: %s", time_str)

        if not remind_at:
            return None

        if remind_at < datetime.now(timezone.utc):
            return "That time's already passed! 🕰️"

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
                source_text=source_text,
            )
        return None

    def _parse_natural_time(self, text: str) -> datetime | None:
        from dateutil import parser as dateparser
        try:
            return dateparser.parse(text, default=datetime.now(timezone.utc))
        except (ImportError, ValueError):
            pass
        return None


# ── Helper: Ask questions that set pending state ──────────────────────


class Ask:
    """Build questions that set pending state for missing params."""

    @staticmethod
    def question(ctx: BotContext, existing_params: dict, stage: str) -> str:
        chat_id = ctx.chat_id

        questions = {
            "remind_create": "📋 What do you need to be reminded about, and when? (e.g., 'meeting tomorrow 9am')",
            "remind_create_time": "⏰ When? (e.g., tomorrow 9am, in 2 hours, June 1st 08:00)",
            "remind_create_text": "📋 Remind you about what?",
            "note_save": "📝 What should I save as a note?",
            "search": "🔍 What should I search for?",
        }

        pending_state.set(chat_id, {
            "stage": stage,
            "action": {"action": "remind_create" if stage.startswith("remind_create") else stage, **existing_params},
            "original_text": ctx.message_text,
        })

        return questions.get(stage, "Could you clarify?")


def _acknowledge_long(text: str) -> str:
    """Fallback when Gemini can't process — never leak raw JSON."""
    return "📨 Pesan diterima, tapi terlalu panjang untuk saya proses. Coba kirim per bagian (maks 3-4 agenda per pesan) ya!"
