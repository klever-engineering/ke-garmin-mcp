# ADR 0001: Personal Garmin Access Strategy

- Status: Accepted
- Date: 2026-03-03

## Context

We need a local personal integration to query Garmin Connect metrics quickly (sleep, workouts, daily summary), with no enterprise onboarding delay.

## Decision

Use the community Python library `garminconnect` for phase 1, authenticated with personal Garmin Connect credentials from environment variables.

## Consequences

- Pros:
  - Fast setup for personal use.
  - Works locally without business approval process.
- Cons:
  - Unofficial integration path may break when Garmin changes internals.
  - Needs monitoring and maintenance.

## Revisit Trigger

Revisit when moving to multi-user production/commercial use, where official Garmin program constraints and compliance are required.

