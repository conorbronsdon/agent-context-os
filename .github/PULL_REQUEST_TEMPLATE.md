## What's in this PR

<!-- Brief description of what was added or changed -->

## Checklist

### Skills & commands
- [ ] Every new skill has a `SKILL.md` with `name:` and `description:` frontmatter
- [ ] Trigger phrases in skill `description:` are specific (what would you actually say?)
- [ ] New skills are referenced in `CLAUDE.md` and/or `ROUTING.md`
- [ ] New commands in `.claude/commands/` have `name:` and `description:` frontmatter
- [ ] Portable workflows keep provider-specific tools and paths in thin host adapters
- [ ] New `.agents/skills/` entries include explicit invocation policy when timing or side effects must remain user-controlled

### Integrations (if adding to catalog)
- [ ] Full-surface capabilities are declared, including `read`
- [ ] Data boundary is fully disclosed
- [ ] Every verified field is supported by first-party evidence, and unverified fields are explicitly disclosed (no live installation or testing used)
- [ ] `last_verified` is the personally checked date
- [ ] Confirmation gates are derived from capabilities, installation scope, and credential boundaries; risk tags are derived from capabilities
- [ ] `references/integrations.md` was regenerated via script
- [ ] `CHANGELOG.md` updated
- [ ] Full validation (`bash scripts/validate-all.sh`) passes locally

### Repo hygiene
- [ ] No sensitive data committed (passwords, API keys, tokens)
- [ ] `CHANGELOG.md` updated
- [ ] CI passes
