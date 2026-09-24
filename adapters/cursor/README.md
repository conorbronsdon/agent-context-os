# Cursor experimental adapter

Context OS supports Cursor as two separate experimental surfaces: the desktop
IDE and the Agent CLI. Both discover the repository-root `AGENTS.md` and project
skills under `.agents/skills/`, but they have different binaries, permissions,
configuration, and conformance gates. A green CLI check is not IDE evidence.

No installed Cursor version was available for this release. The descriptor is
therefore capability-gated, has no tested version, and must not be promoted to
first-class until the opt-in controls pass against exact IDE and CLI versions.

## Setup

Select Cursor alongside any other agents during repository setup:

```bash
bash scripts/setup.sh --agents cursor
# or
bash scripts/setup.sh --agents claude,codex,cursor
```

For the IDE, open this repository as the workspace. For the CLI, install the
Cursor Agent CLI separately, start `agent` from the repository root, and verify
the exact executable with `agent --version`. The executable name `agent` is too
generic for safe automatic detection, so the experimental descriptor does not
use it as a resolution-only availability probe. Setup registers the adapter but
does not launch either surface, authenticate Cursor, trust the workspace, or
change account, user, project, MCP, hook, sandbox, or permission settings.

Invoke `/context-setup`, `/context-start`, `/context-update`, and `/context-end`
explicitly. Cursor CLI owns the built-in `/update` command for updating Cursor
itself, so the documented Cursor lifecycle deliberately avoids the short
aliases. The namespaced skills route mutations through the deterministic
proposal/apply kernel. Even in an IDE run mode or `agent -p --force`, an agent
instruction is not approval of a Context OS proposal: inspect the exact diff
and approve its digest separately.

## Rules and skills

Cursor also supports project rules in `.cursor/rules/**/*.mdc`; plain Markdown
files in that directory are ignored. Cursor documents Team, Project, then User
rule priority, but does not document which source wins when root `AGENTS.md`
conflicts with a project `.mdc` rule. Context OS therefore ships no Cursor rule
file and makes no conflict-precedence claim. Keep the shared lifecycle contract
in `AGENTS.md`; make Cursor rules narrow and non-overlapping.

Cursor discovers skills in both `.agents/skills/` and `.cursor/skills/`, but its
documentation does not define a same-name collision winner. Context OS ships
only `.agents/skills/`. That shared directory includes the four short aliases
as well as the four `context-*` cores, so Cursor discovers both sets even though
this adapter documents only the namespaced commands. Cursor does not document
whether its built-in `/update` or the discovered `update` skill wins. Do not use
the short aliases in Cursor, and do not duplicate these names in another Cursor
skill root. Every shipped lifecycle core and short alias sets
`disable-model-invocation: true`, so Cursor includes it only after explicit
slash invocation. The same files also carry Devin's `triggers: ["user"]`; each
host ignores the other host's extension while the shared procedure remains
provider-neutral.

Cursor CLI also reads a root `CLAUDE.md`, when present, alongside `AGENTS.md`
and `.cursor/rules`. This template ships `CLAUDE.md` as a removable seed, so the
runtime descriptor cannot declare it as a required repository source. Its
Claude command table includes the short lifecycle names; Cursor users should
still use only the namespaced `context-*` skills. Cursor also scans compatible
`.claude/skills/` and `.codex/skills/` roots. No lifecycle skill is shipped in
those roots today, but same-name additions create another unresolved collision.

## Authorization boundaries

The IDE and CLI authorization controls are not interchangeable:

- IDE Run Modes and project/user `permissions.json` govern IDE shell, MCP, and
  fetch behavior. Cursor says Auto-review is not a security boundary.
- CLI permissions live in user `~/.cursor/cli-config.json` and project
  `.cursor/cli.json`. An explicit deny wins an allow for the matched tool, but
  a `Write(...)` deny does not prevent the same filesystem change through
  `Shell(...)`; deny every applicable tool path when enforcing an outcome.
  Treat relative path-scoped `Write(...)` denies as insufficient until an exact
  installed-version fixture proves otherwise; test broad `Write(*)` and
  `Shell(*)` denies against every intended write path, including `--force`.
- Treat `agent -p` as write-capable unless the exact installed-version fixture
  proves the selected mode remains read-only. Use `--mode ask` or `--mode plan`
  when the invocation must remain read-only. `--force` additionally force-allows
  commands unless an explicit permission deny matches. These are
  installed-version conformance gates because unattended behavior can change
  across releases.
- `--trust`, `--force`, and broad shell, write, MCP, or absolute-path grants are
  opt-in permission expansions. Setup never supplies them.

Use a disposable fixture to test unattended modes. Never run a `--force`
conformance check against a real context repository.

## Hooks, memory, and MCP

Cursor project hooks use `.cursor/hooks.json`. Command hooks block on exit code
2 and otherwise fail open by default; cloud-agent hook coverage is a smaller
documented subset. Context OS intentionally ships no Cursor hook adapter until
an exact installed IDE and CLI fixture proves the selected events, output, and
failure behavior. Project hooks and blocking pre-tool hooks are therefore
unsupported by this adapter, not silently inherited from Claude or Codex.

Cursor loads project MCP configuration from `.cursor/mcp.json`; MCP remains a
separate trust and authorization boundary. Setup does not install, authenticate,
approve, or enable a server.

Cursor rules, account settings, chat/session history, Cloud Agents, Automations,
and any host-native memories are outside Context OS state. No Cursor-native
memory is synchronized into `state/` or `sessions/`; portable continuity changes
only through a reviewed Context OS proposal.

## Diagnostics and promotion gates

Run `bash scripts/contextos.sh doctor --runtime cursor` for descriptor,
registration, materialization, and local binary checks. Its aggregate
availability status reflects only the safely identifiable `cursor` IDE launcher;
the generic `agent` CLI name has no resolution-only probe. Cursor has no
documented all-up native doctor. For the CLI, record `agent --version`, `agent
about`, `agent status`, and `agent mcp list` separately from IDE diagnostics.

The current opt-in CLI control is an exact-version and required-flag smoke test,
not installed lifecycle conformance. It runs from a disposable directory and
does not authenticate, trust a workspace, call a model, or exercise writes.

The stronger live CLI harness is `adapters/cursor/live_conformance.py`. Run it
only from a clean exact commit, with an exact separately installed or extracted
binary and an evidence path outside the repository:

```bash
python adapters/cursor/live_conformance.py \
  --binary /exact/path/to/cursor-agent \
  --expected-version <exact-version> \
  --source-sha <exact-clean-commit> \
  --evidence /outside/repository/cursor-cli-evidence.json \
  --allow-model-traffic
```

The opt-in flag authorizes Cursor model traffic and writes only in a synthetic
temporary workspace marked disposable. The root, nested, and rule controls
check exact canary responses in ask mode. Their prompts mention repository
instructions or a project rule, and reads are allowed, so they do not isolate
automatic discovery from a prompted file read. The harness also checks
explicit-skill must-fire and implicit-skill must-not-fire behavior, read-only
ask mode, the exact unattended write behavior
without `--force`, a stream-observed denied write attempt under `--force`, and
an exact allowed write. It does not treat a model merely choosing not to write
as evidence that project denial precedence works.
For the explicit-skill control it denies direct `.agents/**` reads, so a passing
run must use Cursor's skill mechanism rather than merely reading the skill file;
it also denies all shell commands for that turn so `cat` cannot bypass the
file-read control.
It refuses a dirty source worktree,
version drift, missing authentication, evidence overwrite, unexpected fixture
mutation, and the real repository as a target. It never invokes Cursor's
built-in `/update` command. A passing CLI artifact is not IDE evidence.

The IDE has a separate operator-assisted harness at
`adapters/cursor/ide_conformance.py`. Its `prepare` command requires an exact
clean source commit, installed binary hash, disposable workspace, isolated
native profile, and explicit model-traffic opt-ins. Open only the generated
workspace with the generated profile. Follow the prompts stored in the
create-only manifest, record the exact synthetic observations in a JSON file,
then use `record` with `--acknowledge-operator-attestation`. The recorder checks
root and nested instructions, an always-applied project rule, installed-build
instruction/rule conflict behavior, the explicit skill's exact canary response,
implicit-skill must-not-fire behavior, Ask-mode preservation, interactive denial and scoped
approval, native-profile isolation, and absence of project MCP and hook config.
The prepared IDE workspace and profile do not deny direct reads of the skill
file. A matching explicit response therefore cannot establish that the slash
command resolved; the manifest and evidence record `explicit_skill_must_fire`
as `unverified`.
It accepts only one exact approved fixture write and emits create-only evidence
outside the repository. Its artifact labels host observations as
`operator-attested-with-local-verification`, separating them from the fixture
and file-state controls it verifies itself. For the short `/update` collision, observe the slash
menu and record `builtin`, `skill`, `ambiguous`, or `unavailable`; never submit
or execute it.

Project-owned `.cursor/` configuration is permitted by workspace validation.
Strict maintainer validation still requires every template-owned path to have
an explicit component owner.

First-class promotion requires exact-version conformance for both surfaces,
including root and nested instruction discovery, `.cursor/rules` conflict
controls, short-alias versus built-in resolution, the shipped explicit-only
skill frontmatter, interactive must-fire and must-not-fire approval controls,
headless ask, no-`--force`, and `--force` behavior, deny precedence, MCP scope,
native-state isolation, and either a tested Cursor-specific hook adapter or a
continuing explicit no-hook claim.
