# Conductor fixtures

Recorded journals the conductor's replay is tested against (Testing Decisions, seam 4). They are
recordings rather than hand-written journals, so remake one after a change to what the conductor
journals.

## m1-kill-resume

The five-ticket project of `fixtures/projects/five-tickets/`, its conductor killed with SIGKILL in
its second wave while the workers of tickets 3 and 4 were running. Tickets 1 and 2 are done;
tickets 3 and 4 are `running`, each with a journaled session and no result; ticket 5 is open.
`tests/test_resume.py` replays `research/journal.jsonl` and asserts the view the kill left: the
statuses, the attempts, the sessions and pids of the two interrupted workers, the standing state,
and that replaying it twice yields the same view.

What is kept: `harness.json` (with `poll_seconds: 1`, its one change from the project fixture), the
journal, the ticket files, `graph.json`, the heartbeat `conductor.json`, and each session's
`stream.jsonl` and `pid`. The prompts, settings, and environments beside the streams are left out,
because they name the harness checkout the recording was made from; the journal names only the
scratch project `/tmp/wayline-m1-kill-resume/five-tickets`, which is the same on every machine.

To remake it:

```
python3 fixtures/conductor/record.py
```
