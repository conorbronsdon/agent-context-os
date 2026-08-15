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

### Repo hygiene
- [ ] No sensitive data committed (passwords, API keys, tokens)
- [ ] `CHANGELOG.md` updated
- [ ] CI passes
