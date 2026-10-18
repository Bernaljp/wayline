# 105 - References rendered and important ones raised

**What to build:** The owner reads one References section that is always current, and is asked about a reference only when they can help.

After every render, code writes two files:

- `research/sections/references.md`: entries numbered by first citation through the sections in outline order. Each entry gives authors to three then "et al.", the year, title, venue, identifier, and a link to the dossier. A **Not yet resolved** list follows, giving each work as "to the scout", "retrying" with the service and date, "gave up", or "claim kept, to be resolved".
- `research/references.json`: CSL-JSON built from the dossiers.

Before the order, the linter lists an unresolved citation and never fails it. The account's Library gains a pointer to the Not yet resolved list.

An unresolved reference is **important** when the owner named it, or when a standing passage, a concern, or an objective cites it. It is raised once its failure is final, never while it is still retrying. A failure is final when no service matches it anywhere, when the `retry` flag gave up, or when it is a URL no service can look up. How it is raised depends on the autonomy:

- under `interactive`: a notice linking to it, a line under "Waiting on you", and the first item of the next conversation;
- under `checkpoints`: a line under "Waiting on you", put to the owner at the next conversation or with the end notice;
- under `autonomous`: asked at setup only, where the setup batch includes the ones still retrying, and afterward listed but never notified.

The owner's hand-over (a DOI, a title, a PDF, or "leave it") is 71's command. "Leave it" settles the item until the order.

Not part of this ticket:

- the scout's outcomes, the retry flag, and the hand-over command (71);
- `wayline scout` for workers and the check at acceptance (98);
- the order's last live retry and the rule that a compilation never cites an unresolved work (118);
- the dashboard's hand-over form (121) and the References row in the Paper view (111).

**Blocked by:**
- 89 - The account
- 98 - References during a ticket
- 104 - The outline

It blocks 109, 111, 115, and 121.

**Status:** ready-for-agent

**GitHub:** [#252](https://github.com/Bernaljp/wayline/issues/252) (mirror; the local file is the source)

**Milestone:** M8 A paper that grows with the work (v1.1.0). **Spec:** Implementation Decision 17 (a reference found during a ticket: what code writes after every render; the scout's outcomes, cache, and joins: important unresolved references and how each autonomy raises them; the account: Library and Waiting on you; talking with the project: notices); milestone M8 criteria 11 and 12; user stories 146, 147, and 162.

- [ ] After every render, code writes `references.md` with entries numbered by first citation through the sections in outline order, in the stated entry shape, each linking to its dossier.
- [ ] `references.md` ends with a Not yet resolved list that gives each unresolved cited work one of the four states, and "retrying" names the service and the date.
- [ ] `research/references.json` holds CSL-JSON built from the dossiers of the cited works only.
- [ ] Before the order, the linter lists an unresolved citation in a section and never fails it.
- [ ] A reference counts as important when the owner named it or a standing passage, a concern, or an objective cites it, and only then.
- [ ] It is raised only when its failure is final, never while retrying:
  - under `interactive`: a notice with the item's link, a "Waiting on you" line, and the next conversation's first item;
  - under `checkpoints`: "Waiting on you", put at the next conversation or with the end notice;
  - under `autonomous`: setup only, then listed with no notice.
- [ ] Each important reference is raised once, and an item the owner settled with "leave it" is not raised again before the order.
- [ ] The account's Library gives the count of unresolved references and points to References' Not yet resolved list. "Waiting on you" lists each important one raised.
- [ ] Tests:
  - the render over a temporary project with fixture dossiers at L0, L1, and L2 and unresolved ones in each state, asserted on both files;
  - the raise rule under each autonomy by replaying journals that hold a retrying reference, its final failure, and a "leave it", asserted on the notices and events the next wave appends;
  - the linter's listing.
- [ ] The documentation site and the changelog's `## Unreleased` section describe References and when the owner is asked about a reference.
- [ ] `python -m unittest` passes.
