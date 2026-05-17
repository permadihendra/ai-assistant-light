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
│   ├── database.py          # aiosqlite + migration runner
│   ├── bot/
│   │   ├── gateway.py       # Telegram webhook receiver (FastAPI route)
│   │   ├── dispatcher.py    # Maps command → plugin handler
│   │   ├── middlewares.py   # Rate limiter + auth guard
│   │   ├── context.py       # BotContext dataclass builder
│   │   └── setup_webhook.py # One-time webhook registration script
│   ├── plugins/
│   │   ├── base.py          # Plugin ABC + PluginRegistry singleton
│   │   ├── system/          # /start, /help, /ping, /status
│   │   ├── web_search/      # /search — Brave Search API
│   │   ├── reminder/        # /remind, /reminders, /cancel
│   │   ├── summarizer/      # /summarize, /lastsummary
│   │   └── script_runner/   # /run — sandboxed script execution
│   ├── llm/
│   │   ├── base.py          # LLMProvider ABC + dataclasses
│   │   ├── router.py        # Provider registry + convenience wrapper
│   │   ├── prompts.py       # All system prompts in one place
│   │   └── providers/       # anthropic, openai, openrouter, gemini, opencode
│   ├── scheduler/
│   │   └── runner.py        # APScheduler AsyncIOScheduler — polls reminders every 30s
│   └── models/              # Data model placeholders
├── migrations/               # Numbered SQL migration files
├── scripts/                  # Sandboxed user scripts
├── deploy/                   # systemd service file
├── tests/                    # pytest + respx mocks
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
- Each plugin is a single module in `app/plugins/<name>/handler.py`
- Plugins cannot import each other directly
- Max 300 lines per plugin (split into sub-modules if exceeded)
- Use `logging` not `print()`

**Registering a new plugin:**
1. Create `app/plugins/<name>/handler.py` with a Plugin subclass
2. Import and register in `app/main.py` lifespan
3. Add `.env` entries if needed
4. Add commands to `.env.example`
5. Write tests in `tests/test_plugins/`

---

## LLM Provider System

All providers use raw `httpx` — no SDKs. Users select one via `LLM_PROVIDER` in `.env`.

| Provider | Class | Required Env | Test File |
|---|---|---|---|
| anthropic | `AnthropicProvider` | `ANTHROPIC_API_KEY` | `tests/test_llm/test_anthropic.py` |
| openai | `OpenAIProvider` | `OPENAI_API_KEY` | `tests/test_llm/test_openai.py` |
| openrouter | `OpenRouterProvider` | `OPENROUTER_API_KEY` | — |
| gemini | `GeminiProvider` | `GEMINI_API_KEY` | — |
| opencode | `OpenCodeProvider` | `OPENCODE_BASE_URL` | — |
| zen | `OpenCodeProvider` | `ZEN_BASE_URL` | — |

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
uv sync                  # Install runtime deps
uv sync --extra dev      # Install dev deps
uv run uvicorn app.main:app --reload           # Dev server
uv run pytest            # Run all tests
uv run pytest tests/ -v  # Verbose
uv run ruff check .      # Lint
uv run ruff check --fix . # Auto-fix
uv run mypy app/         # Type check
uv run python -m app.bot.setup_webhook         # Register webhook
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
| Bot doesn't reply | Command prefix mismatch | Check dispatcher strips `/` from command |
| `/help` returns nothing | SystemPlugin not registered | Register in `app/main.py` |
| Webhook 401 errors | Secret token mismatch | Check `TELEGRAM_WEBHOOK_SECRET` matches setup |
| LLM calls fail | Provider not configured | Set API key in `.env` |
| Rate limited on `/search` | Brave API quota (2k/mo) | Wait or upgrade |
