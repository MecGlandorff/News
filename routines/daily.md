Run the existing News application for today's dogfooding briefing in
`/Users/mrgreen/Desktop/AI/News-worktrees/from-scratch`.
Scheduled time: every day at 18:00 Europe/Brussels. This prompt does not create
or activate the schedule.

Read `AGENTS.md` and `DOGFOOD.md`. This is an operational run: do not edit code,
tasks, schemas, feeds, schedules or experiment branches. Do not install or
upgrade dependencies. Only the application's data and report writes are in
scope. Preserve the human-edited `.news/dogfood/feedback.md`.

Run this command once:

```sh
.venv/bin/python -m news daily --feeds feeds.json --state .news/dogfood --batch-size 8 --max-batches 12 --timeout 360
```

Use the existing authenticated Codex CLI and fixed `gpt-6-astra` / medium settings.
The ceiling is 12 batch attempts, each with at most one news-model CLI invocation
and a 360-second deadline. Preserve the capture, pending backlog, accepted journal
and failed artifacts. Do not loop, retry a failed batch, invoke an extra resume
run, rebuild memory, change settings or increase a limit to make the run finish.
If another writer is active or a prerequisite is missing, report that condition
and stop. Do not interfere with its process or attempt interactive login.

Inspect this invocation's report and dated briefing. Summarize captured new or
revised source versions, accepted batches, remaining pending work, failures and
reported usage where available. Mark unavailable counts or token usage as unknown;
never convert them to zero. Distinguish CLI invocations from any internal Codex
reconnection attempts. Link the exact report and briefing, then the feedback file.
Keep earlier successful and failed reports intact.

Explain any feed exclusions, missing capture coverage, context overflow or
unprocessed backlog recorded by the app. Capture dates are observation dates;
older publication dates are allowed. Each run collects feeds once; RSS-only
capture cannot recover items that disappeared between polls. Deduplication uses
the last observed version set per source and URL, preserving A → B → A revisions
without replaying an unchanged simultaneous {A, B} set. Do not claim a complete
daily news picture, factual accuracy or successful story tracking from a successful
process exit. Report
material narrative concerns with source and run links instead of silently editing
the generated briefing. Do not launch an improvement experiment in this routine.
