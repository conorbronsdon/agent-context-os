# Devin CLI hook, allowlist, and lifecycle evidence

These are synthetic fixtures, not personal-context sessions. The final hook run
used source `24e77a398dfbd02be98ccbc5992d68949e52aa7f` and the final lifecycle
run used `f36d2c2498c2f92c2914009c174d553222714f48`. Both used Devin CLI
`3000.11.3` with the binary hash recorded in each artifact, the `swe-2-high`
model selection, Normal mode, and Linux. Between the two commits the lifecycle
harness is unchanged; the only change to its fixture is that
`.devin/hooks.v1.json` passes the `post-write` event name instead of `pre-write`
to the same `PostToolUse` check. Each run cloned the exact source
commit. Artifacts keep control results, booleans, versions, and hashes. Raw
responses, temporary paths, and credentials are not included.

## Passing runs on the final source

[Hooks and skill allowlists](hooks-24e77a3.json) passed every gate:

- Devin ran the shipped `SessionStart` and `PostToolUse` hooks. A probe hook in
  the ignored `.devin/config.local.json` logged each event with
  `DEVIN_PROJECT_DIR` set.
- The SessionStart reminder and the `state/current.md` write reminder each
  appeared as a system step Devin injected; the write reminder came after the
  write call. A write to `allowed/probe.txt` got no reminder.
- With `.devin/hooks.v1.json` removed, the probe still ran and neither reminder
  appeared.
- An exit-2 probe `PreToolUse` hook blocked a write. The write's observation
  carried the probe's rejection, and the file was not created.
- `/contextos-devin-allowlist-negative` expanded and made exactly one shell
  call, `bash allowlist-marker.sh`, which Normal mode rejected; the marker file
  was not created. `/contextos-devin-allowlist-control`, the same skill plus
  `allowed-tools: [exec]`, expanded and ran exactly that command once, with
  exit 0.

[Lifecycle](lifecycle-f36d2c2.json) passed setup, start, update, end, and a
fresh-session handoff with the shipped hooks active. Each phase expanded the
shipped `context-*` skill. Setup, update, and end each produced exactly one
proposal containing the requested synthetic content. An external operator (the
Devin session that ran the harness, outside the Devin CLI process) read each
review file and wrote the exact digest. The harness then rejected a wrong
digest, applied the approved one, checked one receipt with runtime `devin`, and
rejected the stale replay for update and end. The model made no `apply`
attempt. A new read-only session recovered the handoff value from `sessions/`.

The setup prompt supplies the identity file and the full dated
`state/current.md`, and the control checks only that the synthetic priority is
present. So this run shows that the skills and kernel carry operator-supplied
setup content through proposal and apply. It does not show the setup skill
choosing onboarding content itself, and it does not separately check that
`start` reports the workspace as initialized after setup. The fresh-session
handoff, run with the shipped SessionStart hook active, is indirect evidence of
initialization: the failed first attempt below shows that hook redirecting an
uninitialized workspace.

## Retained attempts

| Artifact | Outcome |
|---|---|
| [Hooks 1](hooks-attempt-1.json) | On `99c14d5` the write hook ran on `PreToolUse`. Devin ran it, but injects `additionalContext` only for `SessionStart`, `UserPromptSubmit`, and `PostToolUse`, so the reminder never reached the model. The write hook moved to `PostToolUse`. |
| [Hooks 2](hooks-attempt-2.json) | On `359995e` Devin injected the `PostToolUse` reminder, but the model acted on it instead of quoting it, and the control read the final reply. Controls now require the injected system step. |
| [Hooks 3](hooks-attempt-3.json) | Passed on `f435307`. Cross-model review then asked for the removed-hooks countercontrol, the probe's rejection in the blocked write's observation, and exact skill expansion and command for the allowlist; the final run includes them. |
| [Hooks 4](hooks-f36d2c2.json) | Passed on `f36d2c2`. Round-2 review found the negative allowlist control accepted any rejected `exec` mentioning the marker; it now requires expansion, exactly one exact command, and a Normal-mode rejection, and the write hook's event is named `post-write`. Superseded by the `24e77a3` run. |
| [Lifecycle 1](lifecycle-attempt-1.json) | On `f435307` every apply passed, but setup wrote only identity, so `state/current.md` kept its template date. The shipped SessionStart hook correctly reported an uninitialized workspace, and the handoff model ran `scripts/setup.sh` instead of answering. Setup now also writes a dated `state/current.md`. |

## Not established

No MCP execution, native-memory bridge, cloud handoff, sandbox, or native
Windows behavior. The shipped hooks are advisory; blocking was shown with a
synthetic probe, not a shipped policy. Cloud sessions remain experimental and
Review remains compatibility-only.
