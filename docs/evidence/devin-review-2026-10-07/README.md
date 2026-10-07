# Devin Review instruction evidence

These are synthetic controls in the public fixture repository
[`conorbronsdon/contextos-devin-review-fixture`](https://github.com/conorbronsdon/contextos-devin-review-fixture),
not personal-context data. Each run used
[`review_conformance.py`](../../../adapters/devin/review_conformance.py), which
reads GitHub only and binds the artifact to a clean source commit. Artifacts
keep commit SHAs, GitHub review and comment IDs, and hashes. Finding text is not
stored.

Review was triggered with **Run Devin's AI analysis** on the Devin Review page
for each pull request, using the account's Review trial. The organization's
Review settings keep findings in the Devin UI and post only a summary review to
GitHub. An operator therefore published the must-fire finding with Review's
**Post to GitHub** action. Devin marks that comment `user_posted`, and the
artifact records `finding_publication: user_posted`. Devin wrote the finding
text; the operator did not edit it.

## REVIEW.md (passed)

[review-md-762cde9.json](review-md-762cde9.json), source `762cde9`, checked
2026-10-07:

- The base commit `0d25618` holds exactly `README.md` and a `REVIEW.md`
  byte-identical to `adapters/devin/review-fixture/REVIEW.md.fixture`. The
  canary and marker appear in neither the README nor either pull request's
  title or body.
- Must fire: pull request #1 (head `d8e1c11`) adds exactly `control.txt` with
  the marker. Devin Review's summary review on that head reported one flag, and
  Devin's inline finding on `control.txt` at that head carries
  `CONTEXTOS_DEVIN_REVIEW_CANARY_63F0A2D8`.
- Must not fire: pull request #2 (head `1c6bbae`) adds exactly `benign.txt`,
  byte-identical to the checked-in benign fixture. Devin Review's latest summary
  on that head reads "No Issues Found", and no Devin review or comment on the
  pull request carries the canary.

[review-md-9eb7f3f.json](review-md-9eb7f3f.json) is the same run checked by an
earlier harness. It is superseded: that harness accepted any must-not-fire
summary, read only the first page of each list, and did not check the README or
pull request metadata.

## AGENTS.md

Pull requests #3 (must fire) and #4 (must not fire) on base `72704af` hold the
`AGENTS.md` control set. Devin Review reported one flag on #3 and no issues on
#4, each on its exact head. This set has no recorded artifact until its finding
is published to GitHub, so this file makes no `AGENTS.md` claim yet.

## Scope

Review stays a compatibility surface. It reads repository instructions; it
runs no lifecycle workflow, skill, hook, or proposal/apply. These runs do not
establish behavior for Devin CLI or cloud sessions.
