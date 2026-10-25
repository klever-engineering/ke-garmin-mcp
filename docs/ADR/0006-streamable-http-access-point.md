# ADR 0006: Streamable-HTTP Garmin Access Point and Contract Versioning

- Status: Accepted
- Date: 2026-10-25
- Issue: #16
- Amends: ADR 0004 (adds the HTTP transport); supersedes ADR 0003 (phase-1 CLI scope)

## Context

ADR 0003 scoped phase 1 as a CLI, and ADR 0004 delivered MCP over `stdio`
(plus Docker). Since commit cab4804 (2026-06-21) the production path has been
a long-running streamable-HTTP MCP server run as a systemd user service.
`repositories/tools/life-daily-report` reads it every day, and the LifeOS
Track goal is for this server to be the single access point to the owner's
Garmin Connect data for LifeOS and other apps. No record described that
role, how the service is run, or how consumers learn which response contract
they are reading: the package was still `0.1.0` with the description
"phase-1 connector", and there was no changelog.

## Decision

1. **Role.** `garmin-mcp` is the access point for Garmin Connect data. Apps
   and agents read Garmin data through its MCP tools (or the CLI, which
   returns the same payloads); they do not call Garmin Connect directly.
2. **Transport.** Production runs streamable HTTP at
   `http://127.0.0.1:8000/mcp` (`scripts/mcp_streamable_http.sh`;
   `FASTMCP_HOST`/`FASTMCP_PORT` override the bind). `stdio`
   (`scripts/mcp_stdio.sh`) stays supported for local agent clients. The
   server binds to localhost only; any wider exposure needs the access model
   from #17 first.
3. **Lifecycle.** The `lifeos-garmin-mcp.service` systemd user unit keeps it
   running (`Restart=always`). The server logs in to Garmin once per process
   (ADR 0005, `session.py`), so settings and code changes take effect only
   after `systemctl --user restart lifeos-garmin-mcp.service`. A deploy is:
   pull, sync the venv to `requirements.txt`, restart, then check with
   `make verify-outputs` or a `tools/list` call.
4. **Contract versioning.** The response contract is defined in
   `src/garmin_mcp/contract.py` and the README "Response contract" section.
   The package version follows semantic versioning on that contract:
   - MAJOR: removing or renaming a field, changing a unit or meaning, or
     removing a tool;
   - MINOR: new tools or fields, and stricter handling of missing data that
     turns non-measurements into `null` (documented in the changelog);
   - PATCH: fixes that keep the contract.
   While the version is `0.x`, a MINOR bump may also include breaking changes,
   and the changelog marks them. Every response's `source.server` names the
   server version, so consumers can tell which contract they received.
   `CHANGELOG.md` records each version.

## Consequences

- Consumers can pin expectations to a version and read the changelog before
  upgrading.
- Contract changes need a version bump and a changelog entry in the same
  change.
- ADR 0003 no longer describes the system and is superseded; ADR 0004 still
  applies to `stdio` and Docker.
