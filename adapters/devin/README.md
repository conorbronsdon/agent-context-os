# Devin experimental adapter

Context OS supports Devin through two deliberately separate surfaces: cloud
Agent sessions are an experimental lifecycle host, while Devin Review is a
compatibility surface for repository instructions only. Evidence from one
surface does not establish behavior in the other.

No exact Devin model or product build was available to pin for this release.
The adapter is therefore an evidence-backed pilot, not first-class support.

## Repository boundary

Devin cloud sessions document repository-root `AGENTS.md` and Agent Skills under
`.agents/skills/`. Start a session for this repository and invoke
`@skills:context-setup`, `@skills:context-start`, `@skills:context-update`, or
`@skills:context-end`. The namespaced forms avoid implying that Devin owns the
short command vocabulary. The lifecycle kernel binds apply to the exact proposal
digest, preventing proposal substitution. It does not authenticate who supplied
the confirmation or prove that a human reviewed the diff.

Devin skills default to automatic model invocation unless their frontmatter
sets `triggers: ["user"]`. Every shipped lifecycle core and short alias carries
that field, so Devin cannot model-invoke those skills. The same files carry
Cursor's `disable-model-invocation: true`; each host ignores the other host's
extension while the shared procedure remains provider-neutral. Explicit skill
selection still is not human approval of a proposal. This adapter has no
execution-authorization or blocking-hook control that can prove human approval:
do not run lifecycle skills in unattended sessions, and verify every diff
outside the agent before apply.

## Account-managed boundary

Blueprints, builds, snapshots, standalone Knowledge, secrets, repository
permissions, organization roles, security profiles, MCP configuration, and UI
state are Devin-managed account state. They are not Context OS components,
repository instruction sources, locally installable artifacts, or proof of
readiness. Git-based blueprints are not currently supported; configure them in
**Settings > Environment > Blueprints**. Context OS ships no `.devin/` file or
blueprint YAML.

Setup can register `devin` in `contextos.workspace.json` and local host
metadata. That means only "selected for this workspace." It does not connect a
repository, grant a role, create Knowledge, configure a Blueprint, build or pin
a snapshot, inject a secret, authenticate a session, or verify any of those
account-side states. A missing local binary is not a failure because this
surface is cloud-managed; `doctor` can validate the descriptor and materialized
repository files but does not certify the Devin account.

Before use, verify in Devin that:

1. the intended organization can access the exact repository;
2. the repository is included or configured in the environment;
3. the current Blueprint build succeeded and the intended snapshot is active;
4. the session security profile and user role match the task; and
5. required secrets exist at the intended scope.

Secrets are injected by Devin rather than committed here. Devin documents that
secret values are scrubbed from snapshots, but a Blueprint command that writes
a value into a configuration file can persist it in the snapshot. Never put a
real secret in a conformance fixture or repository file.

## Devin Review is not a session

Devin Review documents instruction-file support, including `AGENTS.md`, but it
does not document cloud-session lifecycle skills, Knowledge, snapshots, MCP,
secrets, or hooks as Review inputs. The Review CLI is also distinct from a cloud
Agent session: `npx devin-review <pull-request-url>` computes a local diff in an
isolated worktree and sends the diff and file contents to Devin servers. Run it
only with explicit external-data-transfer approval and never use a private or
user workspace as an incidental fixture.

GitHub comments, approvals, merges, and code changes from Review require
account-side GitHub App permissions. A PAT connection is read-only, and local
git access for the Review CLI does not prove Devin account access to the repo.

## Unsupported and promotion gates

Context OS ships no Devin repository hook, blocking pre-tool hook, memory
bridge, skill allowlist, execution-authorization adapter, Blueprint, Knowledge
record, secret, playbook, MCP config, or Review config. `MEMORY.md` has no
documented special Devin session semantics and is not synchronized.

## Live session conformance

The repository includes a sanitized fixture source under
`adapters/devin/live-fixture/` and an opt-in v3 API harness at
`adapters/devin/live_conformance.py`. Publish only that fixture tree to a
dedicated public repository, without adding personal data or secrets, and bind
the run to its exact remote commit. Do not use this repository or another user
workspace as the fixture.

Use a short-lived human PAT from **Settings > Devin API > PATs** for a local
maintainer run and store it only in `DEVIN_API_TOKEN`. Record the exact
organization ID and the successful build returned by the active-build API,
then run from one clean harness commit:

```bash
python adapters/devin/live_conformance.py \
  --org-id <org-id> \
  --repository <owner/public-fixture> \
  --fixture-sha <exact-fixture-commit> \
  --source-sha <exact-clean-harness-commit> \
  --expected-active-build <exact-active-build-id> \
  --evidence /outside/repository/devin-session-evidence.json \
  --allow-account-access \
  --allow-session-create \
  --acknowledge-public-fixture
```

The harness verifies exact repository access and the active build before it
creates one non-resumable API session. It tests root instructions, the fixture
skill's user-only must-not-fire control, its explicit must-fire control, exact
fixture commit reporting, and absence of a created pull request. It then
terminates and archives the session. Evidence contains hashes and public
fixture identifiers, never the token or session messages. Missing credentials,
opt-ins, repository access, or build identity fail as unverified. The harness
does not enable, trigger, or inspect Devin Review.

This fixture proves the cloud instruction and skill substrate. Promotion still
requires a separate lifecycle proposal/apply authorization fixture and a
separately approved Review fixture; neither may inherit this result.

## Review conformance fixture

`adapters/devin/review-fixture/` is a separate inert control for the Review
surface. Its scoped `REVIEW.md` requires one unique canary when a changed file
adds the benign prohibited marker in `control.txt`. A pull request containing
both files can therefore prove instruction ingestion without using a private
repository or real defect. Merely shipping the fixture does not trigger Review.

For a public GitHub pull request, Devin documents that replacing `github.com`
with `devinreview.com` starts a free read-only review without an account, or the
exact pinned `devin-review` CLI may be run from the local clone. Both paths send
the diff and file contents to Devin servers. Require explicit external-data-
transfer approval immediately before either path, bind evidence to the PR head
SHA and Review version or result identity, and verify that the result contains
`CONTEXTOS_DEVIN_REVIEW_CANARY_63F0A2D8`. Do not comment, approve, merge, apply
changes, enable auto-review, or install the GitHub App as part of conformance.

Promotion requires dated live-account fixtures that demonstrate instruction
and skill discovery, explicit lifecycle behavior, proposal/apply authorization,
repository access, and exact account/build identity. Account-dependent checks
must skip as **unverified** when credentials or opt-in are absent; documentation
or local registration alone must never turn them green. Review needs its own
fixtures and may not inherit a session result.

Current first-party references:

- [AGENTS.md](https://docs.devin.ai/onboard-devin/agents-md)
- [Agent Skills](https://docs.devin.ai/product-guides/skills)
- [Declarative environment configuration](https://docs.devin.ai/onboard-devin/environment/blueprints)
- [Blueprint reference](https://docs.devin.ai/onboard-devin/environment/blueprint-reference)
- [Knowledge](https://docs.devin.ai/product-guides/knowledge)
- [Secrets](https://docs.devin.ai/product-guides/secrets)
- [Devin Review](https://docs.devin.ai/work-with-devin/devin-review)
