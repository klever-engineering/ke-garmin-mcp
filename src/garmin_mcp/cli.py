from __future__ import annotations

import json
from datetime import date
from typing import Any

import typer

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

app = typer.Typer(
    help="Garmin local connector (CLI + MCP support bootstrap)."
)


def _print_json(payload: Any) -> None:
    typer.echo(json.dumps(payload, indent=2, ensure_ascii=True))


@app.command("login")
def login_command(
    force_credentials: bool = typer.Option(
        False,
        "--force-credentials",
        help="Ignore existing token files and perform credential login.",
    )
) -> None:
    """Login and persist Garmin tokens to local token directory."""
    settings = load_settings()
    api = login(settings, force_credentials=force_credentials)
    _print_json(
        {
            "status": "ok",
            "display_name": api.display_name,
            "token_dir": str(settings.garmin_tokens_dir),
        }
    )


@app.command("day")
def day_command(
    target_date: str = typer.Option(
        date.today().isoformat(),
        "--date",
        help="Date in YYYY-MM-DD format.",
    ),
    raw: bool = typer.Option(
        False,
        "--raw",
        help="Return unfiltered Garmin payloads.",
    ),
) -> None:
    """Fetch sleep, workouts, and daily metrics for one date."""
    settings = load_settings()
    parsed_date = parse_date(target_date)

    api = login(settings, force_credentials=False)
    snapshot = fetch_day_snapshot(api, parsed_date)
    payload = {
        "calendar_date": snapshot.calendar_date,
        "summary": snapshot.summary,
        "sleep": snapshot.sleep,
        "activities": snapshot.activities,
    }
    if raw:
        _print_json(payload)
        return

    _print_json(
        {
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
    )


@app.command("today")
def today_command(
    raw: bool = typer.Option(
        False,
        "--raw",
        help="Return unfiltered Garmin payloads.",
    )
) -> None:
    """Shortcut for `day --date <today>`."""
    day_command(target_date=date.today().isoformat(), raw=raw)


@app.command("activities")
def activities_command(
    start_date: str = typer.Option(..., "--start-date", help="YYYY-MM-DD"),
    end_date: str = typer.Option(..., "--end-date", help="YYYY-MM-DD"),
    activity_type: str = typer.Option("", "--activity-type", help="Optional activity type key."),
) -> None:
    """List activities by date range."""
    settings = load_settings()
    start, end = validate_date_range(start_date, end_date, max_days=settings.max_range_days)
    api = login(settings, force_credentials=False)
    activities = fetch_activities_range(
        api, start, end, activity_type=activity_type.strip() or None
    )
    _print_json(
        {
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "count": len(activities),
            "activities": [compact_activity(activity) for activity in activities],
        }
    )


@app.command("sleep-range")
def sleep_range_command(
    start_date: str = typer.Option(..., "--start-date", help="YYYY-MM-DD"),
    end_date: str = typer.Option(..., "--end-date", help="YYYY-MM-DD"),
    include_empty: bool = typer.Option(
        False,
        "--include-empty",
        help="Include days without tracked sleep.",
    ),
) -> None:
    """Get sleep rows and summary for a date range."""
    settings = load_settings()
    start, end = validate_date_range(start_date, end_date, max_days=settings.max_range_days)
    api = login(settings, force_credentials=False)
    rows = fetch_sleep_range(api, start, end)

    output_rows = []
    for row in rows:
        has_sleep = isinstance(row.sleep_time_seconds, (int, float)) and row.sleep_time_seconds > 0
        if not include_empty and not has_sleep:
            continue
        output_rows.append(
            {
                "calendar_date": row.calendar_date,
                "sleep_time_seconds": row.sleep_time_seconds,
                "deep_sleep_seconds": row.deep_sleep_seconds,
                "light_sleep_seconds": row.light_sleep_seconds,
                "rem_sleep_seconds": row.rem_sleep_seconds,
                "awake_sleep_seconds": row.awake_sleep_seconds,
            }
        )

    _print_json(
        {
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "summary": summarize_sleep(rows),
            "rows": output_rows,
        }
    )


def main() -> None:
    try:
        app()
    except GarminAuthError as exc:
        typer.echo(f"Authentication error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except ValueError as exc:
        typer.echo(f"Validation error: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    except Exception as exc:
        typer.echo(f"Unexpected error: {exc}", err=True)
        raise typer.Exit(code=3) from exc


if __name__ == "__main__":
    main()

