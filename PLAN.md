# BrainPlugin v2 — Intent-to-Action Router

## Current State

The BrainPlugin (v1) is a passive conversational layer:
- User sends free text → Gemini responds conversationally
- If the user asks about a feature, it tells them to use a `/command`
- **User must retype** their intent as a command

## Goal

Make the BrainPlugin an **active router** that executes commands on the user's behalf:
- User sends free text → Gemini classifies intent + extracts params
- BrainPlugin routes to the correct plugin internally
- **One message, one LLM call, one reply**

---

## Architecture

```
User: "search for fastapi python"
  ↓
BrainPlugin.handle()
  ↓
Gemini 2.5 Flash
  ↓  structured JSON (one LLM call)
{"action": "search", "params": {"query": "fastapi python"}}
  ↓
BrainPlugin._route(action, params)
  ↓
WebSearchPlugin.handle(modified_context)
  ↓
Result → Telegram reply
```

### Action -> Plugin Mapping

| `action` value | Plugin | Method | Example params |
|---|---|---|---|
| `chat` | BrainPlugin | Responds directly via LLM text | — |
| `search` | WebSearchPlugin | `handle()` with modified message text | `{"query": "..."}` |
| `search` | WebSearchPlugin | `handle()` with modified message text | `{"query": "fastapi python"}` |
| `remind_create` | ReminderPlugin | `handle()` with modified message text | `{"time": "10m", "text": "buy milk"}` |
| `remind_list` | ReminderPlugin | `handle("/reminders")` | — |
| `remind_cancel` | ReminderPlugin | `handle("/cancel 1")` | `{"id": 1}` |
| `summarize` | SummarizerPlugin | `handle("/summarize")` | — |
| `help` | SystemPlugin | `handle("/help")` | — |
| `ping` | SystemPlugin | `handle("/ping")` | — |
| `status` | SystemPlugin | `handle("/status")` | — |

### Key Design Principle

**BrainPlugin never re-implements plugin logic.** It only routes by rewriting the `BotContext.message_text` to look like the equivalent slash command, then calls the target plugin's `handle()` method.

This means:
- WebSearchPlugin still works via `/search <query>` AND via brain routing
- ReminderPlugin still works via `/remind 10m buy milk` AND via brain
- All existing tests pass unchanged
- Brain is just a "smart prefix" — no duplicated code

---

## Gemini System Prompt (v2)

The prompt guides Gemini to output structured JSON:

```
You are the AI brain of a Telegram bot. Route user messages to the best action.

Available actions:
- {"action": "chat", "text": "reply text"} — general conversation
- {"action": "search", "query": "..."} — web search (DuckDuckGo)
- {"action": "remind_create", "time": "10m", "text": "what to do"} — set reminder
- {"action": "remind_list"} — list active reminders
- {"action": "summarize"} — summarize recent messages
- {"action": "ping", ...} — health check OR
- {"action": "help", ...} — show command list
- {"action": "status", ...} — show bot status

Rules:
1. Respond in the user's language.
2. For "chat": write a friendly short reply as the "text" value.
3. For "search": extract the search query.
4. For "remind_create": parse time like "10m", "2h", "tomorrow 09:00".
5. If unsure, use "chat" with a helpful response.
6. Output ONLY valid JSON, no markdown, no extra text.
```

---

## Flow Details

### BrainPlugin.handle()

```
1. Call Gemini with system prompt + user message
2. Parse JSON response
3. Switch on action:
   "chat"        → return response.text directly
   "search"      → rewrite ctx.message_text = "/search <query>"
                    → WebSearchPlugin.handle(ctx)
                    → return result
   "remind_create" → rewrite ctx.message_text = "/remind <time> <text>"
                      → ReminderPlugin.handle(ctx)
                      → return result
   ... (same for other actions)
4. If JSON parse fails → fall back to "chat" action
```

### Routing mechanism

```python
class BrainPlugin(Plugin):
    _action_map = {
        "search": ("web_search", "/search {query}"),
        "remind_create": ("reminder", "/remind {time} {text}"),
        "remind_list": ("reminder", "/reminders"),
        "summarize": ("summarizer", "/summarize"),
        "ping": ("system", "/ping"),
        "help": ("system", "/help"),
        "status": ("system", "/status"),
    }

    async def _route(self, action: str, params: dict) -> str | None:
        if action == "chat":
            return params.get("text")

        mapping = self._action_map.get(action)
        if not mapping:
            return None

        plugin_name, cmd_template = mapping
        plugin = PluginRegistry.get().get_plugin(plugin_name)
        if not plugin:
            return None

        # Rewrite message_text to look like a command
        cmd_text = cmd_template.format(**params)
        ctx = BotContext(
            chat_id=self._original_ctx.chat_id,
            user_id=self._original_ctx.user_id,
            username=self._original_ctx.username,
            message_text=cmd_text,
            is_group=self._original_ctx.is_group,
            raw_update=self._original_ctx.raw_update,
        )
        return await plugin.handle(ctx)
```

---

## Edge Cases & Fallbacks

| Scenario | Handling |
|---|---|
| Gemini returns invalid JSON | Try regex extraction; if fails → return as `chat` text |
| Gemini returns unknown action | Return as `chat` text |
| Target plugin raises exception | Log error, return "Sorry, couldn't do that" |
| Params missing (e.g., no query for search) | Return `chat`: "What would you like me to search for?" |
| Rate limited by Gemini | Return cached/fallback response |
| Empty params | Prompt user via chat response |

---

## Files to Change

### BrainPlugin v2 (Core)

| File | What |
|---|---|
| `app/plugins/brain/handler.py` | Full rewrite: JSON prompt + routing logic |
| `app/llm/prompts.py` | Update `BRAIN_SYSTEM_PROMPT` to v2 |

### PC Power Control

| File | What |
|---|---|
| `scripts/ping-pc.sh` | **Create** — Ping-based PC status check |
| `app/plugins/script_runner/handler.py` | **Update** — Allow `.py` scripts + use right interpreter |
| `app/plugins/brain/handler.py` | **Update** — Add PC actions to `_action_map` |
| `app/llm/prompts.py` | **Update** — Add pc_on, pc_off, pc_status actions |
| `.env` | **Update** — Add `PC_IP_ADDRESS` |
| `.env.example` | **Update** — Add PC_IP_ADDRESS placeholder |
| `README.md` | **Update** — Document PC power control |

**No changes needed to:**
- Existing plugins (WebSearch, Reminder, Summarizer, System)
- Dispatcher, gateway, config, main.py
- Tests

---

## Risk Analysis

| Risk | Mitigation |
|---|---|
| Gemini returns malformed JSON | Regex fallback + graceful `chat` fallback |
| Brain "hijacks" messages that should be commands | Dispatcher checks for `/` prefix first — commands never reach brain |
| User says "delete everything" — brain routes to wrong action | No destructive actions exist in plugins. `/run` requires ALLOWED_CHAT_IDS |
| Extra latency (LLM call + plugin execution) | Single LLM call, plugin runs in same event loop — total < 2s |
| LLM cost (now we use LLM for EVERY message) | Already using free Gemini tier (1,500 req/day). Brain was already calling LLM for every message — now it just does more with the same call. |

---

## Before vs After

| Message | Before (v1) | After (v2) |
|---|---|---|
| `"search for fastapi"` | "Use /search fastapi" | 🔍 [search results] |
| `"remind me in 10m to check oven"` | "Use /remind 10m check oven" | ✅ Reminder set! |
| `"list my reminders"` | "Use /reminders" | 📋 Your reminders: ... |
| `"hello!"` | "Hello! I can help with..." | "Hello! How can I help?" |
| `"summarize today"` | "Use /summarize" | 📊 Summary of last N messages |
| `"turn on my pc"` | — (no handler) | ✅ PC powered on via GPIO relay |
| `"turn off pc"` | — (no handler) | ✅ PC powered off |
| `"pc status"` | — (no handler) | ℹ️ PC is on/off (GPIO sensor) |

---

# PC Power Control via GPIO Relay

## Overview

Control a desktop PC's power button via a relay module connected to Raspberry Pi GPIO.
The bot executes Python scripts (already exist at `scripts/raspberrypi/gpio-scripts/`)
that use `RPi.GPIO` to toggle a relay → PC power on/off.

## Existing Scripts (already cloned)

The user already has these scripts from `github.com/permadihendra/raspberrypi`:

| File | Description | GPIO Pin | Duration |
|---|---|---|---|
| `scripts/raspberrypi/gpio-scripts/relay-poweron-pc.py` | Short press (power on) | GPIO 17 (BCM) | 0.2s hold |
| `scripts/raspberrypi/gpio-scripts/relay-poweroff-pc.py` | Long press (force off) | GPIO 17 (BCM) | 5s hold |

### relay-poweron-pc.py
```python
#!/usr/bin/venv python3
import time
import RPi.GPIO as GPIO

RELAY_PIN = 17
GPIO.setmode(GPIO.BCM)
GPIO.setup(RELAY_PIN, GPIO.OUT)

# relay ON (press button)
GPIO.output(RELAY_PIN, GPIO.LOW)
time.sleep(0.2)
# relay OFF (release button)
GPIO.output(RELAY_PIN, GPIO.HIGH)

GPIO.cleanup()
```

### relay-poweroff-pc.py
```python
#!/usr/bin/venv python3
import time
import RPi.GPIO as GPIO

RELAY_PIN = 17
GPIO.setmode(GPIO.BCM)
GPIO.setup(RELAY_PIN, GPIO.OUT)

try:
    GPIO.output(RELAY_PIN, GPIO.LOW)
    time.sleep(5)
    GPIO.output(RELAY_PIN, GPIO.HIGH)
except KeyboardInterrupt:
    print("interrupted")
finally:
    GPIO.cleanup()
```

## Required Changes to ScriptRunnerPlugin

### Problem
Current `ScriptRunnerPlugin` only allows `.sh` files (regex: `^[a-zA-Z0-9_\\-]+\\.sh$`).
The existing GPIO scripts are Python (`.py`).

### Solution A (Recommended): Add `.py` support
Update the script name regex in `app/plugins/script_runner/handler.py`:
```python
# Before
SCRIPT_NAME_RE = re.compile(r"^[a-zA-Z0-9_\\-]+\\.sh$")

# After
SCRIPT_NAME_RE = re.compile(r"^[a-zA-Z0-9_\\-]+\\.(sh|py)$")
```

Also update execution logic to use the right interpreter:
- `.sh` → `/bin/bash`
- `.py` → Python interpreter from `.venv` or system

### Solution B: Shell wrappers (no code change)
Create wrapper `.sh` scripts that call the Python scripts:

```bash
# scripts/pc-on.sh
#!/bin/bash
cd "$(dirname "$0")/raspberrypi/gpio-scripts"
python3 relay-poweron-pc.py
```

**Recommendation:** Solution A — cleaner, more flexible for future scripts.

## BrainPlugin Integration

### New Actions

| `action` value | Routes To | Natural Language Examples |
|---|---|---|
| `pc_on` | `/run relay-poweron-pc.py` | "turn on my pc", "power on computer", "start my desktop" |
| `pc_off` | `/run relay-poweroff-pc.py` | "turn off pc", "shutdown computer", "power off" |
| `pc_status` | `/run ping-pc.sh` | "is my pc on?", "pc status", "check computer" |

### Action Map Addition

```python
_action_map = {
    # ... existing actions ...
    "pc_on": ("script_runner", "/run relay-poweron-pc.py"),
    "pc_off": ("script_runner", "/run relay-poweroff-pc.py"),
    "pc_status": ("script_runner", "/run ping-pc.sh"),
}
```

### Gemini Prompt Addition

Add to system prompt:
```
- {"action": "pc_on"} — turn on PC via GPIO relay
- {"action": "pc_off"} — turn off PC via GPIO relay
- {"action": "pc_status"} — check if PC is on
```

## PC Status Check

### `scripts/ping-pc.sh` (new)

```bash
#!/bin/bash
# Check if PC is on by pinging it
PC_IP="192.168.1.100"  # ← CHANGE THIS TO YOUR PC'S IP

if ping -c 1 -W 2 "$PC_IP" &>/dev/null; then
    echo "✅ PC is ON"
else
    echo "❌ PC is OFF (or not reachable)"
fi
```

> Update `PC_IP` to match your desktop's local IP address.

## Security

| Concern | Mitigation |
|---|---|
| Unauthorized user turns on/off PC | `ScriptRunnerPlugin` requires `ALLOWED_CHAT_IDS` → only you can run scripts |
| BrainPlugin bypasses auth | Brain routes through `ScriptRunnerPlugin` which enforces auth internally |
| GPIO pin damage | Scripts have built-in delays and `GPIO.cleanup()` |
| Script execution timeout | `SCRIPT_TIMEOUT=10` in `.env` — scripts killed after 10s |

## Hardware Setup

### Wiring

```
Raspberry Pi GPIO          Relay Module
─────────────────          ─────────────
GPIO 17 (pin 11) ────────► IN (signal)
3.3V (pin 1)     ────────► VCC
GND (pin 6)      ────────► GND

Relay COM + NO ────► PC motherboard front-panel header
                       (replace the physical power button)
```

### Pi Permissions

```bash
# RPi.GPIO needs root or /dev/gpiomem access
# If running as systemd service as user pi, add:
sudo usermod -a -G gpio pi

# Or run service as root (edit deploy/ai-assistant.service):
# User=root  (not recommended)
```

## Usage Examples

| Telegram Message | Bot Action |
|---|---|
| `"turn on my pc"` | Brain → `pc_on` → ScriptRunner → `relay-poweron-pc.py` → GPIO relay → PC powers on |
| `"shutdown computer"` | Brain → `pc_off` → ScriptRunner → `relay-poweroff-pc.py` → GPIO relay → PC powers off |
| `"is my pc on?"` | Brain → `pc_status` → ScriptRunner → `ping-pc.sh` → ping result |
| `/run relay-poweron-pc.py` | Direct command (bypasses brain, same result) |
| `/run relay-poweroff-pc.py` | Direct command |

## Files to Create/Change

| File | Action |
|---|---|
| `scripts/ping-pc.sh` | **Create** — Ping-based PC status check |
| `app/plugins/script_runner/handler.py` | **Update** — Allow `.py` scripts + use right interpreter |
| `app/llm/prompts.py` | **Update** — Add pc_on, pc_off, pc_status actions |
| `app/plugins/brain/handler.py` | **Update** — Add PC actions to `_action_map` |
| `.env` | **Update** — Add `PC_IP_ADDRESS=192.168.1.100` |
| `.env.example` | **Update** — Add PC_IP_ADDRESS placeholder |
| `README.md` | **Update** — Document PC power control

---

# Remind + Notes + Personality (remind-notes-features branch)

## Goal

Make every API call count. One Gemini call = maximum useful work:
- Long messages → auto-detect: remind? note? both?
- Notes plugin — save reference info
- Reminders — smart multi-alert (15min + 5min before)
- AI Personality — configurable via `.env`

## Core Principle: One Call To Rule Them All 🏆

```
Before: classify → ask user → user replies → classify again → act = 2-3 API calls
After:  classify + extract + act = 1 API call
```

Gemini returns an `actions[]` array — multiple actions in one response:
```json
{
  "actions": [
    {"action": "note", "text": "wifi password: admin123"},
    {"action": "remind", "time": "tomorrow 10:00", "text": "dentist", "alerts": [15, 5]}
  ]
}
```

Brain iterates through the array and executes each action. **1 call, N actions.**

## Features

### 1. Smart Long-Message Handling

| Message Type | Before | After |
|---|---|---|
| "remind me tomorrow 9am meeting" | Brain chats generically | ✅ Sets reminder + 2 alerts |
| "my wifi is xyz" | Brain chats generically | ✅ Saves as note |
| "dentist tomorrow + my pin is 1234" | Confused | ✅ Reminder + note in 1 call |
| "hello!" | Chats | ✅ Chats (no change) |

Threshold: If message length > 100 chars OR has multiple sentences → triggers smart parsing.

### 2. Notes Plugin 📝

| Command | Description |
|---|---|
| `/notes` | List all saved notes |
| `/note <id>` | View a specific note |
| Brain `:note` route | Save any message as note |

**Storage:** New `notes` table in SQLite:
```sql
CREATE TABLE notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    text TEXT NOT NULL,
    tags TEXT DEFAULT '',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### 3. Multi-Alert Reminders ⏰

Current: single `remind_at` datetime.
New: `alerts` column stores minutes-before as JSON array.

```
reminder: "dentist tomorrow 10am"
  → remind_at = 2026-05-18 10:00
  → alerts = [15, 5]
  → scheduler fires at 09:45 (15min before) + 09:55 (5min before)
  → Final fire at 10:00
```

**Scheduler change:**
- Fires when `remind_at - alert_minutes <= NOW` AND `alert_fired < total_alerts`
- Track fired alerts with an integer counter column

### 4. AI Personality 🎭

New `.env` var:
```env
AI_PERSONALITY=friendly, clear, short, fun, light sarcasm
```

Injected into ALL system prompts:
```python
PERSONALITY = settings.ai_personality or "friendly, clear, concise, fun"

SYSTEM_PROMPT = f"""...
Personality: {PERSONALITY}
..."""
```

**Default:** "Be friendly, clear, and concise. Keep responses short. Use light humor and emojis. A little sarcasm is fine with friends."

## Architecture Changes

### BrainPlugin.handle() — New Flow

```
1. User sends message
2. If short (<100 chars, 1 sentence):
     → Classify as usual (search, remind, chat, etc.)
3. If long (>=100 chars OR multiple sentences):
     → Call Gemini with SMART prompt
     → Expect actions[] array response
     → Iterate actions:
       - remind_create → ReminderPlugin
       - note_save → NotesPlugin
       - chat → respond directly
4. Reply with summary of what was done
```

### BrainPlugin — actions[] Routing

```python
action_map = {
    "note_save": ("notes", None),  # special: save ctx.message_text
    "remind_create": ("reminder", "/remind {time} {text}"),
    "chat": None,  # returned directly
    ...existing actions...
}

async def _route_actions(self, actions: list[dict]) -> list[str]:
    replies = []
    for item in actions:
        action = item.pop("action")
        reply = await self._route_single(action, item)
        if reply:
            replies.append(reply)
    return "\n\n".join(replies) if replies else None
```

## Gemini Prompt — Smart Extraction

```
You are the AI brain. Analyze the user's message and return structured actions.

If message is short/chatty → use "chat" action.
If message contains time-based info → use "remind_create" action.
If message contains reference/save-worthy info → use "note_save" action.
If message has BOTH → return multiple actions in the actions[] array.

Personality: {PERSONALITY}

Respond ONLY with valid JSON:
{"actions": [{"action": "...", ...}]}

Examples:
- "hello" → {"actions": [{"action": "chat", "text": "Hey! 👋"}]}
- "meeting tomorrow 9am" → {"actions": [{"action": "remind_create", "time": "tomorrow 09:00", "text": "meeting", "alerts": [15, 5]}]}
- "wifi is admin123" → {"actions": [{"action": "note_save", "text": "wifi password: admin123"}]}
- "dentist tomorrow 10am and my pin is 1234" → {"actions": [{"action": "remind_create", "time": "tomorrow 10:00", "text": "dentist appointment", "alerts": [15, 5]}, {"action": "note_save", "text": "PIN code: 1234"}]}
```

## Files to Create/Change

| File | What |
|---|---|
| `app/plugins/notes/__init__.py` | **Create** |
| `app/plugins/notes/handler.py` | **Create** — NotesPlugin: save, list, view |
| `app/plugins/brain/handler.py` | **Update** — actions[] routing, long-msg detection |
| `app/plugins/reminder/handler.py` | **Update** — alerts column, multi-fire scheduler |
| `app/scheduler/runner.py` | **Update** — Fire alerts before remind_at |
| `app/llm/prompts.py` | **Update** — Personality template + smart prompt |
| `app/config.py` | **Update** — Add `ai_personality` field |
| `migrations/003_notes.sql` | **Create** — notes table |
| `migrations/004_alerts.sql` | **Create** — alerts column on reminders |
| `.env` | **Update** — Add AI_PERSONALITY |
| `.env.example` | **Update** — Add AI_PERSONALITY |
| `PLAN.md` | This plan |
| `INFORMATION.md` | **Create** — Feature status tracker |

## API Budget Safety 🛡️

Rp50k/month ≈ ~$3 USD ≈ **hundreds of thousands** of Gemini calls.

| Feature | Calls per use | Monthly calls (est.) |
|---|---|---|
| Casual chat | 1 | ~300 |
| Smart parsing (notes+remind) | 1 | ~50 |
| Search | 1-2 | ~100 |
| Summarizer | 1 | ~30 |
| PC control | 1 | ~20 |
| **Total** | | **~500 calls** |

**Cost:** ~$0.05/month. You're safe. ✅

---

# Validation + Confirmation + Time Picker

## Problem

Gemini sometimes returns incomplete data:
```json
{"action": "remind_create", "text": "meeting"}
// Missing time! Bad data hits SQLite.
```

## Solution: 3 Gates Before DB Write

```
Gemini actions[] ──► Gate 1: Required params? ──► Missing? Ask user
                           │                           │
                      Has all? ←───────────────────────┘
                           │
                      ┌────┴────┐
                      │         │
                   Gate 2     Gate 3
                   Confirm    Ambiguous time?
                   with user    → Picker
                      │         │
                      └────┬────┘
                           │
                      Write to DB
                           │
                   "✅ Done! Here's what..."
```

### Gate 1 — Required Params Validation

| Action | Required | If Missing | Bot Says |
|---|---|---|---|
| `remind_create` | `text` + `time` | Missing time | "⏰ When? (today, tomorrow 9am, or June 1st)" |
| `remind_create` | `text` + `time` | Missing text | "📋 Remind you about what?" |
| `note_save` | `text` | Empty | "📝 What should I save?" |
| `search` | `query` | Empty | "🔍 What should I search for?" |

### Gate 2 — Confirmation Before Write

After all params are valid, show preview and ask:

```
Bot:  Here's what I'll set:
      📋 Dentist appointment
      ⏰ Tomorrow, 09:00
      🔔 15min + 5min before
      
      Reply 'yes' to confirm, or tell me what to change.

You:  yes
Bot:  ✅ Reminder #42 set!

--- or ---

You:  no, it's at 10am
Bot:  Got it! Let me fix that...
      (→ re-runs Gemini with correction context)
```

### Gate 3 — Inline Keyboard Time Picker

Telegram has **no native date/time picker**. But we build one with inline keyboards:

```
Gemini returns: time="tomorrow" (no hour specified)
Bot:  "⏰ What time tomorrow?"
      
      [🌅 6-12] [☀️ 12-18] [🌙 18-00]
      
      You tap [🌅 6-12]
Bot:  "Which hour?"
      [6] [7] [8] [9] [10] [11] [12]
      
      You tap [9]
Bot:  "Minutes?"
      [00] [15] [30] [45]
      
      You tap [00]
Bot:  ✅ 9:00 tomorrow. Sound good?
      [✅ Yes] [✏️ Edit]
```

**Fallback:** If user prefers typing, they can just send "9am" instead of tapping buttons.

## Pending State (In-Memory)

```python
# app/plugins/brain/state.py

_pending: dict[int, dict] = {}
# {chat_id: {"actions": [...], "stage": "confirm" | "ask_time" | "ask_text", ...}}

# Key: chat_id, Value: current conversation state
# Lost on restart — user just re-sends their message. Safe.
```

| Stage | What Bot Is Waiting For |
|---|---|
| `ask_time` | User to specify a time |
| `ask_text` | User to specify reminder/note text |
| `confirm` | User to reply "yes" or "no" |
| `pick_hour` | User to tap an hour on the picker |
| `pick_minute` | User to tap minutes on the picker |

## Picker Keyboard Design

```python
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def build_time_picker():
    """3-step picker: period → hour → minutes"""
    kb = [
        [InlineKeyboardButton("🌅 06-12", callback_data="period_morning"),
         InlineKeyboardButton("☀️ 12-18", callback_data="period_afternoon"),
         InlineKeyboardButton("🌙 18-00", callback_data="period_evening")],
    ]
    return InlineKeyboardMarkup(kb)
```

## Multi-Action Summary

When brain executes multiple actions, show a clean summary:

```
Bot:  ✅ Done 2 things:
      
      📝 Note #5 saved ✅
        └─ wifi: admin123
      
      ✅ Reminder #42 set!
        📋 Meeting with the team
        ⏰ Tomorrow, 09:00
        🔔 15min + 5min before
```

## Partial Success

If one action fails and another succeeds:
```
Bot:  ⚠️ Partial success:
      
      ✅ Note #5 saved
      ❌ Reminder failed — missing time. Try again?
```

## Files to Create/Change

| File | What |
|---|---|
| `app/plugins/brain/state.py` | **Create** — Pending state manager |
| `app/plugins/brain/picker.py` | **Create** — Inline keyboard time picker |
| `app/plugins/brain/handler.py` | **Update** — Validation gates + pending flow |
| `app/plugins/notes/handler.py` | **Update** — Return note_id in feedback |
| `app/plugins/reminder/handler.py` | **Update** — Return reminder_id in feedback |
| `app/bot/dispatcher.py` | **Update** — Check pending state before brain |
| `app/bot/gateway.py` | **Update** — Handle callback queries |
| `INFORMATION.md` | Update status |
| `PLAN.md` | This plan |

## Edge Cases

| Scenario | What Happens |
|---|---|
| Time is "tomorrow" without hour | Picker triggers for hour selection |
| User says "no" at confirm | Pending cleared: "Alright, cancelled! Send again." |
| User says "change time to 10am" | Re-runs Gemini with correction context |
| Bot restarts mid-flow | Pending lost — user re-sends. No data corruption. |
| Multiple actions, one fails | Partial success with ❌ indicator |
| User ignores bot's question | Next message starts fresh (clears old pending) |
| Picker callback arrives late | Validate pending still exists; ignore if stale |

---

# Refine /reminders + Link Reminder to Source

## Problem 1: `/reminders` Output

Current format is cluttered:
```
📋 *Your reminders:*
  `1` — Briefing tim — <t:1717200000:R>
  `2` — Meeting klien — <t:1717286400:R>
```

Wanted: clean table with proper columns:
```
📋 *Your Reminders*
┌──────┬──────────────────────────┬──────────────────┐
│ ID   │ Agenda                   │ Time             │
├──────┼──────────────────────────┼──────────────────┤
│ #1   │ Briefing tim dengan klien│ Mon, 1 Jun 09:00 │
│ #2   │ Meeting klien            │ Tue, 2 Jun 10:00 │
│ #3   │ Workshop Digitalisasi    │ Wed, 3 Jun 09:00 │
└──────┴──────────────────────────┴──────────────────┘
🔔 Each alerts 10min before
/cancel <id> to cancel, /note <id> for more detail
```

Since Telegram Markdown doesn't support tables natively, use a **monospace code block** with aligned columns, or a clean **bullet list with consistent formatting**:

```
📋 *Your Reminders*
  #1  Briefing tim — Mon, 1 Jun 09:00  🔔 10min
  #2  Meeting klien — Tue, 2 Jun 10:00  🔔 10min
  #3  Workshop      — Wed, 3 Jun 09:00  🔔 10min

Use /cancel <id> or /note <id> for details.
```

## Problem 2: Link Reminder to Source Message

When Gemini distills a forwarded agenda, details can get lost:
```
Original: "📅 SENIN, 1 JUNI 2024
09:00 - Briefing tim dengan klien membahas proposal project
10:00 - Meeting internal review progress sprint"

Saved as: "Briefing tim dengan klien"  ← details lost!
```

### Solution: Store `source_text` + `/note <id>` for reminders

**New column:** `source_text TEXT` in reminders table. Stores the original full message.

**Flow:**
```
1. User forwards agenda
2. Brain distills → saves reminder with distilled text + source_text
3. User types /note 2
   Bot: 📌 *Reminder #2 source:*
        Briefing tim dengan klien membahas proposal project
```

**Changes:**
- Migration `005_source_text.sql` — add `source_text` column
- `ReminderPlugin.create_reminder()` — accept `source_text` param
- `BrainPlugin._handle_remind_create()` — pass original message as source
- `NotesPlugin` or `ReminderPlugin` — `/note <id>` shows reminder source
- `ReminderPlugin._list_reminders()` — cleaner table format

## Files to Change

| File | What |
|---|---|
| `migrations/005_source_text.sql` | **Create** — add source_text column |
| `app/database.py` | Runs new migration |
| `app/plugins/reminder/handler.py` | **Update** — cleaner list, accept source_text, /note for reminders |
| `app/plugins/brain/handler.py` | **Update** — pass original_text as source |
| `app/plugins/notes/handler.py` | **Update** — /note for BOTH notes and reminders |
| `INFORMATION.md` | Update status |

## UX Flow

```
User:  *Info Agenda TR3* 3 events...
Bot:   Preview → confirm
User:  yes
Bot:   ✅ 3 reminders set!
       1. ✅ Peresmian (Sat 17 Mei 12:30)
       2. ✅ Rapat Evaluasi (Sun 18 Mei 08:00)
       3. ✅ Workshop (Mon 19 Mei 09:00)
       Use /note <id> to see original source.

User:  /note 2
Bot:   📌 *Reminder #2 — source message*
       ⏰ Sun, 18 Mei 2026 at 08:00
       🔔 10min before
       
       Original:
       > Rapat Evaluasi progress sprint
       > dengan tim developer

User:  /reminders
Bot:   📋 *Your Reminders*
       #1  Peresmian Operasionalisasi — Sat 17 Mei 12:30
       #2  Rapat Evaluasi              — Sun 18 Mei 08:00
       #3  Workshop Digitalisasi       — Mon 19 Mei 09:00
       🔔 10min before each
       /cancel <id> | /note <id> for source
```
