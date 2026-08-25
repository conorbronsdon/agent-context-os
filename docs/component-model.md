# Component inventory and ownership

`components/manifest.json` is the authoritative inventory for the files that
make up Context OS. Runtime descriptors name component IDs; the component graph
resolves those IDs to one deterministic dependency closure and one owner for
every checked-in path.

This inventory is metadata, not a materializer. It does not copy, delete,
upgrade, or rewrite a workspace. Those operations require the later
configuration and transaction layers described in the multi-agent design epic.

## Path policies

Every currently tracked file has exactly one component owner and one policy:

- `managed`: product code, instructions, adapters, or documentation that a
  future composition tool may install and update.
- `seed`: initial content that becomes user-owned after it is copied. Future
  updates must preserve an existing destination unless a separately reviewed
  migration says otherwise.
- `development`: repository maintenance, tests, CI, or contribution files.
  These prove or build the product but are not runtime workspace outputs.

The roots `.agents/skills/`, `.claude/commands/`, `content/`, `identity/`,
`inbox/`, `projects/`, `references/`, `sessions/`, `state/`, and `writing/` are
extensible. The legacy root configuration file `workspace.yaml` is an exact
extensible path rather than a directory root. The canonical tracked
`contextos.workspace.json` created by reviewed setup transactions is the other
exact extensible path.
Checked-in files below them retain their explicit owner and policy, while new
user files are workspace-owned rather than component-owned. The maintainer
check remains strict over the repository's tracked source set;
`bash scripts/validate-all.sh --workspace` selects the operational exception
for a customized workspace. That operational check also permits intentionally
removed `seed` files, while missing `managed` or `development` files still fail.
CI and product contributors use the strict default.

Two exact root paths have virtual transaction owners rather than release
components: `contextos.workspace.json` is owned by `workspace-config`, and
legacy `workspace.yaml` by `legacy-workspace-config`. This lets strict tracked
coverage validate a configured clone without pretending those workspace-local
files are shipped component assets. The exception is exact; it does not make
other repository-root paths extensible or writable.

## Components

| Component | Depends on | Responsibility |
|---|---|---|
| `core` | none | Provider-neutral kernel, shared docs and scripts, repository scaffolding, and user-owned seeds |
| `portable-skills` | `core` | Provider-neutral lifecycle and migration skill bodies |
| `openai-skill-metadata` | `portable-skills` | OpenAI discovery metadata, separate from portable skill bodies |
| `agents-instructions` | `core`, `portable-skills` | The shared `AGENTS.md` instruction bridge |
| `claude-adapter` | `core`, `portable-skills` | Claude Code instructions, commands, hooks, memory tooling, and descriptor |
| `codex-adapter` | `core`, `portable-skills`, `agents-instructions`, `openai-skill-metadata` | Codex hooks, onboarding, metadata, and descriptor |
| `hermes-adapter` | `core`, `portable-skills`, `agents-instructions` | Hermes guidance, optional hooks, and descriptor |
| `example-project` | `core` | Optional removable example content |

Shared dependencies have one owner. Selecting both Claude and Codex therefore
includes `core` and `portable-skills` once; neither adapter becomes a second
owner. OpenAI metadata is also isolated so an agentskills.io consumer can use
portable skill bodies without inheriting Codex-specific presentation files.
When a runtime names a directory source such as `.agents/skills`, the resolver
materializes only descendant files owned by the selected closure; an unselected
component may contribute a different fragment beneath the same directory.

## Validation

Run:

```bash
python scripts/component-manifests.py check
```

The full validator runs the same check. It rejects unknown dependencies,
cycles, unknown runtime component references, unsafe or symlinked paths,
case-insensitive, Unicode-normalized, and Windows-aliased collisions,
file/descendant ownership conflicts, symlinked generated targets, missing or
untracked owned files, duplicate owners, and any unclassified tracked source
file. `components/schema.json` is generated from the Python contract and must
stay current.

## Clean-composition prerequisites

Before a later command may materialize a selected component set, it must also:

1. record the selected runtimes and components in workspace-local
   configuration;
2. distinguish pristine managed outputs from modified or user-owned targets;
3. preflight case-folded paths, symlink ancestors, and destination containment;
4. produce an exact add/change/remove plan with immutable source hashes;
5. require digest-bound approval and use the transaction lock and receipts;
6. preserve existing `seed` paths and arbitrary files below extensible roots;
7. define how generated whole-file artifacts and maintainer-only conformance
   evidence behave in a slim workspace; and
8. validate the resulting selected runtime closure without assuming every
   adapter or the development test tree is present;
9. replace the current `AGENTS.md`-based root discovery and doctor requirement
   with a provider-neutral marker before a Claude-only closure can omit the
   `agents-instructions` component; and
10. make shared instruction and documentation links closure-aware so a slim
    workspace neither points at omitted adapter docs nor describes hooks that
    were not selected.

Until those guarantees ship, the catalog is intentionally read-only inventory.
