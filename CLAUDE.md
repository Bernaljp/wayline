# Wayline

`CONTEXT.md` is the glossary: write code, comments, tickets, and reports in its terms. The spec is `.scratch/wayline/spec.md`; the tickets are `.scratch/wayline/issues/NN-slug.md`, each mirrored by the GitHub issue on its `GitHub:` line.

## Starting a ticket

A GitHub issue number is not the ticket number, and the two are close enough to be mistaken for each other. Never open a ticket file because its name carries the number you were given. Look the issue up, whether you were handed a URL, a bare number, or a title:

```
grep -l "issues/7)" .scratch/wayline/issues/*.md
```

Open the file that command names, and read its `GitHub:` line back to confirm it is the issue you were asked for. One file, one issue: no match, or more than one, is a question for the owner rather than a guess.

Then, before the first edit, say which ticket you are on: the file path and its whole `# NN - Title` line. Follow it with the line that names this session after the ticket, for the owner to paste, since only they can run it:

```
/rename 06 - M0 live: one trivial ticket end to end
```

The owner runs several implement sessions at once, so a session named after its ticket is how the right one is found again in `/resume`, and how a session working the wrong ticket is caught in the first minute rather than at the pull request.

## Finishing a ticket

`/implement` commits a ticket on a `worktree-*` branch. The owner reads and merges it on GitHub, so finish every ticket with a pull request:

1. In the ticket file, tick each acceptance criterion you verified and set `**Status:** done`. A criterion you could not verify stays unticked and is named in the pull request body.
2. Commit that, then push the branch: `git push -u origin HEAD`.
3. Open the pull request against `master`: the title is the ticket's `# NN - Title` line; the body opens with `Closes #<issue>` (the number on the ticket's `GitHub:` line), then what was built, how it was verified, and any unticked criterion.
4. End your report with the pull request URL.

The suite is `python -m unittest` from the repository root. It passes before the pull request is opened, and GitHub runs it again on the pull request.
