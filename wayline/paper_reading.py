"""Reading the paper with its provenance (Implementation Decision 17; ticket 141).

The owner reads the paper's main text on the dashboard as a paper, and sees where every claim comes from. This module
builds what the reading view shows, `reading_view`, as blocks made by code from what is on disk and in the ledger: no
model call, no write, no lock, as every view the dashboard polls.

**The blocks.** The current version's parts in order (`PARTS`: the title, the abstract, then `paper.MAIN_TEXT`), each
opened by a `part` block. A part's lines are walked as `provenance.prose_sentences` walks them, so a sentence here is
the sentence the linter, the classifier, and the checks read: a `heading` (its level, its text, and the id its `{#...}`
attribute names, `O1` or `R2` under Results), a `paragraph` of `sentences`, a list item or a block quote as a paragraph
of its own, and a `code` block. Each main-text figure (`F<n>` of the record's figure block, or of `figures/F<n>/` when
the record lists none) follows the Results, where a compilation places it.

**A sentence** is numbered within its part in the order the walk meets it, and its item id is the part and that number
(`results.s12`, `SENTENCE_ID`); a figure's is its own (`F1`). Each sentence carries:

- `source`, its class under the by-source lens: `owner` (the words of one of the owner's own passages), `result` (a
  `res` tag), `code`, `literature` (`ref`), `document` (`doc`), `unresolved` (a `ref` the order kept "to be resolved",
  or one whose dossier is not verified), `untagged` (a claim with no tag, or one the classifier never read), or `prose`
  (a sentence the classifier read as no claim);
- `tags`, each resolved: a `res` tag's run, ticket, file, and locator with what the locator holds there as the numbers
  check reads it (`BASE_AUROC = 0.8352720450281426`), a `code` tag's file and symbol or lines, a `ref` tag's work, a
  `doc` tag's document; `problem` when it does not resolve, `open` the file the viewer opens;
- `from`, the findings and passages it was written from (those sharing its tags, or its words), with their tickets and
  runs; `result` and `objectives` (from the headings it sits under, then its findings);
- `checks`, every check that judged it, read from the journal's `verdict` events (a sampled `claim_support` verdict on
  it as a claim of the paper or of the general report, a `numbers_match` verdict on it as a finding's sentence) and
  from the paper's `builds` (a gate's point quoting it), never from a model; and `check`, `passed`, `failed`, or
  `unchecked`, the latest word of each check.

A figure carries its `figure_result`: the caption, the result it draws, the data and the script behind it, the
candidates the figure role ranked, the machine checks, and the honesty verdict. The part's alternatives
(`paper.alternatives_of`) are on its `part` block. A project with no composed paper answers an empty version with a
line saying why.
"""

import hashlib
import json
import re
from pathlib import Path

from wayline import builds, numbers, paper, provenance
from wayline.ledger import Ledger
from wayline.project import RESEARCH

__all__ = ["PARTS", "SENTENCE_ID", "FIGURE_ID", "SOURCES", "CHECKS", "reading_view", "read_item", "snapshot"]

PARTS = ("title", "abstract") + tuple(paper.MAIN_TEXT)
PAPER_DIR = RESEARCH + "/paper"
SENTENCE_ID = re.compile(r"^(%s)\.s([1-9][0-9]*)$" % "|".join(PARTS))
FIGURE_ID = re.compile(r"^F[1-9][0-9]*$")
SOURCES = ("owner", "result", "code", "literature", "document", "unresolved", "untagged", "prose")
PASSED, FAILED, UNCHECKED = "passed", "failed", "unchecked"
CHECKS = (PASSED, FAILED, UNCHECKED)
NO_PAPER = ("No paper is composed yet: the paper order composes it, and its main text is read here, each claim with "
            "where it comes from.")
HELD_CHARS = 240          # what a tag's held value shows of a long line or a large JSON node
HELD_LINES = 3            # the lines a text locator shows at most
QUOTED_MIN = 40           # a build's point names a sentence when it quotes this much of it, or all of a shorter one

_ATTRIBUTE = re.compile(r"\s*\{#([^\s{}]+)[^{}]*\}\s*$")
_CROSS = re.compile(r"@(fig|tbl):([A-Za-z0-9_-]+)")
_LABEL = re.compile(r"\s*\{#(?:eq|fig|tbl):[^{}]*\}")
_PLOT = re.compile(r"\s*\{plot:[^{}]*\}")
_RUN_TICKET = re.compile(r"^t([1-9][0-9]*)-a[1-9][0-9]*$")
GATE_NAMES = {"kill_argument": "the kill argument", "paper_read": "the independent read", "sampled_verdicts": "the sampled verdicts"}
WEB_IMAGES = (".png", ".svg", ".jpg", ".jpeg")  # what a browser draws; a figure's PDF is the compilation's
_RESULT_ID = re.compile(r"^R[1-9][0-9]*$")
_OBJECTIVE_ID = re.compile(r"^O[1-9][0-9]*$")


def _one_line(text):
    return " ".join(str(text or "").split())


def plain(text):
    """A sentence as a reader sees it: its tags and labels taken off, `@fig:F1` written "Figure 1"."""
    text = provenance.strip_tags(_PLOT.sub("", _LABEL.sub("", str(text or ""))))
    text = _CROSS.sub(lambda found: "%s %s" % ("Figure" if found.group(1) == "fig" else "Table",
                                               found.group(2)[1:] if found.group(2)[:1] in "FT" else found.group(2)), text)
    return re.sub(r"\s+([.,;:!?])", r"\1", _one_line(text))


# --- what a locator holds -------------------------------------------------------------------------------------------


def _clip_held(text):
    text = _one_line(text)
    return text if len(text) <= HELD_CHARS else text[:HELD_CHARS - 1].rstrip() + "…"


def held_at(text, path, locator):
    """What `locator` holds in the file `path`, as lines a reader takes in at a glance, read where the numbers check
    reads it (`numbers.values_at`): a JSON key as `key = value`, a CSV column as its first values, text lines as they are."""
    suffix = Path(path).suffix.lower()
    locator = str(locator or "").strip()
    if suffix in (".json", ".jsonl"):
        records = [text] if suffix == ".json" else text.splitlines()
        shown = []
        for raw in records:
            try:
                node = numbers._json_at(json.loads(raw), locator)
            except ValueError:
                continue
            if node is not None:
                shown.append(_clip_held("%s = %s" % (locator, json.dumps(node, ensure_ascii=False))))
        return shown[:HELD_LINES]
    lines = text.splitlines()
    span = numbers._LINES.match(locator)
    if span:
        start, end = int(span.group(1)), int(span.group(2) or span.group(1))
        return [_clip_held(line) for line in lines[start - 1:min(end, start - 1 + HELD_LINES)] if line.strip()] if end >= start else []
    if suffix in (".csv", ".tsv"):
        import csv
        import io
        rows = list(csv.reader(io.StringIO(text), delimiter="\t" if suffix == ".tsv" else ","))
        if rows and locator in rows[0]:
            column = rows[0].index(locator)
            cells = [row[column] for row in rows[1:] if column < len(row)]
            return [_clip_held("%s: %s%s" % (locator, ", ".join(cells[:12]), " … (%d rows)" % len(cells) if len(cells) > 12 else ""))]
        return [_clip_held(", ".join(row)) for row in rows if locator in row][:HELD_LINES]
    return [_clip_held(line) for line in lines if locator and locator in line][:HELD_LINES]


def code_held(text, locator):
    """The line a `code` tag names: its lines `L<a>-L<b>`, or the line that defines its symbol."""
    lines = text.splitlines()
    span = numbers._LINES.match(locator)
    if span:
        start, end = int(span.group(1)), int(span.group(2) or span.group(1))
        return [_clip_held(line) for line in lines[start - 1:min(end, start - 1 + HELD_LINES)] if line.strip()]
    name = re.escape(locator.rsplit(".", 1)[-1])
    defines = re.compile(r"^\s*(?:async\s+def|def|class)\s+%s\b|^%s\s*[:=]" % (name, name))
    return [_clip_held(line) for line in lines if defines.search(line)][:1]


# --- the view -------------------------------------------------------------------------------------------------------


def _part_file(project, part):
    """A part's file as it is on disk, or None when it is not there."""
    try:
        return (project / PAPER_DIR / ("%s.md" % part)).read_text(encoding="utf-8")
    except OSError:
        return None


def _empty(line, problems=()):
    return {"version": None, "order": None, "composed": None, "blocks": [], "objectives": [], "line": line,
            "counts": {}, "problems": list(problems)}


def reading_view(project):
    """The reading view of the current version: `{version, order, composed, blocks, objectives, line, counts, problems}`."""
    project = Path(project).resolve()
    try:
        record = paper.read_record(project)
    except paper.PaperError as failure:
        return _empty("The paper's record cannot be read, so its text is not shown: %s" % failure, [str(failure)])
    if record is None:
        return _empty(NO_PAPER)
    context = _Context(project, record)
    blocks = []
    for part in PARTS:
        held = _part_file(project, part)
        blocks.append(context.part_block(part, held))
        if held is None:
            continue
        text = paper._STAMP.sub("", held, count=1)
        number = 0
        under = {}
        for block in provenance.prose_blocks(text):
            if block["type"] == "heading":
                attribute = _ATTRIBUTE.search(block["text"])
                identifier = attribute.group(1) if attribute else None
                under = {level: value for level, value in under.items() if level < block["level"]}
                under[block["level"]] = identifier
                blocks.append({"type": "heading", "part": part, "level": block["level"], "id": identifier,
                               "text": plain(block["text"][:attribute.start()] if attribute else block["text"])})
            elif block["type"] == "code":
                blocks.append(dict(block, part=part))
            else:
                sentences = []
                for found in block["sentences"]:
                    number += 1
                    sentences.append(context.sentence(part, number, found, [value for _, value in sorted(under.items()) if value]))
                blocks.append({"type": "paragraph", "part": part, "sentences": sentences})
        if part == "results":
            blocks += context.figures()
    return {"version": record["version"], "order": record["order"], "composed": record["composed"], "blocks": blocks,
            "objectives": context.objective_rows(), "line": None, "counts": _counts(blocks), "problems": context.problems}


def _counts(blocks):
    found = {"source": {}, "check": {}}
    for block in blocks:
        for sentence in block.get("sentences") or []:
            for lens in ("source", "check"):
                found[lens][sentence[lens]] = found[lens].get(sentence[lens], 0) + 1
    return found


class _Context:
    """What the sentences of one version are read against, each read once: the journal, the manifest, the findings,
    the passages, the results, the objectives, the claim classes, and the files a tag names."""

    def __init__(self, project, record):
        self.project = project
        self.record = record
        self.book = Ledger(project)
        self.problems = []
        self.files = {}
        self.events = self._events()
        self.manifest = self._guard("manifest.json", lambda: provenance.read_manifest(self.book), {"entries": []})
        self.manifested = {(entry.get("run_id"), entry.get("path")) for entry in self.manifest.get("entries", [])}
        self.classes = provenance.read_claims_cache(self.book)
        self.resolver = self._guard("manifest.json", lambda: provenance._Resolver(project), None)
        if self.resolver is not None:
            self.resolver._code_read = provenance.code_reader(project)  # the working tree: a poll runs no git
        self.marks = {str(answer.get("ref") or "").partition(":")[2]: answer.get("mark")
                      for answer in record.get("answers") or [] if str(answer.get("ref") or "").startswith("reference:")}
        self._results = None
        self._owner_hashes = None
        self._passages = None
        self._written = None
        self._verdicts = None

    def _guard(self, what, read, default):
        try:
            return read()
        except (OSError, ValueError) as failure:
            self.problems.append("%s: %s" % (what, failure))
            return default

    def _events(self):
        return self._guard("the journal", lambda: self.book.read_events()[0], [])

    # --- parts ---

    def part_block(self, part, text):
        from wayline.dashboard_views import PART_TITLES, _clip
        held = (self.record.get("parts") or {}).get(part) or {}
        current = (text or "").strip()
        return {"type": "part", "part": part, "title": PART_TITLES.get(part, part), "path": "%s/%s.md" % (PAPER_DIR, part),
                "exists": text is not None, "version": held.get("version"),
                "edited": text is not None and bool(held.get("sha256")) and paper._sha(text) != held.get("sha256"),
                "alternatives": [{"name": name, "text": _clip(alternative), "path": "%s/%s/%s.md" % (PAPER_DIR, paper.ALTERNATIVES, name),
                                  "current": alternative == current}
                                 for name, alternative in paper.alternatives_of(self.book, self.record, part)]}

    # --- sentences ---

    def sentence(self, part, number, found, headings):
        tags = [self.tag(tag) for tag in found.tags]
        written = self.written_from(found)
        result = next((value for value in reversed(headings) if _RESULT_ID.match(value)), None)
        if result is None:
            result = next((item["result"] for item in written if item.get("result")), None)
        goals = [value for value in headings if _OBJECTIVE_ID.match(value)]
        goals += self.result_objectives(result)
        goals += [goal for item in written for goal in item.get("objectives") or []]
        runs = [tag["run"] for tag in tags if tag.get("run")] + [item["run"] for item in written if item.get("run")]
        tickets = [tag["ticket"] for tag in tags if tag.get("ticket")] + [item["ticket"] for item in written if item.get("ticket")]
        checks = self.checks(found)
        return {"id": "%s.s%d" % (part, number), "part": part, "number": number, "text": found.text, "plain": plain(found.text),
                "source": self.source(found, tags), "tags": tags, "from": written, "result": result,
                "objectives": _unique(goals), "runs": _unique(runs), "tickets": _unique(tickets), "checks": checks,
                "check": standing(checks)}

    # --- what a sentence was written from ---

    def results(self):
        """`({finding id: result id}, {result id: [objective ids]})` of the live results."""
        if self._results is None:
            from wayline import results
            held = self._guard("results.json", lambda: results.read_results(self.book), [])
            self._results = ({finding.get("id"): result.id for result in held for finding in result.findings},
                             {result.id: list(result.objectives) for result in held})
        return self._results

    def result_objectives(self, result):
        return list(self.results()[1].get(result) or []) if result else []

    def written(self):
        """Every current finding and every passage that could stand behind a sentence: `(item, its tags, its hashes, its
        text as written)`, the item what the panel shows."""
        if self._written is None:
            from wayline import sections
            items = []
            current = self._guard("findings.jsonl", lambda: provenance.current_findings(self.book), [])
            for finding in current:
                tags = set(provenance.finding_tags(finding, self.manifest))
                tags |= {"%s:%s" % pair for pair in provenance.ANY_TAG_RE.findall(str(finding.get("text") or ""))}
                hashes = {provenance.sentence_hash(sentence.text) for sentence in provenance.prose_sentences(finding.get("text"))}
                run = re.match(r"^(t[1-9][0-9]*-a[1-9][0-9]*)-f[1-9][0-9]*$", str(finding.get("id") or ""))
                items.append(({"kind": "finding", "id": finding.get("id"), "text": plain(finding.get("text")),
                               "ticket": finding.get("ticket"), "run": run.group(1) if run else None,
                               "result": self.results()[0].get(finding.get("id")),
                               "objectives": list(finding.get("objectives") or []), "negative": bool(finding.get("negative"))},
                              tags, hashes, str(finding.get("text") or "")))
            passages = self.passages()
            replaced = {item.get("replaces") for item in passages if item.get("replaces")}
            for passage in passages:
                if passage.get("withdrawn") or passage.get("id") in replaced or sections.is_reason(passage):
                    continue
                text = str(passage.get("text") or "")
                tags = {"%s:%s" % pair for pair in provenance.ANY_TAG_RE.findall(text)}
                hashes = {provenance.sentence_hash(sentence.text) for sentence in provenance.prose_sentences(text)}
                items.append(({"kind": "passage", "id": passage.get("id"), "text": plain(text), "by": passage.get("by"),
                               "section": passage.get("section"), "heading": passage.get("heading"), "ticket": passage.get("ticket"),
                               "run": None, "result": None, "objectives": list(passage.get("objectives") or [])}, tags, hashes, text))
            self._written = items
        return self._written

    def written_from(self, found):
        """The findings and passages a sentence was written from: those holding its words, else those sharing the most
        of its tags (a `doc` tag says where an inherited claim came from, not what it was written from)."""
        digest = provenance.sentence_hash(found.text)
        same = [item for item, _, hashes, _ in self.written() if digest in hashes]
        if same:
            return same
        tags = {tag for tag in found.tags if not tag.startswith("doc:")}
        if not tags:
            return []
        shared = [(len(tags & held), item) for item, held, _, _ in self.written()]
        best = max((count for count, _ in shared), default=0)
        return [item for count, item in shared if count and count == best][:3]

    # --- checks ---

    def verdicts(self):
        """`({subject: its latest claim verdict}, {sentence digest: [its latest numbers_match verdicts]})`.

        A `numbers_match` verdict's subject names its finding's sentence by a digest of its text, tags and all
        (`numbers.judge`); each current finding's sentences are read once more so a paper sentence with that
        sentence's words, its tags reordered or trimmed, is found by its words as well (`sentence_hash`).
        """
        if self._verdicts is None:
            latest = {}
            for event in self.events:
                payload = event.get("payload") or {}
                if event.get("event") == "verdict" and payload.get("subject_kind") == provenance.CLAIM:
                    latest[payload.get("subject")] = dict(payload, ticket=event.get("ticket"), ts=event.get("ts"))
            by_digest = {}
            for subject, payload in latest.items():
                _, mark, digest = str(subject).rpartition("#numbers-")
                if mark and payload.get("verdict_type") == "numbers_match":
                    by_digest.setdefault(digest, []).append(payload)
            for item, _, _, text in self.written():
                if item["kind"] != "finding":
                    continue
                for sentence in provenance.prose_sentences(text):
                    held = by_digest.get(_digest(sentence.text))
                    if held:
                        by_digest.setdefault(provenance.sentence_hash(sentence.text), [])
                        by_digest[provenance.sentence_hash(sentence.text)] += [one for one in held
                                                                                if one not in by_digest[provenance.sentence_hash(sentence.text)]]
            self._verdicts = (latest, by_digest)
        return self._verdicts

    def checks(self, found):
        """Every check that judged one sentence, the latest word of each: its sampled claim verdict (as the paper's claim, or
        the general report's, whose sample the paper's builds share), its numbers check's verdict, and the points of the
        last build's gates that quote it."""
        latest, by_digest = self.verdicts()
        claim = provenance.Claim(found.text, found.tags, provenance.sentence_hash(found.text))
        shown = []
        for document in (builds.PAPER_SUBJECT, provenance.REPORT_PATH):
            payload = latest.get(provenance.claim_subject(claim, document))
            if payload is not None:
                shown.append(_verdict_check("claim verdict", payload))
        judged = list(by_digest.get(_digest(found.text), []))
        judged += [one for one in by_digest.get(provenance.sentence_hash(found.text), []) if one not in judged]
        for payload in judged:
            shown.append(_verdict_check("numbers check", payload))
        quoted = builds._plain(found.text)
        if quoted:
            last = (self.record.get("builds") or [])[-1:] or []
            for entry in last:
                for gate in entry.get("gates") or []:
                    for point in gate.get("points") or []:
                        if _quotes(str(point), quoted):
                            shown.append({"check": "build %s: %s" % (entry.get("build"), GATE_NAMES.get(gate.get("gate"), gate.get("gate"))),
                                          "pass": False, "text": str(point), "model": gate.get("model"),
                                          "session_id": gate.get("session_id"), "findings": [], "verdict_type": gate.get("gate")})
        return shown

    def passages(self):
        if self._passages is None:
            from wayline import sections
            self._passages = self._guard("passages.jsonl", lambda: sections.read_passages(self.book), [])
        return self._passages

    def owners(self):
        """The hashes of the sentences of the owner's own passages: a paper sentence with their words is the owner's."""
        if self._owner_hashes is None:
            from wayline import sections
            self._owner_hashes = {provenance.sentence_hash(sentence.text) for passage in self.passages()
                                  if passage.get("by") == sections.OWNER and not passage.get("withdrawn")
                                  for sentence in provenance.prose_sentences(passage.get("text"))}
        return self._owner_hashes

    def source(self, found, tags):
        digest = provenance.sentence_hash(found.text)
        if digest in self.owners():
            return "owner"
        kinds = [tag["kind"] for tag in tags]
        if any(tag["kind"] == "ref" and (tag.get("existence") != "verified" or tag["mark"] == paper.TO_BE_RESOLVED) for tag in tags):
            return "unresolved"
        if not kinds:
            known = self.classes.get(digest)
            return "untagged" if known in (None, provenance.CLAIM) else "prose"
        for kind, name in (("res", "result"), ("code", "code"), ("ref", "literature"), ("doc", "document")):
            if kind in kinds:
                return name
        return "untagged"

    # --- tags ---

    def read_file(self, relative):
        """A project file's text, read once per view; None when it is not there or not inside the project."""
        if relative not in self.files:
            path = Path(relative)
            text = None
            if relative and not path.is_absolute() and ".." not in path.parts:
                try:
                    text = (self.project / path).read_text(encoding="utf-8", errors="replace")
                except OSError:
                    text = None
            self.files[relative] = text
        return self.files[relative]

    def _openable(self, relative):
        return relative if relative and self.read_file(relative) is not None else None

    def tag(self, tag):
        kind, parts = provenance.parse_tag(tag)
        found = {"tag": tag, "kind": kind, "problem": None, "open": None, "held": [], "values": []}
        problem = self.resolver.problem(tag) if self.resolver is not None else None
        if problem is not None:
            found["problem"] = problem[1]
        if parts is None:
            return found
        if kind == "res":
            run, path, locator = parts["run_id"], parts["artifact"], parts["locator"]
            ticket = _RUN_TICKET.match(run)
            found.update(run=run, ticket=int(ticket.group(1)) if ticket else None, path=path, locator=locator)
            if (run, path) in self.manifested:
                text = self.read_file(path)
                if text is not None:
                    found["values"] = numbers.values_at(text, path, locator) or []
                    found["held"] = held_at(text, path, locator)
                    found["open"] = path
        elif kind == "code":
            path = parts["path"] if parts["path"].startswith(provenance.CODE_DIR + "/") else "%s/%s" % (provenance.CODE_DIR, parts["path"])
            text = self.read_file(path)
            found.update(path=path, locator=parts["locator"], open=self._openable(path),
                         held=code_held(text, parts["locator"]) if text is not None else [])
        elif kind == "ref":
            slug = provenance.ref_slug(parts, self.resolver.index() if self.resolver is not None else {})
            found.update(slug=slug, locator=parts.get("locator"), work=self.work(slug), mark=self.marks.get(slug or ""),
                         existence=self.existence(slug),
                         open=self._openable("%s/refs/%s/dossier.json" % (RESEARCH, slug)) if slug else None)
        elif kind == "doc":
            found.update(document=parts["document"], locator=parts["locator"], item=parts["document"])
        found.setdefault("mark", None)
        return found

    def dossier(self, slug):
        text = self.read_file("%s/refs/%s/dossier.json" % (RESEARCH, slug)) if slug else None
        try:
            value = json.loads(text) if text else None
        except ValueError:
            return None
        return value if isinstance(value, dict) else None

    def existence(self, slug):
        """A cited work's standing as its dossier says it, `verified` or not; None when no dossier is filed."""
        return (self.dossier(slug) or {}).get("existence")

    def work(self, slug):
        """A cited work as a reader names it, `Authors (year), Title`, from its dossier; None when there is none."""
        metadata = (self.dossier(slug) or {}).get("metadata") or {}
        title = metadata.get("title")
        if not title:
            return None
        authors = ", ".join(metadata.get("authors") or [])
        year = " (%s)" % metadata["year"] if metadata.get("year") else ""
        return "%s%s, %s" % (authors, year, title) if authors else "%s%s" % (title, year)

    # --- figures ---

    def figures(self):
        """The main-text figures, each a `figure` block: the record's figure block names them, or, before it did, the
        `figures/F<n>/` folders hold them."""
        listed = [entry for entry in ((self.record.get("figures") or {}).get("figures") or [])
                  if entry.get("main") and FIGURE_ID.match(str(entry.get("id")))]
        if not listed:
            root = self.project / PAPER_DIR / "figures"
            names = sorted((path.name for path in root.glob("F*") if path.is_dir() and FIGURE_ID.match(path.name)),
                           key=lambda name: int(name[1:])) if root.is_dir() else []
            listed = [{"id": name} for name in names]
        return [self.figure(entry) for entry in listed]

    def figure(self, entry):
        from wayline import figure_role
        identifier = entry["id"]
        folder = "%s/figures/%s" % (PAPER_DIR, identifier)
        images = sorted((path for path in (self.project / folder).glob("*") if path.suffix.lower() in WEB_IMAGES),
                        key=lambda path: WEB_IMAGES.index(path.suffix.lower())) if (self.project / folder).is_dir() else []
        caption = self.read_file("%s/caption.md" % folder) or ""
        result = None
        if entry.get("figure_id"):
            result = self._guard("figure %s's figure_result.json" % identifier,
                                 lambda: figure_role.read_result(self.project, entry["figure_id"]), None)
        result = result if isinstance(result, dict) else {}
        final = result.get("final") or {}
        checks = [{key: check.get(key) for key in ("id", "type", "pass", "tool", "detail", "not_run")}
                  for check in result.get("checks") or [] if isinstance(check, dict)]
        honesty = result.get("honesty_verdict") or None
        failed = any(check["pass"] is False for check in checks) or (honesty or {}).get("verdict") == "fail"
        judged = any(check["pass"] is True for check in checks) or (honesty or {}).get("verdict") == "pass"
        tags = [self.tag("%s:%s" % pair) for pair in provenance.ANY_TAG_RE.findall(caption)]
        return {"type": "figure", "part": "results", "id": identifier, "result": entry.get("result"),
                "objectives": self.result_objectives(entry.get("result")), "panels": list(entry.get("panels") or []),
                "image": images[0].relative_to(self.project).as_posix() if images else None,
                "caption": _one_line(_PLOT.sub("", provenance.strip_tags(caption))), "tags": tags,
                "status": entry.get("status") or result.get("status"), "figure_id": entry.get("figure_id"),
                "script": final.get("generator"),
                "data": [{"path": item.get("path"), "run": item.get("run_id"), "open": self._openable(item.get("path"))}
                         for item in final.get("inputs") or [] if isinstance(item, dict)],
                "candidates": [{key: candidate.get(key) for key in ("rank", "index_id", "chart_type", "png", "rendered", "error")}
                               for candidate in result.get("candidates") or [] if isinstance(candidate, dict)],
                "selected": result.get("selected"), "checks": checks, "honesty": honesty,
                "findings_for_text": [item.get("text") if isinstance(item, dict) else str(item)
                                      for item in result.get("findings_for_text") or entry.get("findings_for_text") or []],
                "source": "result" if entry.get("result") else "untagged",
                "check": FAILED if failed else PASSED if judged else UNCHECKED}

    def objective_rows(self):
        from wayline import objectives
        held = self._guard("objectives.json", lambda: objectives.read_objectives(self.project), [])
        return [{"id": item.get("id"), "text": item.get("text"), "status": item.get("status")} for item in held
                if isinstance(item, dict) and _OBJECTIVE_ID.match(str(item.get("id")))]


def _digest(text):
    """The digest a `numbers_match` verdict names its sentence by (`numbers.judge`)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _unique(values):
    seen, found = set(), []
    for value in values:
        if value not in seen:
            seen.add(value)
            found.append(value)
    return found


def _quotes(point, quoted):
    """Whether a gate's point quotes a sentence: all of it, or, for a longer one, its first `QUOTED_MIN` characters."""
    return quoted in point or (len(quoted) > QUOTED_MIN and quoted[:QUOTED_MIN] in point)


def _verdict_check(name, payload):
    return {"check": name, "verdict_type": payload.get("verdict_type"), "pass": bool(payload.get("pass")),
            "model": payload.get("model"), "session_id": payload.get("session_id"), "ticket": payload.get("ticket"),
            "subject": payload.get("subject"), "ts": payload.get("ts"), "fallback_from": payload.get("fallback_from"),
            "findings": [{key: item.get(key) for key in ("severity", "text", "locator")}
                         for item in payload.get("findings") or [] if isinstance(item, dict)]}


def standing(checks):
    """How a sentence stands under the by-check lens: failed when a check's latest word failed it, passed when one
    passed it and none failed, else unchecked."""
    if any(check["pass"] is False for check in checks):
        return FAILED
    return PASSED if any(check["pass"] for check in checks) else UNCHECKED


def read_item(project, identifier):
    """What a sentence's or a figure's item id opens: `{kind, part, path, title, ...}`, the reading view at it; None when
    the current version holds no such sentence or figure, as any stale id is."""
    from wayline.dashboard_views import PAPER_VIEW, _clip, _item
    view = reading_view(project)
    for block in view["blocks"]:
        if block["type"] == "figure" and block["id"] == identifier:
            return _item("figure", PAPER_VIEW, identifier, _clip(block["caption"]) or identifier, block["image"],
                         part="results", status=block["status"])
        for sentence in block.get("sentences") or []:
            if sentence["id"] == identifier:
                return _item("sentence", PAPER_VIEW, identifier, _clip(sentence["plain"]), "%s/%s.md" % (PAPER_DIR, sentence["part"]),
                             part=sentence["part"], number=sentence["number"], status=sentence["check"])
    return None


def snapshot(project):
    """What the view reads outside the ledger's snapshot: the paper's files (`dashboard_views.paper_snapshot` without
    its minute) and each figure role's result the record names."""
    from wayline import figure_role
    from wayline.dashboard_views import _stamps, paper_snapshot
    project = Path(project)
    found = dict(paper_snapshot(project))

    def stamp(path, key):
        try:
            held = path.stat()
        except OSError:
            return
        found[key] = (held.st_mtime_ns, held.st_size)

    found.pop("minute", None)
    for directory in sorted((project / PAPER_DIR / "figures").glob("F*")):
        found.update(_stamps(directory, "figures/%s/" % directory.name))
    try:
        record = paper.read_record(project) or {}
    except paper.PaperError:
        record = {}
    for entry in ((record.get("figures") or {}).get("figures") or []):
        found.update(_stamps(project / figure_role.FIGURES / str(entry.get("figure_id")), "role/%s/" % entry.get("figure_id")))
    # What a sentence's class and its held values read beside the ledger: the claim classes, each cited work's
    # dossier, and every file a tag of the main text names.
    stamp(project / RESEARCH / provenance.CLAIMS_CACHE, "claims")
    try:
        refs = sorted((project / RESEARCH / "refs").iterdir())
    except OSError:
        refs = []
    for folder in refs:
        stamp(folder / "dossier.json", "refs/%s" % folder.name)
    for part in PARTS:
        for kind, rest in provenance.ANY_TAG_RE.findall(_part_file(project, part) or ""):
            _, parts = provenance.parse_tag("%s:%s" % (kind, rest))
            if kind == "res" and parts:
                stamp(project / parts["artifact"], "file/" + parts["artifact"])
            elif kind == "code" and parts:
                path = parts["path"] if parts["path"].startswith(provenance.CODE_DIR + "/") else "%s/%s" % (provenance.CODE_DIR, parts["path"])
                stamp(project / path, "file/" + path)
    return found
