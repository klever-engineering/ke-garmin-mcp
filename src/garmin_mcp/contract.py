"""Response contract: the payload each operation returns to its callers.

Both entry points use these functions, so the CLI command and the MCP tool for
an operation return the same dict (the MCP tool adds only `"ok": True`). Change
response shape here, never in cli.py or mcp_server.py. Field rules (units in
key names, null for missing values, wear_data) are documented in the README.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from importlib import metadata
from typing import Any

from .client import (
    CaloriesDay,
    SleepNight,
    calories_has_data,
    compact_activity,
    compact_calories,
    compact_daily_summary,
    compact_sleep_dto,
    fetch_activities_range,
    fetch_calories_range,
    fetch_day_snapshot,
    fetch_health_range,
    fetch_sleep_range,
    sleep_has_data,
    summarize_calories,
    summarize_health_history,
    summarize_sleep,
    wear_data_status,
)


PROVIDER = "garmin_connect"


def _version(package: str) -> str:
    try:
        return f"{package} {metadata.version(package)}"
    except metadata.PackageNotFoundError:
        return package


def source(*endpoints: str) -> dict[str, Any]:
    """Where and when the values were read (OUT_01 source attribution).

    Dates in every response are Garmin calendar dates in the account's local
    time zone, as Garmin Connect reports them.
    """
    return {
        "provider": PROVIDER,
        "client": _version("garminconnect"),
        # Contract version (ADR 0006); see CHANGELOG.md.
        "server": _version("garmin-mcp"),
        "endpoints": list(endpoints),
        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "date_basis": "garmin_calendar_date_local",
    }


def _range(start: date, end: date) -> dict[str, str]:
    return {"start_date": start.isoformat(), "end_date": end.isoformat()}


def day_overview(api: Any, day: date) -> dict[str, Any]:
    snapshot = fetch_day_snapshot(api, day)
    return {
        "calendar_date": snapshot.calendar_date,
        "wear_data": wear_data_status(snapshot.summary),
        "daily_summary": compact_daily_summary(snapshot.summary),
        "calories": compact_calories(snapshot.summary),
        "sleep": compact_sleep_dto(snapshot.sleep),
        "workouts": [compact_activity(activity) for activity in snapshot.activities],
        "source": source("get_user_summary", "get_sleep_data", "get_activities_by_date"),
    }


def activities(api: Any, start: date, end: date, activity_type: str = "") -> dict[str, Any]:
    rows = fetch_activities_range(api, start, end, activity_type=activity_type.strip() or None)
    return {
        **_range(start, end),
        "count": len(rows),
        "activities": [compact_activity(activity) for activity in rows],
        "source": source("get_activities_by_date"),
    }


def sleep_row(row: SleepNight) -> dict[str, Any]:
    return {
        "calendar_date": row.calendar_date,
        "sleep_time_seconds": row.sleep_time_seconds,
        "deep_sleep_seconds": row.deep_sleep_seconds,
        "light_sleep_seconds": row.light_sleep_seconds,
        "rem_sleep_seconds": row.rem_sleep_seconds,
        "awake_sleep_seconds": row.awake_sleep_seconds,
    }


def sleep_range(api: Any, start: date, end: date, include_empty: bool = False) -> dict[str, Any]:
    rows = fetch_sleep_range(api, start, end)
    return {
        **_range(start, end),
        "summary": summarize_sleep(rows),
        "rows": [sleep_row(row) for row in rows if include_empty or sleep_has_data(row)],
        "source": source("get_sleep_data"),
    }


def calories_row(row: CaloriesDay) -> dict[str, Any]:
    return {
        "calendar_date": row.calendar_date,
        "wear_data": row.wear_data,
        "estimate": row.estimate,
        "total_kilocalories": row.total_kilocalories,
        "active_kilocalories": row.active_kilocalories,
        "bmr_kilocalories": row.bmr_kilocalories,
        "wellness_kilocalories": row.wellness_kilocalories,
        "consumed_kilocalories": row.consumed_kilocalories,
        "remaining_kilocalories": row.remaining_kilocalories,
    }


def calories(api: Any, start: date, end: date, include_empty: bool = False) -> dict[str, Any]:
    rows = fetch_calories_range(api, start, end)
    return {
        **_range(start, end),
        "summary": summarize_calories(rows),
        "rows": [calories_row(row) for row in rows if include_empty or calories_has_data(row)],
        "source": source("get_user_summary"),
    }


def health_history(api: Any, start: date, end: date) -> dict[str, Any]:
    rows = fetch_health_range(api, start, end)
    return {
        **_range(start, end),
        "summary": summarize_health_history(rows),
        "rows": rows,
        "source": source("get_body_battery", "get_user_summary"),
    }
