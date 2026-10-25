import os
import unittest
from datetime import date
from unittest.mock import Mock

os.environ.setdefault("LIFEOS_OTEL_DISABLE_OTLP", "1")

from garmin_mcp import mcp_server
from garmin_mcp.client import compact_activity, fetch_health_range, summarize_health_history


class HealthHistoryTests(unittest.TestCase):
    def test_fetch_joins_daily_summary_and_body_battery_without_filling_missing(self):
        api = Mock()
        api.get_body_battery.return_value = [
            {"date": "2026-10-01", "charged": 40, "drained": 55,
             "bodyBatteryValuesArray": [[1, 20], [2, 70]]}
        ]
        api.get_user_summary.side_effect = [
            {"restingHeartRate": 52}, {"restingHeartRate": None}
        ]
        rows = fetch_health_range(api, date(2026, 10, 1), date(2026, 10, 2))
        self.assertEqual(52, rows[0]["resting_heart_rate"])
        self.assertEqual(20, rows[0]["body_battery_start"])
        self.assertEqual(70, rows[0]["body_battery_end"])
        self.assertIsNone(rows[1]["body_battery_charged"])
        self.assertEqual(2, api.get_user_summary.call_count)
        api.get_body_battery.assert_called_once_with("2026-10-01", "2026-10-02")

    def test_summary_reports_coverage_and_week_over_week_changes(self):
        rows = [
            {"resting_heart_rate": 50, "body_battery_charged": 40, "body_battery_drained": 60}
            for _ in range(7)
        ] + [
            {"resting_heart_rate": 54, "body_battery_charged": 30, "body_battery_drained": 65}
            for _ in range(7)
        ]
        summary = summarize_health_history(rows)
        self.assertEqual(14, summary["resting_heart_rate_days"])
        self.assertEqual(52, summary["resting_heart_rate_median_bpm"])
        self.assertEqual(4, summary["resting_heart_rate_weekly_change_bpm"])
        self.assertEqual(-10, summary["body_battery_weekly_charged_change"])
        self.assertEqual(14, summary["body_battery_net_negative_days"])
        self.assertEqual(7, summary["resting_heart_rate_first_week_days"])

    def test_empty_health_history_has_null_aggregates(self):
        summary = summarize_health_history([])
        self.assertEqual(0, summary["calendar_days"])
        self.assertIsNone(summary["resting_heart_rate_average_bpm"])
        self.assertNotIn("resting_heart_rate_weekly_change_bpm", summary)


class HealthHistoryToolTests(unittest.TestCase):
    def test_tool_returns_range_rows_and_summary(self):
        rows = [
            {"calendar_date": "2026-10-01", "resting_heart_rate": 58,
             "body_battery_charged": 40, "body_battery_drained": 50,
             "body_battery_start": 20, "body_battery_end": 10}
        ]
        with unittest.mock.patch.object(mcp_server, "_get_api", return_value=(
            type("Settings", (), {"max_range_days": 93})(), object()
        )), unittest.mock.patch.object(mcp_server, "fetch_health_range", return_value=rows):
            result = mcp_server.garmin_get_health_history("2026-10-01", "2026-10-01")
        self.assertTrue(result["ok"])
        self.assertEqual(rows, result["rows"])
        self.assertEqual(58, result["summary"]["resting_heart_rate_average_bpm"])

    def test_tool_rejects_range_exceeding_configured_limit(self):
        with unittest.mock.patch.object(mcp_server, "_get_api", return_value=(
            type("Settings", (), {"max_range_days": 1})(), object()
        )):
            result = mcp_server.garmin_get_health_history("2026-10-01", "2026-10-02")
        self.assertFalse(result["ok"])
        self.assertEqual("validation_error", result["error"])


class CompactActivityTests(unittest.TestCase):
    def test_preserves_zone_seconds_and_missing_is_not_zero(self):
        result = compact_activity({"activityId": 1, "hrTimeInZone_3": 60, "hrTimeInZone_4": 0})
        self.assertEqual(60, result["heart_rate_zone_3_seconds"])
        self.assertEqual(0, result["heart_rate_zone_4_seconds"])
        self.assertIsNone(result["heart_rate_zone_5_seconds"])


if __name__ == "__main__":
    unittest.main()
