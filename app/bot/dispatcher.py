import logging


from app.config import settings
from app.plugins.base import PluginRegistry
from app.plugins.brain import state as pending_state
from app.plugins.brain.picker import (
    build_confirm_keyboard,
    build_hour_keyboard,
    build_minute_keyboard,
    is_picker_callback,
    parse_callback,
)

logger = logging.getLogger(__name__)


async def dispatch(update) -> str | None:
    """Route incoming messages to the right handler.

    Priority:
    1. Pending state — but ONLY if message looks like a reply
    2. Slash commands → resolved to plugin
    3. Free text → BrainPlugin
    """
    message = update.message or update.edited_message
    if not message or not message.text:
        return None

    text = message.text.strip()
    chat_id = message.chat_id

    # ── 1. Check pending state — only if message IS a reply ──
    state = pending_state.get(chat_id)
    if state and _is_pending_reply(text):
        return await _handle_pending_reply(chat_id, text, state)
    elif state:
        # Message looks like new content — auto-cancel old pending
        pending_state.clear(chat_id)
        logger.info("Auto-cancelled pending for new message: %.80s", text)

    # Build context for normal routing
    from app.bot.context import build_context
    ctx = build_context(update, text)

    # ── 2. Slash commands ────────────────────────────────────
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

    # ── 3. Free text → BrainPlugin ───────────────────────────
    registry = PluginRegistry.get()
    brain = registry.get_plugin("brain")
    if brain:
        try:
            reply = await brain.handle(ctx)
            return reply
        except Exception as e:
            logger.error("Brain failed: %s", e, exc_info=True)
    return None


# ── Detect if message is a reply to pending or fresh content ──────


def _is_pending_reply(text: str) -> bool:
    """Check if a message looks like a reply to a pending question.

    Returns True if message is short and looks like a confirmation response.
    Returns False if message looks like fresh content (forwarded, agenda, etc).
    """
    lower = text.strip().lower()

    # Commands are always fresh
    if text.startswith("/"):
        return False

    # Long messages = new content, not a reply
    if len(text) > 100:
        return False

    # Messages with agenda/date formatting = new content
    if any(sym in text for sym in ("📅", "🗓️", "📋", "⏰", "🗒")):
        return False

    # Messages that look like dates = new content
    import re
    if re.search(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", text):
        return False
    if re.search(r"\b(januari|februari|maret|april|mei|juni|juli|agustus|september|oktober|november|desember)", lower):
        return False
    if re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)", lower):
        return False
    if re.search(r"\b(senin|selasa|rabu|kamis|jumat|sabtu|minggu)", lower):
        return False
    if re.search(r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)", lower):
        return False

    # Short yes/no/edit numbers = reply
    return True


# ── Pending reply handling ──────────────────────────────────────────


async def _handle_pending_reply(chat_id: int, text: str, state: dict) -> str | None:
    """Handle a user's reply to a pending bot question."""
    stage = state.get("stage")
    lower = text.lower().strip()

    # ── Cancel any stage ─────────────────────────────────────
    if lower in ("cancel", "no", "never mind", "forget it"):
        pending_state.clear(chat_id)
        return "Alright, cancelled! Send me the info again when you're ready. 👍"

    # ── Confirmation stage ───────────────────────────────────
    if stage == "confirm":
        if lower in ("yes", "y", "yeah", "sure", "do it", "confirm"):
            return await _execute_pending_actions(chat_id, state)
        elif lower.startswith("edit") or lower.startswith("change"):
            # Re-route to brain with correction context
            original = state.get("original_text", "")
            correction = text[len("edit"):].strip() or text
            pending_state.clear(chat_id)
            # Re-send through brain with context
            return await _rebrain_with_correction(chat_id, original, correction)
        else:
            return "Reply 'yes' to confirm, 'edit <change>' to fix something, or 'no' to cancel."

    # ── Asking for time ──────────────────────────────────────
    if stage == "ask_time":
        pending_state.clear(chat_id)
        # Re-send through brain with the time appended
        original = state.get("original_text", "")
        action = state.get("action", {})
        action["time"] = text
        # Process the completed action
        return await _process_single_action(chat_id, action)

    # ── Asking for text ──────────────────────────────────────
    if stage == "ask_text":
        pending_state.clear(chat_id)
        action = state.get("action", {})
        action["text"] = text
        return await _process_single_action(chat_id, action)

    return None


async def _execute_pending_actions(chat_id: int, state: dict) -> str:
    """Execute all actions after user confirmed."""
    from app.plugins.brain.handler import BrainPlugin
    from app.plugins.base import BotContext

    actions = state.get("actions", [])
    pending_state.clear(chat_id)

    brain = PluginRegistry.get().get_plugin("brain")
    if not isinstance(brain, BrainPlugin):
        return "⚠️ Brain not available."

    # Create a minimal context so _route_single has something to work with
    fake_ctx = BotContext(
        chat_id=chat_id,
        user_id=0,
        username="user",
        message_text=state.get("original_text", ""),
        is_group=False,
        raw_update=None,
    )
    brain._original_ctx = fake_ctx

    replies = []
    for item in actions:
        action = item.get("action") or item.get("type", "")
        if action:
            try:
                reply = await brain._route_single(action, {k: v for k, v in item.items() if k != "action"})
                if reply:
                    replies.append(reply)
            except Exception as e:
                logger.error("Action '%s' failed on confirm: %s", action, e)
                replies.append(f"❌ {action} failed — try again?")

    if not replies:
        return "✅ Done! Nothing to do though. 🤔"

    if len(replies) == 1:
        return replies[0]

    summary = "✅ *Done!*\n\n" + "\n\n".join(
        f"{i+1}. {r}" for i, r in enumerate(replies)
    )
    return summary


async def _process_single_action(chat_id: int, action: dict) -> str | None:
    """Process a single validated action."""
    from app.plugins.brain.handler import BrainPlugin
    from app.plugins.base import BotContext

    brain = PluginRegistry.get().get_plugin("brain")
    if not isinstance(brain, BrainPlugin):
        return None

    action_name = action.pop("action", None) or action.pop("type", None)
    if not action_name:
        return None

    brain._original_ctx = BotContext(
        chat_id=chat_id,
        user_id=0,
        username="user",
        message_text="",
        is_group=False,
        raw_update=None,
    )
    return await brain._route_single(action_name, action)


async def _rebrain_with_correction(chat_id: int, original: str, correction: str) -> str | None:
    """Re-process original message with user's correction."""
    from app.bot.context import build_context

    # Create a fake update-like context
    class FakeMessage:
        def __init__(self):
            self.chat_id = chat_id
            self.text = f"{original}\n\nCorrection: {correction}"
            self.from_user = type("u", (), {"id": 0, "username": "user"})()

    class FakeUpdate:
        def __init__(self):
            self.message = FakeMessage()
            self.edited_message = None

    brain = PluginRegistry.get().get_plugin("brain")
    if not brain:
        return None

    ctx = build_context(FakeUpdate(), FakeMessage().text)
    try:
        return await brain.handle(ctx)
    except Exception as e:
        logger.error("Rebrain failed: %s", e)
        return "⚠️ Sorry, couldn't process that. Try again!"


# ── Callback query handler (inline keyboard taps) ─────────────────


async def handle_callback(cq) -> tuple[str | None, dict | None]:
    """Handle inline keyboard callback from the time picker.

    Returns: (reply_text, new_keyboard_or_None)
    - If None, None: no changes needed
    - If reply_text, None: final answer, remove keyboard
    - If reply_text, keyboard: update message with new text + keyboard
    """
    chat_id = cq.message.chat_id
    data = cq.data
    state = pending_state.get(chat_id)

    if not state or not is_picker_callback(data):
        return ("⏳ This expired! Send your request again.", None)

    action, value = parse_callback(data)

    # ── Cancel ───────────────────────────────────────────
    if action == "cancel":
        pending_state.clear(chat_id)
        return ("Alright, cancelled! 👍 Send me the info again when ready.", None)

    # ── User wants to type instead ───────────────────────
    if action == "type":
        pending_state.set(chat_id, {**state, "stage": "ask_time"})
        return ("⏰ Type the time (e.g., 9am, 14:30, in 2 hours):", None)

    # ── Period selected → show hours ─────────────────────
    if action == "period":
        pending_state.set(chat_id, {**state, "period": value, "stage": "pick_hour"})
        kb = build_hour_keyboard(value)
        return ("⏰ Which hour?", kb.to_dict() if hasattr(kb, 'to_dict') else kb)

    # ── Hour selected → show minutes ─────────────────────
    if action == "hour":
        pending_state.set(chat_id, {**state, "hour": value, "stage": "pick_minute"})
        kb = build_minute_keyboard()
        return ("⏰ Pick minutes:", kb.to_dict() if hasattr(kb, 'to_dict') else kb)

    # ── Minute selected → show confirm ───────────────────
    if action == "minute":
        hour = state.get("hour", "9")
        minute = value
        time_str = f"{int(hour):02d}:{minute}"
        pending_state.set(chat_id, {**state, "time": time_str, "stage": "confirm"})

        action_data = state.get("action", {})
        text = action_data.get("text", "reminder")

        reply = (
            f"⏰ {time_str}. Sound good?\n"
            f"📋 {text}\n"
            f"Reply 'yes' to confirm, 'no' to cancel."
        )
        kb = build_confirm_keyboard()
        return (reply, kb.to_dict() if hasattr(kb, 'to_dict') else kb)

    # ── Done / confirmed via button ──────────────────────
    if action == "done":
        return await _execute_pending_actions(chat_id, state), None

    return (None, None)
