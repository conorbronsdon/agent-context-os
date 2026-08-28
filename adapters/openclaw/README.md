# OpenClaw experimental adapter

This adapter has been tested against `OpenClaw 2026.7.1-2 (0790d9f)`. It
provides skills-first lifecycle support. It does not claim OpenClaw project
hooks, automatic memory synchronization, or messaging/gateway conformance.

## Keep the two workspaces separate

Use this repository as the execution directory and a different, private
directory as OpenClaw's workspace. OpenClaw treats its workspace as private
memory, not as a sandbox. `SOUL.md`, `USER.md`, `MEMORY.md`, and `memory/`
belong there; do not add them to this repository merely to make OpenClaw work.

When OpenClaw executes from the repository, it appends the repository-root
`AGENTS.md` to its instructions. It does not load execution-directory
`SOUL.md`, `USER.md`, or `MEMORY.md` as workspace memory.

## Synchronize the lifecycle skills

Use the adapter-owned synchronizer from the exact repository commit you intend
to run:

```bash
python adapters/openclaw/sync_skills.py sync --workspace <private-workspace>
python adapters/openclaw/sync_skills.py check --workspace <private-workspace>
```

It installs these eight directories from the repository's `.agents/skills/`
directory to `<private-workspace>/.agents/skills/`:

- `setup` and `context-setup`
- `start` and `context-start`
- `update` and `context-update`
- `end` and `context-end`

Synchronize all eight together. The short names are aliases for the
`context-*` cores. The synchronizer records the source Git SHA and per-file
SHA-256 inventory in the private workspace, preserves unrelated skills, and
reports stale or locally changed managed copies without modifying them in
`check` mode. Run `sync` again only after reviewing the new source commit.
The stable version tested here did not discover the same skills reliably via
`skills.load.extraDirs`, so this adapter does not recommend that shortcut.

OpenClaw's skill precedence puts `<workspace>/skills` ahead of
`<workspace>/.agents/skills`. A same-named skill in `skills/` can therefore
shadow a copied Context OS skill. Check the effective inventory after copying:

```bash
openclaw skills list --json
openclaw skills check --json
```

Run those inventory commands from the private workspace, not from the source
repository. All eight lifecycle skills should report source
`agents-skills-project`.

## Run the lifecycle

Keep the OpenClaw configuration pointed at the separate private workspace and
bind each agent turn to the repository execution directory with:

```bash
openclaw acp client --cwd <repository>
```

The ACP session records that directory while skill discovery continues to use
the separate `agents.defaults.workspace`. The ordinary Gateway `agent` RPC is
not a substitute: its `cwd` field is reserved for plugin-owned subagent runs and
is rejected for this workflow. Invoke the lifecycle explicitly in the ACP
session:

Treat the repository directory supplied in ACP session metadata as the exact
lifecycle execution root. A Bash or other tool may still start in the private
workspace. Each lifecycle skill must explicitly anchor repository reads,
writes, payloads, and `scripts/contextos.sh` commands to the supplied directory;
it must never substitute the private workspace or search an ancestor for a
repository. If the supplied directory is unavailable or does not contain both
`AGENTS.md` and `scripts/contextos.sh`, stop the lifecycle instead of falling
back.

```text
/skill setup
/skill start
/skill update
/skill end
```

Context OS proposal/apply remains the write-safety boundary. Review the exact
proposal and approve that digest before applying it.

## Boundaries and diagnostics

- OpenClaw skill allowlists control model and command visibility. They are not
  shell-execution authorization. Configure execution approvals separately. If
  an agent skill allowlist is present, include all eight lifecycle skill names
  or the omitted commands will not be visible to that agent.
- Workspace hooks are disabled until explicitly enabled. This experimental
  adapter installs no hook or plugin and makes no blocking-hook claim.
- The must-not-fire hook control is an empty Context OS hook/plugin inventory;
  proposal/apply remains the write boundary instead of a claimed OpenClaw hook.
- Native OpenClaw memory is private host state and is not synchronized with
  repository state automatically.
- Use `openclaw doctor --lint --json` for a read-only native diagnostic. Exit 1
  can mean lint findings. Do not use `--fix` as a validation step because it can
  modify host state.
- Context OS `doctor` resolves descriptor probe binaries but never executes
  them. Native OpenClaw diagnostics remain an explicit operator action.

The executable conformance fixture is opt-in because it requires the exact
tested OpenClaw binary. Set `CONTEXTOS_OPENCLAW_BIN` to that executable and run
`python -m unittest tests.test_openclaw_conformance`.

## Run the authenticated promotion gate

The operator-driven live harness requires a sanitized disposable repository,
separate unused state and private-workspace paths, an authenticated Claude CLI,
and the exact tested OpenClaw version. OpenClaw onboarding calls the existing
Claude subscription route `anthropic-cli`; the model runtime remains
`claude-cli`. The harness sends only its synthetic fixture to that external
model route and refuses to run without both egress and disposable-repository
acknowledgements.

Create `.context-os-live-disposable` containing exactly `disposable` in the
disposable repository, then run:

```bash
python adapters/openclaw/live_conformance.py \
  --binary <exact-openclaw-binary> \
  --claude-binary <exact-claude-binary> \
  --expected-version 'OpenClaw 2026.7.1-2 (0790d9f)' \
  --repo <sanitized-disposable-repository> \
  --state-dir <unused-openclaw-state-directory> \
  --private-workspace <unused-private-workspace> \
  --evidence <outside-those-directories>/openclaw-live.json \
  --port <unused-loopback-port> \
  --acknowledge-external-model-egress \
  --acknowledge-disposable-repo
```

On Windows, avoid the npm `.cmd` wrapper when driving ACP stdio. Invoke the
same installed release through Node instead:

```text
--binary <node.exe> --binary-arg <openclaw-package>/openclaw.mjs
```

The disposable repository must be at the same Git SHA as the harness source.
The harness validates config before egress, starts an isolated loopback
Gateway that inherits the authenticated Claude environment, selects the
`claude-cli/claude-sonnet-5` route, and verifies skill visibility and shell
denial with both `host: gateway`/`security: deny` and the isolated `deny-all`
execution-policy preset. It then selects `host: gateway`, `security: full`,
`ask: off`, and the `yolo` preset only for the explicitly acknowledged
disposable fixture. It drives each lifecycle prompt by speaking the same ACP
protocol directly to `openclaw acp`: initialize protocol v1, create a session
with the repository `cwd`, send the prompt, collect session updates, and wait
for the final stop reason. The direct NDJSON driver avoids the interactive
client's unreliable piped-input behavior on Windows. It
tests a wrong proposal digest and pauses for the operator to type every exact
approved digest. It never auto-approves a proposal digest. Its redacted JSON
evidence contains hashes and control results, not prompts, credentials, or raw
private paths.
