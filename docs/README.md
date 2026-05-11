# Documentation

This documentation explains the project as a source-grounded event-memory system. It is written for future builders who need to understand the actual flow, the trust boundaries, and the places where the current prototype is still weak.

Only the documents linked from this page are part of the maintained project documentation map.

## Start Here

- [How the project works](how-it-works.md) - end-to-end code-path audit from RSS feed to briefing, PDF, and run report.
- [Database guide](database-guide.md) - practical guide for reading `data/stories.db` with SQLite queries.
- [Architecture](architecture.md) - system shape, memory model, schema reference, and next architectural work.
- [Model behavior](model-behavior.md) - every LLM call, what it may decide, structured output contracts, and failure boundaries.

## Trust And Quality

- [Failure modes](failure-modes.md) - known ways the system can be wrong, how to detect them, and what mitigates them today.
- [Evaluation plan](evaluation.md) - planned and current eval harnesses for story matching, claims, evidence, temporal deltas, and briefing quality.
- [Evaluation harnesses](../evals/README.md) - runnable eval commands, starting with RSS-vs-full-text claim quality.
- [Improvement checklist](improvement-checklist.md) - practical hardening backlog for observability, full-text claims, source agreement, source divergence, and evals.

## Engineering Practice

- [Coding standard](coding-standard.md) - how code should preserve visible pipeline boundaries and source grounding.
- [Communication standard](communication.md) - how docs should explain current behavior, weakness, next steps, and done criteria.
- [Architecture decision records](adr/) - decision history for non-obvious tradeoffs.

## Generated Artifacts

- [Briefing archive](../briefings/)
- [Newspaper archive](../newspapers/)
- [Curated sample output](../sample_outputs/intelligence_brief.md)

Generated outputs are useful examples, but the source of truth for implementation behavior is the code and the docs above.

## Reading Order

1. Read [README.md](../README.md) for the project promise and commands.
2. Read [How the project works](how-it-works.md) to understand the full runtime flow.
3. Read [Database guide](database-guide.md) while inspecting `data/stories.db`.
4. Read [Model behavior](model-behavior.md) before changing prompts, model choices, cache keys, or confidence behavior.
5. Read [Failure modes](failure-modes.md) and [Evaluation plan](evaluation.md) before adding more expensive or autonomous AI behavior.
