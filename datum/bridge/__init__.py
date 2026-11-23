"""The bridge: how something outside InventCraft drives a document.

An agent, through the MCP server in ``datum.mcp``, or anything else that
speaks the protocol, sends requests and gets answers about documents. The
work is done by ``ops``, which is plain Python over ``datum.core``.  A
*host* runs those ops: the headless one in ``host``, a copy of InventCraft
with no window, started on demand, which may die without taking anything
else with it; and, later, the running application itself.

Nothing in this package's own namespace imports OpenCASCADE. ``client``
and ``protocol`` are what the MCP server loads, and the server never
touches geometry: a crash in the kernel takes down a host, which is
started again, and never the conversation.

See docs/MCP.md.
"""

PROTOCOL_VERSION = 1
