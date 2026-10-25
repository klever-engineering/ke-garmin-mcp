"""OUT_01 retrieval contract tests for the agent-facing MCP tools.

Each tool is called through its public function with a mocked Garmin client.
The tests pin the response keys, the unit encoded in each key name, the
date attribution, and that values Garmin omits stay null instead of becoming 0.
"""
import os
import unittest
from unittest import mock

os.environ.setdefault("LIFEOS_OTEL_DISABLE_OTLP", "1")

from garminconnect import (  # noqa: E402
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

from garmin_mcp import mcp_server  # noqa: E402

DAY = "2026-10-24"

# Recorded shape of a worn day (values from 2026-10-24, trimmed).
WORN_SUMMARY = {
    "calendarDate": DAY,
    "totalSteps": 15615,
    "totalDistanceMeters": 12282,
    "activeKilocalories": 821.0,
    "bmrKilocalories": 1814.0,
    "totalKilocalories": 2635.0,
    "wellnessKilocalories": 2635.0,
    "restingHeartRate": 53,
}
WORN_SLEEP = {
    "dailySleepDTO": {
        "calendarDate": DAY,
        "sleepTimeSeconds": 26520,
        "deepSleepSeconds": 5400,
        "lightSleepSeconds": 15000,
        "remSleepSeconds": 6120,
        "awakeSleepSeconds": 600,
    }
}
RUN = {
    "activityId": 42,
    "activityName": "Morning run",
    "activityType": {"typeKey": "running"},
    "startTimeLocal": f"{DAY} 07:00:00",
    "duration": 1800.5,
    "distance": 5000.0,
    "averageHR": 148,
    "maxHR": 171,
    "hrTimeInZone_1": 60,
    "hrTimeInZone_2": 0,
}
YOGA = {"activityId": 43, "activityType": {"typeKey": "yoga"}, "duration": 3600}


class FakeSettings:
    max_range_days = 93


def call(tool, *args, api=None, **kwargs):
    api = api or mock.Mock()
    with mock.patch.object(mcp_server, "_get_api", return_value=(FakeSettings(), api)):
        return getattr(mcp_server, tool)(*args, **kwargs)


def worn_api() -> mock.Mock:
    api = mock.Mock()
    api.get_user_summary.return_value = dict(WORN_SUMMARY)
    api.get_sleep_data.return_value = WORN_SLEEP
    api.get_activities_by_date.return_value = [RUN, YOGA]
    return api


def empty_api() -> mock.Mock:
    """A date Garmin has no record for: every payload is empty."""
    api = mock.Mock()
    api.get_user_summary.return_value = {}
    api.get_sleep_data.return_value = {}
    api.get_activities_by_date.return_value = []
    return api


class DayOverviewContractTests(unittest.TestCase):
    def test_maps_every_out_01_field_with_unit_in_key_and_date(self):
        result = call("garmin_get_day_overview", DAY, api=worn_api())

        self.assertTrue(result["ok"])
        self.assertEqual(DAY, result["calendar_date"])
        self.assertEqual(
            {"steps": 15615, "distance_meters": 12282, "active_kilocalories": 821.0, "resting_heart_rate": 53},
            result["daily_summary"],
        )
        self.assertEqual(2635, result["calories"]["total_kilocalories"])
        self.assertEqual(1814, result["calories"]["bmr_kilocalories"])
        self.assertEqual(DAY, result["sleep"]["calendar_date"])
        self.assertEqual(26520, result["sleep"]["sleep_time_seconds"])
        for stage in ("deep", "light", "rem", "awake"):
            self.assertIn(f"{stage}_sleep_seconds", result["sleep"])
        self.assertEqual(2, len(result["workouts"]))

    def test_date_without_garmin_record_returns_nulls_not_zeros(self):
        result = call("garmin_get_day_overview", DAY, api=empty_api())

        self.assertTrue(result["ok"])
        self.assertEqual(DAY, result["calendar_date"])
        self.assertTrue(all(v is None for v in result["daily_summary"].values()), result["daily_summary"])
        calories = {k: v for k, v in result["calories"].items() if k != "calendar_date"}
        self.assertTrue(all(v is None for v in calories.values()), calories)
        sleep = {k: v for k, v in result["sleep"].items() if k != "calendar_date"}
        self.assertTrue(all(v is None for v in sleep.values()), sleep)
        self.assertEqual([], result["workouts"])

    def test_requests_the_same_calendar_date_from_every_endpoint(self):
        api = worn_api()
        call("garmin_get_day_overview", DAY, api=api)

        api.get_user_summary.assert_called_once_with(DAY)
        api.get_sleep_data.assert_called_once_with(DAY)
        api.get_activities_by_date.assert_called_once_with(DAY, DAY)


class ActivitiesContractTests(unittest.TestCase):
    def test_workout_fields_and_units(self):
        result = call("garmin_list_activities", DAY, DAY, api=worn_api())

        self.assertTrue(result["ok"])
        self.assertEqual((DAY, DAY, 2), (result["start_date"], result["end_date"], result["count"]))
        run = result["activities"][0]
        self.assertEqual(42, run["activity_id"])
        self.assertEqual("running", run["type"])
        self.assertEqual(f"{DAY} 07:00:00", run["start_time_local"])
        self.assertEqual(1800.5, run["duration_seconds"])
        self.assertEqual(5000.0, run["distance_meters"])
        self.assertEqual((148, 171), (run["average_heart_rate"], run["max_heart_rate"]))

    def test_missing_workout_fields_stay_null_and_observed_zero_stays_zero(self):
        result = call("garmin_list_activities", DAY, DAY, api=worn_api())
        run, yoga = result["activities"]

        self.assertEqual(0, run["heart_rate_zone_2_seconds"])
        self.assertIsNone(run["heart_rate_zone_3_seconds"])
        self.assertIsNone(yoga["distance_meters"])
        self.assertIsNone(yoga["average_heart_rate"])

    def test_activity_type_filter_is_case_insensitive(self):
        result = call("garmin_list_activities", DAY, DAY, "YOGA", api=worn_api())

        self.assertEqual(1, result["count"])
        self.assertEqual("yoga", result["activities"][0]["type"])


class SleepRangeContractTests(unittest.TestCase):
    def test_rows_are_dated_and_keep_stage_seconds(self):
        result = call("garmin_get_sleep_range", DAY, DAY, api=worn_api())

        self.assertTrue(result["ok"])
        row = result["rows"][0]
        self.assertEqual(DAY, row["calendar_date"])
        self.assertEqual(
            (26520, 5400, 15000, 6120, 600),
            (row["sleep_time_seconds"], row["deep_sleep_seconds"], row["light_sleep_seconds"],
             row["rem_sleep_seconds"], row["awake_sleep_seconds"]),
        )
        self.assertEqual(1, result["summary"]["tracked_nights"])

    def test_night_without_record_is_dropped_by_default_and_null_when_included(self):
        dropped = call("garmin_get_sleep_range", DAY, DAY, api=empty_api())
        included = call("garmin_get_sleep_range", DAY, DAY, include_empty=True, api=empty_api())

        self.assertEqual([], dropped["rows"])
        self.assertEqual(0, dropped["summary"]["tracked_nights"])
        self.assertIsNone(dropped["summary"]["average_sleep_seconds"])
        self.assertEqual(DAY, included["rows"][0]["calendar_date"])
        self.assertIsNone(included["rows"][0]["sleep_time_seconds"])


class CaloriesContractTests(unittest.TestCase):
    def test_rows_are_integer_kilocalories_with_date(self):
        result = call("garmin_get_calories", DAY, DAY, api=worn_api())

        row = result["rows"][0]
        self.assertEqual(DAY, row["calendar_date"])
        self.assertEqual((2635, 821, 1814), (row["total_kilocalories"], row["active_kilocalories"],
                                             row["bmr_kilocalories"]))
        self.assertIsInstance(row["total_kilocalories"], int)
        self.assertIsNone(row["consumed_kilocalories"])

    def test_non_numeric_values_become_null(self):
        api = worn_api()
        api.get_user_summary.return_value = {**WORN_SUMMARY, "activeKilocalories": True, "totalKilocalories": "n/a"}
        row = call("garmin_get_calories", DAY, DAY, include_empty=True, api=api)["rows"][0]

        self.assertIsNone(row["active_kilocalories"])
        self.assertIsNone(row["total_kilocalories"])

    def test_day_without_record_is_null_when_included(self):
        result = call("garmin_get_calories", DAY, DAY, include_empty=True, api=empty_api())

        self.assertIsNone(result["rows"][0]["total_kilocalories"])
        self.assertEqual(0, result["summary"]["tracked_days"])
        self.assertIsNone(result["summary"]["average_total_kilocalories"])


NO_WEAR_DAY = "2026-08-19"
# Recorded raw summary for a real no-wear day (2026-08-19, trimmed).
NO_WEAR_SUMMARY = {
    "calendarDate": NO_WEAR_DAY,
    "totalSteps": None,
    "totalDistanceMeters": 0,
    "activeKilocalories": 0.0,
    "bmrKilocalories": 2047.0,
    "totalKilocalories": 2047.0,
    "wellnessKilocalories": 2047.0,
    "restingHeartRate": None,
    "averageStressLevel": -1,
    "sedentarySeconds": 86400,
    "highlyActiveSeconds": 0,
}


def no_wear_api() -> mock.Mock:
    api = empty_api()
    api.get_user_summary.return_value = dict(NO_WEAR_SUMMARY)
    api.get_body_battery.return_value = []
    return api


class NoWearDayContractTests(unittest.TestCase):
    def test_day_overview_flags_no_wear_and_nulls_filler_zeros(self):
        result = call("garmin_get_day_overview", NO_WEAR_DAY, api=no_wear_api())

        self.assertIs(False, result["wear_data"])
        self.assertIsNone(result["daily_summary"]["steps"])
        self.assertIsNone(result["daily_summary"]["distance_meters"])
        self.assertIsNone(result["daily_summary"]["active_kilocalories"])
        self.assertIsNone(result["calories"]["active_kilocalories"])
        self.assertEqual(2047, result["calories"]["total_kilocalories"])
        self.assertEqual("bmr_only", result["calories"]["estimate"])

    def test_worn_day_and_day_without_record_are_distinguished(self):
        worn = call("garmin_get_day_overview", DAY, api=worn_api())
        no_record = call("garmin_get_day_overview", DAY, api=empty_api())

        self.assertIs(True, worn["wear_data"])
        self.assertIsNone(worn["calories"]["estimate"])
        self.assertIsNone(no_record["wear_data"])

    def test_low_but_recorded_day_is_still_worn(self):
        api = worn_api()
        api.get_user_summary.return_value = {**NO_WEAR_SUMMARY, "totalSteps": 27, "totalDistanceMeters": 22}
        result = call("garmin_get_day_overview", NO_WEAR_DAY, api=api)

        self.assertIs(True, result["wear_data"])
        self.assertEqual(22, result["daily_summary"]["distance_meters"])

    def test_calories_exclude_no_wear_days_from_tracking(self):
        dropped = call("garmin_get_calories", NO_WEAR_DAY, NO_WEAR_DAY, api=no_wear_api())
        included = call("garmin_get_calories", NO_WEAR_DAY, NO_WEAR_DAY, include_empty=True, api=no_wear_api())

        self.assertEqual([], dropped["rows"])
        self.assertEqual(0, dropped["summary"]["tracked_days"])
        self.assertIsNone(dropped["summary"]["average_total_kilocalories"])
        row = included["rows"][0]
        self.assertEqual((False, "bmr_only", None, 2047),
                         (row["wear_data"], row["estimate"], row["active_kilocalories"], row["total_kilocalories"]))

    def test_health_history_rows_carry_wear_flag(self):
        result = call("garmin_get_health_history", NO_WEAR_DAY, NO_WEAR_DAY, api=no_wear_api())

        self.assertIs(False, result["rows"][0]["wear_data"])
        self.assertIsNone(result["rows"][0]["resting_heart_rate"])


class SourceAttributionContractTests(unittest.TestCase):
    CALLS = {
        "garmin_get_day_overview": ((DAY,), ["get_user_summary", "get_sleep_data", "get_activities_by_date"]),
        "garmin_list_activities": ((DAY, DAY), ["get_activities_by_date"]),
        "garmin_get_sleep_range": ((DAY, DAY), ["get_sleep_data"]),
        "garmin_get_calories": ((DAY, DAY), ["get_user_summary"]),
        "garmin_get_health_history": ((DAY, DAY), ["get_body_battery", "get_user_summary"]),
    }

    def test_every_tool_names_provider_endpoints_time_and_date(self):
        for tool, (args, endpoints) in self.CALLS.items():
            api = worn_api()
            api.get_body_battery.return_value = []
            result = call(tool, *args, api=api)
            with self.subTest(tool=tool):
                src = result["source"]
                self.assertEqual("garmin_connect", src["provider"])
                self.assertTrue(src["client"].startswith("garminconnect"))
                self.assertTrue(src["server"].startswith("garmin-mcp"))
                self.assertEqual(endpoints, src["endpoints"])
                self.assertRegex(src["retrieved_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$")
                self.assertEqual("garmin_calendar_date_local", src["date_basis"])
                self.assertTrue(result.get("calendar_date") or (result.get("start_date") and result.get("end_date")))

    def test_calorie_totals_are_null_when_no_day_is_tracked(self):
        summary = call("garmin_get_calories", DAY, DAY, api=empty_api())["summary"]

        self.assertEqual(0, summary["tracked_days"])
        self.assertIsNone(summary["total_active_kilocalories"])
        self.assertIsNone(summary["total_burned_kilocalories"])


class ErrorEnvelopeContractTests(unittest.TestCase):
    RANGE_TOOLS = ("garmin_list_activities", "garmin_get_sleep_range", "garmin_get_calories",
                   "garmin_get_health_history")

    def test_garmin_failures_map_to_named_error_codes(self):
        cases = {
            GarminConnectAuthenticationError("bad token"): "authentication_error",
            GarminConnectTooManyRequestsError("429"): "rate_limited",
            GarminConnectConnectionError("down"): "connection_error",
            RuntimeError("boom"): "unexpected_error",
        }
        for exc, code in cases.items():
            api = mock.Mock()
            api.get_user_summary.side_effect = exc
            result = call("garmin_get_day_overview", DAY, api=api)
            self.assertEqual((False, code), (result["ok"], result["error"]), code)

    def test_invalid_dates_are_validation_errors_for_every_tool(self):
        self.assertEqual("validation_error", call("garmin_get_day_overview", "24-10-2026")["error"])
        for tool in self.RANGE_TOOLS:
            self.assertEqual("validation_error", call(tool, "2026-10-24", "2026-10-01")["error"], tool)
            self.assertEqual("validation_error", call(tool, "2026-01-01", "2026-12-31")["error"], tool)


if __name__ == "__main__":
    unittest.main()
