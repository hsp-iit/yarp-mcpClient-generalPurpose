# Background Monitoring Metadata for MCP Servers

## Overview

MCP servers can now advertise which of their tools support background monitoring. The client will automatically discover this metadata and make it available to the LLM, allowing for intelligent decisions about when to use background polling.

## How It Works

1. **Server declares monitoring capabilities**: via the `x-monitoring` property in tool input schemas
2. **Client discovers metadata**: during MCP server discovery
3. **LLM makes decisions**: using this information to call `start_monitoring()` when appropriate
4. **Client runs background task**: polls the tool until condition is met

## Metadata Format

Add an `x-monitoring` property to your tool's `inputSchema`:

```python
"x-monitoring": {
    "pollable": true,
    "description": "This tool can be monitored for state changes",
    "typical_use_cases": [
        "Wait for navigation to complete",
        "Monitor battery level",
        "Wait for charging to finish"
    ],
    "expected_fields": ["status", "charge", "state"],
    "suggested_conditions": [
        "status == 'reached'",
        "charge > 80",
        "state == 'complete'"
    ],
    "polling_suggestion": "1.0 - 2.0 seconds",
    "timeout_suggestion": "60.0 - 300.0 seconds"
}
```

### Required Fields

- **pollable** (bool): Set to `True` if the tool can be monitored
- **description** (str): Brief description of what can be monitored

### Optional Fields

- **typical_use_cases** (list[str]): Examples of when to use monitoring
- **expected_fields** (list[str]): Names of fields in the result that can be monitored
- **suggested_conditions** (list[str]): Example conditions for `start_monitoring()`
- **polling_suggestion** (str): Recommended poll interval in seconds
- **timeout_suggestion** (str): Recommended timeout in seconds

## Example: Navigation Server

```python
@self.mcp.tool()
async def get_navigation_status() -> dict[str, Any]:
    """Get the current navigation status including current operation and completion state.

    Returns:
        Dict with 'status' field that can be one of: 'idle', 'navigating', 'reached', 'failed'
    """
    # ... implementation ...
```

### With Monitoring Metadata

```python
# In your MCP tool definition, when using FastMCP:
# The inputSchema will be generated automatically, but you can add custom metadata

# For FastMCP, you might need to extend the schema after tool registration:
# Or document it in the tool description and let the client parse from there

# Alternative: Return metadata through a separate mechanism or in the tool definition
```

## For FastMCP Users

In your `_register_tools()` method, you can add metadata to tool schemas:

```python
@self.mcp.tool()
async def get_navigation_status() -> dict[str, Any]:
    """
    Get the current navigation status.

    Monitoring metadata:
    - x-monitoring: {"pollable": true, "expected_fields": ["status"], "suggested_conditions": ["status == 'reached' or status == 'failed'"]}
    """
    # ...implementation...
```

Or, if you need more control, you could store this in a separate metadata dictionary that the client queries.

## How the Client Uses This

1. **Discovery Phase**: Client extracts `x-monitoring` from tool schemas
2. **System Prompt**: Information about monitorable tools is included in the LLM's system prompt
3. **LLM Decision**: The model can decide to call `start_monitoring()` for long-running tasks
4. **Execution**: Background polling happens asynchronously, with notifications when complete

## Example Usage (From Client Perspective)

When the user asks: *"Navigate to the kitchen and let me know when you get there"*

The LLM might:
1. Call `goto_target_by_absolute_location(x=5.0, y=3.0, theta=0.0)`
2. Call `start_monitoring("get_navigation_status", "status == 'reached' or status == 'failed'", timeout=300.0)`
3. Return a message like: "Starting navigation to the kitchen, I'll monitor progress and notify you when complete"

The client then:
- Polls `get_navigation_status()` every 1-2 seconds in the background
- Continues accepting new user input
- Notifies the user when status changes to 'reached' or 'failed'

## Best Practices

### 1. Keep Tools Lightweight
Monitoring tools should be fast and not block other operations.

### 2. Use Consistent Field Names
Use clear, predictable field names in results (e.g., `status`, `charge`, `temperature`).

### 3. Provide Clear Conditions
Document which field values indicate "done" states:
- Navigation: `status == 'reached'` or `status == 'failed'`
- Battery: `charge > 80` or `charge < 20`
- Charging: `is_charging == False`

### 4. Include Terminal States
Tip the LLM off to terminal states in descriptions:
- "Returns 'reached', 'failed', or 'navigating'"
- "Charge ranges from 0-100"

### 5. Suggested Polling Intervals
- Fast state changes (navigation commands): 0.5-1.0 seconds
- Medium state changes (temperature, battery): 2-5 seconds
- Slow state changes (long charging): 5-10 seconds

## What Happens Without Metadata

If a server doesn't provide `x-monitoring` metadata:
- That tool can still be called normally
- The LLM won't know it supports monitoring
- Users could still ask for monitoring, but the LLM might not automatically use it
- The feature degrades gracefully

## Adding Monitoring to Existing Servers

For existing MCP servers, you can add monitoring metadata without breaking changes:

1. **Minimal addition**: Just add the description to the docstring
2. **Full support**: Add `x-monitoring` to the tool's input schema
3. **Gradual rollout**: Test with one tool first

## Querying Monitoring Metadata in the Client

```python
# Client code can access monitoring info like this:
if tool_name in client.monitoring_metadata:
    metadata = client.monitoring_metadata[tool_name]
    print(f"Tool {tool_name} supports monitoring:")
    print(f"  Typical use cases: {metadata.get('typical_use_cases', [])}")
    print(f"  Example conditions: {metadata.get('suggested_conditions', [])}")
```

## Condition Syntax

Conditions use Python syntax evaluated against the tool result:

```
# Field comparison
status == 'reached'
charge > 80
temperature < 30

# Logical operators
(status == 'reached' or status == 'failed') and charge > 20
state == 'complete' and not error

# Range checks
10 < x < 20 and 5 < y < 15
```

The result dictionary or its fields are available in the condition namespace.

## Example Implementations

### Battery Monitoring
```python
"x-monitoring": {
    "pollable": true,
    "description": "Monitor battery charge level changes",
    "expected_fields": ["charge", "status"],
    "suggested_conditions": [
        "charge < 20",  # Low battery warning
        "charge > 90",  # Fully charged
        "status == 'charging'"  # Is charging
    ],
    "polling_suggestion": "5.0 seconds"
}
```

### Navigation Monitoring
```python
"x-monitoring": {
    "pollable": true,
    "description": "Monitor navigation completion",
    "expected_fields": ["status", "current_wp", "total_wp"],
    "suggested_conditions": [
        "status == 'reached'",
        "status == 'failed'",
        "(status == 'reached' or status == 'failed') and charge > 20"
    ],
    "polling_suggestion": "1.0 second",
    "timeout_suggestion": "300.0 seconds"
}
```

### Position Monitoring
```python
"x-monitoring": {
    "pollable": true,
    "description": "Monitor robot position for target coordinates",
    "expected_fields": ["x", "y", "theta"],
    "suggested_conditions": [
        "x > 5.0 and y < 3.0",  # Specific area
        "abs(x - 5.0) < 0.5",  # Near X coordinate
        "x > previous_x"  # Moving forward
    ],
    "polling_suggestion": "0.5 seconds"
}
```
