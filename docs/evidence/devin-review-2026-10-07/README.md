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

[review-md-7888673.json](review-md-7888673.json), source `7888673`, checked
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

Each pull request's head tree held the unchanged base files plus only its
added control file.

## AGENTS.md (passed)

[agents-md-502c728.json](agents-md-502c728.json), source `502c728`, checked
2026-10-07:

- The base commit `72704af` holds exactly `README.md` and an `AGENTS.md`
  byte-identical to `adapters/devin/review-fixture/AGENTS.md.fixture`, the file
  Context OS ships. The canary and marker appear in neither the README nor
  either pull request's title or body.
- Must fire: pull request #3 (head `ba65163`) adds exactly `control.txt` with
  the `AGENTS.md` marker. Devin Review's summary on that head reported one flag,
  and Devin's inline finding on `control.txt` at that head carries
  `CONTEXTOS_DEVIN_AGENTS_CANARY_E6DF38BF`.
- Must not fire: pull request #4 (head `6ad833d`) adds exactly `benign.txt`.
  Devin Review's latest summary on that head reads "No Issues Found", and no
  Devin review or comment on the pull request carries the canary.

Each pull request's head tree held the unchanged base files plus only its
added control file.

## Scope

Review stays a compatibility surface. It reads repository instructions; it
runs no lifecycle workflow, skill, hook, or proposal/apply. These runs do not
establish behavior for Devin CLI or cloud sessions.
