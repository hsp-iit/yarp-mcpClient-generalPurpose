import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from mcp.client.subscriptions import ListenNotSupportedError

from src.core.background_task_manager import BackgroundTaskManager, TrackedOperation
from src.core.Yarp_mcpClient_BaseCore import Yarp_mcpClient_BaseCore
from src.core.Yarp_mcpClient_GeneralCheckerCore import Yarp_mcpClient_GeneralCheckerCore


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_snapshots_are_ordered_and_completion_is_delivered_once() -> None:
    manager = BackgroundTaskManager(enableExplicitLogging=False)
    operation = TrackedOperation(
        operation_id="op-1",
        operation_type="navigation",
        status_uri="yarp-operation://navigation/op-1",
        server_name="navigation",
        server_url="http://localhost:4001/mcp",
    )
    manager.operations[operation.operation_id] = operation
    completions = []

    async def completed(operation_id, tracked, message):
        completions.append((operation_id, tracked.status, message))

    manager.register_completion_callback(completed)
    await manager.apply_snapshot("op-1", {"revision": 2, "status": "working"})
    await manager.apply_snapshot("op-1", {"revision": 1, "status": "failed"})
    await manager.apply_snapshot("op-1", {
        "revision": 3, "status": "completed", "result": {"ok": True},
    })
    await manager.apply_snapshot("op-1", {"revision": 4, "status": "completed"})

    assert operation.revision == 4
    assert operation.status == "completed"
    assert len(completions) == 1
    assert completions[0][0:2] == ("op-1", "completed")


@pytest.mark.anyio
async def test_query_and_cleanup() -> None:
    manager = BackgroundTaskManager(enableExplicitLogging=False)
    operation = TrackedOperation(
        operation_id="op-2",
        operation_type="battery_charge",
        status_uri="yarp-operation://battery/op-2",
        server_name="battery",
        server_url="http://localhost:4002/mcp",
    )
    manager.operations[operation.operation_id] = operation
    watcher = asyncio.create_task(asyncio.Event().wait())
    manager._watchers[operation.operation_id] = watcher

    status = await manager.get_operation("op-2")
    listing = await manager.list_operations()
    assert status["status_uri"] == operation.status_uri
    assert listing["active_operations"] == 1
    assert listing["total_operations"] == 1

    await manager.cleanup()
    assert watcher.cancelled()


@pytest.mark.anyio
async def test_unsupported_subscription_falls_back_to_polling() -> None:
    snapshots = [
        {"revision": 1, "status": "working"},
        {"revision": 2, "status": "completed", "result": {"ok": True}},
    ]

    class PollOnlyClient:
        async def read_resource(self, _uri):
            snapshot = snapshots.pop(0) if len(snapshots) > 1 else snapshots[0]
            return SimpleNamespace(contents=[SimpleNamespace(text=json.dumps(snapshot))])

        @asynccontextmanager
        async def listen(self, **_kwargs):
            raise ListenNotSupportedError("2025-11-25")
            yield  # pragma: no cover

    manager = BackgroundTaskManager(enableExplicitLogging=False)
    completed = asyncio.Event()

    async def on_complete(*_args):
        completed.set()

    manager.register_completion_callback(on_complete)
    await manager.track_operation(
        operation_id="op-poll",
        operation_type="test",
        status_uri="yarp-operation://test/op-poll",
        server_name="test",
        server_url="http://localhost/mcp",
        client=PollOnlyClient(),
        poll_interval_ms=100,
    )

    await asyncio.wait_for(completed.wait(), timeout=1)
    assert (await manager.get_operation("op-poll"))["status"] == "completed"
    await manager.cleanup()


@pytest.mark.anyio
async def test_tool_result_flattens_sdk_union_wrapper() -> None:
    class ToolClient:
        async def call_tool(self, _name, _arguments):
            return SimpleNamespace(
                is_error=False,
                content=[SimpleNamespace(type="text", text='{"success": true}')],
                structured_content={
                    "result": {
                        "success": True,
                        "operation_id": "op-structured",
                        "status_uri": "yarp-operation://test/op-structured",
                    }
                },
            )

    class ClientManager:
        def get(self, _url):
            return ToolClient()

    core = Yarp_mcpClient_BaseCore(
        input_mode=SimpleNamespace(), llm_backend=SimpleNamespace(),
        enableExplicitLogging=False,
    )
    core.mcp_clients = ClientManager()
    result = await core.call_mcp_tool("start", {}, "http://localhost/mcp")

    assert result["success"] is True
    assert result["operation_id"] == "op-structured"
    assert "result" not in result


@pytest.mark.anyio
async def test_completion_resumes_serialized_llm_workflow() -> None:
    class InputMode:
        def __init__(self):
            self.notifications = []
            self.responses = []

        async def send_notification(self, value):
            self.notifications.append(value)

        async def send_response(self, value):
            self.responses.append(value)

    input_mode = InputMode()
    core = Yarp_mcpClient_GeneralCheckerCore(
        input_mode=input_mode,
        llm_backend=SimpleNamespace(),
        enableExplicitLogging=False,
    )
    continuation_requests = []

    async def process(request):
        continuation_requests.append(request)
        return "Deferred action executed"

    core.process_user_message = process
    operation = TrackedOperation(
        operation_id="op-complete",
        operation_type="battery_charge_monitor",
        status_uri="yarp-operation://battery/op-complete",
        server_name="battery",
        server_url="http://localhost:4001/mcp",
        status="completed",
    )
    worker = asyncio.create_task(core._deliver_operation_events())

    await core._on_operation_completion("op-complete", operation, '{"status":"completed"}')
    await asyncio.wait_for(core._operation_events.join(), timeout=1)
    await core._operation_events.put(None)
    await worker

    assert input_mode.notifications
    assert input_mode.responses == ["Deferred action executed"]
    assert "perform any action" in continuation_requests[0]
