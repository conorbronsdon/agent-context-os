# Continuity rerun for #206, 2026-09-26

This rerun tests the #206 guidance: write each lifecycle fact as one
self-contained sentence that names its subject. It uses the long synthetic
Atlas/Beacon scenario from [the September 23 trials](../continuity-long-2026-09-23/README.md),
from source commit `cb6f038`.

## Setup

- Profiles, all run on the same day with the same models:
  - `handoff`: the original compact note, with label prefixes and multi-fact
    sentences (700 characters).
  - `handoff-sentences`: the same facts rewritten to the new rule (771
    characters). It has per-profile expected quotes, and a test checks that
    every expected quote appears verbatim in the note.
  - `contextos`: canonical files plus older sessions (1,352 characters).
- Models and routes: `mimo-v2.5` and `minimax-m3` through OpenCode Go (a direct
  API call with no tools), and `thinkingmachines/inkling:free` through
  Hermes/OpenRouter with no tool events.
- Trials: 3 models × 3 profiles × 3 fresh sessions. Each response was recorded
  by `record`.
- Normalization: 6 of 27 responses arrived as valid JSON inside a Markdown
  fence. The fence was stripped before scoring ([log](fence-normalization.jsonl)).
  No stored `raw_response` contains a carriage return. No other edits were made.

The table below comes from
`python scripts/continuity-benchmark.py summarize --results docs/evidence/continuity-rerun-2026-09-26/trials.jsonl`.

| Model | Profile | Context chars | Trials | Mean correct | Value correct | Citation rejected | Retention | Safe uncertainty | Missed constraints | Format failures |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| mimo-v2.5 | contextos | 1352 | 3 | 9.00 | 10.00 | 1.00 | 7.00 | 2.00 | 0.00 | 0 |
| mimo-v2.5 | handoff | 700 | 3 | 9.33 | 10.00 | 0.67 | 7.33 | 2.00 | 0.00 | 0 |
| mimo-v2.5 | handoff-sentences | 771 | 3 | 9.33 | 10.00 | 0.67 | 7.33 | 2.00 | 0.00 | 0 |
| minimax-m3 | contextos | 1352 | 3 | 9.33 | 10.00 | 0.67 | 7.33 | 2.00 | 0.00 | 0 |
| minimax-m3 | handoff | 700 | 3 | 10.00 | 10.00 | 0.00 | 8.00 | 2.00 | 0.00 | 0 |
| minimax-m3 | handoff-sentences | 771 | 3 | 9.67 | 10.00 | 0.33 | 7.67 | 2.00 | 0.00 | 0 |
| thinkingmachines/inkling:free | contextos | 1352 | 3 | 10.00 | 10.00 | 0.00 | 8.00 | 2.00 | 0.00 | 0 |
| thinkingmachines/inkling:free | handoff | 700 | 3 | 10.00 | 10.00 | 0.00 | 8.00 | 2.00 | 0.00 | 0 |
| thinkingmachines/inkling:free | handoff-sentences | 771 | 3 | 9.67 | 10.00 | 0.33 | 7.67 | 2.00 | 0.00 | 0 |

Totals over nine trials per profile: every profile chose all 90 values
correctly. Citation rejections were 2/90 for `handoff`, 4/90 for
`handoff-sentences`, and 5/90 for `contextos`. There were no format failures
or missed constraints.

## Rejected answers

| Model | Profile | Trial | Question | Quote | Reason |
|---|---|---|---|---|---|
| mimo-v2.5 | handoff | 1 | atlas_delivery | `Use webhooks for event delivery.` | Label-prefix fragment (drops `Atlas:`) |
| mimo-v2.5 | handoff | 1 | beacon_cache | `Use SQLite for the local cache.` | Label-prefix fragment (drops `Beacon:`) |
| mimo-v2.5 | handoff-sentences | 1 | atlas_migration | `Atlas's staging migration was interrupted before execution.` | Cites the companion sentence, not the expected one |
| mimo-v2.5 | handoff-sentences | 1 | beacon_review | `Beacon's import review was interrupted after the draft.` | Cites the companion sentence, not the expected one |
| minimax-m3 | handoff-sentences | 2 | atlas_migration | `Atlas's staging migration has not been run.` | Paraphrase, not verbatim |
| thinkingmachines/inkling:free | handoff-sentences | 1 | beacon_review | `Beacon's import review was interrupted after the draft.` | Cites the companion sentence, not the expected one |
| mimo-v2.5 | contextos | 1 | atlas_cron_current | `For Atlas, webhooks replace the earlier cron polling plan.` | Fragment of a longer sentence |
| mimo-v2.5 | contextos | 3 | atlas_cron_current | `For Atlas, webhooks replace the earlier cron polling plan` | Fragment of a longer sentence |
| mimo-v2.5 | contextos | 3 | atlas_queue_current | `which had replaced queue delivery.` | Fragment of a longer sentence |
| minimax-m3 | contextos | 2 | atlas_cron_current | `Atlas: Use webhooks for event delivery.` | Different sentence; does not establish the replaced plan |
| minimax-m3 | contextos | 2 | atlas_queue_current | `Atlas: Use webhooks for event delivery.` | Different sentence; does not establish the replaced plan |

## Interpretation

- **The September 23 gap did not reproduce in this run.** On September 23 the
  original `handoff` note lost 16/90 answers on citations; here it lost 2/90,
  with the same prompt text and model routes. Nine trials per profile cannot
  say why. Run-to-run variation and provider-side model changes are both
  possible.
- **The rule removed the failure it targeted.** No `handoff-sentences` answer
  was rejected as a label-prefix fragment; both original `handoff` rejections
  were exactly that.
- **Splitting a compound status created a new citation problem.** The rewrite
  split two status facts across two sentences each. "Atlas's staging migration
  was interrupted before execution." plus "…has not run." together establish
  `not_run`. "Beacon's import review was interrupted after the draft." plus
  "…has not been approved." together establish `draft_only`. Neither sentence
  alone carries the whole answer. The companion citations were therefore
  partial, not correct answers wrongly rejected. The fixture's accepted
  `draft_only` quote ("has not been approved") is also partial, because it
  does not show that a draft existed. For status facts, "one fact per
  sentence" should keep a status and its qualifiers in one sentence, such as
  "Beacon's import review stopped after the draft, before approval."
- **Conclusion:** this run observed no reduction in total citation rejections
  (2/90 vs 4/90). It cannot estimate the rule's underlying effect. The
  guidance is kept because it removes label-prefix fragments. It is not
  presented as a demonstrated improvement.

Limits: one synthetic scenario, three models, three trials per model and
profile, one day. There were no token counts for the Hermes route.

Suggested follow-up: have the lifecycle guidance keep a status and its
qualifiers in one sentence, fix the `handoff-sentences` fixture so each
compound status is one sentence with a full-answer expected quote, and rerun
with more trials per profile.
