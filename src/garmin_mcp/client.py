from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from statistics import median
from typing import Any

import requests
from garminconnect import Garmin, GarminConnectAuthenticationError

from .config import Settings


@dataclass(slots=True)
class DaySnapshot:
    calendar_date: str
    summary: dict[str, Any]
    sleep: dict[str, Any]
    activities: list[dict[str, Any]]


@dataclass(slots=True)
class CaloriesDay:
    calendar_date: str
    total_kilocalories: int | None
    active_kilocalories: int | None
    bmr_kilocalories: int | None
    wellness_kilocalories: int | None
    consumed_kilocalories: int | None
    remaining_kilocalories: int | None
    source_payload: dict[str, Any]
    wear_data: bool | None = None
    estimate: str | None = None


@dataclass(slots=True)
class SleepNight:
    calendar_date: str
    sleep_time_seconds: int | None
    deep_sleep_seconds: int | None
    light_sleep_seconds: int | None
    rem_sleep_seconds: int | None
    awake_sleep_seconds: int | None
    source_payload: dict[str, Any]


logger = logging.getLogger(__name__)

NETWORK_ERRORS = (requests.exceptions.ConnectionError, requests.exceptions.Timeout, ConnectionError, TimeoutError)


class GarminAuthError(RuntimeError):
    """Raised when no valid Garmin auth path is available."""


def _cause_chain(exc: BaseException) -> list[BaseException]:
    chain: list[BaseException] = []
    current: BaseException | None = exc
    while current is not None and current not in chain and len(chain) < 10:
        chain.append(current)
        current = current.__cause__ or current.__context__
    return chain


def is_token_problem(exc: BaseException) -> bool:
    """True when a token login failed because the stored tokens are unusable.

    Only then is a username/password login justified. Network failures, rate
    limits and other errors must surface instead: a password login would not
    fix them and repeated credential logins risk Garmin rate limits or an
    account lock. garminconnect can wrap a network failure in an
    authentication error (for example "Failed to retrieve profile"), so the
    root cause decides.
    """
    chain = _cause_chain(exc)
    if any(isinstance(item, NETWORK_ERRORS) for item in chain):
        return False
    if isinstance(exc, FileNotFoundError):
        return True  # no tokens saved yet
    if any(isinstance(item, json.JSONDecodeError) for item in chain):
        return True  # corrupt token file
    return isinstance(exc, GarminConnectAuthenticationError)


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
        except Exception as exc:
            if not is_token_problem(exc):
                raise
            # Log the reason class only; messages may contain account details.
            logger.warning("Garmin token login failed (%s); using credential login", type(exc).__name__)

    if not settings.garmin_username or not settings.garmin_password:
        raise GarminAuthError(
            "GARMIN_USERNAME/GARMIN_PASSWORD are required for first login."
        )

    api.login()
    settings.garmin_tokens_dir.mkdir(parents=True, exist_ok=True)
    api.garth.dump(tokenstore)
    return api


def compact_activity(activity: dict[str, Any]) -> dict[str, Any]:
    compact = {
        "activity_id": activity.get("activityId"),
        "name": activity.get("activityName"),
        "type": (activity.get("activityType") or {}).get("typeKey"),
        "start_time_local": activity.get("startTimeLocal"),
        "duration_seconds": activity.get("duration"),
        "distance_meters": activity.get("distance"),
        "average_heart_rate": activity.get("averageHR"),
        "max_heart_rate": activity.get("maxHR"),
    }
    # Garmin zone time is observed data, not an estimate. Retain None when the
    # record omits a zone so consumers can distinguish missing from zero.
    for zone in range(1, 6):
        compact[f"heart_rate_zone_{zone}_seconds"] = activity.get(f"hrTimeInZone_{zone}")
    return compact


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


FULL_DAY_SECONDS = 24 * 60 * 60


def wear_data_status(summary: dict[str, Any] | None) -> bool | None:
    """Classify a Garmin daily summary by whether the watch recorded the day.

    True: the device recorded the day (steps are present, even if few).
    False: Garmin's filler for a day without wear data. Observed 2026-10-25 on
        real no-wear days: totalSteps is null, averageStressLevel is -1 and
        sedentarySeconds is 86400, while distance and active kcal are 0 and the
        calorie total is only the BMR estimate. See README "No-wear day semantics".
    None: no Garmin record for the date (for example before any device).
    """
    if not isinstance(summary, dict):
        return None
    if summary.get("totalSteps") is not None:
        return True
    if summary.get("averageStressLevel") == -1 or summary.get("sedentarySeconds") == FULL_DAY_SECONDS:
        return False
    return None


def compact_daily_summary(summary: dict[str, Any] | None) -> dict[str, Any]:
    summary = summary if isinstance(summary, dict) else {}
    # On a no-wear day Garmin reports 0 distance and 0 active kcal; those are
    # not measurements, so return them as missing.
    measured = wear_data_status(summary) is not False
    return {
        "steps": summary.get("totalSteps"),
        "distance_meters": summary.get("totalDistanceMeters") if measured else None,
        "active_kilocalories": summary.get("activeKilocalories") if measured else None,
        "resting_heart_rate": summary.get("restingHeartRate"),
    }


def _coerce_kcal(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    return None


def compact_calories(summary: dict[str, Any] | None) -> dict[str, Any]:
    summary = summary if isinstance(summary, dict) else {}
    wear_data = wear_data_status(summary)
    no_wear = wear_data is False
    return {
        "calendar_date": summary.get("calendarDate"),
        "wear_data": wear_data,
        # On a no-wear day the total is Garmin's BMR estimate, not a measurement.
        "estimate": "bmr_only" if no_wear else None,
        "total_kilocalories": _coerce_kcal(summary.get("totalKilocalories")),
        "active_kilocalories": None if no_wear else _coerce_kcal(summary.get("activeKilocalories")),
        "bmr_kilocalories": _coerce_kcal(summary.get("bmrKilocalories")),
        "wellness_kilocalories": _coerce_kcal(summary.get("wellnessKilocalories")),
        "consumed_kilocalories": _coerce_kcal(summary.get("consumedKilocalories")),
        "remaining_kilocalories": _coerce_kcal(summary.get("remainingKilocalories")),
    }


def fetch_calories_range(api: Garmin, start: date, end: date) -> list[CaloriesDay]:
    rows: list[CaloriesDay] = []
    cursor = start
    while cursor <= end:
        day = cursor.isoformat()
        summary = api.get_user_summary(day)
        summary_dict = summary if isinstance(summary, dict) else {}
        compact = compact_calories(summary_dict)
        rows.append(
            CaloriesDay(
                calendar_date=day,
                total_kilocalories=compact["total_kilocalories"],
                active_kilocalories=compact["active_kilocalories"],
                bmr_kilocalories=compact["bmr_kilocalories"],
                wellness_kilocalories=compact["wellness_kilocalories"],
                consumed_kilocalories=compact["consumed_kilocalories"],
                remaining_kilocalories=compact["remaining_kilocalories"],
                source_payload=summary_dict,
                wear_data=compact["wear_data"],
                estimate=compact["estimate"],
            )
        )
        cursor += timedelta(days=1)
    return rows


def calories_has_data(row: CaloriesDay) -> bool:
    """A day counts as tracked only if it was worn and has calorie values."""
    return row.wear_data is not False and bool(row.total_kilocalories or row.active_kilocalories)


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


def summarize_calories(rows: list[CaloriesDay]) -> dict[str, Any]:
    tracked = [row for row in rows if calories_has_data(row)]
    if not tracked:
        return {
            "tracked_days": 0,
            "total_active_kilocalories": 0,
            "total_burned_kilocalories": 0,
            "average_active_kilocalories": None,
            "average_total_kilocalories": None,
        }

    active_values = [row.active_kilocalories for row in tracked if row.active_kilocalories is not None]
    total_values = [row.total_kilocalories for row in tracked if row.total_kilocalories is not None]
    return {
        "tracked_days": len(tracked),
        "total_active_kilocalories": sum(active_values),
        "total_burned_kilocalories": sum(total_values),
        "average_active_kilocalories": (
            int(sum(active_values) / len(active_values)) if active_values else None
        ),
        "average_total_kilocalories": (
            int(sum(total_values) / len(total_values)) if total_values else None
        ),
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


def day_overview_payload(snapshot: DaySnapshot) -> dict[str, Any]:
    """Shape one day for agents; shared by the CLI and the MCP tool."""
    return {
        "calendar_date": snapshot.calendar_date,
        "wear_data": wear_data_status(snapshot.summary),
        "daily_summary": compact_daily_summary(snapshot.summary),
        "calories": compact_calories(snapshot.summary),
        "sleep": compact_sleep_dto(snapshot.sleep),
        "workouts": [compact_activity(activity) for activity in snapshot.activities],
    }


def fetch_health_range(api: Garmin, start: date, end: date) -> list[dict[str, Any]]:
    """Fetch daily resting HR and Body Battery charged/drained for an inclusive range."""
    battery_rows = api.get_body_battery(start.isoformat(), end.isoformat())
    battery_by_date = {
        row["date"]: row
        for row in battery_rows
        if isinstance(row, dict) and isinstance(row.get("date"), str)
    } if isinstance(battery_rows, list) else {}
    rows: list[dict[str, Any]] = []
    cursor = start
    while cursor <= end:
        day = cursor.isoformat()
        summary = api.get_user_summary(day)
        summary = summary if isinstance(summary, dict) else {}
        battery = battery_by_date.get(day, {})
        samples = battery.get("bodyBatteryValuesArray") or []
        values = [
            sample[1] for sample in samples
            if isinstance(sample, (list, tuple)) and len(sample) > 1
            and isinstance(sample[1], (int, float)) and not isinstance(sample[1], bool)
        ]
        rows.append({
            "calendar_date": day,
            "wear_data": wear_data_status(summary),
            "resting_heart_rate": summary.get("restingHeartRate"),
            "body_battery_charged": battery.get("charged"),
            "body_battery_drained": battery.get("drained"),
            "body_battery_start": values[0] if values else None,
            "body_battery_end": values[-1] if values else None,
        })
        cursor += timedelta(days=1)
    return rows


def summarize_health_history(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize coverage, levels, and first-week versus last-week averages."""
    def values(items: list[dict[str, Any]], key: str) -> list[float]:
        return [item[key] for item in items if isinstance(item.get(key), (int, float))
                and not isinstance(item.get(key), bool)]

    def average(items: list[dict[str, Any]], key: str) -> float | None:
        nums = values(items, key)
        return round(sum(nums) / len(nums), 1) if nums else None

    hr_values = values(rows, "resting_heart_rate")
    battery_values = values(rows, "body_battery_charged")
    paired_battery = [row for row in rows
                      if isinstance(row.get("body_battery_charged"), (int, float))
                      and isinstance(row.get("body_battery_drained"), (int, float))]
    first_week, last_week = rows[:7], rows[-7:]
    summary: dict[str, Any] = {
        "calendar_days": len(rows),
        "resting_heart_rate_days": len(hr_values),
        "resting_heart_rate_average_bpm": average(rows, "resting_heart_rate"),
        "resting_heart_rate_median_bpm": round(median(hr_values), 1) if hr_values else None,
        "resting_heart_rate_min_bpm": min(hr_values) if hr_values else None,
        "resting_heart_rate_max_bpm": max(hr_values) if hr_values else None,
        "resting_heart_rate_first_week_days": len(values(first_week, "resting_heart_rate")),
        "resting_heart_rate_last_week_days": len(values(last_week, "resting_heart_rate")),
        "resting_heart_rate_first_week_average_bpm": average(first_week, "resting_heart_rate"),
        "resting_heart_rate_last_week_average_bpm": average(last_week, "resting_heart_rate"),
        "body_battery_days": len(battery_values),
        "body_battery_first_week_days": len(values(first_week, "body_battery_charged")),
        "body_battery_last_week_days": len(values(last_week, "body_battery_charged")),
        "body_battery_charged_average": average(rows, "body_battery_charged"),
        "body_battery_drained_average": average(rows, "body_battery_drained"),
        "body_battery_net_negative_days": sum(row["body_battery_charged"] < row["body_battery_drained"]
                                               for row in paired_battery),
        "body_battery_net_positive_days": sum(row["body_battery_charged"] > row["body_battery_drained"]
                                               for row in paired_battery),
        "body_battery_first_week_charged_average": average(first_week, "body_battery_charged"),
        "body_battery_last_week_charged_average": average(last_week, "body_battery_charged"),
    }
    first_hr = summary["resting_heart_rate_first_week_average_bpm"]
    last_hr = summary["resting_heart_rate_last_week_average_bpm"]
    if first_hr is not None and last_hr is not None:
        summary["resting_heart_rate_weekly_change_bpm"] = round(last_hr - first_hr, 1)
    first_charge = summary["body_battery_first_week_charged_average"]
    last_charge = summary["body_battery_last_week_charged_average"]
    if first_charge is not None and last_charge is not None:
        summary["body_battery_weekly_charged_change"] = round(last_charge - first_charge, 1)
    return summary


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

