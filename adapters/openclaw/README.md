# OpenClaw adapter

This adapter has been tested against `OpenClaw 2026.7.1-2 (0790d9f)`. It
combines copied portable skills with an external OpenClaw plugin that binds a
configured project alias to a plugin-owned subagent working directory. Support
is first-class for the explicit, multi-turn, proposal-producing lifecycle
documented here. Proposal application stays outside the privileged plugin
runtime and inside an operator-controlled trusted shell. The adapter does not
claim OpenClaw project hooks or automatic memory synchronization.

## Keep the two workspaces separate

Use the Context OS repository as the lifecycle execution directory and a
different, private directory as OpenClaw's workspace. OpenClaw treats its
workspace as private memory, not as a sandbox. `SOUL.md`, `USER.md`, `MEMORY.md`,
and `memory/` belong there; do not add them to the repository merely to make
OpenClaw work.

The plugin starts each lifecycle subagent with the configured repository root
as its actual process working directory and `lightContext: true`. OpenClaw can
therefore append the repository-root `AGENTS.md` to that run while skill
discovery remains in the separate private workspace. The lifecycle system
prompt explicitly forbids reading or quoting the separate OpenClaw workspace,
`USER.md`, `MEMORY.md`, or private host memory. It does not load repository
`SOUL.md`, `USER.md`, or `MEMORY.md` as private workspace memory.

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
`check` mode. Run `sync` again only after reviewing the new source commit. The
stable version tested here did not discover the same skills reliably through
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

## Install and configure the plugin

Package and install the external plugin from the exact reviewed source commit:

```bash
cd adapters/openclaw/plugin
npm test
npm pack
openclaw plugins install ./context-os-openclaw-adapter-0.1.0.tgz
```

Configure `plugins.entries.context-os.config` in OpenClaw's private state. Each
project key is an operator-chosen alias whose `root` must be absolute and
canonical:

```json
{
  "projects": {
    "my-context": {
      "root": "/absolute/path/to/my-context"
    }
  },
  "runTimeoutSeconds": 600
}
```

The plugin resolves the configured root and requires regular non-symlink
`AGENTS.md` and `scripts/contextos.sh` files beneath it. Calls accept only the
alias; they cannot replace it with a per-call repository or proposal path. The
plugin config has no shell or executable path because the privileged plugin
runtime deliberately does not execute repository-writable scripts.

## Run the lifecycle

An authorized messaging operator can use the native command:

```text
/contextos my-context setup
/contextos my-context start
/contextos my-context update
/contextos my-context end
/contextos my-context continue <session-key> <response>
```

The same plugin exposes operator-scoped Gateway methods for automation:

```bash
openclaw gateway call contextos.run \
  --params '{"alias":"my-context","action":"setup"}' --json
openclaw gateway call contextos.wait \
  --params '{"runId":"<returned-run-id>","ownershipToken":"<returned-ownership-token>","timeoutMs":600000}' --json
openclaw gateway call contextos.result \
  --params '{"sessionKey":"<returned-session-key>","ownershipToken":"<returned-ownership-token>"}' --json
openclaw gateway call contextos.continue \
  --params '{"alias":"my-context","sessionKey":"<returned-session-key>","ownershipToken":"<returned-ownership-token>","message":"<response>"}' --json
```

`contextos.run` accepts only `setup`, `start`, `update`, or `end`, starts a
plugin-owned subagent with the configured root as `cwd` and lightweight context,
and instructs the model to stop after reporting any proposal path, digest, and
diff. `wait` and `result` accept only run and session identifiers created by the
same plugin process and the random ownership token returned by `contextos.run`.
For the questions and confirmations required by setup, update, and end,
`contextos.continue` resumes that owned session with an operator response; it
has `operator.write` scope and requires the same project alias and ownership
token. The native command returns the
exact continuation syntax after each non-start turn and binds continuation to
the initiating sender and conversation. Gateway automation is a trusted
control-plane surface: keep its credential, ownership tokens, and returned
session keys private. Continue
until the agent reports the complete proposal. Session ownership is
intentionally process-local and bounded to 128 workflows; if the Gateway
restarts or reaches that bound, restart it and rerun the lifecycle command
instead of attempting to resume the old session key.

Do not use `openclaw acp client --cwd <repository>` as the lifecycle binding.
In the tested release ACP represents that value as session context rather than
as the child tool process working directory; it is not the trusted root bridge
implemented by the plugin. The ordinary Gateway `agent` RPC also rejects an
operator-supplied `cwd`, which is reserved for plugin-owned subagent runs.

## Review and apply

Context OS proposal/apply remains the write-safety boundary. Independently read
the exact repository proposal path, verify its stored workflow and lowercase
SHA-256 digest, and review every stored diff. Do not approve from model prose
alone. Application is intentionally unavailable through `/contextos` and the
Gateway plugin.

From an operator-controlled trusted shell at the configured repository root,
apply the exact reviewed proposal:

```bash
bash scripts/contextos.sh apply <proposal> \
  --confirm <proposal-digest> --runtime openclaw
```

The trusted shell, not OpenClaw's privileged plugin runtime, selects the reviewed
proposal path. The kernel revalidates its digest, shape, target hashes, paths,
and lock before writing and records the OpenClaw-attributed receipt. There is no
`contextos.apply` Gateway method and no native `/contextos ... apply` command.

## Boundaries and diagnostics

- A plugin-owned `cwd` is a reliable default working directory, not OS-level
  containment. A model or executable could explicitly access another path.
  The selected provider or CLI backend's permissions govern tools it runs
  internally. OpenClaw's exec policy governs OpenClaw's own exec surface and
  does not constrain tools internal to an external CLI backend. Configure every
  active tool surface with least privilege. The trusted-shell apply step is a
  separate operator boundary, not an OpenClaw tool permission.
- OpenClaw skill allowlists control model and command visibility. They are not
  shell-execution authorization. If an agent skill allowlist is present,
  include all eight lifecycle skill names or omitted commands will not be
  visible to that agent.
- This adapter installs no project hook and makes no blocking-hook claim.
- The must-not-fire hook control is an empty Context OS hook inventory. The
  plugin can create and continue lifecycle conversations but cannot apply a
  proposal or execute the repository kernel through its privileged runtime.
- Native OpenClaw memory is private host state and is not synchronized with
  repository state automatically.
- Use `openclaw doctor --lint --json` for a read-only native diagnostic. Exit 1
  can mean lint findings. Do not use `--fix` as a validation step because it can
  modify host state.
- Context OS `doctor` resolves descriptor probe binaries but never executes
  them. Native OpenClaw diagnostics remain an explicit operator action.

The installed-version conformance fixture is opt-in. Set
`CONTEXTOS_OPENCLAW_BIN` to the exact tested executable and run:

```bash
python -m unittest tests.test_openclaw_conformance
```

The authenticated live promotion harness additionally requires a sanitized
disposable repository, separate unused state and private-workspace paths, an
authenticated Claude CLI, explicit external-model-egress acknowledgement, and
manual approval of every exact proposal digest. See the harness help for its
current arguments:

```bash
python adapters/openclaw/live_conformance.py --help
```

The harness runs the authenticated Claude CLI in `--safe-mode` so user hooks,
plugins, auto-memory, and other customizations cannot add private host context
to the synthetic fixture. It must prove the plugin-owned subagent `cwd`, private
workspace separation with private-memory canaries, allowlist and removed-apply
must-not-fire controls, retained multi-turn conversation state, wrong-digest
rejection, independently verified proposal review, trusted-shell deterministic
apply, and redacted evidence for the exact candidate commit.
