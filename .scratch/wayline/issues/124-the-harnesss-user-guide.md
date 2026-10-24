# 124 - The harness's user guide

**What to build:** A user guide for wayline itself, written once the features of v1.1.0 exist, so that it describes what was built rather than what was planned. It takes the place of the "documentation site" that 32 of the M8 tickets named in a criterion. Wayline has no documentation site: the site ticket 51 builds documents a project's own package. On 2026-10-18 the owner chose one guide written at the end over a site that every ticket keeps current, which would have had parallel tickets editing the same pages and rewriting them as later tickets changed the features.

The guide is Markdown under `docs/guide/`, readable on GitHub with no site generator, with an index page linked from the repository's `README.md`. It is written for the owner and for someone new to wayline, in the glossary's words (`CONTEXT.md`), and it takes its facts from the code, from `CHANGELOG.md`'s `## Unreleased` section, from Implementation Decision 17 in `.scratch/wayline/spec.md`, and from the M8 tickets, never from memory. One page per topic:

- getting started: installing wayline and its tools (`wayline tools install`, `wayline tools show`, `wayline tools run`), `wayline init`, and reaching the dashboard through the tunnel;
- talking with a project: the dashboard's chat, a Claude Code session in the project, how to start `claude remote-control` (no unit is installed for it), and what is asked at setup under each autonomy;
- objectives and goals: how one is recorded, proposed, changed, answered, parked, or set aside, and keep-if-better with the stopping rule and the budgets;
- starting midway: documents, critiques and concerns, inherited passages, repeated claims, and verifying what a project inherited;
- the research: results, the general and current reports, drawings and plots, and switching the plotting library;
- the paper: the five sections and their passages, editing a section, consolidation, the outline, references (the scout's outcomes and retries, handing a reference over, and `wayline scout` for workers), Methods and the code repository, and the paper order with its builds and compilations;
- the run: the account, the marks view, the dashboard's views and actions, and what each autonomy does after setup;
- software and environments: harness tools, project tools and packages, licensed software, and moving a project's environment;
- upgrading: `research_version`, why a project made on v1.0.x is refused, and the two ways on.

Not part of this ticket:

- a generated or hosted site;
- the documentation site ticket 51 builds for a project's own package, which is unchanged.

**Blocked by:**
- 99 - The surveyor and lit tickets
- 113 - Dashboard: editing sections and the outline
- 114 - The dashboard's chat
- 120 - The decider orders the paper under autonomous
- 121 - Dashboard: cards and new actions

Through them, every ticket from 71 to 121. It blocks 122.

**Status:** done

**GitHub:** [#282](https://github.com/Bernaljp/wayline/issues/282) (mirror; the local file is the source)

**Milestone:** M8 A paper that grows with the work (v1.1.0). **Spec:** none names this guide: it is the owner's reading of the "documentation site" the M8 tickets named, chosen on 2026-10-18 and recorded in `.scratch/wayline/waves.md`; the M8 tickets whose documentation-site criteria it replaces.

- [x] `docs/guide/` holds one page per topic above and an index page that links them all; the repository's `README.md` links the index.
- [x] A test reads every `wayline <verb>` the guide quotes and checks that the verb is in `cli.VERBS`, so a renamed or removed verb fails the suite instead of leaving the guide wrong.
- [x] Every flag, file path, and setting the guide names exists in the code at the commit the guide is written on.
- [x] The guide uses the glossary's words and none of the glossary's _Avoid_ words in their avoided sense.
- [x] Each page says what happens under `interactive`, `checkpoints`, and `autonomous` wherever the three differ.
- [x] `CHANGELOG.md` under `## Unreleased` names the guide.
- [ ] `python3 -m unittest` passes.
