# Minimal starter: evidence and limits

Experiment date: 2026-09-04. One synthetic CSV project, one run per condition.

The simulation provides a limited reason to try the [experimental starter](minimal-starter.md)
for sequential work on one project. It does not establish a preferred file
layout. It also found a checkpoint error that led to a small instruction change. It does not establish time savings or show that
the full template's write controls are unnecessary.

## Method

The original trial completed seven inference calls: two checkpoints generated
by `grok-4.6` through OpenCode Go and five fresh Codex CLI resumptions.
Claude Code returned a session-limit error before inference, so it did not
count as a completed run. Codex CLI 0.153.0 used its default backend; the
captured events did not identify that model. The Go requests had no history;
Codex ran ephemeral sessions with user configuration, memory, discovery, hooks,
and plugins disabled for this experiment.

Models received explicit file contents and actual test results in the prompt.
They generated checkpoint text or proposed next actions. They did not edit code
or run tests. The fixture runner performed the edits and checks: two initial
tests passed, an added embedded-newline test failed against the old parser,
and the corrected parser passed all four tests. This known-bug control checked
that the evidence distinguished the broken and corrected implementations.

## Continuity observations

| Condition | Observed result |
|---|---|
| Fresh session with saved notes | Retained the approved policies and proposed the unfinished newline check. |
| Same code and tests without notes | Correctly treated two business policies as unknown and asked to clarify them. |
| Updated checkpoint | Preserved the prior constraints, recorded passing tests, and changed BOM support to explicitly out of scope. |
| Updated notes with an old handoff | Identified three discrepancies and stayed with the current documentation task. |
| BOM decision removed from both notes | Reported that policy as unknown while retaining the other recorded policy and current task. |

The loss case was compared with an intact second-checkpoint control. Only the
BOM decision text was removed; code, tests, other context, and the request
stayed the same. Missing decisions need a surviving source or user input.
Current implementation alone cannot establish an unrecorded approval.

## Date error and follow-up

The first checkpoint inserted `2026-03-21` even though no session date was
supplied. The second checkpoint carried it forward. Those outputs were left
unchanged throughout the original trial.

The starter now requires a session date supplied by the host, user, or a
checked clock. If none is available, it writes `unknown` rather than guessing
or inheriting a previous session's date. Both state templates expose that
choice in their date placeholders.

Three fresh calls to the same Grok route checked the revised instruction:

| Supplied evidence | Date in both generated files |
|---|---|
| No session date | `unknown` |
| Old dates in both notes, no verified current date | `unknown` |
| Old dates plus a verified session date | The supplied date, `2026-09-04` |

Only the AGENTS.md instruction changed in the two unknown-date checks. The
known-date check also supplied the verified date in the user request. These
are behavioral spot checks, not a guarantee that every model will follow the
rule. Review generated checkpoints for unsupported claims and dropped facts.

## Inspect the evidence

The [source JSON record](https://github.com/conorbronsdon/agent-context-os/blob/b23a55bc9d99d6edc936b2e8ae9ceb91414f2ac2/docs/evidence/minimal-starter-trial.json)
is tracked as development evidence and excluded from installed core files.
It contains the original
criteria, method amendments, frozen templates, parser fixture, exact model
inputs, outputs, and the three date follow-ups. Inputs are bound to their
call-time SHA-256 hashes. Parsed outputs have canonical JSON hashes, with the
serialization convention recorded in the file. Local paths, credentials, and
runtime logs are excluded. Earlier template text and incorrect dates in that
record are historical test inputs and outputs, not current instructions.

The criteria were set before the original calls. An intact second-checkpoint
control was added before the lost-decision condition, and the date checks
followed the observed error. The evidence includes successful and unsuccessful
behavior; the setup failure is recorded separately.

## What remains untested

This was a simulation using supplied snapshots. It did not test native file
discovery, autonomous coding, simultaneous writers, interrupted writes, or
long-term context decay. There was no full-template or AGENTS-only comparator.
BOM and duplicate-policy questions were explicit probes, and each condition
ran once. No human maintenance time or week-long retention was measured.

Keep the full template available for the needs this experiment did not cover.
Use the [one-week trial](minimal-starter.md#evaluate-it-for-one-week) to decide
whether the minimal loop earns its maintenance cost on your own project.
