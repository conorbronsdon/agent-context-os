# Devin CLI native Windows evidence

Synthetic fixtures only. All runs used Devin CLI `3000.11.3 (9c803229faa4)` and
the source commits named below. Windows runs: Windows 11 (`10.0.26200`), started from
PowerShell, in the harnesses' `--windows-real-profile` mode. Artifacts keep
controls, observations, booleans, hashes and synthetic prompts. They exclude raw
responses, absolute local paths and credentials.

## Passed

- [host-1f9bf5d.json](host-1f9bf5d.json), the Windows host harness: every
  control passed at `1f9bf5d`. That covers the Cursor-rule positive control and the import
  guard, root instructions, explicit and implicit skills, print-mode write
  rejection, deny precedence, scoped writes, and both exec controls. The real
  `~/.claude/CLAUDE.md` was checked by local line hashing in all 10 sessions and
  never appeared in context. Observation: in the implicit-skill session the model
  attempted the user-only skill and read its file, but the skill did not fire.
- [hooks-1f9bf5d.json](hooks-1f9bf5d.json), the Windows hook harness: every
  control passed at `1f9bf5d`. SessionStart and write advisories reach the model, the write
  advisory stays silent elsewhere, removing the hooks file removes the
  advisories, an exit-2 probe hook blocks a write, and both skill allowlist
  controls hold. This needed the shipped hooks to call `"${BASH:-bash}"`.
- [hooks-linux-1f9bf5d.json](hooks-linux-1f9bf5d.json), the Linux (WSL) hook
  harness at the same source: every control passed, so the hook command change
  holds on Linux.

- [lifecycle-1314d65.json](lifecycle-1314d65.json), the Windows lifecycle
  harness: all 12 controls passed at `1314d651b17c9f71e213f5eed44c127763a6a76f`.
  Setup, start, update, end and a fresh-session handoff expanded the shipped
  skills. Each mutation produced one proposal; the external Codex operator read
  every diff and approved its exact digest. The harness rejected wrong digests,
  applied the approved proposals with runtime `devin` receipts, rejected stale
  update/end replays, and checked that no other files or Git metadata changed.
  After removing pending inputs and proposals, a fresh read-only session recovered
  the random handoff value from the saved session. All five sessions excluded the
  real global Claude instructions under the local line-hash check. The source
  stayed clean and the disposable workspace was removed.

The host and hook artifacts predate the lifecycle setup fix. Their harness and
hook command behavior is unchanged; the lifecycle run covers the revised
portable skills and startup advisory. The Linux lifecycle replay is recorded
separately when complete.

## Retained diagnosis

Before the lifecycle fix, the Windows lifecycle harness timed out (600 s) in its setup phase when started
from PowerShell. The same setup prompt, run with Devin started from Git Bash,
produced the expected single proposal and stopped. The working hypothesis:
skills run `bash scripts/setup.sh` and `bash scripts/contextos.sh ...`, and in a
PowerShell launch that bare `bash` is the WSL launcher, where `setup.sh` blocks.
A single `bash scripts/contextos.sh start` through WSL returned in 0.8 s.

The passing run reuses the active Bash with `"$BASH"` for lifecycle commands.
The startup advisory now directs the agent to the setup skill and identifies
`scripts/setup.sh` as a separate interactive terminal installer. These two changes
resolved the observed run; the artifact does not isolate their individual effects.

## Scope

First-class CLI support covers the recorded Linux (WSL2) and native Windows 11
runs in Normal mode. The Windows real-profile opt-in does not isolate user-level
skills. The shipped foreign-import guard remains required. macOS, sandboxing,
MCP execution and native-memory synchronization are unverified by these runs.
The operator applies proposals outside Devin, so this lifecycle artifact does
not establish that Devin itself enforces exact-digest approval.
