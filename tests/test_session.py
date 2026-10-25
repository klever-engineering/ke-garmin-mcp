"""Session reuse, retry/backoff, and login fallback rules (issue #11)."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("LIFEOS_OTEL_DISABLE_OTLP", "1")

import requests  # noqa: E402
from garminconnect import (  # noqa: E402
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

from garmin_mcp import client, mcp_server, session  # noqa: E402
from garmin_mcp.config import Settings  # noqa: E402


def settings() -> Settings:
    return Settings("user@example.invalid", "secret", Path(tempfile.mkdtemp()), 93)


class GarminSessionTests(unittest.TestCase):
    def test_logs_in_once_and_reuses_the_client(self):
        login = mock.Mock(return_value=mock.Mock())
        garmin = session.GarminSession(settings_loader=settings, login_fn=login)

        first = garmin.get()[1]
        second = garmin.get()[1]

        self.assertIs(first, second)
        self.assertEqual(1, login.call_count)

    def test_reset_forces_a_new_login(self):
        login = mock.Mock(return_value=mock.Mock())
        garmin = session.GarminSession(settings_loader=settings, login_fn=login)
        garmin.get()
        garmin.reset()
        garmin.get()

        self.assertEqual(2, login.call_count)


class WithGarminTests(unittest.TestCase):
    def test_relogs_in_once_when_garmin_rejects_the_session(self):
        login = mock.Mock(return_value=mock.Mock())
        calls = []

        def operation(_settings, _api):
            calls.append(1)
            if len(calls) == 1:
                raise GarminConnectAuthenticationError("401")
            return "ok"

        with mock.patch.object(mcp_server, "_SESSION", session.GarminSession(settings, login)):
            self.assertEqual("ok", mcp_server._with_garmin(operation))
        self.assertEqual(2, login.call_count)
        self.assertEqual(2, len(calls))

    def test_second_rejection_is_reported_not_retried_forever(self):
        login = mock.Mock(return_value=mock.Mock())

        def operation(_settings, _api):
            raise GarminConnectAuthenticationError("401")

        with mock.patch.object(mcp_server, "_SESSION", session.GarminSession(settings, login)):
            with self.assertRaises(GarminConnectAuthenticationError):
                mcp_server._with_garmin(operation)
        self.assertEqual(2, login.call_count)


@mock.patch.object(session.time, "sleep")
class RetryingGarminTests(unittest.TestCase):
    def test_retries_rate_limit_with_backoff_then_succeeds(self, sleep):
        api = mock.Mock()
        api.get_user_summary.side_effect = [GarminConnectTooManyRequestsError("429"), {"totalSteps": 1}]

        result = session.RetryingGarmin(api).get_user_summary("2026-10-24")

        self.assertEqual({"totalSteps": 1}, result)
        sleep.assert_called_once_with(2.0)

    def test_gives_up_after_three_attempts(self, sleep):
        api = mock.Mock()
        api.get_sleep_data.side_effect = GarminConnectConnectionError("down")

        with self.assertRaises(GarminConnectConnectionError):
            session.RetryingGarmin(api).get_sleep_data("2026-10-24")
        self.assertEqual(3, api.get_sleep_data.call_count)
        self.assertEqual([mock.call(2.0), mock.call(4.0)], sleep.call_args_list)

    def test_does_not_retry_other_errors_or_wrap_non_data_attributes(self, sleep):
        api = mock.Mock()
        api.get_user_summary.side_effect = GarminConnectAuthenticationError("401")
        proxy = session.RetryingGarmin(api)

        with self.assertRaises(GarminConnectAuthenticationError):
            proxy.get_user_summary("2026-10-24")
        self.assertEqual(1, api.get_user_summary.call_count)
        self.assertIs(api.garth, proxy.garth)
        sleep.assert_not_called()

    def test_tool_survives_one_rate_limit(self, sleep):
        api = mock.Mock()
        api.get_user_summary.side_effect = [GarminConnectTooManyRequestsError("429"), {}]
        api.get_sleep_data.return_value = {}
        api.get_activities_by_date.return_value = []
        fake = (type("S", (), {"max_range_days": 93})(), session.RetryingGarmin(api))

        with mock.patch.object(mcp_server, "_get_api", return_value=fake):
            result = mcp_server.garmin_get_day_overview("2026-10-24")

        self.assertTrue(result["ok"])


class LoginFallbackTests(unittest.TestCase):
    def _login(self, token_error):
        instance = mock.Mock()
        instance.login.side_effect = lambda tokenstore=None: (_ for _ in ()).throw(token_error) if tokenstore else None
        with mock.patch.object(client, "Garmin", return_value=instance):
            try:
                client.login(settings())
                return instance, None
            except Exception as exc:  # noqa: BLE001
                return instance, exc

    def credential_logins(self, instance) -> int:
        return sum(1 for c in instance.login.call_args_list if not c.kwargs.get("tokenstore"))

    def test_missing_tokens_use_credentials(self):
        instance, exc = self._login(FileNotFoundError("oauth1_token.json"))
        self.assertIsNone(exc)
        self.assertEqual(1, self.credential_logins(instance))

    def test_rejected_tokens_use_credentials(self):
        instance, exc = self._login(GarminConnectAuthenticationError("401 Unauthorized"))
        self.assertIsNone(exc)
        self.assertEqual(1, self.credential_logins(instance))

    def test_corrupt_token_file_uses_credentials(self):
        try:
            try:
                json.loads("{")
            except json.JSONDecodeError as inner:
                raise GarminConnectConnectionError("Login failed") from inner
        except GarminConnectConnectionError as wrapped:
            instance, exc = self._login(wrapped)
        self.assertIsNone(exc)
        self.assertEqual(1, self.credential_logins(instance))

    def test_connection_error_is_raised_without_password_login(self):
        instance, exc = self._login(GarminConnectConnectionError("network down"))
        self.assertIsInstance(exc, GarminConnectConnectionError)
        self.assertEqual(0, self.credential_logins(instance))

    def test_rate_limit_is_raised_without_password_login(self):
        instance, exc = self._login(GarminConnectTooManyRequestsError("429"))
        self.assertIsInstance(exc, GarminConnectTooManyRequestsError)
        self.assertEqual(0, self.credential_logins(instance))

    def test_auth_error_caused_by_network_is_raised_without_password_login(self):
        try:
            try:
                raise requests.exceptions.ConnectionError("DNS failure")
            except requests.exceptions.ConnectionError as inner:
                raise GarminConnectAuthenticationError("Failed to retrieve profile") from inner
        except GarminConnectAuthenticationError as wrapped:
            instance, exc = self._login(wrapped)
        self.assertIsInstance(exc, GarminConnectAuthenticationError)
        self.assertEqual(0, self.credential_logins(instance))


if __name__ == "__main__":
    unittest.main()
