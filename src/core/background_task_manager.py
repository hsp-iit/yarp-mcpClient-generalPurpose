"""Client-side tracking for MCP v2 operation resources."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from mcp import Client
from mcp.client.subscriptions import (
    ListenNotSupportedError,
    ResourceUpdated,
    SubscriptionLost,
)

from ..utils.fancyLogging import FancyLogger

logger = logging.getLogger(__name__)


@dataclass
class TrackedOperation:
    operation_id: str
    operation_type: str
    status_uri: str
    server_name: str
    server_url: str
    poll_interval_ms: int = 1000
    status: str = "working"
    revision: int = -1
    snapshot: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None

    @property
    def is_complete(self) -> bool:
        return self.status in {"completed", "failed", "cancelled"}


class BackgroundTaskManager:
    """Track exact operation resources through subscription hints plus polling."""

    def __init__(self, enableExplicitLogging: bool = True):
        self.operations: dict[str, TrackedOperation] = {}
        self._watchers: dict[str, asyncio.Task[Any]] = {}
        self._lock = asyncio.Lock()
        self.completion_callbacks: list[Callable[..., Any]] = []
        self.fancyLog = FancyLogger(
            self.__class__.__name__, logger=logger,
            enableExplicitLogging=enableExplicitLogging,
        )

    def register_completion_callback(self, callback: Callable[..., Any]) -> None:
        self.completion_callbacks.append(callback)

    async def track_operation(
        self, *, operation_id: str, operation_type: str, status_uri: str,
        server_name: str, server_url: str, client: Client,
        poll_interval_ms: int = 1000,
    ) -> dict[str, Any]:
        if not operation_id or not status_uri:
            return {"success": False, "error": "operation_id and status_uri are required"}

        async with self._lock:
            if operation_id in self.operations:
                return {"success": True, "operation_id": operation_id, "message": "Already tracked"}
            operation = TrackedOperation(
                operation_id=operation_id,
                operation_type=operation_type or "unknown",
                status_uri=status_uri,
                server_name=server_name,
                server_url=server_url,
                poll_interval_ms=max(100, poll_interval_ms),
            )
            self.operations[operation_id] = operation
            self._watchers[operation_id] = asyncio.create_task(
                self._watch_operation(operation, client),
                name=f"watch-yarp-operation-{operation_id}",
            )
        return {"success": True, "operation_id": operation_id, "status_uri": status_uri}

    async def _watch_operation(self, operation: TrackedOperation, client: Client) -> None:
        backoff = 0.5
        while not operation.is_complete:
            next_event: asyncio.Task[Any] | None = None
            try:
                # Refetch before subscribing. This both closes the gap after the
                # tool result and guarantees progress when re-listen attempts fail.
                await self._refresh(operation, client)
                if operation.is_complete:
                    return
                async with client.listen(resource_subscriptions=[operation.status_uri]) as subscription:
                    backoff = 0.5
                    while not operation.is_complete:
                        if next_event is None:
                            next_event = asyncio.create_task(anext(subscription))
                        done, _ = await asyncio.wait(
                            {next_event}, timeout=operation.poll_interval_ms / 1000.0
                        )
                        if done:
                            event = next_event.result()
                            next_event = None
                            if isinstance(event, ResourceUpdated) and str(event.uri) == operation.status_uri:
                                await self._refresh(operation, client)
                        else:
                            await self._refresh(operation, client)
            except asyncio.CancelledError:
                raise
            except ListenNotSupportedError:
                self.fancyLog.WARNING(
                    f"Subscriptions are unavailable for {operation.operation_id}; using polling"
                )
                await self._poll_operation(operation, client)
                return
            except (StopAsyncIteration, SubscriptionLost):
                self.fancyLog.WARNING(
                    f"Operation subscription ended for {operation.operation_id}; reconnecting"
                )
            except Exception as exc:
                self.fancyLog.WARNING(f"Operation watcher error for {operation.operation_id}: {exc}")
            finally:
                if next_event is not None and not next_event.done():
                    next_event.cancel()
                    await asyncio.gather(next_event, return_exceptions=True)

            if not operation.is_complete:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 10.0)

    async def _poll_operation(self, operation: TrackedOperation, client: Client) -> None:
        """Portable fallback for peers that cannot open subscriptions/listen."""
        while not operation.is_complete:
            await asyncio.sleep(operation.poll_interval_ms / 1000.0)
            try:
                await self._refresh(operation, client)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.fancyLog.WARNING(
                    f"Operation poll failed for {operation.operation_id}: {exc}"
                )

    async def _refresh(self, operation: TrackedOperation, client: Client) -> None:
        response = await client.read_resource(operation.status_uri)
        if not response.contents:
            raise RuntimeError(f"Empty operation resource: {operation.status_uri}")
        text = getattr(response.contents[0], "text", None)
        if text is None:
            raise RuntimeError(f"Operation resource is not JSON text: {operation.status_uri}")
        await self.apply_snapshot(operation.operation_id, json.loads(text))

    async def apply_snapshot(self, operation_id: str, snapshot: dict[str, Any]) -> None:
        callback_payload: tuple[TrackedOperation, str] | None = None
        async with self._lock:
            operation = self.operations.get(operation_id)
            if operation is None:
                return
            revision = int(snapshot.get("revision", 0))
            if revision <= operation.revision:
                return
            was_complete = operation.is_complete
            operation.revision = revision
            operation.status = str(snapshot.get("status", operation.status))
            operation.snapshot = snapshot
            if operation.is_complete and not was_complete:
                operation.completed_at = datetime.now(timezone.utc)
                callback_payload = (
                    operation,
                    f"Operation {operation.operation_id} finished with status {operation.status}: "
                    f"{json.dumps(snapshot, indent=2)}",
                )
        if callback_payload is not None:
            await self._notify(*callback_payload)
        self.fancyLog.INFO(
            f"Operation {operation_id} advanced to revision {revision} "
            f"with status {operation.status}"
        )

    async def get_operation(self, operation_id: str) -> dict[str, Any]:
        async with self._lock:
            operation = self.operations.get(operation_id)
            if operation is None:
                return {"success": False, "error": f"Operation {operation_id} not found"}
            return self._serialize(operation)

    async def list_operations(self) -> dict[str, Any]:
        async with self._lock:
            operations = [self._serialize(item) for item in self.operations.values()]
        return {
            "success": True,
            "active_operations": sum(not item["is_complete"] for item in operations),
            "total_operations": len(operations),
            "operations": operations,
        }

    def _serialize(self, operation: TrackedOperation) -> dict[str, Any]:
        return {
            "success": True,
            "operation_id": operation.operation_id,
            "operation_type": operation.operation_type,
            "status_uri": operation.status_uri,
            "server_name": operation.server_name,
            "status": operation.status,
            "revision": operation.revision,
            "is_complete": operation.is_complete,
            "snapshot": operation.snapshot,
        }

    async def _notify(self, operation: TrackedOperation, message: str) -> None:
        for callback in self.completion_callbacks:
            try:
                result = callback(operation.operation_id, operation, message)
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:
                self.fancyLog.ERROR(f"Error in operation completion callback: {exc}")

    async def cleanup(self) -> None:
        async with self._lock:
            watchers = list(self._watchers.values())
            self._watchers.clear()
        for watcher in watchers:
            watcher.cancel()
        if watchers:
            await asyncio.gather(*watchers, return_exceptions=True)
