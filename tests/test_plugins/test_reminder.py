"""Tests for ReminderPlugin time parser — bilingual (EN/ID), edge cases."""

import pytest
from datetime import datetime, timedelta, timezone
from app.plugins.reminder.handler import _parse_time


def test_parse_relative_seconds():
    """Relative: '30s' → 30 detik dari sekarang."""
    dt = _parse_time("30s")
    assert dt is not None
    diff = (dt - datetime.now(timezone.utc)).total_seconds()
    assert 28 <= diff <= 32


def test_parse_relative_minutes():
    """Relative: '10m' → 10 menit dari sekarang."""
    dt = _parse_time("10m")
    assert dt is not None
    diff = (dt - datetime.now(timezone.utc)).total_seconds()
    assert 598 <= diff <= 602  # ~10 menit


def test_parse_relative_hours():
    """Relative: '2h' → 2 jam dari sekarang."""
    dt = _parse_time("2h")
    assert dt is not None
    diff = (dt - datetime.now(timezone.utc)).total_seconds()
    assert 7190 <= diff <= 7210  # ~2 jam


def test_parse_english_tomorrow():
    """English: 'tomorrow 09:00' — should return a time ~24h from now."""
    dt = _parse_time("tomorrow 09:00")
    assert dt is not None
    # Should be in the future
    assert dt > datetime.now(timezone.utc)
    # Should be within the next 48 hours
    assert (dt - datetime.now(timezone.utc)).total_seconds() < 48 * 3600


def test_parse_indonesian_besok():
    """Indonesian: 'besok 09:00' — should work like 'tomorrow'."""
    dt = _parse_time("besok 09:00")
    assert dt is not None
    assert dt > datetime.now(timezone.utc)


def test_parse_besok_without_hour():
    """Indonesian: 'besok' without hour — should default to 09:00 WIB."""
    dt = _parse_time("besok")
    assert dt is not None
    assert dt > datetime.now(timezone.utc)


def test_parse_hour_minute_today():
    """Time-only: '14:30' — today if future, else tomorrow."""
    dt = _parse_time("14:30")
    assert dt is not None
    assert dt > datetime.now(timezone.utc) - timedelta(hours=1)  # same day or tomorrow


def test_parse_hour_am_pm():
    """AM/PM: '2pm' should be 14:00."""
    dt = _parse_time("2pm")
    assert dt is not None
    # hours should be 14 (2pm) in WIB
    wib = dt.astimezone(timezone(timedelta(hours=7)))
    assert wib.hour == 14


def test_parse_hour_am():
    """AM: '9am' should be 09:00."""
    dt = _parse_time("9am")
    assert dt is not None
    wib = dt.astimezone(timezone(timedelta(hours=7)))
    assert wib.hour == 9


def test_parse_ddmmyyyy():
    """Specific date: '20/05/2026 09:00' — explicit date + time."""
    dt = _parse_time("20/05/2026 09:00")
    assert dt is not None
    wib = dt.astimezone(timezone(timedelta(hours=7)))
    assert wib.day == 20
    assert wib.month == 5
    assert wib.year == 2026
    assert wib.hour == 9


def test_parse_iso_date():
    """ISO date: '2026-06-01 08:00'."""
    dt = _parse_time("2026-06-01 08:00")
    assert dt is not None
    wib = dt.astimezone(timezone(timedelta(hours=7)))
    assert wib.day == 1
    assert wib.month == 6
    assert wib.year == 2026
    assert wib.hour == 8


def test_parse_natural_indonesian():
    """Indonesian: 'nanti 30 menit'."""
    dt = _parse_time("nanti 30 menit")
    assert dt is not None
    diff = (dt - datetime.now(timezone.utc)).total_seconds()
    assert 1780 <= diff <= 1820  # ~30 menit


def test_parse_in_english():
    """English: 'in 10 minutes'."""
    dt = _parse_time("in 10 minutes")
    assert dt is not None
    diff = (dt - datetime.now(timezone.utc)).total_seconds()
    assert 598 <= diff <= 602


def test_parse_5_detik_lagi():
    """Indonesian: '5 detik lagi'."""
    dt = _parse_time("5 detik lagi")
    assert dt is not None
    diff = (dt - datetime.now(timezone.utc)).total_seconds()
    assert 3 <= diff <= 7


def test_parse_now_returns_future():
    """'now' should be ~1 menit dari sekarang."""
    dt = _parse_time("now")
    assert dt is not None
    diff = (dt - datetime.now(timezone.utc)).total_seconds()
    assert 55 <= diff <= 120  # 1 menit (± toleransi)


def test_parse_lusa():
    """Indonesian: 'lusa' (day after tomorrow)."""
    dt = _parse_time("lusa 09:00")
    assert dt is not None
    # Should be ~2 days from now
    diff = (dt - datetime.now(timezone.utc)).total_seconds()
    assert 24 * 3600 < diff < 72 * 3600


def test_parse_weekday_english():
    """English weekday: 'next monday 09:00'."""
    dt = _parse_time("next monday 09:00")
    assert dt is not None
    assert dt > datetime.now(timezone.utc)
    wib = dt.astimezone(timezone(timedelta(hours=7)))
    assert wib.hour == 9
    # Monday is weekday 0
    assert wib.weekday() == 0


def test_parse_invalid_returns_none():
    """Garbage input should return None."""
    assert _parse_time("") is None
    assert _parse_time("not a time") is None
    assert _parse_time("abc123xyz") is None
    assert _parse_time("  ") is None
