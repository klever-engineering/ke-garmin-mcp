# ADR 0008: Owner-Only Token Location

- Status: Accepted (owner approved 2026-10-25)
- Date: 2026-10-25
- Issue: #13
- Amends: ADR 0002 (default token path)

## Context

ADR 0002 set the default token directory to the workspace-relative
`config/garmin-mcp/tokens`. The workspace sits on an NTFS drive mounted with
`allow_other` and fixed modes, so `chmod` has no effect there: the Garmin
tokens were readable by every local user. A second, stale token store
(`.state/garmin-tokens`) and the old garth files (`oauth1_token.json`,
`oauth2_token.json`, unused since garminconnect 0.3) were also on disk.

## Decision

- The default token directory is `$XDG_CONFIG_HOME/lifeos/garmin-mcp/tokens`,
  which is `~/.config/lifeos/garmin-mcp/tokens` when `XDG_CONFIG_HOME` is
  unset. It is on the home filesystem, which honours Unix permissions.
- `GARMIN_TOKENS_DIR` still overrides it. Relative values still resolve from
  the workspace root, as in ADR 0002.
- The server creates the directory with mode 700 and sets token files to 600
  after every login. It logs a warning if the filesystem ignores the modes.
- There is one token store. The old stores and the garth files were deleted
  with the owner's approval after the new location was verified live.
- Docker mounts the same directory at `/data/tokens` and runs as the host user.

## Consequences

- Other local users can no longer read the tokens.
- The token location no longer depends on where the checkout lives.
- Moving to another machine requires one credential login, or a copy of
  `garmin_tokens.json` into the new directory with mode 600.
