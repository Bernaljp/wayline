#!/usr/bin/env bash
# command_guard.sh: PreToolUse guard for Bash (Implementation Decisions 4).
#
# `permissions.deny` is the cheap first layer: it matches the command text Claude
# usually writes. This guard is the second layer, for the spellings a deny rule
# misses (https://code.claude.com/docs/en/permissions#bash-rule-limits): an absolute
# path to the program, `bash -c`, `env`, `sudo`, `xargs`, a command substitution,
# `git -C <dir> push`, `find -delete`.
#
# It reads the hook JSON on stdin (https://code.claude.com/docs/en/hooks#pretooluse-input),
# takes tool_input.command, normalizes it, and exits 2 with a reason on stderr for
# every pattern on the irreversible list:
#
#   git push (any spelling), git reset --hard, git clean -f, git branch -D,
#   git worktree remove, rm outside the touch set, find -delete, chmod -R,
#   truncate, dd of=, an upload flag on curl or wget, twine, pip upload,
#   gh pr, gh release, and any write target resolving outside the worktree,
#   results/ and the temporary directory.
#
# Exit codes (https://code.claude.com/docs/en/hooks#exit-code-output):
#   0  no decision; the normal permission flow applies
#   2  block the tool call; stderr is shown to Claude as the denial reason
#
# The guard fails closed wherever it cannot see: a missing jq, a missing command, a
# target path hidden behind a variable, an unset TICKET_TOUCHES on a deletion, an
# `rm` whose targets arrive on stdin, a pipe or a here-string into a shell, a `cd`
# out of the worktree, and a command too long, too deeply nested, or too expensive
# to lex.
#
# Known limit, and the spec's own (Implementation Decisions 4, quoting the
# permissions documentation): a rule cannot see inside a program. `python3 -c`,
# `perl -e`, an `ssh` command line and a container run are analysed as the
# invocation they are, not as the code they carry. The layers that hold there are
# the role's tool allowlist and the absence of network tools, not this guard.
#
# Environment (exported by the conductor at launch):
#   CLAUDE_PROJECT_DIR      the worktree root; the session starts there
#   TICKET_TOUCHES          colon-separated touch set, as in touch_set_guard.sh
#   WAYLINE_RESULTS         absolute path of the project's results/ (optional)
#   WAYLINE_ALLOWED_ROOTS   colon-separated extra roots a write may reach (optional)
#   WAYLINE_HOOK_RECORD     a file every hook input is appended to (optional; records only)
set -u

MAX_COMMAND_CHARS=20000
MAX_UNITS=64
# A timed-out PreToolUse hook does NOT block, so the guard must finish well inside the
# 30 second handler timeout. Lexing costs about one step per special character and each
# step costs time proportional to the length, so the budget is on their product.
MAX_LEX_COST=40000000
SUBMARK=$'\002'

# Character classes for the lexer, as ERE bracket expressions. Inside brackets a
# backslash is literal in POSIX ERE, so every character here stands for itself.
ORD_RE='^[^\"'\''$`|&;<>()#[:space:]]+'
DQ_RE='^[^\"$`]+'
PAREN_RE='^[^()\"'\''`]+'
INNER_DQ_RE='^[^\"]+'
DELIM_RE='^[^[:space:]\"'\''`]+'

deny() {
  printf 'command_guard: %s\n' "$1" >&2
  exit 2
}

if ! command -v jq >/dev/null 2>&1; then
  deny "jq is not installed; blocking the command"
fi

INPUT=$(cat)

# Recording, for a milestone's live record and nothing else. With WAYLINE_HOOK_RECORD
# set, every hook input the guard is handed is appended there as one JSON line, calls
# made inside an Agent-tool subagent included, which is where the agent_id and
# agent_type of docs/verification/m0.md come from. It can never change a decision: the
# whole of it runs in a subshell with its errors dropped, so a path that cannot be
# written loses the recording rather than the command.
if [ -n "${WAYLINE_HOOK_RECORD:-}" ]; then
  # One JSON object per line, whatever arrives: every reader of this file parses it line by
  # line, so raw multi-line input would lose the whole record rather than the one entry.
  RECORD_LINE=$(printf '%s' "$INPUT" | jq -c . 2>/dev/null)
  [ -n "$RECORD_LINE" ] || RECORD_LINE=$(printf '%s' "$INPUT" | jq -Rsc '{raw: .}' 2>/dev/null)
  [ -n "$RECORD_LINE" ] || RECORD_LINE='{"raw": null}'
  (
    if command -v flock >/dev/null 2>&1; then
      exec 9>>"$WAYLINE_HOOK_RECORD"
      flock -w 5 9 || true
      printf '%s\n' "$RECORD_LINE" >&9
    else
      printf '%s\n' "$RECORD_LINE" >>"$WAYLINE_HOOK_RECORD"
    fi
  ) 2>/dev/null
fi

COMMAND=$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty')
CWD=$(printf '%s' "$INPUT" | jq -r '.cwd // empty')
TOOL=$(printf '%s' "$INPUT" | jq -r '.tool_name // "Bash"')

if [ -z "$COMMAND" ]; then
  deny "no command in tool_input for $TOOL; blocking"
fi
if [ ${#COMMAND} -gt $MAX_COMMAND_CHARS ]; then
  deny "the command is ${#COMMAND} characters, more than the $MAX_COMMAND_CHARS the guard will analyse; split it into smaller commands"
fi

MAX_STEPS=$((MAX_LEX_COST / (${#COMMAND} + 1)))
STEPS=0

step() {
  STEPS=$((STEPS + 1))
  if [ $STEPS -gt $MAX_STEPS ]; then
    deny "the command needs more lexing than the guard will spend on a $((${#COMMAND})) character command; a timed-out hook does not block, so it is blocked here. Write it as several plainer commands."
  fi
}

# The root for relative paths: the project root where the session started
# (CLAUDE_PROJECT_DIR), then the hook's cwd, then the shell cwd.
ROOT="${CLAUDE_PROJECT_DIR:-${CWD:-$PWD}}"
ROOT=$(realpath -m "$ROOT")

# Where a write may land. The worktree and results/ are the spec's two; the temporary
# directory is added here because scratch output (`2>/dev/null`, `> $TMPDIR/x`) is
# routine and a temporary file is not data, so losing one is not irreversible.
TEMP_ROOT=$(realpath -m "${TMPDIR:-/tmp}")
WRITE_ROOTS=("$ROOT" "$(realpath -m "$ROOT/results")" "$TEMP_ROOT")
if [ -n "${WAYLINE_RESULTS:-}" ]; then
  WRITE_ROOTS+=("$(realpath -m "$WAYLINE_RESULTS")")
fi
if [ -n "${WAYLINE_ALLOWED_ROOTS:-}" ]; then
  IFS=':' read -r -a _extra <<< "$WAYLINE_ALLOWED_ROOTS"
  for _entry in "${_extra[@]}"; do
    [ -n "$_entry" ] && WRITE_ROOTS+=("$(realpath -m "$_entry")")
  done
fi

# --- paths ------------------------------------------------------------------------------------

resolve() {
  # Absolute path of a raw word, or failure when a variable or a substitution hides it.
  local w="$1"
  case "$w" in
    *'$'*|*"$SUBMARK"*|*'`'*) return 1 ;;
  esac
  case "$w" in
    '~') w="${HOME:-}" ;;
    '~/'*) w="${HOME:-}/${w#\~/}" ;;
  esac
  [ -n "$w" ] || return 1
  case "$w" in
    /*) realpath -m "$w" ;;
    *) realpath -m "$ROOT/$w" ;;
  esac
}

hidden_by() {
  # How a word hides its target, for the denial reason.
  case "$1" in
    *"$SUBMARK"*|*'`'*) printf 'a command substitution' ;;
    *) printf 'a variable' ;;
  esac
}

under() {
  local path="$1"
  shift
  local root
  for root in "$@"; do
    [ "$path" = "$root" ] && return 0
    case "$path" in
      "$root"/*) return 0 ;;
    esac
  done
  return 1
}

in_touch_set() {
  # The touch-set rule of touch_set_guard.sh, plus the entry itself: `rm -rf build` is
  # inside the touch set `build/`, because the touch set is what the ticket may write.
  local path="$1" entry prefix
  local -a entries
  IFS=':' read -r -a entries <<< "${TICKET_TOUCHES:-}"
  for entry in "${entries[@]}"; do
    [ -z "$entry" ] && continue
    case "$entry" in
      /*) prefix=$(realpath -m "$entry") ;;
      *) prefix=$(realpath -m "$ROOT/$entry") ;;
    esac
    [ "$path" = "$prefix" ] && return 0
    if [ "${entry%/}" != "$entry" ] || [ -d "$prefix" ]; then
      case "$path" in
        "$prefix"/*) return 0 ;;
      esac
    fi
  done
  return 1
}

check_write_target() {
  local raw="$1" what="$2" abs
  [ -n "$raw" ] || return 0
  case "$raw" in
    -|/dev/null|/dev/zero|/dev/full|/dev/stdout|/dev/stderr|/dev/tty|/dev/fd/*|/proc/self/fd/*) return 0 ;;
  esac
  if ! abs=$(resolve "$raw"); then
    deny "$what '$raw' hides its target behind $(hidden_by "$raw"); the guard cannot resolve it, so it is blocked. Write to a literal path inside the worktree."
  fi
  if ! under "$abs" "${WRITE_ROOTS[@]}"; then
    deny "$what '$raw' resolves to $abs, outside the worktree ($ROOT), results/ and $TEMP_ROOT. A worker writes only inside its worktree; report that the ticket needs a wider touch set."
  fi
}

check_delete_target() {
  local raw="$1" what="$2" abs
  if ! abs=$(resolve "$raw"); then
    deny "$what '$raw' hides its target behind $(hidden_by "$raw"); deleting an unresolved path is blocked."
  fi
  if [ -z "${TICKET_TOUCHES:-}" ]; then
    deny "TICKET_TOUCHES is not set; no deletion is allowed in this session ($what '$raw')"
  fi
  if ! in_touch_set "$abs"; then
    deny "$what '$raw' resolves to $abs, outside the ticket touch set (${TICKET_TOUCHES}). Deleting files is on the irreversible list; delete only the listed paths and what is under them."
  fi
}

# --- the lexer ---------------------------------------------------------------------------------
# Tokens land in KIND/TEXT: 'w' a word, 'o' an operator (a segment boundary), 'r' a
# redirection whose next word is a write target, 'h' a here-string whose next word is the
# text fed to the command, 'x' a redirection whose next word is neither (a read, a
# file-descriptor duplication). Command substitutions, backticks, process substitutions,
# `sh -c` bodies and `eval` arguments are pushed onto QUEUE and analysed as commands of
# their own; a heredoc body is kept aside and analysed only when a shell is what reads it.

KIND=()
TEXT=()
QUEUE=("$COMMAND")
HEREDOC_BODIES=()

flush_word() {
  if [ "$have" -eq 1 ]; then
    KIND+=(w)
    TEXT+=("$word")
  fi
  word=""
  have=0
}

take_paren() {
  # `rest` starts with the two characters before the body ('$(', '<(' or '>(');
  # consume through the matching ')' and queue the body.
  local body="" depth=1 char seg
  rest="${rest:2}"
  while [ -n "$rest" ]; do
    step
    if [[ $rest =~ $PAREN_RE ]]; then
      body+="${BASH_REMATCH[0]}"
      rest="${rest#"${BASH_REMATCH[0]}"}"
      continue
    fi
    char="${rest:0:1}"
    case "$char" in
      '(') depth=$((depth + 1)); body+='('; rest="${rest:1}" ;;
      ')')
        depth=$((depth - 1))
        rest="${rest:1}"
        if [ $depth -eq 0 ]; then
          QUEUE+=("$body")
          word+="$SUBMARK"
          have=1
          return 0
        fi
        body+=')' ;;
      '\') body+="${rest:0:2}"; rest="${rest:2}" ;;
      "'")
        seg="${rest:1}"
        if [[ $seg == *"'"* ]]; then
          body+="'${seg%%\'*}'"
          rest="${seg#*\'}"
        else
          body+="'$seg"
          rest=""
        fi ;;
      '"')
        body+='"'
        rest="${rest:1}"
        while [ -n "$rest" ]; do
          step
          if [[ $rest =~ $INNER_DQ_RE ]]; then
            body+="${BASH_REMATCH[0]}"
            rest="${rest#"${BASH_REMATCH[0]}"}"
            continue
          fi
          if [ "${rest:0:1}" = '\' ]; then
            body+="${rest:0:2}"
            rest="${rest:2}"
            continue
          fi
          body+='"'
          rest="${rest:1}"
          break
        done ;;
      '`') body+='`'; rest="${rest:1}" ;;
    esac
  done
  QUEUE+=("$body")
  word+="$SUBMARK"
  have=1
}

take_backtick() {
  local body="${rest:1}"
  if [[ $body == *'`'* ]]; then
    QUEUE+=("${body%%\`*}")
    rest="${body#*\`}"
  else
    QUEUE+=("$body")
    rest=""
  fi
  word+="$SUBMARK"
  have=1
}

skip_arithmetic() {
  # `rest` starts with '$(('; the two parens are counted together.
  local depth=0 char
  rest="${rest:1}"
  while [ -n "$rest" ]; do
    step
    if [[ $rest =~ ^[^()]+ ]]; then
      rest="${rest#"${BASH_REMATCH[0]}"}"
      continue
    fi
    char="${rest:0:1}"
    if [ "$char" = '(' ]; then depth=$((depth + 1)); else depth=$((depth - 1)); fi
    rest="${rest:1}"
    [ $depth -eq 0 ] && break
  done
  word+='0'
  have=1
}

take_heredoc_delimiter() {
  # `rest` starts just after '<<' or '<<-'; read the delimiter word and record it.
  local delim="" quote seg
  while [ -n "$rest" ] && [[ ${rest:0:1} == [[:blank:]] ]]; do rest="${rest:1}"; done
  while [ -n "$rest" ]; do
    step
    case "${rest:0:1}" in
      "'"|'"')
        quote="${rest:0:1}"
        seg="${rest:1}"
        if [[ $seg == *"$quote"* ]]; then
          delim+="${seg%%"$quote"*}"
          rest="${seg#*"$quote"}"
        else
          delim+="$seg"
          rest=""
        fi ;;
      '\') delim+="${rest:1:1}"; rest="${rest:2}" ;;
      *)
        if [[ $rest =~ $DELIM_RE ]]; then
          delim+="${BASH_REMATCH[0]}"
          rest="${rest#"${BASH_REMATCH[0]}"}"
        else
          break
        fi ;;
    esac
    [ -z "$rest" ] && break
    [[ ${rest:0:1} == [[:space:]] ]] && break
  done
  HEREDOCS+=("$delim")
}

cut_heredoc_bodies() {
  # Called once the newline after the redirection is reached. A heredoc body is data to
  # whatever reads it, so it leaves the token stream; it is kept in HEREDOC_BODIES because
  # `bash <<EOF` reads it as a command.
  local delim line trimmed body
  while [ ${#HEREDOCS[@]} -gt 0 ]; do
    delim="${HEREDOCS[0]}"
    HEREDOCS=(${HEREDOCS[@]+"${HEREDOCS[@]:1}"})
    body=""
    while [ -n "$rest" ]; do
      step
      if [[ $rest == *$'\n'* ]]; then
        line="${rest%%$'\n'*}"
        rest="${rest#*$'\n'}"
      else
        line="$rest"
        rest=""
      fi
      trimmed="$line"
      while [ "${trimmed:0:1}" = $'\t' ]; do trimmed="${trimmed:1}"; done
      [ "$trimmed" = "$delim" ] && break
      body+="$line"$'\n'
    done
    HEREDOC_BODIES+=("$body")
  done
}

lex() {
  local rest="$1"
  local word="" have=0 char run
  local -a HEREDOCS=()
  KIND=()
  TEXT=()
  HEREDOC_BODIES=()
  while [ -n "$rest" ]; do
    step
    if [[ $rest =~ $ORD_RE ]]; then
      word+="${BASH_REMATCH[0]}"
      have=1
      rest="${rest#"${BASH_REMATCH[0]}"}"
      continue
    fi
    char="${rest:0:1}"
    case "$char" in
      ' '|$'\t'|$'\n'|$'\r'|$'\v'|$'\f')
        [[ $rest =~ ^[[:space:]]+ ]]
        run="${BASH_REMATCH[0]}"
        rest="${rest#"$run"}"
        flush_word
        if [[ $run == *$'\n'* ]]; then
          KIND+=(o)
          TEXT+=($'\n')
          [ ${#HEREDOCS[@]} -gt 0 ] && cut_heredoc_bodies
        fi ;;
      '#')
        if [ $have -eq 0 ]; then
          if [[ $rest == *$'\n'* ]]; then
            rest="${rest#*$'\n'}"
            KIND+=(o)
            TEXT+=($'\n')
          else
            rest=""
          fi
        else
          word+='#'
          rest="${rest:1}"
        fi ;;
      '\')
        if [ ${#rest} -ge 2 ]; then
          if [ "${rest:1:1}" = $'\n' ]; then
            rest="${rest:2}"
          else
            word+="${rest:1:1}"
            have=1
            rest="${rest:2}"
          fi
        else
          rest=""
        fi ;;
      "'")
        rest="${rest:1}"
        if [[ $rest == *"'"* ]]; then
          word+="${rest%%\'*}"
          rest="${rest#*\'}"
        else
          word+="$rest"
          rest=""
        fi
        have=1 ;;
      '"')
        rest="${rest:1}"
        have=1
        while [ -n "$rest" ]; do
          step
          if [[ $rest =~ $DQ_RE ]]; then
            word+="${BASH_REMATCH[0]}"
            rest="${rest#"${BASH_REMATCH[0]}"}"
            continue
          fi
          char="${rest:0:1}"
          if [ "$char" = '\' ]; then
            if [ ${#rest} -ge 2 ]; then
              word+="${rest:1:1}"
              rest="${rest:2}"
            else
              rest=""
            fi
            continue
          fi
          if [ "$char" = '"' ]; then
            rest="${rest:1}"
            break
          fi
          if [ "$char" = '$' ]; then
            if [ "${rest:1:1}" = '(' ]; then
              if [ "${rest:2:1}" = '(' ]; then skip_arithmetic; else take_paren; fi
            else
              word+='$'
              rest="${rest:1}"
            fi
            continue
          fi
          take_backtick
        done ;;
      '$')
        if [ "${rest:1:1}" = '(' ]; then
          if [ "${rest:2:1}" = '(' ]; then skip_arithmetic; else take_paren; fi
        else
          # A run of '$' that starts no substitution is ordinary text; take it whole so a
          # command full of them costs one step, not one per character.
          [[ $rest =~ ^[$]+ ]]
          run="${BASH_REMATCH[0]}"
          if [ "${rest:${#run}:1}" = '(' ]; then
            run="${run:1}"
          fi
          word+="$run"
          have=1
          rest="${rest:${#run}}"
        fi ;;
      '`') take_backtick ;;
      '(')
        flush_word
        KIND+=(o)
        TEXT+=('(')
        rest="${rest:1}" ;;
      ')')
        flush_word
        KIND+=(o)
        TEXT+=(')')
        rest="${rest:1}" ;;
      '|')
        flush_word
        case "${rest:1:1}" in
          '|') KIND+=(o); TEXT+=('||'); rest="${rest:2}" ;;
          '&') KIND+=(o); TEXT+=('|&'); rest="${rest:2}" ;;
          *) KIND+=(o); TEXT+=('|'); rest="${rest:1}" ;;
        esac ;;
      '&')
        flush_word
        case "${rest:1:1}" in
          '&') KIND+=(o); TEXT+=('&&'); rest="${rest:2}" ;;
          '>')
            if [ "${rest:2:1}" = '>' ]; then rest="${rest:3}"; else rest="${rest:2}"; fi
            KIND+=(r); TEXT+=('&>') ;;
          *) KIND+=(o); TEXT+=('&'); rest="${rest:1}" ;;
        esac ;;
      ';')
        flush_word
        if [ "${rest:1:1}" = ';' ]; then rest="${rest:2}"; else rest="${rest:1}"; fi
        KIND+=(o)
        TEXT+=(';') ;;
      '<')
        if [ "${rest:1:1}" = '(' ]; then
          take_paren
          continue
        fi
        if [ "${rest:1:2}" = '<<' ]; then
          rest="${rest:3}"
          KIND+=(h); TEXT+=('<<<')
          continue
        fi
        if [ "${rest:1:1}" = '<' ]; then
          rest="${rest:2}"
          [ "${rest:0:1}" = '-' ] && rest="${rest:1}"
          flush_word
          take_heredoc_delimiter
          continue
        fi
        if [ "${rest:1:1}" = '&' ]; then
          rest="${rest:2}"
          KIND+=(x); TEXT+=('<&')
          continue
        fi
        flush_word
        rest="${rest:1}"
        KIND+=(x); TEXT+=('<') ;;
      '>')
        if [ "${rest:1:1}" = '(' ]; then
          take_paren
          continue
        fi
        # A word of digits directly before '>' is a file descriptor, not an argument.
        if [ $have -eq 1 ] && [[ $word =~ ^[0-9]+$ ]]; then
          word=""
          have=0
        fi
        flush_word
        case "${rest:1:1}" in
          '>') rest="${rest:2}"; KIND+=(r); TEXT+=('>>') ;;
          '|') rest="${rest:2}"; KIND+=(r); TEXT+=('>|') ;;
          '&') rest="${rest:2}"; KIND+=(x); TEXT+=('>&') ;;
          *) rest="${rest:1}"; KIND+=(r); TEXT+=('>') ;;
        esac ;;
      *)
        word+="$char"
        have=1
        rest="${rest:1}" ;;
    esac
  done
  flush_word
}

# --- normalizing one segment --------------------------------------------------------------------

strip_wrappers() {
  # Drop leading `VAR=` assignments, the shell's own reserved words, and the wrappers that
  # hide the real program. A reserved word is a word like any other, so without this
  # `if true; then git push; fi` would dispatch on `then` and match no rule at all.
  local head
  while [ ${#a[@]} -gt 0 ]; do
    if [[ ${a[0]} =~ ^[A-Za-z_][A-Za-z0-9_]*= ]]; then
      a=(${a[@]+"${a[@]:1}"})
      continue
    fi
    head="${a[0]##*/}"
    case "$head" in
      if|then|elif|else|fi|do|done|while|until|for|select|case|esac|in|function|coproc|'!'|'{'|'}')
        a=(${a[@]+"${a[@]:1}"}) ;;
      env)
        a=(${a[@]+"${a[@]:1}"})
        while [ ${#a[@]} -gt 0 ]; do
          case "${a[0]}" in
            -S|--split-string)
              # `env -S "rm -rf /"` carries the whole command in one argument.
              [ ${#a[@]} -ge 2 ] && QUEUE+=("${a[1]}")
              a=()
              return 0 ;;
            --split-string=*)
              QUEUE+=("${a[0]#*=}")
              a=()
              return 0 ;;
            -S*)
              QUEUE+=("${a[0]#-S}")
              a=()
              return 0 ;;
            -u|--unset|-C|--chdir) a=(${a[@]+"${a[@]:2}"}) ;;
            -*) a=(${a[@]+"${a[@]:1}"}) ;;
            *=*) a=(${a[@]+"${a[@]:1}"}) ;;
            *) break ;;
          esac
        done ;;
      sudo|doas)
        a=(${a[@]+"${a[@]:1}"})
        while [ ${#a[@]} -gt 0 ]; do
          case "${a[0]}" in
            -u|-g|-p|-C|-D|-R|-T|-h|--user|--group|--prompt|--chdir) a=(${a[@]+"${a[@]:2}"}) ;;
            --) a=(${a[@]+"${a[@]:1}"}); break ;;
            -*) a=(${a[@]+"${a[@]:1}"}) ;;
            *) break ;;
          esac
        done ;;
      nice|ionice|chrt)
        a=(${a[@]+"${a[@]:1}"})
        while [ ${#a[@]} -gt 0 ]; do
          case "${a[0]}" in
            -n|-c|-p|--adjustment|--class|--priority) a=(${a[@]+"${a[@]:2}"}) ;;
            -*) a=(${a[@]+"${a[@]:1}"}) ;;
            *) break ;;
          esac
        done ;;
      xargs)
        a=(${a[@]+"${a[@]:1}"})
        while [ ${#a[@]} -gt 0 ]; do
          case "${a[0]}" in
            -n|-L|-P|-I|-i|-s|-d|-E|-a|--max-args|--max-procs|--replace|--delimiter|--arg-file|--max-lines) a=(${a[@]+"${a[@]:2}"}) ;;
            -*) a=(${a[@]+"${a[@]:1}"}) ;;
            *) break ;;
          esac
        done ;;
      timeout)
        a=(${a[@]+"${a[@]:1}"})
        while [ ${#a[@]} -gt 0 ]; do
          case "${a[0]}" in
            -s|-k|--signal|--kill-after) a=(${a[@]+"${a[@]:2}"}) ;;
            -*) a=(${a[@]+"${a[@]:1}"}) ;;
            *) break ;;
          esac
        done
        [ ${#a[@]} -gt 0 ] && a=(${a[@]+"${a[@]:1}"}) ;;
      flock)
        a=(${a[@]+"${a[@]:1}"})
        while [ ${#a[@]} -gt 0 ]; do
          case "${a[0]}" in
            -w|-E|--timeout|--conflict-exit-code) a=(${a[@]+"${a[@]:2}"}) ;;
            -*) a=(${a[@]+"${a[@]:1}"}) ;;
            *) break ;;
          esac
        done
        [ ${#a[@]} -gt 0 ] && a=(${a[@]+"${a[@]:1}"}) ;;
      command|builtin)
        # `command -v rm` asks where rm is; it runs nothing.
        if has_arg "-v" ${a[@]+"${a[@]}"} || has_arg "-V" ${a[@]+"${a[@]}"}; then
          a=()
          return 0
        fi
        a=(${a[@]+"${a[@]:1}"})
        while [ ${#a[@]} -gt 0 ]; do
          case "${a[0]}" in
            -*) a=(${a[@]+"${a[@]:1}"}) ;;
            *) break ;;
          esac
        done ;;
      nohup|stdbuf|time|exec|setsid|unbuffer)
        a=(${a[@]+"${a[@]:1}"})
        while [ ${#a[@]} -gt 0 ]; do
          case "${a[0]}" in
            -*) a=(${a[@]+"${a[@]:1}"}) ;;
            *) break ;;
          esac
        done ;;
      watch)
        a=(${a[@]+"${a[@]:1}"})
        while [ ${#a[@]} -gt 0 ]; do
          case "${a[0]}" in
            -n|-d|--interval) a=(${a[@]+"${a[@]:2}"}) ;;
            -*) a=(${a[@]+"${a[@]:1}"}) ;;
            *) break ;;
          esac
        done
        if [ ${#a[@]} -gt 0 ]; then
          QUEUE+=("${a[*]}")
          a=()
        fi
        return 0 ;;
      eval)
        # `eval` takes its command as data; re-lex the joined arguments as a command.
        a=(${a[@]+"${a[@]:1}"})
        if [ ${#a[@]} -gt 0 ]; then
          QUEUE+=("${a[*]}")
          a=()
        fi
        return 0 ;;
      *) return 0 ;;
    esac
  done
}

has_arg() {
  local wanted="$1" item
  shift
  for item in "$@"; do
    [ "$item" = "$wanted" ] && return 0
  done
  return 1
}

has_abbrev() {
  # git's parse-options accepts any unambiguous abbreviation of a long option, so
  # `git reset --har` is `--hard`. Match "--" plus any non-empty prefix of the name.
  local full="$1" item given
  shift
  for item in "$@"; do
    case "$item" in
      --*)
        given="${item%%=*}"
        given="${given#--}"
        [ -n "$given" ] || continue
        case "$full" in "$given"*) return 0 ;; esac ;;
    esac
  done
  return 1
}

has_short() {
  # A short flag cluster containing one of the letters in $1 (`-fd` holds f and d).
  local letters="$1" item index letter
  shift
  for item in "$@"; do
    case "$item" in
      --*|-) continue ;;
      -*) ;;
      *) continue ;;
    esac
    for ((index = 0; index < ${#letters}; index++)); do
      letter="${letters:index:1}"
      case "${item#-}" in *"$letter"*) return 0 ;; esac
    done
  done
  return 1
}

# --- one rule per program -------------------------------------------------------------------------

git_reads_only() {
  case "$1" in
    log|status|diff|show|rev-parse|rev-list|ls-files|ls-tree|ls-remote|cat-file|describe|blame|shortlog|grep|whatchanged|reflog|var|symbolic-ref|name-rev|for-each-ref|count-objects|check-ignore|diff-tree|diff-index|show-ref|version|help)
      return 0 ;;
  esac
  return 1
}

rule_git() {
  local index=0 sub="" dir="" item
  local -a tail=()
  while [ $index -lt ${#args[@]} ]; do
    case "${args[index]}" in
      -C) dir="${args[index+1]:-}"; index=$((index + 2)) ;;
      -c|--git-dir|--work-tree|--namespace|--exec-path|--config-env) index=$((index + 2)) ;;
      -*) index=$((index + 1)) ;;
      *) sub="${args[index]}"; tail=(${args[@]+"${args[@]:index+1}"}); break ;;
    esac
  done
  # A read-only `git -C <elsewhere> log` is how a worker reads the main checkout, which
  # the launch shares with --add-dir; only a writing subcommand needs the directory checked.
  if [ -n "$dir" ] && ! git_reads_only "$sub"; then
    check_write_target "$dir" "the git -C directory"
  fi
  case "$sub" in
    push|send-pack)
      deny "git $sub is a push, and pushing is on the irreversible list: a worker commits on its branch and the conductor integrates. Blocked (spelling: git ${args[*]})." ;;
    reset)
      if has_abbrev hard ${tail[@]+"${tail[@]}"}; then
        deny "git reset --hard discards committed work and is on the irreversible list. Use git reset --soft or git revert."
      fi ;;
    clean)
      if has_short fF ${tail[@]+"${tail[@]}"} || has_abbrev force ${tail[@]+"${tail[@]}"}; then
        deny "git clean with a force flag deletes untracked files and is on the irreversible list."
      fi ;;
    branch)
      for item in ${tail[@]+"${tail[@]}"}; do
        case "$item" in
          --*) ;;
          -*D*) deny "git branch $item force-deletes a branch and is on the irreversible list." ;;
        esac
      done
      if has_short d ${tail[@]+"${tail[@]}"} || has_abbrev delete ${tail[@]+"${tail[@]}"}; then
        if has_short f ${tail[@]+"${tail[@]}"} || has_abbrev force ${tail[@]+"${tail[@]}"}; then
          deny "git branch deleting with a force flag is the same as -D and is on the irreversible list."
        fi
      fi ;;
    worktree)
      case "${tail[0]:-}" in
        remove|prune) deny "git worktree ${tail[0]} removes a worktree the conductor owns; it is on the irreversible list." ;;
      esac ;;
    subtree)
      if has_arg "push" ${tail[@]+"${tail[@]}"}; then
        deny "git subtree push is a push; it is on the irreversible list."
      fi ;;
  esac
}

rule_rm() {
  local item endopts=0 recursive=0
  local -a targets=()
  for item in ${args[@]+"${args[@]}"}; do
    if [ $endopts -eq 0 ]; then
      case "$item" in
        --) endopts=1; continue ;;
        --recursive|--dir) recursive=1; continue ;;
        --help|--version) return 0 ;;
        --*) continue ;;
        -*) case "$item" in *r*|*R*) recursive=1 ;; esac; continue ;;
      esac
    fi
    targets+=("$item")
  done
  if [ ${#targets[@]} -eq 0 ]; then
    deny "$prog names no target, so its targets come from stdin (an xargs pipeline, say) where the guard cannot see them. Name the paths to delete."
  fi
  for item in "${targets[@]}"; do
    [ -z "$item" ] && continue
    if [ $recursive -eq 1 ]; then
      check_delete_target "$item" "the recursive $prog target"
    else
      check_delete_target "$item" "the $prog target"
    fi
  done
}

rule_find() {
  local index program
  for ((index = 0; index < ${#args[@]}; index++)); do
    case "${args[index]}" in
      -delete)
        deny "find ... -delete deletes every match; deleting files is on the irreversible list." ;;
      -exec|-execdir|-ok|-okdir)
        program="${args[index+1]:-}"
        case "${program##*/}" in
          rm|shred|truncate|dd|chmod|chown|mv|unlink)
            deny "find ... ${args[index]} ${program} runs a destructive command on every match; it is on the irreversible list." ;;
        esac ;;
      -fprint|-fprintf|-fls)
        check_write_target "${args[index+1]:-}" "the find output file" ;;
    esac
  done
}

rule_chmod() {
  local item endopts=0
  for item in ${args[@]+"${args[@]}"}; do
    if [ $endopts -eq 0 ]; then
      case "$item" in
        --) endopts=1; continue ;;
        --recursive) deny "$prog --recursive changes a whole tree and is on the irreversible list." ;;
        --*) continue ;;
        -*R*) deny "$prog $item changes a whole tree and is on the irreversible list." ;;
        -*) continue ;;
      esac
    fi
    case "$item" in
      [0-7][0-7][0-7]|[0-7][0-7][0-7][0-7]|[ugoa]*[-+=]*|[-+=]*) continue ;;
    esac
    check_write_target "$item" "the $prog target"
  done
}

rule_dd() {
  local item
  for item in ${args[@]+"${args[@]}"}; do
    case "$item" in
      of=*) check_write_target "${item#of=}" "the dd output file (of=)" ;;
    esac
  done
}

rule_curl() {
  local index item method
  for ((index = 0; index < ${#args[@]}; index++)); do
    item="${args[index]}"
    case "$item" in
      --data*|--form*|--upload-file*|--json*|--body-data*)
        deny "curl ${item%%=*} uploads data; a network write is on the irreversible list. Fetching sources is the scout's job, in code." ;;
      --request|--request=*|-X*)
        case "$item" in
          --request) method="${args[index+1]:-}" ;;
          --request=*) method="${item#--request=}" ;;
          -X) method="${args[index+1]:-}" ;;
          *) method="${item#-X}" ;;
        esac
        case "$method" in
          POST|PUT|DELETE|PATCH|post|put|delete|patch)
            deny "curl $item $method is a network write; it is on the irreversible list." ;;
        esac ;;
      -o|--output) check_write_target "${args[index+1]:-}" "the curl output file" ;;
      --*) ;;
      -*)
        # A short cluster carrying an upload flag: -T, -d, -F (and -XPOST above).
        if has_short dFT "$item"; then
          deny "curl $item carries an upload flag; a network write is on the irreversible list."
        fi ;;
    esac
  done
}

rule_wget() {
  local index item method
  for ((index = 0; index < ${#args[@]}; index++)); do
    item="${args[index]}"
    case "$item" in
      --post-data*|--post-file*|--body-data*|--body-file*)
        deny "wget ${item%%=*} uploads data; a network write is on the irreversible list." ;;
      --method|--method=*)
        case "$item" in
          --method) method="${args[index+1]:-}" ;;
          *) method="${item#--method=}" ;;
        esac
        case "$method" in
          POST|PUT|DELETE|PATCH|post|put|delete|patch)
            deny "wget --method $method is a network write; it is on the irreversible list." ;;
        esac ;;
      -O|--output-document) check_write_target "${args[index+1]:-}" "the wget output file" ;;
      -P|--directory-prefix) check_write_target "${args[index+1]:-}" "the wget output directory" ;;
    esac
  done
}

rule_pip() {
  local item
  for item in ${args[@]+"${args[@]}"}; do
    case "$item" in
      -*) continue ;;
      upload) deny "pip upload publishes a package; a network write is on the irreversible list." ;;
      *) return 0 ;;
    esac
  done
}

rule_python() {
  local index
  for ((index = 0; index < ${#args[@]}; index++)); do
    case "${args[index]}" in
      -m)
        case "${args[index+1]:-}" in
          twine) deny "python -m twine publishes a package; a network write is on the irreversible list." ;;
          pip|pip3)
            args=(${args[@]+"${args[@]:index+2}"})
            rule_pip ;;
        esac
        return 0 ;;
      -*) ;;
      *) return 0 ;;
    esac
  done
}

rule_packager() {
  # uv, uvx, pipx, poetry and hatch are other spellings of twine and pip upload.
  local item previous=""
  for item in ${args[@]+"${args[@]}"}; do
    case "$item" in
      twine) deny "$prog $item publishes a package; a network write is on the irreversible list." ;;
      publish) deny "$prog publish uploads a package; a network write is on the irreversible list." ;;
      upload)
        if [ "$previous" = "pip" ]; then
          deny "$prog pip upload publishes a package; a network write is on the irreversible list."
        fi ;;
    esac
    previous="$item"
  done
}

rule_gh() {
  # A worker never creates, pushes to, edits, or deletes anything on GitHub; code does
  # that (ticket 73). `pr` and `release` are denied whole; every other group allows only
  # its read verbs; `gh api` allows only a GET (a body without a method makes it a POST).
  local item index group="" verb="" method="" body=""
  for item in ${args[@]+"${args[@]}"}; do
    case "$item" in
      -*) continue ;;
    esac
    if [ -z "$group" ]; then group="$item"; else verb="$item"; break; fi
  done
  case "$group" in
    "") return 0 ;;
    pr|release) deny "gh $group writes to GitHub; a network write is on the irreversible list. The owner opens the pull request." ;;
    api) ;;
    search|status|browse|help|version|completion) return 0 ;;
    *)
      case "$verb" in
        ""|list|view|status|diff|checks|watch|download) return 0 ;;
      esac
      deny "gh $group $verb writes to GitHub, or may; a worker makes no change on GitHub, code does." ;;
  esac
  for ((index = 0; index < ${#args[@]}; index++)); do
    case "${args[index]}" in
      -X|--method) method="${args[index+1]:-}" ;;
      --method=*) method="${args[index]#--method=}" ;;
      -X*) method="${args[index]#-X}" ;;
      -f|-F|--field|--raw-field|--input|--field=*|--raw-field=*|--input=*|-f*|-F*) body="${args[index]}" ;;
    esac
  done
  case "$method" in
    ""|GET|get|HEAD|head) ;;
    *) deny "gh api with $method writes to GitHub; a network write is on the irreversible list." ;;
  esac
  if [ -n "$body" ] && [ -z "$method" ]; then
    deny "gh api with $body sends a body, which makes it a POST that writes to GitHub; a network write is on the irreversible list."
  fi
  return 0
}

rule_cd() {
  # The guard resolves every relative path against the worktree root. A `cd` that leaves
  # the worktree would make that base wrong, so `cd /etc && rm -rf build` would look like
  # a deletion inside the touch set while deleting something else.
  local item target="" abs
  for item in ${args[@]+"${args[@]}"}; do
    case "$item" in
      -*) continue ;;
    esac
    target="$item"
    break
  done
  if [ -z "$target" ]; then
    deny "$prog with no directory goes home, outside the worktree; the guard resolves later relative paths against the worktree ($ROOT), so it could not check them. Stay in the worktree."
  fi
  if [ "$target" = "-" ]; then
    deny "$prog - returns to a directory the guard did not see; it resolves later relative paths against the worktree ($ROOT), so it could not check them. Name the directory."
  fi
  if ! abs=$(resolve "$target"); then
    deny "$prog '$target' hides its directory behind $(hidden_by "$target"); the guard cannot resolve it, and every later relative path with it."
  fi
  if ! under "$abs" "$ROOT"; then
    deny "$prog '$target' leaves the worktree ($ROOT) for $abs; the guard resolves later relative paths against the worktree, so it could not check them."
  fi
}

rule_extract() {
  # An archive extracted outside the worktree is a write outside the worktree.
  local index
  for ((index = 0; index < ${#args[@]}; index++)); do
    case "${args[index]}" in
      -C|--directory|--target-directory) check_write_target "${args[index+1]:-}" "the $prog output directory" ;;
      --directory=*|--target-directory=*) check_write_target "${args[index]#*=}" "the $prog output directory" ;;
      -d)
        if [ "$prog" = unzip ]; then
          check_write_target "${args[index+1]:-}" "the $prog output directory"
        fi ;;
    esac
  done
}

rule_rsync() {
  local item deletes=0
  local -a positional=()
  for item in ${args[@]+"${args[@]}"}; do
    case "$item" in
      --delete*) deletes=1; continue ;;
      -*) continue ;;
    esac
    positional+=("$item")
  done
  [ ${#positional[@]} -gt 0 ] || return 0
  local destination="${positional[${#positional[@]}-1]}"
  case "$destination" in
    *:*)
      deny "rsync to '$destination' writes to another host; a network write is on the irreversible list." ;;
  esac
  if [ $deletes -eq 1 ]; then
    check_delete_target "$destination" "the rsync --delete destination"
  else
    check_write_target "$destination" "the rsync destination"
  fi
}

rule_write_args() {
  local item endopts=0
  local -a targets=()
  for item in ${args[@]+"${args[@]}"}; do
    if [ $endopts -eq 0 ]; then
      case "$item" in
        --) endopts=1; continue ;;
        -*) continue ;;
      esac
    fi
    targets+=("$item")
  done
  [ ${#targets[@]} -gt 0 ] || return 0
  case "$prog" in
    cp|install|ln)
      check_write_target "${targets[${#targets[@]}-1]}" "the $prog destination" ;;
    *)
      for item in "${targets[@]}"; do
        check_write_target "$item" "the $prog target"
      done ;;
  esac
}

rule_sed() {
  local item inplace=0 scripted=0 endopts=0
  local -a targets=()
  for item in ${args[@]+"${args[@]}"}; do
    if [ $endopts -eq 0 ]; then
      case "$item" in
        --) endopts=1; continue ;;
        --in-place|--in-place=*) inplace=1; continue ;;
        -e|-f|--expression|--file|--expression=*|--file=*) scripted=1; continue ;;
        --*) continue ;;
        -*i*) inplace=1; continue ;;
        -*) continue ;;
      esac
    fi
    targets+=("$item")
  done
  [ $inplace -eq 1 ] || return 0
  # Without -e or -f the first positional argument is the script, not a file. It often
  # holds a '$' anchor, which would otherwise read as an unresolvable path.
  if [ $scripted -eq 0 ] && [ ${#targets[@]} -gt 0 ]; then
    targets=(${targets[@]+"${targets[@]:1}"})
  fi
  for item in ${targets[@]+"${targets[@]}"}; do
    check_write_target "$item" "the sed -i target"
  done
}

check_segment() {
  [ $# -gt 0 ] || return 0
  local -a a=("$@")
  strip_wrappers
  [ ${#a[@]} -gt 0 ] || return 0

  local prog="${a[0]##*/}"
  local index body

  case "$prog" in
    sh|bash|zsh|dash|ksh|mksh|ash)
      index=1
      while [ $index -lt ${#a[@]} ]; do
        case "${a[index]}" in
          --*) index=$((index + 1)) ;;
          -*c*)
            if [ $((index + 1)) -lt ${#a[@]} ]; then
              QUEUE+=("${a[index+1]}")
            fi
            return 0 ;;
          -*) index=$((index + 1)) ;;
          *) break ;;
        esac
      done
      # No -c: the shell reads its commands from somewhere. A here-string or a heredoc is
      # text the guard has; a pipe is text it does not.
      if [ -n "$HERESTRING" ]; then
        QUEUE+=("$HERESTRING")
      fi
      for body in ${HEREDOC_BODIES[@]+"${HEREDOC_BODIES[@]}"}; do
        QUEUE+=("$body")
      done
      if [ "${PIPED:-0}" = 1 ]; then
        deny "a pipe into $prog hides the command it runs; the guard cannot check it. Run the command directly."
      fi ;;
  esac

  local -a args=(${a[@]+"${a[@]:1}"})

  case "$prog" in
    git) rule_git ;;
    rm|shred|unlink) rule_rm ;;
    find) rule_find ;;
    chmod|chown|chgrp) rule_chmod ;;
    truncate) deny "truncate rewrites a file in place and is on the irreversible list." ;;
    dd) rule_dd ;;
    curl) rule_curl ;;
    wget) rule_wget ;;
    twine) deny "twine publishes a package; a network write is on the irreversible list." ;;
    pip|pip3) rule_pip ;;
    python|python3|python3.12|python3.13) rule_python ;;
    uv|uvx|pipx|poetry|hatch|flit) rule_packager ;;
    gh) rule_gh ;;
    mv|cp|install|ln|tee|touch|mkdir|rmdir|patch) rule_write_args ;;
    rsync) rule_rsync ;;
    tar|unzip|bsdtar) rule_extract ;;
    cd|pushd) rule_cd ;;
    sed) rule_sed ;;
  esac
}

analyse() {
  lex "$1"
  local -a words=()
  local index kind text mode=""
  PIPED=0
  HERESTRING=""
  for ((index = 0; index < ${#KIND[@]}; index++)); do
    kind="${KIND[index]}"
    text="${TEXT[index]}"
    case "$kind" in
      w)
        case "$mode" in
          write) check_write_target "$text" "the redirection target"; mode="" ;;
          here) HERESTRING="$text"; mode="" ;;
          skip) mode="" ;;
          *) words+=("$text") ;;
        esac ;;
      r) mode=write ;;
      h) mode=here ;;
      x) mode=skip ;;
      o)
        check_segment ${words[@]+"${words[@]}"}
        words=()
        mode=""
        HERESTRING=""
        # The next segment reads this one's stdout, so its input is invisible here.
        case "$text" in
          '|'|'|&') PIPED=1 ;;
          *) PIPED=0 ;;
        esac ;;
    esac
  done
  check_segment ${words[@]+"${words[@]}"}
}

UNITS=0
while [ ${#QUEUE[@]} -gt 0 ]; do
  CURRENT="${QUEUE[0]}"
  QUEUE=(${QUEUE[@]+"${QUEUE[@]:1}"})
  UNITS=$((UNITS + 1))
  if [ $UNITS -gt $MAX_UNITS ]; then
    deny "the command nests more than $MAX_UNITS sub-commands; that is too much to analyse, so it is blocked. Run the steps separately."
  fi
  [ -n "$CURRENT" ] && analyse "$CURRENT"
done

exit 0
