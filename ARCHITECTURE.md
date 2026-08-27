# Client architecture

## Ownership boundaries

`Yarp_mcpClient_BaseCore` owns discovery and the interactive request loop.
`MCPClientManager` owns the SDK context managers: one long-lived `mcp.Client`
per discovered URL, closed through one `AsyncExitStack`. Tool calls and resource
watchers therefore share managed SDK clients instead of opening raw transport
sessions. Every client has a finite read timeout so a stalled peer cannot wedge
discovery, a tool call, or a resource refresh indefinitely.

`Yarp_mcpClient_GeneralCheckerCore` adds policy around asynchronous work. It
recognizes the standard operation fields in a successful structured tool result,
selects the already-connected client for that tool's server, and asks
`BackgroundTaskManager` to track it.

`BackgroundTaskManager` owns exact operation identity and observation. It does
not infer correlation from a tool name or notification order. For each operation
it stores the server URL, status URI, latest revision, and authoritative snapshot.

Input modes own delivery. Their default `send_notification()` delegates to
`send_response()`, while a mode may override it if unsolicited messages need a
separate channel.

## Concurrency rules

- The SDK clients live longer than all tool calls and watcher tasks.
- A watcher subscribes only to its operation's `status_uri`.
- `ResourceUpdated` is an invalidation hint; the watcher always calls
  `read_resource()` to obtain state.
- Polling still occurs at `poll_interval_ms` so missed events or unsupported
  subscriptions do not strand an operation.
- Revisions must increase. Duplicate or out-of-order snapshots are ignored.
- A transition into `completed`, `failed`, or `cancelled` invokes callbacks once.
- Completion callbacks enqueue delivery. They never call the LLM recursively.
- The event worker acquires the conversation lock before resuming the LLM, so a
  deferred instruction such as "when the battery is low, perform X" can safely
  execute without racing a user turn.
- `_response_lock` serializes ordinary replies and unsolicited completion messages.
- Watchers stop before MCP clients, and MCP clients stop before input-mode cleanup.

## Adding an input mode

Implement `initialize`, `get_input`, `send_response`, and `cleanup` from
`InputMode`. Override `send_notification` only when completion updates must be
framed differently from normal responses.

## Adding an LLM backend

Implement the `LLMBackend` interface and return an OpenAI-compatible response
shape: the core reads `response.choices[0].message`, including its function calls.
The backend does not own MCP connections or operation tracking.

## Changing discovery

Keep the two phases distinct:

1. Discover `/mcp_server/*/info:o` and query server metadata through YARP.
2. Connect `mcp.Client`, call `list_tools()`, and retain that client for runtime.

If discovery becomes non-YARP in the future, replace phase one without moving
transport lifecycle management out of `MCPClientManager`.
