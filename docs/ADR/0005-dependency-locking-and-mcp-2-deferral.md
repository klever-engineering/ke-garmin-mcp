# ADR 0005: Dependency Locking and Deferring mcp 2.x

- Status: Accepted
- Date: 2026-10-25
- Issue: #12

## Context

A technical-debt audit (2026-10-25) found the core dependencies far behind:
`garminconnect` 0.2.38 (latest 0.3.20), `garth` 0.5.21 (latest 0.8.0) and
`mcp` 1.26.0 (latest 2.3.0). The pins were duplicated in `pyproject.toml` and
`requirements.txt`, with no lock file, so transitive dependencies such as the
Garmin auth library were not pinned at all.

Evaluation in a separate virtual environment showed:

- `garminconnect` 0.3.x no longer depends on `garth`. It ships its own Garmin
  SSO client built on `curl_cffi`, stores tokens in `garmin_tokens.json`, and
  cannot read the old garth tokens (`oauth1_token.json`/`oauth2_token.json`).
  One credential login is needed to migrate. Given credentials, it also falls
  back to a credential login by itself after any token failure, and it retries
  5xx/network errors internally.
- `mcp` 2.x removes `mcp.server.fastmcp.FastMCP` (renamed to
  `mcp.server.mcpserver.MCPServer`, with other API changes). With 2.3.0 the
  server module does not import. All 41 tests pass with `garminconnect` 0.3.20
  and `mcp` 1.30.0, the latest 1.x release (2026-09-07).

## Decision

1. `pyproject.toml` is the only place direct dependencies are declared, as
   compatible ranges. `uv.lock` pins every package, including transitive ones.
   `requirements.txt` is generated from the lock with hashes (`make lock`) for
   pip, Docker and CI, and is never edited by hand. Dependabot uses the `uv`
   ecosystem so updates change `uv.lock`.
2. Upgrade to `garminconnect` 0.3.20 now. `client.login()` tries tokens with a
   client that has no credentials, so the library cannot fall back to a
   password login by itself; `is_token_problem()` keeps that decision (#11).
   Library retries are turned off (`retry_attempts=0`) so
   `session.RetryingGarmin` is the only retry budget.
3. **Defer `mcp` 2.x.** Pin `mcp>=1.30.0,<2`. Moving to 2.x is a code migration
   (FastMCP to MCPServer, transport setup), not a version bump, so it is
   tracked as its own issue and done with the contract tests and a live
   check of the streamable-HTTP service as the gate.

## Consequences

- `garth` is no longer installed. The old garth token files are unused once
  `garmin_tokens.json` exists; delete them when the token location is
  consolidated (#13).
- Upgrades become reviewable diffs of `uv.lock`; CI runs the tests on them.
- `requires-python` is now `>=3.12`, because `garminconnect` 0.3 requires it.
- Revisit the `mcp` 2.x deferral when the migration issue is picked up, or by
  2027-01-31, whichever comes first.
