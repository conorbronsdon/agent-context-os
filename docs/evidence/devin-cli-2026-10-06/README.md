# Devin CLI promotion evidence

These are synthetic fixtures, not personal-context sessions. Every run used
Devin CLI `3000.11.3 (9c803229faa4)`, installed from the official manifest with
its published SHA-256 verified, on Linux under WSL2 (Windows 11 host). Each
artifact records its source commit, binary hash, Devin's reported model and
permission mode per session, and hashes of commands and ATIF exports. Raw
responses, temporary paths, and credentials are not included.

Both harnesses replaced `HOME` and `XDG_CONFIG_HOME` with temporary
directories and pinned only `XDG_DATA_HOME`, which held the operator's Devin
login. The host harness seeded a synthetic user-level `~/.claude/CLAUDE.md`;
the lifecycle harness at `c638849` did not, and checked only that no `CLAUDE`
rule reached the context. Later lifecycle source (`2b2f6a8`) seeds and
excludes that canary too, and adds the second-review controls; [its rerun](../devin-cli-2026-10-07/README.md)
passed on `f36d2c2`. Devin's default
model reported itself as `swe-2-high` in every session.

## Passing runs on `c638849`

The host controls below still bind to the shipped host harness. The lifecycle
harness changed after this run; its final evidence is the
[10/7 rerun](../devin-cli-2026-10-07/README.md).

Both runs used source `c638849e1300a5ef64be6c7a892f7ab429aa4547`.

[Host controls](host-c638849.json) passed every gate:

- root `AGENTS.md` appeared in Devin's injected rules at session start, and the
  model answered without reading it through a tool;
- with the shipped `.devin/config.json`, neither the repository `CLAUDE.md`,
  the synthetic user-level `~/.claude/CLAUDE.md`, nor a `.claude/skills/` skill
  reached the session context, while the same fixture without the file
  injected both `CLAUDE.md` sources (positive control);
- `/contextos-devin-cli-control` expanded the user-only skill body into the user
  turn with no tool calls, and Devin omitted that skill from the list offered
  to the model; in the implicit turn the model tried to invoke it and Devin
  answered "not found";
- print mode rejected an unapproved write and an unapproved `apply` command;
  a project-local `Write(protected.txt)` deny beat a same-level `Write(**)`
  allow; a scoped write produced exact content and nothing else; an
  allowlisted kernel command ran exactly once.

The same run recorded, without gating, the limits documented in the
[adapter guide](../../../adapters/devin/README.md): Accept Edits wrote through
a project-local deny, and a broad user-level allow and Bypass mode each ran a
command that a project-level deny matched. In the implicit-skill turn the model
also read the skill file with its read tool; that is file access, not skill
invocation, and is recorded separately.

[Lifecycle](lifecycle-c638849.json) passed setup, start, update, end, and a
fresh-session handoff. Each phase showed Devin expanding the shipped
`context-*` skill body into the user turn. Start ran the kernel inventory and
changed nothing. Setup, update, and end each produced exactly one proposal
containing the requested synthetic fact. An external operator (a Claude Code
session acting for the maintainer, outside the Devin process) read each
review file and wrote the exact digest; the harness then rejected a wrong
digest, applied the approved one, checked the single matching receipt with
runtime `devin`, and rejected the stale replay for update and end. The model
made no `apply` attempt in any phase. Before the handoff the harness removed
pending inputs and proposals and confirmed the random value survived only in
`sessions/`; a new read-only session recovered it.

## Retained attempts

Earlier attempts stay visible. Each failure changed the harness or the claim,
never the pass criteria for a claimed behavior.

| Artifact | Outcome |
|---|---|
| [Host 1](host-attempt-1.json), [Host 2](host-attempt-2.json) | Accept Edits wrote through a project-local `Write(protected.txt)` deny. Probes then showed no project or local deny form blocks Accept Edits; the claim was narrowed to Normal mode and the behavior became an observation. |
| [Host 3](host-attempt-3.json) | The Normal-mode deny held, but Devin labels local denies "project-local settings override"; the rejection match was widened to cover both levels. |
| [Host 4](host-attempt-4.json), [Host 7](host-attempt-7.json) | The model invoked Devin's built-in `devin-cli` docs skill, then read files directly. The control now fails only on the fixture's user-only or foreign skill, and scopes must-not-load checks to injected context. |
| [Host 5](host-attempt-5.json), [Host 6](host-attempt-6.json) | A shipped project `ask` rule for `apply` was overridden by a broader local allow, then by a broader user-level allow, contrary to Devin's documented precedence. The adapter now ships no permission rules. |
| [Host 8](host-attempt-8.json) | Passed every gate on `8c1239d`, before the lifecycle and review changes. |
| [Lifecycle 1](lifecycle-attempt-1.json), [Lifecycle 2](lifecycle-attempt-2.json) | Setup tried a shell heredoc for its payload, then the kernel by absolute path; each rejection ended the print-mode session. |
| [Lifecycle 3](lifecycle-attempt-3.json), [Lifecycle 4](lifecycle-attempt-4.json) | Setup and update passed; end chained `date` and `test -f`, which were not allowlisted. The fixture now allows the shell broadly and denies `apply`, direct Python, `rm`, and mutating Git at the same level. |
| [Lifecycle 5](lifecycle-attempt-5.json) | Start drafted a new setup proposal despite "make no changes"; the harness caught the write. Start and handoff now deny file tools and `propose`. |
| [Lifecycle 6](lifecycle-attempt-6.json) | Every phase passed; the handoff's denied `board sync` ended the session before it answered. Read-only phases now allow the board command, which fails without writes when the fixture has no remote. |
| [Lifecycle 7](lifecycle-attempt-7.json) | Passed on `5186a9b`. Independent review then found it did not prove skill expansion, could recover the handoff value from leftover payloads, and missed quoted `apply` spellings; the final run includes those controls. |

## Not established

No hook adapter, MCP execution, native-memory bridge, cloud handoff, sandbox,
or native Windows behavior. On Windows Devin reads the real profile's
`~/.claude` and `~/.agents/skills` regardless of `HOME`, so the harnesses
refuse to run there. Cloud sessions remain experimental and Review remains
compatibility-only; neither inherits this result. First-class describes the
tested CLI lifecycle on the recorded client, model, and platform.
