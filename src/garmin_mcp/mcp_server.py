from __future__ import annotations

import argparse
import logging
import os
from contextlib import nullcontext
from importlib import metadata
from datetime import date
from typing import Any

from garminconnect import (
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)
from mcp.server.mcpserver import MCPServer

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)

from . import access, contract
from .config import load_runtime_env
from .client import GarminAuthError, parse_date, validate_date_range
from .session import GarminSession

logger = logging.getLogger("garmin_mcp.mcp_server")  # also when run as __main__

def _package_version() -> str:
    try:
        return metadata.version("garmin-mcp")
    except metadata.PackageNotFoundError:
        return ""


mcp = MCPServer(
    name="lifeos.garmin-mcp",
    version=_package_version(),
    log_level="WARNING",
    instructions=(
        "Query Garmin Connect data for sleep, workouts, and daily metrics. "
        "Use YYYY-MM-DD dates."
    ),
)


def _init_tracing(service_name: str):
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") or os.getenv(
        "OTEL_EXPORTER_OTLP_ENDPOINT"
    )
    if endpoint and not endpoint.endswith("/v1/traces"):
        endpoint = endpoint.rstrip("/") + "/v1/traces"

    try:
        current_provider = trace.get_tracer_provider()
        if isinstance(current_provider, TracerProvider):
            return trace.get_tracer(service_name)

        resource = Resource.create(
            {
                "service.name": service_name,
                "service.namespace": "life.workspace",
                "deployment.environment": os.getenv("LIFEOS_ENV", "local"),
            }
        )
        provider = TracerProvider(resource=resource)
        if os.getenv("LIFEOS_OTEL_DISABLE_OTLP", "0") != "1":
            exporter = OTLPSpanExporter(endpoint=endpoint) if endpoint else OTLPSpanExporter()
            provider.add_span_processor(BatchSpanProcessor(exporter))
        if os.getenv("LIFEOS_OTEL_CONSOLE", "0") == "1":
            provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
        trace.set_tracer_provider(provider)
        return trace.get_tracer(service_name)
    except Exception:
        return None


_TRACER = _init_tracing("lifeos.garmin-mcp")


def _span(name: str):
    if _TRACER is None:
        return nullcontext()
    return _TRACER.start_as_current_span(name)


def _set_span_attrs(**attrs: Any) -> None:
    span = trace.get_current_span()
    if not span or not span.is_recording():
        return
    for key, value in attrs.items():
        if value is None:
            continue
        if isinstance(value, bool | int | float | str):
            span.set_attribute(key, value)
        else:
            span.set_attribute(key, str(value))


def tracing_probe() -> dict[str, Any]:
    """Emit a safe local span without external API calls."""
    with _span("garmin_tracing_probe"):
        _set_span_attrs(operation="tracing_probe", module="garmin_mcp")
        return {"ok": True, "module": "garmin_mcp"}


# One Garmin login per process; see session.py and README "Request budget".
_SESSION = GarminSession()


def _get_api():
    return _SESSION.get()


def _with_garmin(operation):
    """Run operation(settings, api); log in again once if Garmin rejects the session."""
    settings, api = _get_api()
    try:
        return operation(settings, api)
    except GarminConnectAuthenticationError:
        _SESSION.reset()
        settings, api = _get_api()
        return operation(settings, api)


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
    description=(
        "Get sleep, workouts, and daily summary for one date (YYYY-MM-DD). "
        "Omit target_date for the server's current local date."
    ),
)
def garmin_get_day_overview(target_date: str = "") -> dict[str, Any]:
    # Resolve "today" per call: the HTTP service runs for days, so a default
    # computed at import time would keep returning the service start date.
    target_date = target_date.strip() or date.today().isoformat()
    with _span("garmin_get_day_overview"):
        try:
            _set_span_attrs(
                operation="garmin_get_day_overview",
                target_date=target_date,
            )

            def run(settings, api):
                return {"ok": True, **contract.day_overview(api, parse_date(target_date))}

            return _with_garmin(run)
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
    with _span("garmin_list_activities"):
        try:
            _set_span_attrs(
                operation="garmin_list_activities",
                start_date=start_date,
                end_date=end_date,
                activity_type=activity_type,
            )

            def run(settings, api):
                start, end = validate_date_range(start_date, end_date, max_days=settings.max_range_days)
                return {"ok": True, **contract.activities(api, start, end, activity_type)}

            return _with_garmin(run)
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
    with _span("garmin_get_sleep_range"):
        try:
            _set_span_attrs(
                operation="garmin_get_sleep_range",
                start_date=start_date,
                end_date=end_date,
                include_empty=include_empty,
            )

            def run(settings, api):
                start, end = validate_date_range(start_date, end_date, max_days=settings.max_range_days)
                return {"ok": True, **contract.sleep_range(api, start, end, include_empty)}

            return _with_garmin(run)
        except Exception as exc:
            return _handle_known_errors(exc)


@mcp.tool(
    name="garmin_get_health_history",
    description=(
        "Get daily resting heart rate and Body Battery charged/drained values over a date range, "
        "plus coverage and first-week versus last-week averages."
    ),
)
def garmin_get_health_history(start_date: str, end_date: str) -> dict[str, Any]:
    """Read Garmin daily resting heart rate and Body Battery history (max 93 days)."""
    with _span("garmin_get_health_history"):
        try:
            _set_span_attrs(operation="garmin_get_health_history", start_date=start_date, end_date=end_date)

            def run(settings, api):
                start, end = validate_date_range(start_date, end_date, max_days=settings.max_range_days)
                return {"ok": True, **contract.health_history(api, start, end)}

            return _with_garmin(run)
        except Exception as exc:
            return _handle_known_errors(exc)


@mcp.tool(
    name="garmin_get_calories",
    description=(
        "Get daily calories burned (active, BMR, total) and consumed/remaining "
        "for a date range, with aggregate totals and averages."
    ),
)
def garmin_get_calories(
    start_date: str,
    end_date: str,
    include_empty: bool = False,
) -> dict[str, Any]:
    with _span("garmin_get_calories"):
        try:
            _set_span_attrs(
                operation="garmin_get_calories",
                start_date=start_date,
                end_date=end_date,
                include_empty=include_empty,
            )

            def run(settings, api):
                start, end = validate_date_range(start_date, end_date, max_days=settings.max_range_days)
                return {"ok": True, **contract.calories(api, start, end, include_empty)}

            return _with_garmin(run)
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


def http_bind() -> tuple[str, int]:
    """HTTP bind address. GARMIN_MCP_HOST/PORT; FASTMCP_* accepted for older setups."""
    host = os.getenv("GARMIN_MCP_HOST") or os.getenv("FASTMCP_HOST") or "127.0.0.1"
    port = int(os.getenv("GARMIN_MCP_PORT") or os.getenv("FASTMCP_PORT") or "8000")
    return host, port


def build_http_app(transport: str = "streamable-http", host: str = "127.0.0.1",
                   policy: access.AccessPolicy | None = None):
    """The ASGI app served over HTTP (streamable HTTP at /mcp, or SSE).

    With client tokens configured, requests go through the bearer-token check
    (ADR 0007).
    """
    app = mcp.sse_app(host=host) if transport == "sse" else mcp.streamable_http_app(host=host)
    if policy is None or policy.mode == "off":
        return app
    return access.ClientAuthMiddleware(app, policy)


def _plain_logging() -> None:
    """One line per record for this package, so journal lines stay greppable."""
    package = logging.getLogger("garmin_mcp")
    if not any(getattr(h, "_garmin_plain", False) for h in package.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
        handler._garmin_plain = True
        package.addHandler(handler)
        package.propagate = False


def run_http(transport: str) -> None:
    import uvicorn

    _plain_logging()
    load_runtime_env()
    host, port = http_bind()
    policy = access.load_policy()
    access.check_bind(host, policy)
    if policy.mode == "off":
        logger.warning("HTTP client tokens are not set (GARMIN_MCP_CLIENT_TOKENS); any local process can call the server")
    else:
        logger.warning("HTTP client tokens %s for: %s", "enforced" if policy.mode == "enforce" else "observed only",
                       ", ".join(sorted(policy.tokens)))
    uvicorn.run(build_http_app(transport, host, policy), host=host, port=port, log_level="warning")


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()
    with _span("garmin_mcp_server_run"):
        if args.transport == "stdio":
            mcp.run(transport="stdio")
        else:
            run_http(args.transport)


if __name__ == "__main__":
    main()
