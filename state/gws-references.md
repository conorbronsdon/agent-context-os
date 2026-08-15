# Google Workspace References

Store IDs and references for Google Workspace resources you want Claude to query during sessions. The `/start` command reads this file when the gws MCP server is connected.

## How to use

Add a line for each resource you want to query. Then update `.claude/commands/start.md` to reference the relevant IDs.

## Sheets

```
# Format: Label: SPREADSHEET_ID (tab name if relevant)
# Example: Content log: 1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms (Sheet1)
```

| Label | Sheet ID | Tab |
|-------|----------|-----|
| [Your tracker name] | [PASTE SHEET ID HERE] | [Tab name] |

**How to find a Sheet ID:** Open the sheet in your browser. The ID is the long string in the URL between `/d/` and `/edit`:
```
https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms/edit
                                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                                        this is the Sheet ID
```

## Other resources

Add Drive folder IDs, Doc IDs, or Calendar IDs here as needed.

```
# Drive folder: [FOLDER_ID]
# Doc: [DOC_ID]
# Calendar: [CALENDAR_ID] (default is "primary")
```
