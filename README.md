# wayline

wayline is a research harness built on Claude Code. You say what you want to find out, in a conversation, and it runs
the research as a project on your own machine: it plans the work as tickets, writes and runs the code and the
experiments, has every result checked by sessions that never saw how it was made, and writes a report and, when you
order one, a paper in which every number is traced to the result that produced it. Deterministic Python (standard
library only) decides what runs, when, on which resources, and what counts as done; models decide only content. It
runs on a Claude Code subscription.

**See it run.** [The showcase](https://bernaljp.github.io/wayline/) is wayline's own dashboard over a real run on a toy
question, read-only: an hour's setup conversation, an autonomous run through the night, and a compiled paper the next
afternoon. It is rebuilt from this repository's interface whenever the interface changes. [What that run was, and what
it got wrong](showcase/README.md).

## What it does for a researcher

- **Starts from where you are.** A direction and a pile of references, a precise plan with half an implementation, or a
  project midway with its own drafts and data: references are absorbed to the depth they deserve, the idea is
  positioned against the literature, and what a project inherits is verified before anything builds on it.
- **Objectives and goals.** You record questions as objectives; a goal adds a measure and a target, chased by
  keep-if-better. The run ends by the stopping rule you choose at setup (no objective open, the ones it names closed,
  or no work left), within the budgets you set.
- **As involved as you want.** Three autonomies: `interactive` (you answer each decision), `checkpoints` (decision
  tickets reach you as they open), and `autonomous` (everything is asked during setup, then the decider answers what is
  not yours alone, and you get the end notice). A decision ticket pauses only the work that depends on it.
- **Checked results.** Each ticket's work gets a verdict from a fresh session that never saw the author's context;
  claims are sampled and their numbers checked against the result files; a kill argument is run against the report
  before it stands. Failed work climbs a ladder ordered by token cost: resume, split, a stronger model, and only then
  you.
- **Reports, then a paper.** The general report (`REPORT.md`) and each result's current report are rendered by code
  from the ledger, with plots drawn for each result. A paper order composes a venue-free paper from five sections,
  gates each build, and compiles it for a venue (PDF, Word, LaTeX).
- **An account of what was decided for you.** `research/ACCOUNT.md` lists every decision the decider took on your
  behalf, with its reason, until you review it.
- **A dashboard and a chat.** Five views (Research, Paper, Inherited, Run, Marks) and a chat where you talk with the
  project, reachable from a phone through an SSH tunnel.
- **It improves itself.** What you say should have gone better becomes change records and harness tickets, tested and
  versioned, local to the project first.

## How it is built

- **Code decides, models write.** The conductor (`wayline/conductor.py`) launches Claude Code sessions headless, each
  with a role, a rung (model and effort), and a JSON schema for what it returns; tickets in a dependency graph run in
  waves by touch set and by the machine's GPU and CPU slots, and every event lands in an append-only journal.
- **Roles.** Planner, coder, experimenter, analyst, verifier, critic, decider, surveyor, consultant, plotter, figure
  designer and critic, writer, and evolver among them (`roles/`), each a prompt and a contract for what it returns.
- **Provenance.** Every number in a report or the paper carries a `{res:…}` tag to the result file it came from, and a
  linter flags a sentence that states one without it.
- **Paced by the subscription.** The tick relaunches work after usage windows; pacing steps down the rung ladder as a
  window runs out, and Fable's work falls back to Opus while Fable's weekly window is spent.
- **Small and tested.** Python 3.12 with no third-party packages, about 5,000 unit tests, and browser tests of the
  dashboard on CI.

## How it was made

Spec first, by the owner with Claude Code: a brief (`BRIEF.md`), design questions charted as maps of issues and
resolved one session at a time, a spec (`.scratch/wayline/spec.md`), and tickets (`.scratch/wayline/issues/`, mirrored
as GitHub issues), each implemented in its own Claude Code session and merged as a pull request. Each milestone ends in
a live run, recorded under `docs/verification/`.

## Honest limits

- The release the showcase ran on, v1.1.0, is not tagged yet: its last ticket is a live run on a real project.
- The showcase's run needed a stand-in for the owner, and it found sixteen things wrong with wayline, now tickets 125 to
  140; its paper compiled but did not pass its own gates. [The showcase's notes](showcase/README.md) say what happened.
- One workstation, Linux, a Claude Code subscription, and one active project at a time.

## Using it

- The user guide: [docs/guide/index.md](docs/guide/index.md). The brief: `BRIEF.md`. The glossary: `CONTEXT.md`. The spec: `.scratch/wayline/spec.md`. The tickets: `.scratch/wayline/issues/`, mirrored to GitHub issues.
- Run it: `bin/wayline --help` or `python -m wayline --help` from this directory. Python 3.12, no third-party packages.
- Test it: `python -m unittest` from this directory.
- Versions: one tag per global change, listed in `CHANGELOG.md`; a project pins the tag in its `harness.json`.

Layout (Implementation Decisions 1): `wayline/` is the package, `schemas/` the JSON Schema documents, `policy.json` the global defaults, `templates/project/` what `wayline init` lays down, `fixtures/` the recorded inputs the tests read, `tests/` the unit suite with the schema examples under `tests/examples/`, and `showcase/` the public showcase and its snapshot.

A project: `wayline init <path>` lays one out and makes it active, `wayline objective add "<question>"` records an objective (a goal with `--measure <file> --sample <artifact>`) in `research/objectives.json`, `wayline status` prints the objectives' statuses, the frontier, and the last events, `wayline switch <path>` moves the machine's pointer. The per-machine pointers live in `~/.wayline/`, which `WAYLINE_HOME` moves.

## License

MIT, in `LICENSE`. Third-party files keep their own licenses: the dashboard's vendored libraries (marked, DOMPurify,
and KaTeX; `dashboard/vendor/VENDOR.md` names each license) and the citation styles under `guidelines/` (CC BY-SA 3.0).
