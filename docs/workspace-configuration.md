# Workspace configuration and migration

Context OS separates repository intent from machine-local runtime state and
per-operation evidence:

| Layer | Location | Meaning |
|---|---|---|
| Tracked workspace intent | `contextos.workspace.json` | Selected runtime set, full-template mode, repository paths, and template source |
| Legacy tracked paths | `workspace.yaml` | Read-compatible input while migration is pending; never merged into JSON |
| Local host state | `.context-os/hosts.json` | Runtime manifests configured on this machine; gitignored and never a source of tracked agent intent |
| Operation receipts | `.context-os/receipts/` | The runtime that executed one approved lifecycle transaction |

## Canonical tracked JSON

Schema v1 has exact keys:

```json
{
  "schema_version": 1,
  "mode": "full-template",
  "agents": ["claude", "codex"],
  "paths": {
    "state_dir": "state",
    "sessions_dir": "sessions",
    "task_file": "TODO.md"
  },
  "template": {
    "version": "0.12.0",
    "source": "agent-context-os-template"
  }
}
```

`agents` is a set: order has no behavioral meaning, duplicates fail, and
canonical writers sort IDs lexically. An empty array is valid and deliberately
means core-only. The CLI token `none` maps to that empty set but is never stored.
`auto` describes local launch detection only and can never become repository
intent. `generic` is reserved for operation receipts and is not a runtime ID.

Version 1 intentionally uses only `full-template`. Selecting agents records
intent and controls bare `doctor` validation scope. Removal of unselected
adapters remains later transaction-backed work.

The public template ships `workspace/example.json` with `agents: []`, but no
live root configuration. This avoids overriding an existing clone's legacy YAML
before migration is reviewed. All adapter files remain present in `full-template`
mode. The transaction-backed migration path can create the root JSON and record
choices explicitly rather than inferring from installed binaries; setup-time
selection and adapter composition remain separate work.

Paths use canonical POSIX repository-relative syntax on every platform. Drives,
UNC and absolute paths, backslashes, dot segments, Windows device aliases,
`.git`, `.context-os`, and symlink traversal fail closed. The current defaults
remain `state`, `sessions`, and `TODO.md`; migration does not silently move the
task file to `state/tasks.md`.

The generated structural schema is `workspace/schema.json`.
`contextos.workspace_schema` remains authoritative for registry membership,
portable path rules, set semantics, and role collisions.

## Precedence and legacy compatibility

When `contextos.workspace.json` exists, it is the whole authoritative document.
`workspace.yaml` is ignored for behavior and reported as shadowed, including
supported-key conflicts. Malformed or unsupported JSON fails closed; the loader
never falls back to valid YAML.

Without JSON, the historical flat `workspace.yaml` path reader remains
compatible. It continues to accept `state_dir`, `sessions_dir`, and `task_file`
with the prior defaults and historical host path spelling. Migration safely
normalizes leading `./`, trailing `/`, and repeated `/`. Backslashes remain
runtime-compatible on the current host but cannot be migrated because their
meaning differs across operating systems; replace them with POSIX `/` first.
Duplicate keys, empty values, nested structures, anchors, block scalars,
unknown keys, and unsafe paths block a supposedly lossless preview instead of
being silently dropped.

Inspect effective state:

```bash
bash scripts/contextos.sh workspace show
```

Preview canonical JSON without writing:

```bash
bash scripts/contextos.sh workspace migrate --agents claude,codex
bash scripts/contextos.sh workspace migrate --agents none
```

The singular `--agent` form remains a deprecated singleton compatibility alias.
`--agent` and `--agents` are mutually exclusive. A repeated preview with the
same set is a no-op; explicit expansion can be previewed; shrinking, replacing,
or clearing an existing non-empty set is rejected and must use the later
disable lifecycle. Omitted or `auto` selection never infers intent from binaries
or local state.

Create a local, digest-bound migration proposal after reviewing the preview:

```bash
bash scripts/contextos.sh workspace propose-migration --agents claude,codex
bash scripts/contextos.sh apply .context-os/proposals/<proposal-id>.json \
  --confirm <proposal-digest> --runtime generic
```

Proposal creation writes only the ignored proposal artifact and reports
`writes: false`; it does not change tracked files. The proposal digest covers
the exact canonical JSON write, any legacy YAML deletion, the selected-agent
component closures, the component/runtime/schema source hashes, and the source
Git commit. Apply revalidates those inputs and raw target bytes under the shared
lock before changing tracked files. The digest binds the reviewed proposal but
does not authenticate who approved it; receipts state that boundary directly.
After generation, present the returned changes, authorization evidence, source
Git commit, and digest, then wait for explicit approval of that exact proposal
before invoking `apply`. Approval of the earlier preview is not approval of a
newly generated proposal.

Legacy-only migration writes JSON and deletes YAML as one recoverable transaction
under the agent configuration policy. A shadowed YAML file can be deleted when
canonical JSON already exists and the requested agent set is unchanged. A
workspace without legacy YAML is setup work, and changing an existing JSON agent
set belongs to the later agent lifecycle. A repeated completed migration returns
a structured no-op and produces no proposal.
The transaction authorizer owns only those two exact root paths; ordinary
setup/update/end proposals cannot use it to widen their path policy.

Agent-configuration transactions keep raw-byte backups in a durable local
journal until the receipt is committed. An ordinary failure restores exact
bytes and modes immediately, using inode ownership to avoid overwriting a
concurrent target. Once the receipt exists, recovery verifies the receipt-bound
after bytes and mode rather than requiring the original publication inode; this
lets Git and editors rewrite an equivalent committed file without wedging every
later apply. A missing or stale committed target retains the evidence and fails
with an actionable error. A process kill can leave both the journal and the
shared apply lock; after confirming no apply process is active and removing the
stale lock, the next agent-configuration apply recovers the journal before
revalidating and applying its proposal. POSIX mode bits are exact; Windows
validates only its meaningful writable/read-only behavior.

## Local scalar runtime migration

Older installs wrote one `.context-os/runtime.json`. Migrate it atomically into
the runtime-keyed local host map:

```bash
bash scripts/contextos.sh workspace migrate-local-runtime
```

The migration preserves the legacy installation timestamp and manifest digest,
merges disjoint host entries, rejects conflicts and malformed state, and never
changes `contextos.workspace.json`. It atomically replaces `hosts.json` first,
then removes the now-redundant scalar file. If cleanup fails, the host map
remains authoritative and the command reports the retained legacy file. Runtime
installation uses the same migration order before updating the host map and
preserves an unchanged runtime's original timestamp.

Host-state writes use `.context-os/hosts.lock`. A crash can leave that lock
behind; `doctor` warns with recovery guidance. Remove it only after confirming
that no install or migration process is still running.

Local host records never activate a tracked runtime. Bare `doctor` validates
the JSON `agents` set, reports unselected shipped adapters as inert, and treats
availability, onboarding, descriptor drift, component materialization,
conformance declarations, and evidence freshness as independent dimensions.
An empty `agents` array is therefore a real core-only profile, even when a host
has additional runtimes installed locally.

## Setup compatibility contract

The current bootstrap still exposes singular `scripts/setup.sh --agent` while
the multi-select setup work is completed separately. Its semantics are fixed:

- explicit runtime selection may later establish tracked intent through a
  reviewed transaction;
- `none` means an intentional empty set only when explicitly selected;
- omitted selection and `auto` are local launch choices and never tracked;
- reruns preserve the configured set unless an explicit expansion is reviewed;
- subset, disjoint, or `none` requests against a non-empty set never silently
  remove adapters;
- Cursor and OpenClaw remain launch/read compatibility names until registered
  runtime descriptors exist, so they cannot be stored in `agents` yet.

## Root discovery

`contextos.workspace.json` is the provider-neutral root marker. A valid tracked
configuration is sufficient even for a minimal core-only workspace with no
`AGENTS.md`, runtime adapter, or materialized state paths. Discovery validates
the nearest JSON marker before accepting it; malformed, aliased, symlinked, or
non-file markers fail at that directory instead of falling through to an outer
workspace.

Existing clones remain discoverable through the legacy compound marker:
`AGENTS.md` plus either a `state/` directory or `workspace.yaml`. Discovery
chooses the nearest recognized root. After evaluating a directory, it stops at
an exact `.git` file, directory, or symlink, so an unconfigured nested repository
cannot accidentally inherit an outer repository's Context OS state. Pass an
explicit `--root` only when deliberately operating on an outer workspace. A
discovery start may be a real directory, regular file, or link-like entrypoint.
Internal links and entrypoints such as `current -> repo` remain compatible when
their resolved start stays inside the nearest lexical `.git` boundary. A link
that escapes that boundary fails before an outer workspace can be selected;
symlinked system ancestors above the boundary and non-Git legacy paths remain
compatible.
