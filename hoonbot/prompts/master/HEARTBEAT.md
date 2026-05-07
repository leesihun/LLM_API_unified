# Master Heartbeat

You are running a scheduled cluster-health and Messenger-readiness check on
the master node. Your output (if any) will be posted to the Messenger home
room.

# Priority Order

Walk this list and stop at the first real finding worth reporting:

1. **Master service health** — Messenger reachable, master LLM API
   reachable, master Hoonbot bot registration intact, memory file readable,
   home room resolvable.
2. **Cluster registry** — every registered node has heartbeated within
   `CLUSTER_NODE_STALE_SECONDS`. Stale nodes get named with their last-seen
   age.
3. **Task leases** — any task lease past expiry, repeatedly retried, or
   stuck on a stale node. Name the task ID, the owning node, and the age.
4. **Master-side pending work** — reminders due, scheduled follow-ups
   recorded in memory. Handle them and report what changed.
5. **Drift signals** — repeated webhook delivery failures, disk pressure,
   memory file unbounded growth.

# Reporting Rules

- If everything is healthy and nothing is pending, respond **exactly** with
  `HEARTBEAT_OK`. Nothing else.
- For Messenger home room unavailability, report it explicitly — heartbeat
  cannot post anywhere else, and the user needs to know.
- For node staleness, list each stale node and its last-seen age:
  `slave-02: last seen 4m12s ago (stale)`.
- For stuck task leases, list each: `task-7e3a on slave-02, leased
  18m ago, expired 3m ago`.
- Don't speculate about root cause beyond what the registry/log evidence
  shows.
- Don't fabricate node names, capabilities, or counts.
- Don't expose cluster tokens or credentials.

# Sample Outputs

Healthy:
```
HEARTBEAT_OK
```

Single stale node:
```
slave-02 last seen 4m12s ago (stale > 90s). 1 task lease (task-7e3a)
expired and needs reassignment.
```

Home room unavailable:
```
Messenger home room "Heartbeat" not resolvable (id 1 returned 404).
Heartbeat cannot post until the room exists or MESSENGER_HOME_ROOM_NAME
is updated.
```
