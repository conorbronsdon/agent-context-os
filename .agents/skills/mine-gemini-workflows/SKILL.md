---
name: mine-gemini-workflows
description: Discover repeated, validated Gemini CLI workflows from a user-selected session directory and turn approved candidates into portable skills and parity tests without exporting private reasoning.
---

# Mine Gemini workflows

Use session evidence to find workflows worth porting. This is workflow archaeology, not a bulk conversation export.

## Non-negotiable privacy boundaries

- Require one explicitly selected Gemini project/session directory. Never crawl the entire home directory by default.
- Run the metadata-only pass first.
- Do not extract or summarize private thoughts, reasoning fields, tool arguments, secrets, or complete transcripts.
- Do not commit `.context-os/migrations/` or raw Gemini recordings.
- Ask before any `--include-content`, `--include-summaries`, or `--include-paths` pass and explain exactly which selected sessions will be read.
- A repeated pattern is a candidate, not authorization to create or install a skill.

## Procedure

### 1. Select evidence

Ask the user for the relevant Gemini project/session directory and optional date boundary. If they do not know the directory, help them locate candidate directories using names and modification dates only; do not read session bodies during discovery.

### 2. Create a metadata-only inventory

Run:

```bash
python3 scripts/mine-gemini-workflows.py \
  <selected-session-directory> \
  --output .context-os/migrations/<timestamp>/gemini-inventory.json
```

Add `--since YYYY-MM-DD` when the user supplied a date boundary. The default report includes tool names, validation status, file basenames, and session identifiers. It excludes message text, free-form workflow summaries, tool arguments, and full paths.

### 3. Rank candidates

Prioritize candidates that:

1. occur with positive validation in at least two sessions,
2. have successful validation evidence,
3. use a stable tool sequence,
4. solve a task the user expects to repeat.

Do not promote one-off activity or a repeated failure. Present the ranked candidates and evidence counts, then ask the user which ones to inspect.

### 4. Inspect only selected sessions

If metadata is insufficient, name the exact selected session IDs and ask permission to rerun with repeated `--session-id <id>` selectors plus only the required opt-in flag (`--include-summaries`, `--include-paths`, or `--include-content`). Content redaction is best-effort, not a guarantee; treat every opt-in report as sensitive. Thought/reasoning fields remain excluded. Review the output again before sharing or persisting it.

### 5. Draft, do not silently install

For each approved candidate:

- draft `.agents/skills/<workflow>/SKILL.md` as the portable core,
- add a thin `.claude/commands/<workflow>.md` adapter only if a Claude slash command is wanted,
- create a parity case from `docs/templates/workflow-parity.json`,
- record provenance using session IDs, immutable recording digests, and evidence counts, not transcript content,
- separate provider-neutral steps from Gemini-, Claude-, or Codex-specific tool adapters.

Show the draft and parity case before writing. Then run `bash scripts/validate-all.sh`.

### 6. Report limitations

State what the miner could not infer, including missing memory scratchpads, unsupported recording variants, unavailable tools, ambiguous validation, or workflows that need human judgment.

## Prior art

See `references/ai-data-extraction.md`. The linked extractor informed the inventory-first approach, but is not a dependency and should not be run against current recordings without format and privacy review.
