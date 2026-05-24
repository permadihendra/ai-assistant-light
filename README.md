# ai-assistant-light

> Lightweight AI assistant for Raspberry Pi 3B — Telegram bot interface, cloud LLM, extensible plugins.

**Status:** ✅ Working | **Idle RAM:** ~100 MB | **Peak:** ≤ 500 MB
**Stack:** Python 3.11+ · FastAPI · SQLite · aiosqlite · httpx · APScheduler

---

## Features

| Plugin | Commands / Triggers | Description |
|---|---|---|
| **System** | `/start`, `/help`, `/ping`, `/status` | Basic bot commands |
| **Brain** _(AI Router)_ | Any free text | Understands language → routes to right plugin automatically |
| **Web Search** | `/search <query>` or _"search for ..."_ | DuckDuckGo search (free, no API key) with optional LLM synthesis |
| **Reminder** | `/remind <time> <msg>` or _"remind me..."_ | Set reminders with bilingual time parser (ENG/ID) |
| **Reminder** | `/reminders` | List active reminders with alert countdown |
| **Reminder** | `/cancel <id>` | Cancel a reminder by ID |
| **Notes** | `/notes`, `/note <id>` | Save reference info; also view reminder source messages |
| **Summarizer** | `/summarize` | Summarize recent group chat messages via LLM |
| **Summarizer** | `/lastsummary` | Retrieve last saved summary |
| **Script Runner** | `/run <script>` | Execute sandboxed `.sh` / `.py` scripts (admin-only) |
| **PC Control** | _"turn on/off my pc"_ | GPIO relay via Raspberry Pi (requires hardware) |

## LLM Providers

6 cloud providers via raw `httpx` — no SDKs, no heavy dependencies.

| Provider | Env Variable | Default Model |
|---|---|---|
| Anthropic | `ANTHROPIC_API_KEY` | Claude 3.5 Haiku |
| OpenAI | `OPENAI_API_KEY` | GPT-4o-mini |
| OpenRouter | `OPENROUTER_API_KEY` | 100+ models (many free) |
| **Google Gemini** ★ | `GEMINI_API_KEY` | **Gemini 2.5 Flash** (free tier, 1,500 req/day) |
| OpenCode-Go | `OPENCODE_BASE_URL` | Self-hosted or cloud |
| Zen | `ZEN_BASE_URL` | Self-hosted, key optional |

> ★ **Recommended** — Gemini 2.5 Flash is the default. Free tier needs no credit card.

## AI Personality 🎭

Configurable via `AI_PERSONALITY` in `.env`. Injected into all LLM prompts:

```
AI_PERSONALITY=friendly, clear, concise, fun, light sarcasm
```

Default: friendly, clear, concise, light humor and emojis.

## Smart Natural Language Understanding 🧠

The **BrainPlugin** intercepts every free-text message and uses Gemini to understand intent:

| You say… | Bot does… |
|---|---|
| "search for fastapi python" | 🔍 Web search results |
| "remind me in 10m to check oven" | ✅ Reminder set with 10min alert |
| "list my reminders" | 📋 Shows active reminders |
| "turn on my pc" | 💻 GPIO relay → PC powers on |
| "📅 SENIN, 1 JUNI 2026\n09:00 - Briefing..." | 📅 Extracts all events → multi-reminder preview |
| "hello!" | 👋 Casual chat reply |

**Bilingual** — detects Indonesian vs English automatically. Responds in the same language.

**Confirmation flow** — before creating reminders/notes, bot shows a preview and asks "yes" or "no".

**Inline time picker** — if time is vague (e.g. "tomorrow" without hour), bot shows interactive buttons to pick period → hour → minute.

## Web Search

Default provider is **DuckDuckGo** — completely free, no API key needed.
Optionally switch to Brave Search by adding `BRAVE_API_KEY` to `.env`.

## PC Power Control 💻

Requires a relay module on Raspberry Pi GPIO 17. Scripts at `scripts/raspberrypi/gpio-scripts/`:

| Action | Script | GPIO Hold |
|---|---|---|
| Power ON | `relay-poweron-pc.py` | 0.2s |
| Power OFF (force) | `relay-poweroff-pc.py` | 5s |
| Status check | `ping-pc.sh` | Pings `PC_IP_ADDRESS` |

Brain routes "turn on my pc" / "shutdown" / "is my pc on?" through ScriptRunnerPlugin (requires `ALLOWED_CHAT_IDS`).

Set `PC_IP_ADDRESS` in `.env` to match your desktop's local IP.

---

## Quick Start

### 1. Get a Telegram Bot Token

Open Telegram, search for [@BotFather](https://t.me/BotFather), send `/newbot`, and save the token.

> ⚠️ **Important:** Go to Bot Settings → Group Privacy → **Disable** privacy mode so the bot can see all group messages.

### 2. Clone & Configure

```bash
git clone <your-repo> ai-assistant-light
cd ai-assistant-light

cp .env.example .env
chmod 600 .env
# Fill in at minimum:
#   TELEGRAM_TOKEN      — from BotFather
#   TELEGRAM_WEBHOOK_URL — your public URL (Cloudflare/ngrok)
#   ALLOWED_CHAT_IDS    — your Telegram user ID (for /run)
#   GEMINI_API_KEY      — from https://aistudio.google.com/apikey
# Optionally:
#   PC_IP_ADDRESS       — if using PC power control
#   AI_PERSONALITY       — tone/personality for LLM responses
```

### 3. Install & Run

```bash
uv sync --no-dev
mkdir -p data
uv run uvicorn app.main:app --host 127.0.0.1 --port 8123
```

### 4. Expose with Cloudflare Tunnel

Telegram needs a public HTTPS URL to send updates. Cloudflare Tunnel is the easiest way.

#### Option A — Quick Tunnel (for testing)

No account needed. Runs in foreground:

```bash
# On your Pi or dev machine:
cloudflared tunnel --url http://localhost:8123
```

You'll see:
```
https://<random>.trycloudflare.com → http://localhost:8123
```

Copy that URL, set it in `.env`, then register the webhook:

```bash
# In .env:
TELEGRAM_WEBHOOK_URL=https://<random>.trycloudflare.com

# Register:
uv run python -m app.bot.setup_webhook
```

> ⚠️ Quick Tunnel URL changes every restart — only for development.

---

#### Option B — Permanent Tunnel (production)

Requires a domain with DNS managed by Cloudflare.

**Step 1 — Install cloudflared**

```bash
# Raspberry Pi (ARM):
wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm
sudo mv cloudflared-linux-arm /usr/local/bin/cloudflared
sudo chmod +x /usr/local/bin/cloudflared

# Or via package manager:
# sudo apt install cloudflared
```

**Step 2 — Authenticate**

```bash
cloudflared tunnel login
# Opens a browser — log in to Cloudflare and authorize.
```

**Step 3 — Create the tunnel**

```bash
cloudflared tunnel create ai-assistant
# Saves credentials JSON to ~/.cloudflared/<id>.json
```

**Step 4 — Create config file**

Create `~/.cloudflared/config.yml`:

```yaml
tunnel: <tunnel-id-from-step-3>
credentials-file: /home/pi/.cloudflared/<tunnel-id>.json

ingress:
  - hostname: bot.yourdomain.com
    service: http://localhost:8123
  - service: http_status:404
```

**Step 5 — Route DNS**

```bash
cloudflared tunnel route dns ai-assistant bot.yourdomain.com
```

**Step 6 — Run as systemd service**

```bash
sudo cloudflared service install
sudo systemctl start cloudflared
sudo systemctl enable cloudflared
```

**Step 7 — Verify & register webhook**

```bash
# Tunnel is live → set webhook URL in .env:
TELEGRAM_WEBHOOK_URL=https://bot.yourdomain.com

# Register:
uv run python -m app.bot.setup_webhook
```

> 💡 To check tunnel status: `cloudflared tunnel list` & `cloudflared tunnel info ai-assistant`

---

### 5. Or Expose with ngrok (Dev)

```bash
# Install: https://ngrok.com/download
ngrok http 8123
# Copy the https://*.ngrok-free.app URL
```

```bash
# In .env:
TELEGRAM_WEBHOOK_URL=https://<your-ngrok-subdomain>.ngrok-free.app

# Register:
uv run python -m app.bot.setup_webhook
```

> ⚠️ ngrok free tier gives a random URL each restart. Upgrade for fixed subdomains.

---

## Quick Tunnel: Auto Bot Launcher (`scripts/start-bot.sh`)

For development or when you don't have a permanent domain, use the all-in-one launcher:

```bash
./scripts/start-bot.sh
```

This single script does EVERYTHING automatically:

1. Starts cloudflared Quick Tunnel (background)
2. Waits for the tunnel URL (up to 30s)
3. Updates `TELEGRAM_WEBHOOK_URL` in `.env`
4. Registers the webhook with Telegram
5. Launches uvicorn (foreground)
6. On Ctrl+C → cleans up tunnel + exits cleanly

```
[INFO]  Step 1/7 — Starting cloudflared tunnel...
[INFO]    cloudflared PID: 12345
[INFO]  Step 2/7 — Waiting for tunnel URL (timeout: 60s)...
[INFO]    ✅ Tunnel URL: https://abc123.trycloudflare.com
[INFO]  Step 3/7 — Updating TELEGRAM_WEBHOOK_URL in .env...
[INFO]    ✅ .env updated
[INFO]  Step 4/7 — Waiting for tunnel DNS propagation...
[INFO]  Step 5/7 — Registering webhook with Telegram...
[INFO]    ✅ Webhook registered
[INFO]  Step 6/7 — Sending startup notification...
[INFO]    ✅ Notification sent to chat 123456789
[INFO]  Step 7/7 — Starting uvicorn on port 8123...

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Bot is LIVE! 🚀
  Tunnel: https://abc123.trycloudflare.com
  Webhook: https://abc123.trycloudflare.com/webhook
  Started: 2026-05-24 18:00:00
  Press Ctrl+C to stop.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

> ⚠️ **Quick Tunnel URL changes every restart.** The script handles this automatically by re-registering the webhook each time.
> 💡 For permanent deployment, set up a named tunnel (Option B above) and use `sudo systemctl restart ai-assistant` instead.

---

## Deploy to Raspberry Pi 3B

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
git clone <repo> ai-assistant-light
cd ai-assistant-light
cp .env.example .env && chmod 600 .env
uv sync --no-dev
mkdir -p data
uv run python -m app.bot.setup_webhook

sudo cp deploy/ai-assistant.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ai-assistant

# If using GPIO relay for PC control:
sudo usermod -a -G gpio pi   # grant GPIO access to the pi user
```

---

## Development

```bash
uv sync --extra dev             # install including dev deps
uv run uvicorn app.main:app --reload   # hot-reload dev server
uv run pytest                   # run tests (3 tests, HTTP mocked with respx)
uv run ruff check .             # lint
uv run ruff check --fix .       # auto-fix
uv run mypy app/                # type check
```

---

## Architecture

```
Telegram ──► Cloudflare/ngrok ──► FastAPI webhook
                                       │
                                  ┌────┴────┐
                                  │ gateway │  ← secret token verification
                                  │  .py    │  ← rate limiter + callback queries
                                  └────┬────┘
                                       │
                                  ┌────┴────┐
                                  │dispatch │  ← pending state → slash → brain
                                  └────┬────┘
                                       │
              ┌───────────┬───────────┼───────────┬───────────┐
              ▼           ▼           ▼           ▼           ▼
        System     WebSearch   Reminder     Notes     ScriptRunner
        /ping      /search     /remind      /notes     /run
        /help      (or brain)  /reminders   /note <id> (admin only)
        /status                /cancel      + brain     + PC control
              │
              ▼
        ┌─────────────────┐
        │   BrainPlugin   │  ← free text → Gemini → JSON actions[]
        │  (AI Router)    │  → routes to correct plugin internally
        └─────────────────┘
              │
        ┌─────┴─────┐
        │   LLM     │  ← httpx, no SDKs
        │  Provider  │  ← Gemini (default) / Anthropic / OpenAI / etc.
        └───────────┘
```

**Message Flow (with BrainPlugin):**

```
You: "search for fastapi"
  ↓
BrainPlugin.handle()
  ↓
Gemini 2.5 Flash
  ↓  structured JSON
{"action": "search", "query": "fastapi"}
  ↓
_routes to → WebSearchPlugin.handle("/search fastapi")
  ↓
🔍 Search results → Telegram reply
```

---

## Security

- **`.env` is NEVER committed** — in `.gitignore` + `chmod 600`
- **Pre-commit `detect-secrets`** hook blocks accidental key commits
- **Script runner** uses `create_subprocess_exec` — **no `shell=True`**
- **Path traversal blocked** — script names validated with regex (`[a-zA-Z0-9_-].sh` or `.py`)
- **Parameterized SQL** — all queries use `?` placeholders, no injection
- **Secrets never logged** — `settings.*` not serialized in responses or errors
- **Webhook secret token** — constant-time comparison against `X-Telegram-Bot-Api-Secret-Token`
- **`ALLOWED_CHAT_IDS`** — only authorized users can run scripts or trigger PC power control
- **Pending state cleared on restart** — no stale data, user just re-sends message

---

## Plugin API

Adding a new plugin takes < 50 lines:

```python
from app.plugins.base import BotContext, Plugin

class MyPlugin(Plugin):
    name = "my_plugin"
    commands = ["mycmd"]
    description = "Does something useful"

    async def handle(self, ctx: BotContext) -> str | None:
        return f"You said: {ctx.message_text}"
```

Then register it in `app/main.py`:
```python
from app.plugins.my_plugin.handler import MyPlugin
# Add to the plugins list in lifespan()
```

---

## Resource Budget (Raspberry Pi 3B)

| Component | Idle RAM |
|---|---|
| uvicorn + FastAPI | ~50 MB |
| python-telegram-bot | ~25 MB |
| APScheduler | ~5 MB |
| aiosqlite | ~5 MB |
| httpx | ~5 MB |
| Plugins + LLM layer | ~10 MB |
| **Total idle** | **~100 MB** |

Cloud API means zero local model RAM. The Pi 3B handles this comfortably.

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---|---|---|
| Bot doesn't reply | Webhook not set or wrong URL | Run `uv run python -m app.bot.setup_webhook` |
| Bot ignores group messages | Privacy mode enabled in BotFather | Settings → Group Privacy → Disable |
| Webhook returns 401 | Secret token mismatch | Check `TELEGRAM_WEBHOOK_SECRET` matches |
| LLM calls fail | Provider not configured | Set `GEMINI_API_KEY` (or other provider key) in `.env` |
| Script runner blocked | `ALLOWED_CHAT_IDS` not set | Add your Telegram user ID |
| "No pending actions" when saying yes | Pending state timed out | Just send the original request again |
| Brain doesn't route to search | Gemini returned "chat" action | Try explicit `/search <query>` as fallback |
| PC control says script not found | Scripts path issue | Ensure `scripts/` exists relative to working directory |
| Cloudflare Tunnel 500 error | Transient trycloudflare issue | Retry — usually works on second attempt |
| Reminder says "time must be in future" | Time already passed today | Use tomorrow or a later time

---

## License

MIT
