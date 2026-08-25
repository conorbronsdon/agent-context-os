# Choose an optional integration

Integrations are opt-in extensions, not part of the core session loop. Start with a concrete outcome, choose at most one new trust boundary at a time, and read its full generated entry in [`references/integrations.md`](../references/integrations.md).

Nothing in this guide installs, activates, authenticates, or grants permissions to an integration.

## Outcome chooser

| I want to… | Candidate | First boundary to review |
|---|---|---|
| Browse and install reusable agent skills | [Agent Skills](../references/integrations.md#agent-skills) | Replacement or removal of an existing local skill |
| Add a standalone lifecycle/workspace package | [Agent Workspace](../references/integrations.md#agent-workspace) | Local state writes and optional cleanup actions |
| Discover creator-oriented tools without installing one | [AI Tools for Creators](../references/integrations.md#ai-tools-for-creators) | Listings can drift and are not endorsements |
| Inspect repositories, issues, pull requests, or CI context | [GitHub MCP](../references/integrations.md#github-mcp) | Private-repository reads, public comments, branch or file changes, and enabled toolsets |
| Read or update product work in Linear | [Linear MCP](../references/integrations.md#linear-mcp) | Workspace-wide reads and remote issue, project, relationship, or comment changes |
| Search a personal reading library or organize highlights | [Readwise MCP](../references/integrations.md#readwise-mcp) | Full-library indexing, sensitive reading history, bulk edits, and highlight deletion |
| Read calendar, email, Drive, or Sheets data | [Google Workspace CLI](../references/integrations.md#google-workspace-cli) | OAuth identity, sensitive reads, and the CLI's broader write-capable surface |
| Search or change a Notion workspace | [Notion MCP](../references/integrations.md#notion-mcp) | OAuth, sensitive and connected-source reads, remote writes, and overwrite-capable updates |
| Coordinate Gemini work with a persistent issue graph | [Beads for Gemini CLI](../references/integrations.md#beads-for-gemini-cli) | User-global defaults, remote sync, and force overwrite |
| Search meeting notes or retrieve transcripts | [Granola MCP](../references/integrations.md#granola-mcp) | OAuth, sensitive reads, retention, and participant consent |
| Let an agent work with an Obsidian vault | [Obsidian CLI](../references/integrations.md#obsidian-cli) | Broad command/eval surface and implicit vault/file targeting |
| Manage Substack drafts or publish Notes | [Substack MCP](../references/integrations.md#substack-mcp) | Session credentials, sensitive analytics, and immediate public Notes |
| Read or update a mounted Markdown vault | [Tolaria MCP](../references/integrations.md#tolaria-mcp) | Sensitive vault reads and full-note overwrite |
| Convert an explicitly selected document or URI to Markdown | [MarkItDown MCP](../references/integrations.md#markitdown-mcp) | Local-file and network reads through an unauthenticated server process |
| Export reviewed Markdown to DOCX, PDF, EPUB, or HTML | [Pandoc](../references/integrations.md#pandoc) | Sensitive local or network reads, output overwrite, and PDF-engine execution |

The obsolete checked-in `gws mcp` configuration was removed. The current Google Workspace path uses the reviewed CLI setup in [`references/google-workspace-cli-setup.md`](../references/google-workspace-cli-setup.md); it is still opt-in and is not pre-approved by the command adapters.

## Activation checklist

For the selected entry:

1. Read its current source and every linked evidence page.
2. Confirm the supported host and whether installation is project- or user-scoped.
3. List the exact credentials, local paths, accounts, vaults, or workspaces it can reach.
4. Start with the least privilege and the narrowest read-only health check available.
5. Require a separate confirmation for sensitive reads, writes, remote writes, publish, overwrite, deletion, arbitrary execution, OAuth, or destructive actions when the catalog marks them.
6. Record how to disable or uninstall it before relying on it.
7. Re-run `bash scripts/validate-all.sh --workspace` after changing tracked
   configuration.

Do not infer safety from the word `verified`. In this repository it means the catalog metadata was checked against linked evidence on the stated date; it is not live authentication, an end-to-end test, or a guarantee about future upstream behavior.

## When no integration is the right choice

Keep the core filesystem workflow when a tool would duplicate data, widen access without a concrete task, require more credentials than the outcome warrants, or add a remote write where a local file is enough. Repository context, lifecycle skills, and manual links remain useful without any optional integration.
