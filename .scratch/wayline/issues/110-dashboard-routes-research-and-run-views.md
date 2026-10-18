# 110 - Dashboard: routes, the projects page, and the Research and Run views

**What to build:** The dashboard becomes five hash-routed views behind the project tabs. This ticket builds the routing, the link scheme, the projects page, the "Waiting on you" strip, and the first two views, Research and Run. The other three follow: Paper and Inherited (111) and Marks (112).

- **Links.** Every item has a link `#/<project>/<id>` that opens it in the popup viewer (74) over its view, so a phone notice lands on the item in one tap.
- **The "Waiting on you" strip** is on every view and mirrors the account's section. Its count also shows in the browser tab's title and on each project tab.
- **The projects page** lists each project with the account's standing line, its run state, and its waiting count. An old project at `research_version` 1 is listed read-only, marked with its tag, and its files open in the viewer.
- **Research** comes first. It shows:
  - the general report;
  - each objective with its status, its measure and kept values, and its lineage;
  - each objective's results, with the headline, the current and earlier reports, plots by id, and a "left out" row;
  - results beyond the objectives, set-aside claims, and tickets parked for a closed objective;
  - the plotting library in use.
- **Run** is today's page as it is, plus the account in the popup viewer and Software: `tools.json`, the MATLAB check's outcome, and the environment with any move in progress. New decision kinds (objective changes, software, the empty frontier, a concern to sort, a verification gap) get cards with their own fields.

Views are thin lists: id, title, status, view, insert into chat, and the item's action. Every Markdown file code renders is read only in the popup viewer, never rendered twice. A renewed current report shows a "new since you looked" dot and notifies nowhere. Every view this ticket builds works at phone width. The dashboard spends no tokens.

Not part of this ticket:

- the Paper and Inherited views (111);
- the marks view (112);
- the editor (113);
- the chat panel (114);
- the new confirmation cards and actions (121).

**Blocked by:**
- 72 - research_version and the big-upgrade refusal
- 74 - The document viewer: dialog, zoom, KaTeX math, and the sanitizer
- 82 - Project tools and the software decision
- 83 - Moving a project's environment
- 89 - The account
- 90 - Results and the general report
- 101 - Current and earlier reports

It blocks 111, 112, and 114.

**Status:** ready-for-agent

**GitHub:** [#257](https://github.com/Bernaljp/wayline/issues/257) (mirror; the local file is the source)

**Milestone:** M8 A paper that grows with the work (v1.1.0). **Spec:** Implementation Decision 17 (the dashboard: the five views, the strip, the projects page, thin lists, item links, phone width; upgrades: the old project listed read-only; tools: what Run's Software shows), 8 (the dashboard); milestone M8 criteria 16 and 18; user stories 169 and 173.

- [ ] The dashboard routes `#/<project>/research`, `#/<project>/run`, and the projects page by hash. The browser's back and forward buttons move between views, and reloading keeps the view.
- [ ] `#/<project>/<id>` opens that item in the popup viewer over its view, for every kind of id this ticket's views list:
  - objectives (O);
  - results (R);
  - plots (R4.3) and tables (R4.T1);
  - reports;
  - decision tickets and tickets;
  - the account.
  
  An unknown id shows a "not found" line, not an error page.
- [ ] The "Waiting on you" strip appears on every view with the account's items, and its count appears in the tab's title and on each project tab.
- [ ] The projects page lists each project with its standing line, run state, and waiting count. A project at `research_version` 1 is listed read-only, marked with its tag. Its files open in the viewer, and no action is offered for it.
- [ ] Research lists what is above, each item a thin row with its link. Reports, plots, and the account open only in the popup viewer.
- [ ] Run keeps today's page and adds the account in the viewer, Software (`tools.json`, the MATLAB check's outcome, the environment, and a move in progress), and cards for each new decision kind with its fields.
- [ ] A current report renewed since the owner last opened it shows the "new since you looked" dot, and no notice is sent.
- [ ] At a narrow window or phone width, every view this ticket builds keeps its content readable with no sideways scroll. Recorded live once in `docs/verification/m8.md`.
- [ ] Tests, over HTTP against a fixture ledger:
  - each route's JSON;
  - the strip's count;
  - the projects page with an old project;
  - `#/<project>/<id>` resolution for each kind;
  - ETag 304s on the new reads.
- [ ] The changelog's `## Unreleased` section describes the five views and item links.
- [ ] `python -m unittest` passes.
