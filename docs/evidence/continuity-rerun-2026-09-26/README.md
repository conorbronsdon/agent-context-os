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

- **The September 23 gap did not reproduce.** On that date, the original
  `handoff` note lost 16/90 answers on citations. Today it lost 2/90, with the
  same prompt text and model routes. That difference is larger than anything
  the profiles show today, so run-to-run variation (or provider-side model
  changes) dominates at this sample size.
- **The rule removed the failure it targeted.** No `handoff-sentences` answer
  was rejected as a label-prefix fragment; both original `handoff` rejections
  were exactly that.
- **The rewrite introduced a different ambiguity.** In the new note, some
  answers are supported by two sentences: "was interrupted before execution"
  and "has not run" both establish `not_run`. The fixture accepts only one
  quote per question, so correct citations of the companion sentence were
  rejected. This is a scorer and fixture limit, not model confusion.
- **Conclusion:** at nine trials per profile, this rerun shows no measurable
  drop in citation rejections from the rule. The guidance is still kept as
  writing hygiene, because it removes the label-prefix failure mode. It is not
  presented as a demonstrated improvement.

Limits: one synthetic scenario, three models, three trials per model and
profile, one day. There were no token counts for the Hermes route.

Suggested follow-up: let a question accept any sentence in the source that
establishes the answer, so correct companion citations are not rejected.
