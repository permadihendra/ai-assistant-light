# ai-assistant-light

> Lightweight AI assistant for Raspberry Pi 3B — Telegram bot interface, cloud LLM, extensible plugins.

**Status:** ✅ Working | **Idle RAM:** ~100 MB | **Peak:** ≤ 500 MB
**Stack:** Python 3.11+ · FastAPI · SQLite · aiosqlite · httpx · APScheduler

---

## Features

| Plugin | Commands | Description |
|---|---|---|
| **System** | `/start`, `/help`, `/ping`, `/status` | Basic bot commands |
| **Web Search** | `/search <query>` | Brave Search API with optional LLM synthesis |
| **Reminder** | `/remind <time> <msg>` | Set reminders (relative, tomorrow, date formats) |
| **Reminder** | `/reminders` | List active reminders |
| **Reminder** | `/cancel <id>` | Cancel a reminder by ID |
| **Summarizer** | `/summarize` | Summarize recent group chat messages |
| **Summarizer** | `/lastsummary` | Retrieve last saved summary |
| **Script Runner** | `/run <script>` | Execute sandboxed scripts (admin-only) |

## LLM Providers

6 cloud providers via raw `httpx` — no SDKs, no heavy dependencies.

| Provider | Env Variable | Models |
|---|---|---|
| Anthropic | `ANTHROPIC_API_KEY` | Claude 3.5 Haiku, Sonnet, Opus |
| OpenAI | `OPENAI_API_KEY` | GPT-4o-mini, o1-mini, etc. |
| OpenRouter | `OPENROUTER_API_KEY` | 100+ models (many free) |
| Google Gemini | `GEMINI_API_KEY` | Gemini 1.5 Flash, Pro |
| OpenCode-Go | `OPENCODE_BASE_URL` | Self-hosted or cloud |
| Zen | `ZEN_BASE_URL` | Self-hosted, key optional |

---

## Quick Start

### 1. Get a Telegram Bot Token

Open Telegram, search for [@BotFather](https://t.me/BotFather), send `/newbot`, and save the token.

### 2. Clone & Configure

```bash
git clone <your-repo> ai-assistant-light
cd ai-assistant-light

cp .env.example .env
chmod 600 .env
# Fill in at minimum: TELEGRAM_TOKEN, ALLOWED_CHAT_IDS, and one LLM provider key
```

### 3. Install & Run

```bash
uv sync --no-dev
mkdir -p data
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### 4. Expose with Cloudflare Tunnel (Option A — Quick)

```bash
cloudflared tunnel --url http://localhost:8000
# Copy the https://*.trycloudflare.com URL
```

Update `.env` with the URL, then register the webhook:

```bash
uv run python -m app.bot.setup_webhook
```

### 5. Or Expose with Cloudflare Tunnel (Option B — Permanent)

Requires a domain with Cloudflare DNS:

```bash
cloudflared tunnel login
cloudflared tunnel create ai-assistant
cloudflared tunnel route dns ai-assistant bot.yourdomain.com
cloudflared tunnel run ai-assistant
```

### 6. Or Expose with ngrok (Dev)

```bash
ngrok http 8000
# Put https://*.ngrok-free.app in .env, then:
uv run python -m app.bot.setup_webhook
```

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
                                  │  .py    │  ← rate limiter
                                  └────┬────┘
                                       │
                                  ┌────┴────┐
                                  │dispatch │  ← resolve command → plugin
                                  └────┬────┘
                                       │
              ┌────────────────────────┼────────────────────────┐
              ▼                        ▼                        ▼
        SystemPlugin           WebSearchPlugin          ReminderPlugin
        /ping, /help           /search <query>         /remind, /reminders
        /status, /start        + Brave Search API      + SQLite + APScheduler
                                       │
                              ┌────────┴────────┐
                              │  LLM Provider   │  ← httpx, no SDKs
                              │  (anthropic/    │
                              │   openai/gemini)│
                              └─────────────────┘
```

---

## Security

- **`.env` is NEVER committed** — in `.gitignore` + `chmod 600`
- **Pre-commit `detect-secrets`** hook blocks accidental key commits
- **Script runner** uses `create_subprocess_exec` — **no `shell=True`**
- **Path traversal blocked** — script names validated with regex
- **Parameterized SQL** — all queries use `?` placeholders, no injection
- **Secrets never logged** — `settings.*` not serialized in responses or errors
- **Webhook secret token** — constant-time comparison against `X-Telegram-Bot-Api-Secret-Token`

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
| Bot doesn't reply to commands | Command prefix mismatch | Already fixed — dispatcher strips `/` |
| `pending_update_count` stays 0 but no reply | Missing `/help` handler | Add SystemPlugin to registration |
| Webhook returns 401 | Secret token mismatch | Check `TELEGRAM_WEBHOOK_SECRET` matches |
| LLM calls fail | Provider not configured | Set API key in `.env` |
| Script runner blocked | `ALLOWED_CHAT_IDS` not set | Add your Telegram user ID |
| Cloudflare Tunnel 500 error | Transient trycloudflare issue | Retry — usually works on second attempt |

---

## License

MIT
