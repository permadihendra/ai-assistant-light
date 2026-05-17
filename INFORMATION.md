# ai-assistant-light — Feature Status

> Project status tracker. What's built, what's coming, what's cooking.

---

## ✅ Done (on `main`)

### Core Infrastructure
- [x] FastAPI webhook server
- [x] aiosqlite with WAL mode + migration runner
- [x] Plugin system with PluginRegistry singleton
- [x] Config via pydantic-settings + `.env`
- [x] Rate limiter + auth guard
- [x] APScheduler for background tasks
- [x] Logging (no secrets ever logged)

### LLM Layer
- [x] 6 cloud providers: Anthropic, OpenAI, OpenRouter, Gemini, OpenCode, Zen
- [x] All via raw `httpx` — no SDKs
- [x] Default: Gemini 2.5 Flash (free tier, 1,500 req/day)
- [x] Provider router with fail-fast validation

### System Plugin
- [x] `/start` — Welcome message
- [x] `/help` — Full command list
- [x] `/ping` — Health check
- [x] `/status` — Bot + user info

### Web Search
- [x] `/search <query>` — DuckDuckGo search (free, no API key)
- [x] LLM synthesis (optional, if LLM configured)

### Reminder
- [x] `/remind <time> <msg>` — Set reminders
- [x] `/reminders` — List active reminders
- [x] `/cancel <id>` — Cancel a reminder
- [x] Time parsing: `10m`, `2h`, `tomorrow 09:00`, `2026-06-01 08:00`

### Summarizer
- [x] `/summarize` — Summarize recent messages
- [x] `/lastsummary` — Get last saved summary

### Script Runner
- [x] `/run <script>` — Execute sandboxed scripts (admin-only)
- [x] `.sh` and `.py` support with auto-detected interpreter
- [x] Path traversal protection
- [x] Timeout + output cap

### BrainPlugin (v2)
- [x] Non-command messages → Gemini → classified action → router
- [x] Structured JSON routing (`search`, `remind_create`, `ping`, `help`, etc.)
- [x] PC power control: `pc_on`, `pc_off`, `pc_status`

### PC Power Control
- [x] GPIO relay scripts (power on/off via `RPi.GPIO`)
- [x] `scripts/ping-pc.sh` — ping-based PC status check
- [x] Brain routes "turn on pc" → `/run relay-poweron-pc.py`

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

## 🚧 Building (on `remind-notes-features` branch)

### Notes Plugin
- [ ] Save long messages as notes
- [ ] `/notes` — list all saved notes
- [ ] `/note <id>` — view specific note
- [ ] Notes SQLite table + migration

### Smart Long-Message Parsing
- [ ] Messages >100 chars → auto-detect intent
- [ ] Gemini extracts: remind? note? both?
- [ ] Multiple actions from one API call (`actions[]`)

### Multi-Alert Reminders
- [ ] `alerts: [15, 5]` — fire warnings before the actual time
- [ ] Scheduler polls for pending alerts
- [ ] Overdue alert handling

### AI Personality
- [ ] `AI_PERSONALITY` env var
- [ ] Injected into all system prompts
- [ ] Default: friendly, concise, fun, light sarcasm

---

## 🔮 Future Ideas

| Idea | Priority | Notes |
|---|---|---|
| Recurring reminders | 🟡 Medium | "every monday 9am" |
| Note tags/categories | 🟢 Low | `#work`, `#personal` |
| RSS monitoring | 🟡 Medium | Cron-based feed checker |
| Weather plugin | 🟢 Low | Free API needed |
| Multi-language support | 🟢 Low | Already partially works via Gemini |
| Dashboard web UI | 🔴 Low | Maybe? Not the focus |

---

## Known Limitations

| Issue | Status |
|---|---|
| Genimi free tier: 60 req/min limit | Can't bypass — free tier limitation |
| Notes are per-chat (no cross-device sync) | By design — SQLite local |
| No encryption at rest | SQLite file — only as secure as your Pi |
| Scripts run as bot user | Need `gpio` group access on Pi |

---

## Branch History

| Branch | Merged | What |
|---|---|---|
| `main` | ✅ | Initial project setup |
| `search-features` | ✅ | DuckDuckGo search (free) |
| `llm-brain` | ✅ | BrainPlugin v1 + Gemini + PC control |
| `remind-notes-features` | 🔧 In progress | Notes, smart parsing, personality |
