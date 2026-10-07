# Devin adapter

Context OS supports Devin through three deliberately separate surfaces. Devin
CLI is a first-class lifecycle host. Cloud Agent sessions remain an
experimental lifecycle host, and Devin Review is a compatibility surface for
repository instructions only. Evidence from one surface does not establish
behavior in another.

CLI promotion is scoped to Devin CLI `3000.11.3 (9c803229faa4)` on Linux
(WSL2), with the default model, host controls, the shipped setup/start/update/end
workflows, exact-digest operator apply, and fresh-session handoff recorded in
the [promotion evidence](../../docs/evidence/devin-cli-2026-10-06/README.md).
It does not promote cloud sessions or Review, and it does not cover native
Windows (see below).

## Devin CLI

Install Devin CLI separately, sign in with `devin auth login`, start `devin`
from the repository root, and record `devin version`. Setup registers the
adapter but does not install, authenticate, or configure Devin.

Devin CLI loads the root `AGENTS.md` into the session context at start and
discovers project skills under `.agents/skills/`. Invoke `/context-setup`,
`/context-start`, `/context-update`, and `/context-end` explicitly. Devin CLI
owns built-in `/update` (self-update), so the documented Devin lifecycle avoids
the short aliases, as on Cursor. Every lifecycle skill sets `triggers: ["user"]`;
Devin omits such skills from the list it offers the model and refuses a model
attempt to invoke one. An explicit slash command expands the skill body into
the user turn.

### Import guard

By default Devin CLI also imports instructions, skills, commands, MCP servers,
and hooks from Claude Code, Cursor, Windsurf, GitHub Copilot, OpenCode, and Zed,
including user-level files such as `~/.claude/CLAUDE.md`. In this repository
that would load the removable `CLAUDE.md` seed (whose command table uses the
short names), `.claude/skills/`, and the operator's private global Claude
instructions alongside `AGENTS.md`.

The adapter therefore ships `.devin/config.json`, which sets
`read_config_from` to `false` for every foreign tool and leaves
`agents_standard` at its default. Live sessions with the file loaded only
`AGENTS.md`; the same fixture without it loaded both the repository and
user-level `CLAUDE.md`. `devin rules list` still lists `CLAUDE.md` rules when
imports are disabled, so inspect a session export rather than that listing.
The file contains no permissions, hooks, MCP servers, or secrets. Project-level
`.devin/config.json` accepts only `permissions`, `read_config_from`, and
`hooks`; keep personal overrides in the git-excluded `.devin/config.local.json`.

### Authorization boundaries

The kernel's exact-digest apply is the enforcement boundary. Devin permission
rules are useful defense in depth only within the limits observed on
`3000.11.3`:

- Normal mode (the default) runs reads and read-only shell commands such as
  `ls` and `grep` automatically and asks before every other shell command,
  file write, and fetch. In `devin -p`, an unanswerable request is rejected and
  ends the session's tool use.
- In Normal mode, a project or project-local `deny` beats an `allow` at the same
  level, and path-scoped `Write(...)` allows work as documented.
- Accept Edits auto-approves workspace edits even when a project or
  project-local `deny` or `ask` matches; only user-level denies held. Bypass
  ignores project denies entirely.
- A broad `allow` in user or project-local config overrode a project-level
  `deny` or `ask` for the same command, contrary to the documented precedence.
- Path-scoped `Read(...)` denies were not reliable across configuration levels.

Context OS therefore ships no Devin permission rules and makes no claim that a
rule keeps `apply` away from the model. Use Normal mode for lifecycle work,
approve `propose` calls as they appear, inspect the proposal diff, and approve
`apply` only for the exact digest you reviewed. Do not grant a broad
`Exec(bash scripts/contextos.sh)` allow or a broad allow for the kernel's Python
module, and never run lifecycle skills in Bypass mode.

### Native Windows

On Windows, Devin CLI resolves the home directory through the operating-system
profile. Overriding `HOME` or `USERPROFILE` does not hide `~/.claude/CLAUDE.md`
or `~/.agents/skills/`, so a harness cannot isolate user-level sources there.
The shipped import guard still disables the Claude import in a Context OS
checkout, but user-level skill directories that Devin owns, such as
`~/.agents/skills/`, are always loaded. Native Windows behavior is untested;
the conformance harnesses refuse to run there. Use WSL for verified behavior.

### Hooks, memory, MCP, and handoff

Devin CLI supports Claude-compatible hooks in `.devin/hooks.v1.json`, project
MCP servers in `.devin/mcp_config.json`, and `/handoff` to a cloud session.
Context OS ships none of them and makes no claim about them. Devin CLI has no
native memory store beyond session resume; nothing is synchronized into
`state/` or `sessions/`.

### Conformance

Both harnesses run only on Linux, macOS, or WSL. They point `HOME` and
`XDG_CONFIG_HOME` at temporary directories, seed synthetic user-level
canaries there, and pin only `XDG_DATA_HOME`, which must already hold the
operator's Devin credentials. Evidence comes from Devin's ATIF session export
(`--export`), which records the injected rules, the offered skills, every tool
call, and every tool observation. Shareable evidence keeps hashes and booleans,
never raw responses, temporary paths, or credentials.

```bash
python3 adapters/devin/cli_conformance.py \
  --binary /exact/path/to/devin --expected-version <version> \
  --source-sha <exact-clean-commit> --data-home ~/.local/share \
  --evidence /outside/repository/devin-cli-host.json --allow-model-traffic

python3 adapters/devin/cli_lifecycle_conformance.py \
  --binary /exact/path/to/devin --expected-version <version> \
  --source-sha <exact-clean-commit> --data-home ~/.local/share \
  --evidence /outside/repository/devin-cli-lifecycle.json \
  --approval-dir /outside/repository/empty-approvals --allow-model-traffic
```

The host harness checks that `AGENTS.md` is injected at session start, that
the shipped config keeps repository and user-level Claude sources out of
context while a positive control without it loads them, explicit-skill
must-fire and implicit-skill must-not-fire behavior, print-mode rejection of
an unapproved write and shell command, same-level deny precedence, an exact
scoped write, and an allowlisted kernel command. It records, without gating,
the Accept Edits and Bypass and precedence observations listed above, so a
client release that changes them is visible. The lifecycle harness clones the
exact source commit and runs every phase in Normal mode. A rejected call ends a
print-mode session and the skills chain ordinary shell inspection, so the
disposable fixture's local config allows the shell broadly (as the Cursor run
used `--force`) while denying every `apply` form, direct Python, `rm`, and
mutating Git at the same level, and allows file writes only under
`.context-os/inputs/`. Start and the handoff also deny file tools and
`propose`. Each phase must show Devin expanding the complete shipped skill body
into the user turn, and start must run the kernel wrapper's `start` and receive
a successful inventory. A synthetic user-level `~/.claude/CLAUDE.md` must stay
out of every phase. Apply detection deliberately over-matches (quoting,
chaining, `bash -c`, ANSI-C strings), and every detected model `apply`
attempt, including in the handoff, must show a deny-rule rejection; tracked
files must be unchanged until the operator acts, which also catches an
undetected spelling that succeeds. An external operator approves each
proposal's exact digest before the harness applies it. End must save the
handoff fact under the session's `## Next time` heading. Before the handoff,
the harness removes pending inputs and proposals and requires the verification
value to survive only in `sessions/`, so a fresh session must read the saved
session to recover it. It checks wrong-digest and stale rejection, receipts, read-only
start, and fresh-session handoff. Add `--debug-dir` to keep raw exports locally
when diagnosing a failure; never share them.

## Cloud session repository boundary

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
**Settings > Environment > Blueprints**. Context OS ships no blueprint YAML.
Its only `.devin/` file is the CLI import guard described above; Devin does not
document whether cloud sessions read it, so it is not a cloud-session control.

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
`adapters/devin/live_conformance.py`. Publish only the materialized two-file
fixture to a dedicated public repository, without adding personal data or
secrets, and bind the run to its exact remote commit. Do not use this repository
or another user workspace as the fixture.
Republish the public fixture from the updated `.fixture` files before the next
live run; the old public fixture bytes will fail the exact-content check.

The checked-in instruction sources have `.fixture` suffixes so repository agents
do not discover them as live instructions. In a separate disposable checkout of
the dedicated public fixture repository, place `AGENTS.md.fixture` at `AGENTS.md`
and `SKILL.md.fixture` at
`.agents/skills/contextos-devin-live-control/SKILL.md`. Publish only those two
files. Both session harnesses compare the public files with the checked-in source
bytes before running a control.

The API harness requires a currently supported `cog_` credential. Devin's
current authentication documentation lists human PATs as closed beta, so a
free or otherwise unflagged account may correctly have no PAT control. Never
claim that as a local installation failure. Where PAT access is enabled, use a
short-lived human PAT for a local maintainer run and store it only in
`DEVIN_API_TOKEN`. A supported organization service-user key is also accepted,
but creating one is account administration outside Context OS. Record the exact
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

The harness verifies exact repository access, the active build, and the complete
two-file public fixture tree and byte content before it creates one read-only
API session. It tests root instructions without placing the root answer in the
prompt, the fixture skill's user-only must-not-fire control across every returned
message and a settling window before the explicit turn, its explicit must-fire
control ordered after the harness's user message, exact fixture commit reporting,
unchanged public default-branch head and content, and absence of a created pull
request. It then uses
the current v3 archive endpoint and verifies the archived state. If archival
fails, it attempts a separate termination but still fails conformance. Evidence
contains hashes and public
fixture identifiers, never the token or session messages. Missing credentials,
opt-ins, repository access, or build identity fail as unverified. The harness
does not enable, trigger, or inspect Devin Review.

The root prompt names no instruction file, but Devin can still read files on
request and the harness cannot deny those reads. A passing root control shows
that Devin returned the canary from repository instructions. It does not prove
that Devin loaded `AGENTS.md` before the prompt asked for it.

For an account without API credentials, use the operator-assisted web-session
recorder at `adapters/devin/ui_conformance.py`. `prepare` verifies that the
dedicated public repository still contains exactly the two synthetic fixture
files at the requested commit, that its default branch still points to that
commit, and records its complete pull-request inventory.
It emits create-only prompts outside the source repository. In Devin, start one
read-only session for that exact public repository, run the root prompt, then
explicitly invoke the synthetic user-only skill. Do not edit, branch, commit,
push, open a pull request, or enable/invoke Review. Archive the session and use
`record` with an operator observation JSON. The recorder re-verifies the remote
fixture and unchanged pull-request inventory, checks the exact root and skill
canaries, hashes rather than stores the session URL, and records whether the UI
exposed product-build and environment identities. Its artifact labels those
host outcomes as `operator-attested-with-local-verification`, distinct from the
fixture, source-commit, response-syntax, and pull-inventory controls the recorder
checks directly. If either identity is
unavailable, the live substrate result may justify continued experimental
support but cannot be represented as exact account/build promotion evidence.

The UI path proves only the same read-only instruction and explicit-skill
substrate as the API harness. Operator attestation is not an execution-
authorization control, and UI evidence does not inherit API-only active-build
or account-inspection claims.

This fixture proves the cloud instruction and skill substrate. Promotion still
requires a separate lifecycle proposal/apply authorization fixture and a
separately approved Review fixture; neither may inherit this result.

## Review conformance fixture

`adapters/devin/review-fixture/` is a separate inert control for the Review
surface. Its `REVIEW.md.fixture` source must be placed as `REVIEW.md` only in a
dedicated disposable Review fixture checkout. That scoped instruction requires
one unique canary when a changed file
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
- [API authentication and PAT availability](https://docs.devin.ai/api-reference/authentication)
- [Archive session](https://docs.devin.ai/api-reference/v3/sessions/post-organizations-sessions-archive)
- [Devin Review](https://docs.devin.ai/work-with-devin/devin-review)
