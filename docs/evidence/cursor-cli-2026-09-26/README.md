# Cursor CLI live conformance, 2026-09-26

`evidence.json` is the create-only artifact from
`adapters/cursor/live_conformance.py`, unmodified. It records hashes of each
command's arguments and output, not the prompts or responses.

- Source commit: `fb761f824a1b3c16bc6769d0dca2f9a25f94bd4b`. This commit
  contains the deny-stream parser fix that the harness needed for this client.
- Cursor CLI: `2026.09.26-dd393fe`. The launcher `agent.cmd` has SHA-256
  `299eaddf3327768e7fcd64f29ad01747c740f7e316931575fb3cee617c92ccfc`, and the
  run was on Windows 11.
- Account: a paid Cursor plan, with privacy mode on in the CLI configuration.
  The prompts contained only synthetic fixture canaries.
- Configuration: a dedicated `CURSOR_CONFIG_DIR` whose `cli-config.json` was a
  copy of the operator's configuration with empty permission allow and deny
  lists. The operator's normal configuration allows `Shell(ls)`, which the
  harness rejects as a confound. The evidence records the dedicated file's hash.
- Result: all 14 controls passed, and the workspace cleanup completed.

## What the run established

The run checked, in its synthetic workspace:
- root and nested instruction canaries
- explicit-skill must-fire, with `.agents/**` reads and all shell commands denied
- implicit-skill must-not-fire
- read-only ask mode
- a write-capable headless mode without `--force`
- a project `deny` that rejects an attempted write under `--force`
- a scoped allowed write

The harness never invoked Cursor's built-in `/update`.

## Earlier attempts the same day

- **Harness bug:** a run from `3597a85` on CLI `2026.09.23-86fc751` failed the
  deny-precedence control. A manual reproduction showed that Cursor had denied
  the write. The stream reported it as `editToolCall` with a
  `writePermissionDenied` result. The model then tried a shell redirect, which
  was also blocked, with a `permissionDenied` result. The harness looked only
  for `writeToolCall` with `denied` or `rejected` keys, so it could not
  recognize the denial. The recorded stream is now the test fixture
  `tests/fixtures/cursor/deny-stream-2026.09.23-86fc751.jsonl`.
- **Version drift:** the CLI then updated itself to `2026.09.26-dd393fe`. A run
  pinned to the earlier version correctly stopped at the exact-version check.

## Limits

This is CLI evidence only; it is not IDE evidence. The limits in
[the adapter README](../../../adapters/cursor/README.md) still apply:
- The root, nested, and rule prompts mention the instructions, so they do not
  isolate automatic discovery from a prompted read.
- One Windows run on one CLI build.
- Cursor support remains experimental until the IDE surface and the other
  promotion requirements have evidence.
