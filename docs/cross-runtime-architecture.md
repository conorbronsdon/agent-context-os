# Cross-runtime architecture

Context OS guarantees equivalent lifecycle state transitions across supported
runtimes. It does not claim identical command syntax, hook timing, permission
models, tool names, or native memory.

## Layers

1. **Repository state:** `identity/`, `projects/`, `state/`, and `sessions/` are
   the durable, reviewable source of truth.
2. **Portable intent:** `.agents/skills/context-*` gathers facts and asks for
   judgment without owning mutation mechanics.
3. **Deterministic kernel:** `bash scripts/contextos.sh` owns paths, rendering,
   invariants, proposals, locks, optimistic hashes, applies, and receipts.
4. **Component inventory:** `components/manifest.json` assigns every tracked
   product, seed, and development path to one owner and defines the dependency
   closure shared by runtime selections. It is validated metadata, not a file
   materializer. See [the component model](component-model.md).
5. **Runtime adapters:** discoverable schema-v2 descriptors in `runtimes/` map
   each host surface to instructions, skills, lifecycle invocations, probes,
   capabilities, and evidence. Provider files remain in their adapter directories.
6. **Conformance:** dependency-light tests assert exact state transitions;
   opt-in launch tests exercise installed host discovery without hiding skips.

## Commands

```text
bash scripts/contextos.sh start [--now ISO_TIMESTAMP]
bash scripts/contextos.sh propose setup|update|end --input payload.json [--now ISO_TIMESTAMP]
bash scripts/contextos.sh apply proposal.json --confirm SHA256 --runtime RUNTIME
bash scripts/contextos.sh install --runtime RUNTIME
bash scripts/contextos.sh doctor [--runtime RUNTIME | --all]
```

`--now` exists for deterministic fixtures. Production calls use local time.

## Input contracts

Update requires `progress: [string]` and optionally accepts complete
`current_markdown`. End requires `what_happened: [string]` and accepts
`decisions`, `next_time`, and complete desired Markdown for state files that
materially changed. Setup accepts `files: {path: content}` and requires every
populated replacement path in `replace_populated`.

The kernel rejects absolute paths, traversal, setup writes outside approved
context roots, multiple or missing `Last Updated` lines, and no-op proposals.

## Best-effort transaction protocol

Proposal files contain exact after-content, unified diffs, and before/after
SHA-256 values. Their proposal digest covers the entire unsigned proposal. It
binds integrity; the host permission prompt supplies the human approval boundary.
Apply requires that exact digest, re-hashes every target, takes an exclusive
`O_EXCL` lock, writes using UTF-8/LF, and emits a receipt inside the rollback
boundary. Individual replacements are atomic; a multi-file batch is not
crash-atomic. A process kill can leave partial state and a stale lock; `doctor`
surfaces the lock and never deletes it silently.

Proposals and receipts can contain full state text. They remain local and ignored
by Git; `doctor` warns when artifacts are older than 30 days so the owner can
remove them after their audit or recovery value has expired.

The kernel never commits, pushes, calls an integration, or accesses native
memory. Those actions remain separate approval boundaries.

## Capabilities and degradation

`runtimes/*.json` declares capabilities per host surface as `native`, `adapter`,
`advisory`, or `unsupported`. `contextos/runtime_schema.py` is the authoritative
contract and deterministically generates `runtimes/schema.json`; validation
fails if the generated schema or README support table drifts. `generic` is a
reserved apply-receipt identity, never a discoverable or installable runtime.
Adapters may improve presentation or catch errors earlier, but unsupported hooks
never weaken kernel enforcement. Hermes copied skills can drift, so installation
and `doctor` report that boundary explicitly.

Binary probes are declarative, resolution-only checks. `doctor` may resolve the
listed executable candidates with `PATH`, but runtime descriptors cannot supply
arguments or cause a process to execute. Native diagnostic execution requires a
separate code-owned trust policy.

## Conformance policy

Every lifecycle mutation needs:

- a successful transition test;
- an exact-confirmation rejection;
- a stale-target rejection;
- a concurrent-lock rejection;
- path-containment controls; and
- a must-not-change assertion for unrelated files.

Runtime launch tests are opt-in because CI may not have installed clients or
authentication. A skip is visible and is not counted as evidence of parity.
