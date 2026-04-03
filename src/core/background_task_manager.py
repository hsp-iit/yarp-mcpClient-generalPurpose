import asyncio
import json
import logging
from typing import Dict, Any, Optional, Callable, List
from datetime import datetime
from threading import Thread, Lock
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class MonitoringTask:
    """Represents a single background monitoring task"""
    task_id: str
    target_tool: str
    poll_interval: float
    timeout: float
    condition: str  # e.g., "status == 'reached'" or "charge < 20"
    server_url: str
    created_at: datetime = field(default_factory=datetime.now)
    last_poll: Optional[datetime] = None
    last_result: Optional[Dict[str, Any]] = None
    is_active: bool = True
    is_complete: bool = False
    completion_reason: str = ""  # "condition_met", "timeout", "cancelled"
    completion_result: Optional[Dict[str, Any]] = None

    def elapsed_time(self) -> float:
        """Get elapsed time in seconds since task creation"""
        return (datetime.now() - self.created_at).total_seconds()

    def remaining_time(self) -> float:
        """Get remaining time before timeout"""
        return max(0, self.timeout - self.elapsed_time())


class BackgroundTaskManager:
    """Manages background monitoring tasks for tool polling"""

    def __init__(self, tool_caller: Callable, main_loop=None):
        """
        Initialize the task manager

        Args:
            tool_caller: Async callable that takes (tool_name, args, server_url) and returns dict
            main_loop: The main asyncio event loop (for scheduling async callbacks)
        """
        self.tool_caller = tool_caller
        self.tasks: Dict[str, MonitoringTask] = {}
        self.task_lock = Lock()
        self.notification_callbacks: List[Callable] = []
        self.polling_thread: Optional[Thread] = None
        self.is_running = False
        self.task_counter = 0
        self.main_loop = main_loop

    def register_notification_callback(self, callback: Callable):
        """Register a callback for task completion notifications

        Args:
            callback: Async callable that takes (task_id, task, notification_message)
        """
        self.notification_callbacks.append(callback)

    async def start_monitoring(
        self,
        target_tool: str,
        condition: str,
        poll_interval: float = 1.0,
        timeout: float = 60.0,
        server_url: str = None
    ) -> Dict[str, Any]:
        """
        Start a background monitoring task

        Args:
            target_tool: Name of the tool to monitor (must be callable)
            condition: Condition to wait for (e.g., "status == 'reached'" or "charge > 80")
            poll_interval: Seconds between polls (default: 1.0)
            timeout: Maximum seconds to wait (default: 60.0)
            server_url: URL of the MCP server hosting the tool

        Returns:
            Dict with task_id and status
        """
        if not target_tool:
            return {
                "success": False,
                "error": "target_tool cannot be empty"
            }

        if not condition:
            return {
                "success": False,
                "error": "condition cannot be empty"
            }

        if poll_interval <= 0:
            return {
                "success": False,
                "error": "poll_interval must be positive"
            }

        if timeout <= 0:
            return {
                "success": False,
                "error": "timeout must be positive"
            }

        # Generate unique task ID
        self.task_counter += 1
        task_id = f"monitor_{self.task_counter}"

        # Create monitoring task
        task = MonitoringTask(
            task_id=task_id,
            target_tool=target_tool,
            poll_interval=poll_interval,
            timeout=timeout,
            condition=condition,
            server_url=server_url or ""
        )

        with self.task_lock:
            self.tasks[task_id] = task

        # logger.info(f"Started monitoring task {task_id}: {target_tool} with condition '{condition}'")

        # Start polling if not already running
        if not self.is_running:
            self.is_running = True
            # Start polling in background thread
            self.polling_thread = Thread(target=self._polling_loop_threaded, daemon=True)
            self.polling_thread.start()

        return {
            "success": True,
            "task_id": task_id,
            "message": f"Started monitoring {target_tool} with condition: {condition}"
        }

    async def stop_monitoring(self, task_id: str) -> Dict[str, Any]:
        """
        Stop a monitoring task

        Args:
            task_id: ID of the task to stop

        Returns:
            Dict with status
        """
        with self.task_lock:
            if task_id not in self.tasks:
                return {
                    "success": False,
                    "error": f"Task {task_id} not found"
                }

            task = self.tasks[task_id]
            task.is_active = False
            task.is_complete = True
            task.completion_reason = "cancelled"

        # logger.info(f"Stopped monitoring task {task_id}")

        return {
            "success": True,
            "task_id": task_id,
            "message": f"Monitoring task {task_id} cancelled"
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
            "is_active": task.is_active,
            "is_complete": task.is_complete,
            "elapsed_time": task.elapsed_time(),
            "remaining_time": task.remaining_time(),
            "last_poll": task.last_poll.isoformat() if task.last_poll else None,
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
                    "is_active": task.is_active,
                    "is_complete": task.is_complete,
                    "elapsed_time": task.elapsed_time(),
                    "remaining_time": task.remaining_time()
                })

        return {
            "success": True,
            "active_tasks": len([t for t in tasks_list if t["is_active"]]),
            "total_tasks": len(tasks_list),
            "tasks": tasks_list
        }

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
            eval_result = bool(eval(condition, eval_env))
            return eval_result
        except Exception as e:
            logger.warning(f"Error evaluating condition '{condition}': {e}")
            return False

    def _polling_loop_threaded(self):
        """Main polling loop - runs in a separate thread with its own event loop"""
        import time
        # logger.debug("Started background monitoring polling loop in thread")

        while self.is_running:
            tasks_to_check = []

            # Collect active tasks
            with self.task_lock:
                tasks_to_check = [
                    task for task in self.tasks.values()
                    if task.is_active and not task.is_complete
                ]

            # If no active tasks, stop the loop
            if not tasks_to_check:
                self.is_running = False
                # logger.debug("No active tasks, stopping polling loop")
                break

            # Poll each active task
            for task in tasks_to_check:
                try:
                    # Check if enough time has passed since last poll
                    if task.last_poll and (datetime.now() - task.last_poll).total_seconds() < task.poll_interval:
                        continue

                    # Check timeout
                    if task.elapsed_time() > task.timeout:
                        with self.task_lock:
                            task.is_active = False
                            task.is_complete = True
                            task.completion_reason = "timeout"

                        message = f"⏱️ Monitoring task {task.task_id} timed out after {task.timeout}s waiting for '{task.condition}' on {task.target_tool}"
                        # logger.info(message)
                        self._notify_sync(task.task_id, task, message)
                        continue

                    # Call the tool (create a new event loop for this thread)
                    try:
                        result = asyncio.run(self.tool_caller(task.target_tool, {}, task.server_url))
                        task.last_poll = datetime.now()
                        task.last_result = result
                    except Exception as e:
                        # logger.warning(f"Error polling {task.target_tool} for task {task.task_id}: {e}")
                        continue

                    # Evaluate condition
                    if self._evaluate_condition(result, task.condition):
                        with self.task_lock:
                            task.is_active = False
                            task.is_complete = True
                            task.completion_reason = "condition_met"
                            task.completion_result = result

                        message = f"✅ Monitoring task {task.task_id} completed! Condition '{task.condition}' was met on {task.target_tool}. Result: {json.dumps(result, indent=2)}"
                        # logger.info(message)
                        self._notify_sync(task.task_id, task, message)

                except Exception as e:
                    # logger.error(f"Error in polling loop for task {task.task_id}: {e}")
                    continue

            # Sleep before next polling cycle
            time.sleep(0.1)  # Small sleep to prevent busy-waiting

    async def _polling_loop(self):
        """Main polling loop - runs in the event loop, not a separate thread"""
        # logger.debug("Started background monitoring polling loop")

        while self.is_running:
            tasks_to_check = []

            # Collect active tasks
            with self.task_lock:
                tasks_to_check = [
                    task for task in self.tasks.values()
                    if task.is_active and not task.is_complete
                ]

            # If no active tasks, stop the loop
            if not tasks_to_check:
                self.is_running = False
                # logger.debug("No active tasks, stopping polling loop")
                break

            # Poll each active task
            for task in tasks_to_check:
                try:
                    # Check if enough time has passed since last poll
                    if task.last_poll and (datetime.now() - task.last_poll).total_seconds() < task.poll_interval:
                        continue

                    # Check timeout
                    if task.elapsed_time() > task.timeout:
                        with self.task_lock:
                            task.is_active = False
                            task.is_complete = True
                            task.completion_reason = "timeout"

                        message = f"⏱️ Monitoring task {task.task_id} timed out after {task.timeout}s waiting for '{task.condition}' on {task.target_tool}"
                        # logger.info(message)
                        await self._notify(task.task_id, task, message)
                        continue

                    # Call the tool
                    try:
                        result = await self.tool_caller(task.target_tool, {}, task.server_url)
                        task.last_poll = datetime.now()
                        task.last_result = result
                    except Exception as e:
                        # logger.warning(f"Error polling {task.target_tool} for task {task.task_id}: {e}")
                        continue

                    # Evaluate condition
                    if self._evaluate_condition(result, task.condition):
                        with self.task_lock:
                            task.is_active = False
                            task.is_complete = True
                            task.completion_reason = "condition_met"
                            task.completion_result = result

                        message = f"✅ Monitoring task {task.task_id} completed! Condition '{task.condition}' was met on {task.target_tool}. Result: {json.dumps(result, indent=2)}"
                        # logger.info(message)
                        await self._notify(task.task_id, task, message)

                except Exception as e:
                    # logger.error(f"Error in polling loop for task {task.task_id}: {e}")
                    continue

            # Sleep before next polling cycle
            await asyncio.sleep(0.1)  # Small sleep to prevent busy-waiting

    async def _notify(self, task_id: str, task: MonitoringTask, message: str):
        """Send notifications for task completion (async version)

        Args:
            task_id: ID of the completed task
            task: The MonitoringTask object
            message: Message to send
        """
        for callback in self.notification_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(task_id, task, message)
                else:
                    callback(task_id, task, message)
            except Exception as e:
                # logger.error(f"Error in notification callback: {e}")
                pass

    def _notify_sync(self, task_id: str, task: MonitoringTask, message: str):
        """Send notifications for task completion (thread-safe sync version)

        Args:
            task_id: ID of the completed task
            task: The MonitoringTask object
            message: Message to send
        """
        for callback in self.notification_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    # For async callbacks from a thread, schedule them on the main event loop
                    if self.main_loop and self.main_loop.is_running():
                        asyncio.run_coroutine_threadsafe(callback(task_id, task, message), self.main_loop)
                    else:
                        # Fallback if main loop is not available
                        asyncio.run(callback(task_id, task, message))
                else:
                    callback(task_id, task, message)
            except Exception as e:
                # logger.error(f"Error in notification callback: {e}")
                pass

    async def cleanup(self):
        """Clean up all resources"""
        self.is_running = False
        with self.task_lock:
            for task in self.tasks.values():
                task.is_active = False
        # logger.info("Background task manager cleaned up")
