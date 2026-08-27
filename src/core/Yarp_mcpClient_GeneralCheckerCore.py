"""General-purpose client with MCP operation-resource tracking."""

import asyncio
import json
import logging
from typing import Any, Dict, List

from ..input_modes.input_mode_base import InputMode
from ..llm_backends.llm_backend_base import LLMBackend
from .background_task_manager import BackgroundTaskManager, TrackedOperation
from .Yarp_mcpClient_BaseCore import Colors, Yarp_mcpClient_BaseCore

logger = logging.getLogger(__name__)


class Yarp_mcpClient_GeneralCheckerCore(Yarp_mcpClient_BaseCore):
    """YARP MCP client that tracks long-running server operations."""

    def __init__(self, input_mode: InputMode, llm_backend: LLMBackend, custom_prompt_file: str = None,
                 enableExplicitLogging: bool = True):
        super().__init__(
            input_mode, llm_backend, custom_prompt_file=custom_prompt_file, logger=logger,
            enableExplicitLogging=enableExplicitLogging,
        )
        self.task_manager = BackgroundTaskManager()
        self.task_manager.register_completion_callback(self._on_operation_completion)
        self._operation_events: asyncio.Queue[tuple[TrackedOperation, str] | None] = asyncio.Queue()
        self._operation_event_worker: asyncio.Task[Any] | None = None

    async def _on_operation_completion(
        self, operation_id: str, operation: TrackedOperation, message: str,
    ) -> None:
        """Queue completion delivery so a watcher never re-enters the LLM loop."""
        await self._operation_events.put((operation, message))

    async def _deliver_operation_events(self) -> None:
        while True:
            event = await self._operation_events.get()
            try:
                if event is None:
                    return
                operation, message = event
                notification = (
                    f"Operation {operation.operation_id} on {operation.server_name} "
                    f"finished with status '{operation.status}'."
                )
                self.conversation_history.append({
                    "role": "system",
                    "content": f"[SERVER OPERATION UPDATE] {message}",
                })
                print(f"\n{Colors.OKGREEN}{'=' * 80}")
                print("SERVER OPERATION FINISHED")
                print(f"{'=' * 80}\n{message}\n{'=' * 80}{Colors.ENDC}\n")
                async with self._response_lock:
                    await self.input_mode.send_notification(notification)

                # Resume the original request through the normal tool-calling
                # loop. The conversation lock prevents this background trigger
                # from racing a user-initiated LLM turn.
                continuation_request = (
                    "A tracked server operation has reached a terminal state. "
                    "Continue the user's pending request now: perform any action "
                    "they asked to happen at this condition, using tools when needed. "
                    "If no deferred action was requested, briefly acknowledge the result. "
                    f"Authoritative operation snapshot: {message}"
                )
                async with self._conversation_lock:
                    response = await self.process_user_message(continuation_request)
                if response and response.strip():
                    async with self._response_lock:
                        await self.input_mode.send_response(response)
            except Exception as exc:
                self.fancyLog.ERROR(f"Could not deliver operation completion: {exc}")
            finally:
                self._operation_events.task_done()

    def _get_system_prompt_additions(self) -> str:
        return """
Additional rules for this client:
1. Long-running tools return an operation_id and status_uri and are tracked automatically.
2. Use get_tracked_operation for one exact operation and list_tracked_operations for a summary.
3. Several operations can run concurrently; identify them by operation_id, never by tool name alone.
4. Use cancel_tracked_operation when the user asks to interrupt tracked work.
5. A completion update is authoritative only after the client reads the operation resource.
6. Be helpful and conversational while executing YARP tools."""

    def get_available_tools(self) -> List[Dict[str, Any]]:
        tools = super().get_available_tools()
        tools.extend([
            {
                "type": "function",
                "function": {
                    "name": "get_tracked_operation",
                    "description": "Return the latest snapshot for one tracked server operation.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "operation_id": {
                                "type": "string",
                                "description": "Exact operation ID returned by a long-running tool",
                            }
                        },
                        "required": ["operation_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "list_tracked_operations",
                    "description": "List all operations tracked during this client session.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "cancel_tracked_operation",
                    "description": (
                        "Cancel one exact tracked operation on its owning server. "
                        "For navigation this also requests that the robot stop."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "operation_id": {
                                "type": "string",
                                "description": "Exact operation ID to cancel",
                            }
                        },
                        "required": ["operation_id"],
                    },
                },
            },
        ])
        return tools

    async def _handle_tool_call(self, tool_call: Any) -> Dict[str, Any]:
        fn_name = tool_call.function.name
        fn_args = json.loads(tool_call.function.arguments)

        if fn_name == "get_tracked_operation":
            return await self.task_manager.get_operation(fn_args.get("operation_id", ""))
        if fn_name == "list_tracked_operations":
            return await self.task_manager.list_operations()
        if fn_name == "cancel_tracked_operation":
            operation_id = fn_args.get("operation_id", "")
            tracked = await self.task_manager.get_operation(operation_id)
            if not tracked.get("success"):
                return tracked
            server_name = tracked["server_name"]
            server_url = self.mcp_urls.get(server_name)
            if not server_url:
                return {
                    "success": False,
                    "error": f"Server {server_name} is not connected",
                }
            return await self.call_mcp_tool(
                "cancel_operation", {"operation_id": operation_id}, server_url,
            )

        result = await super()._handle_tool_call(tool_call)
        if not result.get("success"):
            return result

        operation_id = result.get("operation_id")
        status_uri = result.get("status_uri")
        if not operation_id or not status_uri:
            return result

        server_name = self.tool_to_server.get(fn_name)
        server_url = self.mcp_urls.get(server_name, "") if server_name else ""
        if not server_url:
            result["tracking"] = {
                "success": False,
                "error": f"Cannot identify the server for operation {operation_id}",
            }
            return result

        result["tracking"] = await self.task_manager.track_operation(
            operation_id=str(operation_id),
            operation_type=str(result.get("operation_type", fn_name)),
            status_uri=str(status_uri),
            server_name=server_name,
            server_url=server_url,
            client=self.mcp_clients.get(server_url),
            poll_interval_ms=int(result.get("poll_interval_ms", 1000)),
        )
        if result["tracking"].get("success"):
            print(
                f"{Colors.OKCYAN}Tracking server operation {operation_id} "
                f"at {status_uri}{Colors.ENDC}"
            )
        return result

    async def _run_loop_setup(self) -> None:
        self._operation_event_worker = asyncio.create_task(
            self._deliver_operation_events(), name="deliver-yarp-operation-events",
        )

    async def _run_loop_cleanup(self) -> None:
        await self.task_manager.cleanup()
        await self._operation_events.put(None)
        if self._operation_event_worker is not None:
            await self._operation_event_worker
            self._operation_event_worker = None
