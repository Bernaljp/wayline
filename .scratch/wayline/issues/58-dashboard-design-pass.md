# 58 - A design pass over the dashboard

**What to build:** From the laptop, through the tunnel, the dashboard looks deliberate, and every view shares one visual style: the overview, the graph and the ticket pages, decisions, outputs, logs, and intake. Tables are sized to their content, and an empty table or list says so in words instead of drawing a bare header row. Nothing the dashboard shows or lets the owner do changes, and every endpoint, action, and read-only guarantee stays as Implementation Decisions 8 gives it. The design work is done with the ui-ux-pro-max skill. The ticket answers the owner's verdict from the M1 demo, recorded in `docs/verification/m1.md` under "Through the tunnel from the laptop, during a run". The page showed everything it had to show, but it was "not very good looking", and an empty table rendered as its header row stretched across the full width.

**Blocked by:** None - can start immediately. The dashboard tickets 11, 12, 35, and 42 are done.

**Status:** done

**GitHub:** [#114](https://github.com/Bernaljp/wayline/issues/114) (mirror; the local file is the source)

**Milestone:** M5 Overnight and report. **Spec:** Implementation Decisions 8 (the views, exposure, no build step), 1 (the layout of `dashboard/` with vendored marked and DOMPurify); the owner's reaction in `docs/verification/m1.md` (ticket 15).

- [x] **One visual style.** Every view (the overview, the graph and the ticket pages, decisions, outputs, logs, and intake) shares one style, designed with the ui-ux-pro-max skill. That means:
  - one type scale, one spacing scale, and one set of colors
  - tables sized to their content rather than stretched across the page
  - long values that wrap or truncate, with the full value available
  - a page that reads at a laptop's width
- [x] **Empty, loading, and error states.** Every empty table or list says so in words instead of drawing a header row with nothing under it. Loading and error states show in the panel they belong to.
- [x] **No build step and nothing fetched from outside the workstation.** The page, its stylesheet, and its scripts are served from `dashboard/`. marked and DOMPurify stay vendored at their pinned versions, with their digests in `VENDOR.md` unchanged.
- [x] **What the dashboard does stays the same.**
  - Every endpoint answers as before.
  - What is read-only today stays read-only.
  - Every action still requires the token.
  - Rendered markdown still passes through `DOMPurify.sanitize(marked.parse())`.
  - The existing dashboard tests pass.
- [ ] **Browser renders, recorded.** Every view is rendered in a real browser, before and after, over the fixture ledger and over a project during a live run. The screenshots and what changed are recorded in `docs/verification/m5.md`, and no render logs a console message at any level. (Done except for the word live: the renders over a running project were taken over a real conductor run driven by the fake launcher, since a live run spends the owner's weekly window. Everything else is in `docs/verification/m5.md` with the renders in `docs/verification/images/58/`, and the console is silent at every level, in both themes.)
- [x] **The owner accepts the look.** The owner opens the dashboard through `ssh -L` from the laptop and accepts it, and the owner's words are recorded beside the screenshots. (Accepted on 2026-09-16 at the fourth look: "Very good! finalize this ticket". Each look, in the owner's words, is in `docs/verification/m5.md`.)
