# Security

## Reporting a vulnerability

Do not open a public issue or pull request for a security problem.

Report it privately through GitHub's
[private vulnerability reporting](https://github.com/conorbronsdon/agent-context-os/security/advisories/new)
for this repository. Include what you found, how to reproduce it, and what an
attacker could do with it.

Expect an acknowledgement within about a week. This is a small project without
a staffed security rotation, so please do not treat that as a guarantee.

## What is in scope

This repository ships Markdown, shell scripts, a Python lifecycle kernel, and
host adapters. In scope:

- A path escape or unintended write in the lifecycle kernel (`contextos/`) —
  it is supposed to refuse writes outside approved context paths.
- A way to bypass the proposal/apply confirmation gates, or to get a proposal
  applied whose content differs from the diff that was reviewed.
- A repository hook or script that executes attacker-controlled input.
- A catalog entry in `integrations/catalog.json` that materially understates an
  integration's capabilities — an entry claiming read-only access for something
  that can write, publish, or delete is a safety defect, not a typo.
- Committed credentials or personal data in this repository's history.

## What is not in scope

- **Vulnerabilities in the integrations themselves.** The catalog documents
  third-party tools; it does not vendor them. Report those to their maintainers.
- **Vulnerabilities in Claude Code, Codex, or Hermes.** Report those to their
  respective vendors.
- **Your own clone.** This is a template. Once you fill it with your context,
  its contents, visibility, and access controls are yours to manage.

## Boundaries you should understand before using this

These are design limits, not bugs. They are documented here because misreading
them is the most likely way someone gets hurt.

- **Validation is not a publication guarantee.** `scripts/validate-all.sh`
  checks structure and known invariants. It does not prove a file is free of
  sensitive content, and its secret scanning is a limited tripwire.
- **Deleting a file does not erase git history.** If a credential was ever
  committed, rotate it. Removing it in a later commit is not sufficient.
- **`verified` in the integration catalog is a metadata claim.** It means the
  fields were checked against the linked source on the stated date. It is not a
  live authentication test, a penetration test, or an ongoing guarantee. An
  integration's capabilities can change after `last_verified`.
- **Nothing here sandboxes an agent.** The repository documents boundaries and
  asks for confirmation at specific points. Enforcement lives in your agent
  host's permission system, not in these files.
- **Host-local memory is outside this boundary.** Native agent memory is not
  synchronized by the lifecycle kernel and is not covered by repository
  review. See [docs/auto-memory.md](docs/auto-memory.md).

## If you are storing personal or client context

Use a private repository. Repository visibility is one control among several —
do not store credentials, raw account exports, or anything you would not want
every agent you configure to be able to read. See
[docs/safety-contract.md](docs/safety-contract.md).
