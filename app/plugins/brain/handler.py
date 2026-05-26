import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from app.cost_tracker import log_usage as _log_token_usage
from app.llm.base import LLMMessage
from app.llm.prompts import BRAIN_SYSTEM_PROMPT
from app.llm.router import get_provider
from app.plugins.base import BotContext, Plugin, PluginRegistry
from app.plugins.brain.context import retrieve_context

logger = logging.getLogger(__name__)


class BrainPlugin(Plugin):
    name = "brain"
    commands: list[str] = []
    description = "AI brain - understands natural language and routes to commands"

    def __init__(self) -> None:
        self._original_ctx: BotContext | None = None

    async def handle(self, ctx: BotContext) -> str | None:
        self._original_ctx = ctx

        # Skip pure separators (===, ---, ***, ___)
        if re.match(r"^[=\-*_#~]{3,}$", ctx.message_text.strip()):
            return None

        provider = self._get_provider()
        if provider is None:
            return None

        try:
            # Retrieve conversation context (recent messages + FTS5 search)
            context = await retrieve_context(ctx.chat_id, ctx.message_text)

            # Build messages with context
            messages = [LLMMessage(role="system", content=BRAIN_SYSTEM_PROMPT)]
            if context:
                messages.append(LLMMessage(
                    role="system",
                    content=f"Conversation context:\n{context}",
                ))
            messages.append(LLMMessage(role="user", content=ctx.message_text))

            # Dynamic token budget: longer input → more output room
            input_len = len(ctx.message_text)
            output_budget = max(1024, min(8192, input_len * 2))

            response = await provider.chat(
                messages=messages,
                max_tokens=output_budget,
                timeout=30.0,
            )

            # Log token usage (if available)
            if response.input_tokens is not None or response.output_tokens is not None:
                await _log_token_usage(
                    chat_id=ctx.chat_id,
                    model=response.model,
                    input_tokens=response.input_tokens or 0,
                    output_tokens=response.output_tokens or 0,
                )

            # Parse TOOL: calls from Gemini's response
            result = await self._process_agent_response(ctx, response.text)
            return result

        except Exception as e:
            logger.error("Brain failed: %s", e, exc_info=True)
            # Acknowledge so user knows message wasn't lost
            return "📝 I had trouble processing that. Could you rephrase?"

    # ── Agent response processing ────────────────────────────────────

    _TOOL_RE = re.compile(r'^TOOL:\s*(\w+)\((.*)\)\s*$', re.MULTILINE)

    async def _process_agent_response(self, ctx: BotContext, text: str) -> str | None:
        """Process Gemini's agent response.

        If there are TOOL: calls, execute them and REPLACE each TOOL: line
        with the tool result - preserving Gemini's conversational text.
        This keeps the bot's personality intact in a single API call.
        """
        if 'TOOL:' not in text:
            return text.strip()

        # Split into segments: conversational text and tool calls
        lines = text.split('\n')
        output_lines = []

        for line in lines:
            m = re.match(r'^TOOL:\s*(\w+)\((.*)\)\s*$', line.strip())
            if m:
                tool_name = m.group(1)
                params_str = m.group(2)
                try:
                    params = self._parse_tool_params(params_str)
                    result = await self._execute_tool(ctx, tool_name, params)
                    if result:
                        output_lines.append(result)
                except Exception as e:
                    logger.error("Tool '%s' failed: %s", tool_name, e)
                    output_lines.append(f"⚠️ {tool_name} failed: {e}")
            else:
                # Conversational text from Gemini - keep it
                output_lines.append(line)

        return '\n'.join(output_lines).strip()


    def _parse_tool_params(self, params_str: str) -> dict:
        """Parse tool parameters. Handles quoted strings AND nested JSON."""
        params = {}
        i = 0
        while i < len(params_str):
            # Skip whitespace and commas
            while i < len(params_str) and params_str[i] in ' ,':
                i += 1
            if i >= len(params_str):
                break
            # Find key
            m = re.match(r'(\w+)=', params_str[i:])
            if not m:
                i += 1
                continue
            key = m.group(1)
            i += len(m.group(0))
            # Skip whitespace before value
            while i < len(params_str) and params_str[i] in ' \t':
                i += 1
            if i >= len(params_str):
                break
            # Determine value type by first char
            c = params_str[i]
            if c in '"\'':
                # Quoted string
                quote = c
                i += 1
                val_start = i
                while i < len(params_str) and params_str[i] != quote:
                    i += 1
                params[key] = params_str[val_start:i]
                i += 1
            elif c == '[':
                # JSON array - track bracket depth
                depth = 0
                val_start = i
                while i < len(params_str):
                    if params_str[i] == '[': depth += 1
                    elif params_str[i] == ']': depth -= 1
                    i += 1
                    if depth == 0:
                        break
                params[key] = params_str[val_start:i]
            elif c == '{':
                # JSON object - track brace depth
                depth = 0
                val_start = i
                while i < len(params_str):
                    if params_str[i] == '{': depth += 1
                    elif params_str[i] == '}': depth -= 1
                    i += 1
                    if depth == 0:
                        break
                params[key] = params_str[val_start:i]
            else:
                # Unquoted simple value
                val_start = i
                while i < len(params_str) and params_str[i] not in ' ,':
                    i += 1
                params[key] = params_str[val_start:i].strip()
        return params


    async def _execute_tool(self, ctx: BotContext, tool: str, params: dict) -> str:
        """Execute a tool call by routing to the appropriate plugin."""
        from app.plugins.base import PluginRegistry

        if tool == "remind_create":
            return await self._handle_remind_create({
                "text": params.get("text", ""),
                "time": params.get("time", ""),
                "alerts": [10],
                "source_text": ctx.message_text,
            })

        if tool == "agenda_query":
            date = params.get("date", "today")
            if date == "all":
                return await self._route_single("agenda_all", {})
            elif date == "tomorrow":
                return await self._route_single("agenda_tomorrow", {})
            else:
                return await self._route_single("agenda_today", {})

        if tool == "agenda_create":
            items_str = params.get("items", "[]")
            try:
                items = json.loads(items_str)
            except (json.JSONDecodeError, TypeError):
                # Try replacing dot time separators with colon
                items_str_fixed = items_str.replace('"', '"')
                try:
                    items = json.loads(items_str_fixed)
                except json.JSONDecodeError:
                    items = []
            return await self._handle_agenda_create({
                "date": params.get("date", ""),
                "items": items,
            })

        if tool == "agenda_done":
            plugin = PluginRegistry.get().get_plugin("agenda")
            if plugin:
                try:
                    rid = int(params.get("id", 0))
                    return await plugin.mark_done_by_id(ctx.chat_id, rid)
                except ValueError:
                    return "❌ Invalid ID."
            return "❌ Agenda plugin not available."

        if tool == "search":
            return await self._route_single("search", {"query": params.get("query", "")})

        if tool == "note_save":
            plugin = PluginRegistry.get().get_plugin("notes")
            if plugin:
                return await plugin.save_note(
                    ctx.chat_id, params.get("text", ctx.message_text)
                )
            return "📝 Note feature not available."

        if tool == "note_search":
            plugin = PluginRegistry.get().get_plugin("notes")
            if plugin:
                return await plugin.search_notes(
                    ctx.chat_id, params.get("query", "")
                )
            return "📝 Note feature not available."

        if tool == "note_update":
            plugin = PluginRegistry.get().get_plugin("notes")
            if plugin:
                return await plugin.update_note(
                    ctx.chat_id, params.get("id", "0"), params.get("text", "")
                )
            return "📝 Note feature not available."

        if tool == "note_delete":
            plugin = PluginRegistry.get().get_plugin("notes")
            if plugin:
                return await plugin.delete_note(
                    ctx.chat_id, params.get("id", "0")
                )
            return "📝 Note feature not available."

        if tool == "note_list":
            return await self._route_single("note_list", {})

        if tool == "summarize":
            return await self._route_single("summarize", {})

        if tool in ("pc_on", "pc_off", "pc_status"):
            return await self._route_single(tool, {})

        if tool == "remind_list":
            return await self._route_single("remind_list", {})

        logger.warning("Unknown tool: %s", tool)
        return f"❓ Unknown tool: {tool}"


    def _get_provider(self):
        try:
            return get_provider()
        except RuntimeError:
            return None

    # ── Route single action ───────────────────────────────────────────

    async def _route_single(self, action: str, params: dict[str, Any]) -> str:
        """Route a single action to the right plugin. Never returns None."""
        ctx = self._original_ctx
        if not ctx:
            return "⚠️ Internal error: no context."

        # Direct plugin calls
        if action == "note_save":
            plugin = PluginRegistry.get().get_plugin("notes")
            if plugin:
                return await plugin.save_note(ctx.chat_id, params.get("text", ctx.message_text))
            return "📝 Note feature not available."

        # Agenda queries → AgendaPlugin
        if action in ("agenda_today", "agenda_tomorrow", "agenda_all"):
            plugin = PluginRegistry.get().get_plugin("agenda")
            if plugin:
                cmd = f"/agenda {action.replace('agenda_', '')}"
                return await plugin.handle(BotContext(
                    chat_id=ctx.chat_id, user_id=ctx.user_id,
                    username=ctx.username, message_text=cmd,
                    is_group=ctx.is_group, raw_update=ctx.raw_update,
                ))
            return "📋 Agenda feature not available."

        # Commands via plugin routing
        CMD_MAP = {
            "search": ("web_search", lambda: f"/search {params.get('query', '')}"),
            "remind_list": ("reminder", lambda: "/reminders"),
            "summarize": ("summarizer", lambda: "/summarize"),
            "ping": ("system", lambda: "/ping"),
            "help": ("system", lambda: "/help"),
            "status": ("system", lambda: "/status"),
        }
        if action in CMD_MAP:
            plugin_name, cmd_builder = CMD_MAP[action]
            plugin = PluginRegistry.get().get_plugin(plugin_name)
            if plugin:
                return await plugin.handle(BotContext(
                    chat_id=ctx.chat_id, user_id=ctx.user_id,
                    username=ctx.username, message_text=cmd_builder(),
                    is_group=ctx.is_group, raw_update=ctx.raw_update,
                ))
            return f"⚠️ {action} feature not available."

        # PC control → ScriptRunnerPlugin
        if action in ("pc_on", "pc_off", "pc_status"):
            script = {"pc_on": "relay-poweron-pc.py", "pc_off": "relay-poweroff-pc.py",
                      "pc_status": "ping-pc.sh"}[action]
            plugin = PluginRegistry.get().get_plugin("script_runner")
            if plugin:
                return await plugin.handle(BotContext(
                    chat_id=ctx.chat_id, user_id=ctx.user_id,
                    username=ctx.username, message_text=f"/run {script}",
                    is_group=ctx.is_group, raw_update=ctx.raw_update,
                ))
            return "💻 PC control not available."

        logger.debug("Unknown action: %s", action)
        return "🤔 Not sure how to help with that."

    # ── Agenda create ───────────────────────────────────────────────

    async def _handle_agenda_create(self, params: dict[str, Any]) -> str:
        ctx = self._original_ctx
        if not ctx:
            return "⚠️ Internal error: no context."

        date_str = params.get("date", "")
        items = params.get("items", [])
        if not date_str or not items:
            return "The schedule looks incomplete. Please include the date and event details."

        from app.plugins.agenda.handler import AgendaPlugin
        plugin = PluginRegistry.get().get_plugin("agenda")
        if isinstance(plugin, AgendaPlugin):
            return await plugin.save_items(
                chat_id=ctx.chat_id, user_id=ctx.user_id,
                date_str=date_str, items=items,
                alerts=params.get("alerts", [10]),
            )
        return "❌ Agenda feature not available."

    # ── Remind create ────────────────────────────────────────────────

    async def _handle_remind_create(self, params: dict[str, Any]) -> str:
        from app.plugins.reminder.handler import ReminderPlugin, _parse_time

        text = params.get("text", "")
        time_str = params.get("time", "")
        # Normalize dot separators to colon (10.30 → 10:30)
        time_str = re.sub(r'(\d{1,2})\.(\d{2})', r'\1:\2', time_str)

        if not text or not time_str:
            return "I need the time and what to remind about. Try: 'in 10m check oven' or 'besok 09:00 meeting'."

        ctx = self._original_ctx
        if not ctx:
            return "⚠️ Internal error: no context."

        remind_at = _parse_time(time_str)
        if not remind_at:
            remind_at = self._parse_natural_time(time_str)

        if not remind_at:
            return (
                f"I couldn't understand '{time_str}' as a time. "
                f"Try formats like 'in 10m', 'tomorrow 09:00', 'besok 08:00', or '2 jam lagi'."
            )

        if remind_at < datetime.now(timezone.utc):
            return f"That time ({time_str}) has already passed. Try a different time or date."

        alerts = params.get("alerts", [10])
        if not isinstance(alerts, list):
            alerts = [10]

        plugin = PluginRegistry.get().get_plugin("reminder")
        if isinstance(plugin, ReminderPlugin):
            return await plugin.create_reminder(
                chat_id=ctx.chat_id, user_id=ctx.user_id,
                text=text, remind_at=remind_at,
                alerts=alerts, source_text=params.get("source_text", ""),
            )
        return "⏰ Reminder feature not available."

    def _parse_natural_time(self, text: str) -> datetime | None:
        from dateutil import parser as dateparser
        try:
            return dateparser.parse(text, default=datetime.now(timezone.utc))
        except (ImportError, ValueError):
            pass
        return None
