# Repository map

This repository is the conversational MCP client. It discovers YARP-hosted MCP
servers, exposes their tools to an LLM, executes tool calls, and follows
long-running server operations.

## Start here

| Path | Responsibility |
|---|---|
| `Yarp_mcpClient_GeneralPurpose.py` | CLI entry point; selects input mode and LLM backend. |
| `src/core/Yarp_mcpClient_BaseCore.py` | YARP discovery, MCP client ownership, tool discovery/routing, and the main conversation loop. |
| `src/core/Yarp_mcpClient_GeneralCheckerCore.py` | Adds automatic operation tracking and user-facing completion delivery. |
| `src/core/background_task_manager.py` | Subscribes to exact operation resources, refetches snapshots, polls as fallback, and orders revisions. |
| `src/input_modes/` | Terminal, YARP, and ROS-facing input/output adapters. |
| `src/llm_backends/` | Remote and local model adapters. |
| `tests/` | Focused operation-tracking tests. |
| `ASYNC_OPERATIONS.md` | The client/server contract and runtime sequence. |
| `ARCHITECTURE.md` | Component ownership and common change recipes. |

## Runtime path

```text
input mode -> GeneralCheckerCore -> LLM backend
                           | tool call
                           v
                    BaseCore router
                           |
                    persistent MCP Client
                           |
                    discovered MCP server

long-running result -> BackgroundTaskManager
                    -> subscribe to status_uri
                    -> ResourceUpdated hint or poll timeout
                    -> read authoritative resource
                    -> queued input-mode notification
```

YARP discovery and MCP transport have separate jobs. YARP RPC ports advertise a
server name, MCP URL, and prompt addendum. MCP handles tools, resources, and
subscriptions after discovery.

## Commands

```bash
uv sync --group dev
uv run python Yarp_mcpClient_GeneralPurpose.py --mode chat --model remote
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run --group dev pytest -p anyio.pytest_plugin -q
```

Plugin autoload is disabled in the test command because ROS installations may
publish unrelated system-wide pytest plugins with dependencies outside this
project environment.
