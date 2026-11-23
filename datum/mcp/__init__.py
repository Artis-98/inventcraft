"""The MCP server: how an AI agent designs in InventCraft.

    python -m datum.mcp            from source
    InventCraft.exe --mcp          from the installed build

It speaks MCP to the agent and the bridge protocol to a headless
InventCraft host, which it starts on the first call. It never imports the
geometry kernel itself. See docs/MCP.md.
"""
