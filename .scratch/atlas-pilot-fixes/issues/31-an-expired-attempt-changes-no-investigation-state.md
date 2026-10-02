# 31: An expired attempt changes no investigation state

**What to build:** When a job's lease expires and another attempt of the same job runs, the earlier attempt can no longer record anything on the investigation: not a task's outcome, not an event, not a plan change.

Evidence: an external review by Codex (the owner shared it on 2026-10-02); the lead verified the finding in the code before writing this ticket. The queue checks which worker holds a job, but the investigation task's finish only checks that the task is running and belongs to the same job (`backend/atlas/investigations/tasks.py`, `_finish`: "recorded by an earlier attempt"); two attempts of one job share the job ID. Production runs one worker process today, so attempts do not overlap; they would once role calls run concurrently (pilot-fix ticket 27).

- Each investigation write made on a job attempt's behalf (the task's outcome, its events, the plan's growth, pointers) is fenced by the attempt that holds the job's lease: the queue's attempt number or lease token, checked in the same transaction.
- A stale attempt's write is dropped and recorded as an event (`stale_attempt_ignored`), never an error that fails the newer attempt.

**Blocked by:** None

**Status:** ready-for-agent after the verdict; it blocks pilot-fix ticket 27 (no concurrent role calls before this is in)

- [ ] Integration test at the worker seam: an attempt whose lease has expired and been taken by a second attempt finishes last; its outcome is not recorded and the second attempt's is.
- [ ] Decision entry.
