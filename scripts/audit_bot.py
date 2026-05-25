#!/usr/bin/env python3
"""
Live Bot Audit — User Acceptance Test (UAT)

Tests the RUNNING bot by POSTing real webhook payloads to /webhook.
No mocks. Everything hits the real bot: dispatcher, plugins, DB,
Gemini LLM, and Telegram API (side effects will actually send messages).

Usage:
    uv run python scripts/audit_bot.py

Requires:
    - Bot running at http://127.0.0.1:8123
    - .env with valid TELEGRAM_TOKEN, GEMINI_API_KEY
"""

import json
import sqlite3
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

BASE_URL = "http://127.0.0.1:8123"
DB_PATH = Path(__file__).parent.parent / "data" / "assistant.db"

PASS = 0
FAIL = 0
SKIP = 0


def log(msg: str, end="\n"):
    print(msg, end=end, flush=True)


def ok(msg: str):
    global PASS
    PASS += 1
    log(f"  ✅ {msg}")


def fail(msg: str):
    global FAIL
    FAIL += 1
    log(f"  ❌ {msg}")


def skip(msg: str):
    global SKIP
    SKIP += 1
    log(f"  ⏭️  {msg}")


# Read webhook secret from .env (same as what the bot expects)
_WEBHOOK_SECRET = None
_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        if line.startswith("TELEGRAM_WEBHOOK_SECRET=") and "=" in line:
            _WEBHOOK_SECRET = line.split("=", 1)[1].strip('"')
            break


def post_webhook(payload: dict) -> tuple[int, str | None]:
    """POST a Telegram update to the bot's webhook. Returns (status_code, error)."""
    try:
        data = json.dumps(payload).encode()
        headers = {"Content-Type": "application/json"}
        if _WEBHOOK_SECRET:
            headers["X-Telegram-Bot-Api-Secret-Token"] = _WEBHOOK_SECRET
        req = urllib.request.Request(
            f"{BASE_URL}/webhook",
            data=data,
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, None
    except urllib.error.HTTPError as e:
        return e.code, str(e)
    except Exception as e:
        return 0, str(e)


def get_reminders(chat_id: int, fired: int | None = None) -> list[dict]:
    """Query reminders from DB."""
    import sqlite3
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    query = "SELECT * FROM reminders WHERE chat_id = ?"
    params = [chat_id]
    if fired is not None:
        query += " AND fired = ?"
        params.append(fired)
    query += " ORDER BY id DESC LIMIT 10"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_notes(chat_id: int) -> list[dict]:
    """Query notes from DB."""
    import sqlite3
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM notes WHERE chat_id = ? ORDER BY id DESC LIMIT 10",
        (chat_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def health_check() -> bool:
    """Check if bot is alive."""
    try:
        req = urllib.request.Request(f"{BASE_URL}/health")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            return data.get("status") == "ok"
    except Exception:
        return False


CHAT_ID = 76465160  # Replace with your chat_id


# ═══════════════════════════════════════════════════════════
# SECTION 1 — Pre-flight
# ═══════════════════════════════════════════════════════════

def section1_preflight():
    log("\n═══ 1. Pre-flight ═══")
    
    if not DB_PATH.exists():
        fail(f"DB not found: {DB_PATH}")
        return False
    
    if not health_check():
        fail(f"Bot not responding at {BASE_URL}/health")
        return False
    ok("Bot health check passed")
    
    ok(f"DB found: {DB_PATH}")
    log(f"  Chat ID for tests: {CHAT_ID}")
    return True


# ═══════════════════════════════════════════════════════════
# SECTION 2 — Basic Commands
# ═══════════════════════════════════════════════════════════

def section2_commands():
    log("\n═══ 2. Commands ═══")
    
    # 2a. /ping
    code, err = post_webhook({
        "update_id": 2001,
        "message": {
            "message_id": 101,
            "from": {"id": CHAT_ID, "is_bot": False, "first_name": "Tester"},
            "chat": {"id": CHAT_ID, "type": "private", "first_name": "Tester"},
            "date": int(time.time()),
            "text": "/ping",
        },
    })
    ok("/ping → 200") if code == 200 else fail(f"/ping → {code}: {err}")
    
    time.sleep(1)
    
    # 2b. /start
    code, err = post_webhook({
        "update_id": 2002,
        "message": {
            "message_id": 102,
            "from": {"id": CHAT_ID, "is_bot": False, "first_name": "Tester"},
            "chat": {"id": CHAT_ID, "type": "private", "first_name": "Tester"},
            "date": int(time.time()),
            "text": "/start",
        },
    })
    ok("/start → 200") if code == 200 else fail(f"/start → {code}: {err}")
    
    time.sleep(1)
    
    # 2c. /help
    code, err = post_webhook({
        "update_id": 2003,
        "message": {
            "message_id": 103,
            "from": {"id": CHAT_ID, "is_bot": False, "first_name": "Tester"},
            "chat": {"id": CHAT_ID, "type": "private", "first_name": "Tester"},
            "date": int(time.time()),
            "text": "/help",
        },
    })
    ok("/help → 200") if code == 200 else fail(f"/help → {code}: {err}")
    
    time.sleep(1)
    
    # 2d. /status
    code, err = post_webhook({
        "update_id": 2004,
        "message": {
            "message_id": 104,
            "from": {"id": CHAT_ID, "is_bot": False, "first_name": "Tester"},
            "chat": {"id": CHAT_ID, "type": "private", "first_name": "Tester"},
            "date": int(time.time()),
            "text": "/status",
        },
    })
    ok("/status → 200") if code == 200 else fail(f"/status → {code}: {err}")
    
    time.sleep(1)


# ═══════════════════════════════════════════════════════════
# SECTION 3 — Agenda
# ═══════════════════════════════════════════════════════════

def section3_agenda():
    log("\n═══ 3. Agenda ═══")
    
    # Clean up any previous test data
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("DELETE FROM reminders WHERE text LIKE 'AUDIT TEST:%'")
    conn.commit()
    conn.close()
    
    # 3a. /agenda (no items yet)
    code, err = post_webhook({
        "update_id": 3001,
        "message": {
            "message_id": 201,
            "from": {"id": CHAT_ID, "is_bot": False, "first_name": "Tester"},
            "chat": {"id": CHAT_ID, "type": "private", "first_name": "Tester"},
            "date": int(time.time()),
            "text": "/agenda",
        },
    })
    ok("/agenda (empty) → 200") if code == 200 else fail(f"/agenda → {code}: {err}")
    
    time.sleep(1)
    
    # 3b. Create agenda items via reminder INSERT
    conn = sqlite3.connect(str(DB_PATH))
    from datetime import datetime, timedelta, timezone
    
    now = datetime.now(timezone.utc)
    today_9am = now.replace(hour=2, minute=0, second=0, microsecond=0)  # 09:00 WIB
    if today_9am <= now:
        today_9am += timedelta(days=1)
    today_10am = today_9am + timedelta(hours=1)
    
    conn.execute(
        "INSERT INTO reminders (chat_id, user_id, text, remind_at, alerts, alerts_fired, fired) VALUES (?,?,?,?,?,0,0)",
        (CHAT_ID, 0, "AUDIT TEST: Briefing tim dengan klien", today_9am.strftime('%Y-%m-%d %H:%M:%S'), "[10]"),
    )
    conn.execute(
        "INSERT INTO reminders (chat_id, user_id, text, remind_at, alerts, alerts_fired, fired) VALUES (?,?,?,?,?,0,0)",
        (CHAT_ID, 0, "AUDIT TEST: Meeting internal review", today_10am.strftime('%Y-%m-%d %H:%M:%S'), "[10]"),
    )
    conn.commit()
    conn.close()
    
    # 3c. /agenda (should show 2 items)
    code, err = post_webhook({
        "update_id": 3002,
        "message": {
            "message_id": 202,
            "from": {"id": CHAT_ID, "is_bot": False, "first_name": "Tester"},
            "chat": {"id": CHAT_ID, "type": "private", "first_name": "Tester"},
            "date": int(time.time()),
            "text": "/agenda",
        },
    })
    ok("/agenda (with items) → 200") if code == 200 else fail(f"/agenda → {code}: {err}")
    
    time.sleep(1)
    
    # 3d. /agenda tomorrow
    code, err = post_webhook({
        "update_id": 3003,
        "message": {
            "message_id": 203,
            "from": {"id": CHAT_ID, "is_bot": False, "first_name": "Tester"},
            "chat": {"id": CHAT_ID, "type": "private", "first_name": "Tester"},
            "date": int(time.time()),
            "text": "/agenda tomorrow",
        },
    })
    ok("/agenda tomorrow → 200") if code == 200 else fail(f"/agenda tomorrow → {code}: {err}")
    
    time.sleep(1)
    
    # 3e. /agenda all
    code, err = post_webhook({
        "update_id": 3004,
        "message": {
            "message_id": 204,
            "from": {"id": CHAT_ID, "is_bot": False, "first_name": "Tester"},
            "chat": {"id": CHAT_ID, "type": "private", "first_name": "Tester"},
            "date": int(time.time()),
            "text": "/agenda all",
        },
    })
    ok("/agenda all → 200") if code == 200 else fail(f"/agenda all → {code}: {err}")
    
    time.sleep(1)
    
    # 3f. /done with the first test item
    test_items = get_reminders(CHAT_ID, fired=0)
    test_items = [r for r in test_items if "AUDIT TEST" in r["text"]]
    if test_items:
        done_id = test_items[-1]["id"]  # Last inserted (10am meeting)
        code, err = post_webhook({
            "update_id": 3005,
            "message": {
                "message_id": 205,
                "from": {"id": CHAT_ID, "is_bot": False, "first_name": "Tester"},
                "chat": {"id": CHAT_ID, "type": "private", "first_name": "Tester"},
                "date": int(time.time()),
                "text": f"/done {done_id}",
            },
        })
        if code == 200:
            # Verify in DB
            updated = get_reminders(CHAT_ID, fired=1)
            updated_ids = [r["id"] for r in updated]
            if done_id in updated_ids:
                ok(f"/done {done_id} → marked as done in DB")
            else:
                fail(f"/done {done_id} → not marked as done")
        else:
            fail(f"/done {done_id} → {code}: {err}")
    else:
        skip("No test items to mark done")
    
    time.sleep(1)
    
    # 3g. /done all
    code, err = post_webhook({
        "update_id": 3006,
        "message": {
            "message_id": 206,
            "from": {"id": CHAT_ID, "is_bot": False, "first_name": "Tester"},
            "chat": {"id": CHAT_ID, "type": "private", "first_name": "Tester"},
            "date": int(time.time()),
            "text": "/done all",
        },
    })
    ok("/done all → 200") if code == 200 else fail(f"/done all → {code}: {err}")
    
    time.sleep(1)
    
    # Verify all AUDIT TEST items are now done
    remaining = get_reminders(CHAT_ID, fired=0)
    remaining_audit = [r for r in remaining if "AUDIT TEST" in r["text"]]
    if not remaining_audit:
        ok("All AUDIT TEST items cleared (fired=1)")
    else:
        fail(f"{len(remaining_audit)} items still active: {[r['id'] for r in remaining_audit]}")


# ═══════════════════════════════════════════════════════════
# SECTION 4 — Notes
# ═══════════════════════════════════════════════════════════

def section4_notes():
    log("\n═══ 4. Notes ═══")
    
    # 4a. /notes (empty)
    code, err = post_webhook({
        "update_id": 4001,
        "message": {
            "message_id": 301,
            "from": {"id": CHAT_ID, "is_bot": False, "first_name": "Tester"},
            "chat": {"id": CHAT_ID, "type": "private", "first_name": "Tester"},
            "date": int(time.time()),
            "text": "/notes",
        },
    })
    ok("/notes → 200") if code == 200 else fail(f"/notes → {code}: {err}")
    
    time.sleep(1)


# ═══════════════════════════════════════════════════════════
# SECTION 5 — Reminder
# ═══════════════════════════════════════════════════════════

def section5_reminder():
    log("\n═══ 5. Reminder (Brain → Reminder) ═══")
    
    # 5a. /reminders (empty or list)
    code, err = post_webhook({
        "update_id": 5001,
        "message": {
            "message_id": 401,
            "from": {"id": CHAT_ID, "is_bot": False, "first_name": "Tester"},
            "chat": {"id": CHAT_ID, "type": "private", "first_name": "Tester"},
            "date": int(time.time()),
            "text": "/reminders",
        },
    })
    ok("/reminders → 200") if code == 200 else fail(f"/reminders → {code}: {err}")
    
    time.sleep(1)


# ═══════════════════════════════════════════════════════════
# SECTION 6 — Edge Cases
# ═══════════════════════════════════════════════════════════

def section6_edge_cases():
    log("\n═══ 6. Edge Cases ═══")
    
    # 6a. Empty text
    code, err = post_webhook({
        "update_id": 6001,
        "message": {
            "message_id": 501,
            "from": {"id": CHAT_ID, "is_bot": False, "first_name": "Tester"},
            "chat": {"id": CHAT_ID, "type": "private", "first_name": "Tester"},
            "date": int(time.time()),
            "text": "",
        },
    })
    ok("Empty text → 200") if code == 200 else fail(f"Empty text → {code}: {err}")
    
    time.sleep(1)
    
    # 6b. Edited message
    code, err = post_webhook({
        "update_id": 6002,
        "edited_message": {
            "message_id": 502,
            "from": {"id": CHAT_ID, "is_bot": False, "first_name": "Tester"},
            "chat": {"id": CHAT_ID, "type": "private", "first_name": "Tester"},
            "date": int(time.time()),
            "edit_date": int(time.time()),
            "text": "/ping",
        },
    })
    ok("Edited msg → 200") if code == 200 else fail(f"Edited msg → {code}: {err}")
    
    time.sleep(1)
    
    # 6c. Unknown command
    code, err = post_webhook({
        "update_id": 6003,
        "message": {
            "message_id": 503,
            "from": {"id": CHAT_ID, "is_bot": False, "first_name": "Tester"},
            "chat": {"id": CHAT_ID, "type": "private", "first_name": "Tester"},
            "date": int(time.time()),
            "text": "/unknowncommand123",
        },
    })
    ok("Unknown cmd → 200 (ignored)") if code == 200 else fail(f"Unknown cmd → {code}: {err}")
    
    time.sleep(1)
    
    # 6d. Rapid 5 commands
    for i in range(5):
        code, err = post_webhook({
            "update_id": 6100 + i,
            "message": {
                "message_id": 510 + i,
                "from": {"id": CHAT_ID, "is_bot": False, "first_name": "Tester"},
                "chat": {"id": CHAT_ID, "type": "private", "first_name": "Tester"},
                "date": int(time.time()) + i,
                "text": ["/ping", "/help", "/status", "/agenda", "/notes"][i],
            },
        })
        if code != 200:
            fail(f"Rapid cmd {i} → {code}: {err}")
            break
    else:
        ok("5 rapid commands → all 200")


# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════

def main():
    log("╔══════════════════════════════════════╗")
    log("║   AI Assistant Light — Live Audit    ║")
    log("╚══════════════════════════════════════╝")
    log(f"Target: {BASE_URL}")
    log(f"DB:     {DB_PATH}")
    log(f"Time:   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    if not section1_preflight():
        log("\n❌ Pre-flight failed. Aborting.")
        sys.exit(1)
    
    section2_commands()
    section3_agenda()
    section4_notes()
    section5_reminder()
    section6_edge_cases()
    
    # Summary
    log("\n╔══════════════════════════════════════╗")
    log(f"║   Results: ✅ {PASS} passed  ❌ {FAIL} failed  ⏭️  {SKIP} skipped  ║")
    log("╚══════════════════════════════════════╝")
    
    if FAIL > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
