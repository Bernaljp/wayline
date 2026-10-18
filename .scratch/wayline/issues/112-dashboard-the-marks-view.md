# 112 - Dashboard: the marks view

**What to build:** A long batch can span several sittings. The marks view holds every open batch (79), and each item is shown whole:

- a plot: its SVG with its three explanations;
- a merge: its texts side by side;
- a proposal: its reason, evidence, feasibility, and judgment;
- every other kind with the fields its batch carries.

Each item has a note box and the marks its batch offers:

| Batch | Marks |
|---|---|
| plots | keep, maybe, drop |
| objective changes, the software ask | approve, decline |
| account review | stand, reverse |
| merges | right, split |
| contradictions | real, not a contradiction |
| concern placements | take it, or another place |
| outline proposals | take, decline |

A mark saves when clicked, with no submit, through the same `wayline mark` verb the conversation uses. The first answer in either place settles an item. "Take all defaults" answers a batch in one click. At phone width the view shows one item per screen.

Not part of this ticket:

- the batch record and the `marked` event (79);
- what each mark does once recorded, which belongs to the ticket owning its batch.

**Blocked by:**
- 79 - Batches and marks
- 82 - Project tools and the software decision
- 89 - The account
- 91 - Objective changes
- 95 - Repeated claims
- 96 - Critiques and concerns
- 100 - Drawings on the plotter
- 104 - The outline
- 110 - Dashboard: routes, the projects page, and the Research and Run views

It blocks 121.

**Status:** ready-for-agent

**GitHub:** [#259](https://github.com/Bernaljp/wayline/issues/259) (mirror; the local file is the source)

**Milestone:** M8 A paper that grows with the work (v1.1.0). **Spec:** Implementation Decision 17 (the dashboard: the marks view; talking with the project: batches; drawings and plots: the owner's marks), 8 (the dashboard: the `ACTIONS` whitelist); milestone M8 criteria 16 and 20; user stories 129 and 168.

- [ ] `#/<project>/marks` lists every open batch with its unsettled count. A settled item shows its mark and who settled it, the owner in the dashboard or in the conversation.
- [ ] Each batch kind renders its items whole as listed above. A plot shows its SVG from the drawing's artifacts, not a re-render.
- [ ] Clicking a mark calls the `mark` action, which runs the `wayline mark` verb and saves at once. A note saves with its item. A second click changes the mark until the batch's owner ticket acts on it.
- [ ] An item already settled in the conversation shows as settled, and the dashboard does not record a second answer.
- [ ] "Take all defaults" records each unsettled item's default in one action.
- [ ] At phone width the view shows one item per screen with next and previous, checked live and recorded in `docs/verification/m8.md`.
- [ ] The server's `ACTIONS` whitelist gains `mark` and nothing else. The action is token-guarded like the others.
- [ ] Tests, over HTTP against a fixture ledger holding one batch of each kind:
  - the view's JSON;
  - a mark saved per click and read back through the ledger;
  - a mark refused without the token;
  - an item settled first in the conversation;
  - "take all defaults".
- [ ] The documentation site and the changelog's `## Unreleased` section describe the marks view.
- [ ] `python -m unittest` passes.
