# Protocol

1. Read every feedback item below, and the retrospective when there is one. Each has an id; every
   record you return names the item it answers in `feedback`, and every item ends up answered by
   at least one record or listed in `dismissed` with the reason.
2. Read the journal digest. It is numbered by journal line, so the lines that show a behaviour are
   cited as `research/journal.jsonl#L<n>`. Open `research/journal.jsonl`, a ticket file, or a
   session directory under `research/sessions/` when the digest is not enough to say what happened.
3. Read the change records already open. A behaviour one of them answers is not answered again:
   dismiss the item and name the record.
4. Read what the harness and the project hold: the registry lists every skill and role with its
   scope and its outcome record, and the policy is given with the project's overrides. Open the
   role, the skill, the prompt, or the hook you think is responsible before you blame it.
5. For each change, decide the mechanism, then local or global, then the target path:
   - a local skill: `.claude/skills/wayline-<name>/` (the `wayline-` prefix is what lets a ticket
     name it);
   - a local role or prompt change: `.claude/agents/<role>.md`, for a role the harness has;
   - a local policy change: `harness.json`, with the top-level policy keys in `keys`;
   - a global change: the path in the harness repository, such as `roles/writer/agent.md`,
     `prompts/roles/planner.md`, `policy.json`, `hooks/command_guard.sh`, or `wayline/plan.py`.
   A hook or a code change is always global.
6. Name the fixture, `<kind>/<slug>`, with `kind` one of `prompt`, `role`, `skill`, `verifier`, and
   say in `notes` which session to record it from and what it must check. Give `acceptance`
   commands that fail today and pass after the change, `difficulty` by the rubric, and `risk`.
7. Return the list through the structured output, once, before you stop: `records`, `dismissed`,
   and `recommendations`. Code gives each record its id and status and files its harness ticket;
   nothing you say outside the structured output is read by anyone.
