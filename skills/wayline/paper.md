# The paper order

The paper is made only on an explicit order. Until one, the project holds only its five sections and its reports:
the general report (`research/REPORT.md`) is always current, and nothing writes a paper on its own. The owner orders
the paper by saying so ("write the paper", "compile the paper", "make the manuscript"); "compile" said of a section
is a consolidation instead, and you ask one line when it is unclear which they mean.

## Confirm first, with the card

Before anything is ordered, show the card: run `wayline paper --project .` and relay what it prints. It is built by
code at no cost and launches nothing. It carries the readiness list (the open objectives, the outline's gaps, the
general report's last kill argument and its standing points, the results changed since their last drawing, the
inherited claims unchecked or unverifiable, the open contradictions, the unresolved references, the concerns kept
for the order, the outline's link, and the front matter not given yet) and the cost: about $35 to $40 for six
figures when the first build passes, and about $10 more for each build that fails.

Nothing on the card blocks the order. Say what it lists plainly, with your recommendation, and wait for the owner's
word. On their yes run `wayline paper --yes --project .`; on "not now" do nothing at all: no decision ticket, no
record. The dashboard shows the same card, and its Confirm runs the same order.

## What the order does

The order is a rest point. Running tickets finish, nothing new launches, the results changed since their last drawing
are drawn first, and the paper is composed from that commit; then the run resumes if it had not ended. With no run
going, the order starts a conductor for itself, whose run ends as the last one did. The order starts no research
ticket: a point that needs new evidence is an objective (`wayline objective add`), never part of the order.

Under `interactive` and `checkpoints` the order asks one batch before any writer launches, which `wayline paper --yes`
prints: each open contradiction (code's suggested side, or "a typo, fix it"), each unverifiable claim the owner might
keep (stated as not verified, with why), each unresolved reference (hand it over, drop it, or keep the claim marked
"to be resolved"), the outline's open proposals, and, when no inherited result is verified yet, whether to keep the
unchecked ones as stated (the default) or leave them out. Relay it as `wayline mark` prints it; each item has code's
default, and "take all defaults" is one answer: `wayline mark <batch> --defaults --project .`. A reference the owner
hands over is `wayline reference <slug> <doi> --project .`. Under `autonomous` no batch is asked of the owner.

Before the writer, code takes its own steps on `code/`: it copies the scripts behind the figures and the cited drawing
numbers into `code/figures/`, writes an environment file and a Dockerfile from the locks, tags `paper-N` on `main`, and
pushes the code repository's split with the tag (never forced, never made public). Each result whose code changed since
its run is re-run at the tag as a job, and the order waits for those jobs: a result whose numbers held stands, and one
whose numbers moved gets a ticket the run takes after the paper. The code-to-Methods check then runs over all of
`code/`, and what it finds goes to the writer. `PAPER.md` lists all of it under "Code at the order". A code repository
still private at the order is under "Waiting on you"; making it public is the owner's word alone.

One writer session then composes the whole paper from the outline and the sections, each part in its own file under
`research/paper/`: `title.md`, `abstract.md`, `introduction.md`, `results.md`, `discussion.md`, `methods.md`,
`supplement.md`, and `front.md`, each heading carrying its outline id; `tables/`, `references.json`, `alternatives/`
(the writer's three titles), and `PAPER.md`, the build report: the commit, each part with its version, the batch's
answers, what was left out and why, the owner's passages whose wording changed, what the writer proposes, and the
cost. Read `PAPER.md` to the owner when they ask how the paper stands; never compose or edit a part yourself.

When the owner picks one of the alternatives ("use the second title"), record it with `wayline paper choose title-2
--project .`: free, no card. Its text becomes the part's, text no alternative held is kept as the next alternative, and
each compilation is "made before" that part changed until it is compiled again or the paper is ordered again.

The figures come from the plots the owner marked, through code's figure plan: each main-text result gets one figure
holding every plot marked keep (or, with none marked keep, every plot its synthesis cites), with no panel cap; maybe
and unmarked plots go to its supplementary figure, and dropped plots never appear. The batch shows each figure's
planned panels (as planned, or to the supplement), each figure too large for one page (split, the default, or drop the
panels past the page to its supplementary figure), and each drawn result with no figure (no figure, the default, or a
figure from nothing). A figure from nothing is made only when the owner asks for one there. To change what a figure
holds, the owner marks its plots (keep, maybe, drop) before ordering. The figures land in `research/paper/figures/F<n>/`
and `S<n>/`, each with its `caption.md`, and `PAPER.md` gives each figure's plan line and what was left out.

A change the writer wanted to the outline is a proposal in `PAPER.md`, never a move: the owner makes it, or not, by
changing the outline (`wayline outline show` prints it). An owner's edit of a part file stands at the next order
unless what that part is made from changed. Each order makes a new version; the previous one is kept under
`research/paper/earlier/v<n>/`.

## The builds

Every build of the paper is tested before the owner reads it: the kill argument (told the general report's last
verdict), then the independent read, then sampled verdicts on the claims never sampled. A build that fails sends the
points still standing to the next build, a fresh writer session, with no ticket; an order runs at most three.
`PAPER.md` lists each gate of each build with its points. Read them to the owner when they ask how the paper stands.

After three failed builds the paper is not passed, and it is the owner's choice, which "Waiting on you" lists: three
more builds, keeping it as it is, or the points as objectives. Ask in one line with your recommendation, and on their
word run `wayline paper builds more --project .`, `wayline paper builds keep --project .`, or `wayline paper builds
objectives --project .`. Never choose for them.

An unverifiable inherited claim stays out of the paper unless the owner kept it in the batch, and then the paper
says it is not verified and why. The supplement ends with code's table of every inherited result's verdict and route.
When the project has critiques, `research/paper/response/<critique>.md` answers each point verbatim; it is the owner's
to send, never yours.

## The compilations

Once the paper is composed, code compiles it with no model call: the order asks the scout once more about every
unresolved work the paper cites, then writes `research/paper/compilations/plain/`: the LaTeX, the PDF, a `.docx`, and
a Markdown copy. A work still unresolved is never cited; its claim is kept marked "to be resolved", or dropped, as the
batch answered. When the owner names a venue with the order ("for Nature Methods"), confirm with
`wayline paper --yes --for <venue> --project .`, the venue being a slug under the harness's `guidelines/`, and the order
also writes `compilations/<venue>/`, typeset and checked under that venue's guidelines with its citation style. A
paper over a venue's limit gets one fitting session (about $3) that cuts text or moves it to the supplement, adding no
claim; the venue-free paper stays as it is. Each compilation's `compilation.json` says what was made, the checks on the
compiled output, and what was cut.

Compiling for another venue later is a compilation alone, behind its own card: run `wayline paper compile <venue>
--project .` and relay the card; on the owner's yes run `wayline paper compile <venue> --yes --project .`. Nothing is
submitted anywhere.

## The front matter

The authors with their affiliations, the corresponding author, the acknowledgments, the funding, and the competing
interests are the owner's, asked once at setup at every autonomy and answerable at any time later; until said, each
is a marked placeholder in `front.md`. Record what they give as one JSON object on stdin:

```bash
wayline paper front - --project . <<'EOF'
{"authors": [{"name": "Ada Lovelace", "affiliations": ["Analytical Engines Ltd"], "corresponding": true,
  "email": "ada@example.org"}], "funding": "None.", "competing_interests": "None declared."}
EOF
```

The data and code availability statements are code's, written from the records; never write them for the owner.
