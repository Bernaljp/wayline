# 79 - Batches and marks

**What to build:** One shared record for every batch of items the owner (or the decider) settles, so the producers of decision 17 put items in one place and the marks view and the conversation show and settle them the same way. Decision 17 names eight kinds of batch (plots, objective changes, the software ask, account review, merges, contradictions, concern placements, outline proposals) but no record for them; this prefactor is that record.

A **batch** has an id, a kind, a title, the decision ticket it answers when there is one, and its items. An **item** has an id, a reference to what it is about (a plot id, a proposal, a merge, and so on), the mark options its kind allows, code's default where the kind has one, an optional note, and its settled mark. The mark options per kind come from decision 17's marks view:

| Kind | Marks |
|---|---|
| plots | keep, maybe, drop |
| objective changes, software ask | approve, decline |
| account review | stand, reverse |
| merges | right, split |
| contradictions | real, not a contradiction |
| concern placements | take it, another place |
| outline proposals | take, decline |

`wayline mark <batch> <item> <mark> [--note <text>]` records a mark, journaled as `marked`, and is a function the dashboard calls in-process. A mark saves when given, with no submit; the first answer, from the marks view or the conversation, settles an item, and a later mark on a settled item is refused with what settled it. "Take all defaults" settles every open item that has a default in one call. A batch whose items are all settled is closed, and its producer reads the marks back. A note alone, with no mark, is kept on the item.

The batch module renders a batch as text for the conversation (whole items at five or fewer, otherwise one line with the count) so the `wayline` skill and the chat use one rendering.

Not part of this ticket:

- any producer: 82, 89, 91, 95, 96, 100, and 104 each put their own items in batches and act on the marks;
- the marks view in the dashboard, which shows each kind's item whole (112);
- the conversation's routing to `mark` (109).

**Blocked by:** None - can start immediately. It blocks 82, 89, 91, 95, 96, 100, 104, 109, and 112.

**Status:** ready-for-agent

**GitHub:** PENDING

**Milestone:** M8 A paper that grows with the work (v1.1.0). **Spec:** Implementation Decision 17 (the dashboard: the marks view's batches and marks; talking with the project: every batch goes to the marks view, the first answer settles an item, five items or fewer as text; vocabulary the build adds: `marked`), 1 (the verb table: the conversation's marks verb), 2 (the event table: `marked`), the schemas list (the batch record, a reading this cut makes where the spec is silent); M8 criterion 16 (the marks the view saves); user story 168.

- [ ] A batch record with the fields above is written through the ledger and has a schema in the schemas list; its kinds and their mark options are the table above.
- [ ] `wayline mark` records a mark and an optional note, journaled as `marked` with batch, item, mark, note, and who; a mark not allowed for the item's kind is refused.
- [ ] The first mark settles an item; a second is refused naming the first; a note alone is kept without settling.
- [ ] "Take all defaults" settles every open item with a default and leaves the rest open.
- [ ] A batch with every item settled is closed, and a producer can read each item's mark and note back.
- [ ] The text rendering shows whole items at five or fewer and one line with the count and a link otherwise.
- [ ] The verb table of decision 1 gains the marks verb and the event table of decision 2 gains `marked`, in the same commit.
- [ ] Tests over a temporary project through the ledger seam: a batch of each kind created and marked, a refused mark, first answer settling, take all defaults, closing, the text rendering at five and six items.
- [ ] `python -m unittest` passes.
