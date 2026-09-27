# MarkItDown MCP through OpenClaw, 2026-09-26

This is the first integration-by-host evidence record for #147. It follows the
[host compatibility evidence](../../integrations-guide.md#host-compatibility-evidence)
requirements. The integration is the catalog's
[`markitdown-mcp`](../../../integrations/entries/markitdown-mcp.json) entry.
The host is OpenClaw, exercised through its CLI and one headless agent turn
that converted one local file. Local paths are replaced with `<HOST_ROOT>`,
`<UV_DIR>`, or `<HOME>` in the captures, and the agent session ID is redacted.

Items marked *operator-observed* were seen during the run, but no capture of
them was kept.

## Tested versions and provenance

The versions and hashes below are in [the provenance capture](captures/10-provenance.txt),
which was taken after the run from the same install.

| Component | Version | Provenance |
|---|---|---|
| Platform | Windows 11 (`Windows-11-10.0.26200`) | Provenance capture. |
| OpenClaw | `2026.9.6 (eb377ac)` | npm `openclaw@2026.9.6`, installed into a private prefix. The lockfile integrity equals the registry's `dist.integrity`. The package names `openclaw/openclaw` as its repository and MIT as its license. It requires Node `>=24.16.0 <25 \|\| >=26.1.0`. *Operator-observed:* npm skipped the package's install scripts. |
| Node.js | `v24.21.0` win-x64 | Official zip. Its SHA-256 equals the `SHASUMS256.txt` line shown in the capture. |
| markitdown-mcp | `0.0.1a7` | PyPI, source `microsoft/markitdown`. The capture lists PyPI's published file hashes. The installed version appears in [the uninstall capture](captures/09-pip-uninstall.txt). The installed wheel was not hash-pinned. It was installed with uv into an isolated Python 3.12 virtual environment. |
| markitdown | `0.1.7` | The release the catalog entry's evidence cites; the installed version is in the uninstall capture. *Operator-observed:* the resolver first chose `0.1.8`, the operator pinned `0.1.7`, and `uv pip check` then reported no conflicts. |
| Agent model | `anthropic/claude-sonnet-5` | Runs through OpenClaw's bundled `claude-cli` runtime, which launches the operator's logged-in Claude Code CLI ([config](inputs/exec-config.json), [result](captures/06-agent-exec.json)). |

`MARKITDOWN_ENABLE_PLUGINS` was unset in the capture environment. The server
was configured with a tool filter that includes only `convert_to_markdown`
([show](captures/04-mcp-show.txt)).

## Procedure

All commands used one dedicated `OPENCLAW_STATE_DIR`. *Operator-observed:* the
directory was newly created for this test.

1. `openclaw mcp add markitdown --command <HOST_ROOT>\md-venv\Scripts\markitdown-mcp.exe --cwd <HOST_ROOT>\fixtures --include convert_to_markdown --timeout 60 --connect-timeout 60`
   ([capture](captures/01-mcp-add.txt)). OpenClaw probes a server before saving
   it. *Operator-observed:* an earlier attempt without `--connect-timeout`
   failed with "did not complete initialize within 5s". The later add succeeded.
2. Health check: `openclaw mcp probe markitdown --json`
   ([capture](captures/02-mcp-probe.json)). Then `mcp doctor`, `mcp show`, and
   `mcp list` ([doctor](captures/03-mcp-doctor.txt),
   [show](captures/04-mcp-show.txt), [list](captures/05-mcp-list.txt)).
3. One agent turn: `openclaw agent exec --config inputs/exec-config.json --state-dir <state> --cwd <HOST_ROOT>\fixtures --message-file task.md --no-auth-env-only --json --timeout 300`
   ([config](inputs/exec-config.json), [prompt](inputs/task.md),
   [fixture](inputs/proof.txt), [result](captures/06-agent-exec.json)).
4. Uninstall: `openclaw mcp unset markitdown`, `openclaw mcp list`, then
   `uv pip uninstall markitdown-mcp markitdown`
   ([unset](captures/07-mcp-unset.txt),
   [list after](captures/08-mcp-list-after-unset.txt),
   [pip](captures/09-pip-uninstall.txt)).
5. State inspection after uninstall
   ([capture](captures/11-state-after-uninstall.txt)). It covers:
   - the file list of the state directory
   - whether each config file still mentions the server
   - row counts in credential-like SQLite tables
   - SQLite rows that mention the server
   - a byte search of the state files for common token markers
   - the count of running `markitdown` processes

## Record

| Field | Observed |
|---|---|
| Tested host surface | OpenClaw CLI `2026.9.6 (eb377ac)`: `openclaw mcp add/probe/doctor/show/list/unset` and one headless `openclaw agent exec` turn using the `claude-cli` runtime, converting one local file. The Gateway, channels, interactive sessions, and HTTP or HTTPS conversions were not tested. |
| Test date | 2026-09-26 (US Pacific). The probe capture's UTC timestamp is 2026-09-27. |
| Credential model | MarkItDown uses no credentials, and the saved OpenClaw config contains none. The model turn used the operator's existing Claude Code login, which `--no-auth-env-only` lets OpenClaw discover. The state inspection found zero rows in every credential-like table of the state SQLite databases, and no common token markers in the state files. Claude Code's own credential storage was outside this test and was not inspected. |
| Egress | The only conversion used a `file:` URI. The result reports `anthropic` as the provider for the model turn. Network traffic was not monitored, so no destination, including any background traffic from OpenClaw or Claude Code, is measured here. |
| Side effects | The tool is read-only in the catalog. It was called once, on the synthetic fixture. The state inspection lists the files OpenClaw left in its state directory: `openclaw.json`, `openclaw.json.bak`, SQLite databases, plugin skill files, and lock files. `exec-config.json` is the operator's own copy. No destructive command was run. Writes outside the state directory were not monitored. |
| Confirmation gates observed | The probe reports `codexApprovalMode: auto` and "tools have no safety annotations; calls require approval in prompting session postures". The headless `agent exec` result shows a successful tool call and no confirmation event, and the command returned without operator input. The catalog requires confirming the exact URI before each conversion (`read_sensitive`), so on this surface that confirmation has to come from the operator. Here, the operator named the one fixture file in [the prompt](inputs/task.md). |
| Health check | `openclaw mcp probe markitdown --json` returned `"tools": ["markitdown__convert_to_markdown"]`, a per-server `"tools": 1`, and empty `diagnostics`. `openclaw mcp doctor` printed `markitdown: ok`. |
| Tool call | `toolSummary.tools` lists `ToolSearch` (Claude Code's deferred-tool loader) and `mcp__markitdown__convert_to_markdown`, with 0 failures. The reply begins with the fixture's text unchanged, followed by the requested `TOOL_USED` line and an unrelated note (see below). |
| Uninstall | `openclaw mcp unset markitdown` removed the entry, and `mcp list` then reported no managed servers. `uv pip uninstall` removed both packages. The state inspection found no running `markitdown` process. **Residue:** `openclaw.json.bak` still names the removed server, and SQLite rows in the agent and state databases mention it. Delete the state directory if these must not persist. No credential was issued, so nothing needed revoking. |
| Evidence location | This directory. |

## Host isolation finding

The `claude-cli` runtime launches the user's own Claude Code CLI. The captured
reply ends with a note about a memory-sync pull. That note came from the
operator's personal Claude Code configuration, not from OpenClaw or MarkItDown.
*Operator-observed:* the operator's settings, which are not published, define
the session-start hook that does this sync. The reply is kept verbatim apart
from the session ID. Anyone repeating this test should expect their own Claude
Code configuration, including hooks, to apply inside the OpenClaw turn unless
they use a separate Claude Code profile.

## Limits

This record covers one integration, one host version, one platform, one
headless turn, one local fixture, and only the `claude-cli` runtime. HTTP and
HTTPS conversions, the Gateway, OpenClaw's embedded runtime with API-key
providers, and other operating systems were not tested.
