# MCP client configs

Copy one of these next to your client's config and replace `/path/to/inventcraft`
with your checkout. On Windows use `.venv\Scripts\python.exe` and backslash-escaped
paths. Claude Code can also register it directly:

```bash
claude mcp add inventcraft -- /path/to/inventcraft/.venv/bin/python -m datum.mcp
```

- `mcp.json`: Claude Code (`.mcp.json`), Claude Desktop, Cursor, any `mcpServers` client.
- `opencode.json`: OpenCode.

Full guide: [docs/MCP.md](../../docs/MCP.md).
