# Compatibility contract for 1.x

Status: the compatibility promise for 1.x, in effect since the qualified 1.0.0
release was published ([#228](https://github.com/conorbronsdon/agent-context-os/issues/228)).
Source version 1.1.1 is a candidate until its immutable release is published.

## Supported interfaces

The stable kernel entry point is `bash scripts/contextos.sh`, backed by
`python -m contextos`. The four lifecycle operations are `start`, `propose
setup`, `propose update`, and `propose end`, followed by `apply` for mutations.
Payload examples in [templates](templates/setup-payload.json),
[update](templates/update-payload.json), and [end](templates/end-payload.json)
describe the supported inputs. [Commands and skills](commands-and-skills.md)
owns host invocation names; host shortcuts are not interchangeable. `bash scripts/setup.sh --agents <ids>`
is the supported interactive onboarding wrapper; its prompts are presentation,
while its agent-selection proposal uses the same kernel transaction boundary.

`start` reads continuity without changing tracked context. Proposals show the
exact changes and digest. Apply requires approval of that exact digest,
revalidates sources and destination snapshots, and records a receipt. A changed
proposal needs new review. Digests bind bytes, not the identity of the human
approver; the receipt's runtime is self-reported. Hooks supplement this boundary.

Workspace configuration uses schema 2 in `contextos.workspace.json`.
[Workspace configuration](workspace-configuration.md) defines exact keys,
agent-set semantics, profiles, paths, precedence, migration and reconciliation.
Schema 1 and legacy YAML remain migration inputs, not alternate writable
formats. Malformed JSON never falls back to YAML. [The root contract](root-contract.md)
defines which root owns each operation and which paths it can change.

Lifecycle proposals and receipts currently use schema 1. The canonical
validators and writers are in `contextos/kernel.py`; proposal fields and
digests must not be edited manually. Keep proposals, receipts and pending
journals together when preserving recovery evidence. Regenerate an unapplied
proposal after an upgrade rather than assuming a proposal from an older kernel
can still apply. Plans and proposals bind the input snapshots and executable-mode
checks available on the system that created them. Moving a proposal between operating systems is not a supported
reuse path. Receipt history remains evidence of past changes, not approval
to repeat them.

Runtime descriptors use schema 2 in `runtimes/`. Their public interface is the
runtime ID, selected component closure, per-surface tier, instruction and skill
sources, lifecycle invocation, capability declarations and dated evidence.
`contextos/runtime_schema.py` validates this interface. A new host surface
needs its own evidence; CLI support does not establish IDE, ACP, bot or cloud
support. Native memory, credentials and host permissions stay outside shared
state. The [capability view](commands-and-skills.md#runtime-boundary) distinguishes
claims, installed components and availability.

Detached bundle locks use schema 1 and planner protocol 1.
[Bundle locks](bundle-locks.md) defines exact version and digest verification,
current-versus-candidate compatibility, ownership and executable-mode limits.
Component manifests use schema 1. Generated JSON schemas describe structure;
Python validators also enforce membership, paths and other semantic constraints.

## Changes within 1.x

Patch releases repair defects without changing supported invocation, accepted
valid inputs or durable format meaning. Minor releases may add optional
commands, adapters or capabilities while preserving existing supported behavior.
Strict formats stay strict: consumers must not assume unknown fields are
accepted. A format change needs a versioned validator and an explicit migration,
rather than silently changing the meaning of an existing schema version.

A breaking change includes removing a supported command, rejecting previously
valid supported workspace input, changing path ownership or approval meaning,
or requiring an incompatible durable format. Such changes require a major
version, a documented migration and recovery path, and upgrade qualification.
A security fix may reject an unsafe input sooner; its release notes must name
the newly rejected case, affected users and recovery procedure.

Deprecations are announced in release notes with the replacement and migration
instructions. A supported interface remains usable throughout 1.x unless a
documented security correction requires rejection. Experimental surfaces may
change in a minor release, with the change recorded in release notes. This
promise does not freeze upstream client versions or establish untested platform
coverage; refresh runtime evidence before advertising current support.

## Upgrades and recovery

Keep an independently verified copy of both the installed release and candidate
bundles. Reconcile missing installed state against the workspace's pinned bundle
before using `workspace update` with explicit current and candidate inputs.
Schema-v1 migration first preserves the `full-template` profile and adds the
verified digest; changing to `selected` is a subsequent reviewed update. Legacy
YAML may remain readable while strict migration rejects its ambiguous paths.
Review the complete structural proposal before `bundle apply`. Existing seed
files and extensible user files remain user-owned. Modified managed files cause
a conflict; preserve the edits and resolve them explicitly before reproposing.
Do not overwrite customizations to make qualification pass.

Updates reuse the existing shared lock, journal, rollback and receipt mechanisms.
For an interruption, first establish that no apply process is active. Retain
the journal and follow [workspace recovery](workspace-configuration.md);
removing a lock is not permission to discard recovery evidence. `bundle apply`
also runs doctor after its receipt is durable: a warning or failure at that point
does not roll back the committed update. Inspect the report and resolve its
specific configuration or onboarding problem before claiming readiness. Never install
an older kernel over a pending newer journal as a rollback shortcut.
If doctor raises after apply, the command can exit 2 without printing its already
durable receipt. Check `.context-os/receipts/` and
`.context-os/installed-bundle.json` before retrying; a nonzero exit alone does not
establish rollback.

Qualification must exercise actual published 0.14, 0.15 and 1.0 bundles, customized
seeds and extensible files, managed conflicts, missing installed state, failed
and interrupted updates, and recovery. Synthetic unit fixtures complement
these release trials. Final qualification of each 1.x release also requires current host
evidence, independent exact-source reviews, full validation and the
[release asset gates](release-process.md).

The [published-bundle preflight](https://github.com/conorbronsdon/agent-context-os/blob/c4648d80fc72ed27abce527a05e952e42580783b/docs/evidence/upgrade-preflight-2026-09-29/report.md)
records early Windows upgrade and recovery controls. Its development snapshot
is separate from the final release qualification.
