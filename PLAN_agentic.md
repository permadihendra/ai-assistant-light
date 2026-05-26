# Agentic Architecture — v0.3 Migration Plan

## Vision

Single-agent flow: **Gemini understands intent, manages conversation, calls tools.**

```
User: "remind me 9:00 about doing something"
  ↓
Gemini (agent prompt + tool definitions)
  ↓
"📅 I'll set a reminder for 9:00. Is that today or tomorrow?"
  ↓
User: "today"
  ↓
Gemini:
  "Got it! Today at 9:00 — I'll remind you. What should I call it?"
  ↓
User: "doing something"
  ↓
Gemini → TOOL CALL: create_reminder(date="today", time="9:00", text="doing something")
  ↓
Plugin executes → ✅ Reminder set!
```

## Key Changes

| Area | v0.2 (local detect) | v0.3 (agentic) |
|---|---|---|
| **Primary brain** | Keyword matching + Gemini fallback | **Gemini always** (with agent prompt) |
| **Tool calling** | Action map + hardcoded routing | Gemini decides what tool to call |
| **Conversation** | "Reply yes to confirm" | Natural back-and-forth |
| **Missing params** | Silent fail / confusing prompt | Gemini asks naturally |
| **Default model** | gemini-2.5-flash | **gemini-2.5-flash-lite** (cheaper) |
| **Cost per msg** | ~0 (local) + ~Gemini (fallback) | Gemini always (~1,500 free/day) |

## Prompt Strategy

Replace rigid JSON prompt with **agent persona + tool definitions**:

```
You are a helpful Telegram bot assistant. You have tools to help users.
Always respond conversationally and naturally.

TOOLS:
1. create_reminder(date, time, text) — Schedule a reminder
2. list_reminders() — Show all active reminders
3. cancel_reminder(id) — Cancel a reminder
4. save_note(text) — Save a note
5. search_web(query) — Search the internet
6. show_agenda(date) — Show agenda for a date
7. mark_done(id) — Mark agenda item as done
8. get_pc_status() — Check PC status
9. ping() — Health check

When a user makes a request, call the appropriate tool.
If information is missing, ask naturally.
Do NOT call a tool with incomplete parameters.
```

## Conversation Flow

```
User: "remind me about meeting"
Gemini: "Sure! When should I set the reminder? (e.g. 'tomorrow 9am', 'in 2 hours')"
  → tool called only after all params gathered
```

## Tool Execution

Gemini's tool call → Python function → result → back to Gemini → formatted response

```
Step 1: Gemini → create_reminder(today, 9:00, "doing something")
Step 2: ReminderPlugin.create_reminder() → {"id": 42, "status": "ok"}
Step 3: → Gemini formats: "✅ Reminder #42 set for today at 9:00!"
```

## Implementation Plan

### Phase 1: Prompt + Agent Flow
- Rewrite BRAIN_SYSTEM_PROMPT as agent prompt
- Add tool execution layer (tool registry / dispatcher)
- Keep local detection for ping/help/agenda (fast path)

### Phase 2: Remove Local Intent Detection
- Remove _detect_local_intent and all keyword sets
- All non-command messages → Gemini agent
- Keep only ping/help/agenda as commands

### Phase 3: Polish Conversation
- Handle multi-turn tool calls (ask → answer → execute)
- Graceful error recovery when tool fails
- Natural language for ALL responses

## Files to Change

| File | Phase | Change |
|---|---|---|
| `app/llm/prompts.py` | P1 | Agent prompt with tool definitions |
| `app/plugins/brain/handler.py` | P1 | Tool execution layer |
| `app/config.py` | P1 | Default model → gemini-2.5-flash-lite |
| `.env.example` | P1 | Update model name |
| `app/plugins/brain/handler.py` | P2 | Remove local intent detection |
| `app/bot/gateway.py` | P3 | Handle multi-turn tool conversations |
