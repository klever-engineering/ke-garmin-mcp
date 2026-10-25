#!/usr/bin/env python3
"""Observe whether this Track's LifeOS expected outputs are accomplished.

Each LifeOS expected output for the Garmin MCP Track (GitHub issues #6-#18) has
a done-when criterion. This script checks every criterion directly against the
repository, the test suites, GitHub CI, the running service, and behavior
probes against a fake Garmin client, so an agent or the owner can see the
status without asking anyone.

Usage (stdlib only; behavior probes run in the repo's .venv):
    python3 scripts/verify_expected_outputs.py            # all outputs
    python3 scripts/verify_expected_outputs.py --only 7,8 # selected issues
    python3 scripts/verify_expected_outputs.py --offline  # skip live service/network checks
    python3 scripts/verify_expected_outputs.py --json     # machine-readable
    python3 scripts/verify_expected_outputs.py --save     # also write .state/expected-outputs/<ts>.json

Status per check: PASS, FAIL, or SKIP (could not be observed, e.g. service down
or --offline). An output is ACCOMPLISHED only when every check passes.
Exit code: 0 if every selected output is accomplished, 1 otherwise.

The script only observes. It never edits LifeOS records: verifying outputs and
confirming claims stays with the owner.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parents[2]
LDR_DIR = Path(os.getenv("LDR_DIR", ROOT.parent.parent / "tools" / "life-daily-report"))
VENV_PYTHON = ROOT / ".venv" / "bin" / "python"
SERVER_URL = os.getenv("GARMIN_MCP_URL", "http://127.0.0.1:8000/mcp")
LIFEOS_URL = os.getenv("LIFEOS_URL", "http://127.0.0.1:8765")
TRACK_ID = "LD02_TRK_GARMIN_MCP_SERVER"
REPO = "klever-engineering/ke-garmin-mcp"
SERVICE = "lifeos-garmin-mcp.service"
OUT_01_TOOLS = (
    "garmin_get_day_overview",
    "garmin_list_activities",
    "garmin_get_sleep_range",
    "garmin_get_calories",
)

# LifeOS expected-output ids, keyed by GitHub issue number.
OUTPUT_IDS = {
    6: "5c2f891b-1f09-47e5-92a0-b4075dea611a",
    7: "3bab8c91-b789-4ef8-82c5-bb78b666225c",
    8: "ffffaebf-f96d-4bdc-9021-b5734407eae9",
    9: "cc2d7a26-ae62-4bd0-9538-2a707b357861",
    10: "1b84cf11-d349-4c8f-94ab-e0ab1bc8daa0",
    11: "34de3a5d-1b07-41b7-be80-7bf07e3693a4",
    12: "973a2056-1994-4794-bf40-9f2b49c8ae28",
    13: "54f31803-e0ec-4ef3-b27f-c87d719bb27c",
    14: "1f0c7c26-f0f6-4d51-9ba2-3ebf3d60c9b3",
    15: "bd27d0a7-ec50-4f59-b9df-903b730613ea",
    16: "0f678da0-b8da-43b5-9a13-c99afa373a71",
    17: "246b0c50-3332-46a9-9602-bf0c88d425ca",
    18: "004c4e83-a638-49dd-b11a-f77bbfca1d28",
}


@dataclass
class Check:
    name: str
    status: str  # PASS | FAIL | SKIP
    evidence: str


@dataclass
class OutputResult:
    issue: int
    title: str
    output_id: str
    checks: list[Check] = field(default_factory=list)

    @property
    def status(self) -> str:
        states = {c.status for c in self.checks}
        if "FAIL" in states:
            return "NOT ACCOMPLISHED"
        if "SKIP" in states:
            return "INCOMPLETE OBSERVATION"
        return "ACCOMPLISHED"


class Ctx:
    def __init__(self, offline: bool) -> None:
        self.offline = offline
        self._cache: dict[str, Check] = {}

    def cached(self, key: str, fn) -> Check:
        if key not in self._cache:
            self._cache[key] = fn()
        return self._cache[key]


# ---------------------------------------------------------------- helpers


def run(cmd: list[str], cwd: Path = ROOT, timeout: int = 300, env: dict | None = None) -> tuple[int, str]:
    try:
        done = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)
    return done.returncode, (done.stdout + done.stderr).strip()


def tail(text: str, n: int = 3) -> str:
    lines = [line for line in text.splitlines() if line.strip()]
    return " | ".join(lines[-n:])[:400]


def read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def ok(name: str, cond: bool, evidence: str, fail_evidence: str | None = None) -> Check:
    return Check(name, "PASS" if cond else "FAIL", evidence if cond else (fail_evidence or evidence))


def skip(name: str, why: str) -> Check:
    return Check(name, "SKIP", why)


def adrs() -> list[tuple[Path, str]]:
    return [(p, read(p)) for p in sorted((ROOT / "docs" / "ADR").glob("[0-9]*.md"))]


def accepted_adr(name: str, pattern: str) -> Check:
    for path, text in adrs():
        if re.search(pattern, text, re.I) and re.search(r"status:\s*accepted", text, re.I):
            indexed = path.name in read(ROOT / "docs" / "ADR" / "README.md")
            return ok(name, indexed, f"{path.relative_to(ROOT)} accepted and indexed",
                      f"{path.relative_to(ROOT)} accepted but not listed in docs/ADR/README.md")
    return Check(name, "FAIL", f"no accepted ADR in docs/ADR matching /{pattern}/")


def probe(name: str, timeout: int = 120) -> Check:
    """Run a behavior probe in the repo venv, isolated in its own process."""
    if not VENV_PYTHON.exists():
        return skip(f"probe:{name}", f"missing {VENV_PYTHON.relative_to(ROOT)}; run scripts/bootstrap.sh")
    rc, out = run([str(VENV_PYTHON), __file__, "--probe", name], timeout=timeout)
    try:
        data = json.loads(out.splitlines()[-1])
        return Check(f"probe:{name}", data["status"], data["evidence"])
    except (ValueError, IndexError, KeyError):
        return Check(f"probe:{name}", "FAIL", f"probe crashed (rc {rc}): {tail(out)}")


def mcp_call(tool: str, args: dict, timeout: int = 90) -> dict:
    def post(message: dict, headers: dict) -> tuple[dict, dict]:
        req = urllib.request.Request(SERVER_URL, data=json.dumps(message).encode(), method="POST", headers={
            "Accept": "application/json, text/event-stream", "Content-Type": "application/json", **headers})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode()
            hdrs = {k.lower(): v for k, v in resp.headers.items()}
        if "application/json" in hdrs.get("content-type", ""):
            return json.loads(body), hdrs
        data = [line[5:].strip() for line in body.splitlines() if line.startswith("data:")]
        return json.loads("\n".join(data)), hdrs

    init, hdrs = post({"jsonrpc": "2.0", "id": "init", "method": "initialize", "params": {
        "protocolVersion": "2025-03-26", "capabilities": {},
        "clientInfo": {"name": "verify-expected-outputs", "version": "1"}}}, {})
    session = {"mcp-session-id": hdrs.get("mcp-session-id", ""),
               "mcp-protocol-version": init.get("result", {}).get("protocolVersion", "2025-03-26")}
    msg, _ = post({"jsonrpc": "2.0", "id": "call", "method": "tools/call",
                   "params": {"name": tool, "arguments": args}}, session)
    result = msg.get("result") or {}
    if isinstance(result.get("structuredContent"), dict):
        return result["structuredContent"]
    for item in result.get("content", []):
        try:
            return json.loads(item.get("text", ""))
        except ValueError:
            continue
    raise ValueError(f"no JSON payload: {str(msg)[:200]}")


def live(ctx: Ctx, name: str, fn) -> Check:
    if ctx.offline:
        return skip(name, "--offline")
    try:
        return fn()
    except (OSError, urllib.error.URLError, ValueError) as exc:
        return skip(name, f"could not observe live: {str(exc)[:200]}")


def unit_tests(ctx: Ctx) -> Check:
    def go() -> Check:
        env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "LIFEOS_OTEL_DISABLE_OTLP": "1"}
        rc, out = run([str(VENV_PYTHON), "-m", "unittest", "discover", "-s", "tests"], env=env)
        return ok("garmin-mcp unit tests pass", rc == 0, tail(out, 2))
    return ctx.cached("unit", go)


def ldr_live_status(ctx: Ctx) -> Check:
    def go() -> Check:
        if ctx.offline:
            return skip("life-daily-report live garmin-status", "--offline")
        rc, out = run([str(LDR_DIR / "scripts" / "garmin-status"), "--format", "json"], cwd=LDR_DIR, timeout=120)
        try:
            data = json.loads(out[out.index("{"):])
        except ValueError:
            return Check("life-daily-report live garmin-status", "FAIL", f"rc {rc}: {tail(out)}")
        statuses, warnings = data.get("garmin_statuses", []), data.get("warnings", [])
        today = date.today().isoformat()
        good = rc == 0 and not warnings and any(s.get("calendar_date") == today for s in statuses)
        return ok("life-daily-report live garmin-status", good,
                  f"status for {today}: {statuses[0].get('summary') if statuses else None}",
                  f"rc {rc}; statuses={len(statuses)}; warnings={warnings}")
    return ctx.cached("ldr_live", go)


def ci_on_main(ctx: Ctx) -> Check:
    def go() -> Check:
        if ctx.offline:
            return skip("CI passes on latest origin/main", "--offline")
        # Only a workflow that runs the tests counts (CodeQL etc. do not).
        test_workflows = [p.name for p in (ROOT / ".github" / "workflows").glob("*.y*ml")
                          if re.search(r"unittest|pytest|make test", read(p))]
        if not test_workflows:
            return Check("CI passes on latest origin/main", "FAIL", "no test workflow in .github/workflows")
        rc, out = run(["gh", "run", "list", "-R", REPO, "--branch", "main", "--workflow", test_workflows[0],
                       "--limit", "1", "--json", "conclusion,headSha,workflowName,url"], timeout=60)
        if rc != 0:
            return skip("CI passes on latest origin/main", f"gh unavailable: {tail(out)}")
        runs = json.loads(out or "[]")
        _, head = run(["git", "ls-remote", "origin", "refs/heads/main"], timeout=60)
        head_sha = head.split()[0] if head else ""
        if not runs:
            return Check("CI passes on latest origin/main", "FAIL", "no workflow runs on main")
        last = runs[0]
        good = last.get("conclusion") == "success" and last.get("headSha") == head_sha
        return ok("CI passes on latest origin/main", good,
                  f"{last.get('workflowName')} success on {head_sha[:7]} ({last.get('url')})",
                  f"latest run {last.get('conclusion')!r} on {last.get('headSha', '')[:7]}; main is {head_sha[:7]}")
    return ctx.cached("ci", go)


def readme_heading(name: str, pattern: str) -> Check:
    text = read(ROOT / "README.md")
    found = re.search(rf"^#+\s*.*{pattern}", text, re.I | re.M)
    return ok(name, bool(found), f"README heading: {found.group(0).strip() if found else ''}",
              f"README has no heading matching /{pattern}/")


# ---------------------------------------------------------------- outputs


def out_06(ctx: Ctx) -> list[Check]:
    src = read(LDR_DIR / "src" / "life_daily_report" / "sources" / "garmin.py")
    tests = read(LDR_DIR / "tests" / "test_garmin_status.py")
    wanted = ("test_mcp_error_envelope_becomes_warning_not_status",
              "test_missing_or_mismatched_calendar_date_becomes_warning",
              "test_missing_data_produces_no_recommended_actions")
    rc, out = run(["make", "test"], cwd=LDR_DIR)
    return [
        ok("consumer rejects ok:false / undated payloads", "def garmin_payload_problem" in src,
           "garmin_payload_problem() present in sources/garmin.py"),
        ok("consumer tests cover error, date and all-null cases", all(t in tests for t in wanted),
           "all 3 named tests present", f"missing: {[t for t in wanted if t not in tests]}"),
        ok("life-daily-report make test passes", rc == 0, tail(out, 2)),
        ldr_live_status(ctx),
    ]


def out_07(ctx: Ctx) -> list[Check]:
    def service_current() -> Check:
        rc, out = run(["systemctl", "--user", "show", SERVICE, "-p", "ActiveState", "-p", "ExecMainStartTimestamp"])
        props = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
        started = props.get("ExecMainStartTimestamp", "")
        _, src_ct = run(["git", "log", "-1", "--format=%ct", "--", "src"])
        try:
            started_ts = datetime.strptime(" ".join(started.split()[1:3]), "%Y-%m-%d %H:%M:%S").timestamp()
        except ValueError:
            return skip("service runs the latest src commit", f"cannot read service start: {out[:200]}")
        good = props.get("ActiveState") == "active" and started_ts >= int(src_ct or 0)
        return ok("service runs the latest src commit", good, f"active since {started}",
                  f"state={props.get('ActiveState')}; started {started}; last src commit is newer")

    def no_arg_today() -> Check:
        today = date.today().isoformat()
        got = mcp_call("garmin_get_day_overview", {})
        return ok("live no-arg day overview returns today", got.get("calendar_date") == today,
                  f"returned {got.get('calendar_date')}", f"returned {got.get('calendar_date')}, expected {today}")

    return [
        probe("day_overview_default_is_resolved_per_call"),
        unit_tests(ctx),
        ok("README documents the default", "resolved on each call" in read(ROOT / "README.md"),
           "README: default date 'resolved on each call'", "README lacks 'resolved on each call'"),
        live(ctx, "service runs the latest src commit", service_current),
        live(ctx, "live no-arg day overview returns today", no_arg_today),
    ]


def out_08(ctx: Ctx) -> list[Check]:
    def live_source() -> Check:
        got = mcp_call("garmin_get_day_overview", {"target_date": date.today().isoformat()})
        src = got.get("source")
        return ok("live response carries source", isinstance(src, dict) and bool(src.get("provider")),
                  f"source={src}", f"no source object in live response keys {sorted(got)[:8]}")
    return [
        probe("every_tool_response_has_source_and_date"),
        probe("empty_calorie_range_has_null_totals"),
        readme_heading("README has a response contract section", r"response contract"),
        unit_tests(ctx),
        live(ctx, "live response carries source", live_source),
    ]


def out_09(ctx: Ctx) -> list[Check]:
    tests = "\n".join(read(p) for p in (ROOT / "tests").glob("test_*.py"))
    missing = [t for t in OUT_01_TOOLS if t not in tests]
    readme = read(ROOT / "README.md")
    no_wear = re.search(r"^#+\s*no[- ]wear.*$", readme, re.I | re.M)
    dated = bool(no_wear and re.search(r"\d{4}-\d{2}-\d{2}", readme[no_wear.start():no_wear.start() + 1500]))
    return [
        ok("tests exercise every OUT_01 tool", not missing, f"tests reference {', '.join(OUT_01_TOOLS)}",
           f"no test references {missing}"),
        probe("missing_values_are_null_not_zero"),
        ok("no-wear-day result documented with a date", dated, "README no-wear section with observed date",
           "README needs a 'No-wear day' heading that states the observed date and null-vs-0 result"),
        unit_tests(ctx),
    ]


def out_10(ctx: Ctx) -> list[Check]:
    workflows = [(p, read(p)) for p in (ROOT / ".github" / "workflows").glob("*.y*ml")]
    runs_tests = [p.name for p, t in workflows if re.search(r"unittest|pytest|make test", t)]
    rc, out = run(["make", "test"])
    bare_env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    bare_env["LIFEOS_OTEL_DISABLE_OTLP"] = "1"
    rc2, out2 = run([str(VENV_PYTHON), "-m", "unittest", "discover", "-s", "tests"], env=bare_env)
    return [
        ok("workflow runs the tests", bool(runs_tests), f"workflows: {runs_tests}", "no .github/workflows file runs tests"),
        ok("make test passes", rc == 0, tail(out, 2)),
        ok("tests run without PYTHONPATH", rc2 == 0, tail(out2, 2)),
        ok("README documents make test", "make test" in read(ROOT / "README.md"), "README mentions `make test`"),
        ci_on_main(ctx),
    ]


def out_11(ctx: Ctx) -> list[Check]:
    return [
        probe("one_login_across_tool_calls"),
        probe("no_password_fallback_on_connection_error"),
        probe("retries_after_rate_limit"),
        ok("README states the request budget", re.search(r"request budget", read(ROOT / "README.md"), re.I) is not None,
           "README mentions 'request budget'"),
        unit_tests(ctx),
    ]


def out_12(ctx: Ctx) -> list[Check]:
    locks = [n for n in ("uv.lock", "pylock.toml", "requirements.lock", "requirements-lock.txt") if (ROOT / n).exists()]
    lock_text = "".join(read(ROOT / n) for n in locks)
    single = not (ROOT / "requirements.txt").exists() or "autogenerated" in read(ROOT / "requirements.txt").lower() \
        or "generated" in read(ROOT / "requirements.txt").lower()[:300]

    def current() -> Check:
        lagging = []
        for pkg in ("garminconnect", "garth"):
            rc, out = run([str(VENV_PYTHON), "-m", "pip", "show", pkg], timeout=60)
            installed = re.search(r"^Version:\s*(\S+)", out, re.M)
            with urllib.request.urlopen(f"https://pypi.org/pypi/{pkg}/json", timeout=20) as resp:
                latest = json.load(resp)["info"]["version"]
            inst = installed.group(1) if installed else "?"
            if inst.split(".")[:2] != latest.split(".")[:2]:
                lagging.append(f"{pkg} {inst} < {latest}")
        return ok("garminconnect and garth on current minor release", not lagging, "both current", "; ".join(lagging))

    return [
        ok("lock file exists", bool(locks), f"lock: {locks}", "no uv.lock / pylock.toml / requirements.lock"),
        ok("lock pins garth", "garth" in lock_text, "garth pinned in lock", "garth not in a lock file"),
        ok("pyproject is the single dependency source", single, "requirements.txt absent or generated",
           "requirements.txt is still hand-maintained alongside pyproject.toml"),
        live(ctx, "garminconnect and garth on current minor release", current),
        accepted_adr("decision recorded on mcp 2.x", r"mcp\s*2"),
        unit_tests(ctx),
        ci_on_main(ctx),
        live(ctx, "live token login works", lambda: ok(
            "live token login works", mcp_call("garmin_get_day_overview", {}).get("ok") is True,
            "live call ok=true")),
    ]


def out_13(ctx: Ctx) -> list[Check]:
    candidates = [ROOT / ".state" / "garmin-tokens", WORKSPACE / "config" / "garmin-mcp" / "tokens"]
    existing = [str(p.relative_to(WORKSPACE)) for p in candidates if p.is_dir() and any(p.iterdir())]
    scripts = [p for p in (ROOT / "scripts").glob("*.sh")]
    shallow = [p.name for p in scripts if 'PROJECT_DIR}/../.."' in read(p)]
    cfg_default = re.search(r'GARMIN_TOKENS_DIR",\s*"([^"]+)"', read(ROOT / "src" / "garmin_mcp" / "config.py"))
    example = re.search(r"^GARMIN_TOKENS_DIR=(\S+)", read(ROOT / ".env.example"), re.M)
    same = bool(cfg_default and example and cfg_default.group(1) == example.group(1))
    return [
        ok("exactly one token store on disk", len(existing) == 1, f"token store: {existing}",
           f"token stores with files: {existing}"),
        ok("scripts resolve the workspace root", not shallow, "no script uses PROJECT_DIR/../.. as workspace",
           f"WORKSPACE_DIR resolves to repositories/ in {shallow}"),
        ok(".env.example token path matches config default", same,
           f"both {cfg_default.group(1) if cfg_default else None}",
           f"config={cfg_default.group(1) if cfg_default else None} example={example.group(1) if example else None}"),
        readme_heading("README configuration reference", r"configuration"),
    ]


def out_14(ctx: Ctx) -> list[Check]:
    rc, out = run(["git", "grep", "-nE", r"/media/|/home/[a-z]", "--", ".", ":!scripts/verify_expected_outputs.py"])
    unit = read(ROOT / "systemd" / "lifeos-garmin-mcp.service")
    runbook = next((p for p in (ROOT / "docs").rglob("*.md") if re.search(r"systemctl --user (enable|start)", read(p))), None)
    return [
        ok("no absolute machine paths in tracked files", rc == 1 and not out, "git grep found none", tail(out, 3)),
        ok("systemd unit is portable", "%h" in unit or "EnvironmentFile" in unit or not unit,
           "unit uses %h/EnvironmentFile", "unit has no %h or EnvironmentFile"),
        ok("stdio launcher does not install packages", "bootstrap.sh" not in read(ROOT / "scripts" / "mcp_stdio.sh"),
           "mcp_stdio.sh never calls bootstrap.sh", "mcp_stdio.sh still runs bootstrap.sh (pip install) at startup"),
        ok("install/update runbook exists", runbook is not None,
           f"runbook: {runbook.relative_to(ROOT) if runbook else ''}", "no docs/*.md with `systemctl --user enable|start` steps"),
    ]


def out_15(ctx: Ctx) -> list[Check]:
    cli = read(ROOT / "src" / "garmin_mcp" / "cli.py")
    return [
        probe("cli_and_mcp_return_identical_payloads"),
        ok("CLI does not shape Garmin fields itself", "totalSteps" not in cli and "sleep_time_seconds" not in cli,
           "no raw Garmin field mapping in cli.py", "cli.py still maps Garmin fields (totalSteps/sleep rows)"),
        unit_tests(ctx),
    ]


def out_16(ctx: Ctx) -> list[Check]:
    pyproject = read(ROOT / "pyproject.toml")
    version = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.M)
    ver = version.group(1) if version else "?"
    changelog = read(ROOT / "CHANGELOG.md")
    return [
        accepted_adr("ADR for the streamable-HTTP access point", r"streamable"),
        ok("package metadata updated", ver != "0.1.0" and "phase-1" not in pyproject.lower(),
           f"version {ver}", f"version {ver}; description still says phase-1" if "phase-1" in pyproject.lower() else f"version {ver}"),
        ok("CHANGELOG has the current version", bool(changelog) and ver in changelog,
           f"CHANGELOG.md lists {ver}", "CHANGELOG.md missing or lacks current version"),
    ]


def out_17(ctx: Ctx) -> list[Check]:
    def unauth_rejected() -> Check:
        req = urllib.request.Request(SERVER_URL, method="POST", data=b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"x","version":"1"}}}',
                                     headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return Check("unauthenticated request rejected", "FAIL", f"HTTP {resp.status}: accepted without credential")
        except urllib.error.HTTPError as exc:
            return ok("unauthenticated request rejected", exc.code in (401, 403), f"HTTP {exc.code}")
    consumer = read(LDR_DIR / "src" / "life_daily_report" / "sources" / "garmin.py")
    return [
        accepted_adr("access-model ADR", r"access model"),
        live(ctx, "unauthenticated request rejected", unauth_rejected),
        ok("consumer sends a credential", "Authorization" in consumer, "life-daily-report sets Authorization",
           "life-daily-report Garmin source sends no Authorization header"),
        ldr_live_status(ctx),
    ]


def out_18(ctx: Ctx) -> list[Check]:
    def live_flag() -> Check:
        got = mcp_call("garmin_get_day_overview", {"target_date": NO_WEAR_DAY})
        return ok("live 2026-08-19 day overview carries the no-wear flag", _no_wear_flag(got),
                  f"flag present; daily_summary={got.get('daily_summary')}",
                  f"no no-wear flag; daily_summary={got.get('daily_summary')}")
    readme = read(ROOT / "README.md")
    return [
        probe("no_wear_day_is_flagged_and_not_zero"),
        ok("README describes the normalized no-wear behavior", "currently\npasses those values through" not in readme
           and "currently passes those values through" not in readme and "No-wear day" in readme,
           "README no longer says values are passed through", "README still says no-wear values are passed through"),
        unit_tests(ctx),
        live(ctx, "live 2026-08-19 day overview carries the no-wear flag", live_flag),
    ]


NO_WEAR_DAY = "2026-08-19"
# Raw Garmin summary observed for a no-wear day (2026-08-19, trimmed).
NO_WEAR_SUMMARY = {"totalSteps": None, "totalDistanceMeters": 0, "activeKilocalories": 0.0,
                   "bmrKilocalories": 2047.0, "totalKilocalories": 2047.0, "wellnessKilocalories": 2047.0,
                   "restingHeartRate": None, "averageStressLevel": -1, "sedentarySeconds": 86400,
                   "highlyActiveSeconds": 0}


def _no_wear_flag(payload: dict) -> bool:
    """Accept any explicit no-wear marker the implementation chooses."""
    blobs = [payload, payload.get("daily_summary") or {}, payload.get("calories") or {}]
    for blob in blobs:
        if blob.get("wear_data") is False or blob.get("no_wear") is True:
            return True
        if "no_wear" in str(blob.get("data_status", "")).lower():
            return True
    return False


OUTPUTS = {
    6: ("Daily report treats Garmin MCP errors and undated payloads as warnings", out_06),
    7: ("Day overview default date resolved per call, live in the service", out_07),
    8: ("Response contract: source, date and units on every response", out_08),
    9: ("OUT_01 contract tests and documented no-wear-day result", out_09),
    10: ("CI test workflow and make test", out_10),
    11: ("Resilient Garmin session layer", out_11),
    12: ("Locked, current dependencies and mcp 2.x decision", out_12),
    13: ("Single env/token configuration reference", out_13),
    14: ("Portable service install runbook", out_14),
    15: ("Single response-contract module for CLI and MCP", out_15),
    16: ("HTTP access-point ADR, versioning and CHANGELOG", out_16),
    17: ("Access model and client authentication", out_17),
    18: ("No-wear days flagged instead of reported as zeros", out_18),
}


# ---------------------------------------------------------------- probes
# Probes run in the repo venv (via --probe) against a fake Garmin client, so
# they observe behavior through public tool functions, not implementation names.


def _probe_env():
    import tempfile
    from unittest import mock

    sys.path.insert(0, str(ROOT / "src"))
    tmp = tempfile.mkdtemp(prefix="garmin-verify-")
    os.environ.update({"GARMIN_TOKENS_DIR": tmp, "GARMIN_USERNAME": "probe@example.invalid",
                       "GARMIN_PASSWORD": "probe", "GARMIN_ENV_FILE": os.path.join(tmp, "none.env"),
                       "LIFEOS_OTEL_DISABLE_OTLP": "1", "GARMIN_MAX_RANGE_DAYS": "93"})
    import garminconnect

    class State:
        logins: list[str] = []
        token_error: Exception | None = None
        rate_limit_once = False
        summary: dict = {}
        sleep: dict = {}
        activities: list = []

    class FakeGarmin:
        def __init__(self, *args, **kwargs):
            self.garth = mock.Mock()

        def login(self, tokenstore=None, *args, **kwargs):
            State.logins.append("token" if tokenstore else "password")
            if tokenstore and State.token_error is not None:
                raise State.token_error
            return None, None

        def get_user_summary(self, day):
            if State.rate_limit_once:
                State.rate_limit_once = False
                raise garminconnect.GarminConnectTooManyRequestsError("429")
            return {"calendarDate": day, **State.summary}

        def get_sleep_data(self, day):
            return State.sleep

        def get_activities_by_date(self, start, end, *args, **kwargs):
            return State.activities

        def get_body_battery(self, start, end=None):
            return []

    import garmin_mcp.cli  # noqa: F401  (import before patching so every module is loaded)
    import garmin_mcp.mcp_server  # noqa: F401
    for name, module in list(sys.modules.items()):
        if name.startswith("garmin_mcp") and hasattr(module, "Garmin"):
            setattr(module, "Garmin", FakeGarmin)
    import time
    time.sleep = lambda *_a, **_k: None
    return State, garmin_mcp.mcp_server


def _result(status: str, evidence: str) -> None:
    print(json.dumps({"status": status, "evidence": evidence[:400]}))


def run_probe(name: str) -> None:
    State, server = _probe_env()
    day = "2026-01-15"
    if name == "day_overview_default_is_resolved_per_call":
        import inspect
        default = inspect.signature(server.garmin_get_day_overview).parameters["target_date"].default
        got = server.garmin_get_day_overview()
        good = default in ("", None) and got.get("calendar_date") == date.today().isoformat()
        _result("PASS" if good else "FAIL", f"default={default!r}; no-arg call returned {got.get('calendar_date')}")
    elif name == "every_tool_response_has_source_and_date":
        calls = {
            "garmin_get_day_overview": lambda: server.garmin_get_day_overview(day),
            "garmin_list_activities": lambda: server.garmin_list_activities(day, day),
            "garmin_get_sleep_range": lambda: server.garmin_get_sleep_range(day, day),
            "garmin_get_calories": lambda: server.garmin_get_calories(day, day),
            "garmin_get_health_history": lambda: server.garmin_get_health_history(day, day),
        }
        bad = []
        for tool, call in calls.items():
            got = call()
            src = got.get("source")
            dated = bool(got.get("calendar_date") or (got.get("start_date") and got.get("end_date")))
            if not (isinstance(src, dict) and src.get("provider") and src.get("retrieved_at") and dated):
                bad.append(tool)
        _result("FAIL" if bad else "PASS", f"missing source/provider/retrieved_at/date in: {bad}" if bad
                else "all tools return source.provider, source.retrieved_at and a date")
    elif name == "empty_calorie_range_has_null_totals":
        got = server.garmin_get_calories(day, day)
        summary = got.get("summary", {})
        totals = {k: summary.get(k) for k in ("total_active_kilocalories", "total_burned_kilocalories")}
        _result("PASS" if all(v is None for v in totals.values()) else "FAIL", f"no-data range totals: {totals}")
    elif name == "missing_values_are_null_not_zero":
        overview = server.garmin_get_day_overview(day)
        values = {**overview.get("daily_summary", {}), **{f"sleep.{k}": v for k, v in overview.get("sleep", {}).items()
                                                         if k != "calendar_date"}}
        zeros = [k for k, v in values.items() if v == 0]
        _result("FAIL" if zeros or not values else "PASS",
                f"fields reported as 0 for a no-data day: {zeros}" if zeros else f"{len(values)} fields null on a no-data day")
    elif name == "one_login_across_tool_calls":
        server.garmin_get_day_overview(day)
        server.garmin_get_day_overview(day)
        server.garmin_get_sleep_range(day, day)
        _result("PASS" if len(State.logins) == 1 else "FAIL", f"logins across 3 tool calls: {State.logins}")
    elif name == "no_password_fallback_on_connection_error":
        import garminconnect
        State.token_error = garminconnect.GarminConnectConnectionError("network down")
        got = server.garmin_get_day_overview(day)
        good = "password" not in State.logins and got.get("ok") is False
        _result("PASS" if good else "FAIL", f"logins={State.logins}; response ok={got.get('ok')} error={got.get('error')}")
    elif name == "retries_after_rate_limit":
        State.rate_limit_once = True
        got = server.garmin_get_day_overview(day)
        _result("PASS" if got.get("ok") is True else "FAIL",
                f"after one 429: ok={got.get('ok')} error={got.get('error')}")
    elif name == "cli_and_mcp_return_identical_payloads":
        from typer.testing import CliRunner
        from garmin_mcp.cli import app
        State.summary = {"totalSteps": 1234, "totalDistanceMeters": 900, "activeKilocalories": 50, "totalKilocalories": 2000}
        State.sleep = {"dailySleepDTO": {"calendarDate": day, "sleepTimeSeconds": 25000}}
        pairs = {
            "day": (["day", "--date", day], lambda: server.garmin_get_day_overview(day)),
            "activities": (["activities", "--start-date", day, "--end-date", day], lambda: server.garmin_list_activities(day, day)),
            "sleep-range": (["sleep-range", "--start-date", day, "--end-date", day], lambda: server.garmin_get_sleep_range(day, day)),
            "calories": (["calories", "--start-date", day, "--end-date", day], lambda: server.garmin_get_calories(day, day)),
        }

        def norm(payload: dict) -> dict:
            payload = {k: v for k, v in payload.items() if k != "ok"}
            if isinstance(payload.get("source"), dict):
                payload["source"] = {k: v for k, v in payload["source"].items() if k != "retrieved_at"}
            return payload

        differ = []
        for command, (argv, tool) in pairs.items():
            out = CliRunner().invoke(app, argv)
            try:
                cli_payload = json.loads(out.output)
            except ValueError:
                differ.append(f"{command} (CLI output not JSON)")
                continue
            if norm(cli_payload) != norm(tool()):
                differ.append(command)
        _result("FAIL" if differ else "PASS", f"CLI and MCP payloads differ for: {differ}" if differ
                else "CLI and MCP return identical payloads for day, activities, sleep-range, calories")
    elif name == "no_wear_day_is_flagged_and_not_zero":
        State.summary = dict(NO_WEAR_SUMMARY)
        overview = server.garmin_get_day_overview(NO_WEAR_DAY)
        calories = server.garmin_get_calories(NO_WEAR_DAY, NO_WEAR_DAY)
        ds = overview.get("daily_summary", {})
        problems = []
        if ds.get("distance_meters") is not None:
            problems.append(f"distance_meters={ds.get('distance_meters')}")
        if ds.get("active_kilocalories") is not None:
            problems.append(f"active_kilocalories={ds.get('active_kilocalories')}")
        if not _no_wear_flag(overview):
            problems.append("no no-wear flag")
        if calories.get("summary", {}).get("tracked_days"):
            problems.append(f"calories tracked_days={calories['summary']['tracked_days']}")
        _result("FAIL" if problems else "PASS", "; ".join(problems) if problems
                else "no-wear day: null distance/active kcal, flagged, excluded from calorie tracking")
    else:
        _result("FAIL", f"unknown probe {name}")


# ---------------------------------------------------------------- report


def lifeos_status() -> dict[str, str]:
    try:
        with urllib.request.urlopen(f"{LIFEOS_URL}/api/tracks/{TRACK_ID}/context", timeout=10) as resp:
            ctx = json.load(resp)
    except (OSError, ValueError):
        return {}
    states = {}
    for task in ctx.get("tasks", []):
        for output in task.get("expected_outputs", []) or []:
            verification = (output.get("verification") or {}).get("status")
            states[output.get("id")] = f"{output.get('status')}/{verification}"
    return states


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", help="comma-separated issue numbers, e.g. 7,8")
    parser.add_argument("--offline", action="store_true", help="skip live service, GitHub and PyPI checks")
    parser.add_argument("--json", action="store_true", help="print JSON instead of text")
    parser.add_argument("--save", action="store_true", help="write a JSON report under .state/expected-outputs/")
    parser.add_argument("--probe", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.probe:
        run_probe(args.probe)
        return 0

    selected = [int(n) for n in args.only.split(",")] if args.only else sorted(OUTPUTS)
    ctx = Ctx(offline=args.offline)
    results = []
    for issue in selected:
        title, fn = OUTPUTS[issue]
        results.append(OutputResult(issue, title, OUTPUT_IDS[issue], fn(ctx)))
    recorded = {} if args.offline else lifeos_status()
    observed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    report = {
        "observed_at": observed_at,
        "head": run(["git", "rev-parse", "--short", "HEAD"])[1],
        "outputs": [{**asdict(r), "status": r.status, "lifeos_recorded": recorded.get(r.output_id)} for r in results],
    }
    if args.save:
        out_dir = ROOT / ".state" / "expected-outputs"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{observed_at.replace(':', '')}.json").write_text(json.dumps(report, indent=2))
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Expected outputs for {TRACK_ID} — observed {observed_at} at {report['head']}\n")
        for r in results:
            rec = recorded.get(r.output_id)
            print(f"#{r.issue} {r.title}: {r.status}" + (f"  [LifeOS: {rec}]" if rec else ""))
            for c in r.checks:
                print(f"   {c.status:4} {c.name} — {c.evidence}")
            print()
        done = sum(r.status == "ACCOMPLISHED" for r in results)
        print(f"{done}/{len(results)} accomplished.")
    return 0 if all(r.status == "ACCOMPLISHED" for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
