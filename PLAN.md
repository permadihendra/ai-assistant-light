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
