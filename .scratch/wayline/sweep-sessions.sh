#!/bin/bash
# Remove the ended background sessions of this repository whose worktree branch is merged into
# origin/master, with their worktrees and local branches. Everything else is kept and named:
# a session still working, a branch not yet merged, a detached worktree. `claude rm` itself keeps
# a worktree that holds uncommitted changes or unpushed commits and prints the flag that discards them.
set -u
root=$(git rev-parse --show-toplevel) || exit 1
cd "$root" || exit 1
git fetch -q --prune origin || { echo "fetch failed; nothing removed"; exit 1; }

claude agents --json --all | python3 -c '
import json, sys
root = sys.argv[1] + "/.claude/worktrees/"
for r in json.load(sys.stdin):
    cwd = r.get("cwd", "")
    if cwd.startswith(root):
        print(r["id"], r.get("state", "?"), cwd, r.get("name", ""))
' "$root" | while read -r id state cwd name; do
    if [ "$state" = "working" ]; then
        echo "kept $id ($name): still working"
        continue
    fi
    if [ ! -d "$cwd" ]; then
        claude rm "$id"          # the worktree is already gone; drop the session record
        continue
    fi
    branch=$(git -C "$cwd" branch --show-current)
    if [ -z "$branch" ]; then
        echo "kept $id ($name): detached HEAD in $cwd"
        continue
    fi
    if git merge-base --is-ancestor "$branch" origin/master; then
        claude rm "$id"
    else
        echo "kept $id ($name): $branch is not merged into origin/master"
    fi
done
