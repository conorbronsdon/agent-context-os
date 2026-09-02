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
