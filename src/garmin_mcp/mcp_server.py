from __future__ import annotations

import argparse
from datetime import date
from typing import Any

from garminconnect import (
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)
from mcp.server.fastmcp import FastMCP

from .client import (
    GarminAuthError,
    compact_activity,
    compact_sleep_dto,
    fetch_activities_range,
    fetch_day_snapshot,
    fetch_sleep_range,
    login,
    parse_date,
    summarize_sleep,
    validate_date_range,
)
from .config import load_settings

mcp = FastMCP(
    name="lifeos.garmin-mcp",
    log_level="WARNING",
    instructions=(
        "Query Garmin Connect data for sleep, workouts, and daily metrics. "
        "Use YYYY-MM-DD dates."
    ),
)


def _get_api():
    settings = load_settings()
    api = login(settings, force_credentials=False)
    return settings, api


def _handle_known_errors(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, GarminAuthError | GarminConnectAuthenticationError):
        return {"ok": False, "error": "authentication_error", "message": str(exc)}
    if isinstance(exc, GarminConnectTooManyRequestsError):
        return {"ok": False, "error": "rate_limited", "message": str(exc)}
    if isinstance(exc, GarminConnectConnectionError):
        return {"ok": False, "error": "connection_error", "message": str(exc)}
    if isinstance(exc, ValueError):
        return {"ok": False, "error": "validation_error", "message": str(exc)}
    return {"ok": False, "error": "unexpected_error", "message": str(exc)}


@mcp.tool(
    name="garmin_get_day_overview",
    description="Get sleep, workouts, and daily summary for one date.",
)
def garmin_get_day_overview(target_date: str = date.today().isoformat()) -> dict[str, Any]:
    try:
        settings, api = _get_api()
        _ = settings
        parsed_date = parse_date(target_date)
        snapshot = fetch_day_snapshot(api, parsed_date)
        return {
            "ok": True,
            "calendar_date": snapshot.calendar_date,
            "daily_summary": {
                "steps": snapshot.summary.get("totalSteps"),
                "distance_meters": snapshot.summary.get("totalDistanceMeters"),
                "active_kilocalories": snapshot.summary.get("activeKilocalories"),
                "resting_heart_rate": snapshot.summary.get("restingHeartRate"),
            },
            "sleep": compact_sleep_dto(snapshot.sleep),
            "workouts": [compact_activity(activity) for activity in snapshot.activities],
        }
    except Exception as exc:
        return _handle_known_errors(exc)


@mcp.tool(
    name="garmin_list_activities",
    description="List activities in a date range, optionally filtered by activity type.",
)
def garmin_list_activities(
    start_date: str,
    end_date: str,
    activity_type: str = "",
) -> dict[str, Any]:
    try:
        settings, api = _get_api()
        start, end = validate_date_range(
            start_date, end_date, max_days=settings.max_range_days
        )
        activities = fetch_activities_range(
            api, start, end, activity_type=activity_type.strip() or None
        )
        return {
            "ok": True,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "count": len(activities),
            "activities": [compact_activity(activity) for activity in activities],
        }
    except Exception as exc:
        return _handle_known_errors(exc)


@mcp.tool(
    name="garmin_get_sleep_range",
    description=(
        "Get nightly sleep rows and aggregate stats in a date range."
    ),
)
def garmin_get_sleep_range(
    start_date: str,
    end_date: str,
    include_empty: bool = False,
) -> dict[str, Any]:
    try:
        settings, api = _get_api()
        start, end = validate_date_range(
            start_date, end_date, max_days=settings.max_range_days
        )
        rows = fetch_sleep_range(api, start, end)
        table: list[dict[str, Any]] = []
        for row in rows:
            has_sleep = (
                isinstance(row.sleep_time_seconds, (int, float))
                and row.sleep_time_seconds > 0
            )
            if not include_empty and not has_sleep:
                continue
            table.append(
                {
                    "calendar_date": row.calendar_date,
                    "sleep_time_seconds": row.sleep_time_seconds,
                    "deep_sleep_seconds": row.deep_sleep_seconds,
                    "light_sleep_seconds": row.light_sleep_seconds,
                    "rem_sleep_seconds": row.rem_sleep_seconds,
                    "awake_sleep_seconds": row.awake_sleep_seconds,
                }
            )

        return {
            "ok": True,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "summary": summarize_sleep(rows),
            "rows": table,
        }
    except Exception as exc:
        return _handle_known_errors(exc)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Garmin MCP server")
    parser.add_argument(
        "--transport",
        choices=("stdio", "sse", "streamable-http"),
        default="stdio",
        help="MCP transport mode.",
    )
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()
    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
