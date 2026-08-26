# MCP Efficiency Guidelines

## Always Set Limits

Every MCP call that returns a list should include a `maxResults` or `limit` parameter. Unbounded queries waste tokens and slow down sessions.

## Per-Tool Defaults

| Tool | Parameter | Default |
|------|-----------|---------|
| Gmail (search/list) | `maxResults` | 10 |
| Google Calendar (list events) | `maxResults` | 10 |
| Google Sheets | Range | Named range or specific `A1:Z50`, never whole-sheet |

## Prefer Snippets

When scanning emails, use list/search results (which include snippets) before fetching full message bodies. Only fetch the full body when the snippet confirms relevance.

## Cache Layer

If `state/cache/_meta.yaml` exists and defines cached data sources, check cache freshness before making live MCP calls. A cache hit saves a full round-trip.

## Token Budget

Keep total MCP-sourced content under ~5k tokens during session start. This leaves room for the briefing, state files, and user interaction without blowing up context.

## Quick Reference

1. Set `maxResults` / `limit` on every list call
2. Read snippets before full bodies
3. Check cache before live calls
4. Stay under 5k tokens for startup MCP pulls
