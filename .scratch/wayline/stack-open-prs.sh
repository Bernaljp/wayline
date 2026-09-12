#!/bin/bash
# Stack the open pull requests, so that they merge on GitHub one after another without conflicts.
#
# Every ticket appends to the same lines (the SHIPPED list of the schema tests, the changelog's
# Unreleased section, the verb table), so pull requests open at the same time conflict with each
# other as soon as one of them is merged. This script merges origin/master into the lowest-numbered
# open pull request, then that result into the next one, and so on, pushing every branch it
# changes. Each pull request then holds master and every open pull request numbered below it, so
# merging them in number order never conflicts; merging a later one first lands the earlier ones
# with it. A draft pull request is left out of the stack.
#
# A conflict resolved before is resolved the same way again by git rerere, from the resolutions
# recorded in this clone's .git/rr-cache. At the first conflict with no recorded resolution the
# script stops and names the files; the pull requests below it are already pushed. Resolve that
# merge by hand (git rerere records the resolution), push, and run the script again.
set -u
root=$(git rev-parse --show-toplevel) || exit 1
cd "$root" || exit 1
git config rerere.enabled true
git config rerere.autoUpdate true
git fetch -q --prune origin || { echo "fetch failed; nothing done"; exit 1; }

open=$(gh pr list --state open --base master --json number,headRefName,isDraft \
    --jq 'map(select(.isDraft | not)) | sort_by(.number) | .[] | "\(.number) \(.headRefName)"') \
    || { echo "gh failed; nothing done"; exit 1; }
if [ -z "$open" ]; then
    echo "no open pull request"
    exit 0
fi

tmp=""
trap '[ -n "$tmp" ] && { git worktree remove --force "$tmp" >/dev/null 2>&1; rm -rf "$tmp"; }' EXIT
below=$(git rev-parse origin/master)
below_name="master"
while read -r number branch; do
    head=$(git rev-parse "origin/$branch") || exit 1
    # A branch that already holds everything below it is left as it is.
    if tree=$(git merge-tree --write-tree "$head" "$below" 2>/dev/null) \
        && [ "$(echo "$tree" | head -1)" = "$(git rev-parse "$head^{tree}")" ]; then
        echo "#$number ($branch): already holds $below_name"
        below=$head
        below_name="#$number"
        continue
    fi
    if [ "$below_name" = "master" ]; then
        message="Merge branch 'master' into $branch"
    else
        message="Merge master and the pull requests up to $below_name into $branch"
    fi
    tmp=$(mktemp -d "${TMPDIR:-/tmp}/wayline-stack-XXXXXX")
    git worktree add -q --detach "$tmp" "$head" || exit 1
    if git -C "$tmp" merge -q --no-edit -m "$message" "$below" >/dev/null 2>&1; then
        echo "#$number ($branch): merged $below_name, no conflicts"
    else
        unresolved=$(git -C "$tmp" diff --name-only --diff-filter=U)
        if [ -n "$unresolved" ]; then
            git -C "$tmp" merge --abort
            echo "#$number ($branch): conflicts with $below_name that have no recorded resolution:"
            echo "$unresolved" | sed 's/^/  /'
            echo "stopped; merge $below into $branch by hand, push, and run this again"
            exit 1
        fi
        git -C "$tmp" commit -q -m "$message

Conflicts resolved the way they were resolved before (git rerere)." || exit 1
        echo "#$number ($branch): merged $below_name, conflicts resolved from the recorded resolutions"
    fi
    git -C "$tmp" push -q origin "HEAD:refs/heads/$branch" || exit 1
    below=$(git -C "$tmp" rev-parse HEAD)
    below_name="#$number"
    git worktree remove --force "$tmp"
    rm -rf "$tmp"
    tmp=""
done <<< "$open"
echo "stacked; merge the pull requests in number order, each once its tests check is green"
