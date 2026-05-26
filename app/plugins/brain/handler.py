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
from app.plugins.brain.context import retrieve_context

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
    "agenda_today": ("agenda", "/agenda today"),
    "agenda_tomorrow": ("agenda", "/agenda tomorrow"),
    "agenda_all": ("agenda", "/agenda all"),
    "agenda_done": ("agenda", None),  # special: parsed by AgendaPlugin
    "agenda_done_all": ("agenda", None),  # special: mark all today as done
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

        # Skip pure separators (===, ---, ***, ___)
        if re.match(r"^[=\-*_#~]{3,}$", ctx.message_text.strip()):
            return None

        # ── Local intent detection (fast path, 0 API call) ────
        local_action = _detect_local_intent(ctx.message_text)
        if local_action:
            logger.debug("Local intent detected: %s", local_action)
            return await self._route_single(
                local_action["action"],
                local_action.get("params", {}),
            )

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

            # Parse TOOL: calls from Gemini's response
            result = await self._process_agent_response(ctx, response.text)
            return result

        except Exception as e:
            logger.error("Brain failed: %s", e, exc_info=True)
            # Acknowledge so user knows message wasn't lost
            return _acknowledge_long(ctx.message_text)

    # ── Agent response processing ────────────────────────────────────

    _TOOL_RE = re.compile(r'^TOOL:\s*(\w+)\((.*)\)\s*$', re.MULTILINE)

    async def _process_agent_response(self, ctx: BotContext, text: str) -> str | None:
        """Process Gemini's agent response. Extract TOOL: calls, execute them."""
        tool_calls = self._TOOL_RE.findall(text)
        
        if not tool_calls:
            # No tool calls — just return Gemini's conversational response
            return text.strip()
        
        # Execute each tool call
        results = []
        for tool_name, params_str in tool_calls:
            try:
                params = self._parse_tool_params(params_str)
                result = await self._execute_tool(ctx, tool_name, params)
                if result is not None:
                    results.append(result)
            except Exception as e:
                logger.error("Tool '%s' failed: %s", tool_name, e)
                results.append(f"⚠️ {tool_name} failed: {e}")
        
        return "\n\n".join(results) if results else None


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
                # JSON array — track bracket depth
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
                # JSON object — track brace depth
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


    # ── Provider ──────────────────────────────────────────────────────

    def _get_provider(self):
        try:
            return get_provider()
        except RuntimeError:
            return None

    # ── JSON parsing (kept for backward compat) ───────────────────────

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

            # Validate remind_create time — must have BOTH date AND hour
            if action == "remind_create":
                ts = params.get("time", "")
                if ts and not _has_explicit_hour(ts):
                    # Time exists but no hour specified → ask
                    pending_state.set(ctx.chat_id, {
                        "stage": "ask_time",
                        "action": {"action": "remind_create", **params, "time": ""},
                        "original_text": ctx.message_text,
                    })
                    if _lang(ctx.message_text) == "id":
                        return "⏰ Jamnya belum disebut. Reply dengan jam-nya aja, misal `09:00` atau `14:30`"
                    else:
                        return "⏰ Hour not specified. Reply with just the time, e.g. `09:00` or `14:30`"

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

        if action == "agenda_create":
            return await self._handle_agenda_create(params)

        if action == "agenda_done":
            reminder_id = params.get("id")
            if reminder_id:
                plugin = PluginRegistry.get().get_plugin("agenda")
                if plugin:
                    return await plugin.mark_done_by_id(ctx.chat_id, reminder_id)
            return "❓ Which item? Use `/done <id>` or tell me the number."

        if action == "agenda_done_all":
            plugin = PluginRegistry.get().get_plugin("agenda")
            if plugin:
                return await plugin.mark_done_all_today(ctx.chat_id)
            return "❌ Agenda plugin not available."

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

    # ── Agenda create ───────────────────────────────────────────────

    async def _handle_agenda_create(self, params: dict[str, Any]) -> str | None:
        """Save agenda items via AgendaPlugin."""
        from app.plugins.agenda.handler import AgendaPlugin

        ctx = self._original_ctx
        if not ctx:
            return None

        date_str = params.get("date", "")
        items = params.get("items", [])
        if not date_str or not items:
            return "❓ Missing date or items for agenda."

        plugin = PluginRegistry.get().get_plugin("agenda")
        if isinstance(plugin, AgendaPlugin):
            return await plugin.save_items(
                chat_id=ctx.chat_id,
                user_id=ctx.user_id,
                date_str=date_str,
                items=items,
                alerts=params.get("alerts", [10]),
            )
        return "❌ Agenda plugin not available."

    # ── Remind create ────────────────────────────────────────────────

    async def _handle_remind_create(self, params: dict[str, Any]) -> str | None:
        from app.plugins.reminder.handler import ReminderPlugin, _parse_time

        text = params.get("text", "")
        time_str = params.get("time", "")
        # Normalize dot separators to colon (10.30 → 10:30)
        time_str = re.sub(r'(\d{1,2})\.(\d{2})', r'\1:\2', time_str)
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
            logger.info("Time parse failed for: %s", time_str)
            return None

        if remind_at < datetime.now(timezone.utc):
            return "❌ Waktu sudah lewat ('" + time_str + "'). Bot tidak bisa mengingatkan untuk waktu yang sudah berlalu."

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

        # Normalize stage names
        normalized = "ask_time" if "remind_create" in stage else stage

        questions = {
            "ask_time": "⏰ Kapan? Reply dengan format `besok 09:00`, `20/05/2026 09:00`, atau `nanti 2 jam`",
            "ask_time_en": "⏰ When? Reply with format `tomorrow 09:00`, `20/05/2026 09:00`, or `in 2 hours`",
            "ask_text": "📋 Remind you about what?",
            "note_save": "📝 What should I save as a note?",
            "search": "🔍 What should I search for?",
        }

        pending_state.set(chat_id, {
            "stage": normalized,
            "action": {"action": "remind_create" if "remind" in stage else stage, **existing_params},
            "original_text": ctx.message_text,
        })

        # Pick language based on user's message
        if normalized == "ask_time":
            key = "ask_time" if _lang(ctx.message_text) == "id" else "ask_time_en"
            return questions[key]
        return questions.get(normalized, "Could you clarify?")


def _acknowledge_long(text: str) -> str:
    """Fallback when Gemini can't process — never leak raw JSON."""
    return "📨 Pesan diterima, tapi terlalu panjang untuk saya proses. Coba kirim per bagian (maks 3-4 agenda per pesan) ya!"


def _has_explicit_hour(time_str: str) -> bool:
    """Check if a time string includes an explicit hour or relative time.
    
    Has hour/relative:
      'tomorrow 09:00' → True (explicit time)
      'besok 09:00' → True
      '2m', '10m', '2h' → True (relative time — minutes/hours)
      'in 2 hours', 'nanti 30 menit' → True
    
    No hour:
      'tomorrow' → False (just a date keyword)
      'besok' → False
      '20/05/2026' → False
    """
    import re
    # Relative time: \d+m (minutes), \d+h (hours), \d+s (seconds)
    if re.search(r"\d+[smh]$", time_str):
        return True
    # Relative time: in/dalam/nanti X minutes/hours/menit/jam
    if re.search(r"\b(in|dalam|nanti)\s+\d+\s*(s|m|h|seconds?|minutes?|hours?|detik|menit|jam)", time_str, re.IGNORECASE):
        return True
    # Has a digit followed by : or . (like 09:00, 9:00, 9.00)
    if re.search(r"\d{1,2}[:\.]\d{2}", time_str):
        return True
    # Has specific hour notation (9am, 9pm, 9 AM)
    if re.search(r"\d{1,2}\s*(am|pm)", time_str, re.IGNORECASE):
        return True
    # Has explicit Indonesian time (jam 9, pukul 09.00)
    if re.search(r"\b(jam|pukul)\s+\d", time_str, re.IGNORECASE):
        return True
    # Only date keywords without digits → no hour
    return False

def _lang(msg: str) -> str:
    """Detect if message is Indonesian or English based on keywords."""
    id_words = r"\b(besok|lusa|hari\s+ini|nanti|jam|menit|detik|senin|selasa|rabu|kamis|jumat|sabtu|minggu|depan|lagi|sekarang|ini|saya|saya|tolong|ingatkan|beli|makan|pergi|kerja)\b"
    en_words = r"\b(tomorrow|today|now|next|in\s+\d+|minutes?|hours?|seconds?|monday|tuesday|wednesday|thursday|friday|saturday|sunday|remind|me|buy|go|work|meeting|call)\b"
    
    id_count = len(re.findall(id_words, msg.lower()))
    en_count = len(re.findall(en_words, msg.lower()))
    
    if id_count > en_count:
        return "id"
    return "en"


# ── Local intent detection (confidence scoring) ──────────────
# All features scored independently. Highest score wins.
# Ambiguous (scores too close) → fallback Gemini.

# ── Keyword sets (EN + ID + slang + typos + mixed) ─────
# All variants included directly — no separate typo map needed.
# Word-boundary matching prevents substring false positives.

_AGENDA_W = {
    # English
    "agenda", "agendas", "schedule", "schedules", "scheduling",
    "meeting", "meetings", "meet", "task", "tasks", "plan", "plans",
    # English slang / typos
    "schedual", "schdule", "skedul", "skedule",
    "meetin", "meetin", "mtg",
    # Indonesian
    "jadwal", "jadwall", "rapat", "rapatan", "rapatnya",
    "acara", "acaraa", "tugas", "tugass", "kegiatan",
    # Indonesian slang / typos
    "jdwal", "jadual", "jadwel",
    "agend", "agnda", "agendaa", "agin", "ajenda",
}

_TODAY_W = {
    # English
    "today", "today's", "todays",
    # Indonesian
    "hari ini", "sekarang", "ini", "skrg", "skrng",
    "hari",  # in context like "agenda hari ini"
}

_TOMORROW_W = {
    # English
    "tomorrow", "tomorrow's",
    # English typos
    "tomorow", "tomoro", "tommorow", "tmrw",
    # Indonesian
    "besok", "lusa", "besoknya",
    # Indonesian typos
    "bsk", "esok",
}

_ALL_W = {
    # English
    "all", "everything", "upcoming", "upcomming",
    "list", "lists", "full", "complete", "whole",
    # Indonesian
    "semua", "keseluruhan", "daftar", "seluruh", "semuanya",
    # Indonesian slang
    "all", "semuaa", "daftar", "list",
}

_SHOW_W = {
    # English
    "show", "shows", "display", "view", "open",
    "what", "whats", "what's", "wat", "wats", "wot", "wuts",
    # Indonesian
    "lihat", "lihatlah", "tampilkan", "tampilin", "tunjukin",
    "cek", "ceck", "cekin", "check", "periksa",
    "buka", "lihatin", "liatin", "lihatkan",
}

_DONE_W = {
    # English
    "done", "finish", "finished", "finishd", "complete",
    "completed", "complite", "complited", "complate",
    "mark", "marked",
    # Indonesian
    "selesai", "selesain", "selesaikan", "beres", "beresin",
    "tandai", "tandain", "centang", "sudah", "udh", "udah", "dah",
    "ok", "oke",
}

_REMIND_CREATE_W = {
    # English
    "remind", "reminds", "reminding", "remind me", "reminder", "reminders",
    "set reminder", "create reminder", "add reminder", "new reminder",
    "alert", "alerts", "alert me", "notify", "notify me",
    # Indonesian
    "ingatkan", "ingetin", "ingetin", "pengingat", "alarm",
    "tolong ingatkan", "kasih tahu", "kasih tau", "kasi tau",
    # Mixed
    "remind saya", "remind aku", "remind gue",
}

_REMIND_LIST_W = {
    # English
    "reminders", "reminder list", "my reminders", "list reminders",
    # Indonesian
    "reminder saya", "daftar reminder", "pengingat",
}

_SEARCH_W = {
    # English
    "search", "searches", "searching", "search for",
    "find", "finds", "finding", "look up", "lookup",
    "google", "googling", "find info", "find information",
    # Indonesian
    "cari", "cariin", "carian", "mencari", "nyari",
    "googling", "searching",
    # Mixed
    "search tentang", "cari for",
}

_NOTE_SAVE_W = {
    # English
    "save", "saves", "saving", "save this",
    "remember this", "remember that", "note this", "note down",
    "take note", "take notes", "store this",
    # Indonesian
    "catat", "catat ini", "catetan", "nyatet",
    "simpan", "simpen", "simpan ini", "nyimpen",
    "ingat ini", "inget ini",
}

_NOTE_LIST_W = {
    # English
    "notes", "my notes", "all notes", "list notes", "saved notes",
    # Indonesian
    "catatan", "catatan saya", "catatan ku", "daftar catatan",
    "semua catatan", "catetan",
}

_PC_W = {
    # English
    "pc", "computer", "computers", "desktop", "workstation", "machine",
    # Indonesian
    "komputer", "pc",
}

_PC_ON_W = {
    # English
    "turn on", "turnon", "power on", "poweron", "boot", "start",
    "wake", "wake up", "wakeup", "switch on",
    # Indonesian
    "hidupkan", "nyalakan", "nyalain", "start", "hidupin", "booting",
}

_PC_OFF_W = {
    # English
    "turn off", "turnoff", "power off", "poweroff", "shut down",
    "shutdown", "switch off", "switchoff", "kill", "stop",
    # Indonesian
    "matikan", "matiin", "padamkan", "shutdown", "tutup", "nonaktifkan",
}

_PC_STATUS_W = {
    # English
    "status", "running", "on?", "is on", "is off", "state",
    # Indonesian
    "nyala", "hidup", "mati", "status", "kondisi", "keadaan",
}

_HELP_W = {
    # English
    "help", "helps", "commands", "what can you", "what can i",
    "what you do", "what can i do", "how to", "guide",
    # Indonesian
    "bantuan", "tolong", "perintah", "perintah apa", "bisa apa",
    "cara pakai", "panduan", "help",
}

_MY_W = {
    # English
    "my", "mine",
    # Indonesian
    "saya", "aku", "gue", "gw", "ku", "punya saya",
}


def _normalize(text: str) -> str:
    """Normalize: lowercase, strip punctuation, collapse whitespace.
    
    Keyword variants (including typos) are handled directly in the
    keyword sets — no separate typo normalization needed.
    """
    t = text.lower().strip()
    # Remove common punctuation but keep internal spaces
    t = re.sub(r'[\?\!\.\,\;\:]', '', t)
    t = re.sub(r'\s+', ' ', t)
    return t.strip()


def _has_w(t: str, s: set, min_c: int = 1) -> bool:
    """Check if text t has >= min_c words from set s (word boundary match)."""
    count = 0
    for w in s:
        if re.search(r'\b' + re.escape(w) + r'\b', t):
            count += 1
            if count >= min_c:
                return True
    return False


def _has_num(t: str) -> int | None:
    """Extract first number."""
    m = re.search(r'(?:nomor\s*|#)?(\d+)', t)
    return int(m.group(1)) if m else None


def _score_agenda_today(t: str) -> float:
    s = 0.0
    # If user mentions tomorrow/besok, this is NOT today
    if _has_w(t, _TOMORROW_W):
        return 0.0
    if _has_w(t, _AGENDA_W) and _has_w(t, _TODAY_W): s = max(s, 0.85)
    if _has_w(t, _SHOW_W) and _has_w(t, _TODAY_W): s = max(s, 0.80)
    if _has_w(t, _SHOW_W) and _has_w(t, _AGENDA_W): s = max(s, 0.80)
    if _has_w(t, _MY_W) and _has_w(t, _AGENDA_W): s = max(s, 0.75)
    if t in ("agenda", "jadwal", "schedule"): s = max(s, 0.90)
    if re.search(r'\bada\s+apa\b', t) and _has_w(t, _TODAY_W): s = max(s, 0.75)
    if _has_w(t, {"what"}) and _has_w(t, _TODAY_W) and _has_w(t, _SHOW_W): s = max(s, 0.75)
    # Penalize if search/remind keyword present (likely not agenda)
    if _has_w(t, _SEARCH_W) and "agenda" not in t: s -= 0.30
    if _has_w(t, _REMIND_CREATE_W): s -= 0.30
    return max(0, s)


def _score_agenda_tomorrow(t: str) -> float:
    s = 0.0
    if _has_w(t, _AGENDA_W) and _has_w(t, _TOMORROW_W): s = max(s, 0.85)
    if _has_w(t, _SHOW_W) and _has_w(t, _TOMORROW_W): s = max(s, 0.80)
    if re.search(r'\bada\s+apa\b', t) and _has_w(t, _TOMORROW_W): s = max(s, 0.75)
    if _has_w(t, _SEARCH_W): s -= 0.30
    return max(0, s)


def _score_agenda_all(t: str) -> float:
    s = 0.0
    if _has_w(t, _AGENDA_W) and _has_w(t, _ALL_W): s = max(s, 0.85)
    if _has_w(t, _SHOW_W) and _has_w(t, _ALL_W): s = max(s, 0.75)
    return max(0, s)


def _score_agenda_done(t: str) -> tuple[float, dict | None]:
    s = 0.0
    num = _has_num(t) if _has_w(t, _DONE_W) else None
    if num is not None: s = max(s, 0.90)
    if _has_w(t, _DONE_W) and _has_w(t, {"all", "semua", "today"}):
        return 0.90, {"action": "agenda_done_all"}
    if s >= 0.90:
        return s, {"action": "agenda_done", "params": {"id": num}}
    return 0, None


def _score_remind_create(t: str) -> float:
    s = 0.0
    has_primary = _has_w(t, _REMIND_CREATE_W)
    has_time = bool(re.search(r'\d+\s*(m|h|s|menit|jam|detik|minutes?|hours?)', t)) or \
               bool(re.search(r'\b(tomorrow|besok|hari ini|lusa|today|tonight|nanti)\b', t))
    if has_primary and has_time: s = max(s, 0.90)
    if has_primary and len(t) > 15: s = max(s, 0.75)
    if has_primary: s = max(s, 0.60)
    # Penalize if search/agenda/list intent
    if _has_w(t, _SEARCH_W): s -= 0.40
    if _has_w(t, _AGENDA_W): s -= 0.30
    if _has_w(t, _ALL_W): s -= 0.30
    if _has_w(t, {"list", "daftar"}): s -= 0.40
    return max(0, s)


def _score_remind_list(t: str) -> float:
    s = 0.0
    if t in ("reminders", "reminder", "reminder saya", "daftar reminder"): s = max(s, 0.90)
    if _has_w(t, _REMIND_LIST_W) and (_has_w(t, _SHOW_W) or _has_w(t, _MY_W) or _has_w(t, {"daftar"})): s = max(s, 0.80)
    if _has_w(t, _REMIND_LIST_W): s = max(s, 0.50)
    if _has_w(t, _REMIND_CREATE_W) and _has_w(t, {"my", "saya", "list", "daftar"}): s = max(s, 0.75)
    # Penalize if time/create words present (likely remind_create)
    if _has_w(t, {"in", "at", "jam", "besok", "tomorrow", "nanti"}): s -= 0.30
    return max(0, s)


def _score_search(t: str) -> float:
    s = 0.0
    has_primary = _has_w(t, _SEARCH_W)
    query_len = len(t) - 6  # rough query length after "search "
    if has_primary and query_len > 10: s = max(s, 0.85)
    if has_primary and query_len > 3: s = max(s, 0.75)
    if has_primary: s = max(s, 0.55)
    # Penalize if agenda/note/remind keywords present (those take priority)
    if _has_w(t, _AGENDA_W): s -= 0.35
    if _has_w(t, _NOTE_SAVE_W): s -= 0.35
    if _has_w(t, _REMIND_CREATE_W): s -= 0.35
    if t.strip() in ("cari", "search", "find"): s = 0  # too vague alone
    return max(0, s)


def _score_note_save(t: str) -> float:
    s = 0.0
    has_primary = _has_w(t, _NOTE_SAVE_W)
    has_content = len(t) > 10
    if has_primary and has_content: s = max(s, 0.80)
    if has_primary: s = max(s, 0.55)
    # Penalize if remind/search/agenda
    if _has_w(t, _REMIND_CREATE_W): s -= 0.40
    if _has_w(t, _SEARCH_W): s -= 0.35
    if _has_w(t, {"list", "daftar", "show", "tampilkan"}): s -= 0.30
    return max(0, s)


def _score_note_list(t: str) -> float:
    s = 0.0
    if t in ("notes", "catatan", "my notes", "catatan saya"): s = max(s, 0.90)
    if _has_w(t, _NOTE_LIST_W) and (_has_w(t, _SHOW_W) or _has_w(t, _MY_W) or _has_w(t, {"daftar"})): s = max(s, 0.80)
    if _has_w(t, _NOTE_LIST_W): s = max(s, 0.50)
    if _has_w(t, _NOTE_SAVE_W): s -= 0.30
    return max(0, s)


def _score_pc_control(t: str) -> tuple[float, str | None]:
    s = 0.0
    action = None
    has_device = _has_w(t, _PC_W)
    has_on = _has_w(t, _PC_ON_W)
    has_off = _has_w(t, _PC_OFF_W)
    has_status = _has_w(t, _PC_STATUS_W)
    
    if has_on and has_device: s = max(s, 0.90); action = "pc_on"
    if has_off and has_device: s = max(s, 0.90); action = "pc_off"
    if has_device and has_status: s = max(s, 0.85); action = "pc_status"
    if "pc" in t and "status" in t: s = max(s, 0.80); action = "pc_status"
    return s, action


def _score_help(t: str) -> float:
    if _has_w(t, _HELP_W):
        return 0.85
    if t in ("help", "bantuan", "tolong", "commands", "perintah"):
        return 0.90
    return 0


def _detect_local_intent(text: str) -> dict | None:
    """Detect intent via confidence scoring. Returns action dict or None → Gemini.
    
    All features scored independently (0.0 - 1.0).
    - Best score > 0.75 AND gap > 0.15 → route
    - Otherwise → Gemini (ambiguous or low confidence)
    """
    t = _normalize(text)
    
    # Skip very short noise (unless it's a known command)
    if len(t) < 3:
        return None
    if len(t) < 5 and t not in ("agenda", "jadwal", "help", "ping", "notes", "catatan", "status", "schedule"):
        return None
    
    # ── Score all features ────────────────────────────────
    candidates: list[tuple[float, dict]] = []
    
    # Priority 1: Exact command words (highest confidence)
    if t == "ping": candidates.append((1.0, {"action": "ping"}))
    if t == "status": candidates.append((1.0, {"action": "status"}))
    if t == "help": candidates.append((1.0, {"action": "help"}))
    
    # Agenda
    candidates.append((_score_agenda_today(t), {"action": "agenda_today"}))
    candidates.append((_score_agenda_tomorrow(t), {"action": "agenda_tomorrow"}))
    candidates.append((_score_agenda_all(t), {"action": "agenda_all"}))
    s_done, done_action = _score_agenda_done(t)
    if done_action:
        candidates.append((s_done, done_action))
    
    # Reminders
    candidates.append((_score_remind_create(t), {"action": "remind_create"}))
    candidates.append((_score_remind_list(t), {"action": "remind_list"}))
    
    # Notes
    candidates.append((_score_note_save(t), {"action": "note_save"}))
    candidates.append((_score_note_list(t), {"action": "note_list"}))
    
    # Search
    candidates.append((_score_search(t), {"action": "search"}))
    
    # PC control
    s_pc, pc_action = _score_pc_control(t)
    if pc_action:
        candidates.append((s_pc, {"action": pc_action}))
    
    # Help
    candidates.append((_score_help(t), {"action": "help"}))
    
    # ── Filter + rank ────────────────────────────────────
    MIN_CONFIDENCE = 0.75
    AMBIGUITY_GAP = 0.15
    
    # Filter: only keep above threshold
    valid = [(s, a) for s, a in candidates if s >= MIN_CONFIDENCE]
    
    if not valid:
        return None  # → Gemini
    
    # Sort by score descending
    valid.sort(key=lambda x: -x[0])
    
    # If top two are too close → ambiguous → Gemini
    if len(valid) > 1 and valid[0][0] - valid[1][0] < AMBIGUITY_GAP:
        logger.debug("Ambiguous intent: %.2f vs %.2f (%s vs %s)",
                    valid[0][0], valid[1][0],
                    valid[0][1].get("action"), valid[1][1].get("action"))
        return None  # → Gemini
    
    logger.debug("Local intent: %s (score=%.2f)", valid[0][1].get("action"), valid[0][0])
    return valid[0][1]
