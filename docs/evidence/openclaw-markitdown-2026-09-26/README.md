# MarkItDown MCP through OpenClaw, 2026-09-26

This is the first integration-by-host evidence record for #147. It follows the
[host compatibility evidence](../../integrations-guide.md#host-compatibility-evidence)
requirements. The integration is the catalog's
[`markitdown-mcp`](../../../integrations/entries/markitdown-mcp.json) entry. The
host is OpenClaw, running one real agent turn. The operator ran it on Windows 11
in a disposable state directory. Local paths are replaced with `<HOST_ROOT>` in
the captures.

## Tested versions and provenance

| Component | Version | Provenance |
|---|---|---|
| OpenClaw | `2026.9.6 (eb377ac)` | npm `openclaw@2026.9.6`, installed into a private prefix. Registry integrity `sha512-Ie0kyQSCVfFqixsgVg39vevUDq01Ch5u3+7Yu5Y3qARczmdAe+lzp8bVnO9925rHiW/+CFp70zfORCyPmCH31g==` matched the installed package. Repository `openclaw/openclaw`, MIT. npm skipped install scripts. |
| Node.js | `v24.21.0` win-x64 | Official zip; SHA-256 `158f7685b44de51f6c0df1d153526cbcd3e1bc739a8dfc607721cef75de9e541` matched `SHASUMS256.txt`. OpenClaw requires Node 24.16 or newer. |
| markitdown-mcp | `0.0.1a7` | PyPI, wheel SHA-256 `e38dce929a28b210a936396c4e1546b30b02601667c79dfa104afd6a7e3b818b`. Source `microsoft/markitdown`. Installed with uv into an isolated Python 3.12 virtual environment. |
| markitdown | `0.1.7` | Pinned to the release that the catalog entry's evidence cites. The resolver first chose `0.1.8`; the operator downgraded it and `uv pip check` reported no conflicts. |
| Agent model | `anthropic/claude-sonnet-5` | OpenClaw's bundled `claude-cli` runtime, which runs the operator's logged-in Claude Code CLI. |

`MARKITDOWN_ENABLE_PLUGINS` was unset. The server was configured with an
explicit tool filter that includes only `convert_to_markdown`.

## Procedure

Every command ran with `OPENCLAW_STATE_DIR` set to a new, empty directory.

1. `openclaw mcp add markitdown --command <HOST_ROOT>\md-venv\Scripts\markitdown-mcp.exe --cwd <HOST_ROOT>\fixtures --include convert_to_markdown --timeout 60 --connect-timeout 60`
   ([capture](captures/01-mcp-add.txt)). OpenClaw probes the server before it
   saves it. A first attempt with the default 5-second connection timeout
   failed: the server's cold start takes longer than 5 seconds, and OpenClaw
   saved nothing. A 60-second connection timeout succeeded.
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

## Record

| Field | Observed |
|---|---|
| Tested host surface | OpenClaw CLI `2026.9.6 (eb377ac)`: `openclaw mcp add/probe/doctor/show/list/unset` and one headless `openclaw agent exec` turn using the `claude-cli` runtime. The Gateway, channels, and interactive sessions were not tested. |
| Test date | 2026-09-26 (US Pacific). The probe capture's UTC timestamp is 2026-09-27. |
| Credential model | MarkItDown needs no credentials, and OpenClaw's config stored none. The model turn used the operator's existing Claude Code login, which Claude Code stores in the user profile, because `--no-auth-env-only` allows external CLI credential discovery. After the run, every credential table in the state directory's SQLite databases had zero rows (`auth_profile_store`, `auth_profile_state`, `mcp_oauth_stores`, `secret_store_entries`, `worker_environment_credentials`, and the device and gateway token tables), and no token strings were found in the state files. |
| Egress | The server was only used with a `file:` URI, so the conversion itself needed no network. The Claude Code child process reached Anthropic's API for the model turn. Network traffic was not monitored, so this record does not rule out other OpenClaw or Claude Code background traffic. |
| Side effects | The integration read one synthetic fixture and made no writes. OpenClaw wrote `openclaw.json`, an `openclaw.json.bak` backup, and SQLite session state inside the disposable state directory. There were no destructive actions. |
| Confirmation gates observed | **None fired.** The probe reports `codexApprovalMode: auto` and "tools have no safety annotations; calls require approval in prompting session postures". The headless `agent exec` turn called the tool without any prompt. The catalog requires confirming the exact URI before each conversion (`read_sensitive`). On this surface, that confirmation must come from the operator: here, the operator named the one fixture file in the prompt. |
| Health check | `openclaw mcp probe markitdown --json` returned `"tools": ["markitdown__convert_to_markdown"]`, a per-server `"tools": 1`, and empty `diagnostics`. `openclaw mcp doctor` printed `markitdown: ok`. |
| Tool call | `toolSummary.tools` lists `ToolSearch` (Claude Code's deferred-tool loader) and `mcp__markitdown__convert_to_markdown`, with 0 failures. The reply reproduced the fixture's Markdown exactly. |
| Uninstall | `openclaw mcp unset markitdown` removed the entry, and `mcp list` then reported no managed servers. `uv pip uninstall` removed both packages. No `markitdown-mcp` process remained. **Residue:** `openclaw.json.bak` still contains the removed server entry, and the session SQLite keeps the call history. Delete both or the whole state directory if the entry must not persist. There was no credential to revoke. |
| Evidence location | This directory. |

## Host isolation finding

The `claude-cli` runtime launches the user's normal Claude Code CLI, which
loaded the operator's global Claude Code settings, including hooks. A personal
session-start hook ran inside the OpenClaw turn and added an unrelated
memory-sync note to the reply (visible in [the result](captures/06-agent-exec.json)).
The result is kept verbatim. Anyone repeating this test should expect the
agent's context to include their own Claude Code configuration, unless they
run it under a separate Claude Code profile.

## Limits

This record covers one integration, one host version, one platform (Windows 11),
one headless turn, one local fixture, and the `claude-cli` runtime only. HTTP
and HTTPS conversions, the Gateway, OpenClaw's embedded runtime with API-key
providers, and other operating systems were not tested.
