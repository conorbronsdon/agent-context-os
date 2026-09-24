# Hermes live conformance attempts, 2026-09-23

These are the first installed-client runs of `adapters/hermes/live_conformance.py`
against a current Hermes Agent build. **No attempt passed all controls, so the
Hermes adapter stays experimental.** The files are kept as recorded, failures
included.

## Setup

- Client: Hermes Agent v0.21.4 (2026.9.21), upstream `d94769da`, installed from
  a fresh clone with its own virtual environment. Each attempt used a fresh
  `HERMES_HOME` and a newly prepared disposable fixture.
- Host: Windows 11, Git for Windows bash. Hermes's terminal tool disables MSYS
  path conversion, which broke every kernel call until the fix in #209; all
  attempts ran with that fix.
- Provider: OpenRouter zero-priced (`:free`) routes, tools enabled inside the
  fixture only. The OpenRouter key was supplied to the Hermes process through
  its environment and was never written into the fixture or a prompt. Nothing
  here verifies whether Hermes removes it from its terminal subprocesses, so a
  model with terminal access could have been able to read it.
- Operator: the orchestrating agent (Claude), acting on the maintainer's
  instruction to run conformance, using the file-based approval mode.

The recorded `model` field in attempts 1-4 is over-redacted
(`thinkingmachines[PATH]`, `[REDACTED]:free`). The harness now records route
identifiers verbatim. The exact routes, from the command lines, are listed
below.

Attempts 1-4 also predate joined redaction of streamed text. Their `text`
events were redacted one delta at a time, so they contain fragments of the
synthetic native-memory canaries. They contain no credentials. The harness now
redacts the joined text once and records it as a single event.

## Attempts

| File | Source commit | Model route | Controls passed | Recorded failure |
|---|---|---|---|---|
| [attempt-1.json](attempt-1.json) | `19b2775` | `thinkingmachines/inkling:free` | version | `self-read: discovery not shown` |
| [attempt-2.json](attempt-2.json) | `db1330d` | `thinkingmachines/inkling:free` | version | `canary not reported: agents, context-setup` |
| [attempt-3.json](attempt-3.json) | `96f9cff` | `thinkingmachines/inkling:free` | version | `self-read: discovery not shown` |
| [attempt-4.json](attempt-4.json) | `96f9cff` | `nvidia/nemotron-3-ultra-550b-a55b:free` | version, agents discovery\*, setup discovery\* | `approval file did not contain the exact proposal digest` (operator rejection) |
| [attempt-5.json](attempt-5.json) | `a2b7577` (fixture `8f67ea5`) | `nvidia/nemotron-3-ultra-550b-a55b:free` | version | `HarnessError: self-read: discovery not shown` |

\* Recorded as passed by a harness later found to allow false greens; see attempt 4 below.
Attempt 5 used the final harness in this PR.

What each failure means:

1. **Attempt 1.** In the setup turn, Hermes loaded `context-setup` through its
   own `skill_view` tool, and the model reported that skill's canary. It did
   not report the `AGENTS.md` canary. The harness then used one message for
   both "missing canary" and "self-read"; it now reports them separately.
2. **Attempt 2.** The model reported the correct `context-setup` canary, but the
   harness joined streaming text deltas with newlines, splitting it. This was
   a harness defect, fixed before attempt 3 (Hermes streams small `text` deltas
   followed by a final `result` event). The `AGENTS.md` canary was again not
   reported.
3. **Attempt 3.** The model opened `AGENTS.md` with `read_file` and grepped for
   the canaries, so discovery was correctly not credited. Its setup payload
   also targeted a path outside the approved context paths, and the kernel
   rejected it.
4. **Attempt 4.** The harness recorded both discovery controls as passed, and
   the model reported the `AGENTS.md` and `context-setup` canaries. **Do not
   treat this as discovery evidence.** An independent review later found
   false-green paths in the harness used for attempts 1-4. The manifest
   and uncommitted canary edits sat inside the fixture, where `cat`, `grep`,
   or `git diff` could reveal them. Self-reads were only detected by exact
   file names in three tools. Attempt 4's events include reads of two `.md`
   files whose names were redacted, so the record cannot rule out a
   self-read. The current harness closes these paths. The setup proposal was
   valid in form, but it copied both
   synthetic native-memory canaries from `HERMES_HOME/memories/` (`MEMORY.md`,
   `USER.md`) into `identity/professional-background.md`. It also wrote the
   fixture's absolute path into `identity/who-i-am.md`. The operator rejected
   it by supplying a non-matching approval; the recorded failure is that
   mismatch, and the reason is in [attempt-4-operator.md](attempt-4-operator.md). The harness now fails `memory_separation` when a proposal diff contains
   a native-memory canary, before approval is requested.
5. **Attempt 5**, on the final harness: the manifest was outside the fixture, the
   canaries were committed, self-reads were checked across all read-like tools
   and raw tool results, and the environment was filtered. Hermes loaded
   `context-setup` through `skill_view`. The model read ordinary repository
   files, which the evidence now names (`scripts/contextos.sh`,
   `contextos/kernel.py`, `ROUTING.md`, `TODO.md`). It created a setup
   proposal through the kernel after several payload corrections. Before
   answering, it ran `search_files` for the literal `Hermes fixture canary:`
   prefix. That is a self-read under the harness rules, so discovery was not
   credited and the run stopped there. The run also shows that the final
   harness processes real Hermes stream output: `skill_view` results, joined
   text deltas, readable relative paths, and names-only environment evidence.

## Findings that do not depend on the model

The first three points below come from separate diagnostic runs on the same
client before these attempts; they are not recorded in the attempt files.

- Hermes v0.21.4 reserves `/start` and `/update` for built-ins
  (`hermes skills list --source local`: "slash command /start unavailable —
  name taken by built-in; use /skill start"). The documented Hermes invocation
  is now `/context-setup`, `/context-start`, `/context-update`, and
  `/context-end`.
- A bare `/context-start` query resolves the repository skill through
  `skill_view` with no file named in the prompt.
- `AGENTS.md` is in the system context. Asked with no tools, the model quoted a
  marker appended to it.
- Hermes injects native memory into the model context. Keeping it out of
  repository state therefore depends on the proposal review and exact-digest
  apply, as the lifecycle design intends. Attempt 4 is a concrete case.

## What promotion still needs

A run in which every control passes: discovery for all four phases, read-only
start, operator-approved apply with receipts, wrong-digest and stale-target
rejection, the sentinel check, and memory separation. The free routes above did
not reach it.
A stronger model route through Hermes is the likely next step.
