# Wayline

`CONTEXT.md` is the glossary: write code, comments, tickets, and reports in its terms. The spec is `.scratch/wayline/spec.md`; the tickets are `.scratch/wayline/issues/NN-slug.md`, each mirrored by the GitHub issue on its `GitHub:` line.

## Finishing a ticket

`/implement` commits a ticket on a `worktree-*` branch. The owner reads and merges it on GitHub, so finish every ticket with a pull request:

1. In the ticket file, tick each acceptance criterion you verified and set `**Status:** done`. A criterion you could not verify stays unticked and is named in the pull request body.
2. Commit that, then push the branch: `git push -u origin HEAD`.
3. Open the pull request against `master`: the title is the ticket's `# NN - Title` line; the body opens with `Closes #<issue>` (the number on the ticket's `GitHub:` line), then what was built, how it was verified, and any unticked criterion.
4. End your report with the pull request URL.

The suite is `python -m unittest` from the repository root. It passes before the pull request is opened, and GitHub runs it again on the pull request.
