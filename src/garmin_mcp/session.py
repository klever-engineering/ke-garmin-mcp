"""One authenticated Garmin client per process, with bounded retries.

A token login costs two extra Garmin requests (profile and user settings), so
the long-running MCP service logs in once and reuses the client. The MCP server
logs in again only when Garmin rejects the session (mcp_server._with_garmin).
Data requests are retried with exponential backoff on rate limits and
connection errors. See README "Request budget".
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from garminconnect import (
    Garmin,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

from .client import login
from .config import Settings, load_settings

logger = logging.getLogger(__name__)

RETRY_ATTEMPTS = 3  # total tries per Garmin data request
RETRY_BASE_DELAY_SECONDS = 2.0  # waits 2s, then 4s
RETRYABLE_ERRORS = (GarminConnectTooManyRequestsError, GarminConnectConnectionError)


class RetryingGarmin:
    """Proxy for a Garmin client that retries `get_*` data requests."""

    def __init__(
        self,
        api: Garmin,
        *,
        attempts: int = RETRY_ATTEMPTS,
        base_delay: float = RETRY_BASE_DELAY_SECONDS,
    ) -> None:
        self._api = api
        self._attempts = max(1, attempts)
        self._base_delay = base_delay

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._api, name)
        if not name.startswith("get_") or not callable(attr):
            return attr

        def call(*args: Any, **kwargs: Any) -> Any:
            for attempt in range(1, self._attempts + 1):
                try:
                    return attr(*args, **kwargs)
                except RETRYABLE_ERRORS as exc:
                    if attempt == self._attempts:
                        raise
                    delay = self._base_delay * 2 ** (attempt - 1)
                    logger.warning(
                        "Garmin %s failed (%s); retry %d of %d in %.0fs",
                        name, type(exc).__name__, attempt, self._attempts - 1, delay,
                    )
                    time.sleep(delay)
            raise AssertionError("unreachable")

        return call


class GarminSession:
    """Lazily logs in once and shares the client across tool calls."""

    def __init__(
        self,
        settings_loader: Callable[[], Settings] = load_settings,
        login_fn: Callable[[Settings], Garmin] = login,
    ) -> None:
        self._settings_loader = settings_loader
        self._login_fn = login_fn
        self._lock = threading.Lock()
        self._settings: Settings | None = None
        self._api: RetryingGarmin | None = None

    def get(self) -> tuple[Settings, RetryingGarmin]:
        with self._lock:
            if self._api is None or self._settings is None:
                settings = self._settings_loader()
                self._api = RetryingGarmin(self._login_fn(settings))
                self._settings = settings
            return self._settings, self._api

    def reset(self) -> None:
        with self._lock:
            self._api = None
