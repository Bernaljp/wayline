# 66 - The paper's figure text and captions

**What to build:** Inside `wayline paper`, what the figure role has to say about the text goes to the writer who is drafting that text, and no caption points to a figure the paper does not show.

The M7 run found both gaps (`docs/verification/m7.md`, "What differed from what the spec expected", items 3 and 4):

- **Text suggestions became tickets.** `figure_role._hand_on` files every `findings_for_text` entry as a `writing` proposal, and admission turns each into a `writing` ticket. The run filed tickets 70 to 81 in the toy project this way while the writer was drafting that same text.
- **A caption pointed to a lost figure.** The adjudication of build 7 found Figure 2's caption sending readers to "the ceiling_gap figure", a figure from an earlier draft.

Figures the paper asks for carry `figure_request.ticket: "paper"`, so the paper's own requests can be told from a ticket's. A figure a ticket asked for keeps today's path, with its proposals and `writing` tickets.

**Blocked by:** None - can start immediately. Every module it edits is built.

**Status:** done

**GitHub:** [#163](https://github.com/Bernaljp/wayline/issues/163) (mirror; the local file is the source)

**Milestone:** after M7 (v1.0.1). **Spec:** Implementation Decisions 13 (the figure role, the paper); ticket 53's live record in `docs/verification/m7.md`.

- [x] A figure the paper asked for files no proposal and opens no `writing` ticket. Its `findings_for_text` join the next build's list for the writer, each with the figure and the `manuscript_locator` it came from, and the build record keeps them.
- [x] A figure a ticket asked for still files its proposals as it does today.
- [x] The figure designer's prompt says that a caption describes its own figure and names no other, because cross-references between figures are the writer's, in the text.
- [x] Every build checks each placed caption. A caption that names the id of any other figure under the project's `figures/` fails the build. The next build sends that figure back to the figure role as a guided revision, whose change request drops the reference. A caption that names no other figure is never sent back.
- [x] Tests with the fake launcher:
  - a paper build whose figure returns `findings_for_text` lists them for the writer and admits no ticket;
  - a ticket's figure still admits its proposals;
  - a caption naming an earlier draft's figure fails its build and is revised on the next;
  - a caption naming no other figure passes.
- [x] The changelog names both changes under the next release.
- [x] `python -m unittest` passes.
