# Shared experiment contract

Compare `single` (one structured decision per batch) with `staged` (first choose
verbatim evidence per article, then group and match events). Both use Codex exec,
gpt-6-astra, medium reasoning. This is a bounded comparison, not proof of general
news quality. Do not call the old API-backed code.

Input JSON to the grouping task:

```
{"day":"2026-10-01","articles":[{"id":"a1","source":"Example",
"url":"https://example.test/a1","published_at":"2026-10-01T12:00:00Z",
"title":"Example title","text":"Exact source text."}],
"memory":[{"id":"e1","title":"Prior event","last_seen":"2026-09-30",
"evidence":[{"article_id":"old1","source":"Example",
"quote":"Prior quoted source text."}]}]}
```

Grouping task output (no extra keys):

```
{"events":[{"title":"A concise event label","previous_event_id":null,
"article_ids":["a1"],"evidence":[{"article_id":"a1",
"quote":"Exact source text."}]}]}
```

Every input article must appear in exactly one event and have at least one
nonempty exact quote from its `text`. Quotes cannot cite titles unless that title
also appears in text. No unknown or duplicate article IDs; no unknown prior event
IDs; at most one current event per previous_event_id. An uncertain match starts
a new event. Group only the same real event or direct development, never a broad
topic. Quotes may disagree: report them side by side without inventing consensus.
No free-form factual prose other than the event label; render exact quotes and
source links deterministically. An event label is model interpretation, not a
verified claim. This modest contract deliberately avoids paraphrase verification.

Extraction output for the staged approach:

```
{"articles":[{"article_id":"a1","quotes":["Exact source text."]}]}
```

Validate extraction coverage and exact quotes against the original input before
the grouping call. The grouping task sees extracted evidence in article text.
Validate the final output against the original articles as well.

Shared transport contract: `news.codex.run_task(task: str, payload: dict,
artifact_dir: Path, *, timeout: float = 180, executable: str = "codex") -> dict`.
Task files are `news/tasks/{task}.md` and `{task}.schema.json`. Task names: `single`,
`extract`, `group`. Save prompt/input/schema/config/final/events/stderr/metadata
per call. Fail clearly on timeout, nonzero exit, schema mismatch or missing output.
No retry loop, caching, database changes, or strategy logic in the transport.
The caller gives a fresh directory for each call. Always use read-only sandbox,
no web search, no shell interpolation, no inherited personal MCP/plugin config.
The model should use only supplied evidence. Record actual usage and duration.

Strategy function in final app will call transport once (`single`) or twice
(`extract`, `group`); reject invalid evidence before persistence. Experiments use
isolated state and a common labeled corpus, not private live databases.
