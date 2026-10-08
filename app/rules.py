from datetime import datetime, timedelta, timezone

VALID_STATUSES = ('new', 'in_progress', 'closed')


def normalize_utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def response_minutes(created_at: datetime, first_response_at: datetime | None):
    if first_response_at is None:
        return None
    return max(0, round((normalize_utc(first_response_at) - normalize_utc(created_at)).total_seconds() / 60, 2))


def is_sla_breached(created_at: datetime, first_response_at: datetime | None,
                    sla_minutes: int, now: datetime | None = None) -> bool:
    current = now or datetime.now(timezone.utc)
    end = first_response_at if first_response_at is not None else current
    return normalize_utc(end) - normalize_utc(created_at) > timedelta(minutes=sla_minutes)
