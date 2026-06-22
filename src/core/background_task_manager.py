import asyncio
import json
import logging
from typing import Dict, Any, Optional, Callable, List
from datetime import datetime
from threading import Lock
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class MonitoringTask:
    """Represents a server-side task tracked through MCP notifications."""
    task_id: str
    target_tool: str
    timeout: float
    condition: str  # e.g., "status == 'reached'" or "charge < 20"
    server_url: str
    created_at: datetime = field(default_factory=datetime.now)
    last_result: Optional[Dict[str, Any]] = None
    is_active: bool = True
    is_complete: bool = False
    completion_reason: str = ""  # "notification", "cleanup"
    completion_result: Optional[Dict[str, Any]] = None

    def elapsed_time(self) -> float:
        """Get elapsed time in seconds since task creation"""
        return (datetime.now() - self.created_at).total_seconds()

    def remaining_time(self) -> float:
        """Get remaining time before timeout"""
        return max(0, self.timeout - self.elapsed_time())


class BackgroundTaskManager:
    """Tracks server-side MCP tasks and completes them from task notifications."""

    def __init__(self):
        """Initialize the notification-backed task manager."""
        self.tasks: Dict[str, MonitoringTask] = {}
        self.task_lock = Lock()
        self.completion_callbacks: List[Callable] = []

    def register_completion_callback(self, callback: Callable):
        """Register a callback for task completion events.

        Args:
            callback: Async callable that takes (task_id, task, notification_message)
        """
        self.completion_callbacks.append(callback)

    async def handle_notification(self, notification_method: str, params: Dict[str, Any]):
        """Handle an incoming notification from an MCP server

        This method processes notifications about task events (e.g., tool call completion,
        status changes) and updates monitoring tasks accordingly.

        Args:
            notification_method: The notification method name (e.g., "task/complete", "task/status_changed")
            params: The notification parameters
        """
        if not self._is_monitoring_notification(notification_method):
            return

        event_type = params.get("event") or self._event_type_from_method(notification_method)
        task_id = params.get("task_id") or params.get("taskId")
        tool = params.get("tool") or params.get("target_tool")
        server_url = params.get("_server_url")
        mcp_task_status = params.get("status")
        data = self._extract_notification_result(params)

        notifications_to_send = []
        with self.task_lock:
            if task_id and task_id in self.tasks:
                task = self.tasks[task_id]
                if task.is_complete:
                    task.last_result = data
                    return
                candidate_tasks = [task]
            else:
                candidate_tasks = [
                    task for task in self.tasks.values()
                    if task.is_active
                    and not task.is_complete
                    and (not tool or task.target_tool == tool)
                    and (not server_url or not task.server_url or task.server_url == server_url)
                ]

            for task in candidate_tasks:
                task.last_result = data

                condition_met = self._evaluate_condition(data, task.condition)
                terminal_task_status = (
                    notification_method == "notifications/tasks/status"
                    and mcp_task_status in {"completed", "failed", "cancelled"}
                )
                exact_task_completed = (
                    bool(task_id)
                    and task_id == task.task_id
                    and (
                        event_type in {"complete", "completed", "failed", "cancelled"}
                        or terminal_task_status
                    )
                )

                if condition_met or exact_task_completed:
                    task.is_active = False
                    task.is_complete = True
                    task.completion_reason = "notification"
                    task.completion_result = data

                    message = (
                        f"🔔 Monitoring task {task.task_id} condition met via MCP notification! "
                        f"Result: {json.dumps(data, indent=2)}"
                    )
                    logger.info(message)
                    notifications_to_send.append((task.task_id, task, message))

        for completed_task_id, completed_task, message in notifications_to_send:
            await self._notify(completed_task_id, completed_task, message)

    def _is_monitoring_notification(self, notification_method: str) -> bool:
        """Return True for notification methods that can update monitors."""
        return notification_method.startswith("task/") or notification_method == "notifications/tasks/status"

    def _event_type_from_method(self, notification_method: str) -> str:
        """Map notification method names to a compact event type."""
        if notification_method == "notifications/tasks/status":
            return "status_changed"
        return notification_method.rsplit("/", 1)[-1]

    def _extract_notification_result(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize custom and MCP task notification payloads into condition data."""
        data = params.get("data")
        if isinstance(data, dict):
            result = dict(data)
        else:
            result = {}

        for key in (
            "task_id",
            "taskId",
            "event",
            "tool",
            "target_tool",
            "status",
            "statusMessage",
            "createdAt",
            "lastUpdatedAt",
            "ttl",
            "pollInterval",
        ):
            if key in params and key not in result:
                result[key] = params[key]

        if "status" in params and result.get("status") != params["status"]:
            result["mcp_task_status"] = params["status"]

        if "success" not in result and "error" not in result:
            result["success"] = True

        return result

    async def track_external_task(
        self,
        task_id: str,
        target_tool: str,
        condition: str = "True",
        server_url: str = "",
        timeout: float = 0.0,
    ) -> Dict[str, Any]:
        """Track a server-side task that will complete via MCP notifications."""
        if not task_id:
            return {
                "success": False,
                "error": "task_id cannot be empty"
            }

        with self.task_lock:
            if task_id in self.tasks:
                return {
                    "success": True,
                    "task_id": task_id,
                    "message": f"Already tracking server-side task {task_id}"
                }

            self.tasks[task_id] = MonitoringTask(
                task_id=task_id,
                target_tool=target_tool,
                timeout=timeout,
                condition=condition or "True",
                server_url=server_url or "",
            )

        return {
            "success": True,
            "task_id": task_id,
            "message": f"Tracking server-side task {task_id}"
        }


    async def get_task_status(self, task_id: str) -> Dict[str, Any]:
        """
        Get the status of a monitoring task

        Args:
            task_id: ID of the task

        Returns:
            Dict with task status and details
        """
        with self.task_lock:
            if task_id not in self.tasks:
                return {
                    "success": False,
                    "error": f"Task {task_id} not found"
                }

            task = self.tasks[task_id]

        status = {
            "success": True,
            "task_id": task_id,
            "target_tool": task.target_tool,
            "condition": task.condition,
            "status": self._task_status_label(task),
            "is_active": task.is_active,
            "is_complete": task.is_complete,
            "timeout": task.timeout,
            "elapsed_time": task.elapsed_time(),
            "remaining_time": task.remaining_time(),
            "last_result": task.last_result
        }

        if task.is_complete:
            status["completion_reason"] = task.completion_reason
            status["completion_result"] = task.completion_result

        return status

    async def list_tasks(self) -> Dict[str, Any]:
        """
        List all active monitoring tasks

        Returns:
            Dict with list of task summaries
        """
        with self.task_lock:
            tasks_list = []
            for task_id, task in self.tasks.items():
                tasks_list.append({
                    "task_id": task_id,
                    "target_tool": task.target_tool,
                    "condition": task.condition,
                    "status": self._task_status_label(task),
                    "is_active": task.is_active,
                    "is_complete": task.is_complete,
                    "timeout": task.timeout,
                    "elapsed_time": task.elapsed_time(),
                    "remaining_time": task.remaining_time(),
                    "last_result": task.last_result,
                    "completion_reason": task.completion_reason if task.is_complete else None,
                    "completion_result": task.completion_result if task.is_complete else None
                })

        return {
            "success": True,
            "active_tasks": len([t for t in tasks_list if t["is_active"]]),
            "total_tasks": len(tasks_list),
            "tasks": tasks_list
        }

    def _task_status_label(self, task: MonitoringTask) -> str:
        """Return a compact human-readable task state."""
        if task.is_active:
            return "active"
        if task.is_complete:
            return task.completion_reason or "complete"
        return "inactive"

    def _evaluate_condition(self, result: Dict[str, Any], condition: str) -> bool:
        """
        Evaluate a monitoring condition against a tool result

        Args:
            result: The tool result to evaluate
            condition: The condition string (e.g., "status == 'reached'")

        Returns:
            True if condition is met, False otherwise
        """
        try:
            # Create a safe evaluation environment with the result data
            eval_env = {
                'result': result,
                '__builtins__': {}
            }

            # Add flattened result fields to the environment for easier access
            # e.g., if result = {"status": "reached"}, then status="reached" is available
            if isinstance(result, dict):
                eval_env.update(result)

            # Evaluate the condition
            eval_result = bool(eval(condition, {"__builtins__": {}}, eval_env))
            return eval_result
        except Exception as e:
            logger.warning(f"Error evaluating condition '{condition}': {e}")
            return False


    async def _notify(self, task_id: str, task: MonitoringTask, message: str):
        """Send notifications for task completion (async version)

        Args:
            task_id: ID of the completed task
            task: The MonitoringTask object
            message: Message to send
        """
        for callback in self.completion_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(task_id, task, message)
                else:
                    callback(task_id, task, message)
            except Exception as e:
                # logger.error(f"Error in notification callback: {e}")
                pass

    async def cleanup(self):
        """Clean up all resources"""
        with self.task_lock:
            for task in self.tasks.values():
                task.is_active = False
                if not task.is_complete:
                    task.is_complete = True
                    task.completion_reason = "cleanup"
        # logger.info("Background task manager cleaned up")
