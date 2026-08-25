# Contributing

Thanks for looking. This repository is a **template** people clone and fill with
their own context, so the most valuable contributions are structural: clearer
conventions, portable skills, better host adapters, and integration catalog
entries. Personal content does not belong here.

Issues labelled [`good first issue`](https://github.com/conorbronsdon/agent-context-os/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22)
are scoped to be finishable without any external account or credential.

## Prerequisites

Git, Bash, and Python 3.10 or newer. Python may be installed as either
`python3` or `python`. CI runs the suite on 3.10 so the floor stays real.

There is nothing to install — no package manager, no dependencies, no build
step. Clone the repository and run the validator.

```bash
git clone https://github.com/conorbronsdon/agent-context-os.git
cd agent-context-os
bash scripts/validate-all.sh
```

If that passes on a clean checkout, your environment is ready.

## The one rule

**`bash scripts/validate-all.sh` must pass before you open a pull request.**

CI runs the same aggregate validator. It checks structure, adapter mappings,
links, shell syntax, hook behavior, JSON, the Python test suite, and the
generated integration documentation. It cannot prove the behavior of an
installed agent version or an external service — that part is still on you.

Run it locally rather than discovering a failure in CI. It takes about a minute.

## Generated files — do not hand-edit

Four artifacts are produced by scripts. Editing them directly means your change is
silently reverted on the next regeneration.

| File | Source of truth | Regenerate with |
|---|---|---|
| `references/integrations.md` | `integrations/catalog.json` | `scripts/integrations.py render` |
| `REPO_MAP.md` | the repository itself | `scripts/generate-repo-map.sh` (gitignored — never commit it) |
| `runtimes/schema.json` | `contextos/runtime_schema.py` | `scripts/runtime-manifests.py generate` |
| README registered-host table | validated `runtimes/*.json` descriptors | `scripts/runtime-manifests.py generate` |

## Adding a runtime descriptor

Add `runtimes/<runtime-id>.json`; the lowercase filename stem is the stable ID.
Copy a current descriptor, declare each host surface independently, and cite
official evidence for native behavior plus the named local conformance test for
adapter or advisory behavior. Unknown keys, capability values, evidence claims,
future dates, missing repository references, and generated-artifact drift all
fail validation. `generic` is reserved for apply receipts and cannot be a host.

Run `scripts/runtime-manifests.py generate`, add or extend a must-work conformance
control, then run the full validator. Do not add compatibility-only hosts to the
generated registered-host block; a shipped descriptor is a support claim.

## Adding an integration to the catalog

The most commonly requested contribution. Use the
[integration proposal issue template](.github/ISSUE_TEMPLATE/integration-proposal.md)
to check the entry is wanted before writing it.

1. Add an entry to `integrations/catalog.json`. Copy an existing entry and fill
   every field — the validator enforces the required set.
2. Set `last_verified` to the date **you** checked the source. Do not copy a
   date from an issue or another entry; upstream tools move quickly.
3. Put first-party documentation in `evidence`. A vendor blog roundup or an
   MCP aggregator listing is not evidence.
4. Describe `capabilities` honestly, including the unpleasant parts. If a
   server can delete remote objects, `delete` and `destructive` are `true` even
   when you never intend to use those tools.
5. Recommend the narrowest useful default profile. Most entries should default
   to read-only scopes with writes behind a separate confirmation group.
6. Regenerate `references/integrations.md` and run the validator.

`maturity` is a claim about metadata, not about testing. `verified` means you
checked the fields against the linked source on the stated date. If you could
not confirm something, `listed` is the honest value — and saying "I could not
verify X" in the pull request is genuinely useful, not a failure.

Nothing in this repository is installed or enabled at setup. A catalog entry is
a discovery and risk document that lets a reader decide, so an entry that
undersells a capability is worse than no entry.

## Skills and commands

Portable workflow cores live in `.agents/skills/<name>/SKILL.md` and must stay
provider-neutral — no host-specific tool names, paths, or permission syntax.
Host adapters are thin files that route to the portable core:
`.claude/commands/` for Claude Code, `.codex/` for Codex, `adapters/hermes/`
for Hermes.

The validator enforces size limits so instructions stay loadable:

| File | Limit |
|---|---|
| `AGENTS.md` | 100 lines |
| `.agents/skills/*/SKILL.md` | 180 lines |
| alias `SKILL.md` | 15 lines |
| `.claude/commands/*.md` | 40 lines |

A workflow that needs more room needs a focused doc, not a longer skill.

See [docs/agent-template.md](docs/agent-template.md) for the scaffold and
[docs/first-skill.md](docs/first-skill.md) for a worked example.

## Single source of truth

Every fact should have exactly one canonical home; everything else links to it.
When you find the same number, date, or claim in two files, fix the duplication
rather than updating both. `docs/repo-maintenance.md` covers the staleness
convention, the archival workflow, and the `**Last Updated:**` rules.

Before removing a link, a table row, or an index entry, check what pointed at
the target. `bash scripts/check-links.sh` catches links to files that no longer
exist; `bash scripts/check-doc-reachability.sh` catches the opposite problem —
a doc that still exists but that nothing points to any more.

## Changelog

Update `CHANGELOG.md` whenever you add, remove, or significantly change a file.
Use each applicable `Added`, `Changed`, `Fixed`, or `Removed` heading at most
once per release block, and list each public behavior change once.

## Pull requests

- Branch from `main`. Keep one concern per pull request.
- Fill in the pull request template checklist.
- Never commit credentials, tokens, API keys, or personal context. Secret
  scanning here is a limited tripwire, not a guarantee.
- Say what you verified and what you could not. A pull request that states its
  own gaps is easier to merge than one that implies completeness it does not
  have.

## Security

Do not report a security issue in a public issue or pull request. See
[SECURITY.md](SECURITY.md).

## Questions

Open an issue describing the pattern and the problem it solves. For a change
that would alter conventions or product language, read
[docs/positioning.md](docs/positioning.md) first — it records the claims this
project deliberately avoids making.
