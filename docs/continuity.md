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

For attached application repositories, supply the same explicit `--kernel-root`,
`--context-root`, and `--working-root` arguments used by lifecycle commands.
The existing project binding must validate. Reports read ContextRoot sources
and local receipts; they do not load application content as shared memory.

Try the [first handoff](first-handoff.md), then use the
[benchmark](continuity-benchmark.md) to check constrained continuity behavior.
