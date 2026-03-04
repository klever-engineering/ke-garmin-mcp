from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from garminconnect import Garmin

from .config import Settings


@dataclass(slots=True)
class DaySnapshot:
    calendar_date: str
    summary: dict[str, Any]
    sleep: dict[str, Any]
    activities: list[dict[str, Any]]


@dataclass(slots=True)
class SleepNight:
    calendar_date: str
    sleep_time_seconds: int | None
    deep_sleep_seconds: int | None
    light_sleep_seconds: int | None
    rem_sleep_seconds: int | None
    awake_sleep_seconds: int | None
    source_payload: dict[str, Any]


class GarminAuthError(RuntimeError):
    """Raised when no valid Garmin auth path is available."""


def parse_date(value: str, *, field_name: str = "date") -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"{field_name} must be in YYYY-MM-DD format.") from exc


def validate_date_range(start_date: str, end_date: str, *, max_days: int) -> tuple[date, date]:
    start = parse_date(start_date, field_name="start_date")
    end = parse_date(end_date, field_name="end_date")
    if end < start:
        raise ValueError("end_date must be on or after start_date.")
    days = (end - start).days + 1
    if days > max_days:
        raise ValueError(f"Date range too large ({days} days). Max allowed is {max_days}.")
    return start, end


def login(settings: Settings, force_credentials: bool = False) -> Garmin:
    api = Garmin(email=settings.garmin_username, password=settings.garmin_password)
    tokenstore = str(settings.garmin_tokens_dir)

    if not force_credentials:
        try:
            api.login(tokenstore=tokenstore)
            return api
        except FileNotFoundError:
            pass
        except Exception:
            # Token files can expire or become invalid; fallback to credentials.
            pass

    if not settings.garmin_username or not settings.garmin_password:
        raise GarminAuthError(
            "GARMIN_USERNAME/GARMIN_PASSWORD are required for first login."
        )

    api.login()
    settings.garmin_tokens_dir.mkdir(parents=True, exist_ok=True)
    api.garth.dump(tokenstore)
    return api


def compact_activity(activity: dict[str, Any]) -> dict[str, Any]:
    return {
        "activity_id": activity.get("activityId"),
        "name": activity.get("activityName"),
        "type": (activity.get("activityType") or {}).get("typeKey"),
        "start_time_local": activity.get("startTimeLocal"),
        "duration_seconds": activity.get("duration"),
        "distance_meters": activity.get("distance"),
        "average_heart_rate": activity.get("averageHR"),
        "max_heart_rate": activity.get("maxHR"),
    }


def _extract_sleep_dto(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    dto = payload.get("dailySleepDTO")
    if not isinstance(dto, dict):
        return {}
    return dto


def compact_sleep_dto(payload: dict[str, Any]) -> dict[str, Any]:
    dto = _extract_sleep_dto(payload)
    return {
        "calendar_date": dto.get("calendarDate"),
        "sleep_time_seconds": dto.get("sleepTimeSeconds"),
        "deep_sleep_seconds": dto.get("deepSleepSeconds"),
        "light_sleep_seconds": dto.get("lightSleepSeconds"),
        "rem_sleep_seconds": dto.get("remSleepSeconds"),
        "awake_sleep_seconds": dto.get("awakeSleepSeconds"),
    }


def fetch_day_snapshot(api: Garmin, target_date: date) -> DaySnapshot:
    day = target_date.isoformat()
    summary = api.get_user_summary(day)
    sleep = api.get_sleep_data(day)
    activities = api.get_activities_by_date(day, day)
    return DaySnapshot(
        calendar_date=day,
        summary=summary if isinstance(summary, dict) else {},
        sleep=sleep if isinstance(sleep, dict) else {},
        activities=activities if isinstance(activities, list) else [],
    )


def fetch_activities_range(
    api: Garmin, start: date, end: date, *, activity_type: str | None = None
) -> list[dict[str, Any]]:
    activities = api.get_activities_by_date(start.isoformat(), end.isoformat())
    if not isinstance(activities, list):
        return []

    if not activity_type:
        return activities

    activity_type_normalized = activity_type.strip().lower()
    return [
        activity
        for activity in activities
        if ((activity.get("activityType") or {}).get("typeKey") or "").lower()
        == activity_type_normalized
    ]


def fetch_sleep_range(api: Garmin, start: date, end: date) -> list[SleepNight]:
    rows: list[SleepNight] = []
    cursor = start
    while cursor <= end:
        day = cursor.isoformat()
        payload = api.get_sleep_data(day)
        payload_dict = payload if isinstance(payload, dict) else {}
        dto = _extract_sleep_dto(payload_dict)
        rows.append(
            SleepNight(
                calendar_date=day,
                sleep_time_seconds=dto.get("sleepTimeSeconds"),
                deep_sleep_seconds=dto.get("deepSleepSeconds"),
                light_sleep_seconds=dto.get("lightSleepSeconds"),
                rem_sleep_seconds=dto.get("remSleepSeconds"),
                awake_sleep_seconds=dto.get("awakeSleepSeconds"),
                source_payload=payload_dict,
            )
        )
        cursor += timedelta(days=1)
    return rows


def summarize_sleep(rows: list[SleepNight]) -> dict[str, Any]:
    nights = [row for row in rows if isinstance(row.sleep_time_seconds, (int, float)) and row.sleep_time_seconds > 0]
    if not nights:
        return {
            "tracked_nights": 0,
            "average_sleep_seconds": None,
            "median_sleep_seconds": None,
            "below_6h_count": 0,
            "below_7h_count": 0,
            "at_or_above_8h_count": 0,
        }

    sleep_values = [int(row.sleep_time_seconds) for row in nights if row.sleep_time_seconds is not None]
    sleep_values_sorted = sorted(sleep_values)
    middle = len(sleep_values_sorted) // 2
    if len(sleep_values_sorted) % 2 == 0:
        median = int((sleep_values_sorted[middle - 1] + sleep_values_sorted[middle]) / 2)
    else:
        median = sleep_values_sorted[middle]

    return {
        "tracked_nights": len(nights),
        "average_sleep_seconds": int(sum(sleep_values) / len(sleep_values)),
        "median_sleep_seconds": median,
        "below_6h_count": sum(1 for value in sleep_values if value < 6 * 3600),
        "below_7h_count": sum(1 for value in sleep_values if value < 7 * 3600),
        "at_or_above_8h_count": sum(1 for value in sleep_values if value >= 8 * 3600),
    }

