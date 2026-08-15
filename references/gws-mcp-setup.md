# Google Workspace integration status

**Last verified:** 2026-08-15

The template previously tracked a `.mcp.json` entry that ran `gws mcp`. That path is obsolete: the current [`googleworkspace/cli`](https://github.com/googleworkspace/cli) release line no longer exposes the built-in MCP subcommand used by the old configuration. The tracked entry, broad pre-approved tool grants, and automatic session-start queries were removed.

Do not recreate the old configuration from repository history. It can fail at startup, and an older installed/authenticated binary can expose sensitive Gmail, Calendar, Drive, and Sheets data merely by trusting the workspace.

The Google Workspace CLI remains a separate, actively developed command-line project. This repository does not currently ship, install, authenticate, or pre-approve it as an agent integration.

Before a replacement is added here, it should go through the same catalog review as other integrations:

1. Pin current upstream evidence and supported versions.
2. Declare exact services, accounts, OAuth scopes, credential storage, and retention.
3. Separate sensitive reads from local writes, remote writes, sending, deletion, and sharing.
4. Expose a narrow read-only health check before any mutation.
5. Require explicit activation instead of a tracked live client configuration.
6. Document disable, token-revocation, and uninstall behavior.

Use the [integration chooser](../docs/integrations-guide.md) for currently cataloged options. A future Google Workspace entry should be added to `integrations/catalog.json` only after its actual current tool surface and safety gates are verified.
