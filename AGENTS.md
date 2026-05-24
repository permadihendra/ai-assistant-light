# ai-assistant-light — Agent Guide

## Project Overview

Lightweight AI assistant for Raspberry Pi 3B. Telegram bot interface with cloud LLM providers and extensible plugins.

**Stack:** Python 3.11+ · FastAPI · aiosqlite · python-telegram-bot · httpx · APScheduler

**Architecture:** Telegram webhook → FastAPI → Dispatcher → Plugin → LLM Provider (cloud API)

---

## Repository Layout

```
ai-assistant-light/
├── app/
│   ├── main.py              # FastAPI app factory + lifespan
│   ├── config.py            # pydantic-settings, module-level singleton
│   ├── database.py          # aiosqlite + migration runner (WAL mode)
│   ├── bot/
│   │   ├── gateway.py       # Telegram webhook receiver (FastAPI route)
│   │   ├── dispatcher.py    # Pending state → slash commands → BrainPlugin
│   │   ├── middlewares.py   # Rate limiter + auth guard
│   │   ├── context.py       # BotContext dataclass builder
│   │   └── setup_webhook.py # One-time webhook registration script
│   ├── plugins/
│   │   ├── base.py          # Plugin ABC + PluginRegistry singleton
│   │   ├── system/          # /start, /help, /ping, /status
│   │   ├── web_search/      # /search — DuckDuckGo (free, no API key)
│   │   ├── reminder/        # /remind, /reminders, /cancel
│   │   ├── notes/           # /notes, /note <id> — save & view notes
│   │   ├── summarizer/      # /summarize, /lastsummary
│   │   ├── script_runner/   # /run — sandboxed .sh/.py execution
│   │   └── brain/           # AI router — free text → Gemini → JSON → route
│   │       ├── handler.py   # Intent classification + action routing
│   │       ├── state.py     # In-memory pending state tracker
│   │       └── picker.py    # Inline keyboard time picker
│   ├── llm/
│   │   ├── base.py          # LLMProvider ABC + dataclasses
│   │   ├── router.py        # Provider registry + convenience wrapper
│   │   ├── prompts.py       # All system prompts (personality injected)
│   │   └── providers/       # anthropic, openai, openrouter, gemini, opencode
│   ├── scheduler/
│   │   └── runner.py        # APScheduler AsyncIOScheduler — polls reminders every 30s
│   └── models/              # Placeholder (models stored in SQLite)
├── migrations/               # Numbered SQL migration files (001–005)
├── scripts/                  # Sandboxed user scripts
│   ├── ping-pc.sh            # Ping-based PC status check
│   └── raspberrypi/gpio-scripts/  # GPIO relay scripts for PC power control
├── deploy/                   # systemd service file
├── tests/                    # pytest fixtures (tests need writing)
├── pyproject.toml            # UV-managed, no provider SDKs
└── .env.example              # Placeholder values only
```

---

## Plugin Architecture

Every plugin extends `Plugin` ABC from `app/plugins/base.py`:

```python
class Plugin(ABC):
    name: str
    commands: list[str]   # Telegram slash commands (without /)
    description: str

    async def handle(self, ctx: BotContext) -> str | None: ...
    async def on_load(self) -> None: ...
    async def on_unload(self) -> None: ...
```

**Rules:**
- Each plugin is a folder in `app/plugins/<name>/` with `handler.py`
- Plugins cannot import each other directly — use `PluginRegistry.get().get_plugin(name)`
- Max 300 lines per handler (split into sub-modules if exceeded)
- Use `logging` not `print()`

**Registering a new plugin:**
1. Create `app/plugins/<name>/handler.py` with a Plugin subclass
2. Import and register in `app/main.py` lifespan (add to `plugins` list)
3. Add `.env` entries if needed
4. Add commands to `.env.example`
5. Write tests in `tests/test_plugins/`

### BrainPlugin — Intent Router 🧠

The `brain` plugin intercepts ALL non-command messages and routes them:

1. User sends free text → Gemini 2.5 Flash → structured JSON `actions[]` array
2. Each action is validated (required params check) → preview → user confirms
3. On confirmation, routes to the target plugin internally (rewrites `BotContext.message_text` as command)

**Action-to-Plugin Mapping:**

| Action | Targets Plugin | Command Template |
|---|---|---|
| `chat` | BrainPlugin itself | Returns text directly |
| `search` | web_search | `/search {query}` |
| `remind_create` | reminder | `/remind {time} {text}` |
| `remind_list` | reminder | `/reminders` |
| `summarize` | summarizer | `/summarize` |
| `note_save` | notes | Saves via `plugin.save_note()` |
| `ping` / `help` / `status` | system | `/ping` / `/help` / `/status` |
| `pc_on` / `pc_off` / `pc_status` | script_runner | `/run relay-poweron-pc.py` etc. |

**Brain sub-modules:**
- `app/plugins/brain/state.py` — in-memory pending state per chat (lost on restart — safe)
- `app/plugins/brain/picker.py` — inline keyboard time picker (period → hour → minute)

**Bilingual:** Detects Indonesian/English from message keywords. Responds in same language.

### NotesPlugin 📝

Stores reference information in the `notes` SQLite table. Also serves as a cross-plugin viewer:
- `/notes` — list all saved notes
- `/note <id>` — view a note OR view a reminder's source message

### PC Power Control 💻

Brain routes "turn on my pc" / "shutdown" / "pc status" through ScriptRunnerPlugin:
- Scripts live in `scripts/raspberrypi/gpio-scripts/`
- Requires `ALLOWED_CHAT_IDS` authorization
- Requires `PC_IP_ADDRESS` in `.env` for ping status
- Hardware: relay module on GPIO 17 (BCM)

---

## LLM Provider System

All providers use raw `httpx` — no SDKs. Users select one via `LLM_PROVIDER` in `.env`.

| Provider | Class | Required Env | Default Model |
|---|---|---|---|
| anthropic | `AnthropicProvider` | `ANTHROPIC_API_KEY` | claude-3-5-haiku-latest |
| openai | `OpenAIProvider` | `OPENAI_API_KEY` | gpt-4o-mini |
| openrouter | `OpenRouterProvider` | `OPENROUTER_API_KEY` | (user-specified) |
| **gemini** ★ | `GeminiProvider` | `GEMINI_API_KEY` | **gemini-2.5-flash** |
| opencode | `OpenCodeProvider` | `OPENCODE_BASE_URL` | (user-specified) |
| zen | `OpenCodeProvider` | `ZEN_BASE_URL` | (user-specified) |

> ★ **Default** — Gemini 2.5 Flash (free tier, 1,500 req/day, no credit card)

**Adding a new provider:**
1. `app/config.py` — add `new_provider_api_key: str = ""`
2. `.env.example` — add placeholder
3. `app/llm/providers/` — subclass `LLMProvider`
4. `app/llm/router.py` — add to `_REGISTRY`
5. `app/config.py` — add to validator's allowed set
6. `tests/test_llm/` — add test with respx mock

---

## Secret Safety Rules

Coding agent MUST enforce these:

| Rule | Detail |
|---|---|
| `.gitignore` first | Generated before any other file; verified before any git command |
| No provider SDKs | Use `httpx` for all LLM calls; no `anthropic`, `openai`, `google-generativeai` |
| `shell=True` forbidden | Always `create_subprocess_exec` with explicit arg list |
| No threading | `asyncio` only; never `import threading` |
| Parameterized SQL | All DB writes use `?` placeholders; no f-string SQL |
| Secrets via `settings` | Every credential from `settings.*`; never hardcoded, never in comments |
| Secrets never logged | No `logging.debug(settings.anthropic_api_key)` or equivalent |
| Explicit HTTP timeouts | Every `httpx` call sets `timeout=` |
| Log with `logging` | No `print()` in production paths |
| `.env.example` fake values | e.g. `your-anthropic-api-key-here`, never a real key format |
| `detect-secrets` baseline | Run `detect-secrets scan` after any new file is added |

---

## Common Commands

```bash
uv sync                     # Install runtime deps
uv sync --extra dev         # Install dev deps
uv run uvicorn app.main:app --reload             # Dev server
uv run pytest               # Run all tests (none written yet)
uv run pytest tests/ -v     # Verbose
uv run ruff check .         # Lint
uv run ruff check --fix .   # Auto-fix
uv run mypy app/            # Type check
uv run python -m app.bot.setup_webhook           # Register webhook
uv run python -m app.bot.setup_webhook --delete  # Remove webhook
```

---

## Deployment Checklist (Raspberry Pi 3B)

```bash
# One-time
curl -LsSf https://astral.sh/uv/install.sh | sh
git clone <repo> ai-assistant-light
cd ai-assistant-light
cp .env.example .env && chmod 600 .env  # fill real keys
uv sync --no-dev
mkdir -p data
uv run python -m app.bot.setup_webhook

# systemd service
sudo cp deploy/ai-assistant.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ai-assistant

# If using GPIO relay for PC control:
sudo usermod -a -G gpio pi   # grant GPIO access

# IMPORTANT: In BotFather, disable Group Privacy mode so bot sees all messages
```

---

## Resource Budget (Pi 3B)

| Component | Idle RAM |
|---|---|
| uvicorn + FastAPI | ~50 MB |
| python-telegram-bot | ~25 MB |
| APScheduler | ~5 MB |
| aiosqlite | ~5 MB |
| httpx | ~5 MB |
| Plugins + LLM layer | ~10 MB |
| **Total idle** | **~100 MB** |

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---|---|---|
| Bot doesn't reply | Webhook not set | Run `uv run python -m app.bot.setup_webhook` |
| Bot ignores group messages | Privacy mode enabled | Disable in BotFather settings |
| Webhook 401 | Secret token mismatch | Check `TELEGRAM_WEBHOOK_SECRET` |
| LLM calls fail | No API key | Set `GEMINI_API_KEY` in `.env` |
| `/run` blocked | `ALLOWED_CHAT_IDS` not set | Add your Telegram user ID |
| Brain falls back to chat only | Gemini returned chat action | Try explicit `/search` as workaround |
| Search fails | DuckDuckGo rate limit | Wait and retry |
| "No pending actions" | Stale state | Re-send the original request |
| Reminder time parse fails | Unrecognized format | Use `10m`, `2h`, `tomorrow 09:00`
