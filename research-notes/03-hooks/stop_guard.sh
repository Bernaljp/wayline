#!/usr/bin/env bash
# stop_guard.sh: Stop hook that refuses to let the worker stop until the
# machine acceptance has been run.
#
# Input: Stop hook JSON on stdin (https://code.claude.com/docs/en/hooks#stop-input):
#   stop_hook_active  true when Claude Code is already continuing because of a
#                     stop hook. Always allow the stop then, or the session loops
#                     until the 8-block cap (https://code.claude.com/docs/en/hooks#stop).
#   last_assistant_message  final text of the turn (unused here).
#
# Output (https://code.claude.com/docs/en/hooks#stop-decision-control):
#   exit 0 with no JSON      allow the stop
#   exit 0 with JSON         {"decision":"block","reason":"..."} keeps Claude working;
#                            reason is required and is fed back to Claude
#   exit 2 + stderr          equivalent block; stderr becomes the reason
#
# Contract with the harness: TICKET_ACCEPTANCE_FILE names the file that the
# acceptance runner writes (a JSON result, Section 5.4 of BRIEF.md). Missing
# file means acceptance was never run, so the stop is blocked once.
set -u

INPUT=$(cat)

if ! command -v jq >/dev/null 2>&1; then
  # Cannot parse the input; do not risk an infinite loop. Allow the stop.
  echo "stop_guard: jq not installed; allowing the stop" >&2
  exit 0
fi

ACTIVE=$(printf '%s' "$INPUT" | jq -r '.stop_hook_active // false')
if [ "$ACTIVE" = "true" ]; then
  exit 0
fi

# No contract configured: nothing to enforce.
if [ -z "${TICKET_ACCEPTANCE_FILE:-}" ]; then
  exit 0
fi

if [ -f "$TICKET_ACCEPTANCE_FILE" ]; then
  exit 0
fi

jq -n --arg f "$TICKET_ACCEPTANCE_FILE" '{
  decision: "block",
  reason: ("The machine acceptance has not been run: " + $f + " does not exist. Run the ticket acceptance command (see the ticket prompt), fix any failure, then finish with the structured result.")
}'
exit 0
