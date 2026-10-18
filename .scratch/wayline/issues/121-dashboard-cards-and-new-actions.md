# 121 - Dashboard: cards and new actions

**What to build:** Everything the owner can confirm in the chat, they can also start from a button on the dashboard, with no tokens spent. Buttons open the same confirmation cards the chat shows: order the paper (with its readiness list and cost), ask for a consolidation, and make the code repository public. A reference handed over takes a DOI or title field, a PDF drop, "drop it", or "keep the claim marked 'to be resolved'". A select in the Run view's controls sets the plotting library.

The Paper view gains the paper's parts, each with its version and alternatives, plus earlier versions and the compilations. Compilations offer downloads of the PDF, the `.docx`, the LaTeX directory as a `.zip`, and the Markdown copy. Choosing an alternative is free, and it marks the compilations "made before part X changed" until the next order. Compiling for another venue is a card. An order's end notifies outside `autonomous`.

Every write calls the CLI verb the conversation and a terminal use, so the server's `ACTIONS` whitelist grows by these actions and nothing else, each token-guarded like the others.

Not part of this ticket:

- the chat's cards, which are 114's (this ticket reuses the same card);
- the marks view, which is 112's;
- the editor, which is 113's.

**Blocked by:** 85 - The code repository; 88 - The owner's passages, consolidation, and the linter's new tags; 102 - The plotting library switch; 105 - References rendered and important ones raised; 112 - Dashboard: the marks view; 115 - The paper order and the paper's parts; 118 - Compilations. It blocks 122.

**Status:** ready-for-agent

**GitHub:** [#268](https://github.com/Bernaljp/wayline/issues/268) (mirror; the local file is the source)

**Milestone:** M8 A paper that grows with the work (v1.1.0). **Spec:** Implementation Decision 17 (The dashboard: buttons, the reference hand-over, the plotting select, compilations, alternatives; The paper order and what it compiles; Methods and the code: public on the owner's word), 8 (dashboard actions); M8 criterion 16; user stories 147, 157, 160, 167, 169.

- [ ] Order the paper, ask for a consolidation, and make the repository public each open a card with what will happen and its cost; Confirm calls the same verb the chat's card calls, Not now does nothing, and no model is launched by the card.
- [ ] The reference hand-over form accepts a DOI or title (back to the scout), a PDF drop (the reference's source), "drop it", or "keep the claim marked 'to be resolved'", each through its CLI verb.
- [ ] The Run view's select sets `harness.json.plotting` through `switch --plotting`.
- [ ] The Paper view lists the paper's parts with versions and alternatives, earlier versions, and each compilation with downloads of the PDF, `.docx`, LaTeX `.zip` (passing `zipfile.testzip`), and Markdown; choosing an alternative marks each compilation "made before part X changed".
- [ ] The `ACTIONS` whitelist gains exactly these actions, each refusing without the token; an order's end sends a notice outside `autonomous`.
- [ ] Tests: HTTP over a fixture ledger for every action with and without the token, the downloads with range and integrity checks, and the stale-compilation mark; built in the dashboard's designed style and usable at phone width.
- [ ] `python -m unittest` passes.
