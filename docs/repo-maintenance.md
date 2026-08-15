# Repository maintenance

Context is useful only when it is current, scoped, and safe to load. Maintenance should remove drift rather than create routine file churn.

## Every working session

Use `/start` and `/end` in Claude Code, or `$context-start` and `$context-end` in Codex. The close workflow proposes a handoff before updating shared state.

Before committing:

```bash
bash scripts/validate-all.sh
git diff --check
git status --short
```

Review the actual diff. Validation catches structure and known invariants, not an incorrect personal fact or an overly broad instruction.

## Weekly review

Review `state/current.md`, `state/weekly-priorities.md`, `state/blockers.md`, and recent files under `sessions/`.

- Remove completed threads from the active view.
- Move durable decisions into `state/decisions.md`.
- Confirm dates and people attached to open commitments.
- Keep `state/current.md` short enough to load every session.
- Check whether browser-project copies need a manual refresh.

`state/current-log.md` records the prior real date when `current.md` advances. It is a small audit trail, not a second copy of current state.

## Monthly review

Review the most frequently loaded identity, project, routing, and skill files.

- Verify claims that affect money, access, deadlines, credentials, or external relationships.
- Remove duplicate facts and keep one canonical source.
- Archive completed project material that no active route needs.
- Inspect `.gitignore`, recent commits, and tracked files for sensitive migration artifacts or exports.
- Review enabled integrations against `references/integrations.md`, including scopes, connected accounts, current evidence, and whether each integration is still needed.
- Run a narrow health check for integrations you still rely on.

Do not refresh timestamps without a content review. A recent date should mean someone checked the file.

## Staleness convention

Context files should have a `**Last Updated:**` line near the top. When a file passes its configured threshold, flag it before relying on it. The default general threshold is 90 days, while frequently used state files have shorter lifecycle-specific thresholds.

Choose one of four outcomes:

1. keep it after verifying it is still current;
2. update the changed facts;
3. archive it and remove active routes; or
4. delete it only when the user approves and history is not needed.

## Archival workflow

Prefer an `archive/` directory inside the relevant topic or project. Before moving a file:

1. find inbound links and routes;
2. decide whether callers need a replacement source;
3. move the file without mixing unrelated edits;
4. update or remove links;
5. run the full validator; and
6. describe the archive decision in the commit.

Repository history is not a reason to leave stale material in active context paths.

## Browser-project sync

claude.ai project knowledge is a manual consumer copy. After changing a file used by a browser project, re-upload only the changed, relevant files and remove the previous copies. See [claude-projects-sync.md](claude-projects-sync.md).

Do not describe this as automatic synchronization. Record any external copy that requires periodic refresh in the relevant project context or checklist.

## Optional integration review

The generated catalog is a discovery and risk document. It does not activate or continuously verify an integration.

Before enabling or renewing one:

- confirm the exact account and workspace;
- select the narrowest useful scopes and services;
- inspect sensitive-read and remote-write boundaries;
- require confirmation for publish, overwrite, deletion, or arbitrary execution;
- run the documented health check; and
- know how to revoke access and uninstall without deleting user data.

If upstream behavior changed since `last_verified`, update `integrations/catalog.json`, regenerate `references/integrations.md`, add regression coverage when needed, and review the diff.

## Changelog

Whenever you add, remove, or significantly change a file, update `CHANGELOG.md`. Use each applicable `Added`, `Changed`, `Fixed`, or `Removed` heading at most once per release block, and list each public behavior change once.

## Instruction size

Keep `CLAUDE.md` and `AGENTS.md` concise. Put detail in skills, routing, and focused docs. The validator enforces the current limits and host-adapter structure.

## Repository map

`REPO_MAP.md` is a generated, gitignored overview for manual uploads or inspection. Run `scripts/generate-repo-map.sh` when you need a fresh copy. Do not commit it or use it as a source of truth.
