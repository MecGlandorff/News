# Frozen source-only supplement

Pack: `fresh-source-integrity-20261007`, label version 1. Freeze completed UTC: 2026-10-07T21:19:12.337373+00:00.

This is a targeted three-case, 14-source supplement. It is not a random sample, a production quality rate, or a complete end-to-end long-history test. All labels were authored from archived source fields before any model output for this pack was inspected. The labeling agent must not inspect later model outputs. Root reviews the labels against the sources before constructing baseline/candidate requests.

## Files and hashes

- `sources.json`: SHA-256 `9a0b7f81291280716a1e02f83da03719983df7c2f7a6551728b60490a5d3f329`.
- `labels.json`: SHA-256 `4aa941c26aa8cb2236c4b43d86dd3d69fd0e3eb70773e0d23960c2da4442fe5e`.
- Selected archive: `/Users/mrgreen/Desktop/AI/News-worktrees/experiments/historical/.news/historical/source-archive.db`; SHA-256 `0cf6e2cd67b5edb578878403474a21c85fc6df0bde4267db7a7a77ce2294a610`.
- Input-definition code read for format: `/Users/mrgreen/Desktop/AI/News-worktrees/experiments/source-integrity-20261007/news/domain.py`; SHA-256 `29b28e5deeec7afd3df4a85f04972b667b8b5d55f984e9176eb459f1afd4a7dc` at extraction.

The source archive was opened only through SQLite URI `mode=ro`. Selected content came only from `article_occurrences`, selecting these fields: `occurrence_id, article_id, editorial_date, source, language, title, description, body_text, url, published_at, content_hash, retrieval_status, captured_at`. The source file path plus table and `occurrence_id` identifies each original record. `sources.json` embeds the exact raw values, raw-record hash, normalized article and normalized-article hash. Canonical record hashes use SHA-256 of UTF-8 JSON with sorted keys, no ASCII escaping, and separators `(',', ':')`.

| Source ID / occurrence_id | Archive editorial date | Publisher | Raw record SHA-256 |
| --- | --- | --- | --- |
| occ-3600 | 2026-04-27 | BBC News | `1f0a0a4268d07b30fe1e6c090b387e5eeaade2860328ee11ae448a825e6cb4e9` |
| occ-3602 | 2026-04-27 | The Guardian | `dc4cd2479eb394e92752af20d0ce76eb4a98864fb05ead9456b08ba7d8fe928b` |
| occ-4397 | 2026-04-29 | NOS | `a42dac891cc6e0e6242a422cf2caf4affac46d13e080a76c86553e68e7117025` |
| occ-4956 | 2026-04-29 | The Guardian | `83cd591181c8d5a4fad380646debf37a7885d7a953f168ed0a0fd993d169ccd4` |
| occ-12956 | 2026-05-18 | NOS | `35b761e9cc4f35219b8e8763d59cebe495b1eb67fa49e8b5c3d8733c384b6d70` |
| occ-12961 | 2026-05-18 | BBC News | `3589ab5feb27cc899d411e5f58bcc32b675e059397fe72988d2ef908f99f443f` |
| occ-3589 | 2026-04-27 | BBC News | `47d31f93081d7a05fee80f5e8f3b3ca19b509c6f5c786d6c4c54e249115a1efd` |
| occ-4125 | 2026-04-28 | Telegraaf | `cc784baa73154fd741847a80ce44e4982f9502344e74ba9f6b5b8f704a18e9a1` |
| occ-4902 | 2026-04-29 | NYT | `433cb22a9589d7b118251a685d64fe41f12f185a4e1f27006610515aa5049b78` |
| occ-4903 | 2026-04-29 | BBC News | `d0c9b1a87e27308490749f6c0feef324f64118b64d591d8c71f49c89ddf08864` |
| occ-5707 | 2026-04-30 | The Guardian | `ee8180bd46fd648d08057225a0b6a9ad9ad9862e793afacc0514ee468e481c31` |
| occ-17587 | 2026-07-22 | BBC News | `ca296d10fce5b527f89986e436d19c6f6a984acd55fb31c1243385fef98149a2` |
| occ-17589 | 2026-07-22 | BBC News | `540cf8347df97c8da00a4eb9f2682925e06cf163c7b3e2affeab4554c4bba11e` |
| occ-17590 | 2026-07-22 | BBC News | `00acad45367c360e245e3e64e0c70fa9eb37ad7991c13e01cd21f383a5f50a31` |

## Selection and fixed contexts

1. C01 uses April 27/29 prior sources and May 18 current sources about a named Musk/OpenAI lawsuit. The latest supplied same-matter prior article is 19 calendar days older, and the earliest is 21 days older. Separate OpenAI/Tumbler Ridge coverage is a plausible competing prior matter. Current NOS text, rather than a URL or title alone, establishes the connection to the older nonprofit-mission dispute.
2. C02 uses an April 27 prior inquiry-vote item and four source reports from April 28–30. The current batch deliberately spans three archive dates, retaining each source’s original timestamp. It tests whether the Mandelson parliamentary-inquiry matter remains separate from a Starmer-linked arson trial, with allegation and denial attribution preserved. It is not an exact replay of a single historical feed batch.
3. C03 uses three July 22 BBC RSS briefs. Concrete developments and important scope appear in their titles: most bus fares in England capped at £2 from January; four people charged over an alleged Southern Water test-manipulation plan; and an AI cyberattack claim attributed to OpenAI. Headline text stays separate from description text.

Exactly one bounded fixed-context request per case, per arm, can carry all sources. The pack requires at most three requests per arm, not one request per archived day. Cases contain these prior/current counts and normalized input sizes:

| Case | Prior versions | Current versions | All-source snapshot characters |
| --- | ---: | ---: | ---: |
| C01 | 4 | 2 | 9439 |
| C02 | 1 | 4 | 2699 |
| C03 | 0 | 3 | 1143 |

`current_source_ids` identifies the evaluated batch; `prior_source_ids` is source-only context. Do not include `labels.json` in prompts. Preserve identical source cards and ordering across arms and freeze any schema adapter’s actual requests separately before runs. No previous generated story summary or model decision was used as source context here. The pack intentionally supplies a relevant old matter and a competitor; it does not test whether a production retriever can discover them among every archived article.

## Evidence and scoring boundaries

Story relationships and event identity have separate labels. A continuing matter can contain several developments. Some exact event matches are ambiguous: notably two same-day arson-court snippets and the relation of an anticipated parliamentary vote to its outcome. These are explicitly unscored; they must not enter a hard-correctness denominator.

Reader questions include exact title/text evidence expectations and meaningful omissions. Evidence offsets are zero-based Python Unicode character intervals `[start,end)` in normalized `article.title` or `article.text`. If a fact occurs only in the title, a body-only evidence reference cannot support it. An alternative supplied source that states the fact in its text can support it. URLs are provenance, not factual evidence. Do not require every optional contextual detail in a short output.

No invented sources, conflict fixtures or correction fixtures are included. There are no explicit publisher correction notices. Party allegations and rebuttals are supported in C01/C02; these should not be mislabeled as publisher disagreement. The two NOS descriptions use different currencies for an approximate donation amount. The pack neither resolves that variation nor requires the amount, and does not call it an explicit correction.

## Limitations and source-only access record

- This is independently authored source-only labeling by a delegated agent, not human gold or independent verification that every archived report is true. The model is judged against the supplied evidence and its limits.
- The archive contains 17,618 occurrences spanning editorial dates April 18–July 22, with a gap after May 28. Selection was purposeful, using raw title/description searches for OpenAI/Anthropic/Kyndryl and Starmer/Charles, then July 22 BBC briefs. Broader source queries informed selection, not prior evaluation labels or outputs.
- All selected `body_text` fields are empty. The first eleven are marked `legacy_metadata_only`; the final three are `rss_only`. Some descriptions contain extensive publisher HTML, but they are not presented as newly retrieved complete articles. Raw HTML and normalized text are both retained. Formatting normalization strips tags/decodes entities, collapses in-line whitespace, preserves paragraph text and keeps `Continue reading...` boilerplate. Nothing is rewritten or truncated.
- Legacy rows were captured/backfilled on July 21 despite older publication/editorial dates. The simulated history gap is based on the source dates, not proof that this runtime had those rows in April/May. The final three were captured July 22.
- A real NRC occurrence 3953 with an unrelated-looking title/description and older timestamp was encountered during source selection and excluded. Its ambiguity would dominate this small scored pack. No gold was inferred from its URL or headline.
- No network fetches or news-model invocations were made. No generated stories, decisions, prior review reports, old evaluation labels, or model-cache values were read. `rg --files` surfaced names only. The legacy `/Users/mrgreen/Desktop/AI/News/data/stories.db` was inspected only for schema and raw-source count/date aggregates; selected record content came from the frozen archive above. SQLite table names/schema were viewed to locate raw source storage; no derived-table content was queried.
- No application/live-state changes, commit, push, or no-mistakes run occurred. Writes were confined to this evaluation directory plus a temporary labeling script. Production data was read-only.

Verification before freeze: all 14 raw records matched their read-only archive rows; raw and normalized hashes matched; all 48 evidence spans matched exactly; source membership, unique identifiers/URLs, timestamp presence, field sets and input size limits passed. No model outputs were used for verification.

After any output inspection, do not silently revise these files. A source-only correction before runs requires a new documented label version and new hashes. Later revisions must be treated as a new evaluation iteration rather than retroactively blind gold.
