# 95 - Repeated claims

**What to build:** A claim made in several places is one passage citing every occurrence's `doc` tag and every work any occurrence cites. Merging never loses content, and contradictions are listed rather than resolved for the owner.

At setup, two checks run over each inherited set:

- one consistency read on `opus high` finds repeat groups and contradictions;
- the local embedding model (BAAI/bge-base-en-v1.5, installed by "75 - The harness's tools", no tokens) proposes pairwise repeats. A confirmer on Opus, seeing each sentence's heading, labels each pair the same, contradicting, or different.

TF-IDF and Haiku leave this check. A merge stays automatic, but its kept text (the fuller occurrence verbatim, or a sentence combined from both) must cover every occurrence. The confirmer checks that nothing is lost, and code checks that nothing is added: no number, symbol, or citation that neither occurrence has. When either check fails, the occurrences stay apart, with no fallback to one of them. A pair kept apart may carry a flag that lists it for the grill. Contradicting pairs both stay, listed for the grill and for the verification of the result they touch.

The setup's merges and contradictions are items in a batch of "79 - Batches and marks". A merge item offers right or split, and a contradiction item offers real or not a contradiction. Each merge is also listed for the owner under "Changed without asking you" in the account.

At each ticket's acceptance, the embedding net and the same confirmer run on the ticket's new passages and findings. One that repeats a current passage without naming it in `replaces` is sent back to the worker. Text the harness writes from inherited passages (a combined merge, a later replacement) is allowed.

Not part of this ticket:

- the marks view that shows these batches, which is "112 - Dashboard: the marks view";
- the Inherited view's lists of merges and contradicting pairs, which is "111 - Dashboard: the Paper and Inherited views".

**Blocked by:** 75 - The harness's tools; 79 - Batches and marks; 93 - Inherited passages. It blocks 111 and 112.

**Status:** done

**GitHub:** [#242](https://github.com/Bernaljp/wayline/issues/242) (mirror; the local file is the source)

**Milestone:** M8 A paper that grows with the work (v1.1.0). **Spec:** Implementation Decision 17 (Inherited passages and repeated claims; Setup, at every autonomy: the merges and contradictions batch); Implementation Decision 14 (the policy table: the consistency read's and confirmer's rungs, if they land as policy); M8 criterion 9; user story 138.

- [x] At setup, one consistency read on `opus high` per inherited set returns repeat groups and contradictions, through the launcher.
- [x] The embedding model proposes pairwise repeats with no tokens. The Opus confirmer labels each pair same, contradicting, or different, and sees each sentence's heading.
- [x] A merge writes one passage whose kept text is either occurrence verbatim or a combined sentence, citing every occurrence's `doc` tag and every work any cites. The confirmer's no-loss check and code's no-addition check (numbers, symbols, citations) both pass, or the occurrences stay apart with no fallback.
- [x] A pair kept apart can carry a flag listing it for the grill. Contradicting pairs both stay, listed for the grill and attached to the verification of the result they touch.
- [x] The merges and contradictions form one batch of ticket 79 with the marks right or split, and real or not a contradiction. A split mark undoes the merge and restores both passages, and the merges appear in the account under "Changed without asking you".
- [x] At acceptance, a ticket's new passage or finding that repeats a current passage without naming it in `replaces` sends the worker back with the passage it repeats.
- [x] The old TF-IDF pre-filter and Haiku confirmer are removed from this path.
- [x] Tests on the ledger seam over a temporary project with the synthetic start-midway project of ticket 78. The consistency read and the confirmer are scripted through the fake launcher, and the embedding model runs through the tool runner's recordings. They cover merges that pass, a merge refused by each check, a contradiction, a flagged pair, the batch and its marks, and the acceptance check sending a worker back.
- [x] Any policy key added (rungs, thresholds) lands in decision 14's table in the same commit.
- [x] `python -m unittest` passes.
