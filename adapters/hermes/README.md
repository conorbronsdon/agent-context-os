# Hermes adapter

Run `bash scripts/contextos.sh install --runtime hermes` from the repository root.
Expose `.agents/skills/` as an external Hermes skill directory, or install the
four short aliases together with their four `context-*` cores. Hermes copies
installed skills, so `bash scripts/contextos.sh doctor --runtime hermes` should be
part of updates and copied skills should be refreshed after a source change.

The optional [`hooks.example.yaml`](hooks.example.yaml) maps Hermes lifecycle
and pre-write events to the same read-only policy checks used by the other
runtimes. Merge it into user configuration only after reviewing its commands.
Kernel proposal/apply enforcement does not depend on these hooks.

The YAML example is POSIX-oriented. On Windows, use an equivalent command such
as `powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command
"$root = git rev-parse --show-toplevel; & (Join-Path $root
'scripts/context-os-hook.ps1') hermes pre-write"` for the pre-tool event (and replace `pre-write` with
`session-start` for the session event). Hermes hook policy remains advisory.

Hermes `MEMORY.md` and `USER.md` remain host-local. Never point the kernel at
them or mirror them into repository state automatically.
