# Hermes adapter

This adapter is experimental in v0.12. Deterministic repository, kernel, skill,
and hook conformance passes, but the installed Hermes 0.20.5 client did not
complete model inference during the retained live run. That attempt is not
counted as installed-client conformance.

Run `bash scripts/contextos.sh install --runtime hermes` from the repository root.
The primary skill path is the repository-local `.agents/skills/` directory.
For an isolated fixture, set a fresh `HERMES_HOME` and run `hermes skills trust
<fixture>` yourself. Check `hermes skills list --source local` in a new session
for all four short aliases and all four `context-*` cores. Do not enable a
partial set. If you instead copy skills into a Hermes profile, record the source
commit and SHA-256 of each of the eight `SKILL.md` files; compare all eight after
every source revision and refresh changed copies. Run `bash scripts/contextos.sh
doctor --runtime hermes` to inspect local runtime and descriptor state. Binary
discovery by doctor is not installed-client conformance.

Invoke `/context-setup`, `/context-start`, `/context-update`, and
`/context-end`. On Hermes Agent v0.21.4, `hermes skills list --source local`
reports that `/start` and `/update` are unavailable because built-ins take
those names and suggests `/skill start` and `/skill update`. Keep the short
aliases installed; their invocation still needs a live control.

## Live conformance

The first recorded attempts, and why none passed, are in
[`docs/evidence/hermes-live-2026-09-23/`](../../docs/evidence/hermes-live-2026-09-23/README.md).

From a clean, reviewed source commit, choose new sibling paths outside any
Context OS checkout and run:

```sh
python adapters/hermes/live_conformance.py prepare --source . --expected-commit <full-sha> --fixture <new-fixture> --home <new-hermes-home>
```

Follow the printed manifest. Set `HERMES_HOME` to the new home, supply provider
credentials through environment variables, and run `hermes skills trust
<fixture>` yourself. Do not copy a profile, credentials, or native memory into
the fixture. Check the eight local skills. Then run from the source checkout:

```sh
python adapters/hermes/live_conformance.py record --fixture <fixture> --home <new-hermes-home> --manifest <manifest-path> --evidence <new-evidence.json> --binary <hermes-executable> --model <model-id> --provider <provider> --expected-version 'Hermes Agent v0.21.4' --run-budget 120 --max-turns 20
```

`prepare` places two synthetic native-memory canaries under the fresh
`HERMES_HOME/memories/` path described by [Hermes memory documentation](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/memory.md).
`record` makes bounded `hermes chat --format stream-json --source tool` calls in
the fixture. It records version, commands, redacted events, discovery canaries,
skill views, read-only start, kernel proposals, no file changes before operator
apply, exact-digest apply receipts, wrong-digest and stale-target rejection,
memory separation,
and a byte-identical sentinel. The manifest stays outside the fixture, and
the canary edits are committed in the disposable fixture. Evidence names both
the source and fixture commits. By default, pass-through is limited to
`PATH`, `SYSTEMROOT`, `HOME`, `USERPROFILE`, `TEMP`, `TMP`, `APPDATA`,
`LOCALAPPDATA`, `HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY` (including lowercase
forms), `SSL_CERT_FILE`, `SSL_CERT_DIR`, `REQUESTS_CA_BUNDLE`,
`CURL_CA_BUNDLE`, and `HERMES_*` variables other than `HERMES_ACCEPT_HOOKS`.
For `openrouter`, it also passes `OPENROUTER_API_KEY`. Other provider keys
require an explicit `--env-allow NAME`.
The harness sets `HERMES_HOME` and `PYTHONDONTWRITEBYTECODE`. Evidence lists
passed variable names and API key names without values. Use `--env-allow NAME`
for an additional required variable. Inspect each printed proposal diff
and type its digest yourself. The evidence file is create-only and outside the
checkout. A failed control remains failed; prepare a new fixture for another
attempt. Model calls are opt-in and are not part of CI. The optional hook example
is recorded as unsupported unless separately exercised and reviewed.

For an operator watching another process, pass `--approval-dir <existing-dir>`
to `record`. Keep that directory outside the fixture and `HERMES_HOME`.
For each proposal, inspect `<phase>.review.txt`, then write only
the exact digest, without a newline, to `<phase>.approve`. The harness waits up
to 15 minutes for each approval and rejects any other content. Without this
option, it prints the proposal and asks for the digest interactively.

The optional [`hooks.example.yaml`](hooks.example.yaml) maps Hermes lifecycle
and pre-write events to the same read-only policy checks used by the other
runtimes. Merge it into user configuration only after reviewing its commands.
Kernel proposal/apply enforcement does not depend on these hooks.

The YAML example is POSIX-oriented. On Windows, use an equivalent command such
as `powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command
"$root = git rev-parse --show-toplevel; & (Join-Path $root
'scripts/context-os-hook.ps1') hermes pre-write"` for the pre-tool event (and replace `pre-write` with
`session-start` for the session event). Hermes hook policy remains advisory.

Hermes `MEMORY.md` and `USER.md` remain host-local. Never point the kernel at
them or mirror them into repository state automatically.
