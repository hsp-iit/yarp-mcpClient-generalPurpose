# Background Monitoring Quick Reference

## For Users

### Starting a Monitoring Task
```
User: "Navigate to the kitchen and notify me when you arrive"

Behind the scenes:
- LLM calls goto_target()
- LLM calls start_monitoring("get_navigation_status", "status == 'reached'")
- You get notified when complete
```

### Conditions You Can Use
Any Python comparison expression:
- `status == 'reached'` - Exact match
- `charge > 80` - Numeric comparison
- `charge < 20 or status == 'error'` - Logical OR
- `x > 5.0 and y < 3.0` - Multiple conditions
- `status in ['reached', 'paused']` - Multiple values

### How It Works
1. Start monitoring in response to task
2. LLM decides when to use it based on task type
3. Background polling runs continuously
4. You're notified when condition is met
5. Main conversation continues normally

### Examples
- "Wait until the robot reaches the table"
- "Monitor battery and stop when it hits 20%"
- "Tell me when temperature exceeds 40 degrees"
- "Navigate while monitoring battery"

## For Server Developers

### Enabling Monitoring (Minimal)
Add this to your tool docstring:

```python
@self.mcp.tool()
async def get_navigation_status() -> dict[str, Any]:
    """
    Get navigation status.

    Monitoring: Can monitor with conditions like "status == 'reached'"
    Returns fields: status, current_x, current_y
    """
    # ... your implementation ...
```

### Enabling Monitoring (Full)
Add structured metadata:

```python
@self.mcp.tool()
async def get_navigation_status() -> dict[str, Any]:
    """
    Get navigation status.

    Can be monitored for completion with conditions like:
    - "status == 'reached'"
    - "status == 'failed'"
    - "(status == 'reached' or status == 'failed')"

    x-monitoring metadata:
    {
        "pollable": true,
        "expected_fields": ["status", "x", "y"],
        "suggested_conditions": ["status == 'reached'"],
        "polling_suggestion": "1.0 second"
    }
    """
```

### Return Value Format
Make sure your tool returns predictable field names that can be used in conditions:

```python
return {
    "status": "navigating",  # Can use in: status == 'navigating'
    "charge": 85.0,          # Can use in: charge > 80
    "x": 5.5,                # Can use in: x > 5.0
    "y": 3.2,                # Can use in: y < 4.0
}
```

### Suggested Polling Intervals
- Fast state changes (navigation): **0.5 - 1.0 seconds**
- Medium changes (temperature, battery): **2 - 5 seconds**
- Slow changes (charging): **5 - 10 seconds**

### Terminal States Guide
Document which states indicate "done":
- **Navigation**: `reached`, `failed` (versus `navigating`, `idle`)
- **Battery**: `charge > 90` (full), `charge < 10` (critical)
- **Lift**: `position == 'up'`, `position == 'down'`

## For Client Developers

### Core Classes

`background_task_manager.py::BackgroundTaskManager`
- Manages all monitoring tasks
- Runs async polling loop
- Handles notifications

`background_task_manager.py::MonitoringTask`
- Individual task state
- Condition evaluation
- Timeout tracking

### Integration Points

```python
# Initialize in your client
self.task_manager = BackgroundTaskManager(self.call_mcp_tool)
self.task_manager.register_notification_callback(self._on_task_completion)

# Handle LLM requesting monitoring
if fn_name == "start_monitoring":
    result = await self.task_manager.start_monitoring(
        target_tool=args["target_tool"],
        condition=args["condition"],
        poll_interval=args.get("poll_interval", 1.0),
        timeout=args.get("timeout", 60.0),
        server_url=server_url
    )

# Cleanup on exit
await self.task_manager.cleanup()
```

### Notification Callback

```python
async def _on_task_completion(self, task_id: str, task, message: str):
    """Called when monitoring task completes"""
    # Add to conversation
    self.conversation_history.append({
        "role": "system",
        "content": f"[MONITORING COMPLETE] {message}"
    })
    # Notify user
    await self.input_mode.send_notification(message)
```

### Condition Safety
The system uses `eval()` with a restricted environment:
- Only builtins disabled
- Result dict and fields available in namespace
- Errors caught and logged

### Discovery

```python
# Extract monitoring metadata during server discovery
if "x-monitoring" in input_schema:
    monitoring_data = input_schema["x-monitoring"]
    self.monitoring_metadata[tool.name] = monitoring_data
```

## Files

```
modules/core/
├── Yarp_mcpClient_GeneralCheckerCore.py  (updated)
├── background_task_manager.py             (new)
└── __init__.py

Documentation/
├── MONITORING_METADATA.md     (full server guide)
└── EXAMPLE_SERVER_UPDATE.md   (implementation example)
```

## Checklist: Adding Monitoring to a Tool

- [ ] Identify which tool results can be monitored
- [ ] Document expected fields in the result
- [ ] Suggest common conditions for monitoring
- [ ] Add metadata to tool docstring or schema
- [ ] Test with `start_monitoring()` from client
- [ ] Verify conditions are evaluated correctly
- [ ] Document in server's README

## Common Conditions by Tool Type

### Navigation
```
"status == 'reached'"
"status == 'failed'"
"(status == 'reached' or status == 'failed')"
```

### Battery
```
"charge < 20"
"charge > 90"
"charge == 100"
"status == 'charging'"
```

### Positioning
```
"x > 5.0 and y < 3.0"
"abs(x - target_x) < 0.5"
"distance < 0.1"
```

### Temperature
```
"temperature > 40"
"temperature < -5"
"temperature_change > 2"
```

## Troubleshooting

### Condition Not Met
- Check field names match result dict
- Test condition syntax: `x > 5` vs `x > "5"`
- Check data types (float vs string)

### Task Doesn't Complete
- Verify timeout is long enough
- Check polling interval isn't too long
- Verify tool returns expected fields

### No Notifications
- Check notification callback is registered
- Verify input_mode supports notifications
- Check logs for callback errors

## Performance Notes

- Polling happens in asyncio event loop (non-blocking)
- Each task uses minimal memory
- Can run many tasks concurrently
- Cleanup happens automatically on shutdown

