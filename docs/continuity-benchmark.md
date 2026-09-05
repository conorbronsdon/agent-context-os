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
containing that sentence. It deliberately does not grade arbitrary paraphrases.
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
