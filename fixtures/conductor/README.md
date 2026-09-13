# Conductor fixtures

Recorded journals the conductor's replay is tested against (Testing Decisions, seam 4). They are
recordings rather than hand-written journals, so remake one after a change to what the conductor
journals.

## m1-kill-resume

The five-ticket project of `fixtures/projects/five-tickets/`, its conductor killed with SIGKILL
once the workers of tickets 3 and 4 had both journaled their sessions, while both were still running.
Tickets 1 and 2 are done; tickets 3 and 4 are `running`, each with a journaled session and no
result; ticket 5 is open.

`tests/test_resume.py` uses it twice. It replays `research/journal.jsonl` and asserts the view the
kill left: the statuses, the attempts, the sessions and pids of the two interrupted workers, the
standing pause, pacing, and stall counter, and that replaying it twice yields the same view. Then it
copies the recording, lays it out with `init`, runs the next conductor over it with the fake worker,
and asserts what that run appends: both interrupted workers resumed by their session ids, ticket 5
launched after them, and `run_ended` with `frontier_empty`.

What is kept: `harness.json` (with `poll_seconds: 1`, its one change from the project fixture), the
journal, the ticket files, `graph.json`, the heartbeat `conductor.json`, each session's
`stream.jsonl` and `pid`, and the files `main` held at the kill (`notes/` and `reports/`). The
prompts, settings, and environments beside the streams are left out, because they name the harness
checkout the recording was made from; the journal names only the scratch project
`/tmp/wayline-m1-kill-resume/five-tickets`, which is the same on every machine.

To remake it:

```
python3 fixtures/conductor/record.py
```
