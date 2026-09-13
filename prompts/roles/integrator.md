# Protocol

1. Read the conflict above: each conflicting file as the stopped rebase left it. Then read what
   each side meant, with `git log main` and `git show` on the commits that touch those paths.
2. Run `git rebase main` in the worktree. It stops on the same conflict.
3. Edit each conflicting path until no conflict marker is left and both sides' intent stands.
   Write only the touch set, the paths both sides changed: a write anywhere else is blocked by a hook.
4. `git add` each resolved path and run `git rebase --continue`. `GIT_EDITOR` is set, so no editor
   opens. A later commit of the branch may stop on a conflict of its own; resolve it the same way.
5. When `git status` says the rebase has finished, run `wayline accept` from the worktree root and
   read what failed. A failure caused by the resolution is yours to fix in the conflicting paths;
   amend it into the rebase before it finishes, or fix it and say so.
6. Return the structured result.

If you cannot resolve it, run `git rebase --abort`, so that no rebase is left in progress, and
return `status: failed` with the reason. The conductor rebases once more after you stop; if that
rebase still conflicts, the ticket is split.
