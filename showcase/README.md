# The showcase

**[Open the showcase](https://bernaljp.github.io/wayline/)**: wayline's own dashboard over a finished run, read-only.
Every view, ticket, report, plot, and the paper are there as the run left them; the buttons and the chat are off.

## The run it shows

The M8 toy run (ticket 122), October 24 to 25, 2026, on wayline's v1.1.0 line before its release, on one workstation
(an RTX 3090 and 128 cores) under a Claude Code subscription. The full record, step by step and with every count, is
[docs/verification/m8.md](../docs/verification/m8.md#the-toy-overnight-on-v110-ticket-122-m8-criteria-14-15-16-19-and-21).

- **The question.** A small Python package (`toy`) generates a synthetic two-class problem. The objective: do feature
  interaction terms improve held-out AUROC, and by how much? Beside it a goal, a held-out AUROC of at least 0.82 by the
  project's own measure command, and two questions the setup's grill added.
- **Setup.** One conversation of eleven turns, from 13:42 to 14:53: the question, the goal, `autonomous`, the budgets,
  the stopping rule, the code repository, and the paper order. Then the run started.
- **The night.** 175 tickets were created (98 of them parked by six re-cuts of the plan), 73 ticket launches on Opus
  and Sonnet rungs, 201 verdicts, 65 decisions (51 by the decider), 21 GPU jobs, and 5,165 journal
  events: 502 sessions, $444.60 at API-equivalent prices, on the subscription.
- **What it found.** Yes, by about 0.087: over 20 paired replicates the same logistic model scores a mean held-out
  AUROC of 0.768 without the x3·x4 column and 0.855 with it (paired gain 0.0872, 95% interval 0.0843 to 0.0900), which
  is the generator's Bayes ceiling of 0.8555. With no interaction planted, the gain is -0.0003, inside a ±0.01 band.
  The goal was reached at 0.854.
- **The paper.** Ordered from the dashboard's chat the next morning, composed by the writer with three supplement
  figures by the figure role, and compiled for arXiv and as a plain document: "An explicit product column recovers a
  planted interaction: paired AUROC gains against the Bayes ceiling on one synthetic generator" (31 pages,
  [PDF](https://bernaljp.github.io/wayline/files/research/paper/compilations/arxiv/paper.pdf)). It did not pass its own
  gates: after its second build, 24 points of the independent read and the kill argument still stood.

## Read it honestly

- A Claude Code session stood in for the owner during the run: it held the setup conversation, and it made every hand
  change the night needed (reruns, budget raises, worker slots). The record lists each one under "What the sitting
  changed in the toy by hand". The owner checked the chat and the views from a phone afterwards.
- The run found sixteen things wrong with wayline itself, now tickets 125 to 140
  ([#332](https://github.com/Bernaljp/wayline/issues/332) to [#347](https://github.com/Bernaljp/wayline/issues/347)):
  among them a rejected login read as a model failure, verdicts run one at a time inside a wave, the plotter writing the
  wrong tag form, and the decider never judging the paper because the run ended with scope-downs open.
- Panels that read the machine live (the overview's slots and load) show the machine that built the showcase.

## Where to look

- **Research**: the objectives and their answers, the results R1 to R18, each result's current report with its plots,
  and the general report.
- **Paper**: the five sections, the outline, the paper order's two builds, and the compilations (PDF, Word, Markdown,
  LaTeX).
- **Run**: the account (what the decider decided for the owner, and why), the decisions, the ticket graph with each
  ticket's page and what its sessions returned, the change records the run's retrospectives wrote, every output with
  its download (the toy package's documentation site among them, which the run wrote and built), and the journal's
  last events.
- **Marks**: the plots and tables as the owner marks them.
- **The chat**: the conversation held with the project during the run.

## How it is made

`showcase/build.py` builds the site from this repository's own dashboard: it serves the snapshot of the run
(`toy.tar.xz`, described by `toy.json`) with the real server, asks it every GET the page makes, and writes the answers
beside the real page, unchanged but for one script, `replay.js`, which answers the page's requests from them. So the
showcase changes whenever the interface does:

- `.github/workflows/showcase.yml` builds it on every pull request and opens every view in Chrome, keeping a screenshot
  of each, and on every push to master builds it and publishes it to GitHub Pages.
- `tests/test_showcase.py` fails when the server gains a GET route the showcase does not account for (`COVERAGE`) or a
  view stops answering over the snapshot; `tests/test_showcase_browser.py` fails when the page asks for something no
  recording answers, an image does not load, or a view scrolls sideways at a phone's width.

The snapshot keeps every file the views read, the paper, the plots and figures, the documentation site, and the small
result files behind every number. It leaves out the session transcripts (620 of them, 198 MB; each ticket's page still
shows what its sessions returned), the raw result tables (732 files, 114 MB), and the machine's tick log, and it drops
the owner's address and the notifier from `harness.json`. A snapshot in which anything matches a secret's pattern is
refused.

- Build it: `python3 -m showcase.build _site`, then `python3 -m http.server -d _site` and open the address it prints.
- Make the snapshot again from a finished project: `python3 -m showcase.build --snapshot <project>`.
