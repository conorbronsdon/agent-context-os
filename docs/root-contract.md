# Root contract

**Status:** Accepted. v0.12 compatibility mode and the first distinct-root
external-project attachment slice are implemented; desired component
composition remains a later workspace-schema milestone.

Context OS uses three root roles. The normal v0.12 full-template wrapper path
colocates them. A minimal marker-only JSON ContextRoot can be discovered and
inspected by already-loaded Context OS code, but that code's installation
location is not runtime/component authorization. Their ownership and authority
are defined separately now so a later attachment flow does not have to
reinterpret existing proposals, receipts, or safety claims.

## Root roles

| Role | Owns | Lifecycle access |
|---|---|---|
| **KernelRoot** | Authoritative executable product assets: `contextos/`, executable wrappers, runtime and component manifests, schemas, and immutable bundle sources and locks | Read product authority and execute the kernel. Lifecycle setup/update/end never mutate these KernelRoot-owned authority paths. |
| **ContextRoot** | Tracked workspace intent, materialized repository instructions and portable skill bodies, and durable context: routing, identity, projects, state, sessions, and tasks; plus local `.context-os/` inputs, proposals, locks, staging, journals, receipts, host state, and installed-bundle state | The only mutation authority for lifecycle setup/update/end. Transaction targets and journal entries are ContextRoot-relative. |
| **WorkingRoot** | The nominal application working directory whose files describe the work being performed. In v0.12 this is the discovered root; its containing Git repository may be an ancestor. | Application-owned paths are read-only evidence for lifecycle. When roles are colocated, lifecycle may mutate only paths authorized as ContextRoot content; other application edits remain ordinary host/tool actions outside proposal/apply. |

Role ownership is stronger than physical containment. In attachment mode, the
canonical roots must be distinct and non-overlapping: none may be
nested beneath another. v0.12 permits the full-template colocation below and a
marker-only workspace to use the already loaded executable package without
turning that installation into product, ContextRoot, or WorkingRoot authority.
Component policy and root role answer different questions: `managed` records
bundle upgrade/customization policy, not runtime immutability. In colocated
v0.12, materialized `AGENTS.md`, `CLAUDE.md`, and `.agents/skills/**` are
ContextRoot instruction paths that the explicitly reviewed setup allowlist may
personalize even though the component manifest also manages their upgrade
provenance. Kernel code, wrappers, schemas, manifests, and bundle authority are
not on that setup allowlist.

The v0.12 setup allowlist is explicit: root files `ROUTING.md`, `TODO.md`,
`CLAUDE.md`, and `AGENTS.md`; content beneath `identity/`, `projects/`, and
`state/`; and portable skills beneath `.agents/skills/`. Update and end use the
configured state/session paths subject to the product-authority guard below.

## v0.12 compatibility decision

Every supported v0.12 workspace binds lifecycle state and nominal work to one
discovered path:

```text
ContextRoot == nominal WorkingRoot == canonical discovered root
```

On the normal full-template path, `scripts/contextos.sh` loads the kernel from
that same root, so `KernelRoot == ContextRoot` as well. A full-template
core-only profile (`agents: []`) still has this colocated product closure. A
minimal marker-only JSON root is narrower: already-loaded code may discover,
report, diagnose, run direct provider-neutral hooks, and publish content
proposals there, but it may not apply those proposals or mutate agent/runtime
configuration until trusted runtime/component descriptors are colocated.
`generic` execution is reserved for authenticated agent-config and
materialization proposals, not descriptor-free content apply. Verified
detached-bundle materialization is the separate explicit-destination
installation boundary that may create the product closure. For a marker-only
target, its tracked `template.source` and `template.version` must already match
the verified candidate bundle exactly; use `bundle propose` without current
bundle inputs, then review and run `bundle apply`. The clean-target
`bundle compose` command is not the marker-only path because the marker already
exists.
v0.12 exposes no KernelRoot path field, and the origin of imported code grants
no lifecycle authority.

`GitEvidenceScope` is a documentation-only evidence source, not a fourth
authority root or a v0.12 path/identity field. It is the nearest valid containing
Git worktree, when one exists, used only for existing commit evidence. It is
absent when the nearest repository is unborn, absent, invalid, or Git cannot
execute; evidence never falls outward past a nearer repository. It
normally equals the discovered root, but an intentionally nested ContextRoot
makes it an ancestor of the nominal WorkingRoot. That compatibility case does
not authorize lifecycle mutation outside ContextRoot.

The existing `--root` option supplies the starting path for ContextRoot and
nominal WorkingRoot discovery; it does not require its argument itself to be
the root. Discovery
ascends from that path to the nearest valid `contextos.workspace.json` or legacy
compound marker and stops at a nested `.git` boundary. Without `--root`, a
direct module invocation starts from process cwd. The shell wrapper instead
passes its own parent as exact KernelRoot and executes Python from that root so
caller cwd cannot influence imports; when no split roles are supplied,
compatibility discovery deliberately starts at that KernelRoot. In the v0.12
full-template colocated mode, host lifecycle skills require the exact
host-supplied directory containing
`AGENTS.md` and `scripts/contextos.sh`. That is an adapter heuristic, not
ContextRoot discovery: a marker-only JSON workspace remains CLI-discoverable
without those files. Split-mode role options identify exact role roots and do
not inherit this upward-search compatibility behavior.

Consequences that must be stated rather than inferred:

- `start.git_head`, proposal `source_git_head` when that field is present, and
  receipt Git evidence all
  describe `GitEvidenceScope`, the nearest containing Git worktree. A legacy or
  non-top-level ContextRoot may therefore report an enclosing
  Git worktree's HEAD; the nominal WorkingRoot remains the discovered path and
  v0.12 exposes neither the evidence-scope path nor a second mutation authority.
  A new enclosing HEAD therefore invalidates proposal commit evidence even when
  the commit did not touch ContextRoot; these fields do not represent
  uncommitted worktree status.
- Starting an agent in an unrelated application repository and reaching into a
  separate Context OS repository is not a supported v0.12 lifecycle path.
- When supplied, `--root` is the sole discovery start. A relative value resolves
  against process cwd like any path argument; Context OS never falls back to
  cwd, a skill installation directory, or an installed-package location.
- External attachment requires versioned binding, evidence, and receipt
  contracts; it cannot silently change the meaning of v0.12 fields.

The release therefore publishes the trustworthy full-template, full-closure,
colocated mode. It does not claim external project attachment or slim
composition.

## Resolution and canonicalization

The public readiness entrypoints canonicalize their root before using it for
containment or identity checks.

- In v0.12, CLI discovery returns the canonical ContextRoot and nominal
  WorkingRoot; full-template wrapper execution also loads KernelRoot there.
- Direct Python `start_report`, `hook_report`, and `doctor` calls normalize the
  exact supplied root to the same canonical ContextRoot spelling before
  workspace resolution; they do not search upward. The CLI performs discovery
  first. Direct callers and CLI callers share one canonical readiness contract.
- Strict lifecycle reads and hooks fail closed when a path changes identity or
  becomes link-like after canonicalization. `doctor` remains diagnostic: a
  late race produces structured results rather than a traceback or followed
  link. Initialization and freshness become `unknown` warnings; a required
  state file that becomes link-like remains a failing check.
- Discovery never falls through an invalid nearer marker or climbs past a
  nested Git boundary to capture an outer ContextRoot.

In split mode, KernelRoot will come from the trusted installation or wrapper,
ContextRoot from an exact explicit option or validated local binding, and
WorkingRoot from an exact explicit host working directory or argument. In that
mode, KernelRoot location and process cwd must never be implicit authority for
ContextRoot. The v0.12 cwd-based discovery compatibility described above is the
deliberate exception.

## Legacy linked-path boundary

v0.12 preserves the explicitly tested pre-JSON behavior for an internal linked
`state_dir`, both with legacy `workspace.yaml` and with no tracked configuration:
readiness may read the resolved internal target, and update/end proposal/apply
uses that resolved internal path rather than the link spelling. Migration and
activation continue to reject the link. This is a compatibility exception, not
part of the canonical no-follow guarantee. Readiness files beneath the resolved
target remain no-follow in every mode; the exception covers only the pre-JSON
`state_dir` indirection for readiness and never a linked `current.md` or other
descendant. Other legacy path fields retain their historical resolution
semantics outside this readiness guarantee.

`doctor` identifies the link spelling and resolved internal target, scopes the
exception, and directs the owner to replace or retarget the link before
migration. Canonical JSON workspaces continue to reject linked or
reparse-point state paths for `start`, hooks, and diagnostics. Distinct-root
mode requires canonical tracked configuration and does not inherit
the exception.

## External attachment binding

External attachment keeps stable project identity separate from
machine-specific location:

- ContextRoot stores a schema-versioned tracked project identity. It never
  stores an absolute KernelRoot or WorkingRoot path.
- Ignored local state beneath `ContextRoot/.context-os/` maps that identity to
  canonical machine-local KernelRoot and WorkingRoot paths plus observed
  repository identity.
- The first attachment slice adds no tracked pointer or Context OS lifecycle
  file to WorkingRoot.
- Moving a repository requires explicit rebinding after identity validation.
  A path match, remote-name match, cwd, symlink, or copied marker is not
  authorization.
- A missing, stale, or mismatched binding makes strict lifecycle operations
  fail before proposal or mutation. Read-only diagnostics may report it as
  unavailable or stale.

The tracked manifest is `projects/<project-id>/contextos.project.json`, schema
version 1. It stores a lowercase project id and a Git identity composed of the
repository object format plus an anchor commit; it stores no absolute path or
remote. Validation proves that the exact WorkingRoot Git object database still
contains that canonical commit; it deliberately identifies clones or forks that
share the anchor history rather than claiming checkout-global uniqueness. The ignored local registry is
`.context-os/project-bindings.json`, schema version 1. It binds that project id
to exact canonical KernelRoot, ContextRoot, and WorkingRoot paths, the same Git
identity, and the binding timestamp.

`project attach --id <id>` proposes the first tracked manifest and local
binding. `project rebind --id <id>` proposes only a replacement local binding
after the tracked anchor is found at the new exact Git top level. Both use the
existing exact-digest proposal, lock, staging, journal, receipt, rollback, and
recovery protocol. The binding is deliberately nonexclusive: two ContextRoots
may make independent read-only claims on one WorkingRoot. No machine-global
registry or WorkingRoot marker is created; every invocation and receipt is
instead scoped to one exact ContextRoot and project identity.

## Write and evidence boundaries

Journal-backed lifecycle and promotion workflows obey these invariants:

1. Proposal, lock, staging, journal, receipt, and every target path are owned by
   ContextRoot. Host skills conventionally place reviewed input beneath
   `ContextRoot/.context-os/inputs/`; the CLI also accepts an explicit input
   file elsewhere, whose bytes are read but whose location is not mutation
   authority.
2. Journal and receipt target paths are relative to ContextRoot; recovery can
   restore only ContextRoot targets.
3. WorkingRoot state may be bound as read-only evidence, but it never grants
   mutation authority and never replaces ContextRoot target hashes.
4. On the v0.12 full-template path, colocated product files supply executable
   code, schemas, and runtime/component authorization. Marker-only content
   cannot borrow authority from the installed package: named-runtime apply,
   agent configuration, and runtime registration fail until the trusted product
   closure is colocated. Verified detached-bundle materialization supplies its
   own pinned authority at the separate installation boundary.
5. Materializing a bundle is a separately named installation/composition
   boundary with an explicit reviewed destination. It is not a setup/update/end
   lifecycle write to an attached WorkingRoot.

For both canonical JSON and pre-JSON compatibility configuration, update/end
proposal publication, apply, and recovery reject configured state or session
targets whose first path component is a product-authority namespace. Config
readability therefore cannot widen lifecycle mutation authority.

The v0.12 protected namespaces are `.agents/`, `.claude/`, `.codex/`,
`.cursor/`, `.github/`, `adapters/`, `bundles/`, `components/`, `contextos/`,
`integrations/`, `runtimes/`, `scripts/`, and `workspace/`. This update/end
guard includes extensible host instruction surfaces; it does not make those
paths KernelRoot-owned or remove setup's narrower `.agents/skills/` authority.

In split mode, receipts and reports use role-qualified identities and Git
fields. The compatibility `git_head` remains ContextRoot evidence and does not
silently acquire a WorkingRoot meaning.

## Required controls

The root split retains all v0.12 controls and adds distinct-root
fixtures. Each row names a must-fire behavior and its must-not-fire complement.

| Surface | Must fire | Must not fire |
|---|---|---|
| Compatibility | `--root R` starts discovery at `R`, resolves ContextRoot and the nominal WorkingRoot to the nearest canonical root, keeps full-template wrapper KernelRoot colocated while permitting already-loaded code to inspect a marker-only root, attributes existing Git commit fields to `GitEvidenceScope`, and keeps existing commands/receipts valid | A supplied discovery start falls back to cwd or installed product paths; an installed package grants product or ContextRoot authority; an enclosing Git worktree gains lifecycle mutation authority or is presented as ContextRoot-authored work; exact split-role options search upward |
| Marker-only bootstrap | Discovery, start, diagnosis, direct provider-neutral hooks, and content proposal publication remain read/local-publication surfaces; `bundle propose` without current-bundle inputs may materialize a matching verified product closure at its explicit destination | Descriptor-free content apply, agent configuration, runtime registration, or a named provider hook/apply succeeds; `bundle compose` is presented as accepting an existing marker, or bundle authority is inferred from installed code or writable ContextRoot content |
| Context discovery | Nearest valid marker wins | Invalid inner marker falls outward, or discovery crosses nested `.git` |
| Canonicalization | Equivalent permitted entrypoints produce one canonical identity for CLI and direct API calls | Link/reparse swaps or alias changes redirect a role after validation |
| Start | Reads ContextRoot continuity and, in split mode, separately reports WorkingRoot identity/status/history | Writes any root, reads context state from WorkingRoot, or presents KernelRoot commits as user work |
| Propose | Publishes reviewed proposal state only beneath ContextRoot | Absolute, escaping, unresolved link-like, canonical-config linked, KernelRoot, or WorkingRoot targets reach publication; the documented pre-JSON internal-link exception is resolved before target calculation |
| Apply/recovery | Changes and restores only ContextRoot-relative targets under the existing digest, lock, journal, and receipt protocol | Crafted or legacy artifacts cause KernelRoot/WorkingRoot mutation |
| Runtime registration | In v0.12 full-template mode, reads colocated trusted runtime/component descriptors and records local state beneath ContextRoot | Marker-only registration borrows descriptors from the installed package, or registration writes host state before descriptor validation |
| Doctor | Diagnoses each role independently and stays total across late races | Executes runtime probes, follows links, mutates a root, or hides an unexecuted check as green |
| Hooks | Resolves protected ContextRoot paths against the declared role | Treats an ordinary WorkingRoot-relative source path as ContextRoot-relative |
| Binding | Explicit identity match permits a local binding and explicit rebind handles a move | cwd, copied marker, stale path, or matching remote name alone authorizes use |
| Root isolation | Split-mode lifecycle succeeds with a read-only KernelRoot and unchanged WorkingRoot snapshot | Any successful or rejected lifecycle path changes KernelRoot or WorkingRoot bytes, modes, or tree shape |

## Implementation surface inventory

Distinct-root execution updates these surfaces together rather than creating a
second ad hoc root path:

- `contextos/cli.py` adds unambiguous role options; `--root` remains the v0.12
  colocated compatibility form.
- `contextos/kernel.py` adds typed root resolution; ContextRoot workspace and
  transaction guards; role-qualified Git evidence, reports, hooks, receipts,
  and recovery.
- `scripts/contextos.sh` and hook wrappers load KernelRoot assets without
  replacing the caller's WorkingRoot or discovering ContextRoot from cwd.
- `.agents/skills/context-*` execute in WorkingRoot while
  invoking an explicit/bound ContextRoot through KernelRoot.
- Apply and hooks read runtime/component authority from KernelRoot, never from
  writable context or application content.
- OpenClaw plugin alias attachment remains separately bounded. Desired
  component composition is tracked by workspace schema v2 and changes only the
  explicit ContextRoot through the materialization transaction.

Issue #116 owns distinct-root execution and its Windows/Linux Claude-to-Codex
golden path. Schema-v2 composition does not broaden those root roles: guided
init/update/reconcile target one explicit ContextRoot, and pre-mutation bundle
source revalidation remains mandatory.
