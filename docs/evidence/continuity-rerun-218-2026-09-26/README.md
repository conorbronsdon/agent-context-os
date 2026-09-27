# Continuity rerun for #218, 2026-09-26

This rerun follows [the #206 rerun](../continuity-rerun-2026-09-26/README.md).
That run found the `handoff-sentences` note split two compound statuses across
two sentences each, so no single sentence established the answer. The fixture
now keeps each status with its qualifiers in one sentence ("Atlas's staging
migration was interrupted before execution and has not run."; "Beacon's import
review was interrupted after the draft, before approval."). The lifecycle
skills give the same guidance. Source commit: `3818981`.

## Setup

- Profiles: `handoff` (the original compact note, 700 characters),
  `handoff-sentences` (the fixed rule-following note, 719 characters), and
  `contextos` (1,352 characters).
- Models and routes: `mimo-v2.5` and `minimax-m3` through OpenCode Go (a direct
  API call with no tools), and `thinkingmachines/inkling:free` through
  Hermes/OpenRouter with no tool events.
- Trials: 3 models × 3 profiles × 5 fresh sessions, all on one day. Each
  response was recorded by `record`.
- Normalization: 13 of 45 responses were valid JSON inside a Markdown fence.
  The fence was stripped before scoring ([log](fence-normalization.jsonl)). No
  stored `raw_response` contains a carriage return. No other edits were made.

The table below comes from
`python scripts/continuity-benchmark.py summarize --results docs/evidence/continuity-rerun-218-2026-09-26/trials.jsonl`.

| Model | Profile | Context chars | Trials | Mean correct | Value correct | Citation rejected | Retention | Safe uncertainty | Missed constraints | Format failures |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| mimo-v2.5 | contextos | 1352 | 5 | 9.60 | 10.00 | 0.40 | 7.60 | 2.00 | 0.00 | 0 |
| mimo-v2.5 | handoff | 700 | 5 | 8.40 | 10.00 | 1.60 | 6.40 | 2.00 | 0.00 | 0 |
| mimo-v2.5 | handoff-sentences | 719 | 5 | 10.00 | 10.00 | 0.00 | 8.00 | 2.00 | 0.00 | 0 |
| minimax-m3 | contextos | 1352 | 5 | 10.00 | 10.00 | 0.00 | 8.00 | 2.00 | 0.00 | 0 |
| minimax-m3 | handoff | 700 | 5 | 9.60 | 10.00 | 0.40 | 7.60 | 2.00 | 0.00 | 0 |
| minimax-m3 | handoff-sentences | 719 | 5 | 10.00 | 10.00 | 0.00 | 8.00 | 2.00 | 0.00 | 0 |
| thinkingmachines/inkling:free | contextos | 1352 | 5 | 10.00 | 10.00 | 0.00 | 8.00 | 2.00 | 0.00 | 0 |
| thinkingmachines/inkling:free | handoff | 700 | 5 | 9.60 | 10.00 | 0.40 | 7.60 | 2.00 | 0.00 | 0 |
| thinkingmachines/inkling:free | handoff-sentences | 719 | 5 | 10.00 | 10.00 | 0.00 | 8.00 | 2.00 | 0.00 | 0 |

Totals over 15 trials per profile: every profile chose all 150 values
correctly. Citation rejections were **12/150 for `handoff`**, **0/150 for
`handoff-sentences`**, and **2/150 for `contextos`**. There were no format
failures or missed constraints.

## Rejected answers

| Model | Profile | Trial | Question | Quote (truncated) | Reason |
|---|---|---|---|---|---|
| mimo-v2.5 | handoff | 1 | atlas_delivery | `Use webhooks for event delivery.` | Label-prefix fragment (drops `Atlas:`) |
| mimo-v2.5 | handoff | 1 | beacon_cache | `Use SQLite for the local cache.` | Label-prefix fragment (drops `Beacon:`) |
| mimo-v2.5 | handoff | 1 | atlas_cron_current | `webhooks replace the earlier cron polling plan` | Fragment of a multi-fact sentence |
| mimo-v2.5 | handoff | 1 | atlas_queue_current | `webhooks replace the earlier cron polling plan, which had replaced que…` | Fragment (drops `For Atlas,`) |
| mimo-v2.5 | handoff | 2 | atlas_delivery | `Use webhooks for event delivery. For Atlas, …` | Span starts mid-sentence (drops `Atlas:`) |
| mimo-v2.5 | handoff | 2 | beacon_cache | `Use SQLite for the local cache.` | Label-prefix fragment |
| mimo-v2.5 | handoff | 5 | atlas_cron_current | `For Atlas, webhooks replace the earlier cron polling plan.` | Fragment of a multi-fact sentence |
| mimo-v2.5 | handoff | 5 | atlas_queue_current | `webhooks replace the earlier cron polling plan, which had replaced que…` | Fragment (drops `For Atlas,`) |
| minimax-m3 | handoff | 3 | atlas_cron_current | `Atlas: Use webhooks for event delivery.` | Different sentence; does not establish the replaced plan |
| minimax-m3 | handoff | 3 | atlas_queue_current | `Atlas: Use webhooks for event delivery.` | Different sentence; does not establish the replaced plan |
| thinkingmachines/inkling:free | handoff | 2 | atlas_delivery | `Use webhooks for event delivery. For Atlas, …` | Span starts mid-sentence (drops `Atlas:`) |
| thinkingmachines/inkling:free | handoff | 2 | beacon_cache | `Use SQLite for the local cache.` | Label-prefix fragment |
| mimo-v2.5 | contextos | 1 | atlas_cron_current | `Atlas: Use webhooks for event delivery.` | Different sentence; does not establish the replaced plan |
| mimo-v2.5 | contextos | 1 | atlas_queue_current | `Atlas: Use webhooks for event delivery.` | Different sentence; does not establish the replaced plan |

## Interpretation

- **With statuses kept whole, the rule-following note had no citation
  rejections: 0/150, against 12/150 for the original note.** Ten of the
  original note's twelve came from label prefixes or multi-fact sentences, the
  form the rule removes. The other two cite the current decision for a question
  about a replaced one.
- **The effect is consistent across models:** each model had equal or fewer
  rejections with `handoff-sentences` than with `handoff`.
- **Compared with the #206 rerun:** there, the rule-following note had 4/90
  rejections, all caused by split statuses or a paraphrase. Keeping each status
  in one sentence removed that failure mode in this run.
- **Limits:** one synthetic scenario, three models, five trials per model and
  profile, one day. The September 23 and September 26 runs of the original note
  (16/90 and 2/90) show large run-to-run variation, so 12/150 against 0/150 is
  directional evidence, not a precise effect size. There were no token counts
  for the Hermes route.
