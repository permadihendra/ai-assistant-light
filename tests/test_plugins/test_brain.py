"""Tests for BrainPlugin — JSON parsing, action validation, language detection."""

import pytest
from app.plugins.brain.handler import BrainPlugin, _has_explicit_hour, _lang


# ── Fixture ──────────────────────────────────────────────

@pytest.fixture
def brain():
    return BrainPlugin()


# ── JSON Parsing ─────────────────────────────────────────

def test_parse_actions_valid_json(brain):
    """Valid single action JSON."""
    result = brain._parse_actions('{"action": "search", "query": "fastapi"}')
    assert result == [{"action": "search", "query": "fastapi"}]


def test_parse_actions_array(brain):
    """Valid actions array JSON."""
    result = brain._parse_actions(
        '[{"action": "chat", "text": "hello"}, {"action": "search", "query": "test"}]'
    )
    assert len(result) == 2
    assert result[0]["action"] == "chat"
    assert result[1]["action"] == "search"


def test_parse_actions_with_wrapper(brain):
    """JSON with 'actions' wrapper key."""
    result = brain._parse_actions(
        '{"actions": [{"action": "remind_create", "time": "tomorrow", "text": "meeting"}]}'
    )
    assert len(result) == 1
    assert result[0]["action"] == "remind_create"
    assert result[0]["time"] == "tomorrow"


def test_parse_actions_code_fence_json(brain):
    """Gemini sometimes wraps JSON in ```json ... ```."""
    result = brain._parse_actions(
        '```json\n{"action": "ping"}\n```'
    )
    assert result == [{"action": "ping"}]


def test_parse_actions_code_fence_no_lang(brain):
    """Gemini sometimes wraps in ``` without language tag."""
    result = brain._parse_actions(
        '```\n{"action": "help"}\n```'
    )
    assert result == [{"action": "help"}]


def test_parse_actions_inline_backtick(brain):
    """Sometimes wrapped in single backticks: `{...}`."""
    result = brain._parse_actions('`{"action": "status"}`')
    assert result == [{"action": "status"}]


def test_parse_actions_malformed_not_json(brain):
    """If Gemini returns non-JSON, should return None."""
    result = brain._parse_actions("Hello! How can I help you?")
    assert result is None


def test_parse_actions_empty_string(brain):
    """Empty input should return None."""
    result = brain._parse_actions("")
    assert result is None


def test_parse_actions_whitespace_only(brain):
    """Whitespace-only should return None."""
    result = brain._parse_actions("   \n  \t  ")
    assert result is None


def test_parse_actions_mixed_text_and_json(brain):
    """If Gemini adds text before/after JSON, still extract."""
    result = brain._parse_actions(
        'Here you go:\n```\n{"action": "chat", "text": "Sure!"}\n```\nHope that helps!'
    )
    assert result == [{"action": "chat", "text": "Sure!"}]


def test_parse_actions_extract_actions_array(brain):
    """Extract 'actions' array even with surrounding text."""
    result = brain._parse_actions(
        'Some text... {"actions": [{"action": "search", "query": "pytest"}]} more text'
    )
    assert len(result) == 1
    assert result[0]["action"] == "search"
    assert result[0]["query"] == "pytest"


# ── _has_explicit_hour ───────────────────────────────────

def test_has_explicit_hour_tomorrow_only():
    """'tomorrow' alone → False (no hour)."""
    assert _has_explicit_hour("tomorrow") is False


def test_has_explicit_hour_tomorrow_with_time():
    """'tomorrow 09:00' → True."""
    assert _has_explicit_hour("tomorrow 09:00") is True


def test_has_explicit_hour_besok_only():
    """'besok' alone → False."""
    assert _has_explicit_hour("besok") is False


def test_has_explicit_hour_besok_with_time():
    """'besok 09:00' → True."""
    assert _has_explicit_hour("besok 09:00") is True


def test_has_explicit_hour_with_am_pm():
    """'tomorrow 2pm' → True."""
    assert _has_explicit_hour("tomorrow 2pm") is True


def test_has_explicit_hour_date_only():
    """'20/05/2026' → False (no hour)."""
    assert _has_explicit_hour("20/05/2026") is False


def test_has_explicit_hour_date_with_time():
    """'20/05/2026 09:00' → True."""
    assert _has_explicit_hour("20/05/2026 09:00") is True


def test_has_explicit_hour_dot_separator():
    """'besok 9.00' → True (dot as separator)."""
    assert _has_explicit_hour("besok 9.00") is True


# ── _lang detection ──────────────────────────────────────

def test_lang_indonesian():
    """Indonesian keywords → 'id'."""
    assert _lang("besok jam 9") == "id"


def test_lang_english():
    """English keywords → 'en'."""
    assert _lang("tomorrow at 9") == "en"


def test_lang_mixed_id_wins():
    """Mixed keywords: 'besok hello' → 'id' (besok triggers ID).
    
    'hello' is NOT in en_words list, 'besok' IS in id_words list.
    So ID wins with 1 vs 0.
    """
    result = _lang("besok hello")
    assert result == "id"


def test_lang_empty():
    """Empty message → 'en' (default)."""
    assert _lang("") == "en"


def test_lang_indonesian_remind():
    """Indonesian reminder keywords."""
    assert _lang("tolong ingatkan saya beli susu") == "id"
