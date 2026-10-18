"""The scout (Implementation Decisions 9): a reference in, verified identifiers and an abstract out.

The scout is code, not a model: it takes what the owner wrote down (a DOI, an arXiv id, a bare
title, a URL) and asks the keyless services in the order of `research-notes/06` Section 3 until
one of them knows the work. What comes back is an L0 record whose every field was read off a
response, which is the whole point: a reference nothing knows is marked `existence: unresolved`
and stays that way. Nothing in this module invents a citation, and nothing writes `fabricated`.

The order per reference kind, and why:

- a DOI: Crossref (free, complete, polite pool by `mailto`), then OpenAlex (identifiers and an
  abstract Crossref often lacks), then Unpaywall (where the PDF is), then Europe PMC (which has
  the biomedical work and the preprints the other three miss). A `10.1101` DOI is bioRxiv or
  medRxiv and goes to their own API first: it is the only source with the preprint's version
  history and the journal DOI it was later published under, which is the whole value of asking.
- a title: Crossref `query.bibliographic` with three rows and a title-similarity check here in
  code, because a bibliographic query always answers something and the top hit is often a
  different paper; then OpenAlex `search`, then Europe PMC `TITLE:`.
- an arXiv id: the arXiv API, and nothing else. OpenAlex has no arXiv namespace, so an arXiv
  paper reaches it through the journal DOI the arXiv record carries, when it has one.
- a bare URL: nothing. No keyless service answers a URL, so it stays unresolved.

After a work is found, whatever the resolving source left empty is filled from the next source
that has it, and no more than that: an L0 record is metadata, identifiers, and an abstract, and
Crossref carries no abstract for most journals.

Semantic Scholar is not called: keyless it returns 429 on the first request (note 06), so a
chain that depended on it would be a chain that fails. A test asserts no request ever goes there.

Every request goes through the fetch seam, so the cache under `research/.cache/scout/` and the
suite's recorded responses are both just a backend.
"""

import difflib
import html
import re
import time
import unicodedata
import urllib.parse
import xml.etree.ElementTree as ElementTree

from datetime import datetime, timezone
from html.parser import HTMLParser

from wayline.fetch import FetchError, canonical_url

__all__ = [
    "Reference", "ScoutError", "Scout", "parse_reference", "parse_references", "resolve",
    "VERIFIED", "UNRESOLVED", "SOURCES", "TITLE_SIMILARITY", "normalize_title", "title_similarity",
    "FOUND", "NO_MATCH", "FAILED", "SKIPPED", "OUTCOMES", "NO_SUCH_WORK", "outcome", "timestamp",
]

VERIFIED = "verified"
UNRESOLVED = "unresolved"

# What one lookup attempt came to (decision 17). `found`: the service knew the work. `no match`: the
# service answered and nothing it had matched. `failed`: an error status, a timeout, or an answer
# nobody can read, which says nothing about the work and is why a failure is asked again and a no
# match is not. `skipped`: nothing was asked (a bare URL, Unpaywall without an address).
FOUND = "found"
NO_MATCH = "no match"
FAILED = "failed"
SKIPPED = "skipped"
OUTCOMES = (FOUND, NO_MATCH, FAILED, SKIPPED)

# What a whole lookup came to when the work was not found and every service asked answered no match:
# the one case where the scout may say the work is not there, rather than that it could not tell.
NO_SUCH_WORK = "no such work"

# Statuses that are a service's answer that it has no such record, rather than a failure to answer.
_NO_RECORD = (404, 410)

# Every source the scout may name as the one that resolved a reference.
SOURCES = ("crossref", "openalex", "unpaywall", "europepmc", "arxiv", "biorxiv", "medrxiv")

# How close a returned title must be to the one asked for before a bibliographic query counts as
# a hit. Crossref answers every query with something, so this check, not the service, decides.
TITLE_SIMILARITY = 0.90

CROSSREF_WORK = "https://api.crossref.org/works/%s"
CROSSREF_QUERY = "https://api.crossref.org/works"
OPENALEX_WORK = "https://api.openalex.org/works/doi:%s"
OPENALEX_SEARCH = "https://api.openalex.org/works"
UNPAYWALL_WORK = "https://api.unpaywall.org/v2/%s"
EUROPEPMC_SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
ARXIV_QUERY = "https://export.arxiv.org/api/query"
ARXIV_ABS = "https://arxiv.org/abs/%s"
ARXIV_DOI = "10.48550/arXiv.%s"
BIORXIV_DETAILS = "https://api.biorxiv.org/details/%s/%s/na/json"

# The preprint servers behind the 10.1101 prefix; which of the two a DOI belongs to is not in the
# DOI, so both are asked (bioRxiv first: it is the larger of the two).
PREPRINT_PREFIX = "10.1101"
PREPRINT_SERVERS = ("biorxiv", "medrxiv")

_DOI = re.compile(r"\b(10\.\d{4,9}/[^\s\"'<>,;)\]]+)", re.IGNORECASE)
_ARXIV_DOI = re.compile(r"^10\.48550/arxiv\.(.+)$", re.IGNORECASE)
_ARXIV_NEW = re.compile(r"\b(?:arxiv[:/\s]?)?(\d{4}\.\d{4,5}(?:v\d+)?)\b", re.IGNORECASE)
_ARXIV_OLD = re.compile(r"\b(?:arxiv[:/\s]?)?([a-z-]+(?:\.[A-Z]{2})?/\d{7}(?:v\d+)?)\b", re.IGNORECASE)
_ARXIV_MARKER = re.compile(r"arxiv", re.IGNORECASE)
_URL = re.compile(r"^(https?://\S+)$", re.IGNORECASE)
_TAGS = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"\s+")
_BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_MARKDOWN_LINK = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")


class ScoutError(ValueError):
    """A reference the scout cannot even parse into a question."""


class Reference:
    """What the owner wrote down, read as a question one of the services can answer."""

    __slots__ = ("kind", "value", "raw", "note", "pdf")

    def __init__(self, kind, value, raw=None, note=None, pdf=None):
        self.kind = kind  # doi | arxiv | title | url | file (a PDF given with no identifier, never asked of a service)
        self.value = value
        self.raw = raw if raw is not None else value
        # What the owner wrote beside the reference, and the PDF that is its source: kept on the
        # dossier by the caller, and never read by the scout.
        self.note = note
        self.pdf = pdf

    def __repr__(self):  # pragma: no cover - debugging
        return "Reference(%r, %r)" % (self.kind, self.value)

    def __eq__(self, other):
        return isinstance(other, Reference) and (self.kind, self.value) == (other.kind, other.value)

    def as_dict(self):
        return {"kind": self.kind, "value": self.value, "raw": self.raw}


# --- reading what the owner wrote ---------------------------------------------------------------


def parse_reference(text):
    """One line of an intake's reference list, read as a DOI, an arXiv id, a URL, or a title."""
    raw = _strip_markup(text)
    if not raw:
        raise ScoutError("an empty reference is not a question any service can answer")
    doi = _DOI.search(raw)
    if doi is not None:
        value = doi.group(1).rstrip(".,;")
        arxiv = _ARXIV_DOI.match(value)
        return Reference("arxiv", arxiv.group(1), raw) if arxiv else Reference("doi", value, raw)
    identifier = _arxiv_id(raw)
    if identifier is not None:
        return Reference("arxiv", identifier, raw)
    url = _URL.match(raw)
    if url is not None:
        return Reference("url", url.group(1), raw)
    return Reference("title", _SPACES.sub(" ", raw).strip(), raw)


def parse_references(lines):
    """Every non-empty line of a reference list, parsed; a line nobody can read is skipped."""
    references = []
    for line in lines:
        try:
            references.append(parse_reference(line))
        except ScoutError:
            continue
    return references


def _strip_markup(text):
    """A bullet, a markdown link, and the surrounding whitespace taken off a reference line."""
    line = _BULLET.sub("", str(text or "").strip())
    link = _MARKDOWN_LINK.search(line)
    if link is not None:
        target, label = link.group(2).strip(), link.group(1).strip()
        line = target if (_DOI.search(target) or _arxiv_id(target)) else (label or target)
    return line.strip().strip("<>").strip()


def _arxiv_id(text):
    """The arXiv id in `text`, or None. A bare number counts only next to the word arXiv or a link."""
    lowered = text.lower()
    marked = bool(_ARXIV_MARKER.search(lowered))
    for pattern in (_ARXIV_NEW, _ARXIV_OLD):
        found = pattern.search(text)
        if found is None:
            continue
        if not marked and not lowered.startswith(found.group(1).lower()):
            continue  # a bare number inside a sentence is a number, not an identifier
        return found.group(1)
    return None


# --- title matching -----------------------------------------------------------------------------


def normalize_title(title):
    """A title stripped to what two spellings of the same paper share: letters, digits, and spaces."""
    folded = unicodedata.normalize("NFKD", str(title or ""))
    folded = "".join(char for char in folded if not unicodedata.combining(char))
    return _SPACES.sub(" ", re.sub(r"[^a-z0-9 ]+", " ", folded.lower())).strip()


def title_similarity(asked, returned):
    """0 to 1 between two titles, over their normalized forms."""
    left, right = normalize_title(asked), normalize_title(returned)
    if not left or not right:
        return 0.0
    return difflib.SequenceMatcher(None, left, right).ratio()


# --- the scout ----------------------------------------------------------------------------------


class Scout:
    """The resolution chain over one fetcher. One instance per project run."""

    def __init__(self, fetcher, email=None, clock=None):
        self.fetcher = fetcher
        self.email = email if email is not None else getattr(fetcher, "email", None)
        self.clock = clock or time.time

    # --- the entry point ---

    def resolve(self, reference, found=False):
        """An L0 record for one reference: `existence`, `resolved_by`, identifiers, metadata, abstract.

        `found` says the work is already found (a dossier says `existence: verified`), which is the
        one case the scout's cache may answer from disk (decision 17); otherwise every request goes
        to the network.
        """
        if not isinstance(reference, Reference):
            reference = parse_reference(reference)
        self._replay = bool(found)
        record = _blank(reference)
        chain = {
            "doi": self._resolve_doi,
            "arxiv": self._resolve_arxiv,
            "title": self._resolve_title,
            "url": self._resolve_url,
            "file": self._resolve_file,
        }[reference.kind]
        chain(reference, record)
        if record["resolved_by"] is not None:
            record["existence"] = VERIFIED
        self._enrich(record)
        failed = [attempt for attempt in record["attempts"] if attempt["outcome"] == FAILED]
        if failed and record["existence"] != VERIFIED:
            record["retry"] = {"service": failed[0]["source"], "failure": failed[0]["note"] or FAILED,
                               "date": timestamp(self.clock())}
        return record

    # --- the chains ---

    def _resolve_doi(self, reference, record):
        doi = reference.value
        record["identifiers"]["doi"] = doi
        if doi.lower().startswith(PREPRINT_PREFIX + "/"):
            for server in PREPRINT_SERVERS:
                if self._biorxiv(doi, server, record):
                    return
        if self._crossref_doi(doi, record):
            return
        if self._openalex_doi(doi, record):
            return
        if self._unpaywall(doi, record):
            return
        self._europepmc('DOI:"%s"' % doi, record, source_doi=doi)

    def _resolve_arxiv(self, reference, record):
        record["identifiers"]["arxiv_id"] = reference.value
        if self._arxiv(reference.value, record):
            return
        if record["attempts"] and record["attempts"][-1]["outcome"] == FAILED:
            self._arxiv_abs(reference.value, record)

    def _resolve_title(self, reference, record):
        title = reference.value
        if self._crossref_title(title, record):
            return
        if self._openalex_title(title, record):
            return
        self._europepmc('TITLE:"%s"' % title.replace('"', " "), record, asked_title=title)

    def _resolve_url(self, reference, record):
        """A bare URL is kept as a locator and nothing is claimed about the work behind it.

        No keyless service takes a URL as a question, so there is nothing to ask. Giving the
        record a title made out of the URL would be inventing one, which is the one thing this
        module may not do; the reference stays `unresolved` until someone gives it an identifier.
        """
        record["identifiers"]["url"] = reference.value
        record["attempts"].append(_attempt("none", reference.value, None, SKIPPED, "no keyless service resolves a bare URL; give it a DOI or an arXiv id"))

    def _resolve_file(self, reference, record):
        """A PDF given with no identifier: a path is never a title query, so nothing is asked (decision 17)."""
        record["attempts"].append(_attempt("none", "file:" + reference.value, None, SKIPPED,
                                           "a local file is never sent to a service; hand over its DOI or its exact title, or the PDF itself"))

    def _enrich(self, record):
        """Fill what the resolving source left empty, and never more than that.

        An L0 record is metadata, identifiers, and an abstract, and the source that established
        the work exists often carries only the first two: Crossref has no abstract for most
        journals, and no service but Unpaywall says where the PDF is. So each of these runs only
        when the field it fills is still empty, which is also what keeps OpenAlex, a daily budget
        rather than a rate (note 06), read sparingly.
        """
        doi = record["identifiers"].get("doi")
        if record["existence"] != VERIFIED or not doi or record.get("retry"):
            return  # a work found by its abs page waits for the API to fill in the rest
        if not record["abstract"] and record["resolved_by"] != "openalex":
            self._openalex_doi(doi, record, enriching=True)
        if not record["abstract"] and record["resolved_by"] != "europepmc":
            self._europepmc('DOI:"%s"' % doi, record, source_doi=doi, enriching=True)
        if not record["open_access"].get("pdf_url") and record["resolved_by"] != "unpaywall":
            self._unpaywall(doi, record, enriching=True)

    # --- one source each ---

    def _crossref_doi(self, doi, record):
        url = _with(CROSSREF_WORK % urllib.parse.quote(doi, safe=""), mailto=self.email)
        message = _message(self._read(self._get(url, "crossref", record), record))
        if message is None:
            return False
        _take_crossref(message, record)
        return _resolved(record, "crossref")

    def _crossref_title(self, title, record):
        url = _with(
            CROSSREF_QUERY,
            **{"query.bibliographic": title, "rows": "3", "select": "DOI,title,author,issued,score,type,container-title,abstract", "mailto": self.email},
        )
        payload = self._read(self._get(url, "crossref", record), record)
        if payload is None:
            return False
        items = (_message(payload) or {}).get("items") or []
        best, score = _best_title_match(title, items, lambda item: _first(item.get("title")))
        if best is None:
            return _too_far(record, score, len(items))
        _note(record, "title similarity %.2f" % score)
        _take_crossref(best, record)
        return _resolved(record, "crossref")

    def _openalex_doi(self, doi, record, enriching=False):
        work = self._read(self._get(OPENALEX_WORK % urllib.parse.quote(doi, safe=""), "openalex", record), record)
        if work is None or work.get("id") is None:
            return False
        _take_openalex(work, record)
        return _found(record, "openalex", enriching)

    def _openalex_title(self, title, record):
        payload = self._read(self._get(_with(OPENALEX_SEARCH, search=title, **{"per-page": "3"}), "openalex", record), record)
        if payload is None:
            return False
        items = payload.get("results") or []
        best, score = _best_title_match(title, items, lambda item: item.get("display_name"))
        if best is None:
            return _too_far(record, score, len(items))
        _note(record, "title similarity %.2f" % score)
        _take_openalex(best, record)
        return _resolved(record, "openalex")

    def _unpaywall(self, doi, record, enriching=False):
        if not self.email:
            record["attempts"].append(_attempt("unpaywall", UNPAYWALL_WORK % doi, None, SKIPPED, "Unpaywall requires an address; harness.json has no owner_email"))
            return False
        url = _with(UNPAYWALL_WORK % urllib.parse.quote(doi, safe=""), email=self.email)
        work = self._read(self._get(url, "unpaywall", record), record)
        if work is None or work.get("doi") is None:
            return False
        _take_unpaywall(work, record)
        return _found(record, "unpaywall", enriching)

    def _europepmc(self, query, record, asked_title=None, source_doi=None, enriching=False):
        url = _with(EUROPEPMC_SEARCH, query=query, format="json", resultType="core", pageSize="3")
        payload = self._read(self._get(url, "europepmc", record), record)
        if payload is None:
            return False
        results = (payload.get("resultList") or {}).get("result") or []
        if asked_title is not None:
            best, score = _best_title_match(asked_title, results, lambda item: item.get("title"))
            if best is None:
                return _too_far(record, score, len(results))
            _note(record, "title similarity %.2f" % score)
        else:
            best = _first_matching(results, source_doi)
            if best is None:
                return False
        _take_europepmc(best, record)
        return _found(record, "europepmc", enriching)

    def _arxiv(self, identifier, record):
        answer = self._get(_with(ARXIV_QUERY, id_list=identifier, max_results="1"), "arxiv", record)
        if answer is None:
            return False
        entry = _arxiv_entry(answer)
        if entry is False:
            _note(record, "an unreadable answer (not an Atom feed)", outcome=FAILED)
            return False
        if entry is None:
            return False
        _take_arxiv(entry, record)
        return _resolved(record, "arxiv")

    def _arxiv_abs(self, identifier, record):
        """The `arxiv.org/abs` page's meta tags, asked when the arXiv API failed: an attempt of its own.

        A work found this way is recorded with its arXiv DOI and keeps the `retry` flag that the
        API's failure set, so the next retry asks the API again and its answer replaces this one.
        """
        failed = record["attempts"][-1]
        answer = self._get(ARXIV_ABS % identifier, "arxiv", record)
        if answer is None:
            return False
        tags = _meta_tags(answer.text())
        if not tags.get("citation_title"):
            _note(record, "an unreadable answer (no citation_title meta tag)", outcome=FAILED)
            return False
        _take_abs_page(tags, identifier, record)
        _note(record, "the abs page's meta tags, after the arXiv API failed; arXiv DOI " + ARXIV_DOI % identifier)
        record["retry"] = {"service": failed["source"], "failure": failed["note"] or FAILED, "date": timestamp(self.clock())}
        return _resolved(record, "arxiv")

    def _biorxiv(self, doi, server, record):
        payload = self._read(self._get(BIORXIV_DETAILS % (server, urllib.parse.quote(doi, safe="/")), server, record), record)
        if payload is None:
            return False
        collection = payload.get("collection") or []
        # The API returns one entry per version, oldest first; the newest is the one to record,
        # and it is the one that has to carry a title before this counts as knowing the work.
        latest = collection[-1] if collection else None
        if not isinstance(latest, dict) or not latest.get("title"):
            return False
        _take_biorxiv(latest, server, record)
        return _resolved(record, server)

    # --- the one place a request is made ---

    def _get(self, url, source, record):
        """One request, recorded in the record's `attempts` whatever it answers; None unless it answered 2xx.

        The attempt starts as `no match`; the reader that takes the work out of the answer marks it
        `found`, and one that cannot read the answer marks it `failed`. A 404 is the service saying
        it has no such record, and any other status outside 2xx, like a refused request or a
        timeout, is a failure that says nothing about the work.
        """
        try:
            answer = self.fetcher.fetch(url, replay=getattr(self, "_replay", False))
        except FetchError as failure:
            record["attempts"].append(_attempt(source, url, None, FAILED, str(failure)))
            return None
        if answer.ok:
            record["attempts"].append(_attempt(source, url, answer.status, NO_MATCH, None))
            return answer
        if answer.status in _NO_RECORD:
            record["attempts"].append(_attempt(source, url, answer.status, NO_MATCH, None))
        else:
            record["attempts"].append(_attempt(source, url, answer.status, FAILED, "status %d" % answer.status))
        return None

    def _read(self, answer, record):
        """The JSON object of a 2xx answer, or None; an answer that is not one marks its attempt `failed`."""
        if answer is None:
            return None
        payload = answer.json()
        if not isinstance(payload, dict):
            _note(record, "an unreadable answer (not a JSON object)", outcome=FAILED)
            return None
        return payload


def outcome(record):
    """What a whole lookup came to: `found`, `no such work` (every service asked answered no match), or `failed`.

    A lookup that found nothing and asked nobody (a bare URL) is `no such work` too: there was no
    service to fail, and nothing will answer it later.
    """
    if record.get("existence") == VERIFIED:
        return FOUND
    if any(attempt.get("outcome") == FAILED for attempt in record.get("attempts") or []):
        return FAILED
    return NO_SUCH_WORK


def timestamp(seconds):
    """An epoch second as the ledger spells a moment: `2026-09-21T14:13:20.000Z`."""
    return datetime.fromtimestamp(seconds, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def resolve(reference, fetcher, email=None):
    """One reference through one fetcher; the convenience the CLI and the tests use."""
    return Scout(fetcher, email).resolve(reference)


# --- the record ---------------------------------------------------------------------------------


def _blank(reference):
    return {
        "schema_version": 1,
        "query": reference.as_dict(),
        "existence": UNRESOLVED,
        "resolved_by": None,
        "identifiers": {},
        "metadata": {},
        "abstract": None,
        "open_access": {},
        "attempts": [],
    }


def _attempt(source, url, status, outcome, note):
    return {"source": source, "url": canonical_url(url), "status": status, "outcome": outcome, "note": note}


def _note(record, note, outcome=None):
    """Write what the last request turned out to mean onto the attempt that made it."""
    if record["attempts"]:
        record["attempts"][-1]["note"] = note
        if outcome is not None:
            record["attempts"][-1]["outcome"] = outcome
    return record


def _too_far(record, score, candidates):
    """Mark the last attempt a miss because no candidate's title was close enough. Always False."""
    _note(record, "%d candidate(s), best title similarity %.2f, below %.2f" % (candidates, score, TITLE_SIMILARITY), outcome=NO_MATCH)
    return False


def _resolved(record, source):
    """The last attempt found the work, and its source is the one that resolved it unless one already had."""
    if record["attempts"]:
        record["attempts"][-1]["outcome"] = FOUND
    record["resolved_by"] = record["resolved_by"] or source
    return True


def _found(record, source, enriching):
    """The last attempt found the work: as its resolver, or while filling in a work another source found."""
    if not enriching:
        return _resolved(record, source)
    if record["attempts"]:
        record["attempts"][-1]["outcome"] = FOUND
    return True


def _set(mapping, key, value):
    """Fill a field only when it is still empty: the first source to know something keeps it."""
    if value not in (None, "", [], {}) and not mapping.get(key):
        mapping[key] = value


def _set_open_access(record, is_oa):
    """Record whether the work is open access, unless a source has already said so.

    `is_oa` is the one field `_set` cannot carry, because False is a real answer and `_set`
    treats every empty value as nothing said.
    """
    if is_oa is not None and record["open_access"].get("is_oa") is None:
        record["open_access"]["is_oa"] = bool(is_oa)


def _with(url, **parameters):
    pairs = [(key.replace("__", "."), value) for key, value in parameters.items() if value not in (None, "")]
    if not pairs:
        return url
    joiner = "&" if "?" in url else "?"
    return url + joiner + urllib.parse.urlencode(pairs)


def _message(payload):
    message = payload.get("message") if isinstance(payload, dict) else None
    return message if isinstance(message, dict) else None


def _first(value):
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _best_title_match(asked, items, title_of):
    """The candidate whose title is close enough to the one asked for, and the best score seen."""
    best, best_score = None, 0.0
    for item in items:
        if not isinstance(item, dict):
            continue
        score = title_similarity(asked, title_of(item) or "")
        if score > best_score:
            best, best_score = item, score
    return (best, best_score) if best_score >= TITLE_SIMILARITY else (None, best_score)


def _first_matching(results, doi):
    for item in results:
        if not isinstance(item, dict):
            continue
        if doi is None or str(item.get("doi", "")).lower() == str(doi).lower():
            return item
    return None


def _clean(text):
    """Prose out of a field that may carry JATS or HTML markup (Crossref abstracts do)."""
    if not text:
        return None
    stripped = _SPACES.sub(" ", _TAGS.sub(" ", str(text))).strip()
    return stripped or None


# --- one reader per source ----------------------------------------------------------------------


def _take_crossref(work, record):
    identifiers, metadata = record["identifiers"], record["metadata"]
    _set(identifiers, "doi", work.get("DOI"))
    _set(identifiers, "url", work.get("URL"))
    _set(metadata, "title", _clean(_first(work.get("title"))))
    _set(metadata, "authors", [_person(author) for author in work.get("author") or []])
    _set(metadata, "year", _crossref_year(work))
    _set(metadata, "container", _clean(_first(work.get("container-title"))))
    _set(metadata, "type", work.get("type"))
    if work.get("abstract") and not record["abstract"]:
        record["abstract"] = _clean(work["abstract"])


def _crossref_year(work):
    for key in ("issued", "published", "published-print", "published-online", "created"):
        parts = ((work.get(key) or {}).get("date-parts") or [[None]])[0]
        if parts and parts[0]:
            return int(parts[0])
    return None


def _person(author):
    if not isinstance(author, dict):
        return str(author)
    name = " ".join(part for part in (author.get("given"), author.get("family")) if part)
    return name or author.get("name") or ""


def _take_openalex(work, record):
    identifiers, metadata = record["identifiers"], record["metadata"]
    ids = work.get("ids") or {}
    _set(identifiers, "doi", _bare_doi(work.get("doi") or ids.get("doi")))
    _set(identifiers, "openalex", work.get("id") or ids.get("openalex"))
    _set(identifiers, "pmid", _tail(ids.get("pmid")))
    _set(identifiers, "pmcid", _tail(ids.get("pmcid")))
    _set(metadata, "title", _clean(work.get("display_name") or work.get("title")))
    _set(metadata, "authors", [
        (entry.get("author") or {}).get("display_name", "") for entry in work.get("authorships") or []
    ])
    _set(metadata, "year", work.get("publication_year"))
    _set(metadata, "container", ((work.get("primary_location") or {}).get("source") or {}).get("display_name"))
    _set(metadata, "type", work.get("type"))
    if not record["abstract"]:
        record["abstract"] = _openalex_abstract(work.get("abstract_inverted_index"))
    best = work.get("best_oa_location") or {}
    _set(record["open_access"], "pdf_url", best.get("pdf_url"))
    _set(record["open_access"], "license", best.get("license"))
    _set(record["open_access"], "status", (work.get("open_access") or {}).get("oa_status"))
    _set_open_access(record, (work.get("open_access") or {}).get("is_oa"))


def _openalex_abstract(inverted):
    """OpenAlex ships abstracts as `{word: [positions]}`; this puts the sentence back together."""
    if not isinstance(inverted, dict) or not inverted:
        return None
    positions = []
    for word, places in inverted.items():
        for place in places or []:
            positions.append((place, word))
    return _clean(" ".join(word for _, word in sorted(positions))) if positions else None


def _take_unpaywall(work, record):
    _set(record["identifiers"], "doi", work.get("doi"))
    _set(record["metadata"], "title", _clean(work.get("title")))
    _set(record["metadata"], "year", work.get("year"))
    _set(record["metadata"], "container", work.get("journal_name"))
    best = work.get("best_oa_location") or {}
    _set(record["open_access"], "pdf_url", best.get("url_for_pdf") or best.get("url"))
    _set(record["open_access"], "license", best.get("license"))
    _set(record["open_access"], "status", work.get("oa_status"))
    _set_open_access(record, work.get("is_oa"))


def _take_europepmc(result, record):
    identifiers, metadata = record["identifiers"], record["metadata"]
    _set(identifiers, "doi", result.get("doi"))
    _set(identifiers, "pmid", result.get("pmid") or (result.get("id") if result.get("source") == "MED" else None))
    _set(identifiers, "pmcid", result.get("pmcid"))
    _set(metadata, "title", _clean(result.get("title")))
    _set(metadata, "authors", [
        part.strip() for part in str(result.get("authorString") or "").split(",") if part.strip()
    ])
    _set(metadata, "year", _int(result.get("pubYear")))
    _set(metadata, "container", result.get("journalTitle") or (result.get("journalInfo") or {}).get("journal", {}).get("title"))
    _set(metadata, "type", result.get("pubType"))
    if not record["abstract"]:
        record["abstract"] = _clean(result.get("abstractText"))
    _set_open_access(record, None if result.get("isOpenAccess") is None else str(result["isOpenAccess"]).upper() == "Y")


def _take_arxiv(entry, record):
    identifiers, metadata = record["identifiers"], record["metadata"]
    atom, arxiv = "{http://www.w3.org/2005/Atom}", "{http://arxiv.org/schemas/atom}"
    absolute = _text(entry.find(atom + "id"))
    _set(identifiers, "arxiv_id", _arxiv_id_from_url(absolute))
    _set(identifiers, "url", absolute)
    _set(identifiers, "doi", _text(entry.find(arxiv + "doi")))
    _set(metadata, "title", _clean(_text(entry.find(atom + "title"))))
    _set(metadata, "authors", [
        _clean(_text(author.find(atom + "name"))) or "" for author in entry.findall(atom + "author")
    ])
    published = _text(entry.find(atom + "published")) or ""
    _set(metadata, "year", _int(published[:4]))
    _set(metadata, "container", _text(entry.find(arxiv + "journal_ref")) or "arXiv")
    category = entry.find(arxiv + "primary_category")
    _set(metadata, "type", category.get("term") if category is not None else "preprint")
    _set(metadata, "version", _arxiv_version(absolute))
    if not record["abstract"]:
        record["abstract"] = _clean(_text(entry.find(atom + "summary")))
    for link in entry.findall(atom + "link"):
        if link.get("title") == "pdf":
            _set(record["open_access"], "pdf_url", link.get("href"))
    _set_open_access(record, True)


def _take_biorxiv(detail, server, record):
    identifiers, metadata = record["identifiers"], record["metadata"]
    _set(identifiers, "doi", detail.get("doi"))
    _set(metadata, "title", _clean(detail.get("title")))
    _set(metadata, "authors", [part.strip() for part in str(detail.get("authors") or "").split(";") if part.strip()])
    _set(metadata, "year", _int(str(detail.get("date") or "")[:4]))
    _set(metadata, "container", server)
    _set(metadata, "type", "preprint")
    _set(metadata, "version", str(detail.get("version")) if detail.get("version") else None)
    if detail.get("published") and str(detail["published"]).lower() not in ("na", "none"):
        _set(identifiers, "published_doi", detail["published"])
    if not record["abstract"]:
        record["abstract"] = _clean(detail.get("abstract"))
    _set_open_access(record, True)
    _set(record["open_access"], "license", detail.get("license"))


# --- the arXiv feed ------------------------------------------------------------------------------


def _arxiv_entry(answer):
    """The one entry of an `id_list` feed; None when arXiv answered with its error entry or none, False when the feed is unreadable."""
    try:
        feed = ElementTree.fromstring(answer.body)
    except ElementTree.ParseError:
        return False
    atom = "{http://www.w3.org/2005/Atom}"
    for entry in feed.findall(atom + "entry"):
        identifier = _text(entry.find(atom + "id")) or ""
        if "api/errors" in identifier:
            return None
        return entry
    return None


class _MetaTags(HTMLParser):
    """Every `<meta name=... content=...>` of a page, the repeated ones (`citation_author`) in order."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags = {}

    def handle_starttag(self, tag, attrs):
        if tag != "meta":
            return
        values = dict(attrs)
        name, content = values.get("name"), values.get("content")
        if name and content is not None:
            self.tags.setdefault(name.lower(), []).append(html.unescape(content).strip())


def _meta_tags(text):
    """The page's meta tags as `{name: content}`, with `citation_author` kept as the list of every author."""
    reader = _MetaTags()
    try:
        reader.feed(text)
        reader.close()
    except Exception:  # a page that is not HTML has no tags, which the caller reads as unreadable
        return {}
    tags = {name: values[0] for name, values in reader.tags.items()}
    tags["citation_author"] = reader.tags.get("citation_author", [])
    return tags


def _take_abs_page(tags, identifier, record):
    identifiers, metadata = record["identifiers"], record["metadata"]
    _set(identifiers, "arxiv_id", tags.get("citation_arxiv_id") or identifier)
    _set(identifiers, "doi", ARXIV_DOI % identifier)
    _set(identifiers, "url", ARXIV_ABS % identifier)
    _set(metadata, "title", _clean(tags.get("citation_title")))
    _set(metadata, "authors", [_unflip(author) for author in tags.get("citation_author") or []])
    _set(metadata, "year", _int((tags.get("citation_date") or tags.get("citation_online_date") or "")[:4]))
    _set(metadata, "container", "arXiv")
    _set(metadata, "type", "preprint")
    if not record["abstract"]:
        record["abstract"] = _clean(tags.get("citation_abstract"))
    _set(record["open_access"], "pdf_url", tags.get("citation_pdf_url"))
    _set_open_access(record, True)


def _unflip(name):
    """`Noether, Emmy` as `Emmy Noether`, the order the other sources write a name in."""
    family, comma, given = str(name).partition(",")
    return ("%s %s" % (given.strip(), family.strip())).strip() if comma else str(name).strip()


def _text(node):
    return None if node is None else _SPACES.sub(" ", (node.text or "")).strip()


def _arxiv_id_from_url(url):
    if not url:
        return None
    tail = url.rstrip("/").rsplit("/abs/", 1)[-1].rsplit("/", 1)[-1]
    return tail or None


def _arxiv_version(url):
    found = re.search(r"v(\d+)$", url or "")
    return found.group(1) if found else None


def _bare_doi(value):
    if not value:
        return None
    return re.sub(r"^https?://(dx\.)?doi\.org/", "", str(value), flags=re.IGNORECASE)


def _tail(value):
    return str(value).rstrip("/").rsplit("/", 1)[-1] if value else None


def _int(value):
    try:
        return int(str(value)[:4])
    except (TypeError, ValueError):
        return None
