"""Tests for BrainPlugin pending state tracker."""

import pytest
from app.plugins.brain import state as pending_state


def test_pending_empty_initially():
    """No pending state for any chat initially."""
    assert pending_state.get(999999) is None
    assert pending_state.has(999999) is False


def test_pending_set_and_get():
    """Set pending state, then get it back."""
    data = {"stage": "confirm", "actions": [{"action": "search", "query": "test"}]}
    pending_state.set(42, data)
    result = pending_state.get(42)
    assert result == data
    assert result["stage"] == "confirm"
    assert len(result["actions"]) == 1


def test_pending_has():
    """has() returns True for chats with pending state."""
    pending_state.set(100, {"stage": "ask_time"})
    assert pending_state.has(100) is True
    assert pending_state.has(200) is False


def test_pending_clear():
    """clear() removes pending state."""
    pending_state.set(50, {"stage": "confirm"})
    assert pending_state.has(50) is True
    pending_state.clear(50)
    assert pending_state.has(50) is False
    assert pending_state.get(50) is None


def test_pending_clear_nonexistent():
    """clear() on nonexistent chat should not raise."""
    # Should not throw
    pending_state.clear(999999)
    assert True


def test_pending_overwrite():
    """set() with same chat_id overwrites previous state."""
    pending_state.set(1, {"stage": "ask_time"})
    pending_state.set(1, {"stage": "confirm", "extra": "data"})
    result = pending_state.get(1)
    assert result["stage"] == "confirm"
    assert result["extra"] == "data"


def test_pending_multiple_chats():
    """Multiple chats can have independent pending states."""
    pending_state.set(10, {"stage": "ask_time"})
    pending_state.set(20, {"stage": "confirm"})
    pending_state.set(30, {"stage": "ask_text"})

    assert pending_state.get(10)["stage"] == "ask_time"
    assert pending_state.get(20)["stage"] == "confirm"
    assert pending_state.get(30)["stage"] == "ask_text"

    pending_state.clear(20)
    assert pending_state.has(20) is False
    assert pending_state.has(10) is True
    assert pending_state.has(30) is True
