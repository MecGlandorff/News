# ADR 0018: Explicit Brussels editorial day

**Date:** 2026-07-11

## Status

Accepted.

## Context

RSS timestamps are absolute, but selecting a daily briefing previously used the host machine's timezone. The same feed item could therefore move between run dates on different machines.

## Decision

Use `Europe/Brussels` as the single editorial timezone for feed-date filtering and the default run date. Continue normalizing persisted and displayed timestamps to UTC.

## Consequences

- A briefing day is deterministic across hosts and matches this personal project's editorial context.
- DST rules come from Python's IANA timezone database.
- Changing the editorial timezone later is a product decision because it changes which articles belong to a run.
