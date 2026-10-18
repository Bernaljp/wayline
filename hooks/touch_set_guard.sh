#!/usr/bin/env bash
# touch_set_guard.sh: PreToolUse guard for Write|Edit|NotebookEdit.
#
# Reads the hook JSON on stdin (https://code.claude.com/docs/en/hooks#pretooluse-input),
# takes the target path from tool_input.file_path (Write, Edit) or
# tool_input.notebook_path (NotebookEdit), resolves it, and exits 2 with a
# message on stderr when the path is outside the ticket's touch set.
#
# TICKET_TOUCHES is a colon-separated list of path prefixes, relative to the
# project root (the worktree the session started in) or absolute.
# Example (BRIEF.md Appendix B): TICKET_TOUCHES="experiments/ablation_b/:results/ablation_b/"
#
# Exit codes (https://code.claude.com/docs/en/hooks#exit-code-output):
#   0  no decision; the normal permission flow applies
#   2  block the tool call; stderr is shown to Claude as the denial reason
# The guard fails closed: no TICKET_TOUCHES, no path, or an unreadable input
# all block the write.
set -u

INPUT=$(cat)

# jq is required; a missing jq must block, not silently allow.
if ! command -v jq >/dev/null 2>&1; then
  echo "touch_set_guard: jq is not installed; blocking the write" >&2
  exit 2
fi

TOOL_NAME=$(printf '%s' "$INPUT" | jq -r '.tool_name // empty')
TARGET=$(printf '%s' "$INPUT" | jq -r '.tool_input.file_path // .tool_input.notebook_path // empty')
CWD=$(printf '%s' "$INPUT" | jq -r '.cwd // empty')

if [ -z "$TARGET" ]; then
  echo "touch_set_guard: no file path in tool_input for $TOOL_NAME; blocking" >&2
  exit 2
fi

if [ -z "${TICKET_TOUCHES:-}" ]; then
  echo "touch_set_guard: TICKET_TOUCHES is not set; no writes are allowed in this session" >&2
  exit 2
fi

# Root for relative entries: the project root where the session started
# (CLAUDE_PROJECT_DIR, https://code.claude.com/docs/en/hooks#reference-scripts-by-path),
# then the hook's cwd, then the shell cwd.
ROOT="${CLAUDE_PROJECT_DIR:-${CWD:-$PWD}}"
ROOT=$(realpath -m "$ROOT")

# file_path is documented as absolute for Write/Edit; normalize anyway so
# "..", symlinks, and relative spellings cannot escape the touch set.
case "$TARGET" in
  /*) ABS=$(realpath -m "$TARGET") ;;
  *)  ABS=$(realpath -m "$ROOT/$TARGET") ;;
esac

# Nothing under research/ is a worker's to write, whatever the touch set names
# (Implementation Decision 1): sections, reports, and the ledger are written only
# by code. This is checked before the touch set, so no entry can widen it.
case "$ABS" in
  "$ROOT/research"|"$ROOT/research"/*)
    echo "touch_set_guard: $TOOL_NAME to $ABS is under research/, which only code writes; no touch set opens it. Report what should change there instead." >&2
    exit 2 ;;
esac

IFS=':' read -r -a ENTRIES <<< "$TICKET_TOUCHES"
for entry in "${ENTRIES[@]}"; do
  [ -z "$entry" ] && continue
  case "$entry" in
    /*) prefix=$(realpath -m "$entry") ;;
    *)  prefix=$(realpath -m "$ROOT/$entry") ;;
  esac
  # An entry that names a directory (trailing slash in the raw entry, or an
  # existing directory) matches everything below it; otherwise exact file match.
  if [ "${entry%/}" != "$entry" ] || [ -d "$prefix" ]; then
    case "$ABS" in
      "$prefix"/*) exit 0 ;;
    esac
  else
    [ "$ABS" = "$prefix" ] && exit 0
  fi
done

echo "touch_set_guard: $TOOL_NAME to $ABS is outside the ticket touch set ($TICKET_TOUCHES). Write only under the listed paths, or report that the ticket needs a wider touch set." >&2
exit 2
