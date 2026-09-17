# 59 - Worker slots count every session a conductor owes

**What to build:** `policy.max_parallel_workers` holds at every moment, not only at the moment a wave picks. Today the pick counts a slot as busy only while a session's thread is still running (`Conductor._picks`: `attempt.running or attempt.adopted`). A session whose process has exited, but whose result the conductor has not carried yet, counts as a free slot. A session that ends between wave step 3 (the poll) and step 9 (the pick) therefore lets the pick fill its slot with a new worker. The next wave carries the session and may resume it (a gate's resume, or the escalation ladder's resume), so one more worker runs than the policy allows. The fix is to count every attempt in flight that runs a session, or is about to start one in the same wave, and to check the slots before a gate's resume as the ladder's resume already does (ticket 38, `Conductor._resume_failed`).

**Blocked by:** 38 (Stall detection and the escalation chain), which added the slot check on the ladder's resume and edits the same wave code.

**Status:** done

**GitHub:** [#126](https://github.com/Bernaljp/wayline/issues/126) (mirror; the local file is the source)

**Milestone:** M5 Overnight and report. **Spec:** Implementation Decisions 5 (wave steps 3 and 9, `max_parallel_workers`), 14 (`max_parallel_workers`). The owner asked for this ticket on 2026-09-17, from the review of ticket 38's pull request.

- [x] With `max_parallel_workers: 1`, a session that returns between the poll and the pick keeps its slot: the pick launches nothing until the session is carried and, if it is resumed, until the resume returns.
- [x] A gate's resume (an invalid result, a failed acceptance, a timeout) and a relaunch after a worker died wait for a free slot when every slot is taken, as the ladder's resume does; the wait is said once, and the session starts at the first wave with a free slot.
- [x] The number of workers the fake launcher holds at once never exceeds `max_parallel_workers` over a run that mixes launches, gate resumes, and ladder resumes. The test drives two and three tickets with scripted delays and checks the fake's live calls at every wave.
- [x] `python -m unittest` passes, with the new tests in `tests/test_conductor.py` or `tests/test_escalation.py`.
