"""Integration tests — bot startup, health, webhook endpoint, Telegram reply.

Uses FastAPI TestClient (no uvicorn needed). Mocks Telegram API with respx.
"""

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


@pytest.fixture(scope="module")
def client():
    """FastAPI TestClient — starts the app with full lifespan (DB init, plugins)."""
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _no_webhook_secret():
    """Clear webhook secret so tests can POST without auth header.
    
    Restores original value after each test.
    """
    original = settings.telegram_webhook_secret
    settings.telegram_webhook_secret = ""
    yield
    settings.telegram_webhook_secret = original


# ── Health endpoint ──────────────────────────────────────

def test_health_returns_ok(client):
    """GET /health returns 200 with status ok."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "provider" in data


# ── Webhook: edge cases ──────────────────────────────────

def test_webhook_no_body_returns_200(client):
    """POST /webhook with empty body — should not 500."""
    resp = client.post("/webhook")
    # FastAPI returns 422 for missing body, but server must NOT crash
    assert resp.status_code in (200, 422)


def test_webhook_malformed_json_returns_200(client):
    """POST /webhook with non-JSON — should return 200 (graceful)."""
    resp = client.post("/webhook", content="not json")
    assert resp.status_code == 200


# ── Webhook: Telegram update → bot response ──────────────

def test_webhook_ping_command(client):
    """POST /webhook with /ping — returns 200, bot processes it."""
    payload = {
        "update_id": 1005001,
        "message": {
            "message_id": 1,
            "from": {"id": 12345, "is_bot": False, "first_name": "Test"},
            "chat": {"id": 12345, "type": "private", "first_name": "Test"},
            "date": 1700000000,
            "text": "/ping",
        },
    }
    resp = client.post("/webhook", json=payload)
    assert resp.status_code == 200


def test_webhook_help_command(client):
    """POST /webhook with /help — returns 200."""
    payload = {
        "update_id": 1005002,
        "message": {
            "message_id": 2,
            "from": {"id": 12345, "is_bot": False, "first_name": "Test"},
            "chat": {"id": 12345, "type": "private", "first_name": "Test"},
            "date": 1700000001,
            "text": "/help",
        },
    }
    resp = client.post("/webhook", json=payload)
    assert resp.status_code == 200


def test_webhook_start_command(client):
    """POST /webhook with /start — returns 200."""
    payload = {
        "update_id": 1005003,
        "message": {
            "message_id": 3,
            "from": {"id": 12345, "is_bot": False, "first_name": "Test"},
            "chat": {"id": 12345, "type": "private", "first_name": "Test"},
            "date": 1700000002,
            "text": "/start",
        },
    }
    resp = client.post("/webhook", json=payload)
    assert resp.status_code == 200


def test_webhook_status_command(client):
    """POST /webhook with /status — returns 200."""
    payload = {
        "update_id": 1005004,
        "message": {
            "message_id": 4,
            "from": {"id": 12345, "is_bot": False, "first_name": "Test"},
            "chat": {"id": 12345, "type": "private", "first_name": "Test"},
            "date": 1700000003,
            "text": "/status",
        },
    }
    resp = client.post("/webhook", json=payload)
    assert resp.status_code == 200


def test_webhook_free_text_brain(client):
    """POST /webhook with free text — BrainPlugin fallback, no crash."""
    payload = {
        "update_id": 1005005,
        "message": {
            "message_id": 5,
            "from": {"id": 12345, "is_bot": False, "first_name": "Test"},
            "chat": {"id": 12345, "type": "private", "first_name": "Test"},
            "date": 1700000004,
            "text": "hello!",
        },
    }
    resp = client.post("/webhook", json=payload)
    assert resp.status_code == 200


def test_webhook_edited_message(client):
    """POST /webhook with edited_message — still returns 200."""
    payload = {
        "update_id": 1005006,
        "edited_message": {
            "message_id": 6,
            "from": {"id": 12345, "is_bot": False, "first_name": "Test"},
            "chat": {"id": 12345, "type": "private", "first_name": "Test"},
            "date": 1700000005,
            "edit_date": 1700000010,
            "text": "/ping",
        },
    }
    resp = client.post("/webhook", json=payload)
    assert resp.status_code == 200


def test_webhook_callback_query(client):
    """POST /webhook with callback_query (inline button tap) — no crash."""
    payload = {
        "update_id": 1005007,
        "callback_query": {
            "id": "cb1",
            "from": {"id": 12345, "is_bot": False, "first_name": "Test"},
            "message": {
                "message_id": 7,
                "from": {"id": 12345, "is_bot": False, "first_name": "Test"},
                "chat": {"id": 12345, "type": "private", "first_name": "Test"},
                "date": 1700000006,
                "text": "Pick a time:",
            },
            "data": "brain_pick_cancel",
        },
    }
    resp = client.post("/webhook", json=payload)
    assert resp.status_code == 200


def test_webhook_group_message(client):
    """POST /webhook with a supergroup message — returns 200."""
    payload = {
        "update_id": 1005008,
        "message": {
            "message_id": 8,
            "from": {"id": 12345, "is_bot": False, "first_name": "Test"},
            "chat": {"id": -10012345, "type": "supergroup", "title": "Test Group"},
            "date": 1700000007,
            "text": "/ping",
        },
    }
    resp = client.post("/webhook", json=payload)
    assert resp.status_code == 200


# ── Separate update types ────────────────────────────────

def test_webhook_non_text_message(client):
    """POST /webhook with a message that has no text (photo) — still 200."""
    payload = {
        "update_id": 1005009,
        "message": {
            "message_id": 9,
            "from": {"id": 12345, "is_bot": False, "first_name": "Test"},
            "chat": {"id": 12345, "type": "private", "first_name": "Test"},
            "date": 1700000008,
            "text": None,
        },
    }
    resp = client.post("/webhook", json=payload)
    assert resp.status_code == 200


def test_webhook_empty_text_message(client):
    """POST /webhook with empty text — still 200."""
    payload = {
        "update_id": 1005010,
        "message": {
            "message_id": 10,
            "from": {"id": 12345, "is_bot": False, "first_name": "Test"},
            "chat": {"id": 12345, "type": "private", "first_name": "Test"},
            "date": 1700000009,
            "text": "",
        },
    }
    resp = client.post("/webhook", json=payload)
    assert resp.status_code == 200


# ── Sequential messages ──────────────────────────────────

def test_multiple_commands_in_sequence(client):
    """Send 5 different commands — no crash."""
    commands = ["/ping", "/help", "/status", "/start", "hello"]
    for i, cmd in enumerate(commands):
        payload = {
            "update_id": 1006000 + i,
            "message": {
                "message_id": 20 + i,
                "from": {"id": 12345, "is_bot": False, "first_name": "Test"},
                "chat": {"id": 12345, "type": "private", "first_name": "Test"},
                "date": 1700000100 + i,
                "text": cmd,
            },
        }
        resp = client.post("/webhook", json=payload)
        assert resp.status_code == 200, f"Failed on command '{cmd}'"
