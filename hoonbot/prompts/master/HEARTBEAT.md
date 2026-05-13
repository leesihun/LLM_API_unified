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
- For system health and memory review tasks, report the observed values under
  `System Review` even when there is no alert; do not reduce those review
  tasks to `HEARTBEAT_OK`.
- Do not send intermediate Messenger messages while running heartbeat tasks.
  Return reminder text, notifications, and findings in your task response so
  the heartbeat orchestrator can post exactly one final bubble.
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

---

# Heartbeat Checklist

This file is read every heartbeat interval.

Your job is to find things to do yourself
and actually, PROACTIVELY DO IT!!!

You need to actually do the job, observe its output and report back what has been done!!!

If there is a job that needs to be done in between this heartbeat and the previous one, do it yourself, proactively.

---

## Memory

- Go through the memory and see if there's things to do. Note that heartbeat interval is limited and may require additional jobs.
- Always display the full info to the user. Don't abbreviate or discard some information.
- **Update memory fully** — after system health check, training status, and any other checks, write all fresh live data back to the memory file. Overwrite the stale sections completely. Do not keep old/stale values.

## Reminders

- Check if any reminders are due. If so, queue the notification text for the
  final heartbeat report.
- If a reminder has fired, remove it from the reminder list and update memory.

## System Health

- Run `nvidia-smi --query-gpu=index,name,memory.used,memory.free,utilization.gpu,temperature.gpu --format=csv` for live GPU stats (util, memory, temp).
- Run `free -m` for live RAM.
- Run `df -h` for disk usage.
- If GPU memory is critically low (<5% free on any GPU), alert immediately.
- If any process has crashed or stalled, alert immediately.

## Priority Order

1. Crash/alert detection -> report immediately
2. System health (GPU, CPU, disk)
3. Training status (live log tail)
4. Reminders
5. Memory update (write all fresh data)
6. Memory review (display to user)
