# ADR 0002: Token Storage and Environment Rules

- Status: Accepted
- Date: 2026-03-03

## Context

We want login-once behavior while keeping secrets out of source code and git.

## Decision

- Credentials are read from environment variables:
  - `GARMIN_USERNAME`
  - `GARMIN_PASSWORD`
- OAuth token files are persisted in a local directory configured by `GARMIN_TOKENS_DIR`.
- Default token path is relative: `.state/garmin-tokens`.
- Absolute paths are allowed only through environment variables (for example `GARMIN_ENV_FILE`).

## Consequences

- Pros:
  - No hardcoded secrets or absolute paths in code.
  - Token reuse reduces repeated credential prompts.
- Cons:
  - Local token files must be protected on disk.
  - Initial credential login is still required.

## Revisit Trigger

Revisit when migrating to keyring/secret manager storage or enterprise auth controls.

