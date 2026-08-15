# Google Workspace References

Legacy placeholder retained so existing users do not lose locally recorded IDs. The current template does not read this file or ship a Google Workspace adapter. See `references/gws-mcp-setup.md` before connecting a replacement.

Treat every identifier below as sensitive metadata. Do not populate or commit it in a repository whose readers should not know the referenced accounts or resources.

## How to use

If you adopt a separately reviewed integration, add only the identifiers it needs and keep the integration's permissions narrower than the account as a whole.

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
