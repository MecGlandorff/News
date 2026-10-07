# C01 supplementary experiment — independent preflight

Reviewer: Astra / max. Assessed after the main campaign closed at 19 calls, before inspecting any supplementary model output. App commit remains `d3b63e2`. Read-only inspection; this reviewer made no model/network calls or application/state changes.

**GO for the separately frozen five-call supplement.** This does not revise the main campaign's result: its second baseline preparation failed structural validation and C01 remains unavailable there. This is an output-informed protocol amendment, not a fresh independent replication or evidence that the candidate causally repairs the original preparation failure.

`followup_campaign.py` imports the unchanged original worker with a separate output root. Its plan caps calls at five. The original 19-call ledger is itself frozen and checked by each worker, making the combined ceiling 24. The supplementary sequence is one candidate preparation (at most two calls), followed only on acceptance by the baseline/current and candidate/current arms (at most three calls). There is no retry loop or additional reserve. Failure or incomplete source coverage leaves the dependent comparison unavailable.

The copied preparation database contains the exact unchanged first accepted row `054f6e7af87043289bcdd6198aae6bcf` from April 27. I compared all six columns of that row with the original shared-prehistory journal, not just its ID. The original failed baseline proposal remains under `states/C01-shared-prior/runs/9036fef0ac284a8fab1fc458d110bea1/`. No manual story/event assignment is introduced.

Both current arms receive identical copies of any newly accepted preparation history. The original worker enforces all four designated prior cards, both current cards, and identical complete author payloads before spending current model calls. Sources and source-only labels are unchanged. This can provide a conditional check of 19-day continuity in the supplied matter with its competitor; it does not measure archive-wide retrieval, repeated-run stability, or months of organic history.

At preflight all 26 supplementary freeze hashes matched, including both code trees, original runner/plan and these supplementary files:

| File | SHA-256 |
| --- | --- |
| `followup_campaign.py` | `0c0adeebc930e45b6820587f125a621686563528616c319ccdd1536b7ad28bba` |
| `followup/plan.json` | `41459eefaaeedaf2c5f4cd987d6a00a75055abcda968ef2b9b84a90db1680c48` |
| Original `calls.json` | `2097aa799634baf8666cef74a2644b2d617b5c981b03408a61fc71c6da7b56cc` |

Keep this supplement separate in results. Report both preparation attempts and their costs. Do not replace the unavailable main-case result with a selected successful second attempt, alter labels after seeing outputs, or claim a model-only causal improvement from the different preparation pipeline.
