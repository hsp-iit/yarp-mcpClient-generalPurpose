# Example: Adding Monitoring Metadata to Navigation Server

This document shows how to update the `Yarp_mcpServer_INavigation2D` server to advertise monitoring capabilities.

## Changes Needed

### 1. Update `get_navigation_status()` Tool

In the `_register_tools()` method, modify the `get_navigation_status` tool definition:

```python
@self.mcp.tool()
async def get_navigation_status() -> dict[str, Any]:
    """
    Get the current navigation status and progress including current state, waypoint info, and completion indicators.

    States: navigating, reached, failed, idle.
    This tool can be monitored to wait for navigation completion using conditions like:
    - "status == 'reached'" to wait until destination is reached
    - "status == 'failed'" to detect navigation failure
    - "(status == 'reached' or status == 'failed')" to wait for completion either way.

    Background monitoring metadata:
    {
        "x-monitoring": {
            "pollable": true,
            "description": "Monitor navigation status for completion or failure",
            "expected_fields": ["status", "current_waypoint", "waypoints_count"],
            "suggested_conditions": [
                "status == 'reached'",
                "status == 'failed'",
                "(status == 'reached' or status == 'failed')"
            ],
            "polling_suggestion": "1.0 second",
            "timeout_suggestion": "300.0 seconds",
            "typical_use_cases": [
                "Wait for robot to reach destination",
                "Monitor multi-waypoint navigation",
                "Detect navigation failures"
            ]
        }
    }
    """
    if not self.is_initialized:
        return {
            "success": False,
            "error": "Navigation system not initialized. Call initialize_yarp_navigation first."
        }

    try:
        status = self.navigation_interface.getNavigationStatus()

        # Get current position and target to include in response
        current_pos = yarp.Map2DLocation()
        self.navigation_interface.getCurrentPosition(current_pos)

        target_pos = yarp.Map2DLocation()
        self.navigation_interface.getAbsoluteTargetLocation(target_pos)

        # Get waypoints info if available
        waypoints_count = 0
        current_waypoint = -1
        try:
            # This depends on INavigation2D implementation
            # You may need to adjust based on actual interface
            current_waypoint = self.navigation_interface.getCurrentWaypoint() if hasattr(self.navigation_interface, 'getCurrentWaypoint') else -1
        except:
            pass

        status_map = {
            0: "idle",
            1: "navigating",
            2: "reached",
            3: "failed",
            4: "paused"
        }

        return {
            "success": True,
            "status": status_map.get(status, f"unknown_{status}"),
            "status_code": status,
            "current_position": {
                "x": current_pos.x,
                "y": current_pos.y,
                "theta": current_pos.theta
            },
            "target_position": {
                "x": target_pos.x,
                "y": target_pos.y,
                "theta": target_pos.theta
            },
            "navigation_active": status == 1,
            "current_waypoint": current_waypoint,
            "waypoints_count": waypoints_count
        }

    except Exception as e:
        logger.error(f"Error getting navigation status: {e}")
        return {
            "success": False,
            "error": f"Failed to get navigation status: {str(e)}"
        }
```

### 2. Update `get_battery_charge()` Tool (if accessed through navigation)

Or in the Battery server, add monitoring metadata:

```python
@self.mcp.tool()
async def get_battery_charge() -> dict[str, Any]:
    """
    Get the battery charge level (state of charge) as a percentage (0-100%).

    Can be monitored to wait for battery level changes using conditions like:
    - "charge < 20" to wait for low battery warning
    - "charge > 90" to wait for full charge

    Background monitoring metadata:
    {
        "x-monitoring": {
            "pollable": true,
            "description": "Monitor battery charge level",
            "expected_fields": ["charge"],
            "suggested_conditions": [
                "charge < 20",
                "charge > 90",
                "charge == 100"
            ],
            "polling_suggestion": "5.0 seconds",
            "timeout_suggestion": "3600.0 seconds",
            "typical_use_cases": [
                "Wait for robot to charge to full",
                "Alert when battery is low",
                "Monitor charging progress"
            ]
        }
    }
    """
    if self.battery_interface is None:
        return {
            "success": False,
            "error": "YARP battery not initialized. Call initialize_yarp first."
        }

    try:
        charge = self.battery_interface.getBatteryCharge()

        return {
            "success": True,
            "charge": charge,
            "unit": "percent",
            "is_low": charge < 20,
            "is_warning": charge < 30,
            "is_critical": charge < 10
        }

    except Exception as e:
        logger.error(f"Error getting battery charge: {e}")
        return {
            "success": False,
            "error": f"Failed to get charge: {str(e)}"
        }
```

## How It Works

### Step 1: Extended Tool Design
The tools remain functionally identical, but their descriptions now include monitoring metadata as a structured comment or in the docstring.

### Step 2: Client Discovery
When the client discovers tools via MCP's `list_tools()`, it now has:
- The metadata in the docstring (human-readable)
- Structured metadata can be extracted and stored

### Step 3: LLM Integration
The system prompt now tells the LLM about monitorable tools and suggests conditions.

### Step 4: User Interaction

User: *"Navigate to location (5, 3) and tell me when you arrive"*

Client/LLM flow:
1. LLM calls `goto_target_by_absolute_location(x=5.0, y=3.0, theta=0.0)`
2. LLM calls `start_monitoring("get_navigation_status", "status == 'reached' or status == 'failed'", timeout=300.0)`
3. Returns: "Starting navigation... I'll monitor and notify you when complete"
4. Background polling:
   - Every 1 second: calls `get_navigation_status()`
   - Evaluates condition: `status == 'reached' or status == 'failed'`
   - When condition is true: sends notification to user

## Multiple Monitoring Example

User: *"Navigate to the kitchen while monitoring battery, and stop if it gets below 15%"*

LLM calls:
1. `goto_target_by_absolute_location(x=5.0, y=3.0)`
2. `start_monitoring("get_battery_charge", "charge < 15", timeout=600.0)`
3. Meanwhile continues to process: "Navigating while monitoring battery..."

Result:
- Navigation proceeds
- Battery is checked every 5 seconds
- If battery drops to 15%, notification arrives
- LLM can then respond appropriately (return to charging dock, etc.)

## Server Implementation Checklist

- [ ] Update tool docstrings with monitoring metadata description
- [ ] Include `x-monitoring` JSON structure in docstrings or schema
- [ ] Document expected fields in result dictionaries
- [ ] Suggest reasonable conditions for common use cases
- [ ] Recommend polling intervals based on state change frequency
- [ ] Suggest timeouts based on typical operation duration
- [ ] Test tool with `start_monitoring()` calls from the client
- [ ] Verify conditions are evaluated correctly by the client

## No Breaking Changes

✅ Existing tools continue to work unchanged
✅ Existing clients ignore the metadata
✅ Gradual adoption - add to one tool first
✅ Fully backward compatible

## Integration Timeline

1. **Phase 1**: Update documentation in tool docstrings
2. **Phase 2**: Add formal `x-monitoring` metadata to schemas
3. **Phase 3**: Test with client's background monitoring
4. **Phase 4**: Refine conditions based on real usage

