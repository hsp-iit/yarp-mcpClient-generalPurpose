# Server Integration Guide: Background Monitoring

## Quick Start (5 minutes)

### Step 1: Identify Monitorable Tools
Look at your server's tools and ask: *"Could the user want to wait for this to change state?"*

- Navigation tool → Yes (waiting for "reached")
- Battery tool → Yes (waiting for charge level)
- Speech tool → Maybe (waiting for speech to finish)
- Sensor reading → Maybe (waiting for threshold)

### Step 2: Update Tool Docstring

For each monitorable tool, add monitoring metadata to the docstring:

```python
@self.mcp.tool()
async def get_navigation_status() -> dict[str, Any]:
    """
    Get the current navigation status.

    Returns can include fields: status, current_x, current_y
    Where status is one of: idle, navigating, reached, failed

    This tool supports background monitoring. Example conditions:
    - "status == 'reached'" - wait until destination reached
    - "status == 'failed'" - wait until navigation fails
    - "(status == 'reached' or status == 'failed')" - wait for either

    Suggested polling interval: 1.0 second
    """
    # ... your implementation ...
```

### Step 3: Test
Run your server and test with the client:
- Client discovers your tools
- LLM sees monitoring guidance in docstring
- When user requests monitoring, it works!

## Detailed Integration

### Locate Your Server Files

```
yarp-mcpServers/src/servers/devices/
├── yarp_mcpServer_IBattery/
│   └── Yarp_mcpServer_IBattery.py
├── yarp_mcpServer_INavigation2D/
│   └── Yarp_mcpServer_INavigation2D.py
└── yarp_mcpServer_ISpeechSynthesizer/
    └── Yarp_mcpServer_ISpeechSynthesizer.py
```

### Edit Your Tools

In your `_register_tools()` method, update tool docstrings:

#### Example 1: Navigation Server

**File**: `Yarp_mcpServer_INavigation2D.py`

**Find**: `async def goto_target_by_absolute_location(...)` or similar

**Update the docstring**:
```python
@self.mcp.tool()
async def get_navigation_status() -> dict[str, Any]:
    """
    Get current navigation status including state and progress.

    Returns status field with values: idle, navigating, reached, failed, paused.

    Background Monitoring:
    This tool supports polling for navigation completion with conditions like:
    - "status == 'reached'" - destination reached
    - "status == 'failed'" - navigation failure
    - "(status == 'reached' or status == 'failed')" - completion either way

    When monitoring: Poll every 1.0 second, typical timeout 300 seconds.
    """
```

#### Example 2: Battery Server

**File**: `Yarp_mcpServer_IBattery.py`

**Find**: `async def get_battery_charge(...)`

**Update the docstring**:
```python
@self.mcp.tool()
async def get_battery_charge() -> dict[str, Any]:
    """
    Get the battery charge level (0-100%).

    Background Monitoring:
    Monitor charge level changes with conditions like:
    - "charge < 20" - battery low
    - "charge > 90" - nearly full
    - "charge == 100" - fully charged

    When monitoring: Poll every 5.0 seconds, typical timeout 3600 seconds for charging.
    """
```

#### Example 3: Speech Server

**File**: `Yarp_mcpServer_ISpeechSynthesizer.py`

**Find**: `async def synthesize_speech(...)` or `get_speech_status()`

**Update the docstring**:
```python
@self.mcp.tool()
async def get_speech_status() -> dict[str, Any]:
    """
    Get current speech synthesizer status.

    Returns status field with values: idle, synthesizing, playing, error.

    Background Monitoring:
    Monitor synthesis/playback completion with:
    - "status == 'idle'" - speech finished
    - "status == 'error'" - error occurred
    - "(status == 'idle' or status == 'error')" - stopped (either way)

    When monitoring: Poll every 0.5 seconds, typical timeout 60 seconds.
    """
```

## Complete Metadata Format

For full monitoring capability, include structured metadata:

```python
@self.mcp.tool()
async def your_tool() -> dict[str, Any]:
    """
    Tool description here.

    Returns field names: field1, field2, field3

    Background Monitoring Metadata:
    └─ x-monitoring:
       ├─ pollable: true (or false to disable)
       ├─ description: "What this tool can monitor"
       ├─ expected_fields: ["field1", "field2"]
       ├─ suggested_conditions:
       │  ├─ "field1 == 'expected_value'"
       │  ├─ "field2 > 80"
       │  └─ "(field1 == 'val1' or field1 == 'val2')"
       ├─ polling_suggestion: "1.0 seconds"
       ├─ timeout_suggestion: "60.0 seconds"
       └─ typical_use_cases:
          ├─ "Use case 1"
          ├─ "Use case 2"
          └─ "Use case 3"
    """
```

## What Each Server Should Update

### IBattery Server
- [ ] `get_battery_charge()` - monitor charge levels
- [ ] `get_battery_status()` - monitor charging/discharging state
- [ ] `get_battery_temperature()` - monitor temperature changes

### INavigation2D Server
- [ ] `get_navigation_status()` - monitor navigation completion
- [ ] `get_current_position()` - monitor position changes
- [ ] `get_localization_status()` - monitor localization state

### ISpeechSynthesizer Server
- [ ] `get_speech_status()` - monitor synthesis completion
- [ ] (Others as applicable)

## Return Value Guidelines

Make return dictionaries with clear, monitorable fields:

**Good:**
```python
return {
    "success": True,
    "status": "navigating",      # Can use: status == 'navigating'
    "charge": 85.5,               # Can use: charge > 80
    "temperature": 35.2,          # Can use: temperature < 40
    "is_charging": False           # Can use: is_charging == True
}
```

**Avoid:**
```python
return {
    "success": True,
    "data": {
        "nested": {
            "value": "something"   # Hard to monitor
        }
    }
}
```

## Common Monitoring Patterns

### State Machine Monitoring
```
States: idle → processing → done/error

Condition: "(status == 'done' or status == 'error')"
Polling: 0.5 - 1.0 seconds
Timeout: Depends on operation duration
```

### Threshold Monitoring
```
Value: charge (0-100)

Condition: "charge > 80" or "charge < 20"
Polling: 2.0 - 5.0 seconds
Timeout: Long (depends on charging/discharging)
```

### Position Monitoring
```
Values: x, y, theta, distance

Condition: "x > 5.0 and y < 3.0"
Polling: 0.5 - 1.0 seconds
Timeout: Depends on movement speed
```

## Testing Your Implementation

### Test 1: Tool Discovery
```python
# Client should discover your tool with metadata
# Check logs for: "Retrieved N tools from your_server"
```

### Test 2: Basic Monitoring
```
User: "Monitor get_navigation_status until status == 'reached'"
Expected: Task created with task_id, polling begins
```

### Test 3: Condition Evaluation
```
User: "Monitor battery until charge > 80"
Expected: Polling continues, completes when condition met
```

### Test 4: Multiple Tasks
```
User: Create 3 different monitoring tasks
Expected: All run in parallel, complete independently
```

## Verification Checklist

- [ ] Tool docstrings updated with monitoring guidance
- [ ] Expected field names documented
- [ ] Suggested conditions provided (3-5 examples)
- [ ] Polling interval suggested (appropriate for state change rate)
- [ ] Timeout suggestion provided
- [ ] Return dict has clear, comparable fields
- [ ] Tools tested with actual monitoring requests
- [ ] No changes to tool functionality required

## No Changes Needed To

✅ Tool signatures
✅ Return value structure (just documented)
✅ Server initialization
✅ MCP configuration
✅ Tool parameters

## Changes Required

⚠️ Tool docstrings (metadata added)
⚠️ Documentation (guide updated)

## Rollback Plan

If you need to remove monitoring support:
- Simply remove metadata from docstrings
- Tools continue working normally
- Client will stop suggesting monitoring for that tool

## Support

For questions about:
- **Metadata format**: See [MONITORING_METADATA.md](MONITORING_METADATA.md)
- **Client integration**: See [Yarp_mcpClient_GeneralCheckerCore.py](modules/core/Yarp_mcpClient_GeneralCheckerCore.py)
- **Examples**: See [EXAMPLE_SERVER_UPDATE.md](EXAMPLE_SERVER_UPDATE.md)

## Next Steps

1. ✅ Identify 2-3 tools in your server that support monitoring
2. ✅ Add metadata to their docstrings (copy/paste from above)
3. ✅ Run server and test with client
4. ✅ Verify LLM uses monitoring when appropriate
5. ✅ Document any specific conditions for your tools

## Important Notes

- **Backward Compatible**: Existing clients ignore metadata
- **Opt-in**: Only tools you annotate get monitoring support
- **Gradual**: Can add to one tool and test before others
- **No Breaking Changes**: Servers work with old and new clients
- **Server-Driven**: Client has no a priori knowledge, relies on metadata
