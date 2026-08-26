# Asynchronous operation contract

This client follows long-running server work through MCP resources and resource
subscriptions. It does not consume custom JSON-RPC notifications and does not
depend on the experimental MCP Tasks extension.

## Start result

A server accepts work by returning structured content with at least:

```json
{
  "success": true,
  "operation_id": "4c1b...",
  "operation_type": "navigation_absolute",
  "status": "working",
  "status_uri": "yarp-operation://navigation/4c1b...",
  "poll_interval_ms": 500,
  "message": "Navigation accepted"
}
```

Only successful results containing both `operation_id` and `status_uri` are
tracked automatically.

## Authoritative snapshot

Reading `status_uri` returns JSON matching this shape:

```json
{
  "operation_id": "4c1b...",
  "operation_type": "navigation_absolute",
  "status": "working",
  "status_message": "Robot is moving",
  "progress": 0.4,
  "created_at": "2026-08-26T10:00:00Z",
  "updated_at": "2026-08-26T10:00:03Z",
  "poll_interval_ms": 500,
  "status_uri": "yarp-operation://navigation/4c1b...",
  "details": {},
  "result": null,
  "error": null,
  "revision": 3
}
```

Valid states are `working`, `completed`, `failed`, and `cancelled`. The latter
three are terminal. `progress`, when present, is in the inclusive range 0 to 1.
Domain-specific values belong in `details`; final output belongs in `result`;
machine-readable failure information belongs in `error`.

## Observation sequence

1. Track the exact ID and URI from the tool result.
2. Enter `client.listen(resource_subscriptions=[status_uri])`.
3. Immediately read the resource to close the subscribe/read race.
4. On a matching `ResourceUpdated`, read the resource again.
5. If no event arrives before the poll interval, read it anyway.
6. On subscription loss, retry with bounded exponential backoff.
7. Accept only a revision newer than the stored revision.
8. Deliver one completion message after observing a terminal state.

After delivery, the checker serializes a new LLM turn containing the authoritative
snapshot. This is what executes deferred instructions such as "when the battery
is below 20%, navigate to the charger". The background turn waits for any active
user turn and therefore cannot modify conversation history concurrently.

The local meta-tools `get_tracked_operation` and `list_tracked_operations` expose
the snapshots retained during the current client session.
`cancel_tracked_operation` routes cancellation through the exact server recorded
for that operation, avoiding ambiguity when several servers expose the common
`cancel_operation` tool. Navigation servers stop physical motion before marking
the operation cancelled.

## Runtime diagnostics

With the checker core, a successful start prints:

```text
Tracking server operation <id> at yarp-operation://<server>/<id>
```

Every accepted snapshot logs its operation ID, revision, and status. A terminal
snapshot prints `SERVER OPERATION FINISHED`, sends an unsolicited input-mode
notification, and starts the serialized continuation turn.

In `resources/applications/testClient_lobbyAmbassador_sim.xml`, the client output
port is `/testClient/text:o`, but that application does not connect it to another
YARP port. Consequently, raw textual responses are visible in the client console
but have no external YARP consumer. Deferred physical or speech actions should be
performed by the resumed LLM through MCP tools; connect `/testClient/text:o` to a
diagnostic reader if the raw messages also need to be observed externally.
