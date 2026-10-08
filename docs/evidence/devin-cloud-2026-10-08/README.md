# Devin cloud session lifecycle evidence

These runs used synthetic public fixtures, not personal-context data. Both ran
through the Devin v3 API as an organization service user, from a clean clone of
source `97b9d51`, against snapshot build
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

[api-97b9d51.json](api-97b9d51.json) used
[`live_conformance.py`](../../../adapters/devin/live_conformance.py) on
[`contextos-devin-live-fixture`](https://github.com/conorbronsdon/contextos-devin-live-fixture)
at `3d58d8f`. In one API session, Devin returned the root instruction canary and
the fixture commit without an explicit skill reference, and the user-only skill
did not fire. On an explicit `@skills:` turn, Devin returned the skill canary.
The fixture content and default head stayed unchanged, the session created no
pull request, Review was not invoked, and the session was archived. Mode:
`normal`.

## Lifecycle, apply and handoff (passed, 32 controls)

[lifecycle-97b9d51.json](lifecycle-97b9d51.json) used
[`cloud_lifecycle_conformance.py`](../../../adapters/devin/cloud_lifecycle_conformance.py)
on [`contextos-devin-cloud-fixture`](https://github.com/conorbronsdon/contextos-devin-cloud-fixture)
at `0243a0f`, the unmodified v1.1.1 release template. The run branch is
[`lifecycle/20261008T061145Z-162b70ee`](https://github.com/conorbronsdon/contextos-devin-cloud-fixture/commits/lifecycle/20261008T061145Z-162b70ee),
with final head `57c3d6c`. The handoff branch is
[`handoff/20261008T061145Z-162b70ee`](https://github.com/conorbronsdon/contextos-devin-cloud-fixture/commits/handoff/20261008T061145Z-162b70ee)
at `fef21c0`.

In one API session, for each of `@skills:context-setup`, `context-update` and
`context-end`:

- **Proposal, before approval.** Devin created exactly one kernel proposal and
  pushed it. Every commit up to that point only added pending inputs and
  proposals, with no receipt. The proposal touched only the phase's allowed
  paths: setup changed `identity/lifecycle-fixture.md` and `state/current.md`,
  and update and end each changed one `sessions/YYYY-MM-DD.md`. The proposal
  contained the required synthetic content.
- **Kernel check.** Locally, the fixture's kernel rejected a wrong digest
  against that proposal without mutation.
- **Approval.** Just before sending it, the harness rechecked that the remote
  branch had not moved. It then sent an approval naming the exact digest.
- **Apply.** Devin ran
  `bash scripts/contextos.sh apply … --confirm <digest> --runtime devin` and
  pushed the result. The pushed tree and receipt matched an independent replay
  of the same apply with the kernel at the pending commit: same receipt file,
  proposal ID and digest, runtime `devin`, file hashes, invariants, and Git
  heads bound to the pending commit.
- **Timing.** The harness held each proposal for 120 seconds before approving.
  On Devin's clock, 149-159 seconds passed from the pending commit to the apply,
  more than the harness's push-to-approval interval. Each duration is measured
  on one clock, so clock offset cancels. This is consistent with applying after
  approval. It is not proof: a host that delayed its push, or withheld an apply
  until approval, could defeat it.
- **Stale check.** For update and end, the kernel rejected re-applying the same
  proposal as stale without mutation.

`@skills:context-start` left the branch unchanged. After the end apply, Devin
created a parentless handoff branch whose tree equals the run branch without
pending inputs and proposals. A fresh API session ran `@skills:context-start` on
that branch and reported the complete next-action sentence, including its random
verification value. On the handoff tree that value exists only in `sessions/`.
Both branches were unchanged after the handoff, every pre-existing ref
(including `main`) was unchanged, and all sessions were archived.

## Limits

- Cloud sessions have no execution-authorization control. Devin's adherence to
  the approval step is observed through per-commit pushes, an independent kernel
  replay, and a timing-consistency check, not enforced. The kernel's digest check is the enforced boundary,
  and it does not authenticate who approved.
- The wrong-digest and stale rejections test the kernel locally, not Devin's
  restraint.
- Skill expansion is evidenced by each proposal's `workflow` field and kernel
  output, not by a session trajectory.
- The run branch stays fetchable in the same repository during the handoff. The
  handoff session is told to use only the parentless handoff branch; that is not
  enforced.
- The approver was the harness, acting as a synthetic external operator after
  validating each proposal. This is not evidence of human review.
- The build identity is a snapshot build ID. Devin does not expose a product
  version for cloud sessions.
- These runs do not establish Devin CLI, native Windows, or Review behavior.
