# 12 - Dashboard graph, ticket pages, and logs endpoints

**What to build:** The owner sees the ticket DAG drawn with status colors and the frontier highlighted, opens a page per ticket (frontmatter, context pack, result, findings, session and job logs), and tails worker streams and the tick log live, all read-only.

**Blocked by:** 11 (Read-only dashboard: transport, tabs, journal tail, overview (verbatim prototype 36))

**Status:** done

**GitHub:** [#13](https://github.com/Bernaljp/wayline/issues/13) (mirror; the local file is the source)

**Milestone:** M1 Frontier and windows. **Spec:** Implementation Decisions 8 (endpoints, views); research-notes 08 Section 5 (the 43-line layered layout).

- [x] `GET /api/projects/<id>/graph.svg` returns inline SVG from a server-side layered layout (longest-path layering, two barycenter sweeps, straight edges with an arrow marker, one link per node, status fills, the frontier highlighted); a 14-node, 18-edge fixture lays out into well-formed SVG under 10 KB.
- [x] `GET /api/projects/<id>/tickets` and `tickets/<id>` return the frontmatter, the body, the context pack list, the latest result, the findings, and the list of session and job logs for the ticket.
- [x] `GET /api/projects/<id>/logs/<kind>/<id>?since=<offset>` tails worker streams and the tick log by byte offset (job logs join with ticket 19).
- [x] The page renders the graph, opens ticket pages from nodes, and shows a log tail that polls every 2 s.
- [x] HTTP tests cover the SVG endpoint, the ticket pages, and the log tail over the fixture ledger.
