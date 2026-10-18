# 73 - The guard and gitignore defects found while charting

**What to build:** Four defects the living paper map found in v1.0.1 are fixed before anything is built on them.

- **The touch-set hook denies every `research/` path.** Decision 1 always said so, but only the planner's check refused one: a worker whose touch set named a `research/` path could still write there. The hook now denies any path under `research/` whatever the touch set, so sections, reports, and the ledger are written only by code.
- **Tickets filed by gates and by proposals are checked as the planner's are.** A scope-down a gate files or a ticket a proposal admits goes through the same touch-set check, so none can name `research/` either.
- **The command guard denies `gh repo create` and every other `gh` write.** A worker never creates, pushes to, edits, or deletes anything on GitHub; code does that (85). Read-only `gh` calls stay allowed where they are today.
- **`absorb --code`'s clone is gitignored.** The clone under `research/refs/*/code/` is ignored like `source/`, so the wave commit stops recording it as an empty gitlink.

Not part of this ticket:

- the code repository's own pushes, which code makes outside any worker (85);
- a project's own clone absorbed into `code/` with its history (85).

**Blocked by:** None - can start immediately. Every module it edits is built. It blocks 85.

**Status:** ready-for-agent

**GitHub:** PENDING

**Milestone:** M8 A paper that grows with the work (v1.1.0). **Spec:** Implementation Decision 17 (defects found while charting; sections and passages, "sections never enter a touch set"; Methods and the code, the worker guard), 1 (the layout, the touch-set rule), 4 (guards and permissions); M8 criteria 4 (the hook clause) and 13 (the worker guard clause); user stories 116, 148.

- [ ] The touch-set hook denies a write to any path under `research/`, including when the ticket's touch set names it.
- [ ] Tickets filed by gates (scope-downs) and admitted from proposals are checked by the same rule as the planner's, and one naming `research/` is refused with the reason.
- [ ] The command guard denies `gh repo create` and every `gh` subcommand that writes (repo, pr, issue, release, api with a write method, and the like), and still allows the read-only forms used today.
- [ ] `absorb --code` writes the clone's path into the project's `.gitignore` beside `source/`, and a wave commit after an absorb records no gitlink.
- [ ] Tests as piped-stdin hook cases with expected exit codes, following the pattern of the existing guard tests: a `research/` write inside and outside the touch set, `gh repo create`, a `gh` write, a `gh` read; a gate-filed and a proposal-admitted ticket naming `research/`; an absorb followed by a wave commit over a temporary project.
- [ ] The changelog names the fixes under `## Unreleased`.
- [ ] `python -m unittest` passes.
