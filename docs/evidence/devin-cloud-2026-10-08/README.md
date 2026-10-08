# Devin cloud session lifecycle evidence

These runs used synthetic public fixtures, not personal-context data. Both ran
through the Devin v3 API as an organization service user, from a clean clone of
source `6516fbe`, against snapshot build
`sbj-f04a9b4dd96a43ff806501a2bedd34bf`. That build was checked before and after
each run. The artifacts keep controls, digests, receipt hashes, commit SHAs and
request hashes. Session IDs are hashed and redacted from request paths. The
artifacts contain no raw model output or credentials.

## Environment prerequisite

A cloud session checks out only repositories that have a repo blueprint in the
organization's environment. Naming a repository in the session-create request
did not check it out. The first API attempt found only the organization's
existing repositories on the VM, and Devin declined to report a canary from a
repository it could not see. Both fixtures were added as repo blueprints, and
build `sbj-f04a9b4dd96a43ff806501a2bedd34bf` was triggered and became active
before these runs. Use the same setup for a real Context OS repository.

## Instructions and skills (passed)

[api-6516fbe.json](api-6516fbe.json) used
[`live_conformance.py`](../../../adapters/devin/live_conformance.py) on
[`contextos-devin-live-fixture`](https://github.com/conorbronsdon/contextos-devin-live-fixture)
at `3d58d8f`. In one API session, Devin returned the root instruction canary and
the fixture commit without an explicit skill reference, and the user-only skill
did not fire. On an explicit `@skills:` turn, Devin returned the skill canary.
The fixture content and default head stayed unchanged, the session created no
pull request, Review was not invoked, and the session was archived. Mode:
`normal`.

## Lifecycle, apply and handoff (passed)

[lifecycle-6516fbe.json](lifecycle-6516fbe.json) used
[`cloud_lifecycle_conformance.py`](../../../adapters/devin/cloud_lifecycle_conformance.py)
on [`contextos-devin-cloud-fixture`](https://github.com/conorbronsdon/contextos-devin-cloud-fixture)
at `0243a0f`, the unmodified v1.1.1 release template. The run branch is
[`lifecycle/20261008T021553Z-21594c8f`](https://github.com/conorbronsdon/contextos-devin-cloud-fixture/commits/lifecycle/20261008T021553Z-21594c8f),
with final head `ef450aa`.

In one API session, for each of `@skills:context-setup`, `context-update` and
`context-end`:

- Devin created exactly one kernel proposal and pushed only the new pending
  input and proposal, with no receipt. The harness fetched the branch, validated
  the proposal, and found the required synthetic content.
- The harness rejected a wrong digest against that proposal without mutation.
- The harness then sent an approval naming the exact digest. Devin ran
  `bash scripts/contextos.sh apply … --confirm <digest> --runtime devin` and
  pushed the result. The harness verified exactly one new receipt binding that
  digest with runtime `devin`, and that the applied files matched the proposal's
  `after_text` with no other changes.
- For update and end, re-applying the same proposal was rejected as stale
  without mutation.

`@skills:context-start` left the branch unchanged. A fresh API session then ran
`@skills:context-start` on the branch and reported the random verification value
recorded as the end phase's next action. That value existed only in
`sessions/` and the committed pending end artifacts under `.context-os/`, and
the handoff session pushed nothing. All sessions were archived.

The branch's six commits alternate proposal and apply for setup, update and end.
An independent clone confirmed three receipts with runtime `devin` whose digests
match the artifact.

## Limits

- Cloud sessions have no execution-authorization control. Devin's adherence to
  the approval step is observed in this run, not enforced. The kernel's digest
  check is the enforced boundary, and it does not authenticate who approved.
- Skill expansion is evidenced by each proposal's `workflow` field and kernel
  output, not by a session trajectory.
- The approver was the harness, acting as a synthetic external operator after
  validating each proposal. This is not evidence of human review.
- The build identity is a snapshot build ID. Devin does not expose a product
  version for cloud sessions.
- These runs do not establish Devin CLI, native Windows, or Review behavior.
