# 85 - The code repository

**What to build:** Everything a project publishes lives under `code/`: the package or scripts, the tests, the environment locks, `README.md`, and `LICENSE`. Code cuts the **code repository** from `code/` with `git subtree split --prefix=code`, which never includes `research/`, `harness.json`, `jobs/`, or `results/`. Code then keeps a private GitHub copy up to date. Code tickets' touch sets go under `code/`. The project stays one working repository.

Intake absorbs a project's own clone into `code/` with its history. It runs `git subtree add --prefix=code <clone> <recorded commit>`, commits uncommitted changes as the next commit (named as such), and keeps the clone's `.git` outside the tree. It records the upstream remote, the commit, and the inherited license. This fixes the empty gitlink that a nested clone left in the wave commit. Code from someone else's paper stays `absorb --code`, a reference.

The repository's shape is settled by one setup question, together with its remote, visibility, and license. There are two shapes:

- **A package** holding the developed method and every model the work applies it to, each callable from the package. A method with its own maintained package (SINDy through pysindy) is a pinned dependency, never copied.
- **A reproducibility repository** of scripts, helpers, and the environment alone.

The harness creates the remote with `gh`, through the tool runner:

- by default, a new private repository;
- for a taken-over repository that is not the owner's, a new private repository carrying the upstream history, never a fork, since forks of public repositories stay public;
- the owner's own repository, when the owner says wayline can take it over, confirmed once if it is public.

Code pushes `code/`'s split after every wave that changed it. A worker never pushes, and the worker guard already denies `gh repo create` (ticket 73). Making the repository public is the owner's word only, at setup or later. Making it public, and every other visibility change, is on the irreversible list.

Every job and every ticket run records the commit of `main` it ran at, on `job_launched` and `ticket_launched`, so a result can be traced to the code that made it.

Not part of this ticket:

- `REPRODUCE.md`, `reproduce.json`, the locks, and the rendered `README.md` (106);
- the rule from code to Methods (107);
- the `paper-N` tag and its push at the order (119);
- the "make it public" confirmation card on the dashboard (121);
- the repository's line in the Paper view (111).

**Blocked by:** 73 - The guard and gitignore defects found while charting; 78 - The synthetic start-midway project. It blocks 97, 106, 107, 109, 111, and 121.

**Status:** ready-for-agent

**GitHub:** [#232](https://github.com/Bernaljp/wayline/issues/232) (mirror; the local file is the source)

**Milestone:** M8 A paper that grows with the work (v1.1.0). **Spec:** Implementation Decision 17 ("Methods and the code": the code repository, intake's absorption, the private push, public on the owner's word; "Setup, at every autonomy": the code repository's question; "Vocabulary the build adds": `harness.json` gaining the code repository's record, the commit on `job_launched` and `ticket_launched`); decisions 1 (`harness.json`; the layout: `code/`), 2 (the event table: the commit on `job_launched` and `ticket_launched`), 4 (the irreversible list: making the repository public), 10 (intake); M8 criterion 13; user stories 148, 149, 175.

- [ ] Intake absorbs a project's own clone into `code/` with `git subtree add --prefix=code <clone> <recorded commit>`. Uncommitted changes become the next commit, named as such. The clone's `.git` stays outside the tree, and the upstream remote, the commit, and the inherited license are recorded. The synthetic start-midway project's repository arrives with its history and no gitlink.
- [ ] Code tickets' touch sets go under `code/`, and the planner's check refuses a code ticket whose touch set leaves it.
- [ ] `git subtree split --prefix=code` cuts the code repository, which never contains `research/`, `harness.json`, `jobs/`, or `results/`.
- [ ] One setup question settles the shape (package or reproducibility repository), the remote, the visibility, and the license, recorded in `harness.json`.
- [ ] Code creates a new private GitHub repository with `gh` through the tool runner. A taken-over repository that is not the owner's gets a new private repository carrying its upstream history, never a fork. The owner's own repository is used as the remote only on their word, confirmed once if it is public.
- [ ] Code pushes `code/`'s split after every wave that changed it, and never otherwise. No worker pushes.
- [ ] Making the repository public is on the irreversible list and runs only on the owner's word.
- [ ] `job_launched` and `ticket_launched` carry the commit of `main` each ran at.
- [ ] Tests:
  - the tool runner's recordings of `git subtree add`, `git subtree split`, `gh repo create --private`, and the push;
  - a temporary project absorbing the synthetic repository;
  - a replayed journal with a wave that changed `code/` and one that did not.
- [ ] The event table of decision 2 and the `harness.json` schema gain these rows in the same commit as the code that writes them.
- [ ] The documentation site and `CHANGELOG.md` under `## Unreleased` describe `code/` and the code repository.
- [ ] `python -m unittest` passes.
