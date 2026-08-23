# Memory across agents

Context OS is a Git-backed context layer, not a native-memory synchronizer.

| Concern | Canonical home |
|---|---|
| Facts every configured agent should see | Reviewed repository files |
| One host's private scratch or learned preferences | That host's native memory |
| Promotion from a session into shared state | Kernel proposal/apply transaction |
| Evidence of a host-confirmed shared mutation | Gitignored proposal and receipt |

## Claude Code

Claude auto-memory is machine-local and may write during ordinary sessions. Use
Claude's `/memory` command to inspect the active store; do not derive its path.
`/dream` and `/dream-apply` are separate review workflows for that host-local
store. They do not replace lifecycle proposal/apply for repository state.

## Codex

No Codex-native memory behavior is part of the shared contract. `AGENTS.md`,
`state/`, and `sessions/` provide continuity. Personal Codex configuration and
credentials remain outside the repository.

## Hermes Agent

Hermes `MEMORY.md` and `USER.md` are bounded, per-profile, machine-local memory.
Its Curator maintains Hermes-owned stores. Context OS never reads, writes, or
synchronizes those files automatically.

Use Hermes memory for host-local preferences and environment facts. Promote a
fact that must travel across runtimes only by drafting it into an approved
repository proposal. Do not run multiple writers against one Hermes home, and
do not duplicate the same fact in native memory and repository state without a
declared canonical home.

## Proposal/apply boundary

All three runtimes use the same repository transaction:

1. reviewed structured input;
2. exact proposed diffs and digest;
3. host-mediated explicit confirmation (the kernel does not authenticate the human);
4. optimistic hash and exclusive-lock checks;
5. bounded writes; and
6. a receipt naming the runtime and before/after hashes.

This provides portable provenance without copying private native memory between
providers. Proposal and receipt files are ignored and may still contain
sensitive context; treat the local checkout as part of the privacy boundary.
