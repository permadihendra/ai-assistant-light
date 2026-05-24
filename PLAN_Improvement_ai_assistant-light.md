# AI-Assistant-Light — Refined Architecture & Memory System Plan

This PLAN contains the refined context-aware memory architecture, SQLite FTS5 retrieval strategy, multi-provider LLM support, and lightweight conversational intelligence system optimized for Raspberry Pi 3B.

Key focuses:
- Retrieval quality
- Context compression
- SQLite FTS5 memory search
- Multi-layer context assembly
- Lightweight async architecture
- Telegram-first UX
- Cloud LLM providers
- Extensible modular system


Your idea is correct.
You are discovering one of the most important truths in AI assistants:

```text id="6j88ez"
"Smartness" mostly comes from context engineering,
not model intelligence alone.
```

Even mediocre models feel smart if:

* retrieval is good
* memory is relevant
* context is compressed correctly

And even GPT-5 feels dumb if:

* context is missing
* retrieval is noisy
* conversation state is lost

---

# 1. Your Current Problem

Right now your bot is probably:

```text id="m29ryo"
User message
    ↓
Send directly to LLM
    ↓
Response
```

Meaning:

* no memory
* no awareness
* no continuity
* no personalization

So every message feels stateless.

---

# 2. Your Proposed Solution

Your proposed architecture:

```text id="6p0onp"
Incoming message
    ↓
Retrieve relevant history/context
    ↓
Synthesize context
    ↓
Inject into prompt
    ↓
LLM response
```

This is EXACTLY the right direction.

This is basically:

* lightweight memory retrieval
* context-aware prompting
* mini-RAG for conversations

---

# 3. Your “Wait I’m Thinking...” Flow

This is also correct UX.

Example:

```text id="rdl0fu"
User:
"What do you think about this architecture?"
(replying to previous text)

Bot:
"Thinking..."

Under the hood:
1. detect reply context
2. fetch related messages
3. search memory
4. build context
5. send to LLM
6. return final answer
```

This creates:

* perceived intelligence
* continuity
* contextual awareness

without requiring giant models.

---

# 4. The KEY Insight

The important part is NOT:

```text id="76z9gm"
"store everything"
```

The important part is:

```text id="ow5br4"
"retrieve the RIGHT context"
```

This is the core challenge.

---

# 5. Recommended Context Layers

Your assistant should have MULTIPLE context sources.

Not just “latest messages”.

---

# Layer 1 — Immediate Conversation Window

Most important.

Example:

* last 10–30 messages

This handles:

* natural conversation flow
* follow-up questions
* references like “that”, “it”, “this”

---

# Layer 2 — Reply Chain Context

Very important for Telegram.

If user replies to a message:

```text id="ch5my5"
reply_to_message_id
```

then retrieve:

* original message
* nearby thread messages

This dramatically improves coherence.

---

# Layer 3 — Semantic/Keyword Memory Search

Your SQLite FTS5 idea.

Search:

* old conversations
* notes
* summaries
* memories

Example:

```text id="98vr2l"
"opencode architecture"
```

Retrieve:

* previous discussions
* saved notes
* summaries

---

# Layer 4 — Persistent User Memory

Examples:

* user prefers pandas
* user uses Raspberry Pi
* user likes minimal stack

This is HIGH VALUE memory.

Very small.
Very important.

---

# 6. Recommended Final Context Pipeline

This is what I recommend.

---

# Context Assembly Pipeline

```text id="y76j2k"
Incoming User Message
        ↓
[1] Recent Messages
        ↓
[2] Reply Context
        ↓
[3] FTS5 Memory Search
        ↓
[4] User Persistent Memory
        ↓
Merge + Compress
        ↓
Final Prompt
        ↓
LLM
```

This architecture is VERY strong.

---

# 7. CRITICAL Problem: Context Explosion

If you naïvely inject everything:

```text id="w8mvs0"
last 100 messages
+ search results
+ summaries
+ notes
```

you get:

* token explosion
* slower responses
* worse reasoning
* noisy prompts

More context is NOT always better.

---

# 8. MOST IMPORTANT COMPONENT

You identified it already:

```text id="tqjsws"
"Synthesize the retrieved context"
```

THIS is the secret sauce.

---

# 9. Do NOT Send Raw Logs Directly

BAD:

```text id="3j5d2e"
100 raw messages
```

Good:

```text id="4b7a44"
small synthesized context summary
```

---

# 10. Recommended Architecture

Use TWO LLM calls.

---

# Call 1 — Context Synthesizer

Cheap model.

Input:

* retrieved messages
* notes
* recent history

Task:

* compress into concise context

Example output:

```text id="ehh8q7"
User and assistant were discussing:
- SQLite FTS5 memory retrieval
- Raspberry Pi constraints
- lightweight AI architecture

User prefers:
- minimal stack
- low RAM usage
- cloud AI APIs
```

This becomes:

* compact
* high signal
* low tokens

---

# Call 2 — Main Response

Main model receives:

```text id="z1skk0"
SYSTEM
CONTEXT SUMMARY
RECENT CHAT
CURRENT MESSAGE
```

This is MUCH smarter.

---

# 11. This Is Basically “Memory Compression”

Very important concept.

Because:

* raw chat logs are noisy
* summaries are dense signal

Good assistants compress aggressively.

---

# 12. Recommended Database Structure

---

# messages table

```sql id="5qzlc6"
id
chat_id
user_id
reply_to
message
timestamp
```

---

# memory_summaries table

```sql id="2x0b49"
id
chat_id
summary
created_at
importance_score
```

---

# user_memory table

```sql id="n9cbvt"
id
user_id
fact
importance
```

---

# 13. IMPORTANT: Memory Ranking

Not all memories matter equally.

Example:

Bad memory:

```text id="gg5pv0"
user said "hello"
```

Good memory:

```text id="t8uwf5"
user prefers pandas workflow
```

You need:

* relevance
* recency
* importance

---

# 14. Lightweight Ranking Formula

Simple scoring:

```python id="5qv4u3"
score =
    keyword_match * 5
    + recency_score * 2
    + importance_score * 3
```

No embeddings needed initially.

---

# 15. Recommended “Thinking” UX

Telegram UX idea:

---

# Immediate Response

```text id="08enr0"
🧠 Thinking...
```

---

# Background Steps

```text id="djlwm5"
1. Retrieve recent context
2. Retrieve reply context
3. Search memories
4. Summarize context
5. Generate response
```

---

# Final Response

```text id="evlklv"
💭 Opinion:
...

📌 Context Used:
- SQLite FTS5 discussion
- Raspberry Pi constraints
- memory retrieval architecture
```

This feels VERY intelligent.

---

# 16. Biggest Mistake To Avoid

DO NOT try to build:

* autonomous agents
* self-reflective loops
* infinite memory
* LangGraph orchestration

right now.

Your biggest win comes from:

```text id="9qqgq2"
better retrieval
+
better context compression
```

---

# 17. My Strong Recommendation

For your architecture:

## Build THIS first

```text id="9jsg1p"
SQLite
+
FTS5
+
Recent conversation window
+
Reply-chain retrieval
+
Memory summaries
+
Context synthesizer
```

This already creates:

* strong contextual awareness
* continuity
* “smart” feeling conversations

without:

* vector DB
* embeddings
* RAG frameworks
* agent frameworks

---

# 18. Final Analysis

Your intuition is VERY good.

You are independently converging toward:

```text id="m89cje"
retrieval-augmented conversational memory
```

which is the correct architecture direction.

But your lightweight version is BETTER for your situation than full enterprise RAG.

Especially because:

* Raspberry Pi constraints
* beginner maintainability
* debugging simplicity
* low RAM
* fast iteration

You are currently designing a genuinely solid assistant architecture.
