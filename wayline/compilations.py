"""Compilations: the paper typeset under a venue (Implementation Decision 17; ticket 118).

A **compilation** is code alone through pandoc, from the venue-free paper of `research/paper/`:

- LaTeX with the venue's class where one is vendored (`guidelines/<venue>/<document_class>.cls`, or a `.sty` a
  conference loads on a plain article), and a plain `article` otherwise; none is vendored in this harness today, since
  `guidelines/` links templates and stores none;
- the PDF, through `latexmk` with xelatex for Unicode;
- a `.docx`, whose equations are Word's own;
- a Markdown copy.

Citations go through citeproc with the venue's CSL style, vendored under `guidelines/<venue>/` from the Citation Style
Language styles and named in `reference_style.csl` (pandoc's own default where a venue names none); a BibTeX venue
(`reference_style.bibtex`) gets `references.bib` from the CSL items and LaTeX citing through natbib. pandoc-crossref
resolves `{#eq:label}`, figure, and table references. A Lua filter (`templates/compile/tags.lua`) turns `ref` tags into
citations and strips every other tag (`res`, `code`, `doc`, `plot`), so no tag's text reaches any output; code checks
every output for one after (`tag_text`).

**Citations.** A `ref` tag naming a found work cites it, by its slug. One still unresolved is never cited: as the order's
batch answered (`paper.json`'s answers), it is dropped, or its claim is kept marked "to be resolved". At a venue capping
references (`max_count`), code drops citations over the cap first from Introduction sentences citing several works, a
work at a time from the last cited, and never a work the Results or the Methods cite: a reference a result or a method
rests on.

**The venue's checks** (`guidelines.run_checks`) run on the compiled LaTeX and the page count `pdfinfo` reads off the
compiled PDF, so page and template checks are real. When the paper exceeds a limit (the length check fails, or the
references are still over the cap), one fresh fitting writer session (`paper_fitting`, read-only, about $3) cuts text or
moves it to the supplement without adding a claim, and the paper is compiled again from what it returned. A Type-A check
(`fitting_problems`) refuses a fitted paper missing a claim tag, carrying a tag the paper did not, or with a number the
paper did not have; a refused fitting leaves the unfitted compilation, said. The fitted parts belong to the compilation
alone, under its `fitted/`: the paper stays venue-free.

**Where it goes.** Every paper order writes `research/paper/compilations/plain/`, and a venue the order names
`compilations/<venue>/` (`after_order`); compiling for another venue later is a compilation alone (`compile_paper`),
confirmed by a card (`card`, `wayline paper compile <slug>`). Before compiling, the order asks the scout live once
more about every unresolved work the paper cites (`last_retry`), and rewrites the paper's `references.json` when one
resolved. Each compilation writes `compilation.json` (schema `compilation`).

Every tool is called through the tool runner (`tools.run_recorded`), by its absolute executable in `tools.json`; the
suite replays recordings of real runs (`recorded_runner`, made by `fixtures/compilations/record.py`).
"""

import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

from wayline import HARNESS_ROOT, guidelines as venues, paper, provenance, worker
from wayline.cli import parse_args
from wayline.jsonschema import ValidationError, check, load_schema
from wayline.ledger import LedgerError, ledger_for, now_ts
from wayline.project import ProjectError, find_project, policy_for
from wayline.scout import Reference
from wayline.tools import Tools, ToolOutput, ToolsError, failure_line, run_recorded, run_tool

__all__ = [
    "CompilationError", "COMPILATIONS", "PLAIN", "RECORD_JSON", "SCHEMA", "FITTING_SCHEMA", "FILTER", "MARK", "FITTING_COST",
    "compile_paper", "after_order", "last_retry", "card", "card_text", "read_compilation", "fitting_problems", "tag_text",
    "plan_citations", "recording_runner", "recorded_runner", "compile_command", "read_compilations", "made_before",
]

COMPILATIONS = "compilations"            # research/paper/compilations/<name>/
PLAIN = "plain"
FITTED = "fitted"                        # compilations/<venue>/fitted/<part>.md, the fitting session's parts
LATEX = "latex"
RECORD_JSON = "compilation.json"
SCHEMA = "compilation"
FITTING_SCHEMA = "paper_fitting"
FILTER = HARNESS_ROOT / "templates" / "compile" / "tags.lua"
MARKDOWN_TEMPLATE = HARNESS_ROOT / "templates" / "compile" / "markdown.template"
MARK = "[to be resolved]"
FITTING_COST = "about $3"
FITTING_BUDGET = "medium"
SESSIONS = "compilations"                # research/sessions/compilations/<n>
ROLE = "writer"
TEXT_FROM = "markdown"
MARKDOWN_TO = "markdown-raw_html-bracketed_spans-fenced_divs-native_divs-native_spans-link_attributes-header_attributes"
LATEXMK_TIMEOUT_S = 900
BUILD_PREFIX = "compile-"                # the scratch build directory of a compilation, `compile-<name>`, as recordings key it

SECTIONS = (("introduction", "Introduction"), ("results", "Results"), ("discussion", "Discussion"), ("methods", "Methods"))
FITTED_PARTS = ("abstract", "introduction", "results", "discussion", "methods", "supplement")
SUPPLEMENT = "Supplementary information"
FRONT_SECTIONS = ("Acknowledgments", "Funding", "Competing interests", "Data availability", "Code availability")
# Not main text at any venue: the supplement and the front matter's statements are left out of a word count.
NOT_MAIN_TEXT = (SUPPLEMENT,) + FRONT_SECTIONS
IMAGE_SUFFIXES = (".pdf", ".png", ".jpg", ".jpeg", ".svg")
OUTPUTS = ("latex", "pdf", "docx", "markdown")

_CLAIM_TAG = provenance.ANY_TAG_RE
_PLOT_TAG = provenance.PLOT_TAG_RE
_ANY = re.compile(r"\{(res|ref|code|doc|plot):([^{}]*)\}")
_NUMBER = re.compile(r"(?<![A-Za-z#])\d+(?:[.,]\d+)*")
_HEADING_ID = re.compile(r"\{#[^{}]*\}")
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\[])")
_TABLE_CAPTION = re.compile(r"^\*\*Table [^*]*\*\*\s*(.*)$")
_PAGES = re.compile(rb"^Pages:\s+(\d+)", re.M)
MAIN_END = "wayline-main-end"           # the label the main text ends on, read back from the LaTeX run's .aux
_MAIN_END_PAGE = re.compile(r"\\newlabel\{%s\}\{\{[^{}]*\}\{(\d+)\}" % MAIN_END)

FITTING_PROMPT = """\
# Fitting the paper to %(venue)s

The paper below was compiled for %(venue)s and exceeds its limits. You are one fresh writer session that fits it: cut
text, or move it to the supplement, until it fits. You read the paper's parts under research/paper/ and write nothing;
return each part you change as its own field through the structured output, and null for every part you leave as it is.

## What exceeds a limit

%(limits)s

## Rules

- Add no claim, no sentence of your own that says something new, no number, and no tag.
- Change no number. Every number you keep is written exactly as the paper writes it.
- Every claim tag stays in the paper, copied exactly: `{res:...}`, `{ref:...}`, `{code:...}`, `{doc:...}`. A sentence
  you move takes its tags with it; a sentence you cut must not carry the last copy of a tag.
- Keep every heading and its id (`## Heading {#id}`); a heading's text moved to the supplement keeps its id there.
- Citations over the reference cap go first from Introduction sentences that cite several works; never drop a work a
  Results or Methods sentence cites, since a result or a method rests on it.%(citations)s
- List in `moved` each piece you moved to the supplement, one line each, and in `notes` anything the owner should read.

## The parts

%(parts)s
"""


class CompilationError(ValueError):
    """A compilation refused: no paper composed yet, a venue with no guidelines, or a CSL it names that is not vendored."""


# --- small readings -------------------------------------------------------------------------------------------------


def _one_line(text):
    return " ".join(str(text or "").split())


def _compilation_dir(name):
    return "%s/%s/%s" % (paper.PAPER_DIR, COMPILATIONS, name)


def read_compilation(project_or_ledger, name):
    """`research/paper/compilations/<name>/compilation.json`, or None before that compilation was made."""
    book = ledger_for(project_or_ledger)
    try:
        return book.read_json("%s/%s" % (_compilation_dir(name), RECORD_JSON))
    except FileNotFoundError:
        return None


def read_compilations(project_or_ledger):
    """Every compilation's record under `research/paper/compilations/`, `plain` first and then the venues by name; one whose
    record is missing or unreadable is left out."""
    book = ledger_for(project_or_ledger)
    root = book.path("%s/%s" % (paper.PAPER_DIR, COMPILATIONS))
    try:
        names = sorted(path.name for path in root.iterdir() if path.is_dir() and not path.name.startswith("."))
    except OSError:
        return []
    found = []
    for name in sorted(names, key=lambda name: (name != PLAIN, name)):
        try:
            record = read_compilation(book, name)
        except (OSError, ValueError):
            continue
        if isinstance(record, dict) and record.get("name") == name:
            found.append(record)
    return found


def made_before(record, compiled):
    """The parts a choice of an alternative changed since `compiled`, one compilation's record, was made: each part chosen
    while the compilation still carried the `compiled` stamp the choice recorded for it (ticket 121). `record` is the
    paper's version record; the next order writes one without choices, so the mark lasts until then or a new compilation."""
    parts = []
    for choice in (record or {}).get("chosen") or []:
        if (choice.get("before") or {}).get(compiled.get("name")) == compiled.get("compiled") and choice["part"] not in parts:
            parts.append(choice["part"])
    return parts


def _venue(harness_root, venue):
    try:
        return venues.read_guidelines(harness_root, venue)
    except (venues.GuidelinesError, ValidationError) as failure:
        raise CompilationError("no venue %s: %s" % (venue, failure)) from None


def _vendored_class(harness_root, venue, found):
    """`(path, kind)` of the venue's class vendored beside its guidelines (`cls`, or a `sty` a plain article loads), or None."""
    wanted = (found or {}).get("template", {}).get("document_class")
    if not venue or not wanted:
        return None
    for suffix, kind in ((".cls", "class"), (".sty", "package")):
        path = Path(harness_root) / venues.GUIDELINES_DIR / venue / (wanted + suffix)
        if path.is_file():
            return path, kind
    return None


def _csl(harness_root, venue, found):
    """The venue's CSL style, vendored under `guidelines/<venue>/`; None where it names none (pandoc's default style)."""
    name = ((found or {}).get("reference_style") or {}).get("csl")
    if not name:
        return None
    path = Path(harness_root) / venues.GUIDELINES_DIR / venue / name
    if not path.is_file():
        raise CompilationError("%s names the CSL style %s, which is not vendored at %s" % (venue, name, path))
    return path


def _parts(book):
    """Each part of the paper's current version as it stands on disk, an owner's edit included."""
    return {part: paper._file_text(book, part) or "" for part in paper.PARTS}


def _answers(record):
    """`{name: mark}` of the order's answers about unresolved references."""
    return {answer["ref"].split(":", 1)[1]: answer["mark"] for answer in (record or {}).get("answers") or []
            if answer["ref"].startswith("reference:")}


# --- the citations --------------------------------------------------------------------------------------------------


def _ref_body(body):
    return " ".join(str(body).split())


def plan_citations(project_or_ledger, texts, answers, max_count=None):
    """What each `ref` tag of `texts` comes to, by code: `{decisions, items, cited, to_be_resolved, dropped}`.

    `decisions` maps a tag's body to `("cite", slug)`, `("mark", name)` for an unresolved work whose claim is kept marked
    "to be resolved", or `("drop", name)` for one the order dropped (or a malformed tag); `items` are the CSL items of the
    works cited, in first-citation order. Over `max_count`, works cited only in Introduction sentences that cite several
    works lose those citations, the last cited first, until the count fits; a work the Results or the Methods cite is never
    one of them. `dropped` says which, and why.
    """
    from wayline import references
    book = ledger_for(project_or_ledger)
    index = references.identifier_index(book.project)
    decisions, works, order = {}, {}, []
    for part in paper.PARTS:
        for kind, body in _CLAIM_TAG.findall(texts.get(part) or ""):
            if kind != "ref":
                continue
            key = _ref_body(body)
            if key in decisions:
                continue
            parts = provenance.parse_tag("ref:%s" % key)[1]
            work = references.work_named(book, parts, index) if parts is not None else None
            if work is None:
                decisions[key] = ("drop", key)
            elif work.found and paper.DROP in (answers.get(work.slug), answers.get(work.named)):
                decisions[key] = ("drop", work.slug)  # the owner dropped it while unresolved; the last retry finding it changes nothing
            elif work.found:
                decisions[key] = ("cite", work.slug)
                if work.slug not in works:
                    works[work.slug] = references.csl_item(work.record)
                    order.append(work.slug)
            else:
                name = work.slug or work.named
                decisions[key] = ("drop" if answers.get(name) == paper.DROP or answers.get(work.named) == paper.DROP else "mark", name)
    dropped = []
    if max_count is not None and len(order) > max_count:
        dropped = _over_the_cap(texts, decisions, order, max_count)
        for slug, _ in dropped:
            order.remove(slug)
    return {"decisions": decisions, "items": [works[slug] for slug in order], "cited": list(order),
            "to_be_resolved": sorted({name for kind, name in decisions.values() if kind == "mark"}),
            "dropped": [{"work": slug, "why": why} for slug, why in dropped]}


def _citing(text, decisions):
    """`[(sentence, [slug])]` of `text`: the found works each sentence cites."""
    found = []
    for sentence in _SENTENCE.split(provenance.PLOT_TAG_RE.sub("", text or "")):
        slugs = []
        for kind, body in _CLAIM_TAG.findall(sentence):
            decision = decisions.get(_ref_body(body)) if kind == "ref" else None
            if decision and decision[0] == "cite" and decision[1] not in slugs:
                slugs.append(decision[1])
        found.append((sentence, slugs))
    return found


def _over_the_cap(texts, decisions, order, max_count):
    """The works dropped to bring `order` within `max_count`: `[(slug, why)]`; changes `decisions` to drop them."""
    rests = {slug for part in ("results", "methods") for _, slugs in _citing(texts.get(part), decisions) for slug in slugs}
    multi, elsewhere = set(), set(rests)
    for part in paper.PARTS:
        for _, slugs in _citing(texts.get(part), decisions):
            if part == "introduction" and len(slugs) > 1:
                multi.update(slugs)
            else:
                elsewhere.update(slugs)
    candidates = [slug for slug in reversed(order) if slug in multi and slug not in elsewhere]
    dropped = []
    for slug in candidates[:max(0, len(order) - max_count)]:
        dropped.append((slug, "over the venue's %d references, cited only in Introduction sentences citing several works" % max_count))
        for key, decision in list(decisions.items()):
            if decision == ("cite", slug):
                decisions[key] = ("drop", slug)
    return dropped


def _marked(text, decisions):
    """`text` with every tag a span the Lua filter reads: a citation, the "to be resolved" marker, or nothing."""
    def span(match):
        kind, body = match.group(1), match.group(2)
        if kind == "ref":
            decision = decisions.get(_ref_body(body), ("drop", None))
            if decision[0] == "cite":
                return '[]{.wayline-tag kind="ref" cite="%s"}' % decision[1]
            if decision[0] == "mark":
                return '[]{.wayline-tag kind="ref" unresolved="mark"}'
        return '[]{.wayline-tag kind="%s"}' % kind
    return _ANY.sub(span, text or "")


def tag_text(text):
    """The tags still written in `text` (an output, as text): what no compilation may leave."""
    return ["{%s:%s}" % found for found in _ANY.findall(str(text or ""))]


# --- the source pandoc reads ----------------------------------------------------------------------------------------


def _section_names(found):
    """The four sections' headings, as the venue names them where its required structure names one."""
    names = dict(SECTIONS)
    required = (found or {}).get("required_structure") or []
    for part, default in SECTIONS:
        match = next((name for name in required if venues.heading_matches(default, name)), None)
        if match:
            names[part] = match
    return names


def _section_order(found):
    """The four sections in the plain order, those the venue's required structure names taking its order among their
    own places (PLOS's Methods before its Results); a section it does not name keeps its place."""
    required = (found or {}).get("required_structure") or []
    default = [part for part, _ in SECTIONS]
    at = {}
    for part, heading in SECTIONS:
        index = next((index for index, name in enumerate(required) if venues.heading_matches(heading, name)), None)
        if index is not None:
            at[part] = index
    named = iter(sorted(at, key=lambda part: at[part]))
    return [next(named) if part in at else part for part in default]


def _front_sections(text):
    """`[(title, body)]` of `front.md`'s sections but the authors, which go in the metadata."""
    found, title, lines = [], None, []
    for line in (text or "").splitlines():
        heading = re.match(r"^##\s+(.*?)\s*$", line)
        if heading:
            if title is not None:
                found.append((title, "\n".join(lines).strip()))
            title, lines = heading.group(1), []
        elif title is not None:
            lines.append(line)
    if title is not None:
        found.append((title, "\n".join(lines).strip()))
    return [(title, body) for title, body in found if title.casefold() != "authors" and body]


def _table(book, identifier):
    """`(pipe table, caption)` of a table as the paper renders it (`tables/T<n>.md`, `paper._table_markdown`), or None."""
    try:
        described = book.path(paper._paper("%s/%s.md" % (paper.TABLES, identifier))).read_text(encoding="utf-8")
    except OSError:
        return None
    lines = described.splitlines()
    caption = next((match.group(1) for match in map(_TABLE_CAPTION.match, lines) if match), "")
    rows = [line for line in lines if line.strip().startswith("|")]
    return ("\n".join(rows), caption) if rows else None


def _table_block(table, identifier, decisions):
    """A table labeled for pandoc-crossref, its caption's tags marked like the text's."""
    rows, caption = table
    return "%s\n\n: %s {#tbl:%s}\n" % (rows, _one_line(_marked(caption, decisions)), identifier)


def _figure_block(identifier, image, caption, decisions):
    return "![%s](figures/%s%s){#fig:%s}" % (_marked(caption, decisions), identifier, image.suffix.lower(), identifier)


def _supplement_text(text):
    """The supplement as written, less the placeholder code writes for an empty one (a fitting may write after it)."""
    text = (text or "").strip()
    if text.startswith(_EMPTY_SUPPLEMENT):
        text = text[len(_EMPTY_SUPPLEMENT):].lstrip(".").strip()
    return text


def _figures(book):
    """`[(id, image path, caption)]` of `research/paper/figures/<id>/`, main-text figures (F) first, then supplementary (S)."""
    root = book.path(paper._paper("figures"))
    found = []
    if not root.is_dir():
        return found
    for folder in sorted(root.iterdir(), key=lambda path: (path.name[:1] != "F", len(path.name), path.name)):
        if not folder.is_dir() or not re.match(r"^[FS][1-9][0-9]*$", folder.name):
            continue
        images = sorted(path for path in folder.iterdir() if path.suffix.lower() in IMAGE_SUFFIXES)
        if not images:
            continue
        image = next((path for suffix in IMAGE_SUFFIXES for path in images if path.suffix.lower() == suffix), images[0])
        try:
            caption = (folder / "caption.md").read_text(encoding="utf-8")
        except OSError:
            caption = ""
        found.append((folder.name, image, _one_line(caption)))
    return found


_EMPTY_SUPPLEMENT = "Nothing is placed in the supplement"


def _source(book, texts, decisions, found, tables, figures, natbib=False):
    """The Markdown document pandoc reads: the sections in the venue's order, the figures and tables, the front matter's
    statements, the references, then the supplement; every tag a span (`_marked`). Under natbib the bibliography makes
    its own heading at the end, so the References heading is left out."""
    names, blocks = _section_names(found), []
    for part in _section_order(found):
        body = _marked(texts.get(part), decisions).strip()
        blocks.append("# %s\n\n%s" % (names[part], body))
        if part == "results":
            blocks += [_table_block(table, identifier, decisions) for identifier, table in tables if table]
            blocks += [_figure_block(identifier, image, caption, decisions) for identifier, image, caption in figures
                       if identifier.startswith("F")]
    blocks.append("```{=latex}\n\\label{%s}\n```" % MAIN_END)  # where the main text ends: its page is the page count
    blocks += ["# %s\n\n%s" % (title, _marked(body, decisions)) for title, body in _front_sections(texts.get("front"))]
    if not natbib:
        blocks.append("# References\n\n::: {#refs}\n:::")
    supplement = _marked(_supplement_text(texts.get("supplement")), decisions).strip()
    shown = [supplement] if supplement else []
    shown += [_figure_block(identifier, image, caption, decisions) for identifier, image, caption in figures
              if identifier.startswith("S")]
    if shown:
        blocks.append("# %s\n\n%s" % (SUPPLEMENT, "\n\n".join(shown)))
    return "\n\n".join(blocks) + "\n"


def _authors(project):
    try:
        record = paper.read_front(project)
    except paper.PaperError:
        record = {}
    authors = []
    for author in record.get("authors") or []:
        places = ", ".join(author.get("affiliations") or [])
        authors.append("%s%s" % (author["name"], " (%s)" % places if places else ""))
    return authors or [paper.PLACEHOLDER % "the authors and their affiliations"]


def _metadata(project, texts, decisions, document_class, package):
    meta = {
        "title": _one_line(texts.get("title")) or paper.PLACEHOLDER % "the title",
        "author": _authors(project),
        "abstract": _marked(texts.get("abstract"), decisions).strip(),
        "documentclass": document_class,
        "eqnPrefix": "Eq.", "figPrefix": "Fig.", "tblPrefix": "Table", "secPrefix": "Section",
        "link-citations": True,
    }
    if package:
        meta["header-includes"] = "\\usepackage{%s}" % package
    return meta


# --- the tools ------------------------------------------------------------------------------------------------------


class _Tools:
    """The compilation's calls, each through the tool runner by its recorded executable; what failed is kept."""

    def __init__(self, tools, run, beat=None):
        self.tools, self.run = tools if tools is not None else Tools(), run
        self.beat = beat or (lambda: None)  # the conductor's heartbeat between calls, so a long build is no stall
        self.versions = {}

    def executable(self, name):
        entry = self.tools.entry(name) or {}
        if not entry.get("executable"):
            raise ToolsError("%s is not recorded in %s (wayline tools install %s)" % (name, self.tools.root / "tools.json", name))
        self.versions[name] = entry.get("version")
        return entry["executable"]

    def call(self, name, args, timeout=600):
        self.executable(name)
        self.beat()
        done = run_recorded(name, [str(part) for part in args], tools=self.tools, run=self.run, timeout=timeout)
        if done.returncode != 0:
            raise ToolsError("%s failed (%s)" % (name, failure_line(done)))
        return done


def _pandoc_common(tools, source, build, meta):
    return [source, "--from", TEXT_FROM, "--lua-filter", FILTER, "--filter", tools.executable("pandoc-crossref"),
            "--metadata-file", meta, "--resource-path", build]


def _citing_args(bibtex, refs, bib, csl, latex):
    if bibtex and latex:
        return ["--natbib", "--bibliography", bib.name]  # natbib reads no file: `\bibliography{references}` beside the LaTeX
    return ["--citeproc", "--bibliography", refs] + (["--csl", csl] if csl else [])


def _build(book, scratch, name, texts, plan, found, harness_root, tools):
    """Run the four outputs (and the `.bib` of a BibTeX venue) in `scratch/compile-<name>/`; returns what was made."""
    build = Path(scratch) / (BUILD_PREFIX + name)
    latex = build / LATEX
    (latex / "figures").mkdir(parents=True)
    (build / "figures").mkdir()
    venue = found.get("venue") if found else None
    vendored = _vendored_class(harness_root, venue, found)
    document_class, package = "article", None
    if vendored is not None:
        shutil.copyfile(vendored[0], latex / vendored[0].name)
        if vendored[1] == "class":
            document_class = vendored[0].stem
        else:
            package = vendored[0].stem
    csl = _csl(harness_root, venue, found) if venue else None
    bibtex = bool(((found or {}).get("reference_style") or {}).get("bibtex"))
    tables = [(identifier, _table(book, identifier)) for identifier in (paper.read_record(book) or {}).get("tables") or []]
    figures = _figures(book)
    for identifier, image, _ in figures:
        for where in (build / "figures", latex / "figures"):
            shutil.copyfile(image, where / (identifier + image.suffix.lower()))
    source, meta, refs, bib = build / "paper.md", build / "metadata.yaml", build / "references.json", latex / "references.bib"
    source.write_text(_source(book, texts, plan["decisions"], found, tables, figures), encoding="utf-8")
    latex_source = build / "paper.natbib.md" if bibtex else source
    if bibtex:
        latex_source.write_text(_source(book, texts, plan["decisions"], found, tables, figures, natbib=True), encoding="utf-8")
    meta.write_text(json.dumps(_metadata(book.project, texts, plan["decisions"], document_class, package), indent=2,
                               ensure_ascii=False) + "\n", encoding="utf-8")
    refs.write_text(json.dumps(plan["items"], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    made = {"build": build, "document_class": document_class, "class_vendored": vendored is not None, "csl": csl.name if csl else None,
            "bibtex": bibtex, "outputs": {}, "pages": None, "main_pages": None}

    def attempt(output, action):
        try:
            action()
            made["outputs"][output] = {"problem": None}
        except ToolsError as failure:
            made["outputs"][output] = {"problem": str(failure)}

    if bibtex:
        attempt("bibtex", lambda: tools.call("pandoc", [refs, "--from", "csljson", "--to", "bibtex", "-o", bib]))
    attempt("latex", lambda: tools.call("pandoc", _pandoc_common(tools, latex_source, build, meta) + ["--to", "latex", "--standalone"]
                                        + _citing_args(bibtex, refs, bib, csl, True) + ["-o", latex / "paper.tex"]))
    if made["outputs"]["latex"]["problem"] is None:
        attempt("pdf", lambda: tools.call("latexmk", ["-cd", "-xelatex", "-interaction=nonstopmode", "-halt-on-error",
                                                      "-file-line-error", latex / "paper.tex"], timeout=LATEXMK_TIMEOUT_S))
        if made["outputs"]["pdf"]["problem"] is None and not (latex / "paper.pdf").is_file():
            made["outputs"]["pdf"] = {"problem": "latexmk wrote no paper.pdf"}
    else:
        made["outputs"]["pdf"] = {"problem": "no LaTeX to compile"}
    if made["outputs"]["pdf"]["problem"] is None:
        try:
            printed = tools.call("pdfinfo", [latex / "paper.pdf"]).stdout
            pages = _PAGES.search(printed or b"")
            made["pages"] = int(pages.group(1)) if pages else None
        except ToolsError as failure:
            made["pages_problem"] = str(failure)
        try:
            ended = _MAIN_END_PAGE.search((latex / "paper.aux").read_text(encoding="utf-8", errors="replace"))
        except OSError:
            ended = None
        made["main_pages"] = int(ended.group(1)) if ended else made["pages"]
    attempt("docx", lambda: tools.call("pandoc", _pandoc_common(tools, source, build, meta) + ["--to", "docx"]
                                       + _citing_args(bibtex, refs, bib, csl, False) + ["-o", build / "paper.docx"]))
    attempt("markdown", lambda: tools.call("pandoc", _pandoc_common(tools, source, build, meta)
                                           + ["--to", MARKDOWN_TO, "--wrap=none", "--standalone", "--template", MARKDOWN_TEMPLATE]
                                           + _citing_args(bibtex, refs, bib, csl, False) + ["-o", build / "paper.copy.md"]))
    return made


def _output_texts(made):
    """Each output's text, for the check that no tag survived: the LaTeX, the Markdown copy, and the `.docx`'s XML."""
    import zipfile
    build = made["build"]
    found = {}
    for output, path in (("latex", build / LATEX / "paper.tex"), ("markdown", build / "paper.copy.md")):
        if path.is_file():
            found[output] = path.read_text(encoding="utf-8", errors="replace")
    if (build / "paper.docx").is_file():
        try:
            with zipfile.ZipFile(build / "paper.docx") as archive:
                xml = archive.read("word/document.xml").decode("utf-8", errors="replace")
            found["docx"] = re.sub(r"<[^>]+>", "", xml)
        except (OSError, KeyError, zipfile.BadZipFile):
            found["docx"] = ""
    return found


# --- the venue's checks and the fitting -----------------------------------------------------------------------------


_SUPPLEMENT_LATEX = re.compile(r"\\section\*?\{%s\}.*?(?=\\bibliography\{|\\end\{document\})" % re.escape(SUPPLEMENT), re.S)


def _checks(made, found):
    """The venue's seven checks on the compiled LaTeX, the page count read off the compiled PDF.

    They read the main text: the supplement (its subsections with it) and the front matter's statements count toward no
    word limit, so the checks run on a copy of the LaTeX directory whose source stops before the supplement."""
    if not found or made["outputs"]["latex"]["problem"] is not None:
        return []
    main = made["build"] / "checked"
    shutil.copytree(made["build"] / LATEX, main, dirs_exist_ok=True)
    tex = main / "paper.tex"
    tex.write_text(_SUPPLEMENT_LATEX.sub("", tex.read_text(encoding="utf-8")), encoding="utf-8")
    for path in main.glob("*.pdf"):
        path.unlink()  # the page count is pdfinfo's, read off the compiled PDF
    manuscript = venues.Manuscript(main)
    manuscript.pdf_pages = lambda: made["main_pages"]  # a venue's page limit is the main text's, not its references or supplement's
    counted = json.loads(json.dumps(found))
    counted["length_limits"]["excluded_sections"] = list(counted["length_limits"]["excluded_sections"]) + list(NOT_MAIN_TEXT)
    return [finding._asdict() for finding in venues.run_checks(manuscript, counted)]


def _over(checks, plan, found):
    """The limits the compiled paper exceeds, one line each: a failed length check, and references still over the cap."""
    lines = [check["message"] for check in checks if check["check"] == "length" and check["level"] == "fail"]
    cap = ((found or {}).get("reference_style") or {}).get("max_count")
    if cap is not None and len(plan["cited"]) > cap:
        lines.append("the paper cites %d works, over the %d %s allows, after code dropped what it could" % (
            len(plan["cited"]), cap, found["display_name"]))
    return lines


def _numbers(text):
    return set(_NUMBER.findall(_HEADING_ID.sub(" ", _ANY.sub(" ", text or ""))))


def fitting_problems(before, after):
    """The Type-A check of a fitted paper against the paper it fits: problems, one line each, empty when it passes.

    `before` and `after` map parts to their text. Every claim tag of the paper is still in it, no tag is one the paper
    did not carry, and no number is one the paper did not have (a number cut is no change; a number written otherwise is).
    """
    def tags(texts):
        return {"{%s:%s}" % (kind, _ref_body(body)) for text in texts.values() for kind, body in _CLAIM_TAG.findall(text or "")}
    problems = []
    was, now = tags(before), tags(after)
    problems += ["the claim tag %s is no longer in the paper" % tag for tag in sorted(was - now)]
    problems += ["the tag %s is new: a fitted paper adds no claim" % tag for tag in sorted(now - was)]
    numbers = set().union(*[_numbers(text) for text in before.values()]) if before else set()
    for part in FITTED_PARTS:
        for number in sorted(_numbers(after.get(part)) - numbers):
            problems.append("%s: the number %s is not one the paper has; a fitted paper changes no number" % (part, number))
    return problems


def _fit(project, book, venue, found, texts, limits, plan, harness_root, policy):
    """The one fitting session: `(fitted texts or None, record)`."""
    record = {"limits": limits, "outcome": None, "problems": [], "moved": [], "model": None, "session_id": None, "usage": None}
    try:
        role = worker.read_role(ROLE, harness_root, project)
    except (worker.RoleError, ValueError, OSError) as failure:
        record.update(outcome="not run", problems=["the writer role could not be read: %s" % _one_line(failure)])
        return None, record
    citations = ("\n- Over the cap now: %d works cited, %d allowed; code already dropped %s." % (
        len(plan["cited"]), found["reference_style"]["max_count"], ", ".join(item["work"] for item in plan["dropped"]) or "none")
        if found["reference_style"].get("max_count") is not None and len(plan["cited"]) > found["reference_style"]["max_count"] else "")
    shown = "\n\n".join("### %s (research/paper/%s.md)\n\n%s" % (part, part, (texts.get(part) or "").strip()) for part in FITTED_PARTS)
    prompt = FITTING_PROMPT % {"venue": "%s (%s)" % (found["display_name"], venue), "limits": "\n".join("- %s" % line for line in limits),
                               "citations": citations, "parts": shown}
    try:
        prompt = provenance.joined(prompt, role.protocol, worker.schema_section("# The answer", FITTING_SCHEMA))
        request = provenance.structured_request(project, role, policy, harness_root, prompt, FITTING_SCHEMA, FITTING_BUDGET,
                                                provenance.session_dir(project, SESSIONS), read_only=True)
    except (provenance.ProvenanceError, worker.RoleError, ValueError, OSError) as failure:
        record.update(outcome="not run", problems=["the session could not be set up: %s" % _one_line(failure)])
        return None, record
    record["model"] = request.model

    def fitted_of(answer):
        return dict(texts, **{part: answer[part] for part in FITTED_PARTS if answer.get(part) is not None})

    def problem_of(envelope):
        problem = provenance.schema_problem(envelope, FITTING_SCHEMA)
        if problem is not None:
            return problem
        found_problems = fitting_problems(texts, fitted_of(envelope.structured_output))
        return "\n".join("- %s" % line for line in found_problems) if found_problems else None

    try:
        envelope = provenance._launch_structured(request, problem_of, "compilation's fitting writer")
    except provenance.UsageLimited as limited:
        record.update(outcome="not run", problems=["a usage limit held the session: %s" % _one_line(limited)])
        return None, record
    except (provenance.ProvenanceError, worker.LaunchError, worker.RoleError) as failure:
        record.update(outcome="refused", problems=[line.lstrip("- ") for line in str(failure).splitlines() if line.strip()][:20])
        return None, record
    answer = envelope.structured_output
    record.update(outcome="fitted", moved=[_one_line(item) for item in answer.get("moved") or []], model=envelope.model or request.model,
                  session_id=envelope.session_id, usage=envelope.usage)
    return fitted_of(answer), record


# --- one compilation ------------------------------------------------------------------------------------------------


def _clear(book, name):
    directory = book.path(_compilation_dir(name))
    if directory.is_dir():
        book.remove_tree(_compilation_dir(name))


def _keep(book, name, made, fitted_texts):
    """Write a compilation's files under `research/paper/compilations/<name>/` from its scratch build."""
    build, base = made["build"], _compilation_dir(name)
    kept = {}
    copies = {"pdf": (build / LATEX / "paper.pdf", "paper.pdf"), "docx": (build / "paper.docx", "paper.docx"),
              "markdown": (build / "paper.copy.md", "paper.md")}
    for output, (path, target) in copies.items():
        if made["outputs"].get(output, {}).get("problem") is None and path.is_file():
            book.write_bytes("%s/%s" % (base, target), path.read_bytes())
            kept[output] = target
    if made["outputs"]["latex"]["problem"] is None:
        for path in sorted((build / LATEX).rglob("*")):
            relative = path.relative_to(build / LATEX)
            if path.is_file() and (path.suffix in (".tex", ".bib", ".cls", ".sty", ".log") or relative.parts[0] == "figures"):
                book.write_bytes("%s/%s/%s" % (base, LATEX, relative.as_posix()), path.read_bytes())
        kept["latex"] = "%s/paper.tex" % LATEX
    if made["bibtex"] and made["outputs"].get("bibtex", {}).get("problem") is None and (build / LATEX / "references.bib").is_file():
        book.write_bytes("%s/references.bib" % base, (build / LATEX / "references.bib").read_bytes())
        kept["bibtex"] = "references.bib"
    for part, text in (fitted_texts or {}).items():
        if part in FITTED_PARTS:
            book.write_markdown("%s/%s/%s.md" % (base, FITTED, part), (text or "").strip() + "\n")
    return kept


def compile_paper(project, venue=None, *, harness_root=HARNESS_ROOT, guidelines_root=None, tools=None, run=run_tool, policy=None, say=None,
                  retried=None, beat=None):
    """Compile the paper's current version, for `venue` or plain; writes `compilations/<name>/` and returns its record.

    Raises CompilationError when no paper is composed yet or the venue has no guidelines. A tool that fails leaves its
    output out and says why in the record (`outputs`); the compilation itself never fails the order. A fitted paper that
    compiles to less than the unfitted one made is set aside, said, and the unfitted compilation kept. `beat` is called
    before each tool and the fitting session (the conductor's heartbeat).
    """
    project = Path(project).resolve()
    book = ledger_for(project)
    record = paper.read_record(book)
    if record is None:
        raise CompilationError("no paper is composed yet: the paper order composes it, and every order compiles it plainly")
    shelves = harness_root if guidelines_root is None else guidelines_root
    found = _venue(shelves, venue) if venue else None
    name = venue or PLAIN
    texts = _parts(book)
    answers = _answers(record)
    cap = (found or {}).get("reference_style", {}).get("max_count") if found else None
    plan = plan_citations(book, texts, answers, cap)
    runner = _Tools(tools, run, beat)
    fitting, fitted_texts = None, None
    with tempfile.TemporaryDirectory(prefix="wayline-compile-") as scratch:
        made = _build(book, scratch, name, texts, plan, found, shelves, runner)
        checks = _checks(made, found)
        limits = _over(checks, plan, found) if found else []
        if limits:
            policy = policy_for(project, harness_root) if policy is None else policy
            runner.beat()
            fitted_texts, fitting = _fit(project, book, venue, found, texts, limits, plan, harness_root, policy)
            if fitted_texts is not None:
                fitted_plan = plan_citations(book, fitted_texts, answers, cap)
                fitted = _build(book, scratch, name + "-" + FITTED, fitted_texts, fitted_plan, found, shelves, runner)
                lost = [output for output in OUTPUTS if fitted["outputs"].get(output, {}).get("problem") is not None
                        and made["outputs"].get(output, {}).get("problem") is None]
                if lost:
                    fitting.update(outcome="refused", problems=["the fitted paper's %s could not be made: %s" % (
                        output, fitted["outputs"][output]["problem"]) for output in lost])
                    fitted_texts = None
                else:
                    made, plan, checks = fitted, fitted_plan, _checks(fitted, found)
                    fitting["still_over"] = _over(checks, plan, found)
        leaked = sorted({tag for text in _output_texts(made).values() for tag in tag_text(text)})
        with book.lock():
            _clear(book, name)
            kept = _keep(book, name, made, fitted_texts)
            outputs = {output: {"file": kept.get(output), "problem": made["outputs"].get(output, {}).get("problem")} for output in OUTPUTS}
            if made["bibtex"]:
                outputs["bibtex"] = {"file": kept.get("bibtex"), "problem": made["outputs"].get("bibtex", {}).get("problem")}
            made_all = all(outputs[output]["file"] for output in OUTPUTS)
            compiled = {
                "name": name, "venue": venue, "paper_version": record["version"], "compiled": now_ts(),
                "outcome": "compiled" if made_all and not leaked else ("failed" if not any(item["file"] for item in outputs.values()) else "partial"),
                "outputs": outputs, "document_class": made["document_class"], "class_vendored": made["class_vendored"],
                "csl": made["csl"], "bibtex": made["bibtex"], "pages": made["pages"], "main_pages": made["main_pages"],
                "tools": {key: value for key, value in sorted(runner.versions.items())},
                "citations": {"cited": plan["cited"], "to_be_resolved": plan["to_be_resolved"], "dropped": plan["dropped"]},
                "retried": retried, "checks": checks, "fitting": fitting, "tag_text": leaked,
            }
            book.write_json("%s/%s" % (_compilation_dir(name), RECORD_JSON), compiled, schema=SCHEMA)
    if say is not None:
        say("  compilation %s of version %d: %s%s" % (name, record["version"], compiled["outcome"],
                                                       "; fitted" if fitting and fitting["outcome"] == "fitted" else ""))
    return compiled


# --- at the order ---------------------------------------------------------------------------------------------------


def last_retry(project, fetcher=None, clock=None):
    """The order's last retry: the scout asked live once more about every unresolved work the paper cites.

    Returns `{asked, found, still}`: the names asked, the slugs that resolved, and the names still unresolved. A work
    that resolved rewrites the paper's `references.json` and References. A URL, a file, and a slug no dossier holds are
    never looked up.
    """
    from wayline import dossier as dossiers
    from wayline import references
    book = ledger_for(project)
    index = references.identifier_index(book.project)
    texts = _parts(book)
    asked, found, still, seen = [], [], [], set()
    for part in paper.PARTS:
        for parts in references.ref_tags(texts.get(part)):
            work = references.work_named(book, parts, index) if parts is not None else None
            if work is None or work.found or work.key in seen:
                continue
            seen.add(work.key)
            query = (work.record or {}).get("query") or {}
            if work.record is not None and query.get("kind") in ("doi", "arxiv", "title") and query.get("value"):
                reference = Reference(query["kind"], query["value"], query.get("raw"))
            elif work.record is None and parts.get("identifier"):
                try:
                    reference = references.tagged_reference(parts["identifier"])
                except references.ReferenceError_:
                    continue
            else:
                continue
            name = work.slug or work.named
            asked.append(name)
            answer = dossiers.look_up_one(book.project, reference, fetcher=fetcher, ledger=book, clock=clock, finish=False, live=True)
            if answer["dossier"] is not None and answer["dossier"].get("existence") == "verified":
                found.append(answer["slug"])
            else:
                still.append(name)
    if found:
        dossiers.finish_lookups(book.project, book, clock)
        record = paper.read_record(book)
        texts = _parts(book)
        with book.lock():
            book.write_json(paper._paper(paper.REFERENCES_JSON), paper._references(book, texts, (record or {}).get("answers") or []))
        references.render_references(book)
    return {"asked": asked, "found": found, "still": still}


def after_order(project, order, *, harness_root=HARNESS_ROOT, guidelines_root=None, tools=None, run=run_tool, policy=None, fetcher=None,
                clock=None, say=None, beat=None):
    """What the order does once the paper is composed: the last retry, then `compilations/plain/`, and the order's venue's.

    Returns `{retried, compilations}`. A last retry that fails is said and the compilations are made all the same, with
    what the dossiers hold; a compilation that cannot be made is said and recorded; neither fails the order.
    """
    say = say or (lambda line: None)
    try:
        retried = last_retry(project, fetcher=fetcher, clock=clock)
    except (LedgerError, OSError, ValueError) as failure:
        retried = None
        say("  paper order %s: the scout's last retry failed (%s); the compilations cite what the dossiers hold" % (
            order.get("order"), _one_line(failure)))
    if retried and retried["asked"]:
        say("  paper order %s: the scout asked once more about %d unresolved work(s): %d found" % (
            order.get("order"), len(retried["asked"]), len(retried["found"])))
    made = []
    for venue in [None] + ([order["venue"]] if order.get("venue") else []):
        try:
            made.append(compile_paper(project, venue, harness_root=harness_root, guidelines_root=guidelines_root, tools=tools, run=run,
                                      policy=policy, say=say, retried=retried, beat=beat))
        except (CompilationError, LedgerError, OSError, ValueError) as failure:
            say("  compilation %s could not be made: %s" % (venue or PLAIN, failure))
    return {"retried": retried, "compilations": made}


# --- the card for another venue -------------------------------------------------------------------------------------


def card(project, venue, harness_root=HARNESS_ROOT):
    """What the owner confirms before a compilation alone, with no model call: the venue, its limits, and the cost."""
    book = ledger_for(project)
    found = _venue(harness_root, venue)
    record = paper.read_record(book)
    limits = found["length_limits"]
    lines = []
    for key, words in (("word_count", "words of main text"), ("page_count", "pages"), ("abstract_word_count", "words of abstract")):
        if limits.get(key) is not None:
            lines.append("at most %d %s" % (limits[key], words))
    if found["figure_spec"].get("max_count") is not None:
        lines.append("at most %d display items" % found["figure_spec"]["max_count"])
    if found["reference_style"].get("max_count") is not None:
        lines.append("at most %d references" % found["reference_style"]["max_count"])
    before = read_compilation(book, venue)
    return {"venue": venue, "display_name": found["display_name"], "version": record["version"] if record else None,
            "limits": lines, "csl": found["reference_style"].get("csl"), "bibtex": bool(found["reference_style"].get("bibtex")),
            "cost": "no model call, unless the paper exceeds a limit: then one fitting session, %s" % FITTING_COST,
            "writes": "research/%s/" % _compilation_dir(venue), "made_before": before["paper_version"] if before else None,
            "open": paper.open_order(book), "confirm": "wayline paper compile %s --yes" % venue}


def card_text(found):
    lines = ["Compile the paper for %s (%s): a compilation alone, typeset and checked under its guidelines; nothing is "
             "submitted." % (found["display_name"], found["venue"]), ""]
    if found["version"] is None:
        lines.append("No paper is composed yet: order it first (wayline paper).")
        return "\n".join(lines)
    lines.append("- The paper: version %d%s." % (found["version"], "" if found["made_before"] is None else
                                                  "; this venue was last compiled from version %d" % found["made_before"]))
    lines.append("- Its limits: %s." % ("; ".join(found["limits"]) or "none recorded"))
    lines.append("- Citations: %s%s." % ("the venue's CSL style %s" % found["csl"] if found["csl"] else "pandoc's default style",
                                         ", and a .bib for its BibTeX template" if found["bibtex"] else ""))
    lines.append("- Writes %s: the LaTeX, the PDF, a .docx, and a Markdown copy." % found["writes"])
    lines.append("- Cost: %s." % found["cost"])
    lines.append("")
    if found["open"]:
        lines.append("Paper order %d is open; compile once it is composed." % found["open"]["order"])
    else:
        lines.append("Confirm: %s. Not now: nothing is done." % found["confirm"])
    return "\n".join(lines)


def compile_command(args):
    """`wayline paper compile <slug> [--yes] [--json] [--project <path>]`: the card, or with `--yes` the compilation."""
    parser = argparse.ArgumentParser(prog="wayline paper compile", description="compile the paper's current version for another "
                                     "venue: without --yes its card, with --yes the compilation alone, under research/paper/compilations/<venue>/")
    parser.add_argument("venue", help="the venue's slug under guidelines/")
    parser.add_argument("--yes", action="store_true", help="the owner's confirmation; without it nothing is done")
    parser.add_argument("--project", help="the project; the active one by default")
    parser.add_argument("--json", action="store_true", help="print the card or the compilation's record as JSON")
    options, code = parse_args(parser, args)
    if options is None:
        return code
    try:
        project = find_project(options.project)
        found = card(project, options.venue)
        if not options.yes:
            print(json.dumps(found, indent=2, default=str) if options.json else card_text(found))
            return 0
        if found["open"]:
            raise CompilationError("paper order %d is open: compile once its paper is composed" % found["open"]["order"])
        made = compile_paper(project, options.venue)
    except (CompilationError, paper.PaperError) as failure:
        print("wayline paper compile: %s" % failure, file=sys.stderr)
        return 2
    except (ProjectError, LedgerError, OSError, ValueError) as failure:
        print("wayline paper compile: %s" % failure, file=sys.stderr)
        return 1
    if options.json:
        print(json.dumps(made, indent=2))
    else:
        print("compiled %s from version %d: %s, under research/%s/" % (made["name"], made["paper_version"], made["outcome"],
                                                                       _compilation_dir(made["name"])))
        for output, item in made["outputs"].items():
            print("  %-9s %s" % (output, item["file"] or "not made: %s" % item["problem"]))
        failing = [check for check in made["checks"] if check["level"] == "fail"]
        for check in failing:
            print("  check    FAIL %s: %s" % (check["check"], check["message"]))
    return 0 if made["outcome"] != "failed" else 1


# --- the recordings -------------------------------------------------------------------------------------------------


def _call_key(argv):
    """`(compilation, tool, output name, build directory, input)` of one tool call a compilation makes."""
    argv = [str(part) for part in argv]
    tool = Path(argv[0]).name
    output = Path(argv[argv.index("-o") + 1]) if "-o" in argv else Path(argv[-1])
    build = next((parent for parent in [output] + list(output.parents) if parent.name.startswith(BUILD_PREFIX)), None)
    name = build.name[len(BUILD_PREFIX):] if build is not None else "unknown"
    source = Path(argv[1]) if tool == "pandoc" else None
    target = output.name if tool != "pdfinfo" else "pdfinfo-" + output.name
    return name, tool, target, build, source


def _digest(path, build):
    """What a pandoc call read: its input, and the build's metadata and CSL items beside it, the build's path kept as `{build}`."""
    digest = hashlib.sha256()
    for each in [Path(path)] + ([build / "metadata.yaml", build / "references.json"] if build is not None else []):
        try:
            data = each.read_bytes()
        except OSError:
            data = b""
        digest.update(data.replace(str(build).encode(), b"{build}") if build is not None else data)
    return digest.hexdigest()


_TEXT_FILES = (".tex", ".md", ".bib", ".log", ".yaml", ".json", ".fls", ".fdb_latexmk", ".aux")


def recording_runner(target, run=run_tool):
    """A `run` that runs each tool for real and keeps what it printed and wrote under `target/<name>/<tool>/<output>/`.

    `files/` holds what the call wrote: the output file, and for `latexmk` every file of the LaTeX directory. The build
    directory's path is kept as `{build}`, and `input.sha256` is what pandoc read, so a replay knows when it is stale.
    """
    target = Path(target)

    def recording(argv, cwd=None, timeout=None, env=None):
        name, tool, output, build, source = _call_key(argv)
        where = target / name / tool / output
        shutil.rmtree(where, ignore_errors=True)
        where.mkdir(parents=True)
        if source is not None:
            (where / "input.sha256").write_text(_digest(source, build) + "\n", encoding="utf-8")
        done = run(argv, timeout=timeout, env=env)
        home = str(Path.home()).encode()
        clean = lambda data: data.replace(str(build).encode(), b"{build}").replace(home, b"~") if build else data
        (where / "stdout").write_bytes(clean(done.stdout or b""))
        (where / "stderr").write_bytes(clean(done.stderr or b""))
        (where / "returncode").write_text("%d\n" % done.returncode, encoding="utf-8")
        (where / "argv.json").write_text(json.dumps([clean(str(part).encode()).decode() for part in argv], indent=1) + "\n", encoding="utf-8")
        written = (Path(argv[argv.index("-o") + 1]),) if "-o" in [str(part) for part in argv] else ()
        if tool == "latexmk":
            written = tuple(Path(str(argv[-1])).with_suffix(suffix) for suffix in (".pdf", ".aux"))
        for path in written:
            if path.is_file():
                (where / "files").mkdir(exist_ok=True)
                data = path.read_bytes()
                (where / "files" / path.name).write_bytes(clean(data) if path.suffix in _TEXT_FILES else data)
        return done

    return recording


class recorded_runner:
    """A `run` that answers from `recording_runner`'s directory instead of starting anything; `calls` keeps every argv.

    A call with nothing recorded answers as a tool not installed (exit 127); a pandoc call whose input differs from the one
    recorded answers that its recording is stale (exit 1). Recorded files are copied where the call writes them.
    """

    def __init__(self, root, missing=()):
        self.root, self.missing, self.calls = Path(root), set(missing), []

    def __call__(self, argv, cwd=None, timeout=None, env=None):
        argv = [str(part) for part in argv]
        self.calls.append(argv)
        name, tool, output, build, source = _call_key(argv)
        where = self.root / name / tool / output
        if tool in self.missing or not where.is_dir():
            return ToolOutput(127, b"", ("%s: nothing recorded for %s/%s" % (tool, name, output)).encode("utf-8"))
        if source is not None and (where / "input.sha256").is_file():
            wanted = (where / "input.sha256").read_text(encoding="utf-8").strip()
            if _digest(source, build) != wanted:
                return ToolOutput(1, b"", ("%s: the recording of %s/%s is stale: its input changed; rerun "
                                           "fixtures/compilations/record.py" % (tool, name, output)).encode("utf-8"))
        restore = lambda data: data.replace(b"{build}", str(build).encode()) if build else data
        if (where / "files").is_dir():
            into = Path(argv[argv.index("-o") + 1]).parent if "-o" in argv else Path(argv[-1]).parent
            for path in (where / "files").iterdir():
                data = path.read_bytes()
                (into / path.name).write_bytes(restore(data) if path.suffix in _TEXT_FILES else data)
        return ToolOutput(int((where / "returncode").read_text(encoding="utf-8").strip() or 0),
                          restore((where / "stdout").read_bytes()), restore((where / "stderr").read_bytes()))
