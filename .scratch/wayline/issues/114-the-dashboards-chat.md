# 114 - The dashboard's chat

**What to build:** The owner talks with a project in the dashboard, which becomes the main place to talk with it. One global collapsible panel holds the chat, full screen at phone width. Each project has one thread, chosen with a picker on the projects page. Every item in a view has a button that inserts its reference into the message, and the current view travels hidden with each message, so "drop this one" said under a plot means that plot.

Each message is one resumed `claude -p` in the project, launched through the worker seam on the chat's rung (`opus high` by default, changed by a `harness.json` setting). The session is resumed while the last message is under an hour old and otherwise started fresh from the digest. A project takes one message at a time, with later ones queued. The thread is kept on disk and gitignored, and the reply streams by polling. No standing process runs. The chat answers at every pacing level but a hit limit, and says so near `stop`.

A chat session runs the `wayline` skill of 109, with read tools on the project and only the verbs its routing table names: no edits, shell, web, or MCP, under `dontAsk`. Anything that needs a confirmation (a paper order, a consolidation, anything on the irreversible list) comes back as a card with Confirm and Not now, which the dashboard runs itself. A chat session therefore never runs an irreversible verb, and text injected into a document cannot change a budget or order the paper. A batch shows as text in the chat only at five items or fewer; a longer one is one line with its count and a link to the marks view. The first answer, in either place, settles an item.

Not part of this ticket:

- the routing table, the reference files, and the setup conversation, which are 109's;
- the marks view, which is 112's;
- the cards' new actions on the views themselves (order, consolidation, make public as buttons in the Paper view, the reference hand-over form), which are 121's. This ticket renders and runs a card the chat returns.

**Blocked by:** 109 - The wayline skill and setup as one conversation; 110 - Dashboard: routes, the projects page, and the Research and Run views. It blocks 122.

**Status:** ready-for-agent

**GitHub:** PENDING

**Milestone:** M8 A paper that grows with the work (v1.1.0). **Spec:** Implementation Decision 17 (Talking with the project; The dashboard; Setup, at every autonomy; Vocabulary the build adds: the chat's rung in `harness.json`), 3 (the worker launcher, which the chat launches through), 8 (the dashboard), 1 (`harness.json`); M8 criterion 15; user stories 165, 166, 167, 168.

- [ ] The chat is one collapsible panel on every view, full screen at phone width, with one thread per project and a picker on the projects page; each item in a view carries a button that inserts its reference, and each message carries the current view hidden.
- [ ] A message launches one `claude -p` through the worker seam on the chat's rung from `harness.json` (default `opus high`), resuming the project's session while the last message is under an hour old and starting fresh from the digest otherwise; one message runs at a time per project and later ones queue in order.
- [ ] The thread is kept on disk under the project and gitignored; the reply streams to the panel by polling, and no process stays running between messages.
- [ ] The chat answers at every pacing level except a hit limit, where it says it cannot; near `stop` its reply says so.
- [ ] A chat session's launch request carries read tools on the project and only the verbs its routing table names, with no edit, shell, web, or MCP tools, under `dontAsk`; a test asserts on the `LaunchRequest`.
- [ ] A session that proposes a confirmed action returns a card (what will happen, what it costs, Confirm, Not now); Confirm runs the verb from the dashboard through its `ACTIONS` whitelist, never from the session; a chat session given a document that asks it to raise a budget or order the paper produces at most a card, never the action.
- [ ] A batch of five items or fewer shows as text in the chat; a larger one shows one line with its count and a link to the marks view; an item answered in either place shows as settled in the other.
- [ ] Tests: the fake launcher scripts the chat's sessions (a first message, a resumed one, one past the hour, a queued second message, a card); HTTP over a fixture ledger covers posting a message, polling the reply, the queue, a card's Confirm with and without the token, and the hidden view; the `harness.json` schema gains the chat's rung in the same commit, and the CHANGELOG `## Unreleased` entry and the documentation site describe the chat.
- [ ] Live through the tunnel: a message from the phone recorded, its reply, a resumed follow-up, and one card confirmed; recorded in `docs/verification/m8.md`.
- [ ] `python -m unittest` passes.
