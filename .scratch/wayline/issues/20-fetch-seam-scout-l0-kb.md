# 20 - Fetch seam, scout, L0 records, and the knowledge base

**What to build:** Every reference the owner names or the harness finds gets an L0 record at near-zero cost: verified identifiers through the keyless API chain, an abstract, and a knowledge-base node, with a reference that resolves nowhere marked unresolved rather than fabricated. All network reads go through one `fetch` seam with a recording backend, so the scout, and later the arXiv source fetch, the plot index crawl, and the guidelines build, are testable offline.

**Blocked by:** 02 (init lays out a project and status reads it)

**Status:** ready-for-agent

**Milestone:** M3 Dossiers. **Spec:** Implementation Decisions 9 (levels, the scout, the knowledge base); Testing Decisions seam 5; research-notes 06 Section 3.

- [ ] `fetch(url, headers) -> Response` has a real backend on `urllib` and a recording backend that reads and writes `fixtures/fetch/<host>/<request hash>.json`; every outbound request carries `User-Agent: wayline/<tag> (mailto:<owner_email>)` with the email `init` asked for and stored in `harness.json`; per-host rate limits are enforced in the seam (Crossref 10 per second, arXiv one per 3 s on a single connection, OpenAlex sparingly, the galleries 1 per second).
- [ ] The scout resolves a DOI through Crossref `works/{doi}?mailto=`, then OpenAlex `works/doi:{doi}`, then Unpaywall `v2/{doi}?email=`, then Europe PMC for biomedical DOIs; a title through Crossref `works?query.bibliographic=` with `rows=3` and a title-similarity check in code, then OpenAlex `search=`, then Europe PMC `TITLE:`; an arXiv id through the arXiv API `query?id_list=`; bioRxiv and medRxiv through `api.biorxiv.org/details/{server}/{doi}/na/json`; Semantic Scholar is not called; every lookup is cached under `research/.cache/scout/` by request hash.
- [ ] A reference that resolves nowhere gets `existence: unresolved`, never `fabricated`; a resolved one gets `existence: verified` with the resolving source and the identifiers.
- [ ] `wayline absorb --level 0` reads the references in `INTAKE.md` (DOIs, arXiv ids, titles, URLs) and writes `refs/<slug>/dossier.json` at level 0 (metadata, abstract, identifiers, existence) and a knowledge-base node.
- [ ] `research/kb/nodes/<id>.json` holds papers, ideas, experiments, and claims; `edges.jsonl` holds typed edges (`extends, contradicts, tested_by, supports, refutes, uses, depends_on`); `query_pack.md` is regenerated under `policy.kb.query_pack_max_chars` and holds relations only, never dossier prose.
- [ ] Tests run the whole chain offline on recorded responses for a DOI, a title, an arXiv id, and a bioRxiv DOI, plus an unresolvable title; live: ten references from a sample intake get L0 records.
