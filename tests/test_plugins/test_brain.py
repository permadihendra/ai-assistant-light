"""Tests for BrainPlugin — TOOL: parsing and tool parameter extraction."""

import pytest
from app.plugins.brain.handler import BrainPlugin


@pytest.fixture
def brain():
    return BrainPlugin()


# ── Tool param parsing ───────────────────────────────────

def test_parse_tool_params_simple(brain):
    """Simple quoted parameters."""
    result = brain._parse_tool_params('time="tomorrow 09:00", text="buy milk"')
    assert result == {"time": "tomorrow 09:00", "text": "buy milk"}


def test_parse_tool_params_json_items(brain):
    """JSON array as parameter value."""
    result = brain._parse_tool_params(
        'items=[{"date":"2026-05-26","time":"09:00","text":"Meeting"}]'
    )
    assert "items" in result
    assert '"date":"2026-05-26"' in result["items"]


def test_parse_tool_params_multiple_items(brain):
    """Multiple items in JSON array."""
    result = brain._parse_tool_params(
        'items=[{"date":"2026-05-26","time":"09:00","text":"A"},{"date":"2026-05-27","time":"10:00","text":"B"}]'
    )
    import json
    items = json.loads(result["items"])
    assert len(items) == 2
    assert items[0]["text"] == "A"
    assert items[1]["text"] == "B"


def test_parse_tool_params_unquoted(brain):
    """Unquoted simple value."""
    result = brain._parse_tool_params('id=42')
    assert result == {"id": "42"}


def test_parse_tool_params_empty(brain):
    """Empty string returns empty dict."""
    assert brain._parse_tool_params("") == {}
