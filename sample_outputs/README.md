# Sample Outputs

This directory is for polished artifacts that show the project's main idea: source-grounded story memory.

The current sample, [intelligence_brief.md](intelligence_brief.md), demonstrates:

- story arcs instead of isolated article summaries
- trend signals
- source counts
- reported timestamps
- "what changed today" deltas
- source links

It does not yet fully demonstrate the target Phase 3/4 output:

- source agreement
- evidence spans with source/article attribution
- confidence levels
- contradiction handling
- cost and latency metadata

One excellent sample output is more valuable than many generated artifacts. When the claim-hardening and observability work lands, update the sample to include:

```markdown
### Source agreement
...

### Open questions
...

### Evidence
- Source — Article title — `claim_type` — "evidence span" _(confidence)_

### Pipeline metadata
- Articles fetched:
- Claims extracted:
- Estimated cost:
- Total latency:
```
