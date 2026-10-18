# 83 - Moving a project's environment

**What to build:** The owner can move a project to another environment at any time by saying so, and its results do not change. `harness.json.environment` is one of:

- `shared` (the default: the tools in `~/.wayline/tools/` and the project's own packages);
- `conda` (one prefix at `<project>/.wayline/env`);
- `venv`;
- `container` (one Singularity image at `<project>/.wayline/env.sif`).

The image is built without root through a sandbox from `docker://` and micromamba, as the research note measured, with Docker used only where the account reaches it.

A move always goes in three steps:

1. Code builds the new environment from the locks ticket 82 writes.
2. Code runs each recorded tool's version check inside it.
3. Only when every check passes does the project switch.

A failed build or check leaves the project where it was and says why. Past results stand. MATLAB stays bound in from the host, and the decider never sets the environment. While a move is in progress, jobs keep running in the old environment. Every job and tool run launched after the switch runs inside the new one: `wayline job add` and `wayline tools run` resolve the tool through the environment.

The verb is `wayline switch --environment shared|conda|venv|container`, accepted with a conductor running or not, written to `harness.json` first and then journaled as a `control` event. The conversation calls it when the owner says so. It has no dashboard action of its own: the Run view shows the setting and a move in progress (ticket 110).

Not part of this ticket:

- the environment file and the Dockerfile the paper order writes into `code/` (119);
- installing the tools themselves (75, 82).

**Blocked by:** 82 - Project tools and the software decision. It blocks 110.

**Status:** ready-for-agent

**GitHub:** PENDING

**Milestone:** M8 A paper that grows with the work (v1.1.0). **Spec:** Implementation Decision 17 ("Tools, packages, and environments": **Environment**; "Vocabulary the build adds": `switch --environment`, `harness.json` gaining `environment`); decisions 1 (the verb table: `switch --environment`; `harness.json`), 2 (the event table: the `control` command), 6 (jobs run inside the environment); M8 criterion 14; user story 156.

- [ ] `harness.json.environment` is in the schema with `shared`, `conda`, `venv`, and `container`. A project without the key behaves as `shared`.
- [ ] `wayline switch --environment <value>` builds the new environment from the locks, runs each recorded tool's version check inside it, and only then writes `harness.json` and journals `control`. A failed build or check changes nothing and prints the failing step.
- [ ] `conda` builds one prefix at `<project>/.wayline/env`. `venv` builds a project venv through uv. `container` builds `<project>/.wayline/env.sif` without root through a Singularity sandbox from `docker://` and micromamba. Docker is used only where the account reaches it.
- [ ] After the switch, `wayline job add` and `wayline tools run` resolve each tool inside the new environment (inside the image for `container`). MATLAB stays bound in from the host. A job launched before the switch finishes where it started.
- [ ] The decider never sets `environment`, and the setting is not among the decider's classes.
- [ ] A rootless Singularity build and one tool's version check inside it run live on this workstation, recorded in `docs/verification/m8.md` with the commands and timings.
- [ ] Tests:
  - the tool runner's recordings for a conda build, a venv build, a Singularity sandbox build, and the version checks;
  - a temporary project for a refused move and a switch;
  - a replayed journal for a job launched across the switch.
- [ ] The verb table of decision 1, the `control` enumeration of the event table, and the `harness.json` schema gain these rows in the same commit as the code.
- [ ] The documentation site and `CHANGELOG.md` under `## Unreleased` describe the four environments and how a move is checked.
- [ ] `python -m unittest` passes.
