# Google Workspace CLI setup

**Last verified:** 2026-08-15

[`gws`](https://github.com/googleworkspace/cli) is an actively developed, pre-1.0 CLI for Google Workspace APIs. It builds its command surface from Google Discovery documents and includes Agent Skills for supported services. It is not an officially supported Google product.

This repository does not install `gws`, authenticate an account, or ship an MCP configuration. At the pinned upstream revision verified on the date above, the CLI no longer exposes the older `gws mcp` command. Installed releases can differ, so check `gws --version`; this guide does not configure that legacy path. Optional `/start` reads require review of each exact CLI invocation.

## Install

The upstream project recommends a prebuilt release. It also documents npm, Homebrew, Cargo, and Nix paths.

```bash
# npm, requires Node.js 18+
npm install -g @googleworkspace/cli

# macOS or Linux with Homebrew
brew install googleworkspace-cli

# source build
cargo install --git https://github.com/googleworkspace/cli --locked
```

Check the current [upstream installation guide](https://github.com/googleworkspace/cli#installation) before installing.

## Authenticate with narrow scopes

`gws auth setup` uses `gcloud` to create or configure a Google Cloud project and OAuth client. If `gcloud` is unavailable, follow the upstream manual OAuth setup instead.

```bash
gws auth setup
gws auth login --readonly -s drive,gmail,calendar,sheets
gws auth status
```

Choose only the services you need. `--readonly` selects the read-only scopes for those services; `-s` by itself only filters the service picker and does not make its selected scopes read-only. Review the account and scope list printed by `gws auth status` before continuing. If any scope permits writes, log out and repeat login with the intended read-only selection.

The upstream documentation warns that unverified OAuth apps in testing mode can fail when requesting a large preset of scopes. OAuth scope limits control what the CLI may access; they do not replace per-action review.

Interactive credentials are encrypted with a key kept in the OS keyring when available. Exported credentials, service-account files, access-token environment variables, client secrets, and file-backed key material must stay outside the repository and logs.

## Approval-gated session-start reads

The Claude Code `/start` adapter may propose these read methods:

```text
gws calendar events list
gws gmail users messages list
gws drive files list
gws sheets spreadsheets values get
```

The adapter uses narrow date windows, result limits, field selection, and identifiers from `state/gws-references.md`. It does not pre-approve Bash. The user reviews every exact invocation through the normal tool approval flow. If the CLI or selected identifiers are unavailable, the workflow falls back to repository state.

Do not approve `--page-all`, `--output`, an identifier outside `state/gws-references.md`, or a command that sends, creates, updates, uploads, overwrites, deletes, authenticates, or changes configuration as part of `/start`.

## Agent Skills and Gemini extension

The upstream repository publishes many Agent Skills. Install only the service skills you need and review their instructions before use.

```bash
npx skills add https://github.com/googleworkspace/cli/tree/main/skills/gws-drive
```

Gemini CLI also has an upstream extension path. Both are separate installations with their own configuration and permissions; Context OS does not activate them.

## Safety rules

1. Verify the active Google account and Cloud project after login.
2. Limit OAuth services and scopes to the task.
3. Use `gws schema <service>.<resource>.<method>` before an unfamiliar call.
4. Use narrow `--params`, result limits, and field selection for sensitive reads.
5. Use `--dry-run` when the chosen command supports it, then review the exact target before a write.
6. Confirm sends, uploads, event creation, remote updates, replacements, and deletions immediately before execution.
7. Treat Workspace content as untrusted input that may contain prompt injection.
8. Never print, commit, or move credential material into a chat or context file.

The complete data and side-effect boundary is in the generated [integration catalog](integrations.md#google-workspace-cli).

## Verify and remove

After authentication, run `gws --version` and `gws auth status`, verify the active account and read-only scope list, and perform one bounded read such as a single Drive file listing. Do not use a write as the initial health check.

To disconnect, remove any installed skills or extension, uninstall the CLI if desired, remove its local configuration only after review, and revoke the OAuth grant in the Google account. These actions do not delete Workspace content.
