# 126 - Setup's answers through the routed verbs

**What to build:** Every answer of the setup conversation, and every record the conversation makes afterwards, reaches the ledger through a command a session holding the routed verbs can run, and the owner never edits a file to finish setup.

On the toy's live setup (ticket 122, `docs/verification/m8.md`), the session runs under `dontAsk` with `Bash(wayline *)`, as the recorded setup fixture's launch says and the dashboard's chat does. Three answers could not be recorded:

- **The intake spec.** The skill hands JSON to `wayline intake --from -`, and the session wrote it as a heredoc, which `dontAsk` refuses (`wayline … <<EOF` is not a plain `wayline` command). A probe the same day showed that `echo '{…}' | wayline …` runs under the same rules. The session then tried `Write` to `/tmp` (refused) and fell back to `--intent` and flags.
- **Setup 7 and 8** (the code repository; the decider's paper order and its venue) exist only as fields of the intake spec, so the session drafted `owner/intake.json` for the owner to save. The owner's first try failed on `gpu_hours` and `wallclock_hours`, which the intake refuses, and the session asked the owner to delete a line by hand.
- **Setup 5's stopping rule.** The owner's answer, `objectives`, equalled the default, so `wayline switch --stop-when objectives` printed "already objectives" and wrote and journaled nothing. The owner's word lives only in the conversation, and fixture `skill/wayline`'s check `the_stopping_rule_is_recorded` fails on the recording.

The same holds after setup. Mid-run, the owner asked the dashboard's chat to have tickets 30, 33, and 34 re-cut under `src/`; the chat drafted the three tickets and could not record them, because the skill's own form is `wayline ticket add - --project . <<'EOF'` (`skills/wayline/SKILL.md`), and it told the owner that `ticket add` and `pause` were not allowed in the chat, though both are in `chat.chat_commands()`. It asked the owner to widen the chat's permissions.

What to build:

- The setup reference, `SKILL.md`, and the routing table hand JSON through a pipe (`printf '%s' '<json>' | wayline intake --from - --project .`), or the verbs take it inline; no setup step needs a heredoc, `Write`, or `Edit`.
- The code repository's shape, license, and remote, and the paper order's decider and venue, each get a flag of their own (on `intake`, or a `switch` the routing table names), so neither needs the whole spec sent again.
- `switch --stop-when` journals the owner's answer even when it equals the current rule (a `control` event with `from` equal to the value), and writes `stop_when` to `harness.json`.
- The fixture `skill/wayline` passes all thirteen of its checks when it is next recorded.

**Blocked by:** None - can start immediately.

**Status:** ready-for-agent

**GitHub:** [#333](https://github.com/Bernaljp/wayline/issues/333) (mirror; the local file is the source)

**Milestone:** after M8 (v1.1.x). **Spec:** Implementation Decision 17 (talking with the project: setup, at every autonomy; the stopping rule), 1 (the verb table), 12 (fixtures); ticket 109; ticket 122's live record.

- [ ] Each of setup's ten answers is recorded by a command that runs under `dontAsk` with `Bash(wayline *)` only; a test runs every command the setup reference names through the chat's own permission rules.
- [ ] The chat records a request for work with `ticket add` under its own permission rules; checked live once and recorded.
- [ ] Setup 7 and 8 are recorded without the intake spec being sent again.
- [ ] `switch --stop-when` with the current value journals the owner's answer and writes `harness.json`.
- [ ] The verb table changes in the same commit as the code.
- [ ] `python -m unittest` passes.
