from datetime import datetime, timedelta, timezone
from app.rules import response_minutes, is_sla_breached

BASE = datetime(2026, 10, 1, 10, tzinfo=timezone.utc)


def test_response_minutes():
    assert response_minutes(BASE, BASE + timedelta(minutes=45)) == 45


def test_missing_response_is_none():
    assert response_minutes(BASE, None) is None


def test_sla_within_limit():
    assert not is_sla_breached(BASE, BASE + timedelta(minutes=30), 60)


def test_sla_broken():
    assert is_sla_breached(BASE, BASE + timedelta(minutes=61), 60)


def test_unanswered_ticket_becomes_overdue():
    assert is_sla_breached(BASE, None, 60, now=BASE + timedelta(minutes=61))


def test_sla_border_is_not_a_violation():
    assert not is_sla_breached(BASE, BASE + timedelta(minutes=60), 60)
