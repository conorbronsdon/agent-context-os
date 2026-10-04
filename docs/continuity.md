# Inspect the context behind a handoff

Use the existing lifecycle state and local transaction evidence to understand
what an agent should know and what was saved. Both views are offline and
read-only. They never infer permission from file content or synchronize native
memory. Their output may contain private context: review its audience before
sharing it.

## Briefing with sources

```bash
bash scripts/contextos.sh start --format markdown
bash scripts/contextos.sh start --briefing
bash scripts/contextos.sh start --source projects/lantern/requirements.md --format markdown
```

The default `start` JSON remains the metadata inventory. `--briefing`, Markdown
output, or explicit `--source` selection adds bounded excerpts, source paths,
selection reasons, normalized-text hashes, and freshness. Repeated `--source`
options select additional repository-relative Markdown files; they never cause
automatic routing or link expansion. The fixed sources are routing, configured
state, recent decision rows, and the latest session. Missing or unreadable
sources have an explicit status. Oversized sources are unavailable; unsafe
explicit paths are rejected.

Each excerpt is limited to 24 lines and 2,400 characters; decisions show the
last five table rows. Read the full source when the excerpt is insufficient.
Current state uses the existing 3/5/7-day policies for current priorities,
weekly priorities, and blockers. Other sources use a 90-day advisory threshold
when they contain a valid `**Last Updated:**` date. Missing dates remain unknown;
the report does not substitute filesystem modification time for confirmation.

The preview prints the recorded date and age for dated sources, explicitly
reports unknown ages, and labels future dates as future. Dates, excerpts and
hashes for each source describe one file snapshot. The earlier metadata
inventory and other sources are separate snapshots, so the whole report is
not an atomic workspace snapshot.

`source_id` is the repository-relative path. `sha256` identifies its complete
normalized UTF-8 text, including content omitted from the excerpt;
`sha256_raw` identifies the exact file bytes. Both appear in JSON, and the
normalized revision appears in Markdown. These identify file revisions, not
individual decisions or Git commits. CRLF and LF have the same normalized
revision and different raw hashes.

To compare a source with a previously captured normalized revision:

```bash
bash scripts/contextos.sh start --briefing \
  --source projects/lantern/requirements.md \
  --expect-source-revision projects/lantern/requirements.md=PREVIOUS_SHA256
```

Replace `PREVIOUS_SHA256` with the 64 lowercase hexadecimal characters from
the prior report. Quote the complete argument if the path contains spaces.
The check returns `matched`, `mismatch`, or `unavailable`, with the expected
and observed hashes. Sources without an expectation return `not_requested`.
An expectation never selects a new file; select additional files with
`--source`. A mismatch still returns the current source path, revision and
excerpt, so a reviewer can inspect the replacement even when its value is
unchanged. The command is read-only and always prints the report. It exits 0
when every expected revision matches, 1 when any is `mismatch` or
`unavailable`, and 2 for invalid arguments, so scripts can gate on the exit
status while agents read `revision_check.status` for each source.

This compares selected files only. It does not traverse claim dependencies,
authenticate a reviewer, prove which revision a host retrieved, or authorize
an outbound action. Stop relying on a mismatched record until its claim and
dependencies have been reviewed against the current source. The remaining
design recommendations are in the [feedback review](feedback-review-2026-10-04.md).

This is a source preview, not an agent read log. A recent date does not prove a
claim is correct, and an old decision can still be valid. Cite actual source
paths in the agent's briefing and distinguish unresolved assumptions from
confirmed decisions.

## Readable change history

```bash
bash scripts/contextos.sh history
bash scripts/contextos.sh history --details --path state/decisions.md
bash scripts/contextos.sh history --format json --limit 20
```

History lists recent local `.context-os/receipts/*.json` records by application
time, with changed paths, before/after hashes, and self-reported runtime. With
`--details`, it checks the matching proposal's digest and change list against
the receipt before showing its recorded diff. Missing or altered proposals do
not supply explanations; their status is shown. Malformed receipts produce
warnings while valid records remain visible. Reports read at most 1,000 receipt
files of at most 1 MiB each and return 1–100 matching entries.

Receipts and proposals are ignored local artifacts: they may be absent in
another clone, manually edited, or removed. Matching digests show consistency,
not authenticity. They do not authenticate a human, prove no other writes
occurred, verify a fact, or recover the model's reasoning. The diff can explain
a recorded rationale only when that rationale was actually saved. Use Git
history for committed changes and the canonical decision file for current
meaning. Do not move raw receipts into tracked session logs.

Each changed file already has its pre-apply and post-apply digests in the same
receipt, under `files_changed`. Content writes use normalized-text
`sha256_before`/`sha256_after`; structural changes use raw-byte
`sha256_before_raw`/`sha256_after_raw`. An absent file is represented by `null`.
The proposal digest identifies the reviewed proposal, not the post-apply
workspace. Apply rejects changed input snapshots before writing; a rejected
apply creates no successful receipt. The [revision benchmark](continuity-benchmark.md#test-revision-attribution-and-proposed-actions)
scores evidence and proposed actions separately.

For attached application repositories, supply the same explicit `--kernel-root`,
`--context-root`, and `--working-root` arguments used by lifecycle commands.
The existing project binding must validate. Reports read ContextRoot sources
and local receipts; they do not load application content as shared memory.

Try the [first handoff](first-handoff.md), then use the
[benchmark](continuity-benchmark.md) to check constrained continuity behavior.
