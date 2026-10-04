# Feedback and open-issue review

Review date: 2026-10-04. Reviewer: Codex (GPT-6).
Source baseline: `08b7a76112605c49b287cb2e1b2e29e1f1a0ff35`.
This records source inspection and local regression controls. No new installed
host, paid backend, human onboarding, or publishing trial was performed.

## Recommended direction

Prioritize evidence that a receiving agent used the current reviewed source.
Portability and Git history are useful foundations, but a correct answer alone
can conceal an old citation, an unreviewed decision, or an unauthorized next
action. Keep the distinction between a proposal, applied context and a
reviewer's identity visible throughout the handoff.

The immediate changes add the Claude import, single-snapshot freshness and
revision comparisons, explicit Markdown review/supersession conventions, a
separate layered synthetic evaluation, and paired-receipt regression controls.
See [continuity](continuity.md), [first handoff](first-handoff.md), and the
[revision evaluation](continuity-benchmark.md#test-revision-attribution-and-proposed-actions).

The remaining product change should be a versioned decision-record contract,
tracked in [#235](https://github.com/conorbronsdon/agent-context-os/issues/235).
Give each record an immutable ID, explicit `proposed`, `accepted`, `rejected`
or `superseded` state, a self-reported reviewer and review time, and exact
supersession targets. Validate references and cycles, preserve legacy rows as
unknown, and expose current records without hiding their predecessors. Keep
this inside reviewed lifecycle changes, with migration and recovery controls;
do not silently widen schema 1 payloads or infer acceptance from a Git author.
Authenticated human approval would require a separate identity/approval
boundary tied to the exact proposal and is a further design decision.

For retrieval, [#236](https://github.com/conorbronsdon/agent-context-os/issues/236)
tracks binding each memory record to source ID, exact content
revision and dependency results from the actual retrieval event. Return the
replacement source pointer on invalidation, including when the proposed value
has not changed. Score recorded retrieval, citation, value and action layers
independently. The new synthetic evaluation establishes a response contract;
it does not implement or prove that live retrieval boundary.

## Open issues

| Issue | Assessment | Next action |
|---|---|---|
| [#230](https://github.com/conorbronsdon/agent-context-os/issues/230), release condition guards | Concrete dependency-free test fix | Review the added quoted/list-leading/spaced-key controls; close only after the fix lands |
| [#234](https://github.com/conorbronsdon/agent-context-os/issues/234), Autoposting CLI MCP | Careful proposal; optional expansion with unresolved capability inventory | Keep proposed until the uncertainty and draft-only restrictions below are resolved |
| [#76](https://github.com/conorbronsdon/agent-context-os/issues/76), framing | README now uses the proposed reviewed-handoff framing; launch work extends beyond prose | Keep an explicit acceptance checklist for remaining social artwork/drafts and contributor work; avoid another broad framing rewrite |
| [#183](https://github.com/conorbronsdon/agent-context-os/issues/183), preference scopes | Feedback concerns review/provenance, not a demonstrated preference conflict | Keep deferred under its existing evidence trigger; do not build a preference engine from this feedback |
| [#170](https://github.com/conorbronsdon/agent-context-os/issues/170), Grok bots | Distinct products and host surfaces need distinct evidence | Retain existing product disambiguation; require a named target and bounded discovery/approval trial before a descriptor |
| [#73](https://github.com/conorbronsdon/agent-context-os/issues/73), Cursor | CLI is first-class on main; IDE evidence remains experimental | Correct the issue's stale all-Cursor wording; preserve the independent IDE operator run and approval-control gate |
| [#71](https://github.com/conorbronsdon/agent-context-os/issues/71), Devin | Remaining account/operator evidence cannot be supplied by local source tests | Preserve the experimental tier and existing runbook; require the updated public fixture and dated account run |

There were seven distinct open issues in the returned search, with no open PRs.
The host issues require their named operator evidence rather than more static
tests that imply promotion.

## Autoposting proposal #234

The useful Context OS job is: approved local update text, remote draft, returned
draft ID/status, then a reviewed handoff linking the exact text revision and
remote resource. Cataloging that optional capability fits the existing model.
Installing it or turning Context OS into a publisher is outside this proposal.

The proposal does several things well: it pins a source commit/version,
separates stdio API-key authentication from hosted OAuth, describes the paid
backend, inventories deletion and publishing, and states its unverified
boundaries. No negative judgment of the vendor follows from those boundaries.

I inspected `server.ts`, `tools.ts`, `handler.ts`, `api-routes.ts`, the CLI
README and package metadata at
[`da104175c6545d521f33d4e06847674daa364458`](https://github.com/Autoposting-ai/autoposting-cli/tree/da104175c6545d521f33d4e06847674daa364458).
The server registers the complete tool list and dispatches requests directly.
The `api-request` bridge fetches a backend-owned route allow-list; a pinned
local commit cannot establish its future or authenticated contents.

There is also a specific draft-only trap: `create-post` exposes `scheduledAt`,
and the dispatcher passes it to `client.posts.create`. `update-post` can set
it too. Restricting only `publish-post` and `schedule-post` therefore does not
establish a draft-only boundary. A narrow wrapper/client policy would also
need parameter restrictions, ownership checks and a returned `draft` status.
Whether supplying `scheduledAt` actually schedules publishing remains a
backend behavior to verify; the exposed request path alone warrants inclusion
in the catalog's scheduling discussion.

The same commit has further paths outside those two tools: `publish-clip`
accepts `publish` and `schedule` modes, `retry-post` retries publishing, and
`create-agent`/`update-agent` configure publish agents and their schedules.
`api-request` can call any route the hosted allow-list returns, with an
arbitrary query and JSON body. The list is fetched once per client and
cached, so a tool-name or argument restriction does not bound it unless the
bridge is removed or its routes are filtered locally. `upload-media` and
`upload-clip` read whatever local path the model supplies and send the bytes
to the backend, so the inventory also needs a local-file egress boundary.
(Claude Code source check of the same pinned files, 2026-10-04; no install or
backend call.)

Before an entry PR, resolve these acceptance points:

1. Enumerate the selected authenticated dynamic routes out of band and redact
   account data, or ship a separately pinned restricted implementation that
   removes the bridge. Do not encode unresolved `arbitrary_execution` as a
   verified `false`; the current catalog uses booleans and cannot express
   uncertainty for that field.
2. Explain both tool and argument restrictions for the optional draft-only
   use case. Retain the complete underlying capability inventory even when a
   client is restricted. Do not describe guidance as server enforcement.
3. Identify exact account/brand/platform destinations, content revision,
   returned draft ID/status and any generation costs in the proposed handoff.
   Keep publishing, scheduling, uploads, webhooks and publish-agent runs
   separately reviewed.
4. Keep maturity `listed`, support `generic`, and transport boundaries honest.
   Re-check evidence on the entry author's actual review date. Dated source
   inspection does not establish authentication, uninstall or host conformance.

My recommendation is to welcome a revised optional catalog proposal while
keeping it behind core continuity work. The immediate schema question is
whether capability uncertainty should be representable across the catalog,
rather than special-cased for one vendor. That needs validator, generated
reference and migration tests before adoption.

The [Bluesky discussion](https://bsky.app/profile/conorbronsdon.com/post/3mwetvs5tyk2k)
could not be retrieved; the feedback supplied by the maintainer is the input
to this review. No additional statements are attributed to that thread.
