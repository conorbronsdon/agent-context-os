# Cross-runtime architecture

Context OS guarantees equivalent lifecycle state transitions across supported
runtimes. It does not claim identical command syntax, hook timing, permission
models, tool names, or native memory.

## Layers

1. **Repository state:** `identity/`, `projects/`, `state/`, and `sessions/` are
   the durable, reviewable source of truth.
2. **Portable intent:** `.agents/skills/context-*` gathers facts and asks for
   judgment without owning mutation mechanics.
3. **Deterministic kernel:** `python3 -m contextos` owns paths, rendering,
   invariants, proposals, locks, optimistic hashes, applies, and receipts.
4. **Runtime adapters:** `.claude/`, `.codex/`, and `adapters/hermes/` map host
   discovery and hooks to the portable layers.
5. **Conformance:** dependency-light tests assert exact state transitions;
   opt-in launch tests exercise installed host discovery without hiding skips.

## Commands

```text
python3 -m contextos start [--now ISO_TIMESTAMP]
python3 -m contextos propose setup|update|end --input payload.json [--now ISO_TIMESTAMP]
python3 -m contextos apply proposal.json --confirm SHA256 --runtime claude|codex|hermes
python3 -m contextos install --runtime claude|codex|hermes
python3 -m contextos doctor [--runtime claude|codex|hermes]
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

`runtimes/*.json` declares host capabilities as `native`, `adapter`,
`advisory`, or `unsupported`. Adapters may improve presentation or catch errors
earlier, but unsupported hooks never weaken kernel enforcement. Hermes copied
skills can drift, so installation and `doctor` report that boundary explicitly.

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
