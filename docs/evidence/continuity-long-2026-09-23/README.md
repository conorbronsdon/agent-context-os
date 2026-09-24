# Long-sequence continuity trials, 2026-09-23

These 27 trials use the synthetic six-session Atlas and Beacon fixture from
source commit `7accaaccdf5e041c945234d1a01b3963727680cc`. The orchestrator
reported running them on 2026-09-23. Individual call times and session IDs are
not in the records. Each of three models received each of three profiles in
three fresh sessions, using `--scenario long` and the same ten questions. The
profiles supplied instructions only (210 source characters), a compact handoff
note (700), or Context OS state and history (1,352). The prompt hashes are
constant within each profile across all nine calls.

`mimo-v2.5` and `minimax-m3` ran through OpenCode Go (`opencode-go` in the
records), by direct API with no tools. `thinkingmachines/inkling:free` ran
through Hermes and OpenRouter (`openrouter` in the records); the orchestrator
observed no tool events. The JSONL records establish the model IDs, providers,
prompts, responses, and scores. They do not independently establish tool or
session isolation. Provider token counts are present for both OpenCode Go
models and absent for the Hermes route. Source characters are not token counts.

The [trial records](trials.jsonl) retain all responses and original scores.
The [normalization log](fence-normalization.jsonl) marks nine responses that
arrived as valid JSON inside a Markdown `json` fence. The documented procedure
requires final JSON without fences, so the orchestrator removed those fences
before `record`; the stored `raw_response` is the unfenced body. Line endings
were normalized to LF and trailing carriage returns removed; no stored
`raw_response` contains a carriage return. An earlier copy of these records
still carried CRLF because the response files were rewritten with Windows
newline translation. The records were re-recorded from the same responses and
the orchestrator saw every score unchanged, but neither the original fenced
responses nor the earlier copy is preserved here, so that comparison cannot be
rechecked from these files.

Prompts are stored as hashes, not text. Each `prompt_sha256` is the SHA-256 of
the UTF-8 string returned by `prepare(scenario, profile)` for the long scenario.
The orchestrator recomputed all three hashes from this fixture and they match;
`summarize` does not recheck them for these records, because it only rescores
records that lack `value_correct`. The prompt files actually sent were the
Windows standard output of `prepare`, so they used CRLF line endings and a
trailing newline. The hash identifies the prompt text, not those exact bytes.

## Scores

The current scorer separates a correct answer value from its citation.
`value_correct` compares the value with the profile's expected value:
`unknown` for instructions only, or the fixture answer for the two informed
profiles. `citation_rejected` counts a correct value that fails the existing
grounding rule. `Mean correct` remains the original `grounded_correct` score;
the other original metrics are unchanged. Means below are per parseable trial.
The table was regenerated from stored `raw_response` values by
`python scripts/continuity-benchmark.py summarize --results docs/evidence/continuity-long-2026-09-23/trials.jsonl`.

| Model | Profile | Context chars | Trials | Mean correct | Value correct | Citation rejected | Retention | Safe uncertainty | Missed constraints | Format failures |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| mimo-v2.5 | contextos | 1352 | 3 | 9.33 | 10.00 | 0.67 | 7.33 | 2.00 | 0.00 | 0 |
| mimo-v2.5 | handoff | 700 | 3 | 6.67 | 10.00 | 3.33 | 4.67 | 2.00 | 0.00 | 0 |
| mimo-v2.5 | instructions | 210 | 3 | 6.67 | 10.00 | 3.33 | 0.00 | 6.67 | 0.00 | 0 |
| minimax-m3 | contextos | 1352 | 3 | 10.00 | 10.00 | 0.00 | 8.00 | 2.00 | 0.00 | 0 |
| minimax-m3 | handoff | 700 | 3 | 8.67 | 10.00 | 1.33 | 6.67 | 2.00 | 0.00 | 0 |
| minimax-m3 | instructions | 210 | 3 | 10.00 | 10.00 | 0.00 | 0.00 | 10.00 | 0.00 | 0 |
| thinkingmachines/inkling:free | contextos | 1352 | 3 | 10.00 | 10.00 | 0.00 | 8.00 | 2.00 | 0.00 | 0 |
| thinkingmachines/inkling:free | handoff | 700 | 3 | 9.33 | 10.00 | 0.67 | 7.33 | 2.00 | 0.00 | 0 |
| thinkingmachines/inkling:free | instructions | 210 | 3 | 10.00 | 10.00 | 0.00 | 0.00 | 10.00 | 0.00 | 0 |

Across the nine informed-profile trials per profile, all 90 handoff values
and all 90 Context OS values matched the expected answers. Handoff had 74/90
grounded answers and 16 citation rejections; Context OS had 88/90 grounded
answers and two citation rejections. Instructions-only gave `unknown` on all
90 answers, with 80 grounded responses and ten rejected citations in one
`mimo-v2.5` trial. It provides no project decisions to retain. No response
had a format failure, a wrong value, or a missed cross-project constraint.

Each category has two questions, or 18 answers per profile across nine trials.
The entries below are `value correct / grounded correct / citation rejected`.

| Category | Instructions | Handoff | Context OS |
|---|---:|---:|---:|
| Retained decision | 18 / 16 / 2 | 18 / 10 / 8 | 18 / 18 / 0 |
| Replaced decision | 18 / 16 / 2 | 18 / 12 / 6 | 18 / 16 / 2 |
| Unresolved | 18 / 16 / 2 | 18 / 18 / 0 | 18 / 18 / 0 |
| Interrupted status | 18 / 16 / 2 | 18 / 16 / 2 | 18 / 18 / 0 |
| Cross-project constraint | 18 / 16 / 2 | 18 / 18 / 0 | 18 / 18 / 0 |

## Rejected answers

Each row is one rejected answer. Trial names combine the recorded model,
profile, and trial index. Every listed value is correct. A fragment is present
in the source but omits part of the required supporting sentence. A different
sentence is present in the source but does not establish the specific replaced
decision. The instructions-only citation is irrelevant to an `unknown` answer;
that profile requires a null source and empty quote. Quotes below are the
model's exact `quote` fields.

| Trial | Question | Value | Quote | Reason |
|---|---|---|---|---|
| mimo-v2.5 handoff 1 | atlas_delivery | webhooks | `Use webhooks for event delivery.` | Fragment omits `Atlas:`. |
| mimo-v2.5 handoff 1 | beacon_cache | sqlite | `Use SQLite for the local cache.` | Fragment omits `Beacon:`. |
| mimo-v2.5 handoff 2 | atlas_delivery | webhooks | `Use webhooks for event delivery.` | Fragment omits `Atlas:`. |
| mimo-v2.5 handoff 2 | beacon_cache | sqlite | `Use SQLite for the local cache.` | Fragment omits `Beacon:`. |
| mimo-v2.5 handoff 3 | atlas_delivery | webhooks | `Use webhooks for event delivery.` | Fragment omits `Atlas:`. |
| mimo-v2.5 handoff 3 | beacon_cache | sqlite | `Use SQLite for the local cache.` | Fragment omits `Beacon:`. |
| mimo-v2.5 handoff 3 | atlas_cron_current | no | `webhooks replace the earlier cron polling plan` | Fragment of the replacement sentence. |
| mimo-v2.5 handoff 3 | atlas_queue_current | no | `which had replaced queue delivery` | Fragment of the replacement sentence. |
| mimo-v2.5 handoff 3 | atlas_migration | not_run | `it has not run.` | Fragment of the migration sentence. |
| mimo-v2.5 handoff 3 | beacon_review | draft_only | `interrupted after the draft, before approval.` | Fragment of the review sentence. |
| minimax-m3 handoff 1 | atlas_cron_current | no | `Atlas: Use webhooks for event delivery.` | Different sentence; does not establish that cron was replaced. |
| minimax-m3 handoff 1 | atlas_queue_current | no | `Atlas: Use webhooks for event delivery.` | Different sentence; does not establish that queue was replaced. |
| minimax-m3 handoff 2 | atlas_cron_current | no | `webhooks replace the earlier cron polling plan, which had replaced queue delivery.` | Fragment omits `For Atlas,`. |
| minimax-m3 handoff 2 | atlas_queue_current | no | `webhooks replace the earlier cron polling plan, which had replaced queue delivery.` | Fragment omits `For Atlas,`. |
| thinkingmachines/inkling:free handoff 3 | atlas_delivery | webhooks | `Use webhooks for event delivery.` | Fragment omits `Atlas:`. |
| thinkingmachines/inkling:free handoff 3 | beacon_cache | sqlite | `Use SQLite for the local cache.` | Fragment omits `Beacon:`. |
| mimo-v2.5 contextos 2 | atlas_cron_current | no | `Atlas: Use webhooks for event delivery.` | Different sentence; does not establish that cron was replaced. |
| mimo-v2.5 contextos 2 | atlas_queue_current | no | `Atlas: Use webhooks for event delivery.` | Different sentence; does not establish that queue was replaced. |
| mimo-v2.5 instructions 2 | atlas_delivery | unknown | `Use the latest explicit project decision. Keep unresolved assumptions unresolved. Report interrupted work as recorded.` | Irrelevant AGENTS.md guidance cited instead of null source and empty quote. |
| mimo-v2.5 instructions 2 | beacon_cache | unknown | `Use the latest explicit project decision. Keep unresolved assumptions unresolved. Report interrupted work as recorded.` | Irrelevant AGENTS.md guidance cited instead of null source and empty quote. |
| mimo-v2.5 instructions 2 | atlas_cron_current | unknown | `Use the latest explicit project decision. Keep unresolved assumptions unresolved. Report interrupted work as recorded.` | Irrelevant AGENTS.md guidance cited instead of null source and empty quote. |
| mimo-v2.5 instructions 2 | atlas_queue_current | unknown | `Use the latest explicit project decision. Keep unresolved assumptions unresolved. Report interrupted work as recorded.` | Irrelevant AGENTS.md guidance cited instead of null source and empty quote. |
| mimo-v2.5 instructions 2 | atlas_release | unknown | `Use the latest explicit project decision. Keep unresolved assumptions unresolved. Report interrupted work as recorded.` | Irrelevant AGENTS.md guidance cited instead of null source and empty quote. |
| mimo-v2.5 instructions 2 | beacon_quota | unknown | `Use the latest explicit project decision. Keep unresolved assumptions unresolved. Report interrupted work as recorded.` | Irrelevant AGENTS.md guidance cited instead of null source and empty quote. |
| mimo-v2.5 instructions 2 | atlas_migration | unknown | `Use the latest explicit project decision. Keep unresolved assumptions unresolved. Report interrupted work as recorded.` | Irrelevant AGENTS.md guidance cited instead of null source and empty quote. |
| mimo-v2.5 instructions 2 | beacon_review | unknown | `Use the latest explicit project decision. Keep unresolved assumptions unresolved. Report interrupted work as recorded.` | Irrelevant AGENTS.md guidance cited instead of null source and empty quote. |
| mimo-v2.5 instructions 2 | atlas_ids | unknown | `Use the latest explicit project decision. Keep unresolved assumptions unresolved. Report interrupted work as recorded.` | Irrelevant AGENTS.md guidance cited instead of null source and empty quote. |
| mimo-v2.5 instructions 2 | beacon_ids | unknown | `Use the latest explicit project decision. Keep unresolved assumptions unresolved. Report interrupted work as recorded.` | Irrelevant AGENTS.md guidance cited instead of null source and empty quote. |

## Interpretation and follow-up

The compact note performed equally well on answer values in these trials. It
performed worse on citable grounding. Its `Atlas:` and `Beacon:` prefixes form
part of the required sentence, and its replacement sentence packs cron and
queue history together. Several models quoted a useful clause instead of the
full sentence. Two handoff rejections and two Context OS rejections instead
cited the current webhooks sentence for a question about an earlier decision.
Those cases show a separate citation-selection error, so changing sentence
shape alone is not guaranteed to remove every rejection.

The handoff note is information-equivalent for these ten questions: each
expected supporting sentence appears in it. It is not equivalent to the full
fixture history. It omits superseded proposals and details kept in the older
session files. These trials also do not isolate sentence shape as the cause
of the citation gap, because the two informed profiles differ in more than
sentence shape.

The grounding rule accepts any quote that contains the required sentence and
appears in the cited source, so a quote of an entire source document would
pass. No trial here did that; the longest recorded quote is 118 characters.

The supported product follow-up is to have lifecycle-written state and handoff
entries use one self-contained sentence per fact, naming its subject in that
sentence. Avoid label prefixes that can be dropped from a quote and sentences
that combine separate facts. The [end payload template](../../templates/end-payload.json)
and [update payload template](../../templates/update-payload.json) each show one
factual string per array item, but neither asks for a self-contained sentence
with its subject. The [starter handoff](../../../starter/handoff.md) groups
changes and next actions by section without sentence-level guidance. The
[end skill](../../../.agents/skills/context-end/SKILL.md) asks for approved
factual strings, decisions, and next actions; the
[update skill](../../../.agents/skills/context-update/SKILL.md) asks for one to
three factual progress strings. Neither skill requires one named fact per
sentence. These files do not explicitly encourage multi-fact sentences, but
they leave room for them. This report recommends the template and instruction
change; it does not implement it.

This is one synthetic scenario, three models, and three trials per model and
profile. There was no human observation, no measure of actual lifecycle use,
and no token counts for the Hermes route. These results support a narrow
comparison of constrained answer values and exact citations, not a general
claim about handoff quality, cost, or model reliability.
