# OpenCode adapter

Context OS supports the OpenCode CLI as a first-class repository-native host.
OpenCode discovers the root `AGENTS.md` and the four portable lifecycle skills
under `.agents/skills/`. This adapter adds typed commands under
`.opencode/commands/` so invocation does not depend on the model guessing a
skill name:

| Workflow | OpenCode command | Portable skill |
|---|---|---|
| Setup | `/context-setup` | `context-setup` |
| Start | `/context-start` | `context-start` |
| Checkpoint | `/context-update` | `context-update` |
| End | `/context-end` | `context-end` |

Start `opencode` from the Context OS repository root. No generated copy or
global installation is required. The command files are deliberately thin; the
portable skills remain the only workflow implementation.

## Safety and authorization

`/context-start` is read-only. Setup, update, and end create deterministic
proposals with `bash scripts/contextos.sh propose ...`; they do not authorize an
apply. Review the complete diff and digest, then explicitly approve that exact
proposal. The kernel rejects a wrong digest, a changed target, path traversal,
or a concurrent apply and records a receipt with runtime `opencode`.

OpenCode permissions are an independent host boundary. A denied tool remains
denied even if a command or model asks to use it, and permission to run shell or
edit tools is not approval of a Context OS proposal. Keep broad rules first and
narrow deny rules last because the last matching OpenCode permission wins. Do
not use `opencode --auto` for lifecycle work: it bypasses the review posture
this adapter assumes.

This repository ships no `opencode.json`. That avoids overwriting a user's model,
provider, MCP, agent, sharing, or permission configuration. It also ships no
OpenCode plugin or hook. `project_hooks` and `blocking_pre_tool_hook` therefore
remain `unsupported` in the runtime descriptor; the deterministic kernel is the
enforcement boundary.

## Data boundary

OpenCode's model route determines where repository context is sent. Free,
trial, and contributor routes may log prompts or use them for training. Use
those routes only for public or deliberately synthetic repositories. Choose a
provider and account whose data handling matches the workspace before opening
private context. Setup never chooses a model, provider, plugin, MCP server, or
sharing policy for you, and it does not launch OpenCode.

OpenCode has no Context OS native-memory bridge. Provider memory, chat history,
and machine-local state are not synchronized into repository state. Durable
continuity belongs in the reviewed Context OS files and receipts.

## Verification

Run deterministic checks with:

```bash
python -m unittest tests.test_opencode_conformance
bash scripts/validate-all.sh
```

The opt-in installed-client harness verifies an exact binary and version,
native `AGENTS.md`/skill discovery, the resolved typed-command templates, and a
read-only live command route that must produce a concrete tool event for the
exact skill. It cannot pass on a generic textual answer:

```bash
python adapters/opencode/live_conformance.py \
  --binary /exact/path/to/opencode \
  --expected-version 1.18.27 \
  --repo .
```

Add `--model <provider/model>` plus all acknowledgement flags printed by
`--help` to run the model-backed command checks in a disposable copy. Never use
a logged or training-enabled route for private repository material. The live
run is release evidence for the exact reviewed commit, not a required CI step.
See the [first-class promotion note](../../docs/releases/opencode-first-class.md)
for the shipped claim boundary.

Official behavior references:

- [Rules and `AGENTS.md`](https://opencode.ai/docs/rules/)
- [Agent Skills and skill permissions](https://opencode.ai/docs/skills/)
- [Custom commands](https://opencode.ai/docs/commands/)
- [Permissions](https://opencode.ai/docs/permissions/)
- [MCP servers](https://opencode.ai/docs/mcp-servers/)
- [OpenCode Zen data handling](https://opencode.ai/docs/zen/)
