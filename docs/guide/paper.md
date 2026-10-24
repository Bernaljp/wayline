# The paper

Until a paper order, a project holds only its five sections and its reports. The paper is made only on an explicit
order: yours, or the decider's at the end of an `autonomous` run when you said yes at setup.

## The five sections and their passages

The **sections** are `research/sections/introduction.md`, `results.md`, `discussion.md`, `methods.md`, and
`references.md`, present from `wayline init` and rendered by code after every integration; no model edits them. Each
is made of **passages** (`P1` onward, in `research/passages.jsonl`), each with its provenance and who contributed it: a
ticket, you, a document, or a consolidation. A later passage replaces an earlier one without deleting it. Every claim
sentence ends with a provenance tag that must resolve: `{res:...}` (a run's output), `{ref:...}` (a reference),
`{code:<path>#<symbol>}` (the project's code), `{doc:D1#p4.s2}` (inherited text), or `{plot:R4.3}`.

Say "put this in the Discussion under Limitations: ..." and the session records your passage. A ticket that replaces
one of your passages must carry evidence and a reason; it is listed under "Changed without asking you" in the account,
and under `interactive` you are told.

## Editing a section

Edit `research/sections/<section>.md` directly, or use the edit button in the dashboard's Paper view (Introduction,
Results, Discussion, Methods, and the outline). Before the next render code reads your edit by the file's render stamp:
a new paragraph becomes your passage, a changed one your replacement, a removed one a withdrawal. If code rendered the
file again meanwhile, the dashboard shows both versions and saves only on your choice. A reason in Methods' parameter
table is edited in its row.

## Consolidation

Ask "make the Discussion shorter" (or "compile the Discussion") and the session offers a **consolidation**: one writer
session rewrites the section's current passages into fewer that keep every tag. It shows what the session reads and
about how many tokens first, and runs only on your yes. It is refused inside an automated run and on Results.

## The outline

`research/OUTLINE.md` is the proposed shape of the paper, built by code at every render: the storyline of the
objectives, the gaps (an empty main-text gap list is what the paper order calls complete), each section's headings in
order, Supplement and Cut, and "Proposed, not settled". Change it by saying so ("put R3 before R2", "move R5 to the
supplement", "note on R2: ...") or by editing the file. What you set, kept in `research/outline.json`, always wins:
placed lines never move. Code may propose merging results whose headings sit close, as a batch you take or decline.

## References

A work enters References only by being cited. `research/sections/references.md` numbers the cited works, then a
**Not yet resolved** list giving each one as "to the scout", "retrying", "gave up", or "claim kept, to be resolved".
The scout records each lookup as found, no match, or failed; a failure sets a retry flag, retried at most once a day,
giving up after `policy.scout.give_up_days` (7).

You are asked about an unresolved reference only when it is important (you named it, or a standing passage, a
concern, or an objective cites it) and only once its failure is final. Hand it over by saying its DOI or exact title,
dropping its PDF in the dashboard's form, or "leave it" until the paper order. By autonomy:

- `interactive`: a notice, a line under "Waiting on you", and the first item of your next conversation.
- `checkpoints`: the line, and it is raised at the next conversation or in the end notice.
- `autonomous`: setup asks about every important one, those still retrying included; afterwards it is listed, never
  notified.

Workers check a work as they cite it with `wayline scout <identifier>` (a DOI, arXiv id, or exact title), and the
surveyor of a `lit` ticket searches the literature with `wayline scout search "<query>"`. Ask for a literature search
and the session files a `lit` ticket.

## Methods and the code repository

Everything the project publishes lives under `code/`. At each acceptance a check reads the ticket's diff and sends the
worker back when Methods and the code disagree: a developed method needs a `code` tag in Methods, a known library method
must be named, and a non-default parameter needs a one-sentence reason. Methods carries a generated parameter table,
the software versions from the locks, and proposed citations. `code/REPRODUCE.md` lists each cited run with its
command, commit, inputs, and outputs.

The **code repository** is cut from `code/` and pushed by code to a private GitHub repository (setup's seventh
question sets its shape, license, and remote). Making it public is your word only: the session confirms it with a card,
and the decider never may.

## The paper order

Say "write the paper" (or "compile the paper"). The session shows the order's card first, built by code at no cost:
the readiness list (open objectives, outline gaps, the last kill argument, results changed since their drawing,
unchecked inherited claims, open contradictions, unresolved references, concerns for the order, the front matter not
yet given) and the cost (about $35 to $40 for six figures when the first build passes, about $10 more per failed
build). Nothing on it blocks the order; it runs on your yes. The dashboard's Paper view has the same card.

The order is a rest point: running tickets finish, changed results are drawn, code commits the figure scripts and
environment files under `code/`, tags `paper-N`, and re-runs results whose code changed. Under `interactive` and
`checkpoints` it asks one batch first (contradictions, unverifiable claims to keep, unresolved references, the outline's
proposals, each figure's planned panels); every item has code's default, and "take all defaults" is one answer. Under
`autonomous` the decider answers that batch and picks among the alternatives, each choice listed under "Decided for
you"; reversing one makes the paper order yours from then on.

The **figures** come from the plots you marked keep through code's figure plan, with no panel cap. One writer session
composes the parts under `research/paper/`: `title.md`, `abstract.md`, the sections, `supplement.md`, `front.md`,
`alternatives/` (three titles), and `PAPER.md`, the build report. Say "use the second title" to choose an alternative.
Each order makes a new version, the previous one under `research/paper/earlier/`.

## Builds and compilations

Each **build** is tested before you read it: the kill argument, an independent read, and sampled verdicts. A failed
build's points go to the next build; an order runs at most three. After three, the paper is not passed and you choose:
three more builds, keep it as it is, or turn the points into objectives (under `autonomous` it waits under "Waiting on
you").

Each order then makes **compilations** with no model call: `research/paper/compilations/plain/` and, for a venue you
named ("for Nature Methods"), `compilations/<venue>/` (a slug under `guidelines/`), each as LaTeX, a PDF, a `.docx`, and
a Markdown copy. A paper over a venue's limit gets one fitting session that adds no claim. Ask later for another venue
and it is compiled behind its own card. The dashboard's Paper view offers downloads of each. Nothing is ever submitted.
Outside `autonomous` you are notified when an order ends.

The front matter (authors, affiliations, corresponding author, acknowledgments, funding, competing interests) is
setup's ninth question and can be given any time; until then it is a marked placeholder.

## Verbs the session runs

`wayline passage add --section <s> --heading <h> "<text>"`, `wayline edit <section|outline>`,
`wayline consolidate <section>` (then with `--yes`), `wayline outline show`, `wayline outline move <item> --before <item>`,
`wayline outline place <item> main`, `wayline outline note <item> "<text>"`, `wayline outline heading <section> "<heading>"`,
`wayline reference` (what waits on you) and `wayline reference <slug> <doi|title|file.pdf|"leave it">`,
`wayline paper` (the card), `wayline paper --yes` (with `--for <venue>`), `wayline paper compile <venue>`,
`wayline paper builds more|keep|objectives`, `wayline paper choose <part>-<n>`, `wayline paper front -`, and
`wayline mark <batch> --defaults`.
