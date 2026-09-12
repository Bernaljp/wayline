#!/bin/bash
# Bring the oldest open pull request up to master, so that it can be merged on GitHub.
#
# Several pull requests open at once collide on the same lines (the SHIPPED list of the schema
# tests, the changelog's Unreleased section, the verb table), so every merge on GitHub re-conflicts
# the rest. The owner merges pull requests oldest first, the lowest number. After each merge, this
# script takes the lowest-numbered open pull request, merges origin/master into its branch in a
# temporary worktree, and pushes. A conflict that was resolved before is resolved the same way again
# by git rerere, from the resolutions recorded in this repository's .git/rr-cache; one with no
# recorded resolution is left for a person: the merge is dropped and the files are named.
set -u
root=$(git rev-parse --show-toplevel) || exit 1
cd "$root" || exit 1
git config rerere.enabled true
git config rerere.autoUpdate true
git fetch -q --prune origin || { echo "fetch failed; nothing done"; exit 1; }

read -r number branch < <(gh pr list --state open --base master --json number,headRefName \
    --jq 'sort_by(.number) | .[0] | "\(.number) \(.headRefName)"')
if [ -z "${number:-}" ]; then
    echo "no open pull request"
    exit 0
fi
if git merge-base --is-ancestor origin/master "origin/$branch"; then
    echo "#$number ($branch) already holds origin/master: merge it on GitHub"
    exit 0
fi

tmp=$(mktemp -d "${TMPDIR:-/tmp}/wayline-pr-XXXXXX")
trap 'git worktree remove --force "$tmp" >/dev/null 2>&1; rm -rf "$tmp"' EXIT
git worktree add -q --detach "$tmp" "origin/$branch" || exit 1
message="Merge branch 'master' into $branch"
if git -C "$tmp" merge -q --no-edit -m "$message" origin/master >/dev/null 2>&1; then
    echo "#$number ($branch): merged origin/master, no conflicts"
else
    unresolved=$(git -C "$tmp" diff --name-only --diff-filter=U)
    if [ -n "$unresolved" ]; then
        git -C "$tmp" merge --abort
        echo "#$number ($branch): conflicts with no recorded resolution, left for a person:"
        echo "$unresolved" | sed 's/^/  /'
        exit 1
    fi
    git -C "$tmp" commit -q -m "$message

Conflicts resolved the way they were resolved before (git rerere)." || exit 1
    echo "#$number ($branch): merged origin/master, conflicts resolved from the recorded resolutions"
fi
git -C "$tmp" push -q origin "HEAD:refs/heads/$branch" || exit 1
echo "pushed; wait for the tests check on #$number, then merge it on GitHub"
