# Release process

Context OS releases one canonical full-template artifact: a deterministic tar of
the complete non-development component closure. GitHub's automatically generated
source archives are convenient repository snapshots, but they are not the
canonical template artifact.

## Assets and identity

For version `X.Y.Z`, the immutable release contains exactly:

- `agent-context-os-template-vX.Y.Z.tar` — deterministic uncompressed USTAR;
- `agent-context-os-template-vX.Y.Z.bundle.lock.json` — detached bundle lock;
- `agent-context-os-template-vX.Y.Z.provenance.json` — outer identity and digest
  binding;
- `agent-context-os-template-vX.Y.Z.OFFLINE-VERIFY.md` — version-specific offline
  verification instructions; and
- `SHA256SUMS` — SHA-256 values for the other four assets.

The archive contains exactly the paths recorded by the lock, beneath one
`agent-context-os-template-vX.Y.Z/` root. Development files, including CI,
tests, release tooling, the changelog, and contributor-only documentation, are
excluded. File order is the lock's portable path order. UIDs and GIDs are zero,
owner and group names are empty, modes are `0755` only for locked executable
files and `0644` otherwise, and every mtime is the source commit epoch.

The provenance binds the repository, anticipated tag, exact commit, template
identity, archive identity, whole lock-file digest, internal `bundle_sha256`,
instructions digest, generator version, source mode, and fixed epoch. It is
deterministic and deliberately excludes runner names, workflow IDs, temporary
paths, and wall-clock generation times.

## Automated qualification and draft staging

Only dispatch `.github/workflows/release.yml` from `main`, with the exact
reviewed 40-hex commit. Before dispatch:

1. merge the release-preparation PR after canonical validation, hosted Linux and
   Windows validation, and exact-SHA Claude plus free-Hermes reviews;
2. confirm the version constants, example workspace, and dated changelog agree;
3. from a locally authenticated GitHub CLI session whose token can read
   repository administration settings, require
   `GET /repos/conorbronsdon/agent-context-os/immutable-releases` to report
   `enabled: true`; and
4. confirm the release tag and release do not already exist.

The administration-read policy endpoint is intentionally not called with an
Actions `GITHUB_TOKEN`: GitHub does not grant that token repository
administration permission. Do not put a personal admin token in workflow inputs,
logs, repository secrets, or artifacts. The workflow uses the checked-in
[v0.12.0 release notes](releases/v0.12.0.md) as the draft description.

The workflow then fails closed through these gates:

1. require the dispatch ref, workflow SHA, input commit, checked-out `HEAD`, and
   `origin/main` to identify the same commit, and require a completely clean
   source;
2. run the canonical validator on that exact source;
3. build twice from its Linux Git index and compare every artifact byte;
4. verify the same Actions candidate in separate Linux and Windows extraction
   jobs, including execution of `python -m contextos bundle check` from the
   extracted archive;
5. only after both candidate jobs pass, create or confirm the exact lightweight
   tag through the GitHub API, classify the release-by-tag lookup by HTTP status,
   and create only after an exact 404; auth, network, rate-limit, and server
   failures stop the workflow. Stage all five assets in an unpublished draft,
   recover a duplicate-create race by rereading the exact draft without another
   upload, and carry its positive numeric release ID through every later job;
6. download those staged release assets—not the Actions copies—and verify them
   again in separate Linux and Windows directories; and
7. only after both staged-asset jobs pass, re-download the exact-run Actions
   candidate and draft assets, require them to be byte-identical, and recheck
   `main`, tag, numeric release ID, draft and non-prerelease state, checked-in
   title/body, exact asset names, IDs, sizes, and server-reported digests.

The workflow stops successfully with the release still an unpublished draft. A
green workflow is qualification evidence for that exact draft; it is not
publication and does not complete the release by itself.

Linux must report executable-mode verification as `true`. Windows must report
it as `false`, because directory sources there do not expose portable POSIX
executable bits. That is an explicit limitation, not a skipped success.

## Local admin publication

Publish only from a clean checkout of the exact commit named by the successful
workflow. Use the checked-in publisher with the exact workflow run ID and the
positive numeric release ID reported by `stage-draft` and `ready-to-publish`:

```bash
python scripts/publish-release.py \
  --repository conorbronsdon/agent-context-os \
  --run-id RUN_ID \
  --release-id RELEASE_ID \
  --commit REVIEWED_40_HEX_COMMIT \
  --version 0.12.0 \
  --tag v0.12.0
```

The publisher uses the existing locally authenticated `gh` session. Before the
irreversible numeric-release-ID PATCH, it requires all of the following:

- the exact workflow run and attempt are complete and successful on `main` for
  the reviewed commit, including every candidate, draft, and terminal readiness
  job;
- the exact attempt-qualified Actions candidate is selected, downloaded by its
  numeric artifact ID, checked against its server-reported ZIP size and digest,
  and re-read by ID before publication;
- local `HEAD` and the target repository's GitHub API `main` and
  `refs/tags/v0.12.0` equal the reviewed commit (the local `origin` is not an
  independent authority);
- the operator-selected numeric release is still a draft, is not a prerelease,
  and has the exact
  tag, title, checked-in body, and five asset IDs/names/sizes/digests;
- independently verified candidate and draft downloads are byte-identical, with
  the release state unchanged across repeated numeric-ID reads;
- no other release workflow has any nonterminal status; and
- the admin-only immutable-release policy endpoint reports `enabled: true`
  immediately before publication.

The GitHub API has no atomic compare-and-publish operation, so a small residual
time-of-check/time-of-use window remains. Coordinate one release operator and do
not mutate the tag or draft while publication runs. The publisher minimizes the
window, PATCHes only the verified numeric release ID, then repeats the tag,
metadata, asset, and byte checks. It requires `.immutable: true`, verifies the
release attestation, and verifies the attestation for each of the five freshly
downloaded published assets. Its JSON result records operator, timestamp, run
and attempt, Actions artifact ID, release ID, commit, policy result, immutable
state, asset metadata, and attestation results.

## Failure policy

- Before the tag exists, publish nothing; retain bounded Actions diagnostics and
  rerun only against the same commit.
- After the tag exists, never move or force-replace it. A failed staged release
  remains a draft for inspection. A rerun may resume only when both the tag and
  every downloaded draft asset are byte-identical to the same candidate; do not
  overwrite assets or delete forensic evidence automatically.
- If the candidate Actions artifact expires before local publication, rerun the
  complete qualification workflow against the same commit. Never publish a
  draft that can no longer be byte-compared to its exact-run candidate.
- If deterministic source or artifact verification fails after the tag exists,
  retire that version and fix the problem in a patch release.
- After publication, tags and assets are immutable. Correct errors with a notice
  and a new patch release, never by replacing bytes. If publication succeeds but
  the final immutable or attestation poll times out, do not PATCH or publish
  again; retry only the read-only numeric-ID, byte, immutable, and attestation
  checks with the same exact bindings:

```bash
python scripts/publish-release.py \
  --repository conorbronsdon/agent-context-os \
  --run-id RUN_ID \
  --release-id RELEASE_ID \
  --commit REVIEWED_40_HEX_COMMIT \
  --version 0.12.0 \
  --tag v0.12.0 \
  --verify-published
```

Both modes bind the numeric ID before any tag-based download; the tag is only an
identity and attestation cross-check and never selects the PATCH target. This
mode requires the numeric release to be published and immutable, repeats
the run, attempt, artifact, repository-ref, metadata, byte, and attestation
checks, and never issues a publication PATCH. Any post-publication integrity
mismatch retires v0.12.0 rather than authorizing mutation.

Consumers should follow the version-specific offline instructions and obtain
the expected digest through a channel they trust. Co-located checksums prove
consistency; GitHub's immutable-release attestation and independently observed
release identity provide publisher provenance.
