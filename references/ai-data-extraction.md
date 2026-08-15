# AI data extraction prior art

[`0xSero/ai-data-extraction`](https://github.com/0xSero/ai-data-extraction) is useful prior art for locating and parsing local conversation data from Gemini CLI, Claude Code, Codex, and other tools.

This project references it for workflow archaeology ideas; it is not vendored or installed as a dependency. Before running any history extractor:

- verify its parser against the current recording format (Gemini recordings may be append-oriented JSONL with structured content),
- constrain the scan to user-selected projects and dates,
- inventory metadata before reading message bodies,
- redact credentials, tool arguments, source paths, and personal data,
- exclude private thoughts/reasoning,
- review output before sharing, training on it, or committing it.

The local `scripts/mine-gemini-workflows.py` applies those boundaries to a narrow use case: it folds Gemini's append log into final state, then finds repeated workflows with positive validation evidence. It deliberately does not attempt a universal chat export; free-form content requires explicit session allowlisting and remains sensitive even after best-effort redaction.
