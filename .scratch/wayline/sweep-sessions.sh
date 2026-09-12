#!/bin/bash
# Remove the worktrees under .claude/worktrees whose pull request is merged, with their sessions and
# local branches.
#
# A worktree goes only when all of these hold: its branch's pull request is merged on GitHub, the
# branch has no commit that origin/master lacks, nothing in it is uncommitted, no session in it is
# busy, and no other program runs in it. An idle session goes with its worktree, and so does a
# worktree no session is left in (an interactive `claude -w` that ended). A session is tied to its
# worktree by the worktreePath its job record keeps, because a session started at the repository
# root reports the root as its directory once it has ended. Every worktree kept is named with the
# reason; a session with no worktree, such as one just started, is never touched.
#
# usage: sweep-sessions.sh [--dry-run]    (--dry-run prints what would be removed, and removes nothing)
set -u
dry=0
[ "${1:-}" = "--dry-run" ] && dry=1
act() {
    if [ "$dry" = 1 ]; then echo "  would run: $*"; else "$@"; fi
}
root=$(git rev-parse --show-toplevel) || exit 1
cd "$root" || exit 1
git fetch -q --prune origin || { echo "fetch failed; nothing removed"; exit 1; }
merged=$(gh pr list --state merged --limit 1000 --json headRefName --jq '.[].headRefName') \
    || { echo "gh failed; nothing removed"; exit 1; }

# One line per session tied to a worktree of this repository: id, status, pid, worktree path.
sessions=$(claude agents --json --all | python3 -c '
import json, os, sys
root = sys.argv[1] + "/.claude/worktrees/"
for row in json.load(sys.stdin):
    path = None
    try:
        with open(os.path.expanduser("~/.claude/jobs/%s/state.json" % row["id"])) as handle:
            path = json.load(handle).get("worktreePath")
    except (OSError, ValueError, KeyError):
        pass
    cwd = row.get("cwd") or ""
    if not path and cwd.startswith(root):
        path = root + cwd[len(root):].split("/")[0]
    if path and path.startswith(root):
        print(row["id"], row.get("status") or "ended", row.get("pid") or 0, path)
' "$root") || { echo "could not read the sessions; nothing removed"; exit 1; }

# An ended session whose worktree is already gone leaves only its record.
while read -r id status pid path; do
    [ -n "$id" ] || continue
    if [ ! -d "$path" ] && [ "$status" = "ended" ]; then
        echo "removing session $id: its worktree ${path##*/} is gone"
        act claude rm "$id"
    fi
done <<< "$sessions"

while IFS=$'\t' read -r path ref lock; do
    name=${path##*/}
    branch=${ref#refs/heads/}
    ids=$(awk -v p="$path" '$4 == p { print $1 }' <<< "$sessions")
    pids=$(awk -v p="$path" '$4 == p { print $3 }' <<< "$sessions")
    busy=$(awk -v p="$path" '$4 == p && $2 == "busy" { printf "%s ", $1 }' <<< "$sessions")
    if [ -n "$busy" ]; then echo "kept $name: session ${busy% } is busy"; continue; fi
    if [ -z "$branch" ]; then echo "kept $name: detached HEAD"; continue; fi
    if ! grep -qxF "$branch" <<< "$merged"; then echo "kept $name: $branch has no merged pull request"; continue; fi
    if ! git merge-base --is-ancestor "$branch" origin/master; then echo "kept $name: $branch has commits that origin/master lacks"; continue; fi
    if [ -n "$(git -C "$path" status --porcelain)" ]; then echo "kept $name: uncommitted changes"; continue; fi
    others=""
    for proc in /proc/[0-9]*; do
        cwd=$(readlink "$proc/cwd" 2>/dev/null) || continue
        case "$cwd" in
            "$path"|"$path"/*) grep -qx "${proc#/proc/}" <<< "$pids" || others="$others ${proc#/proc/}" ;;
        esac
    done
    if [ -n "$others" ]; then echo "kept $name: a program runs in it (pid$others)"; continue; fi
    if [ -n "$ids" ]; then
        echo "removing $name with its session $(echo $ids)"
        for id in $ids; do act claude rm "$id"; done
        [ "$dry" = 1 ] && continue
    fi
    [ -d "$path" ] || continue
    # No session is left to remove the worktree, or `claude rm` kept it: remove it with git.
    lock_pid=$(sed -n 's/.*(pid \([0-9]*\).*/\1/p' <<< "$lock")
    if [ -n "$lock" ]; then
        if [ -n "$lock_pid" ] && [ -d "/proc/$lock_pid" ]; then echo "kept $name: locked by live process $lock_pid"; continue; fi
        act git worktree unlock "$path"
    fi
    echo "removing $name with git"
    act git worktree remove "$path" && act git branch -D "$branch"
done < <(git worktree list --porcelain | awk -v prefix="$root/.claude/worktrees/" '
    function flush() { if (path != "" && index(path, prefix) == 1) print path "\t" branch "\t" lock; path = ""; branch = ""; lock = "" }
    /^worktree / { flush(); path = substr($0, 10) }
    /^branch / { branch = substr($0, 8) }
    /^locked/ { lock = ($0 == "locked") ? "locked" : substr($0, 8) }
    END { flush() }
')
