# Codex onboarding

Codex uses the same repository state and deterministic lifecycle kernel as the
other supported runtimes. The portable boundary is `AGENTS.md`,
`.agents/skills/`, `contextos/`, and the repository state directories.

## Set up

```bash
bash scripts/setup.sh --agent codex
```

Then launch Codex from the repository root and explicitly invoke `$setup`.
Use `$start`, `$update`, and `$end` for the daily loop. The namespaced
`$context-*` forms remain compatibility aliases.

Setup records a gitignored local runtime selection. Inspect it with:

```bash
python3 -m contextos doctor --runtime codex
```

## Deterministic writes

The skills do not directly mutate lifecycle state. They create reviewed input,
run `python3 -m contextos propose`, present exact diffs, and run `apply` only
after the user approves the displayed digest. The receipt is the portable proof
of which paths and hashes changed. The kernel never commits or pushes.

## Host-specific boundaries

| Capability | Shared contract | Codex path |
|---|---|---|
| State, sessions, and decisions | Yes | Lifecycle kernel and skills |
| Explicit lifecycle names | Yes | `$setup`, `$start`, `$update`, `$end` |
| Project instructions | Semantically shared | Hierarchical `AGENTS.md` discovery |
| Project hooks | Event-specific | Trusted `.codex/hooks.json` adapter |
| MCP | Configuration-specific | Keep auth and credentials outside tracked files |
| Native memory | No | Repository state remains the shared SSOT |

Codex now supports repository hooks. This template includes advisory
`SessionStart` and `PreToolUse` mappings, but hook trust and event semantics are
host-specific. Project-local hooks run only after the `.codex` layer is trusted.
Proposal/apply does not rely on a hook firing.

The template intentionally avoids checked-in model, sandbox, approval, MCP, or
credential overrides. Review any future `.codex/config.toml` like infrastructure.

## Optional import

Codex `/import` can help migrate selected supported configuration and recent
history, including up to 50 recent chats from the last 30 days where the current
client supports it. It is not the runtime path for Context OS or an account-wide
importer. Preview every imported item and resolve duplicates against repository
SSOTs.

## Verify

```bash
python3 -m contextos doctor --runtime codex
bash scripts/validate-all.sh
```

Local validation proves kernel transitions and adapter contracts. Opt-in runtime
smoke tests report a visible skip when an installed or authenticated host is not
available; they never turn a skipped runtime into a parity claim. Validation
cannot prove the behavior of every installed Codex version.

Official references:

- [Codex `AGENTS.md` discovery](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
- [Codex skills](https://learn.chatgpt.com/docs/build-skills)
- [Codex hooks](https://learn.chatgpt.com/docs/hooks)
