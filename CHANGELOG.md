# Changelog

## v0.2.0 (2026-05-25)

### Context-Aware Memory
- Conversation context retrieval (20 recent msgs + FTS5 search + notes)
- User↔bot message pairing for full conversation context
- Noise filtering (commands excluded from context)
- Thinking indicator ("⏳ Wait, I'm thinking…" → edit with answer)

### Agenda System
- `/agenda` — Today's agenda with ☐/☑ visual markers
- `/agenda tomorrow` — Tomorrow's agenda
- `/agenda all` — All upcoming grouped by date
- `/done <id>` — Mark item done
- Auto-send: daily at 06:00 (today) and 16:00 (tomorrow)
- Agenda is a UI/UX layer over reminders (no separate storage)

### Local Intent Detection (Confidence Scoring)
- 12 features: Agenda, Remind, Notes, Search, PC Control, Help
- Bilingual (EN + ID + mixed language)
- Confidence scoring 0.0-1.0 with ambiguity detection
- No-API fast path for common queries
- 30+ test patterns, typos normalized directly in keyword sets

### Performance
- Reminder scheduler: 30s → 5min (10× fewer wake-ups)
- Query filter: only load reminders due within 2 hours
- Auto-cleanup expired reminders (>7 days)
- Composite index for scheduler queries

### Bug Fixes
- Reminder date format: ISO 8601 broke SQLite comparison (migration 009)
- Naive vs aware datetime comparison crash
- "besok" without hour → TypeError
- Agenda today/tomorrow ambiguity with "tomorrow" keyword
- start-bot.sh: `source .env` space handling, grep exit code, stale env vars
- start-bot.sh: DNS wait before webhook registration

### Security
- Pre-commit hook with detect-secrets
- Hardcoded IP removed from ping-pc.sh
- `.env` parsing safety

### Tests
- 3 → 66 tests (unit + integration + live audit)
- 50 local intent detection pattern tests
- Live UAT script (scripts/audit_bot.py)

### Documentation
- AGENTS.md: full architecture, local intent matrix
- README.md: deployment modes, features, context-aware memory
- INFORMATION.md: complete feature tracker

---

## v0.1.0 (2026-05-17)

Initial release:
- Telegram webhook server
- 6 LLM providers (Gemini, Anthropic, OpenAI, OpenRouter, OpenCode, Zen)
- Plugin system: System, WebSearch, Reminder, Notes, Summarizer, ScriptRunner
- BrainPlugin v2: natural language → JSON → route
- PC Power Control via GPIO relay
- BrainPlugin v3: actions[] array, validation gates, confirmation flow
- Cloudflare Quick Tunnel + Named Tunnel support
- systemd deployment service
- 3 tests
