# 82 - Project tools and the software decision

**What to build:** A project gets the software its work needs without the owner hunting for it, and one missing program holds only the tickets that need it. Decision 17 names four kinds of software. Ticket 75 builds the harness's own tools. This ticket builds the other three on top of that record:

- **A project's tools** (Octave, R, Julia, or what a plotting setting needs) install after a yes, through the routes 75 set up and never with root. That means micromamba from conda-forge with one prefix per tool, and Julia from its tarball. Every download is checked against its published digest.
- **A project's packages** go into the project's own environment with no ask: `<project>/.venv` through uv, an R library with `renv.lock`, a Julia environment, or Octave Forge in the shared prefix unless two projects disagree. Each is gitignored and locked under `code/`.
- **Licensed software** (MATLAB and its toolboxes) stays the owner's alone. The owner installs it and says where it is. Code records it with `installer: owner` and reads the version and toolboxes from `ver`. It then runs one `matlab -batch "ver"` check job, and a failure keeps the decision open.

A ticket names its tools (`software: ["octave"]`, set by specify, the planner, or the critic), and it is not launchable until every one of them is recorded in `tools.json`. A job spec names a tool (`"tool": "octave"`), and `wayline job add` writes that tool's absolute executable and environment into the job's `command` and `env`. A session calls `wayline tools run <name> -- <args>` for short calls. Each job record carries the name, version, and lock digest of every tool it called.

The ask is a decision ticket of the new class `software`, one per tool, pausing only the tickets that need that tool. It states:

- the route;
- the download and disk sizes from a dry run;
- the tickets waiting;
- the cost.

Its options are Install (recommended), Not now, and Go without. Each ask is also an item in the batch record of ticket 79, so the marks view and the conversation can settle it, approve or decline, and the first answer wins.

Who answers depends on the autonomy:

- Under `interactive` and `checkpoints`, the owner answers.
- Under `autonomous`, the setup question lists every tool the planned work needs. Afterward the decider answers: it installs free software through these routes, and it never changes an installed tool or the tools venv and never touches licensed software.

A failed install is retried once, then becomes the same decision carrying the error. A gap found mid-ticket (an installed tool lacking what the code needs) ends the worker `blocked` with the gap in `blocked_on`, and code opens the decision. Installing free software is neither irreversible nor a global harness change; changing what is already installed is the owner's word only.

Not part of this ticket:

- the harness's own tools, `tools.json`'s entry shape and merge, `tools show`, and `tools run` itself (75);
- moving a project to `conda`, `venv`, or `container` (83);
- the locks rendered into `REPRODUCE.md` and the code repository (106);
- the plotting library switch, which asks through this decision (102);
- the setup conversation's order of questions (109).

**Blocked by:** 75 - The harness's tools; 79 - Batches and marks. It blocks 83, 102, 106, 109, 110, and 112.

**Status:** ready-for-agent

**GitHub:** [#229](https://github.com/Bernaljp/wayline/issues/229) (mirror; the local file is the source)

**Milestone:** M8 A paper that grows with the work (v1.1.0). **Spec:** Implementation Decision 17 ("Tools, packages, and environments"; "Vocabulary the build adds": the decision class `software`, `ticket` and `plan` gaining `software`, the tools each job called); decisions 1 (the verb table: `tools install <name>` for a project's tool, `tools run`), 2 (the event table: the tools on each job record), 6 (jobs: the job spec's `tool`), 10 (the decider's classes), the schemas list (`ticket`, `plan`, the job record); M8 criterion 14; user stories 153, 154, 155.

- [ ] A project's tool (Octave, R, Julia) installs through `wayline tools install <name>` only after a yes, through micromamba from conda-forge (Julia from its tarball), into one prefix per tool under `~/.wayline/tools/`, its download checked against its published digest, and recorded in `tools.json` with its absolute executable, version, required environment, route, lock or digest, install time, and `installer: harness`.
- [ ] A project's packages install into its own environment with no ask: Python through uv into `<project>/.venv`, R into a project library with `renv.lock`, Julia into a project environment, and Octave Forge into the shared prefix unless two projects disagree. Each is gitignored and locked under `code/`.
- [ ] Licensed software is never installed by code. The owner says where MATLAB is, code records it with `installer: owner` and the version and toolboxes `ver` reports, and one `matlab -batch "ver"` check job runs. A failing check keeps the decision open.
- [ ] `ticket` and `plan` gain `software`. A ticket whose tools are not all recorded is not launchable and opens one `software` decision ticket per missing tool, which pauses only the tickets that need that tool.
- [ ] A job spec may name `"tool"`. `wayline job add` writes the tool's absolute executable and environment into `command` and `env`, and each job record carries the name, version, and lock digest of every tool it called.
- [ ] The `software` decision states the route, the download and disk sizes from a dry run, the tickets waiting, and the cost, with Install (recommended), Not now, and Go without. It is also an item in the batch record of ticket 79, so a mark settles it.
- [ ] Under `interactive` and `checkpoints` the owner answers it. Under `autonomous` the decider answers it after setup: it installs free software through these routes and never changes an installed tool, the tools venv, or licensed software.
- [ ] A failed install is retried once, then the decision reopens with the error. A worker that finds an installed tool lacking what its code needs ends `blocked` with the gap in `blocked_on`, and code opens the decision.
- [ ] Installing free software is on neither the irreversible list nor the global harness changes, and changing an installed tool is refused to everyone but the owner's word.
- [ ] Tests:
  - the tool runner's recordings for micromamba and uv installs and for `matlab -batch "ver"`;
  - a temporary project for `software` launchability, the job spec's `tool`, and the job record's tools;
  - replayed journals for a `software` decision holding only its tickets under each autonomy, a retried install, and a `blocked_on` gap, idempotence included.
- [ ] The verb table of decision 1, the event table of decision 2, the decider's classes, and the schemas list gain these rows in the same commit as the code that writes them.
- [ ] `CHANGELOG.md` under `## Unreleased` describes project tools, packages, licensed software, and the `software` decision.
- [ ] `python -m unittest` passes.
