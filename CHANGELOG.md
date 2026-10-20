# Changelog

One entry per tag. `wayline upgrade` prints the entries between two tags. A release that raises `research_version`
(`wayline.RESEARCH_VERSION`, how `research/` is kept) opens its entry with a **Breaking** line: `wayline upgrade` to it
refuses a project made before it, which keeps its old tag or starts again on the new release.

## v1.0.1 (2026-09-28)

- `REPORT.md` gets a second draft (ticket 67; Implementation Decisions 11). When the provenance linter fails on
  sentences the writer wrote, `wayline report` resumes the same writer session with the list, each sentence and
  why (an `untagged_claim` said to be the classifier's reading), and lints the new draft, at most
  `paper.MAX_BUILDS` drafts in all; a draft that still fails is written with today's banner. The prose cache
  (`research/.cache/report_prose.json`) records the linter's result beside the prose, so a render that may launch
  redrafts cached prose that failed rather than reusing it; `--offline`, `--no-draft`, and the tick launch
  nothing and render what the cache holds. An `unclassified` sentence is not sent back: a redraft cannot close it.

- No bytecode in a touch set (ticket 69; Implementation Decisions 3, 5). Every launch request carries
  `PYTHONDONTWRITEBYTECODE=1` beside `CLAUDE_CODE_DISABLE_LEGACY_MODEL_REMAP` unless its `env` names the variable,
  and the conductor's check for work left uncommitted ignores untracked `__pycache__/` and `*.pyc` inside the touch
  set as it does untracked files outside it.

- A tier up carries the last failure (ticket 68; Implementation Decisions 5 and 16). The fresh session a tier up
  opens gets a `# The last failure` section in its prompt: the failure output of the attempt before it, the text
  its resume was given, so after a failed verdict the verdict's type, its model, and its findings. The conductor
  keeps it in the attempt's `failure.json`, so a restart that relaunches the attempt says it again. In 51's live
  run the tier up had started from the ticket alone, found the earlier work on `main` passing, and returned `done`
  with no diff.

## Unreleased

**Breaking:** `research_version` 2 (Implementation Decision 17). A project made on v1.0.x is refused, never migrated:
`wayline upgrade` to this release changes nothing and names the two ways on (`wayline upgrade --to v1.0.1`, or a new
project from the old one's materials), every verb that writes to it refuses with the same message, and the dashboard
lists it read-only, marked with its tag.

- `research_version` in `harness.json` (ticket 72): absent is 1, `wayline init` writes `wayline.RESEARCH_VERSION`
  (2). A small upgrade, within one `research_version`, works as before, both ways.

- Critiques and concerns (ticket 96; Implementation Decisions 17, 2, and 10). A critique's points, an open Word
  comment thread, and an objection of the position memo's hostile review the owner accepts at the grill become
  concerns: `research/concerns.json` (schema `concern`, ids K1 onward, never reused), written only by
  `wayline.concerns` through the ledger, journaled as `concern`, and rendered as `research/CONCERNS.md`. Each records
  its sources (the critique, the locator, the verbatim words), the inherited claims it targets, its place (tied to
  objectives, for the paper order, or declined), and its status (`open`, `answered`, or `declined`, with the answer or
  the reason). `wayline concern split`, and `wayline position` before the critic runs, launch one
  `critique-splitter` session (Sonnet at medium, no tools, schema `concern_split`) per batch of critiques not split
  yet: code keeps a source only when its words are in that critique and locates it at its block, keeps only targets
  among the inherited claims standing now, and merges near-identical points from different critiques with every
  source. The critic reads `DOCUMENTS.md` and every concern, its tools reach `research/documents/`, and its memo
  proposes a place for each concern waiting (`position` gains `concerns`); the proposals form one
  `concern_placements` batch, and the grill asks, each human-only, one question per proposed objective with its
  concerns, one for the order, one for the declines (`take it` or `another place`), and one per objection of the
  hostile review (`reject`, or an accept with where it goes), then one for each concern no question placed. Specify
  refuses to draft during setup while a concern is unsorted;
  `wayline concern place <id> --objective <O> | --order | --decline "<reason>"` sorts one as the owner. Code answers
  a concern once its tied objectives are answered and its targets replaced or withdrawn, follows a reframe to the
  successor, and sends a concern back to be sorted when its objective drops. After setup, each concern that needs
  sorting is a decision ticket of class `concern` (pausing no work): the owner's, or under `autonomous` the
  decider's, which ties it, keeps it for the order, or declines it with a reason, and adds a new objective only once
  the owner took `objective` off the human-only classes; `concern` may be named human-only at intake. Specify, the
  decider, the planner, and the writer read `DOCUMENTS.md` and `CONCERNS.md`, and a worker's context pack carries the
  open concerns of its ticket's objectives.

- The stopping rule, the budgets, and keep-if-better per goal; `GOAL.json` retires (ticket 87; Implementation
  Decision 17). `stop_when` in `harness.json` is `objectives` (the default: the run ends when no objective is open),
  a list of objective ids (when those are closed), or `frontier` (when no work is left); the conductor reads it every
  wave and journals `run_ended` with `objectives_closed`, or `goal_reached` when every objective it closed was a goal
  that reached its target. `budgets.wallclock_hours` (counted from the end of setup) and `budgets.gpu_hours` (each
  job's hours times the GPUs it held) are now read by code: spending one ends the run `budget_spent`, and the tick
  relaunches no run its rule or a spent budget ended. `wayline switch --stop-when <rule>` and `wayline switch --budget
  <name>=<hours>` write `harness.json` and journal `control`; after setup, changing the rule or raising a budget is on
  the irreversible list, and the decider is refused both. Keep-if-better runs per goal: `progress` and `discarded`
  carry `goal`, each goal's best kept value comes from its own events from its baseline, its metric, direction,
  split, and command from its measure in `objectives.json`, and a measure's own `min_seeds` overrides the policy's
  (at 1, any strict gain is kept); code writes a goal reached (`objective` answered, `by: code`). When the frontier
  empties while the rule waits on open objectives, one decision ticket per objective offers replan for it, answer it
  as it stands, park it, or drop it (a replan recommended only after progress since the last one); the owner answers
  under `interactive` and `checkpoints` while the run ends `frontier_empty`, the decider under `autonomous` in one
  session, replan or answer only. Under `stop_when: frontier` none opens and the end notice lists the open
  objectives. Nothing reads `GOAL.json` any more: the `goal` schema is gone, `harness.json.budgets` loses
  `usage_windows` (and `wayline intake` its `--usage-windows`), `wayline status` shows each goal's best kept value
  and the rule and budgets in its place, and the toy project's goal is O1 in `research/objectives.json` with
  `stop_when` in `harness.json`.

- The linter's new tags, the owner's passages, editing a section, and consolidation (ticket 88; Implementation
  Decisions 17, 1, 2, and 11).
  - **New tags.** Beside `res` and `ref`, a claim sentence may end with `{code:<path>#<symbol>}` or
    `{code:<path>#L10-L42}`, for what the project's code does (the path from the project, `code/phase.py`, or from
    inside `code/`), resolved against the ticket's worktree at its acceptance and against `main` at every render, and
    flagged once the file no longer defines the symbol or holds the lines; and `{doc:<document>#<locator>}`, inherited
    text's provenance, resolved against `research/documents.json` and never rendered as a citation. A `ref` tag may
    name its work by exact title, `{ref:title:<exact title>}` (the form ticket 93 writes for an inherited citation
    with neither a DOI nor an arXiv id): it resolves through the identifier index's titles in the linter, the claim
    verifier's paths, the guidelines check, and the acceptance check, which scouts a title no dossier holds. A tag
    just before a sentence's full stop ends it, as one after it does.
  - **The linter at acceptance and at every render.** The worktree's acceptance gains a line, "every claim sentence
    ends with a provenance tag that resolves", over the result's passages and findings: a tag that does not resolve,
    or a sentence the classifier calls a claim ending with no tag, sends the worker back. The classifier (one haiku
    batch) is asked only about the sentences ending with no tag; one it could not classify is listed, never failed,
    and a finding with no tag of its own is tagged by its provenance. Every render of a section records the linter's
    reading in `research/sections/lint.json`; before the paper order a claim tagged only `doc` and an untagged claim
    in an owner's passage are listed there, never failed. The paper's build still fails a `doc`-only claim.
  - **The owner's passages.** `wayline passage add --section <s> --heading <h> [--replaces <id>] "<text>"` records an
    owner's passage, `by: owner`, journaled `passage`; the owner may write in Results too, and replaces any passage
    without a reason. A ticket's passage or finding replacing an owner's passage must carry evidence (a `res`, `ref`,
    or `code` tag; a finding's provenance) and a `reason`, new in the result schema, or the declared-sections check
    sends the worker back; the replacement's `passage` or `finding` event carries `replaces_owner` and the reason for
    the account's "Changed without asking you", and under `interactive` the owner is notified.
  - **Editing a section file.** The owner may edit `research/sections/<section>.md` directly: before the next render
    code takes the edit in by the file's first-line render stamp. A new paragraph becomes an owner's passage under
    the heading above it (or a new `## heading` of the owner's), a changed paragraph the owner's replacement of what
    it printed, and a removed one a withdrawal; a passage that arrived since the stamp, or replaced what the owner
    removed, is never read as a deletion. The render's own notes now follow a `<!-- wayline:notes -->` line, which
    the edit is read up to.
  - **Consolidation.** `wayline consolidate <section>` rewrites a section's current passages into fewer that keep
    their tags, in one read-only writer session the owner asks for: without `--yes` it prints what the session reads,
    the model, and about how many tokens, and launches nothing. The answer is checked before anything is written
    (every current passage replaced by exactly one, fewer of them, every tag kept and none added, and the linter,
    with a tag that already failed carried rather than held against it), sent back once with the problems, and
    written `by: consolidation`, naming in `consolidates` what it rewrote, so a passage made of the owner's still
    steers; journaled as `consolidated`. The owner's pending edit is taken in first, and an inherited claim still
    unchecked is left out with its mark. It refuses inside an automated run and on Results, which is its findings.

- The rule from code to Methods (ticket 107; Implementation Decision 17). At each acceptance in the worktree, a
  Type-A check (`wayline/methods.py`) reads the ticket's diff in `code/` with parsers that spend no tokens and
  sends the worker back with the list when Methods and the code disagree: every developed method the diff adds or
  changes needs a `code` tag (`{code:code/<path>#<symbol>}` or `#L10-L42`) in a current Methods passage, the
  ticket's own included (plumbing such as private names, `load_`/`save_`/`plot_` helpers, and tests is excluded by
  code; anything else the worker lists in the new result field `not_methods`); every used method the diff adds
  that the alias table (`methods/aliases.json`) lists, such as `scipy.signal.hilbert`, must be named in a Methods
  passage by one of its aliases; and every non-default parameter it sets, every numeric default a new method gives
  itself, and every sensitive default left unset (an unseeded random state, default solver tolerances) needs a
  one-sentence reason in the new result field `parameters`, whose value and default code fills. Python is read
  with `ast`, its library defaults from `inspect.signature` run in the project's environment ("not checked", and
  not failed, until that environment is installed); MATLAB with tree-sitter-matlab in the tools venv
  (`converters/matlab_parse.py`), the documented-defaults table (`methods/defaults.json`), and backward slices,
  and the same parse fills the code dossier's new `methods` entries and a MATLAB repository's inventory; another
  language gets one Sonnet reading (the `code-reader` role, `sonnet medium`, schema `code_reading`) whose items are
  kept only when grep finds them, its usage carried on the acceptance result. The reasons and `not_methods` reach
  the ticket's `## Result` section and the verifier's existing verdict, whose schema gains `code_rule`, the
  judgment of each; one that does not hold fails the verdict, and a ticket that earned no verdict earns a read of
  its diff for them.

- References during a ticket (ticket 98; Implementation Decision 17). `wayline scout <identifier>` checks one work
  from inside a worker by its DOI, arXiv id, or exact title (a URL is refused): it files the L0 dossier at once and
  prints the slug, the details, and the abstract; on a service failure it files an unresolved dossier with the
  `retry` flag; on no such work it files nothing and exits 1. Each call is journaled as `scouted` under
  `WAYLINE_TICKET` and the call past `policy.scout.calls_per_ticket` (20) is refused; the coder, analyst,
  experimenter, and writer have the verb, and their prompts say how to cite. A result gains `references[]` of
  `{identifier, note}`. At the worktree's acceptance every cited work (each `ref` tag of the passages and findings)
  must be a dossier or listed, the scout runs free on every work neither a found dossier nor known yet (each
  listed one, and each cited by `doi:` or `arxiv:`), each note is kept on its dossier as `ticket <id>`, and a
  locator must name what the dossier holds at its level (`abstract` or `metadata.<field>`, and at L2 an entry's
  locator): no such work and a locator beyond the level send the worker back, a service failure passes with the
  flag, and an identifier tag with no locator (the inherited citation's form) passes. Lookups ask the services
  outside the ledger's lock and file under it, so two workers scouting at once never share a slug. A `ref` tag names a work by slug or by `doi:` or `arxiv:`,
  resolved through position's identifier index. A `dossier` ticket has no worker session: the conductor promotes
  the paper on the `planner_or_decider` trigger and reads it through absorb, waiting on the decision a promotion
  beyond the phase's budget opens; `proposals.KIND_ROLE` routes neither `dossier` nor `lit`.

- Inherited passages (ticket 93; Implementation Decision 17). `wayline document deconstruct D1` cuts an inherited
  document (an earlier manuscript, a separate Methods, a supplement) verbatim into inherited passages, `by:
  document:D1`, in `research/passages.jsonl`. Only text under headings the fixed table maps is taken (Introduction
  or Background; Discussion, Conclusions, or Outlook; Methods, Materials and methods, Theory, Model, or Algorithm;
  Results, and "Results and discussion" to Results); a subheading follows its parent, and any other heading is
  placed by the setup session (`--place "<heading>=<section>"`) or, with none, lands under Results as written and
  is listed in `DOCUMENTS.md`. The title, abstract, front matter, captions, back matter, availability statements,
  and reference list stay in the document's record (`deconstructed.kept`), never passages. Each claim sentence the
  classifier marks is one passage and the sentences between claims stay together, each ending with a
  `{doc:D1#p4.s2}` tag (provenance, never a citation); a pandoc citation becomes an identifier `ref` tag with no
  locator. An inherited claim stands `unchecked` until a ticket's passage or finding replaces it with `evidence`
  (`supports`, `narrows`, or `contradicts`; the acceptance check asks for it), or is found `unverifiable` with its
  reason. Results now renders from the findings and the inherited Results passages; a render rejoins a document
  paragraph's passages, each claim marked `[unchecked]`. `wayline document move P12 results` moves a separate
  document's outcome passage on the setup session's proposal, listed for the owner. A `.docx` kept without pandoc
  is not deconstructed and the reason is listed; a newer version taken in again comes in like a section edit (new
  text new passages, changed text replacements, removed text withdrawals).

- Consulting one document (ticket 94; Implementation Decision 17). `wayline consult D1 "<question>"` takes a
  document id as well as a dossier slug. The document's `text.md` is cut into chunks of whole blocks under
  `policy.absorb.chunk_max_chars` (`documents/<id>/chunks/`, listed in `chunks.json`, rebuilt when the text
  changes or a newer version is taken in), the consultant reads that directory, and its locators are block
  anchors (`p12`). The exchange goes to `documents/<id>/qa_log.md`, is journaled as `consulted` with the id in
  `slug`, and counts against the ticket's question limit. An unknown id or a document with no text is refused
  in one line.

- `REPRODUCE.md` and the locks (ticket 106; Implementation Decision 17). After a wave that changed `code/` or ran a job a
  current finding cites (or changed which runs the findings cite), and only then, code renders into `code/`:
  `REPRODUCE.md` and `reproduce.json`, which list per result each run its current findings cite with its command, the
  commit of `main` it ran at, its inputs, outputs (with SHA-256), wall-clock time, and hardware (the GPUs it held);
  `locks/<commit>/`, the package locks (`requirements.lock`, `renv.lock`, the Julia `Project.toml` and `Manifest.toml`,
  `octave-packages.lock`) as they stood at each commit a cited run ran at, not as installed now, and `locks/tools.json`,
  every tool a cited job called with the version and lock digest its job record carries; and `README.md`, rendered from
  the records, keeping word for word the owner's part between `<!-- wayline:owner -->` and `<!-- /wayline:owner -->`
  (a README with no markers, such as an absorbed clone's, becomes that part whole). The files are committed with the
  wave and go out with the code repository's next push; none names a path under `research/`, `jobs/`, or `results/`.
  A finding may name the finding it `replaces` (the worker result schema and `provenance.add_finding`); a replaced
  finding is no longer current, so its runs drop out.

- `code/` and the code repository (ticket 85; Implementation Decision 17). Everything a project publishes lives
  under `code/`: the package or scripts, the tests, the environment locks, `README.md`, and `LICENSE`. The new
  module `wayline/code_repository.py` cuts the code repository from it with `git subtree split --prefix=code`, so
  it never holds `research/`, `harness.json`, `jobs/`, or `results/`, and the project stays one working repository.
  - Intake absorbs the project's own clone, the spec's new `clone` (`--clone`), into `code/` with its history:
    `git subtree add --prefix=code <clone> <its HEAD>` on a temporary worktree of `main`, then a fast-forward. A
    repository given as `code`, `--repo`, or a loose material is one the work builds on and is still only listed,
    pinned to its commit. The clone's uncommitted changes (edits, deletions, and untracked files its `.gitignore`
    keeps) follow as the next commit, named as such; its submodules stay gitlinks; the clone itself is never
    changed. A clone that lay inside the project is moved under `.clones/` (a new `.gitignore` entry), so its
    `.git` is outside the tree, and the empty gitlink an earlier commit recorded for it is removed in a commit of
    its own; a failed absorption moves it back. `harness.json` records, under `code_repository.upstream`, the
    clone, where the owner put a nested one, its remote, the commit (SHA-1 or SHA-256), the uncommitted changes'
    commit, and the inherited license (its file and SPDX id), checked against the schema before `main` moves. An
    intake run again names the clone where it is or where the owner put it, and absorbs nothing more whatever the
    clone did since: its Code line says where `code/` began. The project itself, a repository enclosing it, and a
    second clone once `code/` holds one are refused; code from someone else's paper stays `absorb --code`.
  - One setup question, the intake spec's `code_repository` (`shape`: `package` or `reproducibility`;
    `license`, the inherited one by default; `visibility`, private by default; `remote`, a repository to take
    over; `name`; `confirm_public`), is settled by `code_repository.settle` and recorded in `harness.json`, whose
    schema gains `code_repository`. The remote is created with `gh repo create <name> --private` through the
    tool runner, never as a fork: a new private repository by default, carrying the absorbed upstream's history
    when there is one (`how: copy`). A named repository that is not the owner's gets the same private copy, which
    only the clone intake absorbed from it can carry, so any other is refused. The owner's own repository (`gh repo
    view` reports `ADMIN`, `how: owners_own`) is used only on their word, confirmed once (`confirm_public`) when it
    is public, its default branch is the one pushed (`remote.branch`), and it is refused before anything is
    recorded when that branch holds commits `code/`'s history does not descend from. `gh` joins the system tools
    `wayline tools install` records.
  - Code, never a worker, pushes `code/`'s split to the remote's branch, never forced: at setup, and at the end of
    every wave whose `main` holds a `code/` tree other than the one last pushed, which the conductor reads from the
    journal's new `code_pushed` event (`commit`, `remote`, `main`), so a restart pushes nothing twice. The split
    walks only what `main` gained since the last push, from a join commit off every branch that maps that push's
    `main` to its split, and gives the commit the whole walk gives. A push the network or a credential failed is
    said and tried again by the next wave; one the remote refused is told to the owner once (`notified`, event
    `code_push_rejected`) and that split is not pushed again.
  - Making the code repository public is the owner's word only (`code_repository.make_public(by="owner")`, at
    setup or later; `gh repo edit --visibility public` after the private push), and the decider's irreversible
    list gains the class `make the code repository public`, which also catches any other visibility change,
    `gh repo edit --visibility`, open-sourcing the code, and making it public.
  - `ticket_launched` and `job_launched` carry `commit`, the commit each ran at, so a result traces to the code
    that made it: the attempt's worktree HEAD (a later attempt's reused branch included), and for a job the HEAD
    where its working directory lies in the project or a worktree of it, else `main`'s.
  - In a project that keeps a code repository (`code/` exists, or `harness.json` records `code_repository`), a
    `code` ticket's touch set goes under `code/`: the planner's check refuses an entry outside it, and so does the
    touch-set rule a ticket admitted from a proposal is checked by.

- The guard and gitignore defects found while charting (ticket 73; Implementation Decisions 1, 4, 17). The
  touch-set hook denies every write under `research/`, whatever the touch set names. A gate's scope-down and a
  ticket admitted from a proposal are checked by the planner's touch-set rule (`tickets.touch_problem`): a
  scope-down naming `research/` raises `GateError` with the reason, and the kill argument and the paper's read now
  file theirs with no touch set; a proposal naming it is parked with reason `touches`. The command guard denies
  `gh repo create` and every other `gh` write (any group's verb but `list`, `view`, `status`, `diff`, `checks`,
  `watch`, `download`; `gh api` with a write method or a body), and still allows the reads. `absorb --code` writes
  `research/refs/*/code/` into the project's `.gitignore` beside `source/`, so a wave commit records no gitlink.

- A passing outage no longer leaves a project's references broken (ticket 71; Implementation Decision 17). Every
  lookup attempt the scout makes records `found`, `no match` (the service answered and nothing matched), or
  `failed` (an error status, a timeout, or an unreadable answer), in place of v1.0's `hit`, `miss`, and `error`;
  `scout.outcome` says `no such work` only when every service asked answered no match (`not looked up` when nothing
  could be asked, a bare URL or a PDF with no identifier). A failed attempt on a work
  not found sets the dossier's `retry` flag (service, failure, date, and the date it was first set). When arXiv's
  API fails, the scout reads the `arxiv.org/abs` page's meta tags as an attempt of its own and records the arXiv
  DOI `10.48550/arXiv.<id>`; a work found that way keeps the flag, so the API fills in the rest later. The scout's
  cache under `research/.cache/scout/` is now `fetch.AnswerCache`: it writes only successful answers and replays
  one only for a work already found, so every lookup about a work not yet found goes to the network and a failure
  an older cache kept is never replayed; the plot-gallery crawl keeps only successful answers too, and the
  suite's recordings still replay failures. A flagged reference is retried at most once a day by the next
  `absorb` or by the tick while a run is live (`dossier.retry_flagged`), and the flag gives up after
  `policy.scout.give_up_days` (7), the give-up recorded on the dossier.

  A lookup never takes back what a dossier knows: it replaces the lookup's own fields only when it finds the same
  work, keeps the level, the L1 fields, `l2`, `created`, and the node's level, sets `updated`, and journals a level
  0 `absorbed` only for a new dossier or a changed existence; a failure or a no match leaves a found dossier as it
  was, and a found dossier that now resolves to another work is left and listed under `disagreements` in absorb's
  report. One work has one dossier: a second reference to a filed work (by DOI, arXiv id, or published DOI) joins
  it under `names`, and two dossiers of one work collapse to the higher level (the older on a tie), the other a
  pointer (`joined_into`) whose notes move. Intake records references as `{identifier, note}` and never looks them
  up; `INTAKE.md` nests the note (and a PDF as `PDF: <path>`) under each top-level item, and absorb reads only
  top-level items, so a nested remark is never a query and a PDF with no identifier becomes the reference's source
  with nothing sent to any service. The owner's hand-over is the new verb `wayline reference <slug> <doi|title|file.pdf|"leave
  it">` (`dossier.hand_over`, callable in-process): a DOI or an exact title goes back to the scout, a PDF becomes the
  gitignored source and its title is tried, failing which the dossier is found with `resolved_by: owner` from the
  PDF's details, and "leave it" settles the item until the paper order. The `dossier` schema gains `retry`,
  `resolved_by: owner`, `notes`, `names`, `joined_into`, and `handed_over`; no model tokens are spent.

- A paper's figures tell the writer, not the ticket graph, what the text should say (ticket 66). A figure `wayline
  paper` asked for (`figure_request.ticket: "paper"`) files no proposal and opens no `writing` ticket: its
  `findings_for_text` go on the next build's list for the writer, each with the figure and the `manuscript_locator`
  it came from, and `build.json` keeps them under each build's `for_writer`. Each point is listed once. A build whose
  figures bring new points is followed by one that gives them to the writer, even when it failed nothing. Points
  after the last build reach the writer on `wayline paper --continue`, which takes up a draft left with unread
  points even when the gate passed it. A figure a ticket asked for still files its proposals as before. The M7 run
  had filed the toy project's `writing` tickets 70 to 81 this way while the writer was drafting that same text.
- A caption names no other figure (ticket 66). The figure designer's prompt says a caption describes its own figure,
  since cross-references between figures are the writer's, in the text. Every paper build checks each placed
  caption: one that names the id of another figure under the project's `figures/` fails the build, and the next
  build sends that figure back to the figure role as a guided revision whose one change request, `from: "paper"`
  (new in `figure_request/1`), drops the reference. A plain-word id such as `depth` counts only when the caption
  writes it as a reference, in backticks or beside the word figure. A later build asking for the same figure is
  given the revision, not a figure drawn from the start, and a revision that fails (refused, failing its checks or
  its honesty verdict) is drawn again from the figure's own request. The M7 run's build 7 had sent readers to "the
  ceiling_gap figure", a figure from an earlier draft.

- The rung ladder without Fable (ticket 70; Implementation Decisions 16, 14, and 15). The shipped ladder stops at
  Opus 5.5: its rungs 6 and 7, `fable low` and `fable high`, leave it, and `opus medium` joins between `opus low`
  and `opus high`. Difficulty 3 now starts on rung 5, `opus medium`, and difficulties 4 and 5 on rung 6, `opus
  high`, which takes the `large` budget the Fable rungs had, so hard tickets keep their turns and minutes. No
  shipped ticket work draws on Fable's weekly window, and a tier up stays on Opus up to the top rung. Why: a rung
  stays only when it sits between its neighbors on cost and quality, and Opus 5.5 dominates Fable 5.1 on both
  (research note 04). On CursorBench 4.0 Opus 5.5 at `medium` scores 52.5% against Fable 5.1 at `max` with 51.8%,
  for about $3 a problem against $4 at `high`, and on FrontierCode it peaks at `medium`. A project that puts Fable
  rungs back in its own `harness.json` keeps the hold, the step down on Fable's window, and the fallback, which key
  on a rung's family, never its index, so the seven-rung ladder behaves as it did on v1.0.0. `wayline upgrade`
  across this change rewrites a `difficulty` override that names rungs: each index is read against the
  `policy.json` of the tag the project was pinned to and carried by its model and effort, so old rung 5 (`opus
  high`) becomes rung 6, and old rungs 6 and 7 (Fable) become rung 6, the top rung on a cheaper family. Each
  rewrite is printed, and a project whose own `tiers` override defines its ladder is left as it is. An override
  in the shape before the rung ladder that puts a level on Fable now lands on rung 6 too, where it was refused.
- The document viewer (ticket 74; Implementation Decision 17). A Markdown file or an image the dashboard opens now
  opens in one native `<dialog>`, opened with `showModal()` and placed outside the panels the polls redraw, so a
  poll never closes it or moves its scroll; Escape or a click on the backdrop closes it and gives focus back. The
  outputs list's `view` opens it, in place of the preview under the list. The document zooms with CSS `zoom` from
  50% to 300% (the bar's minus, level, and plus, or the keys `+`, `-`, and `0`; the level is remembered in the
  browser), which rewraps the text where pinch zoom only magnifies it, and below 720 px the viewer fills the
  screen. Math renders through KaTeX 0.18.9, vendored with its woff2 fonts under `dashboard/vendor/katex/` and
  found by relative URL, so no request leaves the workstation: one marked extension takes `$...$`, `$$...$$`,
  `\(...\)`, and `\[...\]` (and a bare `\begin{equation}` or `align`) before Markdown reads them, a `*` inside math
  never pairs into emphasis, and `\label`, `\eqref`, `\ref`, `\DeclareMathOperator`, `multline`, a `\newcommand`
  of a name KaTeX predefines, and `$$...$$ {#eq:label}` render, equations numbered as amsmath numbers them. A
  rendered document's relative images and links point into the project, relative to the document, so a report's
  plots show; one that climbs out of the project is not fetched, and neither is anything a rendered file aims at
  the network (an image, a `srcset`, a style's `url()`, a video or its poster, an SVG `<image>`). The position memo
  and a ticket's body render math too, through the same path.
- **Security:** a rendered document can no longer restyle the dashboard (ticket 74). The sanitizer kept a
  document's `<style>`, whose rules applied to the whole page, and a model-written stylesheet can exfiltrate what
  the page shows through attribute selectors and `url()`. Rendering is now KaTeX first, with `trust: false`, then
  `DOMPurify.sanitize(html, {ADD_TAGS: ['semantics', 'annotation'], FORBID_TAGS: ['style']})`: `<style>` is
  refused and KaTeX's MathML keeps its annotations.
- The overview's tables fit a phone (ticket 74). Their 420 px minimum column widened the page past a 390 px
  screen, and with it the viewer; a column is now never wider than its panel.

- The harness's tools (ticket 75; Implementation Decisions 17 and 1). `wayline tools install` installs, beside the
  converter venv and with no ask at any autonomy, never as root: micromamba's static binary at
  `~/.wayline/tools/bin/` (its environments and package cache under `~/.wayline/tools/mamba`, one prefix per tool
  under `envs/`); uv into the same `bin/`, its cache under `uv/`; pandoc 3.11 with pandoc-crossref from conda-forge
  into `envs/pandoc` (pandoc-crossref is added without its declared dependency, which would pull pandoc 3.9 under
  a filter built for 3.11); matplotlib, seaborn, and tree-sitter-matlab in the tools venv; and the embedding
  model, BAAI/bge-base-en-v1.5 at a pinned revision, into `models/`. Every download is checked against the digest
  published beside it (a release's `.sha256`, the Hub's listing for each model file), and a mismatch fails that
  tool alone. Every Python package installs through the harness's uv: the `python -m venv` fallback is gone, since
  it fails on a machine without `ensurepip`. LaTeX, poppler, LibreOffice, and git are recorded as `system` by
  absolute path and never changed. `~/.wayline/tools/tools.json` (now `schema_version` 2) gains one entry per tool
  under `tools`: the absolute executable, the version, the environment it needs, the route, the lock or digest or
  revision, when it was installed, and the installer (`harness`, `owner`, or `system`). It is merged one entry at
  a time under a lock, so two installs keep each other's entries; the converter venv's install keeps every entry
  too, and docling and pdfplumber get entries of their own. New verbs: `wayline tools install <name>` installs one tool, `wayline tools show` prints the record
  (`--json` the file), and `wayline tools run <name> -- <args>` runs a recorded tool by its absolute path and
  environment for a session's short calls, refusing one not recorded. A record of the first version reads as one
  with no entries.

- Project tools, packages, licensed software, and the `software` decision (ticket 82; Implementation Decisions 17,
  1, 2, 6, and 10). The new module `wayline/software.py` builds on ticket 75's record.
  - **A project's tools** install only after a yes, never as root: Octave and R (with renv) from conda-forge
    through the harness's micromamba into `~/.wayline/tools/envs/<tool>`, each package checked against its
    repodata digest and the prefix's explicit export kept as its lock, and Julia 1.12.7 from its release tarball
    into `~/.wayline/tools/julia-<version>`, checked against the SHA-256 Julia publishes. Each is one `tools.json`
    entry with `installer: harness`. `wayline tools install <octave|r|julia>` takes the yes as `--yes` (the
    owner's, in a setup conversation) or `--decision <id>` (its `software` decision answered Install), journals
    `tool_installed`, and refuses otherwise; an installed tool is left as it is, and `--change` changes one on
    the owner's word alone. `--dry-run` prints the route and the sizes micromamba's dry run (or Julia's server)
    states, the disk an estimate of three times what it links.
  - **A project's packages** go into its own environment with no ask: `wayline tools package <python|r|julia|octave>
    <name>...` installs Python packages through the harness's uv into `<project>/.venv` (`code/requirements.lock`),
    R packages from conda-forge into `<project>/.wayline/packages/r`, read by the shared R through `R_LIBS`
    (`code/renv.lock`, by renv), Julia packages into the project environment `code/` (`Project.toml` and
    `Manifest.toml`), and Octave Forge packages into the shared prefix unless two projects disagree on a
    version, when the project gets `<project>/.wayline/packages/octave` (`code/octave-packages.lock`); a package
    the shared prefix holds is never upgraded by another project's ask, and a pin `pkg install -forge` cannot
    serve is refused. `init` gitignores `.venv/` and `.wayline/packages/`; the locks are tracked.
  - **Licensed software** (MATLAB) is never installed by code. `wayline tools install matlab --at <path>`, or the
    answer to its decision naming the path, records it with `installer: owner` and the version, release, and
    toolboxes `matlab -batch "ver"` printed (never the license number), after that one check; mid-run the check
    is a job, and a failing check keeps the decision open.
  - **The `software` decision.** `ticket` and `plan` gain `software` (the planner sets it; the plan check refuses a
    name no route or record knows), and the graph carries it. A ticket is not launchable until every tool it
    names is recorded or its decision said Go without. The conductor sizes a missing project's tool with a dry-run
    job (`wayline tools install <name> --dry-run --json`), then opens one decision ticket of the new class
    `software` per tool, pausing only the tickets that need it, stating the route, the sizes from that dry
    run, the tickets waiting, and the cost, with Install (recommended), Not now, and Go without, and each ask is an
    item of a `software_ask` batch (ticket 79), so a mark settles it; the first answer wins. The owner answers it
    under `interactive` and `checkpoints`, the decider under `autonomous` (its prompt says so); a licensed tool's
    ask and a gap's are `human_only`. An Install answer runs the install as a job, so no wave waits on a download;
    a failed install is retried once, and then the decision is asked again carrying the error. A worker that
    finds an installed tool lacking what its code needs ends `blocked` with `blocked_on: "software <tool>: <what
    it lacks>"`, and code opens the owner's decision; its Install (a change through the tool's route, or for
    licensed software a new check where the owner says it is) or Go without opens that ticket again, once. A
    harness or system tool opens no ask (the ticket waits, and a gap in one is the planner's to re-cut), and
    `rscript` is asked about as R. `wayline tools needs` prints the setup question, every tool the planned work
    needs and lacks, sized, for the setup conversation under `autonomous`.
  - A job spec may name `"tool"`: `wayline job add` writes the tool's absolute executable and environment into
    `command` and `env`, and the job file (schema `job`, widened) and `job_launched` carry `tools`, the name,
    version, and lock digest of every tool the job calls. The journal gains `tool_installed`. Installing free
    software is on neither the irreversible list nor the global harness changes.

- Moving a project's environment (ticket 83; Implementation Decisions 17, 1, 2, and 6). `harness.json` gains
  `environment`, one of four; a project without the key is `shared`. The new module `wayline/environment.py`.
  - **The four environments.** `shared` is the tools as `~/.wayline/tools/tools.json` records them and the
    project's own packages (ticket 82). `conda` is one prefix at `<project>/.wayline/env` holding the project's
    tools and packages. `venv` is one project venv at `<project>/.wayline/env-venv`, built through uv; it holds
    only Python, so the project's other tools stay the shared ones. `container` is one Singularity image at
    `<project>/.wayline/env.sif`, built without root: a sandbox from `docker://debian:bookworm-slim`, the
    harness's micromamba and uv copied in, each tool installed from its lock inside it with the host's package
    cache bound in, then the SIF built from the sandbox. Docker is used only where the account reaches its daemon
    (then the base comes through `docker-daemon://`). SingularityCE is recorded as a `system` tool. `init`
    gitignores `.wayline/env*`.
  - **How a move is checked.** `wayline switch --environment shared|conda|venv|container` builds the new
    environment from the locks ticket 82 writes: each conda tool's explicit export, checked against the digest
    `tools.json` recorded; `code/requirements.lock` through `uv pip sync` on the `.venv`'s Python minor version;
    `code/renv.lock` through `renv::restore`; `code/Manifest.toml` through `Pkg.instantiate`;
    `code/octave-packages.lock` through Octave Forge. Julia's checked tree is copied in, and MATLAB stays the
    owner's install on the host, bound into the image by its own installation folder, found through any link. Code then runs each carried tool's version check inside
    the new environment and compares the Python and Octave packages with their locks. Only when every check
    passes does it write `harness.json` and journal `control environment` (`{environment, from}`). A failed build
    or check removes what it half built, leaves `harness.json`, the journal, and the old environment as they were,
    and prints the failing step. A move is accepted with a conductor running or not; jobs keep running in the old
    environment while it builds. `.wayline/env.json` records what each environment holds, and
    `.wayline/env-move.json` names a move in progress (`environment.move_in_progress`, for the Run view of ticket
    110). A second move while one is in progress is refused. A rebuild is refused while a job still runs, or waits
    to launch, in the place it would replace. Rebuilding the environment the project is in sets its prefix or venv
    aside and puts it back if the build fails or is interrupted, and no job is added there meanwhile; a new image
    replaces the old one only once its checks passed. A project already in an environment is built again when
    the owner moves there and a tool or a lock changed since (the build records each lock's SHA-256), and
    otherwise changes nothing.
  - **After the switch** `wayline job add` and `wayline tools run` resolve each tool through the environment: the
    prefix's or the venv's executable, or inside the image for a container. A job that names no tool runs inside
    it too (`bin/` first on its `PATH`, before what it had, or the whole command in the image, run with `--nv` so a
    GPU job sees the driver, and `LC_ALL=C.UTF-8`), Julia activates `code/` as in `shared`, and the harness's own
    jobs, such as a
    `software` decision's install, stay on the host. The job file (schema `job`) and `job_launched` gain
    `environment`, the environment a job was resolved in when it was added, so a job launched before the switch
    finishes where it started, retries included. A tool recorded after the move is refused until the owner moves
    there again, which rebuilds the environment with it. The harness's and the machine's tools always run as
    `tools.json` records them.
  - The decider never sets the environment. `move` refuses `by: decider`, no decision class names it, its prompt
    says so, and the irreversible list's code check gains the class `environment`, so an answer that would move
    a project is the owner's.

- Objectives (ticket 76; Implementation Decision 17). A project holds objectives, questions the research answers,
  in `research/objectives.json`, written only by code through the ledger (schema `objectives`) and rendered as
  `research/OBJECTIVES.md` in id order with each one's status, measure, answer, and evidence. Ids run O1 onward and
  are never reused: an objective is never deleted, only parked, answered, dropped, or reframed (`reframed_as` names
  its successor). An objective with a measure (`metric`, `direction`, `target`, `held_out_split`, `eval_command`,
  `baseline`, `dataset_or_split`, `min_seeds`) is a goal, and it has at most one measure; a `target` of null means
  keep improving, never reached. `wayline objective add "<question>"` records an open objective; with `--measure
  <file> --sample <artifact>` it records a goal only once the measure's `eval_command` printed the metric on the
  sample, the check intake ran on `GOAL.json`, moved to `wayline/objectives.py`. A measure whose command is not
  ready leaves an objective without a measure, and the verb says why; a measure not in the shape, or two given for
  one objective, is refused and nothing is recorded. Each change journals the new `objective`
  event, with `by` `owner`, `decider`, or `code`. `wayline switch --autonomy autonomous` (and the dashboard's
  autonomy action) refuses while no objective is open and names `wayline objective add`, so setup cannot end without
  one. `wayline status` and the dashboard's overview show each objective's status in place of the goal's latest
  reading; a project with no objectives still shows its `GOAL.json` goal. This is the expand step: every reader of
  `GOAL.json` (keep-if-better, position, specify, plan, the decider, the report) still reads it, and tickets 80, 81,
  and 87 move them to objectives.

- Specify and the plan name objectives (ticket 81; Implementation Decisions 17, 10, and 5). `wayline specify`
  drafts once one objective is open, which may be the question to answer first rather than the project's end, and
  no longer needs `GOAL.json`; with none open it refuses and names the question the conversation asks, "what should
  the project answer first?". The planner's specify prompt lists the open objectives with their measures, and the
  verifier reads `OBJECTIVES.md` in place of `GOAL.json`. The spec gains `summary`, about 120 words on what the
  project is, rendered as the first section of `SPEC.md`, and every claim `objectives`, the open objectives it
  answers (empty for a claim no objective asked for). The Type-A checks refuse a claim naming an objective the
  project does not hold or one that is not open, an open objective no claim answers, and a goal whose metric is not
  among the spec's metrics, each by name; the check of `GOAL.json`'s metric goes. Tickets and the plan schema gain
  `objectives` (the planner states them, empty for a ticket that serves none) and `goal: "O2"` in place of
  `goal_metric`: the metric and direction are read from that goal's measure (`objectives.ticket_goal`). The plan
  returns a ticket naming a closed or unknown objective, or a `goal` with no measure, to the planner, and its prompt
  inlines `OBJECTIVES.md`. A confirmed spec is not checked against the objectives again when the plan cuts it: what
  changed since is the amendment's (ticket 92), and the tickets are held to the objectives open then. Keep-if-better
  runs on a ticket whose goal is open and whose measure has `GOAL.json`'s metric and direction, with `GOAL.json`'s
  command until ticket 87; a closed goal, or a measure that disagrees, is integrated unjudged with the reason said.
  The pick order's second key is the objective class: 0 for a ticket serving an objective the stopping rule waits
  on, 1 for another open objective, 2 for none; until ticket 87 lands `stop_when` the rule is its default,
  `objectives`, every open objective. Which are open is `objectives.json`'s, the one record specify, the plan, and
  keep-if-better read. An `objectives.json` that cannot be read stops `wayline specify` and `wayline plan` with its
  reason, and the conductor says it and judges and orders as if no objective were open, never ending a wave on it.
  The fixtures that carried `goal_metric` carry `goal`.

- Handing over documents (ticket 84; Implementation Decision 17). The owner hands over their own writing in any
  form, and `wayline document add <file|folder|file.zip> --kind inherited|critique|other` keeps it as a
  **document**: converted by code at every autonomy, sorted, recorded, and indexed. A `.docx` goes through pandoc
  (`--track-changes=accept`: headings, every equation as LaTeX), beside a standard-library reader
  (`wayline/office.py`) that decodes Mendeley Cite citations into CSL-JSON and reads comment threads (replies and
  done) with their anchors; a `.tex` goes through pandoc; a PDF with no source beside it through `pdftotext
  -layout` with the margin line numbers stripped, docling marking its headings where it is installed; an `.xlsx`
  by the standard library, one CSV per sheet; a `.doc` through LibreOffice into a `.docx` first. Without pandoc a
  `.docx` is kept and flagged as not converted, its comments and citations still read. Each document lives under
  `research/documents/<id>/` (`source/` and `media/` gitignored, `text.md` with LaTeX math and a block anchor
  `<a id="pN"></a>` before every block, `comments.json`, `citations.json`, `tables/*.csv`), is recorded in
  `research/documents.json` (schema `document`: id, title, kind, version, each file's sha256, the converters and
  their versions, what the conversion lost, and the damage counted), journaled as the new `document` event with
  `by` `session` or `code`, and indexed in `research/DOCUMENTS.md`, rendered by code at or under 20,000 characters
  with each document's kind, version, losses, counts, an inherited one's abstract, and its headings with locators
  (`D1#p3`) and first sentences. One version per text is current, the newest in its source format (an Office
  file's save time read from `docProps/core.xml`, since Word stamps every entry 1980-01-01; a file in a subfolder
  is a text of its own, and a critique has no versions): a folder's versions are kept oldest first, a PDF beside a source of the same text is kept as a copy, and a newer version
  handed over later becomes the next version, the earlier one's source moving under `source/v<n>/`. A folder is
  sorted file by file and a `.zip` unpacked first. A file dropped on the dashboard with no session gets code's
  cautious guess: an identifier makes it a reference (added to `INTAKE.md` as before), review markers a critique,
  anything else `other`, never `inherited`. A PDF sorted as a reference joins the intake's references, and the
  project's `.gitignore` gains `research/intake/*.pdf` so the owner's copy is never committed. The intake skill and
  the drop zone tell the owner to hand over anything in any form: references as bare identifiers, the owner's plan
  as the plan, and a collaborator's list of experiments as a critique. The tests replay the tool runner's
  recordings of pandoc, `pdftotext`, LibreOffice, and docling on the synthetic documents of `fixtures/midway/` and
  `fixtures/documents/` (`fixtures/documents/record.py` makes them).

- The front door reads objectives (ticket 80; Implementation Decisions 17, 10, and 1). A project with no metric
  gets through intake, position, and the grill, and a question that must be answered first can lead.
  - Intake takes information only: `INTAKE.md` loses its `Goal` section, `wayline intake --goal`, `--sample`, and
    `--rationale` are gone, and a spec that carries `goal`, `sample`, or `rationale` is refused naming
    `wayline objective add`, which records an objective and, with a measure checked on a sample, a goal.
    `INTAKE.md` and its template say so.
  - `wayline position` no longer needs `GOAL.json`: the critic reads `INTAKE.md`, `OBJECTIVES.md`, and the
    dossiers. The memo's `goal_feasibility` becomes `objectives`, one row per open or parked objective with a
    verdict (`reachable`, `uncertain`, `out_of_reach`), the reasoning, and a revised target for a goal only, and
    each of the three directions names the objectives it would pursue, by id or as a new question, as
    proposals. `POSITION.md` renders an `## Objectives` section and each direction's objectives;
    `wayline status`, the notice, and the dashboard read `objectives O1 uncertain (revised target 0.83), ...`.
  - The grill's first tier settles which objectives the project takes. While the project is in its setup (not
    past P2), `wayline grill` adds, before the first tier and before every tier once the position memo is written,
    one human-only question per open or parked objective and per
    objective the memo proposes that no question names yet, answered `open` or `parked`; while any is open a tier
    asks the owner only those. Each answer is recorded through the objectives' ledger as an `objective` event
    `by: owner` (a proposal becomes a new objective, its id kept on the record's new `objective` field in
    `DECISIONS.md` and on any revision of it); an objective answered, dropped, or reframed since it was asked is
    refused, and a batch is checked whole before any objective is written.
  - The decider reads `OBJECTIVES.md` in place of `GOAL.json`, and the project's radius with what each radius
    lets it add, an objective only once the owner took `objective` off the human-only classes. The human-only
    class `goal` is now `objective`, which covers goals: `init` writes
    `["objective", "data"]`, and a `harness.json` that names `goal` is read as `objective` (and rewritten so by
    the next intake). The irreversible list the decider is told says a goal's measure, not the goal.
  - The conductor's goal check and keep-if-better still read `GOAL.json` where present, until ticket 87.

- Passages and the five sections (ticket 86; Implementation Decisions 17, 1, 2, 5, 10, and 11). The paper's five
  **sections**, `research/sections/introduction.md`, `results.md`, `discussion.md`, `methods.md`, and
  `references.md`, exist from `wayline init` and are rendered by code (`wayline/sections.py`) after every
  integration; no model edits them. Each file opens with a one-line render stamp (`<!-- wayline:render {...} -->`:
  the section, when, the last passage or finding id seen, the body's sha256), and a render that changes nothing
  keeps the file. A ticket result gains `passages[]`, each `{section, heading, text, replaces}`, which the conductor
  writes through one ledger call once the ticket's work is on `main`: `research/passages.jsonl` (schema `passage`)
  with ids P1 onward, `by` naming the ticket's attempt (`t3-a1`), the owner, a document, a front-door step, an
  answered objective, or a consolidation, the ticket's `objectives`, and the wave, journaled as the new `passage`
  event. A **finding** is a Results passage: findings keep `findings.jsonl` and their ids and gain `heading` (the
  ticket's title when none is named), `replaces`, and `objectives`, on the line and on the `finding` event, and
  `results.md` renders from them. A replaced passage leaves its section and stays in the log; within a heading
  passages keep their arrival order and a replacement takes the place of what it replaces; headings keep their
  first-appearance order; two replacements of one passage in the same wave are both kept and the section notes it,
  and a later wave's replacement replaces what stands in the place. The ticket and plan schemas gain `sections`,
  set by kind (`code` and `experiment` Methods, `analysis` Methods and Results, `lit` Introduction, `writing` what
  it writes, the rest none); the plan returns a ticket declaring another set, and a `writing` ticket with a touch
  set or no section, and a `writing` ticket needs no machine criterion. A Type-A check in the worktree's acceptance
  sends the worker back when a declared section got no passage (Results: no finding) or a `replaces` names nothing
  its section holds. Sections never enter a touch set: tickets adding to one section run in the same wave and are
  written one at a time in id order under the ledger lock. A worker's prompt carries, per declared section, its
  headings with each passage's id and first sentence, and the owner's passages in full. The Introduction is seeded
  by code from the position memo's verified prior work (`step:position`, one passage per row, each tagged
  `{ref:<slug>#<locator>}`) and, once the spec is confirmed, from the spec's new `gap` passages (`step:specify`).
  The planner no longer cuts a `writing` ticket after each analysis. A review pass fixed these before the ticket
  landed: a `running` result's passages are written when its jobs close and its change is kept, never at its
  integration (a discarded or failed run adds none); a discarded change's negative findings replace nothing; a
  later replacement of a passage replaced twice over replaces what renders now, and a same-wave note leaves once the
  passages it names no longer both render; a memo taken again or an amended spec rewords its seeded passage (keyed by
  the reference, or by the heading) rather than adding one beside it; the sections part of a prompt keeps to the
  tier's context cap; the ticket file's `## Result` lists the passages, which is what a verdict on a `writing` ticket
  reads; and Results is re-rendered when a discarded run's findings are filed.

## v1.0.0 (2026-09-27)

- The paper on request (ticket 53; Implementation Decisions 13 and 11). `wayline paper --venue <slug>` drafts
  `research/paper/paper.md` after the report, and `wayline paper` alone asks the decider for the venue that fits
  best, journaled as a `decision` answered `paper venue: <slug>` that the report lists first. `paper_started` is
  journaled. The writer (`opus xhigh`, read-only) returns the whole manuscript through the new `paper_draft`
  schema from the findings with their tags, the references a `ref` tag can name, the manifested results, the
  report, and the venue's `guidelines.json`, and code writes it. Every build runs the sentence classifier and
  the provenance linter, and the seven checks against the venue. A failure goes back to the same writer session
  with the list, at most three builds in all, and a draft that still fails costs no verdict. Each figure the
  draft asks for is requested from the figure role at the venue's target, is not drawn again for the same
  request, and is placed with the figure role's caption; one that waits on the owner holds the gate. A draft
  that builds is gated by the kill argument and then one independent verdict, the read (`gates.PAPER_READ`); each
  fail files a `writing` ticket, unless one for the same point stands open, and the next draft is given the open
  ones, which a draft passing both cancels. `wayline paper --verify` then samples the draft's tagged claims as
  `wayline report --verify` samples the report's (`verify_claims` takes a `document`). `research/paper/build.json`
  records the builds and the gate, and nothing is ever submitted: no verb, dashboard action, or role can.
  `wayline paper --continue` takes up the last draft that failed its build or the gate by resuming the same
  writer session with the list or the points that stood, so its figures are not drawn again, and
  `--continue --venue <slug>` moves the draft to another venue; a figure asked for at the same size under
  another venue's name is not drawn again either. Every verb of the spec's table now has its handler.
- A review pass fixed these before the ticket landed. A window's refusal or the hold on Fable met while a figure
  was drawn read as a figure waiting on the owner, so the paper said "held" and sent the owner to `wayline figure
  resume` where the command should have stopped; it now stops, and a request the figure role refuses outright is a
  failure the writer is told about. The gate filed a new `writing` ticket on every failing run, with nothing to
  close the old ones, so the writer was handed stale and duplicate points; the kill argument now files one per
  subject while one stands open, as the report's claim tickets already did. At a venue that takes neither PDF nor
  PNG (PLOS Computational Biology, bioRxiv) the figure role's PNG failed the format check on every build, spending
  three writer sessions on a conversion only the owner can make; it is a note for the owner now. The second
  verdict was called a review, the word the glossary keeps off a Type-B gate; it is `paper_read`, beside
  `docs_read`. The read is not spent when the kill argument has already sent the draft back. The live M7 run
  found one more: every figure's legend was the path of its `caption.md`, since `final.caption` names the file,
  and the kill argument's adjudication caught it; the legend is the caption's text now, without the
  `[[mixed-data]]` marker the figure checks read, which the next adjudication caught.
- Opus 5.5 in the roles and the verifier table (ticket 65; Implementation Decisions 11, 14, 15, and 16). The
  shipped policy runs the planner, the writer, and the evolver on `opus xhigh` and the decider on `opus max`,
  where they were on Fable at the same efforts, and reads work written on Opus in a fresh `opus max` session,
  where it was `fable high`. Why: since 2026-09-22 `--model opus` launches Opus 5.5, which ranks above Fable
  5.1 on every row of its system card's summary table and costs about a third as much on the matched probe
  (research note 04). No role and no verdict now draws on Fable's weekly window unless a project's
  `harness.json` puts one there, so a spent Fable week holds only the Fable rungs 6 and 7. The roles keep their
  efforts, the ones the fallback of decision 15 already gave them on Opus, and the planner and the decider cut
  their records at `context_pack.max_chars.opus` (200000), which the decider's records on the M5 toy project
  (166,153 characters) fit. A Fable author's verifier stays `opus max`, and the rung ladder is unchanged. The
  tests of the hold, the fallback, and the ask put the role or verifier they exercise back on Fable in their
  project's `harness.json`, as an owner would.

## v0.7.0 (2026-09-26)

- The documentation site (ticket 51; Implementation Decisions 13). A package the harness implemented gets a
  Sphinx site someone else can use, built in the project's own environment while the harness stays standard
  library. `wayline docs init` chooses the theme once per project and records it, the package, and the layout
  in `harness.json.docs`, then lays out whatever is missing: `docs/conf.py`, the four parts (tutorials,
  how-to guides, reference, explanation), the gallery, the examples page, one reference page per public
  module, `docs/requirements.txt`, and `.readthedocs.yaml`. `wayline docs env` installs the requirements
  into the interpreter `harness.json.docs.python` names, or into a venv at `research/.cache/docs/venv`, on
  the interpreter's own pip when it has no `ensurepip`. `wayline docs build` runs seven machine checks and
  writes `research/.cache/docs/checks.json`: the structure and the recorded theme, a docstring on every
  public symbol of the package's `ast` inventory (the code dossier's), every example run, a warning-free
  Sphinx build, every public symbol in the built `objects.inv`, every part reachable from the front page
  with a figure in the gallery and every example shown, and every internal link and anchor, with external
  links asked through the fetch seam unless `--offline`. It prints the failures last and exits 1 on one.
  The new `documentarian` role (`sonnet high`) takes every `docs` ticket, which the `coder` no longer
  covers; the conductor and `wayline accept` add `wayline docs build` to a `docs` ticket's own criteria
  (`tickets.machine_acceptance`), so a failing check returns the ticket with the list; and a done `docs`
  ticket earns the `docs_read` verdict (`gates.DOCS_READ`), one read of the site's clarity and completeness
  against the package's purpose, in place of the read its difficulty would give it. `REPORT.md`'s tickets
  closed section names the site whenever a `code` ticket added public API, with its last build and any
  public API no closed `docs` ticket documents, and the outputs index serves the site built on `main`
  inline under `site/`, in a sandbox.

- The evolve loop, live (ticket 47; the M6 demo). The M6 demo carried two items of feedback, filed from the
  dashboard, through to a tag. What the live run found is fixed here.
  - **Staged writes under `.claude/`.** A worker writes a touch under `.claude/`, which Claude Code refuses to
    any headless session, at `.wayline-staged/`. `wayline accept` and the conductor move it into place.
  - **The proof runs the real old subject.** For a local role override that is the harness role it replaces;
    for a new skill it is no skill.
  - **The proof is cheaper and says why.** It stops at its first failing sample, and it names the checks that
    failed and the session's last words.
  - **Fixture sessions.** A fixture session gets its role's time budget. One cut short by its time or its
    output cap is never cached.
  - **Output cap.** Every launch may answer up to 128000 output tokens.
  - **A change record owns its harness ticket.** No cut or split of the graph takes it back.
  - **Assignable skills.** A local skill whose fixture's baseline passed by the fixture's own rule is
    assignable.
  - **The suite.** `python -m unittest` runs in forked children in about 20 s, and `WAYLINE_BACKENDS=none`
    keeps it off the subscription, the network, and the GPU.

- Promoted the local skill `wayline-interval-claims` from the project `toy` with its fixture `skill/wayline-interval-claims` (`wayline promote`).

## v0.6.0 (2026-09-23)

M5 Overnight and report: the toy project from intake to a report across the real five-hour and weekly
resets of 2026-09-23, with the pause and the conductor's own continuation, two stall replans, verdicts
turning done into accepted, keep-if-better, the Fable fallback under `auto`, the rung ladder's tier up,
top rung, and step down, the notification through hermes, and the outputs over loopback
(`docs/verification/m5.md`, ticket 43).

- Feedback, change records, and harness tickets (ticket 45; Implementation Decisions 12 and 16). The owner
  says what should have gone better and the harness changes itself under test. Feedback arrives from
  `wayline feedback "<text>"`, `wayline evolve "<text>"`, the dashboard's feedback form (the `feedback`
  action, read back by the `changes` view), or a file dropped in `research/feedback/`, each journaled as
  `feedback` with its source; after every `run_ended`, `wayline run` files a retrospective over the journal
  (failures, escalations, stalls, rework, turns per closed ticket, skills below the registry's median
  first-time pass rate, quarantined fixtures) as one more item, source `retrospective`, unless the run
  launched only harness tickets. The new `evolver` role (`fable xhigh`, read-only, `change_list` schema)
  turns the pending items into change records, kept as `research/changes/<id>.json` under the new `change`
  schema and journaled as `change_record`; its list passes Type-A checks (evidence the journal holds, a
  target the mechanism and scope allow, a fixture that does not exist yet) with one return. Code files one
  `harness` ticket per record through the conductor: a local change targets `.claude/skills/wayline-<name>/`,
  `.claude/agents/<role>.md`, or `harness.json` and is integrated like any ticket; a global change works on
  `evolve/<id>`, a worktree of the harness repository under `~/.wayline/worktrees/`, runs the harness tests
  and the full fixture suite there, and waits as `awaiting_owner` until the owner merges it, after which
  `wayline evolve` tags the harness the way a promotion does. Under autonomy `autonomous` a global change
  is only proposed: no ticket, a line in `REPORT.md`, and `wayline evolve --apply <id>` for the owner. A
  `policy` change whose keys include `tiers` or `difficulty` is always `risk: high` and waits on a decision
  ticket of class `ladder`, human-only unless the ladder consent is `auto`; an answer that does not approve
  parks its harness ticket at once. Before a harness ticket is integrated the conductor runs its fixture on
  the subject as it was, where it must fail, and on the change, where it must pass, and commits the passing
  run as the fixture's baseline, which is what makes a model-authored skill assignable. The conductor now
  reads the policy again whenever `harness.json` changes, launches the evolver in the wave that finds
  feedback pending, and commits a `harness.json` the owner's switches left uncommitted before a ticket that
  edits it branches from `main`. The items a session reads are claimed for its length, a list that cannot be filed
  marks its items read, and a done global harness ticket is owed no verdict by the conductor's restart or the tick
  (`gates.owed_asks`, `tickets.works_in_the_harness`). The `wayline-evolve` skill is no longer a shell.
- The model that ran (ticket 63; Implementation Decision 16). Every session now runs with
  `CLAUDE_CODE_DISABLE_LEGACY_MODEL_REMAP=1`, so a retired name such as `claude-opus-4-1` fails
  instead of running, silently and at the newer model's price, on its family's newest. The launcher
  reads the model that ran from the result's `modelUsage` (`worker.model_ran`, `ran_as_asked`,
  `not_served`): a rung naming an alias matches any version of its family, one naming a full version
  matches only that version, dated or not. A ticket attempt whose result names no model of the rung's
  fails with `model_mismatch`, and its `ticket_result` carries `model_ran`; a verdict whose own
  session ran elsewhere carries it too. A name the subscription does not serve (exit 1, `is_error`
  with `subtype: success`, `api_error_status: 404`) fails with `model_not_served` and is never
  resumed or retried: it is no usage refusal and pauses nothing, the rung is held, and one human-only
  decision ticket per held rung asks the owner to edit the policy while every other rung keeps
  launching, a tier up onto the held rung waiting with it. The hold is that open decision ticket, so
  a replay rebuilds it and the owner's answer lifts it. `wayline status` and the dashboard's ticket
  page show both models on a launch whose model was not its rung's: `r5 claude-opus-4-8 high, ran
  claude-opus-5`. No probe runs at `run` start, and no retirement date is stored.
- Pacing and the fallback by rung (ticket 62; Implementation Decision 16). A nearly spent window
  stretches further instead of making hard tickets wait: at `pacing.cheap_at` every ticket launch runs
  one rung below the rung its level gives it, and the deferral of tickets above difficulty 2 under
  `cheap_only` (`schedule.CHEAP_MAX`) is gone. Each launch reads the windows of its rung's family: a
  Fable rung reads Fable's weekly window and the all-models week, every other rung the five-hour and
  all-models windows, and `pacing` carries `fable_action` beside `action`. The step never runs a launch
  below rung 2, and never out of Fable (rung 7 steps to rung 6 and rung 6 stays), because leaving Fable
  is what the hold and the fallback do under the owner's consent; an attempt that is itself a tier up of
  the escalation chain is never stepped down, and role sessions and verdicts are not on the ladder.
  `ticket_launched` carries the rung the attempt actually ran on, and `fallback_from` on
  `ticket_launched` and `verdict` now names the Fable rung the work came from (`r7 fable high`) rather
  than the word `fable`. While a step down is in force the window line of `wayline status` and the
  dashboard overview says so (`stepping down one rung`, or `stepping down to r6 fable low` when only
  Fable's window is at `cheap_at`), and `wayline run --simulate-limit cheap:<seconds>` (or
  `cheap:fable:<seconds>`) forces a reading past `cheap_at` and under `stop_at` for that long, so the
  overnight demo can show launches one rung down without waiting for a window to fill.
- Escalation by rung (`wayline.conductor`, ticket 61; Implementation Decision 16). A tier up now counts
  rungs of the rung ladder, not difficulty levels: it launches the next attempt one rung above the rung
  the attempt that failed ran on, with that rung's model, effort, and budget, and leaves the ticket's
  difficulty level where it was. `difficulty_raised` still moves a kind's level by one after two failures
  at that level, and the rung follows from the level; a raise and a tier up take the higher of the two
  rather than adding. The order after the one resume is now the tier up and then the split while the next
  rung is on the failed attempt's own model family, and the split before the tier up when the next rung is
  on Fable (rung 5 to rung 6), so the scarce Fable week is spent only after the cheaper remedy;
  `policy.escalation.then` ships as `tier_up, split, needs_human`. A ticket on rung 7 has nowhere to climb:
  its tier up is skipped as spent, the split is taken if it is untried, and it then ends `needs_human` with
  the new `reason: top_rung`, which `wayline status`, the dashboard's ticket page, and the `needs_human`
  items of `REPORT.md` show as "at the ladder's top rung". `wayline status` gains a "tickets needing a
  person" section. A tier up onto a Fable rung the hold is holding behaves as any Fable launch under the
  fallback consent: `auto` runs it on the Opus rung at the same effort and budget, `wait` waits for the
  reset, `ask` waits for the ask's answer. The conductor's attribute that names a step of the escalation
  chain is renamed from `rung` to `step` (`replay.TicketView.step`, `_step_from`, `_owed_steps`), so rung
  now means only a rung of the rung ladder, and the journal records the ticket's rung floor rather than a
  raised difficulty. Two rules follow the level no longer moving: a failure counts toward its kind's
  `difficulty_raised` only when the attempt ran on the rung its level names, so one ticket's own climb no
  longer raises every ticket of its kind; and `cheap_only` reads a graph entry's rung where it has one, so
  a ticket the chain tier-upped past the cheap rungs is held by the window as it was before.

- The rung ladder (ticket 60; Implementation Decision 16). A ticket's difficulty names a rung of
  `policy.tiers`, an ordered list of seven rungs cheapest first (a `model`, an `effort`, and a
  `budget`), and `policy.difficulty` maps each level 1 to 5 to a rung index (2, 3, 5, 6, 7). The cap:
  ticket work never runs above `high`, so difficulty 4 launches on `fable low` and 5 on `fable high`,
  while `policy.roles` and every verdict stay at decision 14's efforts. A rung's model is a CLI alias or
  a full version name (`claude-opus-4-8`); its family keys the context cap and the verifier table. The
  policy schema refuses a rung above `high` and the old `difficulty` shape, whose refusal names
  `wayline upgrade`; `wayline upgrade` rewrites a project's old-shape `harness.json` override to the
  nearest rungs and prints one line per level. `ticket_launched` and `verdict` carry `rung`, and
  `wayline status` and the dashboard's ticket page label each launch `r<index> <model> <effort>`. The
  escalation chain climbs it from ticket 61; pacing and the fallback keep their behavior until ticket 62.
- Worker slots count every session a conductor owes (`wayline.conductor`, ticket 59).
  `policy.max_parallel_workers` now holds at every moment, not only at the moment a wave picks: an
  attempt holds its slot while its session runs, while its result waits to be carried (the process
  has exited and no wave has read it yet), and while it waits to start the session it wants. A
  session that returned between wave step 3 and wave step 9 no longer lets the pick fill its slot,
  so the wave that carries and resumes it no longer runs one worker more than the policy allows. A
  gate's resume (an invalid result, a failed acceptance, a timeout) and a relaunch after a worker
  died now wait for a free slot, as the escalation ladder's resume already did; the wait is said
  once and the session starts at the first wave with a free slot, including one freed by a carry in
  that same wave. What a waiting session waits for is the sessions that run, never another waiting
  session, because the attempts in flight can outnumber the slots (the hold on Fable's weekly window
  gives a waiting session's slot away, a restart re-adopts what the journal owes, the policy can be
  lowered between runs) and waiting sessions counted against each other would never start.

## v0.5.0 (2026-09-17)

M4 Front door is live: from a paragraph of intent, the ten references of M3, and a goal, one sitting
ran the intake, the position memo, a three-tier grill with the switch raised, the decider, the spec
(four passes), and the plan: 24 tickets with roles from the registry, and a decision ticket that held
its branch while the other ran and was answered from the dashboard and from `wayline answer`, each
answer relaunching the conductor through the tick (`docs/verification/m4.md`, ticket 36).

- The stall and the escalation ladder (`wayline.conductor`, ticket 38). Every failure journals
  `ticket_failed` with its rung in `next`, and each wave takes every failed ticket up that rung, so a
  restarted conductor carries on where the ladder stood. The order is `policy.escalation.then`, split
  before tier up (the owner's choice, since a tier up to Fable is the dearer step): `resume` resumes
  the failed attempt's session once with the failure output (a failed job and a failed verdict now
  included, in a worktree made again when the integration removed it); `split` calls the planner's
  split (`plan.cut_graph`), and one that fails goes on to the tier up; `tier_up` opens the ticket for
  a new attempt one difficulty tier up; `needs_human` journals `ticket_needs_human` and notifies the
  owner. A ticket a split cut is never split again; a pinned ticket, and one already on the top tier,
  skip the tier up. `ticket_launched` carries `difficulty`, the effective difficulty the attempt launched
  at; two attempts of a kind that failed at a tier past their resume journal `difficulty_raised`
  and move that kind's unpinned tickets up a tier for the rest of the run, never counting an attempt
  that fell back to Opus. A failed acceptance now journals `ticket_failed` with `next: resume` before
  its resume, and a resumed session that reports `failed` again climbs the ladder. The registry's
  outcome record counts one failure per launched attempt. At `policy.stall.waves` settling waves without progress the conductor journals `stall` and
  the planner re-cuts the open tickets (`wayline plan --replan`), or, under radius `strict`, the run
  ends with `stall_strict` and `REPORT.md` is rendered. A run no longer ends while a failed ticket
  waits on a rung or a stall on its replan.
- `wayline run --simulate-failure <id>` fails every acceptance of that ticket on every attempt, so
  the whole ladder runs in a demo; `--detach` passes it to the unit.
- `wayline plan` (`wayline.plan`, ticket 34): the planner's plan protocol cuts a confirmed
  `research/SPEC.md` into `research/tickets/NN-slug.md` and `graph.json`. The planner returns a
  `plan` record (new schema: tickets keyed `T1`, `T2`, ... with `blocked_by` among the keys or
  `#<id>` of an existing ticket, and the decision tickets to open with what they pause); code numbers
  the tickets, has the librarian assign a role and skills to each (journaled `assigned`), runs the
  plan-time Type-A checks (a DAG; every ticket with a demo, machine criteria, a touch set under the
  project and never `research/`, a difficulty, a context pack, a role, and skills; no machine
  criterion passing at the base commit, run in a detached worktree of `main`; a `docs` ticket after
  every `code` ticket declared to add public API, the declaration kept under `## Public API` in the
  ticket body), returns a failing plan to the same session once, writes the graph (journaled
  `ticket_created`), opens the decision tickets, and keeps the plan with the ids it became as
  `research/plan.json`. The registry is rebuilt at every planner launch.
- The graph's confirmation, by autonomy: under `checkpoints` a `blocking: all` decision ticket
  "Confirm the graph", opened in the same locked section that writes the tickets, so no wave can
  find them without their gate; under `autonomous` the decider answers it at once; under
  `interactive` `wayline plan confirm` and `wayline plan revise "<change>"`. A confirmation journals
  `phase P4 -> P5`. An answer that sends the graph back, whichever path it takes (`wayline answer`,
  the ticket file, the dashboard, the decider), parks the graph's open tickets at once
  (`ticket_cancelled` by the planner) so the conductor cannot run an unrevised graph; the graph then
  stands sent back, which no later answer confirms, until the next `wayline plan` cuts it again with
  the change.
- `wayline plan --replan` re-cuts every `open` or `blocked` ticket from the journal's failures,
  stalls, blocks, findings, and answers, parking the superseded ones and, with them, the planner's
  decision tickets that paused nothing else; `wayline plan --split <id>` replaces one failed ticket
  with at least two no harder than it, which inherit its blockers and its dependents. Both are what
  the conductor calls (ticket 38). Two cuts of one graph at once are refused at the write: a first
  plan when one was cut since the session launched, a re-cut when what it supersedes changed. A
  first plan takes back open tickets it finds, so a crash between the ticket writes and `plan.json`
  never leaves a second graph beside the first.
- The `wayline-plan` skill is written around the verb, and its fixture holds the checks
  (`checks.py`) that pin what the verb writes and journals. `roles/planner/agent.md` covers phase P4.
- `wayline.decider.inline_records` is the records inliner the decider's and the planner's prompts
  share; `wayline.specify` exposes `confirms`, `what_to_change`, `move_phase`, and `context_cap`.
- What the M4 demo changed (ticket 36). `wayline status` lists the decisions made, the decider's
  first, each with its confidence and, for the decider's, its rationale. Under `autonomous`,
  `wayline specify` hands the decider the grill's open questions before it drafts
  (`decider.settle_grill`, which `wayline position` uses too), so a `--decide-rest` killed with the
  grill's session is taken up again; the grill skill says how long that verb runs. The spec takes no
  answer to a question that is the owner's (human-only or irreversible): what depends on it is
  written as conditional, and the planner role says so. A prompt over 100 KB goes to `claude -p` on
  stdin, since Linux refuses one argument over 128 KiB. An answered decision ticket stays closed
  across runs: the replay holds it done, and a take-over leaves it to the answers step instead of
  reopening it. The dashboard's decision log shows four lines of a long cell and the rest on a
  click. `wayline init` refuses a project under `~/.claude/`, where Claude Code refuses a worker's
  writes.

## v0.4.0 (2026-09-17)

M3 Dossiers is live: ten references got L0 records, four got L1 skims, and UMAP was promoted as the
primary paper and read in full. All 81 of its inventory items were covered and all 15 figures
described, and its code at `release-0.5.12` was verified by installing it and running a test. The
consultant answered seven questions with locators, one of them a reader's question from inside the
absorb workflow. One level-1 question promoted a paper, another opened a decision ticket beyond the
phase's budget, and a sixth question from one ticket was refused. `docs/verification/m3.md` records
the runs (ticket 26).

- The `consultant` role (read-only, `policy.roles.consultant`, sonnet medium) and the
  `consultant_answer` schema (`answer`, `locators`, `confidence`, `not_in_source`,
  `promote_requested`). Code also refuses an answer that says it was read in the source but names
  no locator.
- `wayline consult <slug> "<question>" [--json]` (`wayline.consult`) launches it through the
  launcher. The dossier directory goes in as `--add-dir`, and the asking worker's
  `TICKET_ACCEPTANCE_FILE` and `TICKET_TOUCHES` are blanked so that its stop guard does not hold the
  consultant. The ledger appends every exchange to `refs/<slug>/qa_log.md` and journals `consulted`.
  `promote_requested` is the `consultant_question` trigger of `dossier.promote`. Under
  `WAYLINE_TICKET`, the question past `policy.consultant.max_questions_per_ticket` is refused before
  any launch (exit 1).
- A reader of an L2 absorb may return one clarification `question` beside its entries.
  `workflows/absorb.js` puts it to the consultant with `agent(question, {agentType: 'consultant',
  schema})`, the conductor fan-out launches the consultant, and both return `consultations`, which
  code validates and records the same way. `absorb_result` gains `consultations`, the reader's list
  schema gains `question`, and the absorb session's `--agents` gains `consultant`.
- A code dossier's recipe skips a test file that defines no test, and runs a pytest-style test file
  (one that imports pytest, or sits under a `conftest.py`) with `python -m pytest` after installing
  pytest into the recipe's venv.
- `policy.absorb.chunk_max_chars` goes from 30,000 to 20,000, from the M3 measurements; the other
  OPEN-16 numbers stand.
- `__version__` is 0.4.0 (it had stayed at 0.2.0 through the v0.3.0 tag).

## v0.3.0 (2026-09-16)

M2 Hardware is live: an `experiment` ticket's worker wrote a three-member job array and returned
`running`, the conductor ran the members one GPU job at a time on cores outside the reservation,
retried the one that ran out of GPU memory with the ticket's smaller batch, manifested every output,
and closed the ticket, and the `analysis` ticket then filed findings on the manifested results, all
with real sessions and real `systemd-run` units. `docs/verification/m2.md` records the runs (ticket
19).

- The job step of the wave (decision 5, steps 2 and 8), which runs whatever the pacing says: every
  job launched and not concluded is polled; one that exited 0 has its outputs checked (JSON and CSV
  parse) and registered in `manifest.json` with its job and run; an OOM steps the footprint ladder
  (a host OOM first doubles `MemoryMax` up to the free RAM over the reservation) and is relaunched at
  once, the log of the attempt that failed moved aside; an exhausted ladder or any other failure
  journals `job_failed` with the log tail, cancels the ticket's other jobs, and fails the ticket with
  the tail as its failure output. A ticket whose jobs all exited 0 is `done` and its verdicts queued.
- A `running` result names its jobs (`ticket_result` gains `jobs`), passes the machine acceptance,
  and is integrated like a done one before its jobs launch, so the jobs run the code on `main`.
  The jobs of a failed attempt never launch.
- The free-slot rule over pending jobs (`resources.place_jobs`): GPUs whole and one job per card,
  cores from the unreserved pool (a `CPUAffinity` never names a reserved core), the load and the RAM
  counted with every placement; a job that waits is journaled once per cause (`job_waiting`, new),
  and one that can never fit fails.
- New roles `experimenter` (the only role with `Bash(wayline job add*)` and `Bash(nvidia-smi *)`)
  and `analyst`; proposals of those kinds default to them.
- `wayline job add` takes the ticket's `resources` (`ram_gb`, `wallclock_minutes`) and `retry` where
  the spec is silent. A ticket file spells a ladder step `"--batch-size=16"`, since its frontmatter
  lists hold scalars only; `ram_gb` is refused as a step.
- The conductor manifests a file a finding cites and refuses a finding whose provenance resolves to
  nothing, noting the refusal on the ticket.
- A job that finished with its outputs counts as progress for the stall counter.
- `fixtures/projects/sweep/`, run by `tests/test_sweep.py` with the fake worker (whose script gained
  `jobs`, the specs it pipes to `wayline job add`) and the fake job runner on a recorded machine.

## v0.2.0 (2026-09-15)

M1 Frontier and windows is live: the five-ticket graph ran on two real workers with its touch-set
conflict serialized, the touch-set guard refused a worker's write outside its touch set, a conductor
killed with SIGKILL mid-wave was resumed by re-adopting its two live workers, a simulated usage limit
paused a run that the tick relaunched under the user manager, and the read-only dashboard showed the
tabs, the frontier, the running tickets, and the journal tail. `docs/verification/m1.md` records the
runs. The entries below it, down to v0.1.0, are everything else this tag carries.

A design pass over the dashboard (ticket 58, M5 Overnight and report), answering the owner's verdict
from the M1 demo: the page "is not good looking", and an empty table drew its header row across the
full width with nothing under it. The owner looked at it through the tunnel four times and accepted
the last; `docs/verification/m5.md` records each look in the owner's words, with the renders before
and after.

- One look, "console", chosen by the owner of three: monospace for the interface, square corners,
  hairlines instead of shadows, and tight rows, from one type scale, one spacing scale, and one set of
  color tokens declared for both themes. The page follows the system's theme until the owner picks day
  or night in the header.
- Every table and list says in words when it is empty, through `tableOrNone` and `listOrNone`, and
  every panel says in its own place when it is reading and when a read failed. Tables are sized to
  their content.
- An index of the sections down the left; every section folds from its heading; the overview's parts
  are ruled off and its tables framed.
- The graph section is Tickets, with two views. The board puts each ticket in a column for where it
  stands, the frontier and the decisions waiting on the owner taken from the server rather than worked
  out again. The graph draws the server's layout again as numbered circles, with a card on hover or
  focus. Pointing at a ticket on either view marks what it waits on and what waits on it.
- A decision ticket can be answered from its own page with the decisions panel's own form, and the
  decisions panel follows the tickets.
- The page carries its own icon as an inline `data:` URI: the browser asked for `/favicon.ico` on
  every load and logged the 404 as a console error.
- Nothing under `wayline/` changed: the endpoints, the token rule, the read-only guarantees, the
  sanitize path, and the vendored files and their digests are as they were. The graph's colors are
  applied in the browser by matching the fills `wayline.dag.svg` writes, and a test holds the two
  together in both directions.

The M1 demo, live (ticket 15, M1 Frontier and windows).

- Ticket 4 of `fixtures/projects/five-tickets/` gains a `## What to do` section, packed into its
  context, asking the worker to try one write outside its touch set and report the hook's refusal
  as a finding; its `fake-worker.json` entry returns that finding. The live run's envelope named
  the refused `Write` in `permission_denials`, and the journal carries it in `ticket_result` and
  `finding`.
- The dashboard's journal tail printed an event whose payload holds a list of objects (every
  `acceptance` event's `results`) as `[object Object]`; an object inside a list now reads as its
  key count, as a bare object already did.
- A worker re-adopted after its conductor died left no `result.json` when it returned after the kill,
  because only the launching thread wrote that file. The conductor now writes it from the stream when
  it carries a re-adopted or already-journaled result (`worker.read_envelope(..., record=True)`).
- `fixtures/conductor/m1-kill-resume/` is recorded again from the changed five-ticket project, so its
  ticket 4 carries the section its finding's provenance names. `record.py` now sets
  `WAYLINE_UNPINNED`, `WAYLINE_UNITS=none`, and `WAYLINE_NOTIFY=none` itself, since the pin check of
  ticket 46 refused its conductor.
- `docs/verification/m1.md` records the two live runs: context-pack sizes per launch, first-time
  pass outcomes, the caps in `policy.json` (kept), the kill and re-adoption, the pause and the
  tick's relaunch, the dashboard as a browser rendered it, and what differed from the notes.

Ask the owner when Fable is spent (ticket 57, M5 Overnight and report).

- Under the fallback consent `ask`, and on a project that never recorded one, the first wave whose hold on Fable's weekly window drops a launch opens the ask (`decisions.open_fable_ask`). A dropped launch is a ticket, a session to start again, verdicts, or an integrator. The ask is one decision ticket per spent window, keyed by the hold's `resets_at` through its origin, so a replay or a restart never opens a second. It is `human_only`, with `blocking: null`, and offers `fall back`, `wait`, `always fall back`, and `always wait`. It recommends `wait` when the reset is under `policy.model_fallback.wait_under_hours` (12) away and `fall back` otherwise. Its `decision_opened` notification names the reset, what is held, the recommended answer, and `wayline answer <id> "<option>"`. A spent week with nothing waiting asks nothing.
- The answer, from `wayline answer`, the dashboard's answer form, or the ticket file, is matched against the options trimmed and case-insensitively, and takes effect at the next wave (`project.falls_back_now`, which the conductor, the gates, the writer, the hold line, and the tick all read). `fall back` falls back for the window, and `wait` waits. `always fall back` and `always wait` also journal `control model_fallback` with `auto` or `wait` (`by` the answer's path). An answer that matches no option counts as `wait`, and the conductor tells the owner so.
- The conductor closes an unanswered ask with a `decision` carrying `decided_by: conductor` (`decisions.close_ask`). It closes it with `answer: superseded` at the first wave past its reset, or on a `control model_fallback` setting `auto` or `wait` while it is open. On a project without the `model_fallback` key under `autonomous`, it answers `fall back` for the window once `policy.model_fallback.ask_timeout_hours` (2) have passed, with a rationale naming the timeout; an explicit `ask` never times out. A late `wayline answer` to a closed ask is refused, and an answer written into its file afterwards is not taken.
- `conductor` joins the `decided_by` enumeration of the `decision` event, the `decision` schema, and the grill's `DECIDERS`. `policy.model_fallback` joins `policy.json`, its schema, and the policy table of Implementation Decisions 14.
- `open_decision` takes `blocking=None` (refused beside tickets to pause) and an `announcement` for the notification's text.
- `wayline status` adds `falls back at <time> unless answered` to the ask where the timeout applies, and so does the dashboard's decisions view, whose controls gain the fallback consent. The dashboard gains the `model_fallback` action, which calls `project.set_model_fallback` behind the action token.
- A review pass fixed these before the ticket landed:
  - A later refusal that moved the hold's reset lost the owner's answer and asked a second time about the same week. The ask now moves with the reset of the hold it asked about.
  - A consent set to `wait` and back to `ask` before the next wave closed the ask. The conductor now closes an ask on the consent it reads at the wave.
  - A late answer to a closed ask was told that `wayline rerun` asks again, which it cannot usefully do. It is now told to use `wayline switch --fallback`.
  - The tick never relaunched a conductor to apply the timeout when only verdicts on Fable were left.
  - An `always` answer whose consent could not be set was journaled anyway. The consent is now set first.

Decision tickets end to end and the dashboard's actions (ticket 35, M4 Front door).

- `wayline.decisions.open_decision` opens a decision ticket: the question, the options, the recommended answer, and the evidence under `## Decision`, with the machine copy as a `decision` record on the grill's `<!-- wayline:decision {...} -->` line; `blocking` and `human_only` in the frontmatter; the new ticket added to the `blocked_by` of every ticket it pauses that is not running or closed; then `ticket_created`, `decision_opened`, and a notification. A second call with the same `origin` finishes what a crash left undone instead of opening another ticket. The conductor opens one for each `decision_requests` entry of a valid result, pausing the tickets that wait on the ticket that asked.
- Under autonomy `interactive` and `checkpoints` the owner answers every decision ticket, so the conductor launches no session for one, and one left on the frontier keeps no run going (`schedule.awaits_owner(entry, autonomy)`); under `autonomous` only a human-only one waits for the owner. The tick measures work under `harness.json`'s autonomy, which is the one a relaunched run starts from, and `wayline status` and the dashboard overview say who answers each open decision ticket.
- `wayline answer` takes `--rationale` and `--confidence`, which a session answering for the owner passes from the conversation, and its checks and writes hold the ledger's lock. The project's `CLAUDE.md` block tells a session to answer with the verb.
- `wayline switch --stop-at/--cheap-at` (`project.set_pacing`) writes the pacing thresholds to `harness.json`, then journals `control pacing`. `project.steer_ticket` is what `wayline cancel`, `wayline rerun`, and their dashboard actions call.
- The dashboard serves `GET /api/projects/<id>/decisions`: the open decision tickets with their options, evidence, and what they pause; the decision log, the decider's decisions first; and the settings the controls start from. It also takes `POST /api/projects/<id>/actions/<name>` for `answer`, `autonomy`, `pause`, `resume`, `switch`, `cancel`, `rerun`, `pacing`, and `intake`, each calling the verb's function in-process and each requiring the token in the `X-Wayline-Token` header whatever the bind. `wayline serve` now prints the URL with the token on loopback too, since the page sends the one its address carries. The page gains the controls, the decisions view with an answer form per open decision ticket, cancel and rerun buttons on the ticket page, and the intake drop zone.
- The intake drop zone keeps a file under `research/intake/` (`intake.drop_material`, up to 64 MB) and adds it to `INTAKE.md` the way `wayline intake` reads a material; every later `wayline intake` takes the files kept there.
- `WAYLINE_NOTIFY=none` keeps the notifier's channels off, and the suite sets it.
- `fixtures/projects/decision-branch/` (rebuilt by its `make.py`) is the graph the tests and the live record in `docs/verification/m4.md` run.
- A review pass fixed these before the ticket landed:
  - Under `autonomous` a decision ticket was launched on the `decider` role, which ticket 31 has not installed, and failed before it started. Until the role reads (`decisions.decider_ready`), every decision ticket waits for the owner.
  - The conductor or the tick could read an answer from the ticket file while `wayline answer` was between its two writes and journal it a second time, without the rationale. The written answers are now read under the ledger's lock.
  - A worker's question that read `## Answer` was taken as the owner's answer. A question that starts with `#` is escaped in the body.
  - The decision requests of a session resumed after a failed acceptance were never opened. A request is now told apart by its question, so the same question asked again in the same attempt opens nothing twice.
  - The notifier ran inside the wave, so a slow channel held every outcome and launch. It now runs on a thread, which `settle` and the end of `run` wait for.
  - A request the ledger refused failed the ticket that asked it.
  - Who answers each decision ticket followed `harness.json` while a conductor ran on the journal's autonomy.
  - `set_pacing` left out `policy.pacing`, so with the thresholds only in the policy a real change wrote nothing.
  - A dropped PDF ran `pdftotext` under the ledger's lock.
  - A switch that met a conductor after its check held the request for the whole drain.
  - `serve` and `run` printed the URL that carries the token into kept output. They now print it only at a terminal.
  - On the page: a stale poll could draw one project's decisions under another's tab, unsaved control edits followed the owner across tabs, and a threshold off the 0.01 grid blocked the pacing form.

Fall back to Opus under the fallback consent (ticket 55, M5 Overnight and report).

- `harness.json` gains `model_fallback`, the fallback consent: `auto`, `ask`, or `wait`. The intake asks it beside the autonomy and the budgets (`--model-fallback`, or `model_fallback` in the spec), says it under Autonomy in `INTAKE.md`, and writes it only when the owner states it, so a project without the key behaves as `ask` and stays distinguishable from an explicit `ask` (`project.fallback_consent` returns whether it was stated).
- `wayline switch --fallback auto|ask|wait` (`project.set_model_fallback`, the function the dashboard's action will call) writes `harness.json` first and then journals `control` with `command: model_fallback` and `args: {model_fallback}`, at any time, with a conductor running or not. A running conductor applies it at its next wave: a `control model_fallback` holds for the run it arrived in, and a new run starts from `harness.json`.
- While the hold stands under `auto`, a ticket whose tier is Fable launches on Opus at the same effort, turns, and minutes (`conductor.fallback_tier`), its context pack cut at `context_pack.max_chars.opus`, with every agent its `--agents` defines on Fable moved to Opus (`worker.fall_back`); `ticket_launched` carries `fallback_from: fable`. An integrator on Fable falls back the same way, and so does the report's writer, whose prose cache records `fallback_from` so the claim verdicts judge that prose as Opus's.
- Under `auto`, a Fable session the hold would keep waiting starts again as a fresh Opus session in the same attempt and worktree, never as a resume of the Fable transcript. That covers a session refused before its first turn, one stopped mid-work, one that died, and one owed a gate's resume.
  - A session that stopped before it returned is said to have left partial work there, and gets the message it was answering when it was a resume.
  - A session that returned and is owed its `invalid_result` or `acceptance_failed` resume is told it returned, and gets the gate's message; the gate's one resume stays spent.
  - The launched session's files are kept in `stopped-<n>/`, and the notes in `fallback.json`, so a restart that relaunches the attempt says them again.
  - After a restart, an attempt that fell back is resumed on Opus whatever the consent says by then.
  - Under `wait`, and under `ask` until ticket 57 asks, Fable work waits as ticket 54 built. A verdict whose verifier is Fable waits under every consent until ticket 56.
- A fallback attempt counts toward the ticket's escalation like any other. The replayed attempt carries `fallback_from`, which ticket 38's difficulty adjustment reads to leave it uncounted.
- While the hold stands, `wayline status` and the dashboard overview print `fable    held until <reset>   consent <auto|ask|wait|ask (unset)>   waiting <n>   fallen back <m>`. `waiting` counts the Fable work the consent keeps waiting: frontier tickets on Fable, Fable sessions stopped at the limit, and Fable sessions owed their acceptance resume. It also counts the done tickets whose verdicts wait on Fable. `fallen back` counts the events carrying `fallback_from` since the hold's `paused`, counting each attempt's fallback launches once.
- A review pass fixed these before the ticket landed:
  - A `control model_fallback` from a run that had ended kept overriding `harness.json`. The replayed consent now holds only while its run is open, and an intake during a run that heard another consent journals the one it writes.
  - A gate's message was dropped when its resume stopped at the limit and fell back.
  - A restart relaunched a fallen-back attempt without its partial-work note.
  - The partial-work note told a session that had returned its result that it had stopped.
  - The owner-facing text for `ask` promised a question that ticket 57 has yet to build.
  - The hold line counted relaunches twice and missed a held acceptance resume.
  - The conductor now reads the consent once a wave, and `status` replays the journal once.

Tags, pins, upgrade, rollback, and promotion (ticket 46, M6 Evolve).

- `wayline run` now refuses to start when the harness checkout is not at the project's pin, `harness.json.harness_tag`, and prints the `wayline upgrade --to <tag> --project <path>` command that fixes it. When the checkout sits on another tag, it also prints the command that moves the project to that tag instead. The check lists every tag on the checkout's commit (`git tag --points-at HEAD`) rather than the one `git describe --tags --exact-match` would pick, so a commit carrying two tags matches either pin. `WAYLINE_UNPINNED=1` skips the check. The suite sets it in `tests/__init__.py`, beside `WAYLINE_UNITS=none`, because it runs between tags and a shallow clone has none; a development checkout running untagged work needs it too.
- `wayline upgrade [--to <tag>]` (`evolve.upgrade`) moves a project to a tag, the latest by default. It refuses while a conductor runs on the project or while the harness checkout has tracked changes. It checks the harness out at the tag, detached, then repins the project through `project.repin`: the pin, the CLAUDE.md block that names it, and the skill and workflow symlinks through ticket 27's refresher. It commits exactly the files that changed, so the next `run` is not refused for changes the harness made outside `research/`. It prints the `CHANGELOG.md` entries between the two tags, read from the newer tag's own changelog so a rollback still lists what it leaves behind, journals `pinned` with `previous`, and names every other registered project still pinned elsewhere. A rollback is `upgrade --to` an older tag. `upgrade --to` the current pin only puts the checkout back and journals nothing.
- `wayline promote skill|role|policy <name>` (`evolve.promote`) works one step per call:
  - The first call opens `promote/<name>` from the harness `main`, as a worktree under `~/.wayline/worktrees/`, so the owner's checkout never moves. It copies in a local skill, a local role prompt (only for a role whose sidecar the harness already has, since the tool lists are the harness's to write), or one policy key merged over the harness default. It also copies the artifact's fixtures, with their subject paths, pinned subject copies, and hashes moved to the harness locations, and without their per-machine `runs/`. It adds a paragraph under `## Unreleased`, commits, and runs `python -m unittest` and `wayline fixture run --suite` in that worktree.
  - A call before the owner merges the branch changes nothing.
  - A call after the merge tags the harness `main`: the next minor tag, or `--tag`, which must be past the latest. The release renames `## Unreleased` to the tag's entry, sets `__version__`, commits `Release vX.Y.Z` where `main` is checked out (or in a worktree of its own), makes an annotated tag, journals `tagged`, and removes the branch and its worktree.
  - A policy key is replaced in place in `policy.json`, leaving every other line as it was spelled, and a value the policy schema refuses opens no branch.
- A review pass fixed three defects before the ticket landed.
  - The pin commit staged all of `.claude/skills/` and `harness.json`, so an owner's half-written local skill or unfinished setting would have been committed under `wayline: pin`. It now stages only the links it rewrote, and `upgrade` refuses while `harness.json` or `CLAUDE.md` has uncommitted changes.
  - `upgrade` checked for a conductor only on the project it moved, while every project runs from the one harness checkout; it now refuses while a conductor runs on any registered project.
  - `promote` counted a branch as merged only when its tip was in `main`'s history, so a squash or rebase merge on GitHub would have waited forever. It now also counts `main` holding every file the promotion wrote as the branch has them, and its waiting message says to pull the merge first.
- `evolve.promotion_candidates` is the recommendation the evolver's retrospective (ticket 45) prints: a local skill with at least three first-time passes and no failure is recommended, and nothing is promoted until the owner runs the command.

Hold only Fable launches while Fable's weekly window is spent (ticket 54, M1 Frontier and windows).

- Fable's weekly window is read apart from the all-models week: from the Fable line of `/usage` (`Current week (Fable): N% used · resets <time>`) at `run` start and again before any wave that would launch Fable work (the wave then picks under what the reading says), and from a Fable session's own `rate_limit_event` (`unifiedWindows.seven_day_overage_included`). The `pacing` event gains `fable`. It never moves the action, and `cheap_at` does not apply to it.
- A Fable refusal is recognized in each of its forms: a rejected `rate_limit_event` of type `seven_day_overage_included`, a 429 on a Fable launch, the "reached your" text beside "hit your", and a subagent's failed task whose `error` names a rate limit and Fable while its parent's result stays a success. `Envelope` gains `failed_tasks` and `answered` (whether the model took a turn at all), and `RateLimitEvent` gains `seven_day_overage_included`.
- A refusal, or a reading of Fable's week at `stop_at`, journals `paused` with `model: fable` and `window: seven_day` instead of pausing the run; `unpaused` with `model: fable` ends it at the reset, or earlier when a reading puts Fable under `stop_at`. A `paused` without `model` stays the whole-run pause, which can start and end inside the hold. A refusal counts as a reading of at least `stop_at`. While the hold stands, a stream's own Fable reading is not taken, since a stream does not say when it wrote an event. A refusal that a restart carries past the reset gives way to a newer reading. The replayed view keeps the two apart as `pause` and `hold`, and `wayline status` and the dashboard overview show `fable <N>` on the window line.
- While the hold stands, the conductor drops every launch on Fable (a ticket whose tier is Fable, the resume or relaunch of a session that runs on Fable or defines an agent on Fable, an integrator on Fable) and keeps launching the rest. A done ticket any of whose verdicts runs on Fable keeps all of them queued.
- A session refused before its first turn is relaunched, never resumed: the conductor relaunches it in the same attempt and keeps the refused stream in `refused-<n>/` beside it; `gates.take_verdict` raises `UsageLimited`, and the verdict stays queued, holding the run open, to be launched again; a refused integrator's rebase is aborted and its session set aside as `integrator-refused-<n>` before it is launched again; the absorb readers, synthesizer, and session, and the report's writer and classifier, are not resumed. A Fable session stopped mid-work waits and is resumed on Fable after the reset.
- `wayline run --simulate-limit fable:<seconds>` rejects the next Fable launch on Fable's weekly window, and `--simulate-limit <seconds>` keeps its meaning. `tests/streams/` gains the recorded Fable refusal and the subagent refusal composed from the research note. The report's resources section counts the holds apart from the run's pauses.

The grill and the autonomy switch (ticket 30, M4 Front door).

- `wayline grill` asks the design tree's frontier one tier at a time. The tree lives in `research/DECISIONS.md` itself: every question is a `decision` record, open until it is settled, written as bullets a person reads over a one-line `<!-- wayline:decision {...} -->` comment that the grill reads back and checks against the schema. A hand edit that breaks a record is reported rather than trusted, and a `DECISIONS.md` wayline did not write is never overwritten. Settled records come first, in the order they were settled, each with `answer`, `rationale`, `decided-by`, `confidence` (or "not stated"), and `timestamp`; open ones follow with what they wait on.
- `wayline grill ask "<question>"` adds a question with its options, recommended answer, evidence (the facts looked up, with where), prerequisites, and whether it is human-only or irreversible. A prerequisite must already be in the tree, which keeps the tree acyclic, and a question the tree already asks is refused with the record that asks it. `wayline grill` alone stamps and prints the tier: every open question whose prerequisites are settled, numbered, each question asked for the first time carrying the tier's number. A question left unanswered is asked again and keeps its first number.
- `wayline grill answer <id> "<answer>" --rationale "<why>" [--confidence c]` settles a question and journals it as `decision` with `decided_by: human` and `ticket: null`, the question's id and text leading the answer. A question whose prerequisites are open is refused, and so is a settled one without `--revise`, which appends a new record that `supersedes` it and leaves the old answer on the record. The decider of ticket 31 settles through the same function, and is refused a human-only or irreversible question. `DECISIONS.md` is written before the journal, and a settled question whose `decision` a crash kept out of the journal is journaled by the next write of the grill. REPORT.md lists a decider decision of the grill under "The grill" rather than a ticket.
- `wayline grill term "<term>" "<definition>" [--avoid ...]` writes a term into `research/CONTEXT.md` under `## Language`, in the glossary's own `**Term**:` shape, replacing the definition of a term settled again (whether it followed on the same line or the next) and keeping every other line of the file as written. `wayline grill --from <file|->` applies questions, answers, and terms as one batch that is checked whole before anything is written.
- `wayline switch --autonomy <interactive|checkpoints|autonomous>` writes `harness.json` and then journals `control {command: autonomy}`, which a running conductor applies at its next wave. Raising is allowed at any moment. Lowering is allowed only while no conductor holds the project, and otherwise the verb refuses it and names the command that stops the run. While a conductor runs, a change is measured against the autonomy the journal says the run holds as well as against `harness.json`, so a hand edit of the file cannot pass a lowering off as a raise. The conductor now reads `harness.json` for `run_started` under the ledger's lock after it takes the heartbeat, so a lowering written while it starts is the autonomy it runs at. `project.set_autonomy` is the function the dashboard's autonomy action will call. Under `autonomous`, `wayline grill` lists the frontier as the decider's and asks the owner only the human-only and irreversible questions.
- The `decision` schema gains `id`, `requires`, `tier`, and `supersedes`. The autonomy descriptions moved from `wayline.intake` to `wayline.project`, beside the switch. `CONTEXT.md` gains **Design tree**.
- The `wayline-grill` skill is written: build the tree from the memo and the intake, look facts up instead of asking them, ask the whole tier with a `Recommended:` line on each question, record every answer and term before the next tier, and on "decide the rest yourself" raise the switch and leave the rest to the decider. Every command it runs passes `--project .`, because a verb without it acts on the machine's active project.
- The skill's fixture holds one grill recorded live over the toy intent, three turns of one session, with structural checks on `DECISIONS.md`, `CONTEXT.md`, the journal, and the turns. The checks confirm four things: every answer follows a tier that asked it in an earlier turn and is journaled; every tier question was asked with a recommendation; no fact was put to the owner; and after the switch nothing but the owner's own questions was settled. `tests/test_intake.py`'s structural helper reads every trace of a recording of several turns and evaluates `tool_not_used`.

The absorb workflow for L2 (ticket 24, M3 Dossiers).

- `wayline absorb --level 2 <slug>` reads one promoted paper in full, in `wayline/absorb.py`. It refuses a paper below level 2 (a read is earned by `dossier.promote`) or one without an inventory.
- Chunking is code. The text layer (`flat.tex` or `text.txt`) is cut into one chunk per section, a subsection riding with its section while the two fit under `policy.absorb.chunk_max_chars`, and a longer section cut into parts that each keep the section's item. Equations, algorithms, and theorems ride with the section they sit in; every figure and table is a chunk of its own with its image file. A PDF item is placed on its page by its title, else by its bbox. Every inventory item lands on exactly one obligation list. `refs/<slug>/absorb/` holds the manifest and one markdown file per chunk: the reading rules, the intent, the obligation list, the image, and the text with its line numbers.
- `workflows/absorb.js` is the saved workflow. It runs `pipeline` over the chunks with one `reader` per chunk and one retry for the items a reader left out, then one `synthesizer` over every entry, and returns `{entries, sections, failures}`. It carries the two schemas verbatim, and a test holds them equal to the schema files. The session is launched from the project root with `/absorb <manifest>` as the first line, the `args` spelled out below it, `Workflow(absorb) Skill(absorb) Read Glob Grep` allowed, the read-only removals, `--agents` defining `absorb`, `reader` (sonnet, medium), and `synthesizer` (opus, high), and the print idle ceiling lifted. When the narrow rules are refused it is launched once more with `Workflow` and `Skill`, and the dossier records which rules ran. The result is read from the run file under `~/.claude/projects/*/<session_id>/workflows/`.
- `policy.absorb.fanout: conductor` is the fallback behind the same `(context) -> Fanout` signature. It runs one reader session per chunk with the chunk pasted in, resumes once for missing items or an invalid result, then runs one synthesizer session. The schema's enum said `sequential`; it now says `conductor`, as the spec does.
- Code merges the readers' work. Every entry is validated, then `entries.jsonl`, `dossier.json` (the new `l2` block: coverage, sections, failures, cost, the queued spot-check), and `dossier.md` are written, and `absorbed` is journaled with the chunk and entry counts and `coverage_pass`. The coverage audit fails with the missing items when an inventory item has no entry, or a figure has no entry saying what it shows. Sentence locators that name nothing are recorded.
- The depth spot-check is queued as a `gates.Ask` for the new `critic` role on the five most important items and every claimed flaw; `take_spot_check` (or `--spot-check`) takes it. `gates.Ask` and `verdict` gain `role`: any role with `may_judge`, on the verifier's tier. New verdict type `depth_spot_check`.
- A review pass and the first live run fixed what they found before the ticket landed:
  - A heading that could not be placed took the line of the one before it and got a chunk with no text. Headings on one line now share it.
  - The spot-check's tier was read for the readers' sonnet, so the critic ran on opus, the synthesizer's model, to judge the flaws the synthesizer wrote. Both authors are now tried, and the critic runs on a model neither used (fable under the shipped policy); a policy that allows no such model is recorded as a problem.
  - The conductor fan-out resumed through `worker.resume` even when handed another launcher. It now resumes through the resumer that goes with that launcher, or not at all.
  - `take_spot_check` left `dossier.md` saying "queued". It re-renders it now, with the critic's findings.
  - A `RoleError` or `LedgerError` ended the verb in a traceback. It now exits 1.
  - On 1706.03762 the readers of Figures 2, 4, and 5 saw one panel of two, because the inventory makes one image per figure. A figure's other `\includegraphics` targets kept under `source/` are now listed in its chunk as its panels.
  - The session passed the workflow's `args` as JSON text, and the Workflow tool handed it to the script as an object. `absorb.js` now accepts either.
- New schemas `dossier_entry`, `dossier_entry_list`, `dossier_sections`, and `absorb_result`, and new roles `absorb`, `synthesizer`, and `critic`. The `reader`'s prompt now allows the one chunk file and image it is pointed at. `fixtures/absorb/` is a small LaTeX paper whose inventory the harness's own chain reads, remade by `make.py`.

The integration protocol and the integrator role (ticket 08, M1 Frontier and windows).

- A rebase conflict no longer fails the ticket outright. The conductor reads the conflicting files with their markers, aborts the rebase, and launches the new `integrator` role once in the ticket's worktree, with the markers as its context and, as its touch set, every path both the branch and `main` changed (the conflicting paths, and the paths a later commit of the branch may stop on); then it rebases again, and only a second conflict fails the ticket with `next: split`. `integrated` records `resolved_by: integrator` when the integrator's rebase is what went through.
- What the integrator hands back is checked, not trusted: the worktree must still be on `ticket/<id>`, and the rebased branch must still change something and nothing it did not change before; otherwise the ticket is split with the reason. A conductor that restarts after launching an integrator finds its session directory, stops it if it still runs, aborts the rebase it left, and never launches a second one for the attempt; a clean rebase then still records `resolved_by: integrator`.
- **A reading for the owner to keep or reverse: the integrator runs `git rebase main` itself and resolves it.** A resolution committed on top of the old branch cannot help, because the conductor's next rebase replays the commit that conflicted and meets the same conflict; so the conductor's second rebase is the check, and a clean one is a no-op. Spec decision 5 now says so.
- `roles/integrator/` reads and edits (`Read, Edit, Glob, Grep`, no `Write`), runs exactly `git rebase main`, `git rebase --continue` and `git rebase --abort` (a `git rebase *` rule would admit `--exec <any command>`), `git add` and the reading git commands, and `wayline accept`; the touch-set guard confines its edits to its touch set. `GIT_EDITOR=true` is in its environment so `git rebase --continue` opens no editor. It runs on `policy.roles.integrator` (opus, high) with the ticket's budget, in `research/sessions/<ticket>/<attempt>/integrator/`. Nothing about its session is journaled as a `ticket_*` event, because a restart would resume its session id as the worker's; the ticket file's `## Result` section records it.
- Integrations are carried one at a time on the conductor's thread, and every step that moves a branch or `main` holds the ledger lock: the rebases, the fast-forward, and the per-wave `ledger: wave <n>` commit. The integrator's session and every acceptance run outside it, so a long acceptance never holds up `wayline answer`, `wayline consult`, or the dashboard.
- The integrator is model work: a conflict met while the owner has paused or the run is stopping leaves the attempt waiting in flight, and the wave after `wayline resume` carries it again from the rebase. That worker result is one outcome, counted by the wave that concludes it, so the stall counter is not moved twice; and a run waiting between waves is no longer woken, wave after wave, by an attempt that waits for the hold to end.

User units, `run --detach`, and the notifier (ticket 13, M1 Frontier and windows).

- `wayline init <path>` now also writes `wayline-tick.service`, `wayline-tick.timer`, and `wayline-dashboard.service` into `~/.config/systemd/user/` exactly as decision 7 gives them, with this checkout's absolute path and interpreter, runs `daemon-reload`, and enables the timer and the dashboard with `--now`. The files are per machine: a second `init`, on any project, rewrites none of them. A manager that refuses is printed as a problem and does not fail the project's layout. `wayline init --uninstall-units` (no path) disables the timer and the dashboard, stops a tick mid-run, cleans the timer's `Persistent=true` stamp, and removes exactly the three files; when the manager cannot be reached it still removes the files, the two `enable` links, and the stamp. Nothing reads or writes the crontab.
- At a terminal, with no `~/.wayline/env` yet, `init` explains that the file is loaded only by the units and offers to run `claude setup-token` and write the pasted token there as `CLAUDE_CODE_OAUTH_TOKEN`, 0600 from the first byte. Away from a terminal it only says so. `claude setup-token` runs through the launcher module (`ClaudeCli.setup_token`), which stays the one place that starts `claude`.
- `wayline run --detach` makes the foreground run's refusals at the terminal, refuses a project whose conductor holds the heartbeat or a `wayline-conductor` unit that is still active, resets a failed one, and starts `systemd-run --user --unit=wayline-conductor -p WorkingDirectory=<harness> -p EnvironmentFile=-<home>/env --expand-environment=no -E PATH=... -E WAYLINE_*... <python> -m wayline run --resume --project <path>`, never with `--collect`. The environment file, `PATH`, and the `WAYLINE_*` variables are carried because a transient unit starts from the manager's environment, not the caller's, and the manager's `PATH` here lacks `~/.local/bin`, where `claude` is installed. The installed tick service has the same `PATH`; ticket 14, whose tick runs `claude`, has to account for it.
- `wayline run`, foreground or detached, prints the dashboard's address and its `ssh -L` line and starts `wayline-dashboard.service` when it is not active; when it will not start, the line says `wayline init` installs it and `wayline serve` runs it by hand.
- `wayline.notify.notify(event, text)` journals `notified` as a claim before any channel runs, tries `notify-send -a wayline -u normal`, falls through to `hermes send --to telegram --subject "[wayline]"` when `harness.json.notify.hermes_python` is set, and journals a second `notified` with the channel whose exit code it carries, `ok`, and the exit code. A missing executable, a timeout, or a crash in a channel falls through to the next; an unwritable journal still reaches the owner; nothing it does raises.
- `WAYLINE_UNITS=none` keeps a process and its children off the user manager. `tests/__init__.py` sets it, so no test writes a unit or starts a service on the machine running the suite; `wayline.tick.use_fake_systemd` stands a manager in a temporary directory in for the real one.
- **One addition to the spec's journal table, for the owner to keep or reverse.** `notified` gains `exit_code`, which the ticket asks the event to record and the table did not carry.

Resume from the journal, the heartbeat, control events, and worker re-adoption (ticket 09, M1 Frontier and windows).

- A wave no longer waits for its workers. Each session runs in a thread of its own; a wave carries the outcomes of the sessions that returned since the last one, launches what the frontier allows into the worker slots the workers still running leave free, and returns, and `wayline run` waits between waves, waking when a session returns or another process appends to the journal. One wave launches a ticket and a later one carries it, so `ledger: wave <n>` now names the wave that carried an outcome.
- Resume is start. `wayline/replay.py` folds the journal into the conductor's working view: statuses, attempts, sessions and pids, jobs, the window pause, pacing, the owner's pause, the stall counter, and what other processes asked for. Replaying twice yields the same view, a view kept by tailing the journal equals the one a restart rebuilds from byte zero, and `run` and `run --resume` rebuild the same one. The first wave of every run takes over: the ticket files are reconciled with the journal (a hand-pinned difficulty and an `## Answer` section win); a worker still running, or one whose stream already holds its result, is re-adopted by its pid and `stream.jsonl`; a dead one is resumed by session id or relaunched in the same attempt, and either waits while the run is paused; a result no conductor carried is carried; the worktrees of closed tickets are removed; and the verdicts a done ticket earned are queued again. `wayline status` reads the window through the same fold, so a pause lasts until `unpaused` in both.
- The heartbeat `research/conductor.json` (`pid, started_at, last_wave_at, harness_tag`) is rewritten in place every wave, and `flock` on it refuses a second conductor on the same project. The lock dies with its process, so a conductor killed with SIGKILL can be resumed at once while its workers live on. `init` gitignores the file (an addition to the spec's ignore line), the ledger commit leaves it out, and decision 2 now records it as the one ledger file rewritten in place.
- The owner steers a running conductor with verbs that live in `wayline/project.py`, beside `switch`: `wayline pause`, `resume`, `stop [--drain]`, `cancel <id>`, `rerun <id>`, and `answer <id> "<text>"` journal what the conductor applies at its next wave, whether or not one is running, and `run --resume` is built (`--detach` is ticket 13's). `stop` ends the run at its next wave and leaves its running workers to finish, for the next run to re-adopt; `stop --drain` launches nothing new and ends once they have returned; `cancel` and `rerun` end the ticket's worker, and a rerun of an answered decision ticket renames its `## Answer` heading to `## Superseded answer` so that it can be answered again. `switch` away from a project whose conductor is running asks it to drain, and waits until it has ended with `run_ended switched`, leaving its jobs to finish, before it moves the pointer.
- The launcher seam gains `StreamTail` (a live stream read as it grows), `pid_alive(pid, run_dir)` (true only while the process's environment names that session, so a reused pid is never adopted or signalled), and `terminate(pid, run_dir, hard)`. The fake's `release()` ends a scripted delay as a worker that finished and `terminate` as one that was killed, and a held call counts as a live pid, so the suite shows slow workers without sleeping.
- **Two additions to the spec's journal table, for the owner to keep or reverse.** `ticket_resumed` gains the reason `readopted`, because none of the four reasons fits a worker picked up again without a new process. A new event, `wave` (`number`, `outcomes`, `progressed`), is journaled at the end of every settling wave; without it a restart cannot rebuild the stall counter, because nothing else in the journal says where one wave ends.
- `fixtures/conductor/m1-kill-resume/` holds the recorded journal, ledger, and `main` files of the five-ticket run killed with SIGKILL mid-wave, remade by `fixtures/conductor/record.py`. The suite replays it and resumes it to `frontier_empty` with both interrupted workers resumed by their session ids; a second test kills a real conductor process during a slow fake worker and resumes that to `frontier_empty` too.

The non-arXiv PDF inventory chain and the tools venv (ticket 22, M3 Dossiers).

- `wayline absorb --inventory <slug> --pdf <path>` writes `refs/<slug>/inventory.json` from a PDF, and a reference with no arXiv id goes there on its own: the PDF kept under `refs/<slug>/source/` from a previous pass, else the open-access PDF the scout found. A PDF-only arXiv submission, which ticket 21 kept and left uninventoried, now runs the same chain on its first pass and again on a 304. The PDF lives under the gitignored `source/` and is never committed.
- The always-on layer runs on every PDF in seconds with no model: `pdfinfo` for the page count, `pdftotext -layout` for the text layer (`refs/<slug>/text.txt`), `pdfimages -list` for the embedded images, and pdfplumber for word and character boxes and ruled tables (`source/boxes.json`), skipped with a note when the tools venv does not have it. With no converter at all, algorithms and theorems still come from the spec's heading regex on the text layer, located by line, and the ruled tables from pdfplumber.
- `wayline tools install` creates `~/.wayline/tools/` with docling and pdfplumber, `--marker` and `--mineru` add the fallbacks, `--grobid` pulls `grobid/grobid:0.9.1-crf`, and `tools.json` records every version and whether torch sees the GPU. Torch is installed first from the PyTorch index that matches the driver: the default wheel on this box was built for CUDA 13 and could not see a GPU whose 535 driver speaks CUDA 12.2, which left docling on the CPU at ten times the cost (279 s against 28 s on the fixture). `--dry-run` prints the commands; `tools show` prints the record.
- The harness only ever runs a converter as a subprocess of the venv's Python, through the helper scripts in `converters/`, and imports none of them. docling runs first (formula enrichment on the GPU, pictures and tables to PNG); marker and then MinerU are tried only when the one before failed on the document, a success that finds nothing in a paper with text counting as a failure; GROBID fills `references[]` and `metadata` through `curl` when a server answers or its image is installed, and a container started for one document is stopped after it. Whatever did not run records `converter: none` and says why in the notes.
- Every converter-derived item carries `provenance: "<tool>-<version>"`, its page, and a bbox in points from the top left, with a `#page=N` locator a PDF viewer follows. Equation LaTeX is `ocr: true`; numbers are regex-recovered from an adjacent `(N)`; algorithm and theorem boundaries, figure meaning, and a guessed caption are named in the new `confirm_fields`, and the notes total what the reader pass confirms.
- What docling did on real papers, each now handled and tested on a document built to show it: it split an aligned display's numbers off and glued "(3)" to the paragraph of the next column (recovered by geometry); it read printed numbers into the LaTeX as `( 1 2 )` (taken off the row ends); it left captions unlinked (paired by page and distance, marked for confirmation); it read labels inside a figure as headings ("Input-Input Layer5"); it called a panel of numbers captioned "Fig. 10" a table; it cut two-panel figures into two pictures and found journal badges on page 1 (a small uncaptioned picture joins the captioned figure on its page, else is left out and counted); and it called the paper title a heading.
- New: the `inventory` schema gains `boxes`, per-item `cells` and `confirm_fields`, page and size on `raw_images`, title, authors, year and page on `references`, and `sha256`, `converter`, `references_by` and `formula_enrichment` on `source`. `fixtures/pdf/` holds a two-column paper written for the suite, rebuilt byte for byte by `make.py`, with what poppler, pdfplumber and docling made of it recorded for replay, and samples of marker, MinerU and GROBID output written to their documented shapes.
- A review pass fixed what it found before the ticket landed. An IEEE-style paper would have been filed whole under `appendices[]`: "I. Introduction" read as a lettered appendix, and every heading after it stayed there. Roman-numbered sections are sections now, and the lettered headings under them are subsections; a letter reads as a numeral only when it is the next one in sequence, so "C. Results" is not section 100. `source.url` recorded the absolute path of a PDF the owner handed over, in an inventory committed with the project; it records the file's name. GROBID was asked without the Crossref consolidation research-notes 06 measured, its references kept a page but no bbox, and a container it started published port 8070 whatever `WAYLINE_GROBID_URL` named. The subprocess seam and the tools record moved into `wayline.tools`, which owns `tools.json`, so the install no longer imports the PDF chain to read its own file.

Figure machine checks, schemas, and the house style (ticket 49, M7 Figures, docs, paper).

- New schemas `figure_request` and `figure_result`. A framework figure and a graphical abstract are forced into the conceptual register, and a guided request must name `revision_of` and at least one change request. Each result status carries the block that justifies it: `verified` needs its final files, its checks, and a passing honesty verdict; an unrendered candidate needs its error.
- `init` copies the harness's `figures/style.default.json` into the project as `figures/style.json` once, and never overwrites an owner's edits. `figures.default_style()` reads the same file, so the palette lives in one place. The default gained `library`, `diverging.cmap` (the ramp the diverging pair is drawn with), and `cvd_min_delta_e`.
- `wayline.figure_checks` runs the 19 Type-A checks of research-notes 11 Section 3 and returns the `checks` block of `figure_result`, one `{id, type: "A", pass, tool, detail}` per check. A tool that is not installed fails its check, since a gate that cannot look cannot pass.
- The harness stays standard-library. What needs matplotlib runs as `figures/checks/artists.py` in the project's own environment: it wraps `savefig` and writes an artist report with the texts actually drawn (size at the target width, extent, role, halo), the panels, the lines marked `required:` or `optional:`, the structure marked `connector:` or `container:`, and the colormaps with their `quantity:`. The clean-room regeneration runs the generator through that script with `python -I`, in a directory holding only the generator, its declared inputs, and the house style. One run gives the exit status, the regenerated files, and the report.
- Written here in the standard library because no check that uses them needs a plotting library: a PDF content-stream walk (text sizes through the text and transformation matrices, colors, rasters), a PNG decoder, mean SSIM with scikit-image's defaults, and CIEDE2000 under Machado's protanopia, deuteranopia, and tritanopia simulations. CIEDE2000 is checked against Sharma, Wu and Dalal's published pairs.
- `fixtures/figures/` holds a sample project (a figure that passes all 19 checks, one that reads an undeclared file, one drawn from unseeded noise) and per-check passing and failing PDFs and PNGs, rebuilt by `fixtures/figures/make.py`. The checks that read an artist report or a caption are tested against committed reports that small real generators wrote, so they run where matplotlib is not installed.
- A review pass fixed six checks that would have been wrong before the ticket landed:
  - A solid `LineCollection`, which is how networkx draws edges, answers its line style as a dash tuple, so every required edge drawn that way read as dashed.
  - Every colormapped plot failed the palette check, because forty neighbouring viridis steps were compared pairwise as new hues; a colormapped artist's colors now count as its ramp, which is checked as a ramp.
  - An axis labelled "x" or a legend entry "y" was taken for a panel.
  - A caption's "(a) ... and (b) ..." lost its (b).
  - Mixed data was grouped by run rather than by result artifact, so two files of one run in one panel went undisclosed.
  - A PDF-only figure drawn from unseeded noise regenerated, since only its text layer was compared; both PDFs are now rasterized and compared by SSIM as well.

  A `verified` result now needs every check to pass, `svg` left the request formats because no check reads it, and an exception while describing a figure no longer stops it being saved.

Provenance tags, the linter, and REPORT.md (ticket 40, M5 Overnight and report).

- `wayline report` renders `research/REPORT.md` from the journal, `findings.jsonl`, `manifest.json`, `GOAL.json`, and the tickets, with the eleven sections of Implementation Decisions 11 in order: decisions by the decider first (with rationale and confidence), open decision tickets and `needs_human`, the goal trajectory drawn as a text chart with the discarded changes, findings by claim, tickets closed as `done` versus `accepted`, negative results, papers by level with the promotions not read in full, "not pursued", proposed global harness changes, resources spent, and the run's events. Every render journals `report_rendered` with the file's sha256, the claim counts, and whether the linter passed.
- Every finding is rendered with `{res:<run-id>/<artifact>#<locator>}` tags built from its provenance and the manifest's run ids, one set on every sentence of it, and the tags become numbered footnote citations with a supplementary reference list in the file. `restore_tags` reads them back, so `lint_report` checks the report on disk rather than a copy of it.
- The sentence classifier is a new `classifier` role (haiku, low effort, no tools) with the `claim_classes` schema. It sees numbered sentences with their tags taken off, in batches of 40, and every answer is cached in `research/.cache/claims.json` by the sentence's hash, so a rebuild classifies only the sentences whose words changed; a tag added to a sentence does not send it back.
- The linter (Type-A) resolves every `res` tag against the run and the path of a `manifest.json` entry and every `ref` tag against a `refs/<slug>/dossier.json` that says `existence: verified` plus a knowledge-base node, requires a claim sentence to end with a tag (a tag in the middle of one does not count), and counts an untagged sentence nobody has classified as a failure, because nothing then says it is not a claim. A failing report is still written, with the offending sentences at its top, and `wayline report` exits 1 and prints them.
- The linter reads prose only. The listings code renders from the journal (decisions, tickets, events, resources) sit between `<!-- wayline:records -->` markers: their provenance is the journal, and asking a model whether "ticket 3 was accepted" is a claim would buy nothing a test cannot say.
- The writer is a new `writer` role (fable, xhigh) with the `report_prose` schema. It drafts one paragraph per claim group and one on the negative results, read-only, from findings handed to it with their tags, and the draft is cached by the hash of that evidence, so a render that changed no finding launches nothing. `--offline` launches no session at all, which is how the tick of ticket 14 should render; `--no-draft` keeps the cached prose.
- `wayline report --verify` samples the tagged claims of the rendered file: 10 percent of them, at least ten, drawn from the claims not produced by a difficulty-5 ticket, plus every one that was, seeded by the claims so the same report samples the same claims. Each goes through `gates.verdict` as `subject_kind: claim`, `verdict_type: claim_support`, on a model other than its author's (the finding's ticket, or the writer), and a failure files one `writing` ticket through the new `gates.file_writing_ticket`, which the kill argument now uses too. A claim that already has a verdict is not read again.
- A session refused by a usage window is not a bad answer. The live writer on fable came back with `status: rejected` on the weekly window and nothing else, and the first cut resumed it and failed the render; now the refusal is a note in the report, the report renders without the prose (or with the sentences the classifier did not reach left unclassified), and nothing is resumed. `docs/verification/m5.md` records the run.
- A failed claim's `writing` ticket carries no touch set: `REPORT.md` and the ledger are written by code, so the correction travels in the ticket's result as a finding with its provenance.
- The fake launcher takes `respond=`, a function of the request that returns the envelope, for a call whose prompt code builds from the ledger; the faked classifier answers the sentences it was actually sent.
- New fixtures: `fixtures/projects/ended-run/`, a toy run that ended with one of everything the report has a section for, rebuilt byte for byte by its `make.py`, and `fixtures/reports/sample-report.md`, the sample the linter tests break one sentence at a time.

Intake and the goal (ticket 28, M4 Front door).

- `wayline intake` is phase P0 as a verb, and the `wayline-intake` skill calls it. It takes what the owner has, as options, as loose arguments, or as one JSON spec with `--from`: a paragraph, a plan (quoted whole under the intent), a reference list, PDFs, data pointers, and repositories (each pinned to its commit, branch, and remote). It writes `research/INTAKE.md` with ten sections in a fixed order: Intent, References, Data, Code, Constraints, Autonomy, Radius, Budgets, Decisions that stay human-only, and Goal. None of them is ever empty, and the settings go into `harness.json`, which the conductor rereads. The skill does not write the file, because the ledger is the only writer of `research/`. The conversation happens in the skill and the files come from the verb.
- A loose argument is classified by what it is, never by guesswork about a missing path. A directory with `.git` is code. A directory of PDFs is references. A text file is a reference list when every line is a list item or an identifier and at least one line carries a DOI, an arXiv id, or a URL; otherwise it is a plan. Words that are not a path are the intent. A path-shaped argument that does not exist is refused rather than read as the intent.
- A PDF becomes its DOI or arXiv id when one can be read, from the uncompressed XMP packet first and then from the first page through `pdftotext` when poppler is installed. Otherwise it is listed by its path, with a sentence saying so. References are written as list items and notes as prose, which is exactly the split `intake_references` makes, so `wayline absorb` looks up the papers and never the notes.
- `harness.json` gains `human_only`, the decision classes the decider never resolves. `goal` and `data` are always there, because decision 4 puts both on the irreversible list. The owner adds classes as `name: what it covers`. `init` writes the default, and a later intake keeps every class already there, so an intake that does not name a class never shrinks what waits for the owner.
- New: the `goal` schema, the shape of BRIEF 6.4 with every key present and null for what the owner did not say. A baseline number without its source is refused. `direction` is `up` or `down`, which is what `wayline status` already reads, and `wallclock` is in hours.
- A goal is written only when its `eval_command` measured it. Intake runs the command from the project root on the `--sample` artifact, which is required, replaces `{artifact}` in the command, and is also exported as `WAYLINE_ARTIFACT`. The goal is rejected with the reason when the command is missing (no command, no sample artifact, or exit 127), fails (a nonzero exit, or the acceptance timeout), prints no number, or the goal is not in the schema's shape. The number has to be the metric: a JSON object with its key, a `metric: value` line, or a bare number on the last line. So "read 1200 rows" does not measure an AUROC. A rejected goal is not a failed intake: the intake is written, its Goal section gives the reason, and the verb exits 1.
- `wayline intake --goal <file> --sample <artifact>` adds or replaces the goal on its own. It runs the same check, rewrites only the Goal section of `INTAKE.md`, and journals a `decision` with `decided_by: human`. `--rationale` carries the owner's reason, and a replacement names the goal it replaced. The same goal twice changes nothing, and a rejected replacement leaves the standing goal and the journal untouched.
- `gates.run_shell` is the acceptance runner made public with an `env` argument, so a goal's `eval_command` gets the same timeout, process-group kill, and bounded drain as a Type-A check.
- The skill's fixture holds a recorded intake, one live `opus high` session under `dontAsk`, and seven structural checks in the research-notes 07 vocabulary: `file_exists`, `file_absent` on `GOAL.json` (the goal nobody asked for), `tool_used` on `wayline intake`, and four `python` checks in `checks.py`. The suite runs those checks on the recording, and on a copy with a section renamed and a goal invented, which they catch. `docs/verification/m4.md` is the live record. Two facts it found are now in the skill. Under `dontAsk` a command chained after the verb is refused whole, and so is a heredoc on stdin even on its own. An unattended session therefore passes the intake as options.
- The project template's `INTAKE.md` now carries the same ten headings as questions.

arXiv e-print sources and the LaTeX inventory (ticket 21, M3 Dossiers).

- `wayline absorb --inventory <slug>` is the arXiv half of the dossier inventory: it fetches `https://export.arxiv.org/src/<id>` through the fetch seam (one request per 3 s on one connection, as the terms of use ask), keeps the source under `refs/<slug>/source/`, flattens it, and writes `refs/<slug>/inventory.json` with the sections, the numbered equations as LaTeX, the figures with their captions and image files, the tables, the algorithms, the theorems, the appendices, and the bibliography, each with a locator of the form `flat.tex:<line>`.
- **Nothing here republishes an e-print.** arXiv's terms of use forbid re-serving one, so `init` now gitignores `research/refs/*/source/` as well (an addition this ticket makes to the spec's ignore list), the source is the only thing under a reference that is ignored, and no real e-print is committed anywhere in this repository: the suite runs on `fixtures/arxiv/tiny-paper.tar.gz`, a paper written for it, and the live counts are recorded once in `docs/verification/m3.md`.
- The ETag is the cache and it never expires: arXiv's ETag is the source's sha256, a version of an e-print never changes, so a second pass offers `If-None-Match`, takes the 304, and re-inventories the source it already has without moving a byte.
- The numbers come from a compile when there is one. LaTeX stores no numbers, so the first pass counts numbered environments in document order, honoring `\nonumber`, `\notag`, the star, and `\tag`, and marks every number `confirm: true`; one `pdflatex` run then replaces the counted numbers of labeled items with the exact ones out of the `.aux` `\newlabel` lines, with the page. Per-field `provenance` says which of the two filled each field, because a paper that labels its figures and not its equations gets one of each. The Attention paper is exactly that paper.
- A number the document does not give is never invented: a `\label` after a `\section*` records whatever the section counter last reached, so the `.aux` will say an unnumbered appendix is section 7. The compile settles a number the count guessed and gives none to an item the document leaves unnumbered; the page from that line is still taken.
- `latexpand` flattens when it is installed and an in-house expander of `\input` and `\include` stands in when it is not, with the note saying which ran and naming every input it could not resolve. Comments are stripped here rather than by latexpand, because the line numbers of `flat.tex` are what every locator points at.
- Figures resolve their `\includegraphics` targets against the tarball the way TeX does, `\graphicspath` included; a raster is copied into `refs/<slug>/figures/`, a PDF figure is rasterized with `pdftoppm -r 150`, and without poppler the target is still recorded and the note says no image file was made.
- `https://arxiv.org/html/<id>` is the second source when the tarball will not flatten, read for LaTeXML's own item classes with the MathML `alttext` as the equation's LaTeX. A PDF-only submission is kept as a PDF and routed to the non-arXiv chain of ticket 22, which its inventory record says in as many words.
- A stranger's archive is unpacked as one: a member that would land outside the reference's directory, a symlink, a device, or anything that is not a plain file is refused, and a tarball that decompresses past 256 MB is not a paper.
- New: the `inventory` schema (per-item `id`, `kind`, `number`, `label`, `page`, `locator`, `provenance`, and the `confirm` flag that says a reader has to check the field), `Ledger.write_bytes` and `Ledger.remove_tree`, because the e-print source and the figure files are writes under `research/` like any other and the ledger is the only code that makes them.
- A review pass fixed six defects before the ticket landed. A PDF-only submission could not be re-inventoried at all: the second pass offered the ETag, took the 304, found no `.tex`, and went looking for an HTML rendering that does not exist for a paper with no source. One `\tag` inside an `align` took the whole environment's numbering and stopped the counter, so every equation after it was numbered wrong, which the `.aux` cannot rescue in a paper that labels no equation. Every bibliography locator was short by the length of a `\begin{thebibliography}{99}` and landed on the line before. The decompression cap was read but never compared, so a gzip bomb was truncated into a corrupt source rather than refused. A figure whose only target was an SVG got neither an image file nor a word about why, while a figure that did get one could still collect a complaint. And the in-house expander dropped the second `\input` of a file it had already expanded, which loses a fragment a paper prints twice.

The venue guidelines and the seven mechanical writer checks (ticket 52, M7 Figures, docs, paper).

- `wayline guidelines build` writes `guidelines/<venue>/` for the fifteen venues `research-notes/10` recorded: `guidelines.json` against the new `guidelines` schema, a `source.md` that says what was fetched and what cannot be believed, and a `checklist/` of reporting-checklist forms. Manuscript templates are linked and never stored, and a test asserts that no URL named in a `template` field was ever requested.
- The build does not parse fifteen publisher layouts, which would rot within the month. Each field carries the short strings the research note read it off, the build re-fetches the page through the fetch seam and looks for them, and a field is `fully_verified` only when the note verified it, its pages answered, and its wording is still there. Everything else is `unverified`, named by sub-path where the note was partial (`figure_spec.color_mode`), with the reason in `source.md`: the note never confirmed it, the page was unreachable, or the page has changed. Nature is the first case the check caught: the page writes "4300 words" where the note wrote "4,300".
- Cell, Cell Systems, PNAS and Bioinformatics answer the harness's stateless client with HTTP 403 from a bot check, on every path the note's action items suggest; the research note reached three of them through a browser-shaped tool the harness does not have. Their fields are the note's and stay unverified. Genome Biology is the opposite: the note could not reach it behind a Springer login, the retry finds that BMC has moved to Springer Nature Link, and five of its eight fields are now read off a fetched page. `docs/verification/m7.md` is the live record.
- The seven checks of `research-notes/10` read `guidelines.json` and nothing else, on a Markdown or LaTeX draft: word or page count with the venue's own exclusions, section presence (a warning where the venue is structure-flexible), figure count, format, resolution, colour mode, file size and legend length, reference style and count, reporting-checklist presence by the study type the draft's own words claim, template or style-package conformance, and the provenance cross-check. `wayline guidelines check <draft> --venue <slug>` runs them and exits 1 on a failure.
- Three fields the spec's list did not name earn their place by making a check possible: `length_limits.excluded_sections`, `reference_style.citation` and `template.document_class`. A word count "with the venue's exclusions" has to know them, and prose cannot drive a style or template check. `figure_spec.notes` mirrors the `length_limits.notes` the spec already had.
- Figure resolution and colour mode are read from PNG, JPEG and TIFF headers in `wayline.guidelines`, because the harness imports no imaging library; a vector file says it carries no resolution rather than claiming one. A page count is read from a compiled PDF sitting beside the source, and skipped rather than guessed when there is none.
- `wayline.provenance` gains the sentence pass both halves of the provenance work share: `sentences` splits prose into sentences carrying the tags they end with, and `parse_tag` says whether a tag is well formed. The guidelines cross-check is what code alone can say, which is that every tag parses and, given a project, resolves; which untagged sentences are claims is a model call and stays ticket 40's.
- A review pass fixed seven defects before the ticket landed, every one of them a check that would have been confidently wrong rather than a crash. A provenance tag was counted as about six words, so the draft this harness is built to write, where every claim sentence ends in one, was over-counted into a length failure; `strip_tags` existed for exactly that and was never called. A venue that writes TIF and JPG in its own format list rejected the `.tif` and `.jpg` files it accepts. A LaTeX table was counted once as a table and again as a figure, and then warned about for pointing at no file, so a compliant draft could fail a display-item cap. A figure's path was resolved and the package's was not, so a draft opened by a relative path, which is how the command is used, read one of its own figures as the compiled manuscript and reported its page count. That page count took the largest `/Count` in the PDF, which in anything built with hyperref is the number of bookmarks. Two required checklists, Genome Biology's and NeurIPS's, could be matched by no file name a person would write, so those venues failed a check nobody could pass; forms are matched by acronym, by title, or by what they are actually called, and a checklist the draft carries as a section counts, because a conference checklist lives inside the manuscript. And `sentences(None)` raised instead of returning nothing, which ticket 40's linter would have hit first.
- The ticket and the spec's M7 criterion both said seventeen venues. The spec's own enumeration and the research note's table both list fifteen: thirteen journals and conferences plus bioRxiv and arXiv, which "the fifteen of BRIEF 13.3 plus bioRxiv and arXiv" counted twice. Fifteen is what is built, and the spec now says so.

The job runner seam (ticket 17, M2 Hardware).

- `JobRunner.launch/poll/kill/cleanup` over a `JobSpec` is seam 2, in `wayline.resources` beside the slot rules it shares decision 6 with. Three backends: `systemd_run` runs the decision's launch line and never `--collect`; `setsid` is chosen with no configuration when `systemctl --user show-environment` finds no manager; `fake` walks a job through scripted `JobState`s, writes scripted outputs, and fakes both OOMs, so the retry ladder and the manifest of ticket 19 are testable without hardware. The conductor sees only a `JobState`, one of `running, exited, oom_host, oom_gpu, failed, killed, gone`, with the manager's `Result=`, the exit code, and the log tail the OOM rule read attached to it.
- The decode table is where the care went, and the recorded `systemctl show` readings of research-notes 05 are the tests: `LoadState=not-found` is `gone` and never success, because an unloaded unit reports `Result=success` whatever it did (R3, R4); `oom-kill` is a host kill and is decided before the log is opened, so a stale traceback cannot outvote the cgroup; `exit-code` plus one of the eight CUDA signatures in the last 64 KB of the log is a GPU OOM, since GPU memory is invisible to cgroups; `signal` with 9 and no `oom-kill` is a cancellation; and `timeout` is a wallclock failure.
- A job outlives the runner that started it, so `poll`, `kill`, and `cleanup` follow the backend named in the handle rather than the one this runner would pick: `handle_for` rebuilds a handle out of `jobs/<id>.json`, which is all a conductor that restarted has, and polling a `setsid` job with `systemctl` would have called a running job `gone`.
- A job the harness cancelled stays `killed` in its file even when a later poll reads success, because a graceful `stop` exits SIGTERM and systemd counts that as `Result=success` (systemd.exec(5) Table 6). Cancellation is a fact about the harness, not a reading.
- `wayline job add` writes one job file, or one per array member under a shared `array` id, from a JSON spec on stdin, resolving its paths against the project and validating every member against the `job` schema before writing any of them. It reads `WAYLINE_PROJECT` and `WAYLINE_TICKET` the way `wayline accept` does, so an experimenter inside a worktree writes to the project's ledger without knowing where the project is. The runner keeps the file current from there: the launch opens an attempt, and the first poll that sees a terminal state closes it with the result, the exit code, and the two timestamps that are the job's duration.
- The `setsid` fallback keeps its `.exit` and `.pid` files beside the log rather than in the jobs directory research-notes 05 A5 names, because only the ledger writes under `research/`. Its poll reads `gone`, never `exited`, when there is neither an exit file nor a live pid: the exit file is missing exactly when the shell itself was killed.
- A review pass fixed ten defects before the ticket landed, and the live check ran again afterwards. Four were in `wayline job add`, where a JSON spec arrives from a worker session: an array whose spec named an `id` gave every member that same id, so the members were written to one job file and the last was the only one that survived while the experimenter was told all of them existed; an array that named no group id at all was written ungrouped, which is not an array as far as the conductor is concerned; `"command": "python train.py"` passed validation as one argv element per character, and the same for every other list-typed field; and `"cores": "8-9"` came out of the verb as a traceback instead of a complaint. Every field the spec carries is now type-checked, and a job id that already has a file is refused rather than overwritten. Two were the cancellation: a kill marked a job `killed` even when it had already exited, turning a successful run into a cancelled one on the ordinary race, and the sticky rule only survived a poll that read exactly `exited`, so the fallback's `gone` and a graceful stop's own readings undid it. Two were the backends: a cancelled fallback job polled `running` forever, because the unreaped process group leader keeps answering `kill(pid, 0)`; and `kill_all` was a silent no-op on the fallback, which is the backend a box with no user manager gets, so a cancel-everything there returned false and left every job running. And two were the runner's contract: relaunching a job id, which is exactly what the footprint ladder does, was refused by `systemd-run` whenever a poll had not cleaned the finished unit up; and `ExecMainCode` was asked for and never read, so a loaded unit whose process had not run yet decoded as an exit 0 and would have sent the conductor looking for outputs of a job that never started.
- `docs/verification/m2.md` is the live record (M2 criterion 1, prototype 27): the pinned GPU job on cores 8 to 15 with a 2 GiB device allocation, a 25 GiB allocation decoded as `oom_gpu` from the driver's own `CUDA_ERROR_OUT_OF_MEMORY`, a 64 MiB `MemoryMax` decoded as `oom_host` with an empty log, a hard kill decoded as `killed`, and the same GPU OOM through the fallback. Three facts the notes did not have: the prototype's eight cores are 8 to 15 and never 0 to 7, which the reservation owns; `show` returns properties in its own order, so the decode reads them by name; and `RuntimeMaxSec`, which is the spec's own addition to the research line, stops a ten-minute sleep at 60 s with `Result=timeout`. torch is not installed on this machine, so the device allocation goes through `libcuda` with `ctypes`, which needs nothing installed and fails with a signature from the table.

Type-B verdicts: the verifier role and the two gates (ticket 32, M4 Front door).

- `roles/verifier/` is the second role the harness ships and the only one with `may_judge`. It is launched by a gate rather than assigned to a ticket, so its `kinds` is empty; it reads and judges and writes nothing. Its session runs with neither `TICKET_TOUCHES` nor `TICKET_ACCEPTANCE_FILE`, and both absences do work: without a touch set the touch-set guard blocks every write and the command guard every deletion, and without an acceptance file the stop guard lets a session stop that has no acceptance to run.
- `gates.verdict(subject_kind, subject, question, paths, scope_limit)` launches it through the launcher seam on the model `policy.verifier` gives for the author's model, validates the `verdict` schema in code, and journals the verdict with its session id and model. A table that would send work back to the model that wrote it is refused rather than obeyed, which is the one rule a project's policy override could otherwise lose. A pass carrying a blocker and a fail carrying no finding are both refused as answers nobody can act on, and a session that cannot produce a usable verdict after one resume raises: a verdict nobody could take is not a verdict against the subject, so the ticket keeps the `done` its machine gates earned and is not accepted.
- The verifier receives paths and one question and no summary of either. Its prompt carries no `/wayline-<skill>` line, and a path that is not there is announced where it is listed, so a session cannot mistake an absent artifact for one it read.
- The conductor queues a ticket's verdicts after `ticket_done` and drains them later in the same wave, because a verdict is model work and is paced with the rest. Decision 11 lists the quality criteria and the independent read separately, so a difficulty-4 ticket with quality criteria earns two verdicts and both have to pass; a difficulty-3 ticket is read as its diff at the commit `main` was fast-forwarded to, a difficulty-4 or -5 ticket as its result. A pass writes `accepted`, a fail writes `failed` with `next: resume` and the findings as the failure output. Pacing holds the whole queue rather than half of it: a ticket whose first verdict passed and whose second was never taken is neither accepted nor failed.
- Either way the verdict is written into the ticket file under the attempt's `## Result` section, naming the model and the session that gave it. The journal has the same thing, but the ticket file is where a person looks and where the next attempt's prompt is assembled from, so findings that reached only the journal would have reached neither.
- `gates.kill_argument(paths)` is the same gate twice: one session writes the strongest rejection memo it can defend from the paths, a second adjudicates it point by point against the same paths, and the adjudication is the one verdict. The memo is the case against the work rather than a judgment of it, so it is not journaled as a verdict: doing that would leave a failing Type-B verdict in the ledger, and in the report rendered from it, against a paper the second thread went on to clear. Its session sits in `memo/` beside the adjudication's, and the ticket a fail files names both. `pass` means one thing in both threads, so a memo that finds no case is an answer rather than a crash: the adjudicator is told the memo was empty and the gate passes.
- A fail files a `writing` ticket carrying the points that still stand, with `proposed_by: verifier`: no planner, worker, decider, human, or evolve pass proposed it, and naming one of them would be a lie in the file a person reads, so the ticket schema takes a sixth author.
- **A read-only Bash command runs under `dontAsk` whether a rule names it or not; one that writes is refused whether one does or not.** Live in `docs/verification/m4.md`: an unallowlisted `grep`/`od` ran in a verdict session with no denial, while a `printf > notes/probe.txt` inside the project was refused with `decision_reason_type: "subcommandResults"` and left no file. The role's `Bash(...)` list is the harness saying what it means to permit; what makes the verifier read-only is the absent write tools and the permission system's own reading of the command. `ToolSearch` was in the live tool list and on neither of the role's lists, and is now disallowed.
- The live record is verdicts on a closed M1 ticket, on `opus high` for a `sonnet` author. The failing one went to the diff on its own initiative and separated the file's prior state from what the ticket's own commit changed, which is the distinction the gate exists for and which nobody asked it for.
- A review pass fixed four defects before the ticket landed. The rejection memo's own scope told it `pass` was always false while the gate refused a fail that named no finding, so a kill argument against clean work would have made the memo either invent an objection or die on a `GateError`, which is the "blocking forever" the spec's shape exists to avoid. A verdict's findings reached the journal and not the ticket file, which is the thing the next attempt's prompt is built from, so nothing handed them to the attempt that had to act on them. A `subject_kind` outside the journal's own enum was refused only by the ledger, after the session had been spent. And `wayline run` counted a verdict-rejected ticket as neither done nor unfinished and exited 0 on it: a ticket that is done and then failed by its verdict is in neither the frontier nor the running set, so nothing else would have mentioned it.

Skills, the registry, and the librarian (ticket 27, M4 Front door).

- `skills/` exists, with the five interactive skills of Implementation Decisions 10: `wayline-intake`, `wayline-grill`, `wayline-plan`, and, as shells their own tickets fill in, `wayline-evolve` and `wayline-paper`. Each is a `SKILL.md` plus a `wayline.json` sidecar, and each has a `fixtures/skill/<name>/` directory in the decision 12 layout holding a `fixture.json` with structural checks only; the runner arrives with ticket 44, so none of them has a baseline yet and their `subject.sha256` is null until a recorder sets it.
- One sidecar shape for both kinds. A role's `wayline.json` now carries the registry fields (`id`, `scope_kind`, `capability_summary`, `applicability_tags`, `cost_hint`, `fixtures`, `sha256`) plus the four a role adds (`allowed_tools`, `disallowed_tools`, `output_schema`, `may_judge`), and `wayline.registry` is the one reader of it, so the index the librarian assigns from and the file the conductor launches from cannot disagree about a role. `roles/coder/wayline.json` was rewritten to it: `role` became `id`, `summary` became `capability_summary`, and `kinds` moved into `applicability_tags`.
- `wayline registry build` writes `research/registry.json`, one `registry_entry` per skill and role of both scopes, with `sha256` recomputed from the files rather than trusted from the sidecar and `outcome` computed from the journal's `ticket_launched` and `ticket_done` or `ticket_failed` pairs. A local entry wins over a global one of the same name, because that is what the launch path does, and a symlink `init` laid down is not registered a second time as a local skill.
- Three things make an entry `assignable: false`, and each of them is a sentence on the entry rather than a silent omission: a local model-authored skill with no fixture that passed at its baseline, a skill directory not called `wayline-<name>` (the prompt builder looks a ticket's skill up under that prefix, so nothing else is reachable), and a local role override of a role the harness does not have (the tool lists are the harness's, so there is nothing to launch it with). A sidecar the build cannot read is listed with the reason instead of stopping the build.
- **`claude plugin validate` reads a skill only from the directory above it.** Run on a skill directory it reports just that the directory holds no plugin manifest, which would make the spec's per-skill pre-check a false failure on every skill. Run on the directory that holds `skills/` it reads every `SKILL.md` under it and returns the ones with problems, with or without a manifest. So the pre-check runs once per scope root, through the launcher seam because that is the only module that spells the executable, and its findings are notes on the entry that never decide `assignable`: the harness's own launch path, not the plugin loader, is what has to accept a skill. No validator on the machine is one note and a build that finishes.
- The librarian (`registry.librarian`) takes a ticket and the registry and returns the role and the skills, ordered by matching tags, then the outcome record (a record of first-time passes beats no record, and no record beats a record of failures), then the cheaper cost hint, then the id. A kind no role covers returns `role: null` and says so, because a missing role is a harness ticket rather than something to paper over. `registry.assign` journals the result, which needed one new journal event, `assigned` with `ticket`, `role`, and `skills`: the spec's table had no event for a plan-time assignment, and the launch that would otherwise be the only record of one comes waves later.
- `project.refresh_symlinks` is the one refresher of the spec's `init` and `upgrade`, promoted from the private helper `init` already used. `init` now links the five skills into every project, which the M0 live fixture's tracked-files test had to learn: the project's own skills are committed as files, the harness's as symlinks that resolve from a worktree because they name the harness by absolute path.
- A review pass fixed six defects before the ticket landed, five of which would have shown up as a registry that was quietly wrong rather than as a failure. A sidecar whose hash had drifted from the files vetoed the skill, so editing a `SKILL.md` without restamping, or a merge leaving a `.orig` beside it, silently stopped the librarian assigning a skill the launch path runs perfectly well; the mismatch is a note now, and `problems` separates the reasons not to assign from the things merely worth reading. A stray file whose name is no artifact name (`.claude/agents/README.md`, `.claude/skills/My_Skill/`) reached the schema and raised, which would have taken the planner down with it every launch, so it is one note on the build and no entry. A dangling symlink inside one skill directory raised out of the hash and killed the whole build; an unreadable file is that artifact's problem and hashes as a marker, so repairing it changes the hash. A `baseline` that recorded no result passed the local-skill gate, because `all()` over no layers is true, which defeated the one check the ticket asks for: a baseline now has to record a layer and sweep it. A local skill's fixture was looked for only under the project, while decision 12's fixture tree is the harness's, so a recorded fixture would never have been found and no local skill could ever have been promoted; both trees are searched. And a local role override was summarised by the harness's words rather than by the description the launch path actually uses.

The frontier, the launchable subset, and two workers at once (ticket 07, M1 Frontier and windows).

- The frontier (`tickets.frontier`) now carries the two rules of wave step 7 that M0 left out: a difficulty-5 blocker holds its dependents until it is `accepted`, not merely `done` (BRIEF 8.4), and an open decision ticket pauses what waits on it, its whole subgraph with `blocking: subgraph` and everything with `blocking: all`. Both leave the decision tickets themselves in the frontier, because a paused project has to be able to answer the question that paused it; the answer paths are ticket 35's.
- `wayline.schedule` is the new module for wave steps 7 to 9: the touch-set collision rule (a directory entry matches everything below it, a file entry matches itself, as `hooks/touch_set_guard.sh` reads one path), the critical-path length, the resource seam, the launchable subset, and the pick order. They are pure functions of a graph, so a wave's scheduling is tested without a conductor.
- The pick order is critical-path length, then a ticket that reports a goal metric, then, under `cheap_only`, the cheaper ticket, then difficulty, hardest first, then id. The two difficulty keys are the spec's and are not one key twice: what is left of a nearly spent window is worth giving to what will close, and otherwise a wave is shortest when its longest job starts earliest. `goal_metric` is not a scheduling field of `graph.json`, so the conductor reads it from the ticket files it opens for every launch anyway.
- The conductor launches up to `policy.max_parallel_workers` (2) workers per wave, one thread each, and carries their outcomes one at a time in pick order, because the integration protocol is one rebase and one fast-forward at a time. Each pick joins the running set before the next is chosen, so two tickets that share a path are never launched into the same wave, and a ticket left `running` by jobs holds its touch set against the frontier while occupying no worker slot. The wave is still as long as its slowest worker; the poll that lets a wave start work beside a running one is ticket 09's.
- A review pass fixed five defects before the ticket landed. The touch-set collision rule compared raw spellings where the guard it mirrors resolves every entry with `realpath -m`, so `./notes/` and `<project>/notes/` collided with nothing and two tickets writing one file could be launched into one wave. An unexpected exception carried back from one worker's thread abandoned the other workers of the same wave, which had already committed, leaving their tickets `running` and holding their touch sets against every wave to come with no poller to release them. `wave.launched` counted tickets the launcher had refused. `wayline status` defined an open decision ticket as one whose status is `open` while the frontier paused on every decision but `done`, `accepted`, and `parked`, so a decision whose decider failed could stop the project and appear nowhere. And a run whose frontier was emptied by a hold rather than by finished work said only `frontier_empty`: it now names, before it stops, every open ticket left outside the frontier and what holds it, whether an unanswered decision or a difficulty-5 blocker that is `done` and waiting for the quality verdict of ticket 32.
- `fixtures/projects/five-tickets/` is the M1 graph: two independent branches and one ticket whose touch set is the directory the alpha branch writes in. Nothing blocks that ticket, so only the collision rule keeps it waiting; the suite asserts from the journal that both workers of a wave were launched before either result was carried and that the conflicting ticket launched only after the `integrated` of both tickets it shares a path with. `WAYLINE_LAUNCHER=fake wayline run` closes all five in three waves and ends with `frontier_empty`.

## v0.1.0 (2026-09-12)

M0 Skeleton is live: `wayline init` lays out a project and `wayline run` takes one trivial ticket
from the frontier to a fast-forwarded `main` through a real `claude -p`, unattended, in one
command. `docs/verification/m0.md` records the run.

The M0 demo, live and unattended (ticket 06, M0 Skeleton).

- `fixtures/projects/m0-live/` is the project the demo runs on: one trivial `code` ticket whose
  every step is a probe of the harness rather than work anyone wants done. It writes two files
  inside its touch set, tries one write outside it, delegates one read to an Agent-tool subagent,
  and names two skills whose `SKILL.md` each carries a passphrase written nowhere else. The suite
  runs it with the fake worker; the live run of the same project is the record.
- Two things the live path needed that nothing had, and that no smoke could have found, because
  neither ticket 03's nor ticket 04's launches went through the conductor. `--json-schema` refuses
  a schema carrying the 2020-12 meta-schema reference every file under `schemas/` opens with, so
  the flag now drops it and the first launch died before its session began until it did. And the
  contract line tells a worker to run `wayline accept` while nothing put the command on its
  `PATH`, so the harness `bin/` now goes first there.
- **Only the first `/wayline-<skill>` line of a prompt expands.** The live run dated it from the
  stream: the worker knew the first skill's passphrase with no tool result carrying it, and had to
  open the second skill's `SKILL.md` itself to learn the other. It could only do that because a
  project's skills are committed in its worktree, which is luck rather than a contract. So the
  conductor inlines the bodies of every skill after the first under a `# The rest of your skills`
  heading, which is the path Implementation Decisions 3 names for exactly this finding, and a
  second live run confirmed both passphrases coming back with no file opened.
- The guards hold inside an Agent-tool subagent, with `agent_id` and `agent_type` in the hook
  input, as the documentation says and nothing had shown. `WAYLINE_HOOK_RECORD` is how: the
  command guard appends every hook input it is handed to that file, for a milestone's record and
  nothing else. It runs in a subshell with its errors dropped, so a recording that cannot be
  written loses the recording and never the decision. The other two guards do not record, because
  they are the research note's scripts carried over byte for byte and a test holds them to it.
- Ten host tools reached the live worker that the coder's `disallowed_tools` did not name, read
  off `system/init` rather than guessed at. All ten are now on the list. `Monitor` is the one that
  mattered: it runs a shell command and it is not the `Bash` tool, so neither the role's
  `Bash(...)` allowlist nor the command guard's `Bash` matcher sees what it runs.
- The portability seam of M0 criterion 10 is asserted rather than described: one free `launch` and
  one free `resume` over a `LaunchRequest`, one of each per backend, one backend named
  `claude_cli`, and no third spelling anywhere in the package.
- The order the run settled, worth having written down: a `PreToolUse` hook runs first, and its
  exit 0 means no decision, after which the normal permission flow refuses a call the role's
  allowlist does not cover. A hook's silence is not permission.
- A review pass fixed four defects before the ticket landed: the first of a ticket's skills was
  never looked up, so a misspelled one was a slash-command line expanding into nothing with no
  problem recorded; the inlined bodies sat outside the tier's context cap and were counted
  nowhere, so three large skills could have tripled a prompt with `cut` still false; the
  meta-schema strip was a blanket recursive delete, which would have taken a result field
  actually named `$schema` out of `properties` and left it in `required`, a schema no worker can
  satisfy; and the recorder fell back to raw multi-line stdin when `jq` could not compact it,
  which costs a reader the whole record file rather than the one entry.

The fetch seam, the scout, L0 records, and the knowledge base (ticket 20, M3 Dossiers).

- `wayline.fetch` is the fifth seam: one `fetch(url, headers) -> Response` over a backend, with `UrllibBackend` for the network and `DirectoryBackend` for a directory of recorded responses at `<host>/<request hash>.json`. With an inner backend it is the scout's self-filling cache under `research/.cache/scout/`; without one it is the suite's `fixtures/fetch/`, where a request nobody recorded raises instead of quietly going out. Every outbound request carries `User-Agent: wayline/<tag> (mailto:<owner_email>)`, and the per-host rate limits of `research-notes/06` are enforced in the seam (Crossref 10 per second, arXiv one per 3 s on one connection, OpenAlex and the galleries once a second), with the clock and the sleep injectable so no test sleeps.
- The request hash deliberately leaves out the `User-Agent` and the values of the `mailto` and `email` query parameters, so a response recorded by one owner replays for the next and no committed recording carries anyone's address.
- `wayline.scout` resolves a reference through the keyless chain: a DOI through Crossref, then OpenAlex, then Unpaywall, then Europe PMC, with a `10.1101` DOI going to bioRxiv and medRxiv first (they are the only source with the preprint's version history and the journal DOI it was later published under); a title through Crossref `query.bibliographic` with three rows and a title-similarity check in code, then OpenAlex `search`, then Europe PMC `TITLE:`; an arXiv id through the arXiv API and nothing else. Semantic Scholar is never called (keyless it answers 429 on the first request), and a test asserts it. A reference that resolves nowhere is `existence: unresolved` and records every door the scout knocked on; nothing in the module can write the word fabricated.
- The similarity check is what decides a title match, not the service's own score: Crossref's best row for "Attention Is All You Need" is "Is Attention All You Need?", a different paper, with the higher score of the three (`docs/verification/m3.md`).
- After a work is found, each remaining source runs only for a field still empty, because an L0 record is metadata, identifiers, and an abstract, and Crossref carries no abstract for most journals. That is also what keeps OpenAlex, a daily budget rather than a rate, read sparingly: a DOI Crossref answered in full costs one request.
- A bare URL with no identifier in it resolves nowhere and says so. No keyless service takes a URL as a question, and giving the record a title made out of the URL would be inventing one.
- `wayline absorb --level 0` reads the references out of `INTAKE.md` (list items, so the sentence introducing the list is not looked up), resolves each one, and writes `refs/<slug>/dossier.json` under the new `dossier` schema plus a knowledge-base node, journaling `absorbed` per reference. A second pass writes the same slugs and asks the network nothing.
- `wayline.kb` holds the graph: `kb/nodes/<id>.json` for papers, ideas, experiments, and claims, `kb/edges.jsonl` for the seven typed edges, and `kb/query_pack.md` regenerated under `policy.kb.query_pack_max_chars`. The pack carries relations and identities and no dossier prose, which a test asserts; when the cap bites, the nodes taking part in no edge go first and the cut is announced in the text.
- `wayline init --email <address>` stores `owner_email` in `harness.json`; away from a terminal git's configured address stands and nothing is asked, so `init` remains the non-interactive command the tick and the suite call. A project with no address absorbs anyway and is told, by `init` and again by every `absorb`, what the polite pools lose and how to fix it.
- Three shared spellings replaced their copies: `ledger.ledger_for` (a ledger from a ledger or a project path), `cli.parse_args` (argparse without the process exit), and `kb.slugify` (the one normalizer behind both a node id and a dossier's directory name, so a slug and its node can never drift apart).
- `fixtures/projects/ten-references/` is a project whose intake names ten references the way an owner names them, and `fixtures/fetch/` holds the 22 responses that resolve them offline. The live run of the same ten is recorded in `docs/verification/m3.md`.
- A review pass fixed three defects and dropped two inventions before the ticket landed: the preprint reader checked one version of a record for a title and then wrote a different one into the dossier; a reference list line beginning "Nothing..." was read as the owner saying there were none; the rate limiter's comment described pacing from the start of a request while the code paced from the end; a table of 24 "biomedical" DOI prefixes decided when Europe PMC was asked, though it held general publishers and the emptiness of the abstract is the honest question; and an arXiv id the API did not know fell through to a Crossref DOI lookup no spec line asks for.

The read-only dashboard: transport, tabs, the journal tail, and the overview (ticket 11, M1 Frontier and windows).

- `wayline serve [--bind <address>] [--port <n>] [--project <path>]` starts the `ThreadingHTTPServer` of Implementation Decisions 8 on `127.0.0.1` at `harness.json`'s `dashboard.port` (8765) and prints the one line the owner pastes on the laptop: `ssh -o ServerAliveInterval=30 -o ExitOnForwardFailure=yes -N -L <port>:127.0.0.1:<port> <workstation>`. The two ssh options are in it because `research-notes/08-dashboard-transport.md` recorded what happens without them: a tunnel whose transport died still accepts connections on the forwarded port, so every request fails until it is rebuilt by hand.
- `GET /api/projects` draws the tabs from `~/.wayline/projects.json` with the active project marked and the poll intervals the page uses; a project whose directory is gone stays in the list as `readable: false` rather than vanishing. Each project's id is its directory name, and its directory name plus eight hex of its path when two projects share one, so a URL segment is stable and a client never derives an id.
- `GET /api/projects/<id>/overview` is `wayline status`'s own view plus the phase the journal last moved to: autonomy, radius, goal progress, window status, the slots in use, the running tickets and jobs, the open decision tickets, the ticket counts, and the last ten events. It is read-only by construction: `status_view(project, refresh=False)` and `refresh_graph(..., write=False)` compute the graph without writing it, so a view polled every five seconds never takes the ledger's lock to rewrite a file the conductor owns.
- `GET /api/projects/<id>/journal?since=<byte offset>` returns only what was appended, with the `next` offset to send back; an offset past the end of the file is reported as `truncated` and read from zero so a tail recovers instead of waiting for bytes that will never come, and a line still being written is held back until it is whole. `?tail=<lines>` is how a page that has just opened finds its first offset, reading backwards in 64 KiB blocks for the last screenful instead of transferring a journal that may be megabytes only to trim it to 500 lines.
- Every JSON view carries an `ETag` and answers 304 to `If-None-Match`. The tag comes from one `os.scandir` snapshot of `(st_mtime_ns, st_size)` per ledger directory behind a 1 s memo, never from hashing contents (0.64 ms against 6 ms for 111 files in the research note); size is half the key because Linux stamps inodes from the coarse clock, so two writes inside one jiffy share an `mtime_ns`. The journal needs no snapshot at all: it is append-only, so its length is its version. A tag covers everything its view carries, not only the ledger: the projects tag stats each project's directory and the active project's `harness.json`, and the overview's stats the active pointer and carries which `READINGS_TTL_S` window the request falls in, so the machine's live readings can never be more than one poll old.
- `?transport=sse` switches the journal tail alone to server-sent events for the comparison OPEN-20 asks for: unchunked with `Connection: close`, `id:` set to the journal offset after the line it carries, `retry: 2000`, a 15 s comment line, and a `select()` dead-client check that ends the thread within a tick of the tab closing. Polling stays the default; the measured reason is in `docs/verification/m1.md`.
- `dashboard/index.html`, `app.js`, and `style.css` render the tabs, the overview, and the tail with no framework and no build step, polling 2 s for the tail and 5 s for the views with `cache: 'no-store'` and a manual `If-None-Match` so a 304 reaches the page instead of the browser's cache. `vendor/marked.umd.js` (18.0.12) and `vendor/purify.min.js` (3.4.15) are pinned, checked in, and recorded with their sizes and SHA-256 in `dashboard/vendor/VENDOR.md`, which a test asserts; `DOMPurify.sanitize(marked.parse(md))` is the one path from markdown to HTML, because workers write the markdown the dashboard renders and the dashboard grows action endpoints in M4.
- Bound to loopback the views need no token. `--bind` wider mints and requires the random URL token of `~/.wayline/dashboard.json` (mode 0600, created at that mode before anything is written to it) on every request, in the `X-Wayline-Token` header, as `?token=`, or in the `SameSite=Strict` cookie the first URL-borne token is answered with, because a browser attaches neither header nor query to a `<link>` or a `<script>` and the page would otherwise load with none of its assets. Actions will require the header whatever the bind (ticket 35), so a cookie alone can never act. A wide bind also raises `request_queue_size` to 16, and the handler carries a 30 s idle timeout so a peer that presents nothing cannot hold a thread on a kept-alive connection.
- The token is minted once and kept across restarts, so a bookmarked URL keeps working; the file records the port and bind the running server actually bound, and never overrides the configured ones.
- `tests/test_dashboard.py` drives a real server on a free loopback port over a copy of `fixtures/ledger/`: every endpoint, the 304 path, the byte-offset tail and the `tail=<lines>` first read, the path traversal refusals, the token rule including the browser's cookie flow, the idle-connection close, and the event stream over raw sockets with `Last-Event-ID` resume and the thread ending when the client goes away.
- A review pass fixed eight defects before the ticket landed: a wide bind served the page and 403'd every asset it references; `/api/projects`' ETag missed whether each project's directory is still there and the active project's poll intervals, so a deleted project kept an enabled tab behind 304s; the overview's ETag missed the live machine readings and the active pointer, so the slots could freeze for hours behind 304s; the journal's ETag missed the cursor, so one tag spoke for several representations; an idle kept-alive connection held a thread with no timeout; the token file was briefly world-readable between its rename and its chmod; an out-of-range `--port` was silently replaced by 8765; and the page refetched the whole journal on every tab switch while keeping a dead ETag entry per offset. Rendering the page in a real browser caught one more: the decisions table treated a ticket's `blocking` as a list of ids when the schema makes it the scope a decision pauses, which left the panel at "loading" with nothing in the console.

The manifest and findings provenance (ticket 18, M2 Hardware).

- `wayline.provenance.register_artifact(project_or_ledger, path, job, run_id, ticket)` hashes a result artifact (sha256, in chunks) into `research/manifest.json` and journals `manifest`; a second registration of the same path replaces its entry instead of appending a stale sibling, and the read-hash-write happens under the ledger's lock so two workers registering at once cannot lose an entry. `run_id` must be `t<ticket>-a<attempt>`; a bad entry (a ticket outside the schema's range, say) never reaches the manifest.
- `add_finding(project_or_ledger, text, provenance, ticket, negative=False)` refuses (raises `ProvenanceError`, writing nothing) when a provenance locator has no `<path>#<locator>` shape or its path half is not in `manifest.json`; an accepted finding gets a sequential id (`f-0001`, ...) in `findings.jsonl`, journals `finding`, and re-renders `findings.md`. `provenance` takes one locator or several, so one finding may cite more than one artifact.
- `render_findings` writes `findings.md` from `findings.jsonl`, grouped by ticket in ticket order, negative results marked; `add_finding` calls it after every change so the two files never drift.
- `oversized_tracked_files(project)` warns (never refuses) about a git-tracked file heavier than `policy.artifacts.commit_threshold_bytes` (a project's `harness.json` may override the shipped default), naming the manifest as the alternative to committing it; `results/` is already git-ignored by `init` (ticket 02), so this only ever catches a file someone chose to commit.

The conductor's M0 path with the fake worker (ticket 05, M0 Skeleton).

- `wayline run` is the conductor over one project. A wave regenerates `graph.json`, computes the frontier, adds `.worktrees/<id>` on `ticket/<id>` from `main`, assembles the prompt, launches through the launcher seam, validates the result, runs the ticket's machine acceptance in the worktree, rebases onto `main`, runs it again as `rebased`, fast-forwards `main`, runs it a third time as `main`, writes the findings and the status through the ledger, journals every step, removes the worktree and the branch, and commits what it wrote as `ledger: wave <n>`. It journals `run_ended` with `frontier_empty` when nothing is left.
- M0 runs one worker per wave and waits for it, so the whole path runs in the suite in seconds and no test sleeps. Ticket 07 makes the launch asynchronous and the launchable filter real; ticket 08 brings the integrator that resolves a rebase conflict (M0 fails the ticket with `next: split`); ticket 09 the heartbeat, the control events, and resume; ticket 10 the pacing; ticket 38 the rest of the escalation ladder, whose next rung M0 names in every `ticket_failed`. A wave that could move nothing ends the loop, because in M0 nothing can arrive while the conductor waits.
- An experiment ticket whose result is `running` keeps that status and records its job ids in the ticket, as decision 5 asks; the run then ends with a ticket nothing here can advance, because the job poller is ticket 17. A result's `proposals`, `decision_requests` and `goal_progress` are written into the ticket's `## Result` section and named on the way past, so nothing a worker returned is lost before tickets 37, 35, and 39 act on them.
- One resume per attempt (BRIEF 9.1): a result the schema refuses is resumed with the error, an acceptance the conductor ran itself is resumed with the failing commands and their output. A second failure fails the ticket and leaves its worktree and branch for the attempt that follows.
- The conductor never trusts the worker's acceptance file, and it integrates a branch, not a working tree: a worktree left with tracked changes, or with an untracked file inside the ticket's touch set, fails the ticket rather than being rebased. Untracked noise elsewhere (what a test command drops) is not held against the worker.
- `run` refuses to start when the project is not on `main`, or when `git status --porcelain` shows changes outside `research/`, and prints what to do about each. The branch is checked as well as the tree because the integration's fast-forward merges into whatever is checked out. The pin-mismatch refusal decision 5 also names is ticket 46's, which ships it with the tagging and the `upgrade` that fixes a mismatch.
- `roles/coder/` is the first role: `agent.md` carries the description and the system prompt with no `tools` field, `wayline.json` the tool lists of Implementation Decisions 4, and the conductor composes `agent.json` from them. Every role's `disallowed_tools` also names `mcp__*`, `Workflow`, `Skill`, and the scheduling tools, because `--settings` adds to the owner's configuration rather than replacing it (`docs/verification/m0.md`). A project overrides a role's words in `.claude/agents/<role>.md`, never its tool lists.
- `wayline.worker` assembles the prompt in the order of Implementation Decisions 3: one `/wayline-<skill>` line per assigned skill, the ticket restated, the context pack under locator headers, the role protocol from `prompts/roles/`, the result schema rendered from the schema file itself, and the five contract lines. A context-pack entry is a path, a `path:first-last` line range, or a `path#anchor` markdown section; the pack is cut at the tier's cap and every cut is announced where it happened.
- `fixtures/projects/one-ticket/` is a project with one trivial `code` ticket and the fake script that satisfies it. The suite runs the whole path on it, and `README.md` there is the three commands that run it from a shell.
- `wayline.project.policy_for` is the one place the global `policy.json` and a project's `harness.json` overrides are merged; `wayline accept` now reads its timeout through it.

`init` lays out a project and `status` reads it (ticket 02, M0 Skeleton).

- `wayline init <path>` lays out the project of Implementation Decisions 1: the `CLAUDE.md` block (appended between markers, never overwriting an existing file, refreshed when the pin moves), `harness.json` with the pin and the defaults of Implementation Decisions 14, the `research/` tree with the `INTAKE.md` template and empty `journal.jsonl`, `findings.jsonl`, `manifest.json`, and `graph.json`, the four `.gitignore` entries, `.claude/` symlinks to the harness skills and workflow scripts, a fresh git repository on `main` with a first commit when the project directory is not itself the root of a work tree, an entry in `~/.wayline/projects.json`, and `~/.wayline/active`. A project laid out inside someone else's repository gets its own and is told so, because the conductor's worktrees branch from the project's own `main`.
- `init` is idempotent: a second run on the same path changes nothing (a test hashes the tree before and after), keeps an owner-edited `harness.json`, `CLAUDE.md`, and `.gitignore`, replaces a symlink that points at another harness checkout, removes a symlink whose harness target is gone, and leaves a local skill that is not a symlink alone.
- `wayline status [--project <path>] [--json]` prints the frontier, the running tickets and jobs, the open decision tickets, the window, the goal progress, the last ten journal events, and the ticket counts, for the active project or the one the flag names. A ledger it cannot read becomes a reported problem and a nonzero exit, never a traceback.
- `wayline switch <path>` moves the pointer and journals `switched` in both projects.
- `wayline.tickets` reads `tickets/NN-slug.md` (the file name must agree with the id), writes them through the ledger, and regenerates `graph.json` from an `os.scandir` snapshot of `tickets/` with the scheduling fields only; a `pinned_difficulty` wins over the ticket's difficulty, the attempt counter comes from the journal's `ticket_launched` events, and a blocking cycle, an unknown blocker, or a duplicate id is refused.
- `templates/project/` holds what `init` lays down; `fixtures/ledger/` is a project whose ledger holds tickets in every status, two jobs, a goal, and a journal longer than the ten events `status` prints.
- `~/.wayline` can be moved with `WAYLINE_HOME`, so the suite never touches the owner's pointers.
- A review pass fixed six defects before the ticket landed: a malformed `graph.json` reaching the frontier computation, trailing padding on rendered status lines, a recovered `.gitignore` entry landing outside its header, a `CLAUDE.md` block with no closing marker needing three runs to converge, `harness.json` reading the shipped `policy.json` rather than the checkout's, and a project inside another repository getting no repository of its own.

The guards, the per-launch settings, and `wayline accept` (ticket 04, M0 Skeleton).

- `hooks/touch_set_guard.sh` and `hooks/stop_guard.sh` are the scripts `research-notes/03-hooks/` validated, carried over byte for byte; a test asserts they stay identical.
- `hooks/command_guard.sh` is new: it reads `tool_input.command` and normalizes it before matching. It strips leading assignments, the shell's own reserved words and brace groups, and the `env`, `sudo`, `nice`, `xargs`, `timeout`, `flock`, `command` and `watch` wrappers; it follows `sh -c`, `bash -c`, `eval` and `env -S` bodies, a here-string or heredoc read by a shell, command substitutions, backticks and process substitutions; it splits pipelines and `&&` and `;` segments, reads redirection targets, drops heredoc bodies as data, and takes the basename of an absolute program path. It exits 2 on `git push` in any spelling including `git -C` and `send-pack`, `git reset --hard` under any legal abbreviation, `git clean -f`, `git branch -D` and its short pair, `git worktree remove`, an `rm` target outside the touch set, `find -delete`, `chmod -R`, `truncate`, `dd` writing outside the worktree, an upload flag on `curl` or `wget` including attached-value spellings, `twine`, `pip upload` and their `uv`, `uvx`, `pipx`, `poetry` and `hatch` spellings, `gh pr`, `gh release`, `gh api` with a write method, `rsync` to another host or with `--delete`, and any write target resolving outside the worktree, `results/` and the temporary directory.
- The guard fails closed where it cannot see: a target path hidden behind a variable or a substitution, an `rm` whose targets arrive on stdin from an `xargs` pipeline, a pipe into a shell, a `cd` out of the worktree (which would move the base every relative path resolves against), a command longer than 20000 characters, one nesting more than 64 sub-commands, and one whose lexing would cost more than the budget. The budget matters because a timed-out `PreToolUse` hook does not block, so a guard that ran past the handler timeout would fail open.
- The temporary directory joins the worktree and `results/` as a write root, which widens Implementation Decisions 4 on purpose: scratch output is routine and a temporary file is not data. `WAYLINE_ALLOWED_ROOTS` widens the set further per launch.
- `hooks/worker-settings.json` is the settings template of Implementation Decisions 4 with the `permissions.deny` first layer; `wayline.gates.worker_settings` renders it with `${CLAUDE_PROJECT_DIR}` replaced by the absolute harness path and refuses a template whose handlers have lost `args: []` or the 30 second timeout.
- `wayline accept` runs the ticket's `acceptance.machine` commands with `shell=True` in the current worktree under `policy.acceptance_timeout_s` and writes `TICKET_ACCEPTANCE_FILE` with `ran_at`, `where`, `results` and `pass`, whether they passed or failed, so the stop guard unblocks either way. A command that outlives the timeout has its process group killed and reports exit code 124; one that leaves a process behind holding its output has that output dropped rather than waited on, so `wayline accept` always returns. The file is written by rename, because the stop guard tests only that it exists.
- The guards are tested through piped stdin: the 14 cases `research-notes/03-hook-shape.md` Section 6 recorded, plus 129 command cases, every listed pattern in a benign spelling that passes and the dangerous spellings a `permissions.deny` rule misses.
- `docs/verification/m0.md` records the two live launches that prove the hooks apply under `--permission-mode dontAsk`.

## v0.0.0 (2026-09-12)

The package skeleton (ticket 01, M0 Skeleton).

- `bin/wayline` and `python -m wayline` print the tag and the verb table of Implementation Decisions 1; every verb exits 2 with "not yet implemented" until its ticket lands.
- The module set of Implementation Decisions 1 exists; four are real (`cli`, `frontmatter`, `jsonschema`, `ledger`), the rest are importable stubs that name the ticket that builds them.
- `policy.json` ships the initial values of Implementation Decisions 14 and validates against `schemas/policy.json`.
- Schemas `journal_event`, `ticket`, `result`, `harness`, `policy`, `job`, `manifest`, and `decision`, restricted to the validator's subset, each with valid and invalid examples under `tests/examples/`.
- `wayline.frontmatter` parses and writes the flat YAML subset of Implementation Decisions 2 with line-numbered rejections; the BRIEF 8.2 ticket round-trips after one normalizing pass. Floats are accepted as scalars (a metric value must not silently become a string).
- `wayline.jsonschema` validates `type, required, properties, additionalProperties, enum, const, items, minItems, maxItems, minimum, maximum, pattern, oneOf, $ref` (same file) and reports the failing path; `check_schema` refuses any other keyword.
- `wayline.ledger` is the only writer under `research/`: `append_event`, `write_json`, `write_markdown`, `append_line`, all under `flock(research/.lock)`, JSON and markdown by write-then-rename, appends fsynced; the journal event vocabulary is constants, cross-checked against the spec's table by a test.
- The package imports only the standard library, and a test walks the import graph to keep it so.
