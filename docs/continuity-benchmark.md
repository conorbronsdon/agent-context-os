# Measure constrained continuity

The offline benchmark prepares a synthetic Lantern project and scores four
decisions: remembered database choice, replaced export plan, rejected retries,
and an unresolved launch date. It tests observable answers with supporting
sentences, rather than asking another model for a subjective grade.

Run it from a **source checkout** of this repository with Python 3.10+. Selected
release bundles omit the development script and fixtures. If you installed a
bundle, clone the public repository into a separate disposable directory and
run these commands there; the benchmark never needs your personal workspace.

## Compare three context profiles

- `instructions`: a basic `AGENTS.md`, with no project facts. Correct behavior
  is to admit missing knowledge; this establishes unsupported-guess behavior.
- `handoff`: the same instructions plus a concise note containing **all four**
  relevant facts. This is a strong, information-equivalent baseline.
- `contextos`: the same instructions plus canonical decisions, blockers, current
  priorities, and an older session containing superseded ideas.

The separate revision scenario below has two supported profiles and an extended
response format. The original short and long prompts and historical scores
remain unchanged.

```bash
python scripts/continuity-benchmark.py prepare --profile handoff > handoff-prompt.txt
python scripts/continuity-benchmark.py prepare --profile contextos > contextos-prompt.txt
```

Submit each prompt to a fresh session of the same model with tools disabled.
Use only these synthetic prompts with free providers. Keep the answer key and
the rest of the checkout outside that session. Save the model's final JSON
answer, without reasoning or Markdown fences, as `response.json` outside the
checkout. Then score it:

```bash
python scripts/continuity-benchmark.py score --profile contextos --response /path/to/response.json
```

Exit 0 means all four answers are grounded and correct; 1 means at least one
failed; 2 means the response could not be scored. A correct choice without the
required supporting sentence fails. The scorer accepts a longer verbatim quote
containing that sentence, up to the whole cited source, so check recorded
quote lengths before treating grounding as precise citation. It deliberately
does not grade arbitrary paraphrases.
Wrong decisions, invented certainty, unsupported guesses, and missing question
IDs have negative controls in the tests.

## Record useful evidence

Record the source commit, exact model/provider, profile, fresh-session ID,
prompt hash, final response, score, latency, and provider-reported token counts
when available. Run all three profiles and repeat with fresh sessions before
claiming a reliable difference. Do not equate reported zero cost with verified
account billing, or a successful model call with a successful score.

`grounded_correct` rewards appropriate uncertainty in the instructions-only
baseline. `known_decisions_retained` separately counts the three resolved
decisions: that baseline cannot retain information it was never given. Context
characters expose the extra input burden; they are not tokenizer measurements.

These four constrained decisions are a regression experiment, not a general
semantic-quality benchmark. They do not execute setup/proposal/apply, prove
host discovery, measure human onboarding time, or establish product superiority.
The [first-handoff exercise](first-handoff.md) covers the user workflow and the
adapter conformance suites cover runtime behavior. If a concise handoff note
performs equally well, report that result and evaluate whether reviewability,
history, and ongoing maintenance justify the added context.

## Longer sequence

`--scenario long` selects a second, synthetic fixture with six sessions and ten
questions. Atlas changes its delivery decision from queue to cron to webhooks.
Beacon has a separate cache decision. Both projects have unresolved items and
interrupted work, and their export rules for customer IDs conflict. The
questions identify retained and replaced decisions, unresolved assumptions,
interrupted status, and cross-project constraints. The original four-question
scenario remains the default.

The four profiles use the same questions and model. `handoff` includes every
answerable fact in one note. `contextos` includes canonical files and older
sessions with superseded proposals. `instructions` contains no project facts.
Each score reports `context_characters`, the sum of selected source lengths;
these are character counts, not measured input tokens. Use a fresh session per
trial, disable tools, keep the model and available facts fixed, and repeat each
profile. The instructions baseline tests safe uncertainty, not retention.

The long-only `handoff-sentences` profile rewrites the compact `HANDOFF.md`
with one self-contained sentence per fact, naming its subject without label
prefixes. Statuses now keep their qualifiers in one sentence (#218).
It preserves the handoff facts and `AGENTS.md` instructions for the
#206 rerun. Its fixture overrides only the expected citation source and quote;
answer values and the grounding rule stay the same. The original three
profiles remain unchanged so the September 23 evidence can still be rescored.

```bash
python scripts/continuity-benchmark.py prepare --scenario long --profile handoff > handoff-prompt.txt
python scripts/continuity-benchmark.py prepare --scenario long --profile handoff-sentences > handoff-sentences-prompt.txt
python scripts/continuity-benchmark.py prepare --scenario long --profile contextos > contextos-prompt.txt
python scripts/continuity-benchmark.py score --scenario long --profile contextos --response response.json
```

The [September 26 rerun](evidence/continuity-rerun-2026-09-26/README.md) compares the three
informed profiles on the same day. It observed no reduction in citation
rejections from the self-contained-sentence rule.
After statuses were kept whole (#218), a [15-trial rerun](evidence/continuity-rerun-218-2026-09-26/README.md)
observed 0/150 citation rejections for the rule-following note, against 12/150 for the original.

`score` reports grounded correctness, retention among the eight resolved
questions, correct handling of replaced decisions (`corrections`), safe
uncertainty, missed cross-project constraints, invented
certainty on unresolved items, and format failure. An unparseable response or
missing question ID is a format failure with no correctness score. A wrong but
parseable answer is scored normally. Exact supporting sentences are required.
It also reports `value_correct`, which checks only the expected answer value,
and `citation_rejected`, which counts correct values that fail grounding. For
the instructions-only profile, the expected value is `unknown`.

Record each raw response, including failures, in a JSONL file. Supply the
provider's exact model identifier, trial index, measured latency, and token
counts when the provider reports them. Omit token flags when unavailable.
`record` appends one line containing the scenario, profile, model/provider,
trial index, SHA-256 of the prompt string, verbatim response text, score,
latency, and nullable input/output token counts. The prompt hash excludes the
trailing newline printed by the command-line `prepare` action.

```bash
python scripts/continuity-benchmark.py record --scenario long --profile contextos --response response.json --results trials.jsonl --model MODEL_ID --provider PROVIDER --trial 1 --latency 2.4 --input-tokens 900 --output-tokens 120
python scripts/continuity-benchmark.py summarize --results trials.jsonl
```

The Markdown summary groups by model and profile and shows context characters.
Grounded correct, value correct, citation rejected, retention, safe uncertainty,
and missed constraints are mean counts
per parseable trial. Format failures remain in the trial count and have a
separate count. Preserve the JSONL and fixture commit with any published
results. Compare the compact note
against the canonical files on the same model and fresh trials, then name a
product change supported by the observations. Volunteer first-handoff
observation belongs in a separate follow-up; these automated cases do not
measure it. Installed-host conformance remains a separate test suite.

The [2026-09-23 long-sequence evidence](evidence/continuity-long-2026-09-23/README.md)
reports 27 fresh-session trials, category counts, rejected answers, and limits.

## Test revision attribution and proposed actions

The `revision` scenario tests two questions with synthetic retrieval records.
An old record and its reviewed replacement both select CSV, so returning CSV
alone cannot establish that invalidation worked. A second question keeps a
launch date unconfirmed and requires holding the launch announcement.

```bash
python scripts/continuity-benchmark.py prepare --scenario revision --profile contextos
python scripts/continuity-benchmark.py prepare --scenario revision --profile handoff
python scripts/continuity-benchmark.py score --scenario revision --profile contextos --response response.json
```

Each profile receives the same facts and current retrieval records; `handoff`
uses the concise handoff source. Use fresh sessions with tools disabled and
keep the answer key outside them, as with the other scenarios. The extended
answer contains `value`, `source`, `quote`, `record_id`, `source_revision`,
`supersedes`, `dependency_check`, and `action`. The prompt supplies an
unordered list of retrieval records with source revisions, supersession links
and dependency-check results; it is not keyed by question. In `contextos`, the
list also contains the superseded session records, whose own checks still
match, so copying a record passes only when the agent selects the current one.
Actions are proposed codes, never executed operations.

The scorer reports each layer independently:

| Layer | Passing evidence |
|---|---|
| Retrieved record | Correct current record ID, superseded ID and supplied dependency-check result |
| Cited revision | Current source path, full normalized-text SHA-256 and supporting sentence |
| Proposed value | Correct CSV choice or unresolved launch status |
| Outbound action | Outline CSV columns locally or hold the public announcement |

All four layers must pass for a question to count as grounded correct. A
correct value with a stale citation, missing supersession link, false check
result, or publishing proposal fails. Citation rejection is counted separately
from record and action failures.

`record --scenario revision` preserves raw responses and layer scores in JSONL.
`summarize` returns mean passing-question counts for each layer and the count
of format failures. Keep revision results in a separate JSONL from the legacy
scenarios. `instructions` and `handoff-sentences` are unsupported for this case.

The [2026-10-04 revision trials](evidence/continuity-revision-2026-10-04/README.md)
ran three models through Codex and Cursor. All 18 trials passed every layer,
so this version does not separate those models; a harder case is needed.

This is a response-format and attribution evaluation over supplied synthetic
evidence. It does not observe a host's retrieval, execute a dependency graph,
authenticate the reviewer, or send an outbound action. Unit controls validate
the scorer; they are not model trials or evidence of live stale-memory repair.
For actual selected-file checks, use [source revision expectations](continuity.md).
The remaining design recommendations are in the [feedback review](feedback-review-2026-10-04.md).
