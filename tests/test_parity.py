"""The CLI and the MCP tools return the same payload for each operation (#15)."""
import json
import os
import unittest
from unittest import mock

os.environ.setdefault("LIFEOS_OTEL_DISABLE_OTLP", "1")

from typer.testing import CliRunner  # noqa: E402

from garmin_mcp import cli, mcp_server  # noqa: E402

DAY = "2026-10-24"


def fake_api() -> mock.Mock:
    api = mock.Mock()
    api.get_user_summary.return_value = {
        "calendarDate": DAY, "totalSteps": 15615, "totalDistanceMeters": 12282,
        "activeKilocalories": 821.0, "bmrKilocalories": 1814.0, "totalKilocalories": 2635.0,
        "restingHeartRate": 53,
    }
    api.get_sleep_data.return_value = {"dailySleepDTO": {"calendarDate": DAY, "sleepTimeSeconds": 26520}}
    api.get_activities_by_date.return_value = [
        {"activityId": 42, "activityType": {"typeKey": "running"}, "duration": 1800, "distance": 5000}
    ]
    api.get_body_battery.return_value = []
    return api


class CliMcpParityTests(unittest.TestCase):
    CASES = {
        "day": (["day", "--date", DAY], lambda: mcp_server.garmin_get_day_overview(DAY)),
        "activities": (["activities", "--start-date", DAY, "--end-date", DAY],
                       lambda: mcp_server.garmin_list_activities(DAY, DAY)),
        "sleep-range": (["sleep-range", "--start-date", DAY, "--end-date", DAY],
                        lambda: mcp_server.garmin_get_sleep_range(DAY, DAY)),
        "calories": (["calories", "--start-date", DAY, "--end-date", DAY],
                     lambda: mcp_server.garmin_get_calories(DAY, DAY)),
    }

    def test_cli_and_mcp_payloads_are_identical(self):
        settings = type("S", (), {"max_range_days": 93})()
        for command, (argv, tool) in self.CASES.items():
            with self.subTest(command=command), \
                    mock.patch.object(cli, "load_settings", return_value=settings), \
                    mock.patch.object(cli, "login", return_value=fake_api()), \
                    mock.patch.object(mcp_server, "_get_api", return_value=(settings, fake_api())):
                out = CliRunner().invoke(cli.app, argv)
                self.assertEqual(0, out.exit_code, out.output)
                mcp_payload = tool()
                self.assertTrue(mcp_payload.pop("ok"))
                self.assertEqual(json.loads(out.output), mcp_payload)


if __name__ == "__main__":
    unittest.main()
