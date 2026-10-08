# Devin CLI native Windows evidence (in progress)

Synthetic fixtures only. All runs used Devin CLI `3000.11.3 (9c803229faa4)` and
source `1f9bf5d`. Windows runs: Windows 11 (`10.0.26200`), started from
PowerShell, in the harnesses' `--windows-real-profile` mode. Artifacts keep
controls, observations, booleans and hashes, never raw responses, paths or
credentials.

## Passed

- [host-1f9bf5d.json](host-1f9bf5d.json), the Windows host harness: every
  control passed. That covers the Cursor-rule positive control and the import
  guard, root instructions, explicit and implicit skills, print-mode write
  rejection, deny precedence, scoped writes, and both exec controls. The real
  `~/.claude/CLAUDE.md` was checked by local line hashing in all 10 sessions and
  never appeared in context. Observation: in the implicit-skill session the model
  attempted the user-only skill and read its file, but the skill did not fire.
- [hooks-1f9bf5d.json](hooks-1f9bf5d.json), the Windows hook harness: every
  control passed. SessionStart and write advisories reach the model, the write
  advisory stays silent elsewhere, removing the hooks file removes the
  advisories, an exit-2 probe hook blocks a write, and both skill allowlist
  controls hold. This needed the shipped hooks to call `"${BASH:-bash}"`.
- [hooks-linux-1f9bf5d.json](hooks-linux-1f9bf5d.json), the Linux (WSL) hook
  harness at the same source: every control passed, so the hook command change
  holds on Linux.

## Open

The Windows lifecycle harness timed out (600 s) in its setup phase when started
from PowerShell. The same setup prompt, run with Devin started from Git Bash,
produced the expected single proposal and stopped. The working hypothesis:
skills run `bash scripts/setup.sh` and `bash scripts/contextos.sh ...`, and in a
PowerShell launch that bare `bash` is the WSL launcher, where `setup.sh` blocks.
A single `bash scripts/contextos.sh start` through WSL returned in 0.8 s.

`runtimes/devin.json` is unchanged. Native Windows stays unverified until the
lifecycle harness passes.
