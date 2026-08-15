# Google Workspace References

Optional placeholder for people who deliberately connect the current Google
Workspace CLI or another reviewed integration. The template does not read this
file, install an integration, or ship a live Google Workspace adapter. Review
[`references/google-workspace-cli-setup.md`](../references/google-workspace-cli-setup.md)
before enabling access.

Treat every identifier below as sensitive metadata. Do not populate or commit
it in a repository whose readers should not know the referenced accounts or
resources.

## How to use

If you adopt a separately reviewed integration, add only the identifiers it
needs and keep its services and permissions narrower than the account as a
whole. Review the exact command and target before every write; do not treat the
presence of an ID here as authorization to read or modify that resource.

## Sheets

```
# Format: Label: SPREADSHEET_ID (tab name if relevant)
# Example: Content log: [SPREADSHEET_ID] (Sheet1)
```

| Label | Sheet ID | Tab |
|-------|----------|-----|
| [Your tracker name] | [PASTE SHEET ID HERE] | [Tab name] |

**How to find a Sheet ID:** Open the sheet in your browser. The ID is the long string in the URL between `/d/` and `/edit`:
```
https://docs.google.com/spreadsheets/d/[SPREADSHEET_ID]/edit
                                   ^^^^^^^^^^^^^^^^
                                   this is the Sheet ID placeholder
```

## Other resources

Add Drive folder IDs, Doc IDs, or Calendar IDs here as needed.

```
# Drive folder: [FOLDER_ID]
# Doc: [DOC_ID]
# Calendar: [CALENDAR_ID] (default is "primary")
```
