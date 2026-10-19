"""Inherited passages: a project's own earlier writing deconstructed verbatim (Implementation Decision 17; ticket 93).

A project started midway brings an earlier manuscript, a separate Methods, or a supplement, kept and sorted
`inherited` by `wayline.documents`. Code deconstructs each into **inherited passages** in the sections, so the owner
can tell what holds from what is overstated:

- **Headings.** Only text under a heading that maps to Introduction, Results, Discussion, or Methods is taken, through
  the fixed `HEADING_TABLE`; a subheading follows its parent; any other heading is placed by the setup session
  (`places`), or with no session under Results as written, and listed in `research/DOCUMENTS.md`.
- **Kept, never deconstructed.** The title, the abstract, the front matter before the first heading, captions, back
  matter, availability statements, and the reference list stay in the document's record (`deconstructed.kept`), so
  none of them reaches the paper.
- **Claims.** Every paragraph is split at its claims: each sentence the sentence classifier (`provenance.classify`,
  the launcher's `classifier` role) calls a claim is one passage, and the sentences between claims stay together.
  Each passage ends with a `{doc:<document>#<locator>}` tag naming the block and the sentence or run of sentences
  (`D1#p4.s2`, `D1#p4.s1-s3`; `D1#p6` for a block kept whole, such as a display equation): provenance, never a
  citation. A pandoc citation `[@key]` becomes an identifier `ref` tag at the end of its sentence, with no locator:
  `{ref:doi:<doi>}`, `{ref:arxiv:<id>}`, or `{ref:title:<exact title>}` from the document's `citations.json`; a key
  no work there names stays as written.
- **Standing.** An inherited claim stands `unchecked` until a ticket's passage or finding replaces it saying in
  `evidence` whether this project's evidence supports, narrows, or contradicts it, or it is found `unverifiable`
  (`mark_unverifiable`, with the reason), which is kept apart from unchecked.
- **Placement by content.** The setup session that reads the inherited passages proposes, for each passage of a
  separate Methods or supplement that reports or interprets an outcome, its place in Results or Discussion;
  `move_passage` moves it (a withdrawal where it stood, the passage again where it goes) and lists the move.
- **No pandoc.** A `.docx` kept without a conversion has no text: nothing is deconstructed from it, and the reason
  is listed.
- **A newer version** of the document, handed over later, is taken in like a section edit by `deconstruct` again:
  new text becomes new inherited passages, changed text replaces what it changed, removed text is withdrawn, and an
  unchanged passage whose block moved is tagged again at its new locator.
"""

import difflib
import re
import sys
from pathlib import Path

from wayline import provenance, sections
from wayline.documents import (
    DOCUMENTS_DIR, FRONT, DocumentError, heading_of, read_documents, save_documents, text_blocks,
)
from wayline.ledger import Ledger, ledger_for

__all__ = [
    "HEADING_TABLE", "KEPT_HEADINGS", "InheritedError", "map_heading", "citation_tag", "deconstruct", "move_passage",
    "mark_unverifiable", "document_passages",
]

# The fixed heading table: a top-level heading's words, once numbering, case, and `&` are set aside.
HEADING_TABLE = {
    "introduction": "introduction", "background": "introduction",
    "results": "results", "results and discussion": "results",
    "discussion": "discussion", "conclusions": "discussion", "outlook": "discussion",
    "methods": "methods", "materials and methods": "methods", "theory": "methods", "model": "methods",
    "algorithm": "methods",
}
# Headings whose text is kept and read, never deconstructed, whatever their parent.
KEPT_HEADINGS = {
    "abstract": "abstract",
    "references": "references", "bibliography": "references", "reference list": "references",
    "literature cited": "references", "works cited": "references",
    "acknowledgements": "back_matter", "acknowledgments": "back_matter", "acknowledgement": "back_matter",
    "acknowledgment": "back_matter", "funding": "back_matter", "author contributions": "back_matter",
    "competing interests": "back_matter", "conflict of interest": "back_matter", "conflicts of interest": "back_matter",
    "declarations": "back_matter", "declaration of interests": "back_matter", "ethics statement": "back_matter",
    "abbreviations": "back_matter",
}
KEPT = "kept"
DEFAULT_SECTION = sections.RESULTS
MOVE_TO = ("introduction", "results", "discussion", "methods")

_NUMBERING = re.compile(r"^(?:\d+(?:\.\d+)*|[ivxlcIVXLC]+|[A-Z])[.)]?\s+")
_CAPTION = re.compile(r"^[*_]*(?:Supplementary\s+|Extended\s+Data\s+)?(?:Figure|Fig\.?|Table|Movie|Video|Box)\s+S?\d+[A-Za-z]?\s*[.:|]",
                      re.IGNORECASE)
_CITATION = re.compile(r"\s*\[((?:[^\[\]]*?@[^\[\]]+))\]")
# A citation written after its sentence's stop (`dusk. [@a] Next`) is put back before the stop, so it stays with its sentence.
_AFTER_STOP = re.compile(r"([.!?])((?:\s*\[[^\[\]]*@[^\[\]]+\])+)")
_CITE_KEY = re.compile(r"@([A-Za-z0-9_][A-Za-z0-9_:.#$%&+?<>~/-]*[A-Za-z0-9_])")
_SENTENCE_TAIL = re.compile(r"([.!?][\"')\]]*)\s*$")
_DOC_TAG = re.compile(r"\{doc:[^{}]+\}")
_ARXIV_URL = re.compile(r"arxiv\.org/(?:abs|pdf)/([^\s?#]+?)(?:v\d+)?(?:\.pdf)?$", re.IGNORECASE)


class InheritedError(DocumentError):
    """A deconstruction or a move the ledger refuses: no such document or passage, a document that is not inherited."""


# --- the headings -------------------------------------------------------------------------------------


def _words(heading):
    text = re.sub(r"[*_`]", "", str(heading or "")).strip()
    text = _NUMBERING.sub("", text)
    text = text.replace("&", " and ").rstrip(" .:")
    return " ".join(text.lower().split())


def map_heading(heading):
    """What the fixed tables make of a heading: a section, `kept` with its part, or None for any other heading.

    Returns `(section or "kept", part or None)`.
    """
    words = _words(heading)
    if words in KEPT_HEADINGS:
        return KEPT, KEPT_HEADINGS[words]
    if "availability" in words.split():
        return KEPT, "availability"
    if words in HEADING_TABLE:
        return HEADING_TABLE[words], None
    return None, None


# --- the citations ------------------------------------------------------------------------------------


def citation_tag(work):
    """The identifier `ref` tag of one CSL-JSON work, with no locator; None for a work with no identifier or title."""
    work = work or {}
    doi = str(work.get("DOI") or work.get("doi") or "").strip()
    if doi:
        return "{ref:doi:%s}" % re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:)", "", doi, flags=re.IGNORECASE).lower()
    arxiv = str(work.get("arxivId") or work.get("arXiv") or work.get("arxiv") or "").strip()
    found = _ARXIV_URL.search(str(work.get("URL") or "").strip())
    if arxiv or found:
        return "{ref:arxiv:%s}" % (arxiv or found.group(1))
    title = " ".join(str(work.get("title") or "").replace("{", "").replace("}", "").split())
    return "{ref:title:%s}" % title if title else None


def _cited(sentence, works):
    """A sentence with each pandoc citation taken out and its works' `ref` tags put after its last stop."""
    tags = []

    def take(match):
        found = [tag for tag in (citation_tag(works.get(key)) for key in _CITE_KEY.findall(match.group(1))) if tag]
        if not found or len(found) < len(_CITE_KEY.findall(match.group(1))):
            return match.group(0)  # a key no work names stays as written
        tags.extend(tag for tag in found if tag not in tags)
        return ""

    text = _CITATION.sub(take, sentence).strip()
    if not tags:
        return text
    tail = _SENTENCE_TAIL.search(text)
    if tail is None:
        return text + "".join(tags)
    return text[:tail.end(1)] + "".join(tags) + text[tail.end(1):]


# --- reading a document -------------------------------------------------------------------------------


class _Unit:
    """One inherited passage a deconstruction plans: where it goes, its text with its tags, and its locator."""

    def __init__(self, section, heading, text, doc, claim, whole=False):
        self.section, self.heading, self.doc, self.claim = section, heading, doc, claim
        # A block kept whole (an equation, a table, a list) takes its tag after a space, off the markup it ends with.
        self.text = "%s%s{doc:%s}" % (text, " " if whole else "", doc)
        self.plain = _plain(self.text)


def _plain(text):
    """A passage's text without its `doc` tag: what a newer version's text is matched on."""
    return " ".join(_DOC_TAG.sub("", str(text or "")).split())


def _listed(block):
    """Whether a block is a list or a block quote: kept whole, a claim when any of its sentences is one."""
    first = block.lstrip()
    return first.startswith((">", "- ", "* ", "+ ")) or re.match(r"^\d+[.)]\s", first) is not None


def _prose(block):
    """Whether a block is a paragraph of prose, which is split at its claims, rather than a block kept whole."""
    first = block.lstrip()
    return not (_listed(block) or first.startswith(("$$", "```", "~~~", "|", "![", "<", ":::", "\\["))
                or re.match(r"^[-=+:| ]+$", first.split("\n", 1)[0]))


class _Reading:
    """A document's `text.md` walked block by block: the planned units, what was kept, and where each heading went."""

    def __init__(self, document, text, works, places):
        self.document, self.works, self.places = document, works, places or {}
        self.units, self.kept, self.headings = [], [], []
        self.pending = []  # (section, heading, locator, block) of prose and whole blocks, before classification
        self.used = set()  # the places that placed a heading
        self._walk(text)
        unused = [key for key in self.places if key not in self.used]
        if unused:
            raise InheritedError("--place %s places no heading of %s: a place names a heading the table leaves unmapped, "
                                 "by its words or its locator in DOCUMENTS.md, whose parent is not placed already"
                                 % (", ".join(sorted(unused)), document["id"]))

    def _place(self, locator, heading_text, parent):
        """Where a heading's text goes, in this order: kept by the tables; after a parent that was placed (by the
        table, the session, or kept); by the heading table; by the setup session; after a parent that only landed
        under Results for want of a placement; kept as the document's own title; or under Results as written.

        A heading the table maps is never swallowed by an unmapped heading above it (a title the record spells
        differently), and the session may place a subheading of one.
        """
        to, part = map_heading(heading_text)
        if to == KEPT:
            return {"to": KEPT, "part": part, "by": "table"}
        if parent is not None and parent["by"] != "default":
            return dict(parent, by="parent")
        if to is not None:
            return {"to": to, "part": None, "by": "table"}
        placed = self._session(locator, heading_text)
        if placed is not None:
            return placed
        if parent is not None:
            return dict(parent, by="parent")
        if _words(heading_text) and _words(heading_text) == _words(self.document.get("title")):
            return {"to": KEPT, "part": "title", "by": "title"}
        return {"to": DEFAULT_SECTION, "part": None, "by": "default"}

    def _session(self, locator, heading_text):
        for key in (locator, _words(heading_text)):
            if key in self.places:
                self.used.add(key)
                placed = self.places[key]
                return {"to": placed, "part": "back_matter" if placed == KEPT else None, "by": "session"}
        return None

    def _unmapped(self, locator, heading_text):
        return self._session(locator, heading_text) or {"to": DEFAULT_SECTION, "part": None, "by": "default"}

    def _walk(self, text):
        blocks = text_blocks(text)
        if any(locator == FRONT for locator, _ in blocks):
            self.kept += [{"locator": FRONT, "part": part} for part in ("title", "abstract") if self.document.get(part)]
        stack = []  # [(level, placement, heading text)]
        first = next((locator for locator, _ in blocks if locator != FRONT), None)
        if first is not None and not any(heading_of(body) for locator, body in blocks if locator != FRONT):
            # A document with no heading at all (a supplement as a PDF) is one unmapped part under its title.
            title = self.document.get("title") or self.document["id"]
            placement = self._unmapped(first, title)
            stack.append((0, placement, title))
            self.headings.append({"locator": first, "text": title, "to": placement["to"], "by": placement["by"]})
        for locator, body in blocks:
            if locator == FRONT:
                continue
            found = heading_of(body)
            if found is not None:
                level, heading_text = found
                while stack and stack[-1][0] >= level:
                    stack.pop()
                placement = self._place(locator, heading_text, stack[-1][1] if stack else None)
                self.headings.append({"locator": locator, "text": heading_text, "to": placement["to"], "by": placement["by"]})
                if placement["by"] != "title":
                    stack.append((level, placement, heading_text))
                continue
            if not stack:
                self.kept.append({"locator": locator, "part": "front_matter"})
            elif stack[-1][1]["to"] == KEPT:
                self.kept.append({"locator": locator, "part": stack[-1][1]["part"] or "back_matter"})
            elif _CAPTION.match(body.strip()):
                self.kept.append({"locator": locator, "part": "caption"})
            else:
                self.pending.append((stack[-1][1]["to"], stack[-1][2], locator, body.strip()))

    def sentences(self):
        """Every sentence the classifier is asked about, with its citations as tags, in reading order."""
        found = []
        for _, _, _, body in self.pending:
            found += self._split(body)
        return found

    def _split(self, body):
        """A prose block's sentences, or a list's, each with its citations as tags; none for a block of markup."""
        if not (_prose(body) or _listed(body)):
            return []
        flat = _AFTER_STOP.sub(lambda found: found.group(2) + found.group(1), " ".join(body.split()))
        return [_cited(sentence.text, self.works) for sentence in provenance.sentences(flat)]

    def plan(self, classes):
        """The units, once each sentence's class is known (`classes` maps a sentence hash to its class)."""
        document_id = self.document["id"]

        def claim(sentence):
            return classes.get(provenance.sentence_hash(sentence), provenance.CLAIM) == provenance.CLAIM

        for section, heading, locator, body in self.pending:
            if not _prose(body):
                self.units.append(_Unit(section, heading, body, "%s#%s" % (document_id, locator),
                                        any(claim(text) for text in self._split(body)), whole=True))
                continue
            run = []
            for number, sentence in enumerate(self._split(body), 1):
                if claim(sentence):
                    if run:
                        self.units.append(self._run(section, heading, locator, run))
                        run = []
                    self.units.append(_Unit(section, heading, sentence, "%s#%s.s%d" % (document_id, locator, number), True))
                else:
                    run.append((number, sentence))
            if run:
                self.units.append(self._run(section, heading, locator, run))
        return self.units

    def _run(self, section, heading, locator, run):
        first, last = run[0][0], run[-1][0]
        where = "s%d" % first if first == last else "s%d-s%d" % (first, last)
        return _Unit(section, heading, " ".join(text for _, text in run), "%s#%s.%s" % (self.document["id"], locator, where), False)


# --- the passages a document holds --------------------------------------------------------------------


def document_passages(project_or_ledger, document_id):
    """The document's own latest passages, one per piece of its text, in its reading order: `[(record, current)]`.

    A piece's latest passage is the last one the document wrote for it (a replacement it made on a newer version, a
    tag moved, a move, an unverifiable standing); `current` says whether it still stands in its section, which it
    does not once a ticket's passage or finding replaced it. A withdrawn piece is not listed.
    """
    book = ledger_for(project_or_ledger)
    by = "document:%s" % document_id
    ours = [item for item in sections.read_passages(book) if item.get("by") == by]
    followed = {item.get("replaces") for item in ours if item.get("replaces")} | {item.get("moved_from") for item in ours if item.get("moved_from")}
    latest = [item for item in ours if item.get("id") not in followed and not item.get("withdrawn")]
    current = set()
    for section in {item.get("section") for item in latest}:
        current |= sections.current_ids(book, section)
    return sorted(((item, item.get("id") in current) for item in latest), key=lambda pair: _order(pair[0].get("doc")))


def _order(doc):
    found = re.search(r"#p(\d+)(?:\.s(\d+))?", str(doc or ""))
    return (int(found.group(1)), int(found.group(2) or 0)) if found else (sys.maxsize, 0)


# --- deconstructing -----------------------------------------------------------------------------------


def _document(project, document_id):
    document = next((entry for entry in read_documents(project) if entry.get("id") == document_id), None)
    if document is None:
        raise InheritedError("no document %s; the documents are listed in research/DOCUMENTS.md" % document_id)
    if document.get("kind") != "inherited":
        raise InheritedError("%s is sorted %s; only an inherited document is deconstructed" % (document_id, document.get("kind")))
    return document


def _not_converted(document):
    loss = next((entry for entry in document.get("losses") or [] if entry.startswith("not converted")), None)
    return "%s was kept as given and has no text (%s)" % (document.get("origin") or "it", loss or "not converted")


def _works(book, document_id):
    try:
        listed = book.read_json("%s/%s/citations.json" % (DOCUMENTS_DIR, document_id))
    except (OSError, ValueError):
        return {}
    return {str(work.get("id")): work for work in listed if isinstance(work, dict)} if isinstance(listed, list) else {}


def _record(book, document_id, change):
    """Apply `change(deconstructed)` to the document's record and save it; the caller holds the lock."""
    documents = read_documents(book.project)
    document = next(entry for entry in documents if entry.get("id") == document_id)
    document["deconstructed"] = change(dict(document.get("deconstructed") or {}))
    save_documents(book, documents)
    return document["deconstructed"]


def _standing(units):
    return sum(1 for item, current in units if current and item.get("standing") in sections.STANDINGS)


def deconstruct(project, document_id, places=None, offline=False):
    """Deconstruct an inherited document, or take in its newer version; returns what was done.

    `places` is the setup session's placement of headings the table does not map: `{locator or heading: section}`,
    a section of `sections.INHERITED` or `kept`. The classifier runs once over every sentence its cache does not hold
    (`offline` launches nothing, and an unclassified sentence counts as a claim, which leaves it unchecked). The
    result is `{id, version, written, new, replaced, withdrawn, retagged, passages, claims, listed, reason, said}`.
    """
    project = Path(project).resolve()
    book = Ledger(project)
    document = _document(project, document_id)
    places = {(key if re.match(r"^p\d+$", str(key)) else _words(key)): value for key, value in (places or {}).items()}
    for key, value in places.items():
        if value not in sections.INHERITED + (KEPT,):
            raise InheritedError("a heading is placed in one of %s, or kept; got %r for %s"
                                 % (", ".join(sections.INHERITED), value, key))
    path = book.path("%s/%s/text.md" % (DOCUMENTS_DIR, document_id))
    if not document.get("converted") or not path.is_file():
        with book.lock():
            standing = document_passages(book, document_id)
            earlier = (document.get("deconstructed") or {}).get("version")
            reason = _not_converted(document) + ("; the inherited passages of version %d stand" % earlier
                                                 if earlier and any(current for _, current in standing) else "")
            passages, claims = sum(1 for _, current in standing if current), _standing(standing)
            _record(book, document_id, lambda done: {
                "version": document["version"], "reason": reason, "passages": passages, "claims": claims,
                "headings": list(done.get("headings") or []), "kept": list(done.get("kept") or []), "moves": list(done.get("moves") or [])})
        return {"id": document_id, "version": document["version"], "written": [], "new": 0, "replaced": 0, "withdrawn": 0,
                "retagged": 0, "passages": passages, "claims": claims, "listed": [reason], "reason": reason,
                "said": "%s: nothing deconstructed: %s" % (document_id, reason)}
    reading = _Reading(document, path.read_text(encoding="utf-8"), _works(book, document_id), places)
    classes = provenance.classify(project, reading.sentences(), offline=offline)
    units = reading.plan(classes)
    with book.lock():
        counts, written = _take_in(book, document_id, units)
        standing = document_passages(book, document_id)
        listed = ["%s placed under Results as written: no session placed it" % heading["text"]
                  for heading in reading.headings if heading["by"] == "default"]
        _record(book, document_id, lambda done: {
            "version": document["version"], "reason": None, "passages": sum(1 for _, current in standing if current),
            "claims": _standing(standing), "headings": reading.headings, "kept": reading.kept, "moves": list(done.get("moves") or [])})
        sections.render_sections(book, only=[name for name in sections.INHERITED])
    said = "%s version %d: %d new, %d replaced, %d withdrawn, %d tagged again; %d inherited passages stand, %d of them claims" % (
        document_id, document["version"], counts["new"], counts["replaced"], counts["withdrawn"], counts["retagged"],
        sum(1 for _, current in standing if current), _standing(standing))
    return dict(counts, id=document_id, version=document["version"], written=written, listed=listed, reason=None,
                passages=sum(1 for _, current in standing if current), claims=_standing(standing),
                said=said + "".join("; %s" % line for line in listed))


def _take_in(book, document_id, units):
    """Write the units against what the document already holds, like a section edit; the caller holds the lock."""
    by = "document:%s" % document_id
    old = document_passages(book, document_id)
    counts = {"new": 0, "replaced": 0, "withdrawn": 0, "retagged": 0}
    written = []

    def add(section, heading, text, **fields):
        written.append(sections.add_passage(book, section, heading, text, by=by, render=False, **fields))

    def new(unit, standing=None, reason=None):
        add(unit.section, unit.heading, unit.text, doc=unit.doc, standing=standing or (sections.UNCHECKED if unit.claim else None),
            reason=reason)
        counts["new"] += 1

    def withdraw(item):
        add(item["section"], item["heading"], item["text"], replaces=item["id"], doc=item.get("doc"), withdrawn=True)
        counts["withdrawn"] += 1

    def rewrite(item, unit, standing, reason, count):
        """The piece again as the newer version has it: in its place, under the newer heading, unless the newer version
        put it in another section (withdrawn here, new there); a piece the session moved keeps where it was moved."""
        if item.get("moved_from") or unit.section == item["section"]:
            heading = item["heading"] if item.get("moved_from") else unit.heading
            add(item["section"], heading, unit.text, replaces=item["id"], doc=unit.doc, standing=standing, reason=reason)
            counts[count] += 1
        else:
            withdraw(item)
            new(unit, standing, reason)

    matcher = difflib.SequenceMatcher(a=[_plain(item.get("text")) for item, _ in old], b=[unit.plain for unit in units], autojunk=False)
    for operation, low, high, start, end in matcher.get_opcodes():
        if operation == "equal":
            for (item, current), unit in zip(old[low:high], units[start:end]):
                moved = not item.get("moved_from") and (unit.section, unit.heading) != (item["section"], item["heading"])
                if current and (item.get("doc") != unit.doc or moved):
                    rewrite(item, unit, item.get("standing"), item.get("reason"), "retagged")
            continue
        pairs = min(high - low, end - start) if operation == "replace" else 0
        for (item, current), unit in zip(old[low:low + pairs], units[start:start + pairs]):
            if current:
                rewrite(item, unit, sections.UNCHECKED if unit.claim else None, None, "replaced")
            else:
                new(unit)  # a ticket's word stands where the earlier text stood; the changed text stands beside it
        for unit in units[start + pairs:end]:
            new(unit)
        for item, current in old[low + pairs:high]:
            if current:
                withdraw(item)
    return counts, written


# --- after the deconstruction -------------------------------------------------------------------------


def _current_inherited(book, passage_id):
    item = next((entry for entry in sections.read_passages(book) if entry.get("id") == passage_id), None)
    if item is None or not sections.is_inherited(item):
        raise InheritedError("%s is not an inherited passage" % passage_id)
    if passage_id not in sections.current_ids(book, item["section"]) or item.get("withdrawn"):
        raise InheritedError("%s no longer stands in %s: a later passage replaced it" % (passage_id, sections.TITLES[item["section"]]))
    return item


def move_passage(project, passage_id, section, heading=None):
    """Move an inherited passage to another section on the setup session's proposal, and list the move.

    A separate Methods or supplement is placed by content: a passage that reports or interprets an outcome goes to
    Results or Discussion. The passage is withdrawn where it stood and written again where it goes, with its tags, its
    standing, and `moved_from`, under `heading` (its own when None). Returns the passage written.
    """
    book = Ledger(Path(project).resolve())
    if section not in MOVE_TO:
        raise InheritedError("an inherited passage moves to one of %s, got %r" % (", ".join(MOVE_TO), section))
    with book.lock():
        item = _current_inherited(book, passage_id)
        if item["section"] == section:
            raise InheritedError("%s already stands in %s" % (passage_id, sections.TITLES[section]))
        by = item["by"]
        sections.add_passage(book, item["section"], item["heading"], item["text"], by=by, replaces=passage_id, doc=item.get("doc"),
                             withdrawn=True, render=False)
        moved = sections.add_passage(book, section, heading or item["heading"], item["text"], by=by, doc=item.get("doc"),
                                     standing=item.get("standing"), reason=item.get("reason"), moved_from=passage_id, render=False)
        document_id = by.split(":", 1)[1]
        standing = document_passages(book, document_id)

        def change(done):
            done.setdefault("version", 1)
            done.setdefault("reason", None)
            done.setdefault("headings", [])
            done.setdefault("kept", [])
            done["moves"] = list(done.get("moves") or []) + [{"passage": passage_id, "to_passage": moved["id"], "from": item["section"],
                                                                "to": section}]
            done["passages"] = sum(1 for _, current in standing if current)
            done["claims"] = _standing(standing)
            return done

        _record(book, document_id, change)
        sections.render_sections(book, only=[item["section"], section])
    return moved


def mark_unverifiable(project, passage_id, reason):
    """Record that an inherited claim was tried and could not be checked, with the reason; kept apart from unchecked.

    The claim is written again in its place with the standing `unverifiable` and `reason`. Returns the passage written.
    """
    book = Ledger(Path(project).resolve())
    reason = " ".join(str(reason or "").split())
    if not reason:
        raise InheritedError("an unverifiable claim carries the reason it could not be checked")
    with book.lock():
        item = _current_inherited(book, passage_id)
        if item.get("standing") not in sections.STANDINGS:
            raise InheritedError("%s is not an inherited claim" % passage_id)
        return sections.add_passage(book, item["section"], item["heading"], item["text"], by=item["by"], replaces=passage_id,
                                    doc=item.get("doc"), standing=sections.UNVERIFIABLE, reason=reason)
