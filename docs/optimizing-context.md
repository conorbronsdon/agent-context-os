# Optimizing Context Files

The format of context files affects both token use and retrieval quality. PDFs often carry layout, font, header, and footer noise that clean Markdown avoids. Large, noisy files slow any agent session that loads them.

This guide covers how to convert common file formats to markdown and how to trim files for maximum efficiency.

---

## Why format matters

Claude reads everything in its context window as tokens. Different formats carry different amounts of overhead:

| Format | Token cost | Notes |
|--------|-----------|-------|
| `.md` / `.txt` | Low | Clean text, minimal overhead |
| Word / Google Doc | Medium | Formatting markup adds noise |
| HTML | Medium-high | Tag overhead, especially with complex layouts |
| PDF | High | Layout data, fonts, and page structure all add tokens |

Exact token cost depends on the parser, document, and host. The useful rule is qualitative: preserve the facts and structure an agent needs, and remove layout artifacts and repeated boilerplate.

The goal: your context should be **as short as possible while remaining complete**. Every token Claude spends parsing formatting noise is a token not spent on your actual task.

---

## The conversion prompt

The fastest approach: paste or attach any file directly into claude.ai or Claude Code and run the prompt below. Claude does the conversion for you — no tools or exports needed. This is how most people build out their initial context files.

Use this prompt in Claude Code or claude.ai. Paste the document content directly, or describe the file and attach it.

```
Convert the following document to clean, context-optimized markdown for use as a Claude context file.

Rules:
- Remove all formatting noise: page numbers, headers, footers, watermarks, table of contents entries, legal boilerplate, and any content that doesn't add meaning
- Flatten structure: prefer flat bullet lists and short paragraphs over deeply nested formatting or complex tables
- Cut redundancy: if the same point is made twice, keep the cleaner version
- Preserve all facts, decisions, and specific details — don't summarize or paraphrase content that needs to be exact
- Use markdown heading levels (##, ###) only where they genuinely help navigate the document
- Output only the converted markdown — no preamble, no explanation

[paste document content here]
```

After converting, apply the efficiency test to the result (see below).

---

## Common conversions

### PDF

**In claude.ai:** Attach the PDF directly to a message and run the conversion prompt above.

**In Claude Code:** If you have `pdftotext` installed (part of `poppler-utils`):
```bash
pdftotext your-file.pdf - | pbcopy   # macOS — copies to clipboard
```
Then paste into the conversion prompt.

Alternatively, paste the PDF text directly if it's copy-able, or take a screenshot and attach it.

### Word / Google Doc

**Word:** File → Save As → Plain Text (`.txt`), then run the conversion prompt on the output.

**Google Doc:** File → Download → Plain text (`.txt`), then run the conversion prompt.

For either: if the doc is short, just select all, copy, and paste directly into the conversion prompt.

### Spreadsheet / CSV

Spreadsheets often contain more data than Claude needs. Before converting, decide:
- Does Claude need the full data, or just the structure and a few representative rows?
- Would a written summary serve better than a table?

If you want a table, use the conversion prompt with this addition:
```
This is a spreadsheet. Convert to a clean markdown table. If it has more than 20 rows,
include the first 5 rows as examples and describe the pattern of the remaining data.
```

**Google Sheets → CSV:** File → Download → CSV, then paste into the conversion prompt.

### Web page / article

Use a browser's "Reader Mode" (Safari, Firefox) to strip navigation and ads, then copy the clean text. You can also:
- Use a service like [Reader](https://reader.readwise.io) to get clean markdown from any URL
- Select the relevant section, copy, and paste it into the conversion prompt — you rarely need the whole page

### Existing claude.ai project files

If you have PDFs or Word docs already uploaded to claude.ai projects:
1. Open the project and ask Claude to output the full text of each uploaded file
2. Run the conversion prompt on each output
3. Save the result as a `.md` file in this repo
4. Replace the original upload with the new `.md` file

This is also covered in the migration workflow — see [migration-guide.md](migration-guide.md).

---

## The efficiency test

Once you have a converted markdown file, read through it and apply this test to every section:

**"Would Claude understand this if it were half as long?"**

In most cases, the answer is yes. Things to cut aggressively:

- **Restatements** — if a point is made in the intro and again in the body, cut one
- **Obvious context** — Claude doesn't need to be told what a spreadsheet is, what LinkedIn is, or what a podcast episode is. Skip the definitions.
- **Hedging language** — "It's worth noting that," "As mentioned above," "For context," — cut these and just state the fact
- **Transition scaffolding** — section headers like "Introduction" or "Overview" that just describe what follows
- **Aspirational language** — goals stated as "we aim to" or "we strive to" — rewrite as facts or cut if they're not actionable
- **Anything Claude won't use** — legal disclaimers, author bios in a document you wrote, table of contents for a short file

A good context file reads like a briefing memo, not a document. Dense, specific, no filler.

---

## Keeping files short over time

Context files grow. Every time you add something, it's easier than removing something. A few conventions to prevent bloat:

- **One file per topic.** Don't merge your bio with your project strategy. Short focused files load faster and are easier to keep current.
- **Archive don't accumulate.** When a project ends or a strategy changes, move the old file to an `archive/` subdirectory rather than leaving it in active context paths.
- **Review on a schedule.** Run the efficiency test on your most-loaded files every few months. You'll almost always find sections that have become stale or redundant.
- **The staleness flag helps.** The `**Last Updated:**` convention in this repo exists for this reason — if a file is 90+ days old, review it before loading it.

---

## Setting up Claude Code

Claude Code is the recommended interface for working with this repo — it reads files directly, can write and commit changes, and supports slash commands.

**Install:**
```bash
npm install -g @anthropic-ai/claude-code
```

**Official docs:** https://docs.anthropic.com/en/docs/claude-code

**Run from this repo:**
```bash
cd /path/to/your-context-repo
claude
```

Claude Code reads `CLAUDE.md` automatically on startup. No additional configuration needed once the repo is set up.

If you're not ready to use Claude Code yet, all the conversion and optimization work in this guide can be done in claude.ai — you just won't be able to write files back to the repo directly.
