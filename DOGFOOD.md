# Daily use and weekly improvement

The routine prompts are prepared; **neither schedule has been activated**.
This session cannot access the Codex app to configure routines, and no scheduling
tool is available. Create the schedules manually using these settings and paste
the linked file's contents as its prompt:

| Routine | Selected schedule | Local project | Prompt |
| --- | --- | --- | --- |
| Daily briefing | Every day, 18:00 Europe/Brussels | `/Users/mrgreen/Desktop/AI/News-worktrees/from-scratch` | [daily.md](routines/daily.md) |
| Weekly experiment | Sunday, 10:00 Europe/Brussels | Same project | [weekly.md](routines/weekly.md) |

Use the named timezone so the selected local times follow daylight saving
changes. Select local execution for this project and `gpt-6-astra` with medium
reasoning. Keep the computer on and the desktop app running. The task needs
the existing authenticated Codex CLI, write access to `.news/dogfood`, and network
access to the three configured feeds and the Codex service. Test one run from the
task's own environment after saving it; that scheduled environment has not been
verified here. See the [official scheduling documentation](https://learn.chatgpt.com/docs/automations).
Scheduling does not
provide missing feed history or guarantee that a run succeeds. Follow the
[installation instructions](README.md#start) first and review `feeds.json`.

## Daily command

From the local project:

```sh
.venv/bin/python -m news daily --feeds feeds.json --state .news/dogfood --batch-size 8 --max-batches 12 --timeout 360
```

These are the daily defaults. Capture and processing can also be separated:

```sh
.venv/bin/python -m news daily --feeds feeds.json --state .news/dogfood --collect-only
.venv/bin/python -m news daily --feeds feeds.json --state .news/dogfood --resume-only
```

`--collect-only` freezes available sources with zero model calls. `--resume-only`
processes frozen pending batches without fetching feeds. An ordinary invocation
captures sources once and works through pending batches chronologically. The
shown command permits at most 12 batch attempts and 24 Codex CLI invocations:
each attempt proposes stories and independently reviews their coherence, using
`gpt-6-astra` with medium reasoning and a shared 360-second batch deadline.
Processing stops at the first failed batch and does not automatically retry it within
the invocation. Codex may reconnect internally; CLI invocations are not a count
of backend attempts. Leave pending work for a later invocation.

An unsupported or uncertain grouping is rejected automatically before acceptance.
The report counts proposal and reviewer calls separately, preserving known token
usage even if the other call's usage is unavailable. Review failures stop the
queue with both outputs retained. The check covers touched stories and their
complete supplied history; it does not retroactively repair the old archive.
Never edit accepted assignments or generated outputs to clear a failure. Diagnose
it in an experiment using frozen inputs and an improved general mechanism.

Daily capture keeps all valid items currently exposed by the configured feeds,
including older publication dates. It reads RSS/Atom text, not full article web
pages. For each source and URL, new versions are compared with the set of versions
present at its last observation. A revision sequence A → B → A preserves the
return to A; repeatedly seeing the same simultaneous set {A, B} does not replay
either version. Capture day means **observed on**, not the article's publication
or event date. Collection happens once per daily routine, not continuously.
Frozen processing copies receive capture-specific article IDs, with a raw-version
digest to processing-ID mapping in the manifest. Original parser IDs and all source
fields stay in the manifest; source text, URL and publication time are unchanged
in processing. This also retains A → B → A captures within one day. A separate
capture is not evidence that a distinct news event occurred.
Missing feed contents between captures cannot be reconstructed. This
differs from the publication-day selection of the separate `news fetch` command.

Small batches limit routine work; they do not guarantee that retrieved history
fits the context budget. Inspect reports for feed failures, exclusions, backlog
and processing failures, and per-run retrieval diagnostics for supplied context.
Successful feeds may still be processed when another feed fails; coverage is
partial. Successful processing and valid quotes do not establish complete
coverage, retrieval of every relevant source, or story quality.

All daily state lives under `.news/dogfood/`:

| Path | Purpose |
| --- | --- |
| `memory/journal.sqlite3` | Accepted story memory, retained across days |
| `memory/runs/<id>/` | Exact processing input, retrieval diagnostics, model artifacts and dated story pages |
| `captures/<id>/manifest.json`, `captures/<id>/batches/*.json`, `captures/<id>/feeds/` | Frozen source inventory, processing inputs and raw feeds |
| `reports/<id>/report.json`, `reports/<id>/briefing.md` | One invocation's operational report and reader output |
| `reports/<id>/started.json`, `reports/<id>/attempts/` | Start intents and completed-attempt receipts, including evidence left by abrupt interruption |
| `index.md`, `latest.md` | Convenience entry points; use the dated reports for evidence |
| `feedback.md` | Created once, then edited by the reader; never replaced by a routine |

Use a fresh dogfood state initially. Do not import the original project's
database or mix experimental states into this journal.
Accepted journal rows determine completion. Missing final invocation receipts and
unfinished capture folders remain visible for review; prior unknown launches or
usage are not counted as zero. Recovery can continue the queue while retaining
these warnings. Dated briefing sections and their links retain each accepted run's
original observation date and as-known story view.

## Reader feedback

Add concrete examples to `.news/dogfood/feedback.md`. A useful entry is:

```text
Observed on:
Category: missing development | wrong merge | missed connection | unsupported | repetition
Severity: minor | material | blocking
Capture ID / run ID / report link:
Source URL(s):
What the briefing says or omits:
What the sources support instead, including any uncertainty:
```

Feedback is evidence to investigate, not a numeric accuracy score. Keep original
entries and link any later experiment or resolution instead of erasing a failure.

## Weekly experiment

The [weekly prompt](routines/weekly.md) creates a permanent isolated worktree,
tests one hypothesis, and compares baseline and candidate on identical frozen
inputs and prehistory. Its default ceiling is **24 news-model CLI invocations
total across all preparation, control and candidate runs**, each with a
360-second deadline. Coding and review-agent account usage is separate from this
news-processing budget and must not be represented as included in it.

An independent agent writes source-grounded questions and expected relationships
before seeing either arm's output, including baseline output. Reviews must cover
the visible dated narrative, missing developments and available context as well
as identity decisions. Preserve failures, unknown usage and unprocessed cases.
Source-supported long gaps, corrections, hard negatives and recovery deserve
coverage; do not invent an archive correction to fill a checklist.

The default result is a reviewed experiment commit and report. Promotion requires
independent correctness, simplicity and semantic review supporting that exact
change within the user's authorization. Passing tests or selected matching
counts alone cannot justify it. The daily routine continues to run the existing
application and writes only operational data and reports.
Integrate an approved code change between daily invocations, while holding the
same outer dogfood state lock; do not change application files during a run.
