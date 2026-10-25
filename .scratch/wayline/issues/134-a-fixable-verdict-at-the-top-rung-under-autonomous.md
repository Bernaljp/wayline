# 134 - A fixable verdict at the top rung under autonomous

**What to build:** Under `autonomous`, a ticket on the rung ladder's top rung whose verdict names a concrete fix gets that fix tried before the run waits on the owner.

On the toy's live run (ticket 122, `docs/verification/m8.md`), two code tickets reached `needs_human` overnight with fixable findings. Ticket 52 (`toy.oracle`, difficulty 3, tiered up to rung 6) failed its machine acceptance and then a quality verdict: a test asserted a looser bound than its comment claimed. Ticket 115 (`toy.paired`, difficulty 4, so rung 6 from its first launch) failed its quality verdict on a missing `mkdir` for `--out` and a test that locked the missing parent in as an error. A ticket that starts on the top rung has only the resume and the split before `needs_human`, and a split of a one-module ticket recut the same work. Ticket 115 blocked the O1 and O4 analyses (96, 108, 113, 116 and what waits on them), so the objectives the stopping rule names could not close until the owner's stand-in ran `wayline rerun` on each. Ticket 116 (pairing the arms in `toy.paired`, difficulty 3 tiered to rung 6) followed the same way after a result verdict and a failed machine acceptance, and was rerun too. Ticket 122 (the E3 verdict analysis, holding O4) followed at 00:43Z: its quality verdict found three rule strings in `verdict.json` rewritten where the criterion kept every existing value. Four reruns by hand in one night.

- When a verdict's findings are concrete (a blocker naming a file and line and what the ticket asked), the next step on the top rung is a fresh attempt handed those findings, before `needs_human`; the verdict's findings travel with it the way ticket 68 made the tier up carry the failure.
- Under `autonomous`, a `needs_human` that blocks an objective the stopping rule names is listed in the account with the objectives it holds, and the end notice says the run is waiting on it rather than ending as if the frontier were empty.
- The escalation chain's order and the token-cost rule (split before tier up only onto Fable) stay as decision 16 says.

**Blocked by:** None - can start immediately. It edits the conductor's escalation step; 129 edits the wave, so the two should not run together.

**Status:** ready-for-agent

**GitHub:** [#341](https://github.com/Bernaljp/wayline/issues/341) (mirror; the local file is the source)

**Milestone:** after M8 (v1.1.x). **Spec:** Implementation Decisions 5 (the escalation chain), 16 (the escalation chain by rung), 17 (the account; the stopping rule); ticket 68; ticket 122's live record.

- [ ] A recorded journal of a top-rung ticket failing a verdict with a concrete blocker launches one fresh attempt carrying the findings before `needs_human`; covered by replay with the fake launcher.
- [ ] The account names the objectives a `needs_human` ticket holds.
- [ ] `python -m unittest` passes.
