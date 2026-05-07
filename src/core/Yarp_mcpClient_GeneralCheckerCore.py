import json
import asyncio
import logging
from typing import Dict, Any, List
from ..llm_backends.llm_backend_base import LLMBackend
from ..input_modes.input_mode_base import InputMode
from .background_task_manager import BackgroundTaskManager
from .Yarp_mcpClient_BaseCore import Yarp_mcpClient_BaseCore, Colors

logger = logging.getLogger(__name__)


class Yarp_mcpClient_GeneralCheckerCore(Yarp_mcpClient_BaseCore):
    """YARP MCP client core with background monitoring and checking capabilities."""

    def __init__(self, input_mode: InputMode, llm_backend: LLMBackend):
        """Initialize the checker core client with monitoring support.

        Args:
            input_mode: Input mode for getting user input
            llm_backend: LLM backend for chat completion
        """
        super().__init__(input_mode, llm_backend, custom_prompt_file=None)

        # Monitoring-specific attributes
        self.monitoring_metadata: Dict[str, Dict[str, Any]] = {}  # Tool name -> monitoring metadata

        # Initialize background task manager
        self.task_manager = BackgroundTaskManager(self.call_mcp_tool)
        self.task_manager.register_notification_callback(self._on_task_completion)
        self.notification_dispatcher.register_handler("*", self.task_manager.handle_notification)

    async def _on_task_completion(self, task_id: str, task, message: str):
        """Callback when a background monitoring task completes

        Args:
            task_id: ID of the completed task
            task: The MonitoringTask object
            message: Completion message
        """
        # Add a system message to conversation history to notify the user
        notification = {
            "role": "system",
            "content": f"[BACKGROUND TASK COMPLETED] {message}"
        }
        self.conversation_history.append(notification)

        # Print prominent notification to terminal
        print(f"\n{Colors.OKGREEN}{'='*80}")
        print(f"🔔 BACKGROUND MONITORING TASK COMPLETED")
        print(f"{'='*80}")
        print(f"{message}")
        print(f"{'='*80}{Colors.ENDC}\n")

        # System bell/alert
        print("\a", end="", flush=True)

        # If input mode supports notifications, send through there
        if hasattr(self.input_mode, 'send_notification'):
            try:
                await self.input_mode.send_notification(message)
            except Exception as e:
                logger.warning(f"Could not send notification through input mode: {e}")

        # Invoke the LLM to respond to the notification
        # Let process_user_message add a user message to trigger LLM response
        try:
            response = await self.process_user_message("[A background monitoring task has completed. Please acknowledge and summarize the result for the user.]")
            if response and response.strip():
                await self.input_mode.send_response(response)
        except Exception as e:
            logger.error(f"Error generating response to task completion: {e}")

    async def _track_server_side_task(self, fn_name: str, result: Dict[str, Any]):
        """Create a local shadow task for server-side MCP task notifications."""
        if not result.get("success") or not result.get("task_id"):
            return

        task_id = result["task_id"]
        server_name = self.tool_to_server.get(fn_name)
        server_url = self.mcp_urls.get(server_name, "") if server_name else ""

        if fn_name in {
            "goto_target_by_absolute_location",
            "goto_target_by_relative_location",
            "follow_path",
        }:
            await self.task_manager.track_external_task(
                task_id=task_id,
                target_tool="get_navigation_status",
                condition="status == 'goal_reached' or status in ['aborted', 'failing', 'error']",
                server_url=server_url,
                timeout=300.0,
            )
        elif fn_name == "start_battery_charge_monitor":
            await self.task_manager.track_external_task(
                task_id=task_id,
                target_tool="get_battery_charge",
                condition=result.get("condition", "True"),
                server_url=server_url,
                timeout=0.0,
            )

    def _get_system_prompt_additions(self) -> str:
        """Get additional text to add to system prompt for monitoring capabilities."""
        # Add monitoring capabilities section
        monitoring_tools = [t for t in self.tool_descriptions_cache.keys() if t in self.monitoring_metadata]

        prompt_additions = """
When using YARP tools:
1. Use function calls for actual operations - do NOT generate fake JSON or mock responses
2. Describe what you're doing in plain English alongside the function calls
3. For monitoring tasks, always explain the condition you're waiting for
4. Be helpful and conversational while executing YARP tools
5. Multiple monitoring tasks can run simultaneously in the background
6. Users can ask "what's the status?" at any time and you can check with get_monitoring_status()"""

        if monitoring_tools:
            prompt_additions += f"""

**Background Monitoring Capabilities** (available for {len(monitoring_tools)} tools):
You have access to background monitoring tools that allow you to:
- `start_monitoring(target_tool, condition, poll_interval, timeout)` - Start monitoring a tool and wait for a condition
- `get_monitoring_status(task_id)` - Check status of a monitoring task
- `stop_monitoring(task_id)` - Cancel a monitoring task
- `list_monitoring_tasks()` - List all active monitoring tasks

Examples:
- User: "Let me know when navigation is complete"
  → Call: start_monitoring("get_navigation_status", "status == 'reached'")
- User: "Wait until battery is below 20%"
  → Call: start_monitoring("get_battery_charge", "charge < 20")
- User: "Tell me when position reaches coordinates X,Y"
  → Call: start_monitoring("get_current_position", "x > 5.0 and y < 3.0")

The monitoring task will run in the background and notify you when the condition is met."""

        return prompt_additions

    def get_available_tools(self) -> List[Dict[str, Any]]:
        """Build tools dynamically from discovered tool descriptions, adding monitoring tools."""
        # Get base tools from parent
        tools = super().get_available_tools()

        # Add special background monitoring tools
        tools.extend([
            {
                "type": "function",
                "function": {
                    "name": "start_monitoring",
                    "description": "Start a background task to monitor a tool and wait for a condition to be met. Useful for waiting for navigation completion, battery level changes, or other state transitions. The task will poll the specified tool at regular intervals and notify when the condition is satisfied.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "target_tool": {
                                "type": "string",
                                "description": "Name of the tool to monitor (e.g., 'get_navigation_status', 'get_battery_charge')"
                            },
                            "condition": {
                                "type": "string",
                                "description": "Condition to wait for. Use Python comparison syntax (e.g., \"status == 'reached'\", \"charge > 80\", \"value < 10\"). The condition is evaluated against the tool's result."
                            },
                            "poll_interval": {
                                "type": "number",
                                "description": "Seconds between polling attempts (default: 1.0)",
                                "default": 1.0
                            },
                            "timeout": {
                                "type": "number",
                                "description": "Maximum seconds to wait before timing out (default: 60.0)",
                                "default": 60.0
                            }
                        },
                        "required": ["target_tool", "condition"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "stop_monitoring",
                    "description": "Cancel a background monitoring task.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "task_id": {
                                "type": "string",
                                "description": "ID of the monitoring task to stop (returned from start_monitoring)"
                            }
                        },
                        "required": ["task_id"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_monitoring_status",
                    "description": "Check the status of a background monitoring task.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "task_id": {
                                "type": "string",
                                "description": "ID of the monitoring task (returned from start_monitoring)"
                            }
                        },
                        "required": ["task_id"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "list_monitoring_tasks",
                    "description": "List all active background monitoring tasks and their status.",
                    "parameters": {
                        "type": "object",
                        "properties": {}
                    }
                }
            }
        ])

        return tools

    async def _handle_tool_call(self, tool_call: Any) -> Dict[str, Any]:
        """Handle a tool call, with special handling for monitoring tasks."""
        fn_name = tool_call.function.name
        fn_args = json.loads(tool_call.function.arguments)

        # Handle special background monitoring tools
        if fn_name == "start_monitoring":
            target_tool = fn_args.get("target_tool")
            condition = fn_args.get("condition")
            poll_interval = fn_args.get("poll_interval", 1.0)
            timeout = fn_args.get("timeout", 60.0)
            server_url = None

            # Determine which server the target tool belongs to
            if target_tool in self.tool_to_server:
                server_name = self.tool_to_server[target_tool]
                if server_name in self.mcp_urls:
                    server_url = self.mcp_urls[server_name]
            else:
                # Use first available server
                server_url = next(iter(self.mcp_urls.values())) if self.mcp_urls else None

            result = await self.task_manager.start_monitoring(
                target_tool=target_tool,
                condition=condition,
                poll_interval=poll_interval,
                timeout=timeout,
                server_url=server_url
            )

            # Print feedback about the monitoring activation
            if result.get("success"):
                task_id = result.get("task_id")
                print(f"\n{Colors.OKGREEN}{'='*80}")
                print(f"✅ BACKGROUND MONITORING ACTIVATED")
                print(f"{'='*80}")
                print(f"   Task ID:        {Colors.BOLD}{task_id}{Colors.ENDC}{Colors.OKGREEN}")
                print(f"   Monitoring:     {target_tool}")
                print(f"   Condition:      {condition}")
                print(f"   Poll Interval:  {poll_interval}s")
                print(f"   Timeout:        {timeout}s")
                print(f"{'='*80}{Colors.ENDC}\n")
            else:
                error_msg = result.get("error", "Unknown error")
                print(f"\n{Colors.FAIL}❌ Failed to start monitoring: {error_msg}{Colors.ENDC}\n")

            return result

        elif fn_name == "stop_monitoring":
            task_id = fn_args.get("task_id")
            result = await self.task_manager.stop_monitoring(task_id)

            # Print feedback about monitoring stop
            if result.get("success"):
                print(f"\n{Colors.WARNING}⏹️  Monitoring task {task_id} stopped{Colors.ENDC}\n")
            else:
                error_msg = result.get("error", "Unknown error")
                print(f"\n{Colors.FAIL}❌ Failed to stop monitoring: {error_msg}{Colors.ENDC}\n")

            return result

        elif fn_name == "get_monitoring_status":
            task_id = fn_args.get("task_id")
            result = await self.task_manager.get_task_status(task_id)

            # Print feedback about monitoring status check
            if result.get("success"):
                status = result.get("status")
                print(f"\n{Colors.OKCYAN}📊 Monitoring Status:{Colors.ENDC}")
                print(f"   Task ID:        {result.get('task_id')}")
                print(f"   Status:         {status}")
                print(f"   Target Tool:    {result.get('target_tool')}")
                print(f"   Condition:      {result.get('condition')}")
                print(f"   Elapsed:        {result.get('elapsed_time', 0):.1f}s")
                print(f"   Timeout:        {result.get('timeout')}s")
                if result.get('last_result'):
                    print(f"   Last Result:    {json.dumps(result.get('last_result'), indent=18)}")
                print()
            elif result.get("error"):
                error_msg = result.get("error", "Unknown error")
                print(f"\n{Colors.FAIL}❌ {error_msg}{Colors.ENDC}\n")

            return result

        elif fn_name == "list_monitoring_tasks":
            result = await self.task_manager.list_tasks()

            # Print feedback about active monitoring tasks
            tasks = result.get("tasks", [])
            if tasks:
                print(f"\n{Colors.OKCYAN}{'='*80}")
                print(f"📋 ACTIVE MONITORING TASKS ({len(tasks)} total)")
                print(f"{'='*80}{Colors.ENDC}")
                for i, task in enumerate(tasks, 1):
                    print(f"\n  Task {i}:")
                    print(f"    ID:         {task.get('task_id')}")
                    print(f"    Tool:       {task.get('target_tool')}")
                    print(f"    Condition:  {task.get('condition')}")
                    print(f"    Status:     {task.get('status')}")
                    print(f"    Elapsed:    {task.get('elapsed_time', 0):.1f}s / {task.get('timeout')}s")
                print(f"\n{Colors.OKCYAN}{'='*80}{Colors.ENDC}\n")
            else:
                print(f"\n{Colors.OKCYAN}📋 No active monitoring tasks{Colors.ENDC}\n")

            return result

        else:
            # For regular tools, use parent's implementation
            result = await super()._handle_tool_call(tool_call)
            await self._track_server_side_task(fn_name, result)
            return result

    async def _run_loop_setup(self):
        """Setup hook to initialize the background task manager event loop."""
        # Set the main event loop for background task manager
        self.task_manager.main_loop = asyncio.get_running_loop()

    async def _run_loop_cleanup(self):
        """Cleanup hook to stop background tasks."""
        # Cleanup background task manager
        await self.task_manager.cleanup()
