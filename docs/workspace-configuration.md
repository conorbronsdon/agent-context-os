# Workspace configuration and migration

Context OS separates repository intent from machine-local runtime state and
per-operation evidence:

All locations below are beneath the v0.12 `ContextRoot`. v0.12 uses the
root contract (`ContextRoot == nominal WorkingRoot`), with KernelRoot also
colocated on the normal full-template wrapper path; it does not store or infer
an external application-repository binding. See
[the root contract](root-contract.md).

| Layer | Location | Meaning |
|---|---|---|
| Tracked workspace intent | `contextos.workspace.json` | Selected runtimes, desired profile/extras, repository paths, and exact bundle pin |
| Legacy tracked paths | `workspace.yaml` | Read-compatible input while migration is pending; never merged into JSON |
| Local host state | `.context-os/hosts.json` | Runtime manifests configured on this machine; gitignored and never a source of tracked agent intent |
| Installed bundle state | `.context-os/installed-bundle.json` | Actual local bundle identity and materialized component closure; compared with tracked intent by `doctor` |
| Operation receipts | `.context-os/receipts/` | The runtime that executed one approved lifecycle transaction |

## Canonical tracked JSON

Schema v2 has exact keys:

```json
{
  "schema_version": 2,
  "agents": ["claude", "codex"],
  "composition": {
    "profile": "selected",
    "extras": ["example-project"]
  },
  "paths": {
    "state_dir": "state",
    "sessions_dir": "sessions",
    "task_file": "TODO.md"
  },
  "template": {
    "version": "0.13.1",
    "source": "agent-context-os-template",
    "bundle_sha256": "<exact-64-character-lowercase-digest>"
  }
}
```

`agents` is a set: order has no behavioral meaning, duplicates fail, and
canonical writers sort IDs lexically. An empty array is valid and deliberately
means core-only. The CLI token `none` maps to that empty set but is never stored.
`auto` describes local launch detection only and can never become repository
intent. `generic` is reserved for operation receipts and is not a runtime ID.

The `full-template` compatibility profile derives every released component and
requires an empty `extras` array. The `selected` profile derives `core` plus the
components required by `agents`, then adds optional component roots from
`extras`. Runtime-required components must not be copied into `extras`.
`template.bundle_sha256` pins the exact verified local release bundle; no
workflow resolves or downloads `latest`.

The tracked `workspace/example.json` uses an all-zero digest placeholder because
the example is itself part of the release bundle and therefore cannot pin that
bundle without creating a self-reference. Replace the placeholder with the
verified lock digest when creating a real workspace; guided `workspace init`
does this from the explicit local bundle input.

Schema v1 remains readable only as a migration source. Its `mode:
"full-template"`, agents, paths, template name, and version migrate to the v2
`full-template` profile only when the caller also supplies the exact bundle
digest. Legacy YAML path migration remains a separate compatibility step.

The public template ships a schema-v2 `workspace/example.json` with `agents: []`, but no
live root configuration. This avoids overriding an existing clone's legacy YAML
before migration is reviewed. All adapter files remain present in `full-template`
profile. Guided composition records choices explicitly rather than inferring
from installed binaries or host registrations.

Canonical JSON paths use POSIX repository-relative syntax on every platform.
Drives, UNC and absolute paths, backslashes, dot segments, Windows device
aliases, `.git`, `.context-os`, and symlink traversal fail closed. The current
defaults remain `state`, `sessions`, and `TODO.md`; migration does not silently
move the task file to `state/tasks.md`.

Path syntax validity is not write authorization. Update/end proposal
publication, apply, and recovery also reject configured state/session targets
under the protected product and host-control namespaces enumerated in the
[root contract](root-contract.md). Benign custom directories remain supported.

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

Pre-JSON readiness preserves one narrower host-compatibility exception: an
internal linked `state_dir` is resolved inside the repository, so `start` and
the session-start hook read the resolved target. `doctor` reports the link and
resolved target as a warning with migration guidance. Migration remains blocked
until the link is replaced or `workspace.yaml` names the resolved
repository-relative directory directly; activation remains blocked until that
canonical JSON migration is applied. Canonical JSON does not inherit this
exception and rejects linked or reparse-point configured paths. Readiness files
beneath the resolved pre-JSON target remain no-follow; a linked `current.md` or
other descendant is rejected in every mode.

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
or clearing an existing non-empty set is rejected and must use `agent disable`.
Omitted or `auto` selection never infers intent from binaries
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
set belongs to the agent lifecycle. A repeated completed migration returns
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

Cleanup never makes a transaction *file* writable merely to delete it. On
Windows, read-only file names are removed atomically with
`FileDispositionInfoEx`. If that API is unavailable, strict recovery fails
closed and best-effort cleanup retains the blocked file while continuing with
other removable siblings; the diagnostic reports the observed file kind and
link count without promising an unchanged retry can remove it. This policy
avoids a check-then-`chmod` window even when metadata reports a single link,
because another link can be created after that observation. Cleanup may
temporarily add write permission to a directory,
which Windows does not permit to be hard-linked, and restores the original mode
if the directory operation fails. Incomplete `.building` and retired `.discard`
journal namespaces contain no recoverable workspace state; their cleanup is
best-effort and a retained artifact there does not block unrelated applies or a
new journal with the same proposal ID. A colliding retained namespace is left
intact and the new build or retirement uses a collision-free numbered sibling.
`doctor` reports proposal-ID recovery candidates separately from those inert
namespaces. A candidate's manifest is validated only when apply inspects it, so
the candidate must be recovered or diagnosed rather than deleted. An inert path
may be removed manually after confirming no apply is active and using a method
that does not change shared-inode attributes. Link-like entries, non-directories,
and names outside both contracts are a third invalid category. Apply does not
traverse link-like entries and rejects the other invalid forms; inspect and
correct or remove each reported path before retrying.

`doctor` does not enumerate `.context-os/staging/`. If unsupported atomic
deletion retains a staging artifact, first confirm no apply is active. The
containing `.context-os/staging/<proposal-id>` namespace is then disposable, but
remove it only with a tool or filesystem that does not change shared-inode
attributes. Journal paths remain subject to the recovery classifications above.

An upgrade can expose a crash-left journal created by an older version whose
configured target is now a protected product or host-control namespace. Current
automatic recovery intentionally retains that journal and refuses to touch the
target. Stop new applies and keep the evidence intact. Archive a complete copy
of the journal outside the active `.context-os/journals/` directory, then use an
explicitly reviewed incident-recovery procedure to restore the target's
presence, bytes, and mode from an independently verified source. Only after
verifying the restored target may that one named active journal be removed and
`doctor` rerun. If the target cannot be independently restored and verified,
retain the journal and escalate; do not rename it inside the active journal
directory or delete it to unblock apply.

## Agent activation lifecycle

List every bundled runtime while keeping tracked activation and machine-local
registration visibly separate:

```bash
bash scripts/contextos.sh agent list
```

Create an activation proposal with `agent enable`; `agent add` is an alias.
`agent disable` is the only operation permitted to shrink tracked intent:

```bash
bash scripts/contextos.sh agent enable --runtime codex
bash scripts/contextos.sh agent disable --runtime claude
bash scripts/contextos.sh apply .context-os/proposals/<proposal-id>.json \
  --confirm <proposal-digest> --runtime generic
```

These commands write only an ignored proposal and return the exact config diff,
authorization evidence, source commit, and digest. Repeating an already-satisfied
operation is a no-op. Apply revalidates the exact before set and raw config bytes,
so a stale enable or disable cannot overwrite a newer selection. Activation
changes only `contextos.workspace.json`: bundled adapters remain in full-template
mode, and host credentials, local registration, native memory, integrations,
binaries, and context/state files are outside the transaction.

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

## Setup selection contract

`scripts/setup.sh --agents <comma-separated-runtime-ids>` selects every agent
the repository is intended to support. On a TTY, omission prompts for that set;
in non-interactive use omission performs local auto-detection only. Explicit
`--agents auto` has the same local-only behavior. The singular `--agent` form
is a deprecated singleton compatibility alias.

Setup uses the existing proposal/apply transaction boundary. It shows the exact
workspace diff, source commit, and digest, then defaults approval to no. An
approved selection is registered in the gitignored host map and updates tracked
intent with these rules:

- setup is additive and idempotent: requested agents are unioned with the
  configured set;
- `none` creates an intentional empty set only for a fresh or legacy workspace;
- subset or `none` reruns against a non-empty set are no-ops;
- only `agent disable` may shrink the configured set;
- local launch choice is ephemeral and never creates a stored primary agent;
- no adapter or component is deleted merely because it was not selected; and
- Cursor is a registered experimental runtime, and OpenClaw is first-class;
  both may be stored in `agents`. Cursor registration does not conflate or launch its IDE and Agent
  CLI surfaces; OpenClaw registration does not configure its private workspace,
  copied skills, external plugin, or project aliases. Both retain separate
  host-local onboarding steps.

## Guided composition and reconciliation

All guided composition commands require an existing target directory plus an
explicit local lock, source directory, and independently obtained exact bundle
digest. They verify that bundle before calculating intent and display the
derived closure in one structural proposal. Nothing installs a host runtime,
changes authentication, downloads a release, or removes native host memory.

Initialize a clean target:

```bash
bash scripts/contextos.sh workspace init \
  --target /path/to/workspace \
  --lock /path/to/contextos.bundle.lock.json \
  --source /path/to/extracted-bundle \
  --expect-sha256 <bundle-digest> \
  --agents codex --profile selected --extras example-project
```

Converge a clone or moved workspace after gitignored installed state is absent:

```bash
bash scripts/contextos.sh workspace reconcile \
  --target /path/to/workspace \
  --lock /path/to/contextos.bundle.lock.json \
  --source /path/to/extracted-bundle \
  --expect-sha256 <digest-pinned-in-contextos.workspace.json>
```

Use `workspace update` with the complete desired `--agents`, `--profile`, and
`--extras` values to add or remove components. For a bundle upgrade, also pass
the pinned `--current-lock`, `--current-source`, and
`--expect-current-sha256`. Update requires valid installed state so removals
have an exact content/ownership base; reconcile restores that state first after
a clean clone.

A schema-v1 workspace first uses `workspace update --profile full-template`
against its matching pinned bundle. This preserves its full closure while the
transaction adds the digest and v2 composition. A safe legacy `workspace.yaml`
can instead seed `workspace init`; its normalized paths are preserved and the
legacy file is retired in that same transaction. Ambiguous or conflicting
legacy input fails before proposal publication.

Every path produces the same digest-bound proposal. Apply it only after review:

```bash
bash scripts/contextos.sh bundle apply \
  --target /path/to/workspace \
  --proposal .context-os/proposals/<proposal-id>.json \
  --confirm <proposal-digest>
```

The apply transaction publishes tracked configuration, managed/seed files, and
installed state together through the shared journal, rollback, receipt, and
second pre-mutation source revalidation path. For `selected` profiles, README
runtime support and shared `AGENTS.md` instructions are deterministically
projected from the selected runtime descriptors; their component owner remains
`core` and `agents-instructions`, respectively.

After the receipt is durable, `bundle apply` runs bare `doctor` in the tracked
profile scope and includes that validation report in its output. A post-commit
warning or failure is reported without pretending the already committed
transaction rolled back.

`doctor` reports the desired and installed bundle identities, desired and
installed closures, and exact missing/extra components. Missing local state is
a reconcile warning; contradictory bundle or closure state is a failure.

## Root discovery

In this section, `root` means the v0.12 colocated ContextRoot selected by the
CLI. `--root` does not designate a separate application WorkingRoot. External
attachment instead requires exact `--kernel-root`, `--context-root`, and
`--working-root` roles plus a validated project binding; it does not revise or
overload workspace schema v2.

`contextos.workspace.json` is the provider-neutral root marker. A valid tracked
configuration is sufficient even for a minimal marker-only workspace with no
`AGENTS.md`, runtime adapter, or materialized state paths. Discovery validates
the nearest JSON marker before accepting it; malformed, aliased, symlinked, or
non-file markers fail at that directory instead of falling through to an outer
workspace.

A marker-only root is not the same as a core-only profile. `agents: []` defines
the profile and remains fully supported in a materialized full-template
workspace. Marker-only describes a bootstrap root that lacks product
descriptors: it supports discovery, reports, diagnosis, direct provider-neutral
hooks, and proposal publication, while apply and agent/runtime configuration
fail until verified detached-bundle materialization installs the product
closure. Schema-v2 marker identity includes `template.source`,
`template.version`, and `template.bundle_sha256`; all three must exactly match
the candidate bundle. Use `workspace reconcile` for the supported path. The
lower-level `bundle compose` command remains only for a clean target where the
marker does not exist.

Existing clones remain discoverable through the legacy compound marker:
`AGENTS.md` plus either a `state/` directory or `workspace.yaml`. Discovery
chooses the nearest recognized root. After evaluating a directory, it stops at
an exact `.git` file, directory, or symlink, so an unconfigured nested repository
cannot accidentally inherit an outer repository's Context OS state. Pass an
explicit `--root` to choose the discovery start when cwd is not the intended
starting point; the argument itself need not be the root. A discovery start may
be a real directory, regular file, or link-like entrypoint.
Internal links and entrypoints such as `current -> repo` remain compatible when
their resolved start stays inside the nearest lexical `.git` boundary. A link
that escapes that boundary fails before an outer workspace can be selected;
symlinked system ancestors above the boundary and non-Git legacy paths remain
compatible.
