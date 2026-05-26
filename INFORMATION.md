# ai-assistant-light — Feature Status

> Version: v0.2.0 | Project status tracker

---

## ✅ Done (on `main`)

### Core Infrastructure
- [x] FastAPI webhook server
- [x] aiosqlite with WAL mode + migration runner
- [x] Plugin system with PluginRegistry singleton
- [x] Config via pydantic-settings + `.env`
- [x] Rate limiter + auth guard
- [x] APScheduler for background tasks (5min interval, 10× more efficient)
- [x] Logging (no secrets ever logged)
- [x] 8 database migrations (001–008)

### LLM Layer
- [x] 6 cloud providers: Anthropic, OpenAI, OpenRouter, Gemini, OpenCode, Zen
- [x] All via raw `httpx` — no SDKs
- [x] Default: Gemini 2.5 Flash (free tier, 1,500 req/day)
- [x] Provider router with fail-fast validation
- [x] Dynamic `max_tokens` — scales with message length (no more truncation)

### System Plugin
- [x] `/start`, `/help`, `/ping`, `/status`

### Web Search
- [x] `/search <query>` — DuckDuckGo search (free, no API key)
- [x] LLM synthesis (optional)

### Reminder
- [x] `/remind <time> <msg>` — Set reminders with time parsing
- [x] `/reminders` — Clean table format with human-readable dates
- [x] `/cancel <id>` — Cancel a reminder
- [x] Single alert `[10]` — 10 minutes before
- [x] `/note <id>` — View reminder source (original forwarded message)
- [x] Clean confirmation: preview → yes/no
- [x] Stray yes/no → "No pending actions" message

### Notes Plugin
- [x] Save long messages as notes
- [x] `/notes` — list all saved notes
- [x] `/note <id>` — view note or reminder source

### Smart Agenda Parsing
- [x] Forwarded/pasted agenda → Gemini extracts ALL events
- [x] Multiple `remind_create` actions in one API call
- [x] Grouped preview by date
- [x] Content distillation: clear WHO + WHAT + OBJECT
- [x] Fallback: acknowledgment when too long

### Summarizer
- [x] `/summarize` — Summarize recent messages
- [x] `/lastsummary` — Get last saved summary

### Script Runner
- [x] `/run <script>` — Execute sandboxed scripts (admin-only)
- [x] `.sh` and `.py` support with auto-detected interpreter
- [x] Path traversal protection
- [x] Timeout + output cap

### BrainPlugin (v4) — Context-Aware
- [x] Non-command messages → Gemini → classified action → router
- [x] `actions[]` array support — multiple actions per API call
- [x] Validation gates: required params check before preview
- [x] Auto-cancel pending when new content arrives
- [x] Separator-only messages (`===`) ignored
- [x] Raw JSON never leaks — acknowledgment fallback
- [x] **Context retriever** (`context.py`) — 20 recent msgs + FTS5 search + notes
- [x] **Noise filtering** — `/ping`, `/help`, `/start` excluded from context
- [x] **User↔Bot pairing** — groups messages into exchange units
- [x] **Thinking indicator** — sends "⏳ Wait, I'm thinking…" → edits with answer
- [x] **FTS5 full-text search** — `messages_fts` + `notes_fts` (migration 007)
- [x] **Message type tracking** — `type='user'` / `type='bot'` (migration 008)
- [x] **Bot responses stored** — LLM sees FULL conversation, not half
- [x] **Local intent detection** — confidence scoring (0.0-1.0), 12 features, bilingual EN+ID
- [x] **Ambiguity detection** — scores within 0.15 → fallback Gemini, avoids false positives
- [x] **Typo normalization** — 25+ common typos (jdwal→jadwal, tomorow→tomorrow)

### PC Power Control
- [x] GPIO relay scripts (power on/off via `RPi.GPIO`)
- [x] `scripts/ping-pc.sh` — ping-based PC status check
- [x] Brain routes "turn on pc" → `/run relay-poweron-pc.py`

### AI Personality
- [x] `AI_PERSONALITY` env var
- [x] Injected into all system prompts
- [x] Default: friendly, concise, fun, light sarcasm

### Security
- [x] `.gitignore` — excludes `.env`, `data/`, `.venv/`, etc.
- [x] `detect-secrets` pre-commit hook
- [x] `ALLOWED_CHAT_IDS` — only authorized users can run scripts
- [x] No `shell=True` anywhere
- [x] Parameterized SQL (no injection)
- [x] Secrets never logged or serialized

### Deploy
- [x] systemd service file
- [x] Cloudflare Tunnel support
- [x] uv.lock committed (reproducible builds)

---

## 🔮 Future Ideas

| Idea | Priority | Notes |
|---|---|---|
| Recurring reminders | 🟡 Medium | "every monday 9am" |
| Note tags/categories | 🟢 Low | `#work`, `#personal` |
| Recurring reminders | 🟡 Medium | "every monday 9am" |
| RSS monitoring | 🟡 Medium | Cron-based feed checker |
| Weather plugin | 🟢 Low | Free API needed |
| Dashboard web UI | 🔴 Low | Maybe? Not the focus |

---

## Known Limitations

| Issue | Status |
|---|---|
| Gemini free tier: 60 req/min limit | Can't bypass — free tier limitation |
| Notes are per-chat (no cross-device sync) | By design — SQLite local |
| No encryption at rest | SQLite file — only as secure as your Pi |
| Scripts run as bot user | Need `gpio` group access on Pi |

---

## Branch History

| Branch | Merged | What |
|---|---|---|
| `main` | ✅ | Current production |
| `search-features` | ✅ | DuckDuckGo search (free) |
| `llm-brain` | ✅ | BrainPlugin v1 + Gemini + PC control |
| `remind-notes-features` | ✅ | Notes, agenda parsing, personality, validations |
