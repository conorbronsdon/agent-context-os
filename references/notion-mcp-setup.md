# Notion MCP legacy setup note

**Last verified:** 2026-08-15

This repository does not currently ship, install, authenticate, configure, or pre-approve a Notion integration. The older instructions on this page targeted the open-source `@notionhq/notion-mcp-server` package. Notion now directs new users to its hosted MCP endpoint at [`https://mcp.notion.com/mcp`](https://developers.notion.com/guides/mcp/get-started-with-mcp), and the open-source repository is no longer the recommended maintained path.

The old install and credential instructions have been removed rather than presenting an uncataloged write-capable integration as ready to use.

## Before a future Notion entry is added

Add it to `integrations/catalog.json` first, with dated primary evidence and typed disclosures for:

- OAuth and credential storage;
- the exact workspace/page scope and sensitive reads;
- create, update, move, archive, delete, comment, and publish-like effects;
- remote writes and third-party data processing;
- supported hosts and configuration destinations;
- a least-privilege health check; and
- concrete disable, revoke, and uninstall steps.

Then generate `references/integrations.md`, review the exact configuration diff, and enable it only after explicit approval. Until that catalog entry exists, follow the [integration chooser](../docs/integrations-guide.md) for the currently reviewed options.
