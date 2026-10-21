"""The surveyor and `lit` tickets (Implementation Decision 17; ticket 99).

The literature is searched mid-run for each objective the Introduction does not yet cover. A `lit`
ticket runs on the **surveyor** role, at `policy.roles.surveyor` (`sonnet medium`) whatever its
difficulty, under the budget its rung gives, and it takes no tier up: the escalation chain goes from
its resume to the split and then to a person. The surveyor's tools are Read, Glob, Grep, `wayline
scout`, and `wayline consult`, and it returns Introduction passages tagged at `#abstract`, its
`references`, and proposals.

**The search** (`search`, the verb `wayline scout search "<query>"`, or `--citing <identifier>`). Code,
no tokens, always live and never cached: every request goes to the network through a fetcher with no
cache (`search_fetcher`), and nothing it finds is filed; the surveyor checks a work it means to cite
with `wayline scout <identifier>`, which files the dossier. A query asks arXiv, Crossref, and Europe
PMC, which are free, then OpenAlex, which costs USD 0.001 a request and is asked only while the day's
`policy.scout.openalex_per_day` requests last: code adds up the `openalex` count of the journal's
`scout_searched` events of the current UTC day, and refuses the request that would pass it, so a search
past the day's budget asks the three free services alone. The works citing a seed are Europe PMC's
citations of its PMID and OpenAlex's `cites:` filter on its OpenAlex id; a seed no dossier holds is
resolved live by the scout and not filed. Every work found is listed once (two services' answers about
one work are joined by DOI, arXiv id, or title) with the identifier `wayline scout` takes. A search under
`WAYLINE_TICKET` runs only for a `lit` ticket, is counted against `policy.scout.searches_per_ticket`, and is
refused past it before any request; every search is journaled as `scout_searched`.

**The tickets.** The planner cuts a `lit` ticket at specify (the graph's first cut, a revise of it, and a
replan, each of which takes back the open tickets) for each open objective no Introduction passage with a
`ref` tag covers (`uncovered`) and no kept `lit` ticket serves, one ticket serving several objectives that
share a literature; after an amendment for an added or reframed
objective that is uncovered (`specify.cut_amendment`, ticket 92); and on a worker's proposal or the
owner's word, which `proposals.KIND_ROLE` routes to the surveyor. Position's `missing_prior_work` is
searched at setup (`scout_missing`), and the first `lit` tickets, those of the graph's first cut or its
revise, are handed what it found in their context pack (`MISSING_LOCATOR`).
"""

import argparse
import json
import os
import re
import shlex
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ElementTree
from datetime import datetime, timezone
from pathlib import Path

from wayline.cli import parse_args
from wayline.fetch import FetchError, Fetcher, UrllibBackend
from wayline.ledger import SCOUT_SEARCHED, LedgerError, ledger_for
from wayline.tickets import LIT, TicketError, read_tickets
from wayline.project import ProjectError, find_project, policy_for, read_harness
from wayline.scout import (ARXIV_QUERY, CROSSREF_QUERY, EUROPEPMC_SEARCH, OPENALEX_SEARCH, OPENALEX_WORK, VERIFIED, Scout,
                           ScoutError, normalize_title, parse_reference)
from wayline.scout import (_arxiv_id_from_url, _bare_doi, _clean, _crossref_year, _first, _int, _person, _tail, _text,
                           _with)

__all__ = [
    "ROLE", "KIND", "DEFAULT_ROLE", "SEARCHES_PER_TICKET", "OPENALEX_PER_DAY", "ROWS", "SERVICES", "MISSING_LOCATOR",
    "SearchError", "SearchRefused", "role_tier", "search_limit", "openalex_limit", "searches_made", "openalex_today",
    "search_fetcher", "search", "render", "search_command", "uncovered", "scout_missing", "missing_scouted", "missing_lines",
]

ROLE = "surveyor"
KIND = LIT
DEFAULT_ROLE = {"model": "sonnet", "effort": "medium"}  # decision 14's, for a policy that names no `roles.surveyor`
SEARCHES_PER_TICKET = 20  # the fallback when a policy carries no `scout.searches_per_ticket`
OPENALEX_PER_DAY = 100    # the fallback when a policy carries no `scout.openalex_per_day`
ROWS = 5                  # the works one service is asked for in one search
SERVICES = ("arxiv", "crossref", "europepmc", "openalex")  # the free three first, then the one that costs
OPENALEX_HOST = "api.openalex.org"
EUROPEPMC_CITATIONS = "https://www.ebi.ac.uk/europepmc/webservices/rest/MED/%s/citations"
FOUND, NO_MATCH, FAILED, SKIPPED = "found", "no match", "failed", "skipped"
# Where the first `lit` tickets read what position's `missing_prior_work` search found (a `POSITION.md` heading).
MISSING_LOCATOR = "research/POSITION.md#what-the-references-lack"


class SearchError(ValueError):
    """A search nobody can ask: no query and no seed, or a seed that is a URL."""


class SearchRefused(SearchError):
    """The search past the ticket's `policy.scout.searches_per_ticket`."""


class _Spent(FetchError):
    """The OpenAlex request that would pass the day's `policy.scout.openalex_per_day`; it is never sent."""


# --- the policy ----------------------------------------------------------------------------------


def role_tier(policy):
    """`(model, effort)` a `lit` ticket runs at: `policy.roles.surveyor`, else decision 14's `sonnet medium`."""
    entry = dict(DEFAULT_ROLE, **(((policy or {}).get("roles") or {}).get(ROLE) or {}))
    return entry["model"], entry["effort"]


def _scout_policy(policy, key, default):
    try:
        return int(((policy or {}).get("scout") or {}).get(key, default))
    except (TypeError, ValueError):
        return default


def search_limit(policy):
    return _scout_policy(policy, "searches_per_ticket", SEARCHES_PER_TICKET)


def openalex_limit(policy):
    return _scout_policy(policy, "openalex_per_day", OPENALEX_PER_DAY)


# --- the counts, from the journal -----------------------------------------------------------------


def _counts(project_or_ledger, ticket, now):
    """`(searches made by ticket, OpenAlex requests made on the UTC day of now)`, from one read of the journal."""
    day = datetime.fromtimestamp(time.time() if now is None else now, timezone.utc).strftime("%Y-%m-%d")
    events, _ = ledger_for(project_or_ledger).read_events()
    made = total = 0
    for record in events:
        if record.get("event") != SCOUT_SEARCHED:
            continue
        if ticket is not None and record.get("ticket") == ticket:
            made += 1
        if str(record.get("ts") or "").startswith(day):
            try:
                total += int((record.get("payload") or {}).get("openalex") or 0)
            except (TypeError, ValueError):
                continue
    return made, total


def searches_made(project_or_ledger, ticket):
    """How many `scout_searched` events the journal holds for `ticket`."""
    return _counts(project_or_ledger, ticket, None)[0]


def openalex_today(project_or_ledger, now=None):
    """The OpenAlex requests the journal's searches made on the UTC day of `now` (epoch seconds; the present when None)."""
    return _counts(project_or_ledger, None, now)[1]


# --- the fetcher ----------------------------------------------------------------------------------


def search_fetcher(email=None):
    """The fetcher a search runs on: straight to the network, with no cache to read or write (always live)."""
    return Fetcher(UrllibBackend(), email=email)


class _Budgeted:
    """A fetcher that never replays and counts every OpenAlex request, refusing the one past the day's budget.

    `spent` reads the day's count from the journal again before each OpenAlex request, so a search another worker
    journaled since this one began counts too; only searches still in flight at that moment are unseen.
    """

    def __init__(self, fetcher, spent, limit):
        self.fetcher, self.spent, self.limit, self.asked, self.seen = fetcher, spent, limit, 0, None
        self.email = getattr(fetcher, "email", None)

    def fetch(self, url, headers=None, method="GET", replay=False):
        if urllib.parse.urlsplit(url).hostname == OPENALEX_HOST:
            self.seen = self.spent()
            if self.seen + self.asked >= self.limit:
                raise _Spent("the day's %d OpenAlex requests are spent (USD 0.001 each); the free services still answer" % self.limit)
            self.asked += 1
        return self.fetcher.fetch(url, headers=headers, method=method, replay=False)


# --- one service each -----------------------------------------------------------------------------


class _Asked:
    """What one service said: its outcome, the works it found, and a note."""

    def __init__(self, outcome, works=(), note=None):
        self.outcome, self.works, self.note = outcome, list(works), note


def _ask(fetcher, url, read):
    """One request and its reader: `found` with the works, `no match`, `failed` on a status or an unreadable answer, `skipped` when spent."""
    try:
        answer = fetcher.fetch(url)
    except _Spent as spent:
        return _Asked(SKIPPED, note=str(spent))
    except FetchError as failure:
        return _Asked(FAILED, note=str(failure))
    if not answer.ok:
        return _Asked(FAILED, note="status %d" % answer.status)
    try:
        works = read(answer)
    except (ValueError, TypeError, AttributeError, ElementTree.ParseError):
        works = None
    if works is None:
        return _Asked(FAILED, note="an unreadable answer")
    works = [work for work in works if work.get("title")]
    return _Asked(FOUND, works) if works else _Asked(NO_MATCH)


def _work(source, title, authors=(), year=None, venue=None, doi=None, arxiv_id=None, pmid=None):
    return {"title": _clean(title), "authors": [name for name in (authors or []) if name], "year": _int(year) if year else None,
            "venue": _clean(venue), "doi": (_bare_doi(doi) or None) if doi else None, "arxiv_id": arxiv_id, "pmid": pmid,
            "sources": [source]}


def _json(answer):
    payload = answer.json()
    if not isinstance(payload, dict):
        raise ValueError("not a JSON object")
    return payload


def _read_arxiv(answer):
    feed = ElementTree.fromstring(answer.body)
    atom, arxiv = "{http://www.w3.org/2005/Atom}", "{http://arxiv.org/schemas/atom}"
    works = []
    for entry in feed.findall(atom + "entry"):
        absolute = _text(entry.find(atom + "id")) or ""
        if "api/errors" in absolute:
            continue
        identifier = _arxiv_id_from_url(absolute)
        bare = re.sub(r"v\d+$", "", identifier) if identifier else None  # a search lists the work, never a version of it
        works.append(_work("arxiv", _text(entry.find(atom + "title")),
                           [_text(author.find(atom + "name")) for author in entry.findall(atom + "author")],
                           (_text(entry.find(atom + "published")) or "")[:4], _text(entry.find(arxiv + "journal_ref")) or "arXiv",
                           doi=_text(entry.find(arxiv + "doi")), arxiv_id=bare))
    return works


def _read_crossref(answer):
    items = ((_json(answer).get("message") or {}).get("items")) or []
    return [_work("crossref", _first(item.get("title")), [_person(author) for author in item.get("author") or []],
                  _crossref_year(item), _first(item.get("container-title")), doi=item.get("DOI"))
            for item in items if isinstance(item, dict)]


def _read_europepmc(answer):
    results = ((_json(answer).get("resultList") or {}).get("result")) or []
    return [_work("europepmc", str(item.get("title") or "").rstrip("."), _split_authors(item.get("authorString")),
                  item.get("pubYear"), item.get("journalTitle"), doi=item.get("doi"), pmid=item.get("pmid"))
            for item in results if isinstance(item, dict)]


def _read_citations(answer):
    citations = ((_json(answer).get("citationList") or {}).get("citation")) or []
    return [_work("europepmc", str(item.get("title") or "").rstrip("."), _split_authors(item.get("authorString")),
                  item.get("pubYear"), item.get("journalAbbreviation"), doi=item.get("doi"),
                  pmid=item.get("id") if item.get("source") == "MED" else None)
            for item in citations if isinstance(item, dict)]


def _read_openalex(answer):
    results = _json(answer).get("results") or []
    return [_work("openalex", item.get("display_name") or item.get("title"),
                  [(entry.get("author") or {}).get("display_name") for entry in item.get("authorships") or []],
                  item.get("publication_year"), ((item.get("primary_location") or {}).get("source") or {}).get("display_name"),
                  doi=item.get("doi"))
            for item in results if isinstance(item, dict)]


def _split_authors(text):
    return [part.strip().rstrip(".") for part in str(text or "").split(",") if part.strip().rstrip(".")]


def _arxiv_query(query):
    words = [word for word in query.split() if word]
    return " AND ".join("all:%s" % word for word in words)


def _query_services(fetcher, query):
    return [
        ("arxiv", _ask(fetcher, _with(ARXIV_QUERY, search_query=_arxiv_query(query), start="0", max_results=str(ROWS)), _read_arxiv)),
        ("crossref", _ask(fetcher, _with(CROSSREF_QUERY, **{"query.bibliographic": query, "rows": str(ROWS),
                                                            "select": "DOI,title,author,issued,container-title,type",
                                                            "mailto": fetcher.email}), _read_crossref)),
        ("europepmc", _ask(fetcher, _with(EUROPEPMC_SEARCH, query=query, format="json", resultType="lite", pageSize=str(ROWS)),
                           _read_europepmc)),
        ("openalex", _ask(fetcher, _with(OPENALEX_SEARCH, search=query, **{"per-page": str(ROWS)}), _read_openalex)),
    ]


# --- the works citing a seed ------------------------------------------------------------------------


def _seed(project, ledger, reference, fetcher, email, clock):
    """What is known of the seed: its filed dossier when it is found, else the scout's live answer, filed nowhere; None when nobody knows it."""
    from wayline import dossier as dossiers  # the dossier module imports the launcher
    slug = dossiers.filed_slug(ledger, reference)
    record = dossiers.read_dossier(ledger, slug) if slug else None
    if record is None or record.get("existence") != VERIFIED:
        record = Scout(fetcher, email, clock).resolve(reference)
    return record if record.get("existence") == VERIFIED else None


def _openalex_id(fetcher, identifiers):
    """The seed's OpenAlex id (`W123`): from its identifiers, else one request by its DOI; None when neither gives one."""
    known = _tail(identifiers.get("openalex"))
    if known or not identifiers.get("doi"):
        return known, None
    try:
        answer = fetcher.fetch(OPENALEX_WORK % urllib.parse.quote(identifiers["doi"], safe=""))
    except _Spent as spent:
        return None, _Asked(SKIPPED, note=str(spent))
    except FetchError as failure:
        return None, _Asked(FAILED, note=str(failure))
    if not answer.ok:
        return None, _Asked(FAILED if answer.status not in (404, 410) else NO_MATCH, note="status %d" % answer.status)
    try:
        return _tail(_json(answer).get("id")), None
    except ValueError:
        return None, _Asked(FAILED, note="an unreadable answer")


def _citing_services(fetcher, identifiers):
    pmid = identifiers.get("pmid")
    asked = [("europepmc", _ask(fetcher, _with(EUROPEPMC_CITATIONS % urllib.parse.quote(str(pmid), safe=""), format="json",
                                               pageSize=str(ROWS)), _read_citations)
              if pmid else _Asked(SKIPPED, note="the seed has no PMID, which Europe PMC's citations are listed by"))]
    work_id, problem = _openalex_id(fetcher, identifiers)
    if work_id:
        asked.append(("openalex", _ask(fetcher, _with(OPENALEX_SEARCH, filter="cites:%s" % work_id, **{"per-page": str(ROWS)}),
                                       _read_openalex)))
    else:
        asked.append(("openalex", problem or _Asked(SKIPPED, note="the seed has no DOI or OpenAlex id to ask OpenAlex by")))
    return asked


# --- the works, joined ------------------------------------------------------------------------------


def _keys(work):
    keys = []
    if work.get("doi"):
        keys.append(("doi", work["doi"].lower()))
    if work.get("arxiv_id"):
        keys.append(("arxiv", work["arxiv_id"].lower()))
    if work.get("title"):
        keys.append(("title", normalize_title(work["title"])))
    return keys


def _joined(asked):
    """Every work the services found, in the order they were asked, each once: a later answer about a listed work fills its gaps."""
    works, index = [], {}
    for _, answer in asked:
        for work in answer.works:
            known = next((index[key] for key in _keys(work) if key in index), None)
            if known is None:
                known = dict(work, sources=[])
                works.append(known)
            for field in ("doi", "arxiv_id", "pmid", "year", "venue"):
                if not known.get(field) and work.get(field):
                    known[field] = work[field]
            if not known.get("authors") and work.get("authors"):
                known["authors"] = work["authors"]
            for source in work["sources"]:
                if source not in known["sources"]:
                    known["sources"].append(source)
            for key in _keys(known):
                index.setdefault(key, known)
    for work in works:
        work["identifier"] = ("doi:%s" % work["doi"] if work.get("doi") else
                              "arxiv:%s" % work["arxiv_id"] if work.get("arxiv_id") else work["title"])
    return [{key: work.get(key) for key in ("identifier", "title", "authors", "year", "venue", "doi", "arxiv_id", "pmid", "sources")}
            for work in works]


# --- the search -------------------------------------------------------------------------------------


def search(project, query=None, *, citing=None, ticket=None, fetcher=None, email=None, clock=None, ledger=None):
    """One search: the works found for `query`, or citing the seed `citing`; returns the report and journals `scout_searched`.

    `ticket` is the asking ticket's id, whose searches are counted and capped; None searches uncounted. Raises
    SearchRefused past the cap and SearchError for no query and no seed or a URL as the seed, both before any request.
    """
    project = Path(project).resolve()
    ledger = ledger_for(ledger if ledger is not None else project)
    clock = clock or time.time
    query = " ".join(str(query or "").split()) or None
    citing = str(citing or "").strip() or None
    if (query is None) == (citing is None):
        raise SearchError("a search names a query or a seed (--citing <identifier>), one of the two")
    reference = None
    if citing is not None:
        try:
            reference = parse_reference(citing)
        except ScoutError as failure:
            raise SearchError(str(failure)) from None
        if reference.kind not in ("doi", "arxiv", "title"):
            raise SearchError("%s is a URL, which is never looked up; name the seed by its DOI, its arXiv id, or its exact title" % citing)
    if ticket is not None:
        _refuse_unless_lit(project, ticket)
    policy = policy_for(project)
    limit = search_limit(policy)
    made, spent = _counts(ledger, ticket, clock())
    made = made if ticket is not None else None
    if ticket is not None and made >= limit:
        raise SearchRefused("ticket %s has made %d search(es), the most policy.scout.searches_per_ticket (%d) allows; write the "
                            "passages from the works already found" % (ticket, made, limit))
    if email is None:
        email = read_harness(project).get("owner_email")
    per_day = openalex_limit(policy)
    budgeted = _Budgeted(fetcher if fetcher is not None else search_fetcher(email), lambda: openalex_today(ledger, clock()), per_day)
    budgeted.seen = spent
    note = None
    if reference is None:
        asked = _query_services(budgeted, query)
    else:
        seed = _seed(project, ledger, reference, budgeted, email, clock)
        if seed is None:
            asked, note = [], "no service knows the seed %s, so no citing work can be listed; check it with `wayline scout`" % citing
        else:
            asked = _citing_services(budgeted, seed.get("identifiers") or {})
    works = _joined(asked)
    ledger.append_event(SCOUT_SEARCHED, {"query": query, "citing": citing, "works": len(works), "openalex": budgeted.asked}, ticket=ticket)
    return {"query": query, "citing": citing, "works": works,
            "services": {name: {"outcome": answer.outcome, "works": len(answer.works), "note": answer.note} for name, answer in asked},
            "openalex": {"asked": budgeted.asked, "today": budgeted.seen + budgeted.asked, "limit": per_day}, "note": note,
            "ticket": ticket, "asked": None if made is None else made + 1, "limit": limit}


def _refuse_unless_lit(project, ticket):
    """A search is the surveyor's: under `WAYLINE_TICKET` it runs only for a `lit` ticket, whatever role's tools reach the verb."""
    try:
        kinds = {fields["id"]: fields.get("kind") for fields in read_tickets(project)}
    except (TicketError, OSError, ValueError) as failure:
        raise SearchRefused("ticket %s cannot be read, so the search cannot tell it is a `lit` ticket: %s" % (ticket, failure)) from None
    if kinds.get(ticket) != KIND:
        raise SearchRefused("ticket %s is %s, and a search of the literature is the surveyor's, for a `lit` ticket: check the works "
                            "you draw on with `wayline scout <identifier>`, or propose a `lit` ticket"
                            % (ticket, "a %s ticket" % kinds[ticket] if kinds.get(ticket) else "no ticket the project holds"))


def _authors(names):
    names = list(names or [])
    return ", ".join(names[:3]) + (" et al." if len(names) > 3 else "")


def render(report):
    """What the surveyor reads: each work with the identifier to scout it by, what each service said, and the counts."""
    lines = ["search      %s" % ('"%s"' % report["query"] if report["query"] else "the works citing %s" % report["citing"])]
    if report.get("note"):
        lines.append("note        %s" % report["note"])
    if not report["works"]:
        lines.append("works       none found")
    for number, work in enumerate(report["works"], 1):
        details = ". ".join(part for part in (_authors(work["authors"]), str(work["year"] or ""), work["venue"] or "") if part)
        lines.append("%2d. %s%s" % (number, work["title"], (". " + details) if details else ""))
        lines.append("    scout it: wayline scout %s (found by %s)" % (shlex.quote(work["identifier"]), ", ".join(work["sources"])))
    if report["services"]:
        lines.append("services    " + "; ".join(
            "%s %s" % (name, "found %d" % entry["works"] if entry["outcome"] == FOUND else
                       entry["outcome"] + (" (%s)" % entry["note"] if entry["note"] else ""))
            for name, entry in report["services"].items()))
    openalex = report["openalex"]
    lines.append("openalex    %d request(s) made; %d of %d today" % (openalex["asked"], openalex["today"], openalex["limit"]))
    if report["ticket"] is not None:
        lines.append("searches    %d of %d made by ticket %s" % (report["asked"], report["limit"], report["ticket"]))
    lines.append("None of these is filed: check a work with `wayline scout <identifier>` before you cite it, and cite the slug it prints.")
    return "\n".join(lines)


def search_command(args):
    """`wayline scout search "<query>" | --citing <identifier> [--json] [--project <path>]`: the ticket is `WAYLINE_TICKET`."""
    parser = argparse.ArgumentParser(prog="wayline scout search",
                                     description="search the literature through arXiv, Crossref, Europe PMC, and OpenAlex (always live)")
    parser.add_argument("query", nargs="?", help="what to search for")
    parser.add_argument("--citing", help="list the works citing this seed, by its DOI, arXiv id, or exact title")
    parser.add_argument("--project", help="the project; WAYLINE_PROJECT or the active one by default")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    options, code = parse_args(parser, args)
    if options is None:
        return code
    raw_ticket = os.environ.get("WAYLINE_TICKET", "").strip()
    if raw_ticket and not raw_ticket.isdigit():
        print("wayline scout search: WAYLINE_TICKET is %r, not a ticket id" % raw_ticket, file=sys.stderr)
        return 2
    try:
        project = find_project(options.project or os.environ.get("WAYLINE_PROJECT") or None)
        report = search(project, options.query, citing=options.citing, ticket=int(raw_ticket) if raw_ticket else None)
    except (SearchError, ProjectError, LedgerError, ValueError, OSError) as failure:
        print("wayline scout search: %s" % failure, file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2) if options.json else render(report))
    return 0


# --- the tickets ------------------------------------------------------------------------------------


def uncovered(project):
    """The open objectives no current Introduction passage with a `ref` tag covers, in the objectives' order."""
    from wayline import objectives, specify  # both read the sections, the spec, and the ledger
    try:
        records = objectives.read_objectives(project)
    except objectives.ObjectivesUnreadable:
        return []
    covered = specify.covered_objectives(project, records)
    return [record["id"] for record in records if record.get("status") == "open" and record["id"] not in covered]


def scout_missing(project, gaps, fetcher=None, email=None, clock=None, say=lambda text: None):
    """Position's `missing_prior_work` searched at setup, uncounted by any ticket: `[{gap, works, note}]`, one per gap.

    A gap is the critic's words, searched as they are; a search that fails or finds nothing is kept with its note,
    and the first `lit` tickets read the lot in `POSITION.md`.
    """
    found = []
    for gap in gaps or []:
        text = " ".join(str(gap or "").split())
        if not text:
            continue
        say("  searching the literature for what the references lack: %s" % text)
        try:
            report = search(project, text, fetcher=fetcher, email=email, clock=clock)
        except (SearchError, LedgerError, ValueError, OSError) as failure:
            found.append({"gap": text, "works": [], "note": "the search could not run: %s" % failure})
            continue
        failed = ["%s (%s)" % (name, entry["note"]) for name, entry in report["services"].items() if entry["outcome"] in (FAILED, SKIPPED)]
        found.append({"gap": text, "works": [{key: work[key] for key in ("identifier", "title", "authors", "year", "venue")}
                                             for work in report["works"]],
                      "note": ("not asked or failed: " + "; ".join(failed)) if failed else None})
    return found


def missing_scouted(project):
    """Whether position's memo named missing prior work and the setup search ran on it: what the first `lit` tickets are handed."""
    from wayline.grill import POSITION_JSON  # the grill reads the position memo, which the front door writes
    try:
        record = ledger_for(project).read_json(POSITION_JSON)
    except (OSError, ValueError):
        return False
    return isinstance(record, dict) and bool(record.get("missing_scouted"))


def missing_lines(item):
    """`POSITION.md`'s lines under one gap: the works its setup search found, each with the identifier to scout it by."""
    lines = []
    for work in (item or {}).get("works") or []:
        details = ", ".join(part for part in (_authors(work.get("authors")), str(work.get("year") or "")) if part)
        lines.append("  - found by the search: *%s*%s; scout it as `%s`" % (work["title"], " (%s)" % details if details else "",
                                                                             work["identifier"]))
    if item is not None and not item.get("works"):
        lines.append("  - the search found nothing%s" % (": %s" % item["note"] if item.get("note") else ""))
    return lines
