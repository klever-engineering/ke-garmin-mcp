import unittest

from garmin_mcp.client import compact_activity


class CompactActivityTests(unittest.TestCase):
    def test_preserves_zone_seconds_and_missing_is_not_zero(self):
        result = compact_activity({"activityId": 1, "hrTimeInZone_3": 60, "hrTimeInZone_4": 0})
        self.assertEqual(60, result["heart_rate_zone_3_seconds"])
        self.assertEqual(0, result["heart_rate_zone_4_seconds"])
        self.assertIsNone(result["heart_rate_zone_5_seconds"])


if __name__ == "__main__":
    unittest.main()
