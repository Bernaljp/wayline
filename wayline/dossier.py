"""Dossiers at L0, L1, and L2 (Implementation Decisions 9): what a reference becomes on disk.

Level 0, which every reference gets, is the scout's verified identifiers, the metadata, the
abstract, and a knowledge-base node, written to `research/refs/<slug>/dossier.json`.
`wayline absorb --level 0` reads the reference list out of `INTAKE.md`, resolves each one through
the scout, and writes a dossier and a node for every one of them, the unresolved included. An L0
pass costs nothing but requests, so it is safe to run again: a reference already resolved is
answered out of `research/.cache/scout/` without a new request.

Level 1 is one `reader` (sonnet, medium) call per paper over a capped input, merged into the same
dossier by `absorb_level_1` (`wayline absorb --level 1 <slug>...`). Level 2, the full absorb
workflow, is `wayline.absorb` (`wayline absorb --level 2 <slug>`); what this module has is the depth budget itself:
`promote` decides, for a trigger of Implementation Decisions 9, whether a paper earns a level-2
read inside `policy.absorb.l2_per_phase` for the current phase, or opens a `decision` ticket
beyond it, and `demote` lowers a level with its own trigger. `render_levels_report` is the
minimal stand-in for the M5 report's "papers not read in full and why" until that report exists.

The second half of the module is the inventory an L2 absorb reads: for an arXiv paper, the
e-print source itself. `wayline absorb --inventory <slug>` fetches
`https://export.arxiv.org/src/<id>` through the fetch seam (one request per 3 s on one
connection, an ETag cache that never expires), keeps the source under `refs/<slug>/source/`,
flattens it, and writes `refs/<slug>/inventory.json`: the sections, the numbered equations as
LaTeX, the figures with their captions and image files, the tables, the algorithms, the
theorems, and the appendices, each with a locator into the flattened source. The arXiv terms of
use forbid re-serving an e-print, so `init` gitignores `research/refs/*/source/` and nothing
here ever publishes what it fetched. A PDF-only submission is kept as a PDF and routed to the
non-arXiv chain of ticket 22.
"""

import argparse
import bisect
import gzip
import html
import io
import json
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from collections import namedtuple
from html.parser import HTMLParser
from pathlib import Path

from wayline import HARNESS_ROOT
from wayline import worker
from wayline.cli import parse_args
from wayline.fetch import FetchError, Fetcher, UrllibBackend, caching_fetcher, recording_fetcher
from wayline.jsonschema import ValidationError, check, load_schema
from wayline.kb import ID_MAX, NODES_DIR, make_node, rebuild_query_pack, slugify, write_node
from wayline.ledger import ledger_for, now_ts
from wayline.project import HARNESS_JSON, ProjectError, find_project, policy_for, read_harness
from wayline.scout import Reference, Scout, UNRESOLVED, parse_reference
from wayline.tickets import DECISION as DECISION_KIND, TicketError, read_tickets, write_ticket

__all__ = [
    "DossierError", "REFS", "CACHE", "LEVEL_0", "LEVEL_1", "LEVEL_2", "slug_for", "l0_dossier", "write_l0", "all_slugs",
    "intake_references", "read_intake", "absorb_level_0", "absorb_command", "scout_fetcher",
    "read_dossier", "l1_input", "l1_prompt", "l1_request", "absorb_level_1",
    "PRIMARY_AT_INTAKE", "CITED_BY_SPEC", "CONTEXT_PACK", "CONSULTANT_QUESTION", "PLANNER_OR_DECIDER",
    "TRIGGERS", "promote", "demote", "render_levels_report", "render_levels_text",
    "ARXIV_SRC", "ARXIV_HTML", "SOURCE", "FIGURES", "INVENTORY", "FLAT", "Fetched",
    "arxiv_source_url", "fetch_arxiv_source", "extract_source", "main_tex", "flatten",
    "strip_comments", "environments", "latex_inventory", "aux_numbers", "apply_aux_numbers",
    "html_inventory", "build_inventory", "source_fetcher",
]

REFS = "refs"
CACHE = ".cache/scout"
LEVEL_0 = 0
LEVEL_1 = 1
LEVEL_2 = 2
QUERY_PACK_MAX = 20000  # the fallback when a policy carries no `kb.query_pack_max_chars`
L1_MAX_CHARS = 40000  # the fallback when a policy carries no `absorb.l1_max_chars`
INTAKE = "INTAKE.md"

# The five triggers of Implementation Decisions 9, in the spec's order.
PRIMARY_AT_INTAKE = "primary_at_intake"
CITED_BY_SPEC = "cited_by_spec"
CONTEXT_PACK = "context_pack"
CONSULTANT_QUESTION = "consultant_question"
PLANNER_OR_DECIDER = "planner_or_decider"
TRIGGERS = (PRIMARY_AT_INTAKE, CITED_BY_SPEC, CONTEXT_PACK, CONSULTANT_QUESTION, PLANNER_OR_DECIDER)

# What each trigger reads as in a decision ticket's body, and who it is proposed by absent an override.
_TRIGGER_LABELS = {
    PRIMARY_AT_INTAKE: "named primary at intake",
    CITED_BY_SPEC: "cited by a spec claim, baseline, or method to implement",
    CONTEXT_PACK: "named in a ticket's context pack",
    CONSULTANT_QUESTION: "a consultant question L1 cannot answer",
    PLANNER_OR_DECIDER: "the planner or the decider promotes",
}
_TRIGGER_PROPOSED_BY = {
    PRIMARY_AT_INTAKE: "human",
    CITED_BY_SPEC: "planner",
    CONTEXT_PACK: "planner",
    CONSULTANT_QUESTION: "decider",
    PLANNER_OR_DECIDER: "decider",
}
_PROMOTE_TITLE = re.compile(r"^Promote (?P<slug>.+) to level 2\?\Z")

# Words a slug drops: they carry no identity and eat the character budget.
_STOPWORDS = frozenset("a an the of for and or to in on with by via using is are at from".split())
STEM_MAX = ID_MAX - 10  # room under a node id's cap for the `-2` a clashing slug takes
_SENTENCE_END = ".:;,!?"
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$")
_REFERENCES_HEADING = re.compile(r"^references?\b", re.IGNORECASE)
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+\S")
_LIST_MARKER = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_EMPTY_ANSWER = frozenset(["none", "n/a", "na", "nothing", "tbd", "todo", "-", "none."])
_ALNUM = re.compile(r"[a-z0-9]", re.IGNORECASE)
_DOI_OR_ID = re.compile(r"\b10\.\d{4,9}/|arxiv|https?://", re.IGNORECASE)


class DossierError(ValueError):
    """A dossier the harness will not write, or an intake it cannot read a reference out of."""


# --- the slug -----------------------------------------------------------------------------------


def slug_for(record, taken=()):
    """`<family name>-<year>-<first title words>` for a resolved reference, the query for the rest.

    The slug is a directory name a person reads in a file tree, so it is built from what a
    person recognizes. A reference that resolved nowhere still gets one, out of what the owner
    wrote, because an unresolved reference is a record like any other and has to live somewhere.
    """
    metadata = record.get("metadata") or {}
    identifiers = record.get("identifiers") or {}
    parts = []
    authors = metadata.get("authors") or []
    if authors:
        parts.append(slugify(_family_name(authors[0])))
    if metadata.get("year"):
        parts.append(str(metadata["year"]))
    words = [word for word in slugify(metadata.get("title") or "").split("-") if word and word not in _STOPWORDS]
    parts.extend(words[:5])
    stem = "-".join(part for part in parts if part).strip("-")
    if not stem:
        stem = slugify(identifiers.get("arxiv_id") or identifiers.get("doi") or (record.get("query") or {}).get("value") or "")
    stem = slugify(stem, STEM_MAX) or "reference"
    candidate, suffix = stem, 1
    while candidate in taken:
        suffix += 1
        candidate = "%s-%d" % (slugify(stem, STEM_MAX - len(str(suffix)) - 1), suffix)
    return candidate


def _family_name(author):
    """The name a person is filed under, from either spelling a service uses.

    Crossref and OpenAlex give "Ashish Vaswani"; the preprint servers give "Gordon, David E.".
    Taking the last word of the second form would file the paper under an initial.
    """
    name = str(author or "").strip()
    if "," in name:
        return name.split(",", 1)[0].strip()
    words = [word for word in name.split() if word.strip(".")]
    return words[-1] if words else ""




# --- the record ---------------------------------------------------------------------------------


def l0_dossier(scout_record, slug, created=None):
    """The scout's answer as a validated level 0 dossier."""
    dossier = {
        "schema_version": 1,
        "slug": slug,
        "level": LEVEL_0,
        "existence": scout_record["existence"],
        "resolved_by": scout_record.get("resolved_by"),
        "query": dict(scout_record["query"]),
        "identifiers": dict(scout_record.get("identifiers") or {}),
        "metadata": dict(scout_record.get("metadata") or {}),
        "abstract": scout_record.get("abstract"),
        "open_access": dict(scout_record.get("open_access") or {}),
        "attempts": list(scout_record.get("attempts") or []),
        "created": created or now_ts(),
    }
    check(dossier, load_schema("dossier"), name="refs/%s/dossier.json" % slug)
    return dossier


def write_l0(project_or_ledger, dossier):
    """Write `refs/<slug>/dossier.json` and the knowledge-base node that points at it.

    The node is written whether or not the reference resolved: the graph has to be able to say
    that a reference was named and did not resolve, which is a fact about the project.
    """
    ledger = ledger_for(project_or_ledger)
    path = ledger.write_json("%s/%s/dossier.json" % (REFS, dossier["slug"]), dossier, schema="dossier")
    node = make_node(
        dossier["slug"],
        "paper",
        (dossier["metadata"].get("title") or dossier["query"].get("raw") or dossier["query"]["value"]),
        identifiers=dossier["identifiers"] or None,
        year=dossier["metadata"].get("year"),
        level=dossier["level"],
        existence=dossier["existence"],
        source=dossier.get("resolved_by"),
        created=dossier["created"],
    )
    write_node(ledger, node)
    ledger.append_event("absorbed", {"slug": dossier["slug"], "level": LEVEL_0})
    return path


# --- the intake ---------------------------------------------------------------------------------


def intake_references(text):
    """The reference lines of an `INTAKE.md`, parsed.

    The references live under a `## References` heading. When anything under it is a list item,
    the list items are the references and the prose around them is prose, which is what keeps a
    sentence introducing the list from being looked up as a paper. When nothing is a list item,
    every line is taken, because a bare list of DOIs is a list too. A line that only says the
    owner has none is never looked up: resolving the word "None" is a request spent on nothing.
    """
    lines, collecting, found, listed = str(text or "").splitlines(), False, [], []
    for line in lines:
        heading = _HEADING.match(line)
        if heading is not None:
            collecting = bool(_REFERENCES_HEADING.match(heading.group(1).strip()))
            continue
        if not collecting:
            continue
        stripped = line.strip()
        if not stripped or not _ALNUM.search(stripped):
            continue
        if _says_none(stripped):
            continue
        found.append(stripped)
        if _LIST_ITEM.match(stripped):
            listed.append(stripped)
    found = listed or found
    references, seen = [], set()
    for line in found:
        try:
            reference = parse_reference(line)
        except ValueError:
            continue
        key = (reference.kind, reference.value.lower())
        if key in seen:
            continue
        seen.add(key)
        references.append(reference)
    return references


def _says_none(line):
    """Whether a line under the heading is the owner saying there are no references.

    "None." and "None. A fixture that needed a dossier would not be a fixture." are both that
    answer, because the word closes a sentence of its own. "Nothing is known about X" is a title
    and is looked up, because the word runs on into the sentence. A line carrying an identifier
    is never this answer, whatever word it opens with.
    """
    if _DOI_OR_ID.search(line):
        return False
    line = _LIST_MARKER.sub("", line).strip()
    if line.lower().rstrip(".").strip() in _EMPTY_ANSWER:
        return True
    words = line.split()
    if not words:
        return False
    opener = words[0].lower()
    return opener.rstrip(_SENTENCE_END) in _EMPTY_ANSWER and (len(words) == 1 or opener[-1:] in _SENTENCE_END)


def read_intake(project):
    """The references named in the project's `INTAKE.md`; an absent file means no references."""
    path = Path(project) / "research" / INTAKE
    try:
        return intake_references(path.read_text(encoding="utf-8"))
    except OSError:
        return []


# --- the arXiv e-print source ---------------------------------------------------------------------

ARXIV_SRC = "https://export.arxiv.org/src/%s"
ARXIV_HTML = "https://arxiv.org/html/%s"
SOURCE = "source"
FIGURES = "figures"
INVENTORY = "inventory.json"
FLAT = "flat.tex"

# A gzipped tarball that decompresses to more than this is not a paper; the guard is here because
# the harness unpacks what a stranger served it.
SOURCE_MAX_BYTES = 256 * 1024 * 1024
_TOOL_TIMEOUT_S = 120

# `attachment; filename="arXiv-1706.03762v7.tar.gz"`: the only place the served version appears.
_DISPOSITION_VERSION = re.compile(r"filename=\"?[^\"]*?(v\d+)\.", re.IGNORECASE)
_GZIP_MAGIC = b"\x1f\x8b"
_PDF_MAGIC = b"%PDF"

Fetched = namedtuple("Fetched", "kind payload etag version url status from_cache")
"""One answer from `/src/<id>`: a tarball, a PDF-only submission, or a 304 that says keep what you have."""


def arxiv_source_url(identifier):
    """`https://export.arxiv.org/src/<id>[vN]`, the e-print endpoint of research-notes 06 Section 2."""
    return ARXIV_SRC % str(identifier).strip()


def fetch_arxiv_source(fetcher, identifier, etag=None):
    """The e-print source through the fetch seam, with the ETag cache that never expires.

    arXiv's ETag is the source's sha256, and an e-print of a given version never changes, so a
    cached tarball is good forever: with an `If-None-Match` the answer is a 304 and no bytes move.
    The seam enforces the one-request-per-3-s single connection the arXiv terms of use ask for.
    """
    url = arxiv_source_url(identifier)
    response = fetcher.fetch(url, {"If-None-Match": etag} if etag else None)
    if response.status == 304:
        return Fetched("cached", b"", etag, None, url, 304, True)
    if not response.ok:
        raise DossierError("arXiv answered %d for %s" % (response.status, url))
    version = _served_version(response.headers)
    kind = "pdf" if _looks_like_pdf(response) else "tarball"
    return Fetched(kind, response.body, response.headers.get("etag"), version, url, response.status, False)


def _served_version(headers):
    match = _DISPOSITION_VERSION.search(headers.get("content-disposition", "") or "")
    return match.group(1) if match else None


def _looks_like_pdf(response):
    """A PDF-only submission: arXiv has no source to serve and answers with the paper itself."""
    kind = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
    return kind == "application/pdf" or response.body[:4] == _PDF_MAGIC


def extract_source(payload, target):
    """The e-print's files under `target`; returns the relative paths written, in sorted order.

    Three shapes come back from `/src/`: a gzipped tar (the usual), a bare tar, and a single
    gzipped file (the old single-file submissions). A member that would land outside `target`, a
    symlink, a device, or anything else that is not a plain file is refused rather than written:
    this is a stranger's archive, unpacked on the owner's machine.
    """
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    raw = _gunzip(payload) if payload[:2] == _GZIP_MAGIC else payload
    if len(raw) > SOURCE_MAX_BYTES:
        raise DossierError("the e-print unpacks to more than %d bytes; refused" % SOURCE_MAX_BYTES)
    written = []
    if _is_tar(raw):
        with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
            total = 0
            for member in archive.getmembers():
                if member.isdir():
                    continue
                if not member.isfile():
                    continue  # a symlink, a hard link, a device: never a paper, sometimes an attack
                relative = _safe_member(member.name)
                if relative is None:
                    continue
                total += member.size
                if total > SOURCE_MAX_BYTES:
                    raise DossierError("the e-print unpacks to more than %d bytes; refused" % SOURCE_MAX_BYTES)
                handle = archive.extractfile(member)
                if handle is None:
                    continue
                path = target / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(handle.read())
                written.append(relative)
    else:
        (target / "main.tex").write_bytes(raw)
        written.append("main.tex")
    return sorted(written)


def _gunzip(payload):
    """The gzip stream, read one byte past the cap so a bomb is refused rather than truncated."""
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(payload)) as handle:
            return handle.read(SOURCE_MAX_BYTES + 1)
    except (OSError, EOFError) as failure:
        raise DossierError("the e-print is not readable gzip: %s" % failure) from None


def _is_tar(raw):
    try:
        with tarfile.open(fileobj=io.BytesIO(raw)):
            return True
    except tarfile.TarError:
        return False


def _safe_member(name):
    """A member's path relative to the extraction root, or None when it does not stay inside it."""
    cleaned = str(name).replace("\\", "/").strip()
    if not cleaned or cleaned.startswith("/"):
        return None
    parts = [part for part in cleaned.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        return None
    if any(":" in part for part in parts):  # a Windows drive letter is not a relative path
        return None
    return "/".join(parts)


# --- the main file, the flattening, and the comments ----------------------------------------------

_DOCUMENTCLASS = re.compile(r"(?<!\\)\\documentclass\b")
_README_TOPLEVEL = re.compile(r"^\s*(\S+)\s+toplevelfile\s*$", re.IGNORECASE | re.MULTILINE)
_INPUT = re.compile(r"\\(?:input|include|subfile)(?![A-Za-z])")
_TEX_SUFFIXES = (".tex", ".ltx")


def main_tex(root):
    """The top-level `.tex`: `00README` first, then the `\\documentclass` grep (research-notes 06).

    Newer submissions carry a `00README.json` or `00README.XXX` naming their top-level file, and
    that name is taken as given. Otherwise every file declaring a `\\documentclass` is a
    candidate, and the one that inputs the most others wins: a paper whose sections are separate
    files has one file that pulls them together and several that declare nothing.
    """
    root = Path(root)
    named = _readme_toplevel(root)
    if named is not None:
        return named
    candidates = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _TEX_SUFFIXES:
            continue
        text = strip_comments(_read_text(path))
        if _DOCUMENTCLASS.search(text) is None:
            continue
        candidates.append((path, len(_INPUT.findall(text)), len(str(path.relative_to(root)))))
    if not candidates:
        return None
    candidates.sort(key=lambda entry: (-entry[1], entry[2], str(entry[0])))
    return candidates[0][0].relative_to(root)


def _readme_toplevel(root):
    """The `<file> toplevelfile` line of a `00README`, as a path that exists."""
    for path in sorted(root.glob("00README*")):
        if not path.is_file():
            continue
        text = _read_text(path)
        names = []
        if path.suffix.lower() == ".json":
            try:
                record = json.loads(text)
            except ValueError:
                record = None
            for entry in (record or {}).get("sources", []) if isinstance(record, dict) else []:
                if isinstance(entry, dict) and str(entry.get("usage", "")).lower() == "toplevelfile":
                    names.append(str(entry.get("filename") or ""))
        names.extend(_README_TOPLEVEL.findall(text))
        for name in names:
            relative = _safe_member(name)
            if not relative or Path(relative).suffix.lower() not in _TEX_SUFFIXES:
                continue  # a `00README` names the compiler's input, which is not always a paper
            if (root / relative).is_file():
                return Path(relative)
    return None


def _read_text(path):
    """A source file as text; LaTeX in the wild is not always UTF-8, and an inventory is not a compiler."""
    try:
        return Path(path).read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        return Path(path).read_bytes().decode("latin-1", errors="replace")
    except OSError:
        return ""


def flatten(root, main, use_latexpand=True):
    """`latexpand main.tex`, or the in-house expander when latexpand is not installed.

    Returns `(text, flattened_by, notes)`. Comments are stripped afterwards rather than by
    latexpand (`--keep-comments`), because latexpand drops whole comment lines and the line
    numbers in `flat.tex` are what every locator in the inventory points at.
    """
    root, main = Path(root), Path(main)
    notes = []
    if use_latexpand and shutil.which("latexpand"):
        text, failure = _run_latexpand(root, main)
        if text is not None:
            return strip_comments(text), "latexpand-%s" % (_latexpand_version() or "unknown"), notes
        notes.append("latexpand failed (%s); the in-house expander stood in" % failure)
    elif use_latexpand:
        notes.append("latexpand is not installed; the in-house expander stood in, which follows \\input and \\include and nothing else")
    text, missing = expand_inputs(root, main)
    notes.extend("unresolved \\input: %s" % name for name in missing)
    return strip_comments(text), "wayline", notes


def _run_latexpand(root, main):
    command = ["latexpand", "--keep-comments", str(main)]
    bbl = (root / main).with_suffix(".bbl")
    if bbl.is_file():
        command[1:1] = ["--expand-bbl", str(bbl.relative_to(root))]
    try:
        done = subprocess.run(command, cwd=str(root), capture_output=True, timeout=_TOOL_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError) as failure:
        return None, str(failure)
    if done.returncode != 0 or not done.stdout.strip():
        return None, (done.stderr or b"").decode("utf-8", errors="replace").strip()[:200] or "empty output"
    return done.stdout.decode("utf-8", errors="replace"), None


def _latexpand_version():
    try:
        done = subprocess.run(["latexpand", "--version"], capture_output=True, timeout=_TOOL_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r"v?([0-9][0-9.]*)", done.stdout.decode("utf-8", errors="replace"))
    return match.group(1).rstrip(".") if match else None


def expand_inputs(root, main, depth=0, ancestors=(), missing=None):
    """`\\input` and `\\include` expanded in place; returns `(text, unresolved names)`.

    This is what stands in for latexpand when it is not installed. It follows the two commands
    that carry a paper's sections and leaves everything else alone, including `\\usepackage`,
    which is what latexpand does without `--expand-usepackage` too. A file input twice is
    expanded twice, because a paper that inputs one table fragment in two places prints it twice
    and an inventory that dropped the second would be counting a paper nobody wrote; only a file
    that inputs itself, directly or through a ring, is left as the command it is.
    """
    root, main = Path(root), Path(main)
    ancestors = tuple(ancestors) or (str(Path(main)),)
    missing = [] if missing is None else missing
    text = _read_text(root / main)
    if depth > 12:
        return text, missing
    out, position = [], 0
    for match in _INPUT.finditer(text):
        if _is_commented(text, match.start()):
            continue
        name, end = _argument(text, match.end())
        if name is None:
            name, end = _bare_input_argument(text, match.end())
        if name is None:
            continue
        target = _resolve_input(root, main, name)
        out.append(text[position:match.start()])
        position = end
        if target is None or str(target) in ancestors:
            missing.append(name.strip())
            out.append(text[match.start():end])
            continue
        inner, _ = expand_inputs(root, target, depth + 1, ancestors + (str(target),), missing)
        out.append(inner)
    out.append(text[position:])
    return "".join(out), missing


def _bare_input_argument(text, index):
    """`\\input file` without braces: the name runs to whitespace."""
    position = index
    while position < len(text) and text[position] in " \t":
        position += 1
    match = re.compile(r"[^\s{}\\%]+").match(text, position)
    return (match.group(0), match.end()) if match else (None, index)


def _resolve_input(root, main, name):
    """An `\\input` target against the file that named it, then against the tarball root."""
    cleaned = _safe_member(name.strip())
    if not cleaned:
        return None
    for base in (Path(main).parent, Path(".")):
        for spelling in (cleaned, cleaned + ".tex"):  # TeX appends .tex to a name without one
            relative = Path(str(base / spelling))
            if (root / relative).is_file():
                return relative
    return None


def strip_comments(text):
    """Drop every `%` comment, keeping the line it was on.

    TeX eats the newline after a comment; this does not, because the line numbers of `flat.tex`
    are the locators the inventory hands a reader. A `%` preceded by an odd number of backslashes
    is an escaped percent sign and is kept.
    """
    out = []
    for line in str(text or "").split("\n"):
        position, cut = 0, None
        while position < len(line):
            char = line[position]
            if char == "\\":
                position += 2
                continue
            if char == "%":
                cut = position
                break
            position += 1
        out.append(line if cut is None else line[:cut])
    return "\n".join(out)


def _is_commented(text, index):
    """Whether `index` sits after an unescaped `%` on its line (the in-house expander's guard)."""
    start = text.rfind("\n", 0, index) + 1
    return len(strip_comments(text[start:index])) < index - start


# --- reading LaTeX --------------------------------------------------------------------------------

Environment = namedtuple("Environment", "name starred start end body_start body")
"""One `\\begin{name}...\\end{name}` span: `start` and `end` bracket it, `body` is what is inside,
and `body_start` is where the body sits in the text the span was found in."""

_ENVIRONMENT = re.compile(r"\\(begin|end)\s*\{\s*([A-Za-z][A-Za-z0-9]*\*?)\s*\}")
_BLANK_LINE = re.compile(r"\n[ \t]*\n")


def environments(text, names=None):
    """Every environment in `text` in document order, nesting of the same name honored.

    `names` is a set of base names (starred and unstarred are the same base): a `\\begin{align*}`
    is `Environment("align", True, ...)`, because "how many align" and "how many are numbered"
    are two questions and the second is answered by the star.
    """
    stack, found = [], []
    for match in _ENVIRONMENT.finditer(text):
        which, raw = match.group(1), match.group(2)
        base, starred = (raw[:-1], True) if raw.endswith("*") else (raw, False)
        if which == "begin":
            stack.append((raw, match.start(), match.end()))
            continue
        for index in range(len(stack) - 1, -1, -1):
            if stack[index][0] != raw:
                continue
            _, start, body_start = stack[index]
            del stack[index:]
            if names is None or base in names:
                found.append(Environment(base, starred, start, match.end(), body_start, text[body_start:match.start()]))
            break
    found.sort(key=lambda item: item.start)
    return found


def _line_starts(text):
    starts = [0]
    for position, char in enumerate(text):
        if char == "\n":
            starts.append(position + 1)
    return starts


def _line_at(starts, position):
    return bisect.bisect_right(starts, position)


def _balanced(text, index):
    """The `{...}` group at `index`: `(content, index past it)`, or `(None, index)` when there is none."""
    if index >= len(text) or text[index] != "{":
        return None, index
    depth, position = 0, index
    while position < len(text):
        char = text[position]
        if char == "\\":
            position += 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[index + 1:position], position + 1
        position += 1
    return None, index


def _skip_optional(text, index):
    """Past a `[...]` optional argument at `index`, or None when it does not close."""
    depth, position = 0, index
    while position < len(text):
        char = text[position]
        if char == "\\":
            position += 2
            continue
        if char == "{":
            _, position = _balanced(text, position)
            continue
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return position + 1
        position += 1
    return None


def _argument(text, index):
    """The `{...}` argument of a command that ends at `index`, past any `[...]` options."""
    position = index
    while position < len(text):
        gap = _BLANK_LINE.match(text, position)
        if gap is not None:
            return None, index  # a blank line ends the paragraph; the group after it is not this one
        if text[position] in " \t\r\n":
            position += 1
            continue
        if text[position] == "[":
            closed = _skip_optional(text, position)
            if closed is None:
                return None, index
            position = closed
            continue
        break
    content, end = _balanced(text, position)
    return (content, end) if content is not None else (None, index)


def _commands(text, *names):
    """Every `\\name[opt]{arg}` in document order, as `(name, starred, argument, start, end)`."""
    pattern = re.compile(r"\\(%s)(\*?)(?![A-Za-z@])" % "|".join(re.escape(name) for name in names))
    for match in pattern.finditer(text):
        argument, end = _argument(text, match.end())
        yield match.group(1), bool(match.group(2)), argument, match.start(), (end if argument is not None else match.end())


def _tidy(value, limit=2000):
    """A LaTeX fragment on one line, for a caption or a title a person reads in a JSON file."""
    if value is None:
        return None
    collapsed = re.sub(r"\s+", " ", value).strip()
    return collapsed[:limit] if len(collapsed) > limit else collapsed


# --- the inventory of a flattened source ------------------------------------------------------------

SECTION_COMMANDS = ("section", "subsection", "subsubsection")
SECTION_LEVELS = {"section": 1, "subsection": 2, "subsubsection": 3}
# Environments numbered by the document, and the ones whose rows are numbered one by one.
EQUATION_ENVIRONMENTS = ("equation", "multline", "eqnarray", "align", "gather", "flalign", "alignat", "displaymath", "dmath")
MULTI_ROW_EQUATIONS = ("eqnarray", "align", "gather", "flalign", "alignat")
UNNUMBERED_EQUATIONS = ("displaymath",)
FIGURE_ENVIRONMENTS = ("figure", "wrapfigure", "sidewaysfigure")
TABLE_ENVIRONMENTS = ("table", "sidewaystable")
# `algorithmic` and `algorithmicx` are the body of an `algorithm` float rather than a float of
# their own, and counting them would count the usual `algorithm` around them twice.
ALGORITHM_ENVIRONMENTS = ("algorithm", "algorithm2e")
# The theorem environments a class defines without being asked; `\newtheorem` adds the paper's own.
THEOREM_ENVIRONMENTS = (
    "theorem", "lemma", "proposition", "corollary", "definition", "remark", "conjecture",
    "claim", "example", "assumption", "observation", "fact", "property", "problem", "hypothesis",
)
ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
# Where an item of each kind is filed in the inventory.
_BUCKETS = {"equation": "equations", "figure": "figures", "table": "tables", "algorithm": "algorithms", "theorem": "theorems"}
# The item lists of the inventory, in the order a reader meets them.
ITEM_KEYS = ("sections", "appendices", "equations", "figures", "tables", "algorithms", "theorems")

_NEWTHEOREM = re.compile(r"\\newtheorem\*?\s*\{\s*([A-Za-z][A-Za-z0-9]*)\s*\}")
_NONUMBER = re.compile(r"\\(nonumber|notag)(?![A-Za-z])")
_ROW_BREAK = re.compile(r"\\\\")
_GRAPHICSPATH = re.compile(r"\\graphicspath\s*\{")
_APPENDIX = re.compile(r"(?<!\\)\\appendix(?![A-Za-z])")
_DOCUMENTCLASS_NAME = re.compile(r"\\documentclass\s*(?:\[[^\]]*\])?\s*\{\s*([^}]*)\s*\}")
_LATEX = "latex"
_AUX = "aux"
_HTML = "html"
_NONE = "none"


def latex_inventory(text, filename=FLAT):
    """Every item a flattened, comment-stripped source names, numbered in document order.

    This is the fallback numbering of research-notes 06: LaTeX stores no numbers, so numbered
    environments are counted in the order they appear, `\\nonumber` and `\\notag` skipped and
    `\\tag` taken as given. A multi-row environment advances the counter once per row, so an
    `align` of three rows is "3-5" and the equation after it is 6. Every number from here carries
    `confirm: true`: it is a count, not a compiler's answer, and `apply_aux_numbers` replaces the
    ones a real compile settled.
    """
    text = str(text or "")
    starts = _line_starts(text)
    appendix_at = _appendix_position(text)
    theorem_names = tuple(sorted(set(THEOREM_ENVIRONMENTS) | set(_NEWTHEOREM.findall(text))))
    wanted = set(EQUATION_ENVIRONMENTS) | set(FIGURE_ENVIRONMENTS) | set(TABLE_ENVIRONMENTS)
    wanted |= set(ALGORITHM_ENVIRONMENTS) | set(theorem_names) | {"thebibliography"}
    spans = environments(text, wanted)

    record = {
        "sections": [], "equations": [], "figures": [], "tables": [],
        "algorithms": [], "theorems": [], "appendices": [], "references": [],
    }
    counters = {"section": [0, 0, 0], "equation": 0, "figure": 0, "table": 0, "algorithm": 0, "appendix": 0}
    theorem_counters = {}
    placements = []  # (start, end, item): where each item sits, so a \label finds its owner
    for position, kind, payload in _events(text, spans, theorem_names):
        locator = "%s:%d" % (filename, _line_at(starts, position))
        in_appendix = appendix_at is not None and position > appendix_at
        if kind == "section":
            where = "appendices" if in_appendix else "sections"
            item = _section_item(payload, locator, counters, in_appendix, len(record[where]) + 1)
            record[where].append(item)
            placements.append((position, position, item))
            continue
        span = payload
        if kind == "equation":
            item = _equation_item(span, text, locator, counters, len(record["equations"]) + 1)
        elif kind == "figure":
            item = _captioned_item(span, text, locator, "figure", counters, len(record["figures"]) + 1, graphics=True)
        elif kind == "table":
            item = _captioned_item(span, text, locator, "table", counters, len(record["tables"]) + 1, latex=True)
        elif kind == "algorithm":
            item = _captioned_item(span, text, locator, "algorithm", counters, len(record["algorithms"]) + 1, latex=True)
        else:
            item = _theorem_item(span, text, locator, theorem_counters, len(record["theorems"]) + 1)
        record[_BUCKETS[kind]].append(item)
        placements.append((span.start, span.end, item))
    record["references"] = _bibitems(text, starts, filename)
    _attach_labels(text, placements)
    record["metadata"] = _latex_metadata(text)
    record["counts"], record["environments"] = _counts(text, record, spans)
    record["graphicspath"] = _graphicspath(text)
    return record


def _appendix_position(text):
    match = _APPENDIX.search(text)
    return match.start() if match else None


def _events(text, spans, theorem_names):
    """Section commands and environments in one document-ordered stream."""
    events = []
    for name, starred, argument, start, _ in _commands(text, *SECTION_COMMANDS):
        events.append((start, "section", (name, starred, argument)))
    for span in spans:
        if span.name in EQUATION_ENVIRONMENTS:
            events.append((span.start, "equation", span))
        elif span.name in FIGURE_ENVIRONMENTS:
            events.append((span.start, "figure", span))
        elif span.name in TABLE_ENVIRONMENTS:
            events.append((span.start, "table", span))
        elif span.name in ALGORITHM_ENVIRONMENTS:
            events.append((span.start, "algorithm", span))
        elif span.name in theorem_names:
            events.append((span.start, "theorem", span))
    events.sort(key=lambda event: event[0])
    return events


def _section_item(payload, locator, counters, in_appendix, index):
    """One heading: its level, its title, and the number the count in document order gives it.

    After `\\appendix` the top level is a letter, which is what `article` does to `\\thesection`.
    """
    name, starred, argument = payload
    level = SECTION_LEVELS[name]
    number = None
    if not starred:
        counters["section"][level - 1] += 1
        for deeper in range(level, 3):
            counters["section"][deeper] = 0
        if in_appendix:
            if level == 1:
                counters["appendix"] += 1
            head = ALPHABET[max(0, counters["appendix"] - 1) % len(ALPHABET)]
        else:
            head = str(counters["section"][0])
        number = ".".join([head] + [str(counters["section"][deeper]) for deeper in range(1, level)])
    kind = "appendix" if in_appendix else "section"
    return _item("%s-%d" % ("app" if in_appendix else "sec", index), kind, locator, _LATEX,
                 number=number, title=_tidy(argument), level=level, confirm=number is not None)


def _equation_item(span, text, locator, counters, index):
    """One numbered environment: its source in exact form and the number the count gives it."""
    numbers = _row_numbers(span, counters)
    return _item("eq-%d" % index, "equation", locator, _LATEX, number=_join_numbers(numbers),
                 environment=_environment_name(span), latex=text[span.start:span.end], confirm=bool(numbers))


def _row_numbers(span, counters):
    """Every number the document prints for this environment, row by row.

    A starred environment and a `displaymath` print none. `\\nonumber` and `\\notag` take a row
    out, and `\\tag` gives that one row a number of its own without stepping the counter, which
    is what amsmath does: the rows around it go on counting as if it were not there.
    """
    if span.starred or span.name in UNNUMBERED_EQUATIONS:
        return []
    rows = _rows(span.body) if span.name in MULTI_ROW_EQUATIONS else [span.body]
    numbers = []
    for row in rows:
        if _NONUMBER.search(row):
            continue
        tag = next((argument for _, _, argument, _, _ in _commands(row, "tag") if argument), None)
        if tag is not None:
            numbers.append(_tidy(tag))
            continue
        counters["equation"] += 1
        numbers.append(str(counters["equation"]))
    return numbers


def _join_numbers(numbers):
    """One string for what may be several numbers: a range when they run, a list when they do not."""
    if not numbers:
        return None
    if len(numbers) == 1:
        return numbers[0]
    digits = [number for number in numbers if number.isdigit()]
    if len(digits) == len(numbers) and int(digits[-1]) - int(digits[0]) == len(digits) - 1:
        return "%s-%s" % (digits[0], digits[-1])
    return ", ".join(numbers)


def _rows(body):
    """A multi-row environment's rows: `\\\\` at brace depth zero and outside a nested environment."""
    rows, depth, nested, start, position = [], 0, 0, 0, 0
    while position < len(body):
        char = body[position]
        if char == "\\":
            if body.startswith("\\begin", position):
                nested += 1
            elif body.startswith("\\end", position):
                nested = max(0, nested - 1)
            elif body.startswith("\\\\", position) and depth == 0 and nested == 0:
                rows.append(body[start:position])
                position += 2
                start = position
                continue
            position += 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth = max(0, depth - 1)
        position += 1
    tail = body[start:]
    if tail.strip():
        rows.append(tail)
    return rows


def _captioned_item(span, text, locator, kind, counters, index, graphics=False, latex=False):
    """A figure, a table, or an algorithm: its caption, its number, and what it draws."""
    counters[kind] += 1
    prefix = {"figure": "fig", "table": "tab", "algorithm": "alg"}[kind]
    caption = next((argument for _, _, argument, _, _ in _commands(span.body, "caption") if argument), None)
    targets = [argument for _, _, argument, _, _ in _commands(span.body, "includegraphics") if argument] if graphics else []
    return _item("%s-%d" % (prefix, index), kind, locator, _LATEX, number=str(counters[kind]),
                 environment=_environment_name(span), caption=_tidy(caption),
                 graphics=[target.strip() for target in targets] if graphics else None,
                 latex=text[span.start:span.end] if latex else None, confirm=True)


def _theorem_item(span, text, locator, counters, index):
    """A theorem and its kin; the number is a per-kind count, which a class can define otherwise."""
    counters[span.name] = counters.get(span.name, 0) + 1
    title = None
    opening = span.body.lstrip()
    if opening.startswith("["):
        closed = _skip_optional(opening, 0)
        if closed is not None:
            title = opening[1:closed - 1]
    number = None if span.starred else str(counters[span.name])
    return _item("thm-%d" % index, "theorem", locator, _LATEX, number=number,
                 environment=_environment_name(span), title=_tidy(title),
                 latex=text[span.start:span.end], confirm=True)


def _environment_name(span):
    return span.name + ("*" if span.starred else "")


def _item(identifier, kind, locator, provenance, **fields):
    """One inventory item with the fields the schema names and nothing else."""
    item = {"id": identifier, "kind": kind, "locator": locator, "provenance": provenance}
    for key in ("environment", "number", "label", "title", "level", "latex", "caption", "file", "page"):
        if key in fields and fields[key] is not None:
            item[key] = fields[key]
    if fields.get("graphics"):
        item["graphics"] = fields["graphics"]
    if fields.get("ocr"):
        item["ocr"] = True
    if fields.get("confirm"):
        item["confirm"] = True
    return item


def _bibitems(text, starts, filename):
    """The bibliography, when the source carries one (latexpand inlines the `.bbl` with `--expand-bbl`)."""
    references, spans = [], environments(text, {"thebibliography"})
    for span in spans:
        marks = [match for match in re.finditer(r"\\bibitem(?![A-Za-z])", span.body)]
        for index, match in enumerate(marks):
            key, end = _argument(span.body, match.end())
            body = span.body[end:marks[index + 1].start() if index + 1 < len(marks) else len(span.body)]
            references.append({
                "id": "ref-%d" % (len(references) + 1),
                "key": _tidy(key),
                "text": _tidy(body, 1000),
                "locator": "%s:%d" % (filename, _line_at(starts, span.body_start + match.start())),
                "provenance": _LATEX,
            })
    return references


def _attach_labels(text, placements):
    """Every `\\label` to the item that holds it, or, outside them all, to the heading it follows.

    The innermost holder wins, so a `\\label` beside the `\\caption` of a figure inside a section
    belongs to the figure. A label before the first heading belongs to nothing and is dropped: it
    is a `\\label` on the title or on a package's own counter, not on an item of the paper.
    """
    for _, _, argument, start, _ in _commands(text, "label"):
        if argument is None:
            continue
        holders = [entry for entry in placements if entry[0] <= start <= entry[1] and entry[0] != entry[1]]
        if holders:
            owner = min(holders, key=lambda entry: entry[1] - entry[0])[2]
        else:
            before = [entry for entry in placements if entry[1] <= start]
            if not before:
                continue
            owner = max(before, key=lambda entry: entry[1])[2]
        owner.setdefault("label", _tidy(argument))


def _latex_metadata(text):
    metadata = {}
    title = next((argument for _, _, argument, _, _ in _commands(text, "title") if argument), None)
    if title:
        metadata["title"] = _tidy(title)
    match = _DOCUMENTCLASS_NAME.search(text)
    if match:
        metadata["documentclass"] = match.group(1).strip()
    return metadata


def _graphicspath(text):
    """The directories `\\graphicspath` adds to the search for an `\\includegraphics` target."""
    match = _GRAPHICSPATH.search(text)
    if match is None:
        return []
    group, _ = _balanced(text, match.end() - 1)
    return [part.strip() for part in re.findall(r"\{([^{}]*)\}", group or "") if part.strip()]


def _counts(text, record, spans):
    """What was found, for the count-against-a-by-eye-count of the milestone's first criterion."""
    environment_counts = {}
    for span in spans:
        name = _environment_name(span)
        environment_counts[name] = environment_counts.get(name, 0) + 1
    counts = {
        "sections": len(record["sections"]),
        "appendices": len(record["appendices"]),
        "section_headings": len(record["sections"]) + len(record["appendices"]),
        "equations": len(record["equations"]),
        "figures": len(record["figures"]),
        "tables": len(record["tables"]),
        "algorithms": len(record["algorithms"]),
        "theorems": len(record["theorems"]),
        "references": len(record["references"]),
        "labels": len(list(_commands(text, "label"))),
        "captions": len(list(_commands(text, "caption"))),
        "refs": len(list(_commands(text, "ref", "eqref"))),
        "unresolved_inputs": len([match for match in _INPUT.finditer(text)]),
    }
    return counts, environment_counts


# --- exact numbers from a compile -------------------------------------------------------------------

_NEWLABEL = re.compile(r"\\newlabel\s*\{")
_OUTPUT_PAGES = re.compile(r"Output written on .*?\((\d+) pages?", re.DOTALL)


def aux_numbers(text):
    """`{label: {"number": n, "page": p}}` from the `\\newlabel` lines of a `.aux`.

    This is the one place a LaTeX document says what its numbers are: LaTeX stores none, but a
    compile writes every labeled item's printed number and the page it landed on. A label with an
    `@` in it belongs to a package's own bookkeeping (`cref`, `sub@`), not to an item of the paper.
    """
    numbers = {}
    for match in _NEWLABEL.finditer(str(text or "")):
        label, position = _balanced(text, match.end() - 1)
        if not label or "@" in label:
            continue
        fields, _ = _balanced(text, position)
        if not fields:
            continue
        number, after = _balanced(fields, 0)
        page, _ = _balanced(fields, after)
        if number is None:
            continue
        numbers[label.strip()] = {"number": _tidy(number), "page": _page(page)}
    return numbers


def _page(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def apply_aux_numbers(record, numbers):
    """Replace every counted number with the compiled one, wherever a label ties the two together.

    An item with a label gets the exact number and the page and stops asking a reader to confirm
    it; an unlabeled one keeps its document-order count and its `confirm`. Returns how many items
    the compile settled.

    An item the document does not number keeps its lack of one: `\\label` after a `\\section*`
    records whatever the section counter last reached, so the `.aux` will happily say that an
    unnumbered appendix is section 7, which is what a `\\ref` to it prints and is not its number.
    The page from that same line is a fact about where it landed and is taken.
    """
    settled = 0
    for key in ITEM_KEYS:
        for item in record.get(key) or []:
            found = numbers.get(item.get("label") or "")
            if not found:
                continue
            if found["number"] and item.get("number"):
                item["number"] = found["number"]
            if found["page"]:
                item["page"] = found["page"]
            item["provenance"] = _AUX
            item.pop("confirm", None)
            settled += 1
    return settled


def compile_once(root, main):
    """One `pdflatex` run in `root`; returns `(aux text, pages, note)`, all None when it did not run.

    One run, never two: the numbers come from the `.aux` and a second run would only fix the
    cross-references inside the PDF, which nothing here reads. `-no-shell-escape` because this is
    a stranger's source, and `-interaction=nonstopmode` without `-halt-on-error` because a source
    that needs a package this machine does not have still numbers everything it reaches, and half
    an `.aux` is better than a prompt nobody is there to answer.
    """
    if not shutil.which("pdflatex"):
        return None, None, "pdflatex is not installed; the numbers are counted in document order"
    root, main = Path(root), Path(main)
    command = [
        "pdflatex", "-interaction=nonstopmode", "-no-shell-escape",
        "-jobname", "wayline-compile", str(main),
    ]
    try:
        subprocess.run(command, cwd=str(root), capture_output=True, timeout=_TOOL_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return None, None, "pdflatex did not finish in %d s; the numbers are counted in document order" % _TOOL_TIMEOUT_S
    except (OSError, subprocess.SubprocessError) as failure:
        return None, None, "pdflatex did not run (%s); the numbers are counted in document order" % failure
    aux = root / "wayline-compile.aux"
    if not aux.is_file():
        return None, None, "the source did not compile; the numbers are counted in document order"
    log = _read_text(root / "wayline-compile.log")
    match = _OUTPUT_PAGES.search(log)
    if match is None:
        # An `.aux` without an "Output written" line is a run that stopped partway, usually on a
        # class or package this machine does not have. What it wrote is still exact.
        return _read_text(aux), None, (
            "pdflatex did not reach the end of the document, so there is no page count and only "
            "the items it reached carry exact numbers; the rest are counted in document order"
        )
    return _read_text(aux), int(match.group(1)), None


# --- the second source: the arXiv HTML rendering -------------------------------------------------

_CLASS_KINDS = (
    ("ltx_theorem", "theorem"), ("ltx_figure", "figure"), ("ltx_table", "table"),
    ("ltx_equation", "equation"), ("ltx_algorithm", "algorithm"),
)
_TITLE_LEVELS = {"ltx_title_section": 1, "ltx_title_subsection": 2, "ltx_title_subsubsection": 3}
# The number inside a LaTeXML tag ("Figure 1: ", "(1)", "1.1 ", "A.2 "): a letter alone is a word.
_TAG_NUMBER = re.compile(r"\b([0-9]+(?:\.[0-9]+)*|[A-Z](?:\.[0-9]+)+)\b")
# The items whose text is their caption; everything else keeps the text of the item itself.
_CAPTIONED_KINDS = ("figure", "table")


class _LatexmlReader(HTMLParser):
    """The items of an `arxiv.org/html/<id>` page: LaTeXML marks every one of them with a class.

    The MathML carries the LaTeX it was built from in `alttext`, which is the only reason this
    page is worth reading at all when the tarball will not flatten: the equations come back as
    LaTeX rather than as a picture of themselves.
    """

    _VOID = frozenset(["br", "img", "hr", "meta", "link", "input", "source", "col", "area", "base", "wbr"])

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.items = []
        self._stack = []     # one entry per open element: (tag, item opened here or None, classes)
        self._title = None

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        classes = frozenset((attrs.get("class") or "").split())
        item = None
        level = next((level for name, level in _TITLE_LEVELS.items() if name in classes), None)
        if level is not None:
            self._title = {"level": level, "id": attrs.get("id"), "text": [], "tag": []}
        current = self._current()
        for name, kind in _CLASS_KINDS:
            if name not in classes:
                continue
            if current is not None and current["kind"] == kind:
                break  # LaTeXML nests a row of an equation inside the equation; one item is one item
            item = {"kind": kind, "id": attrs.get("id"), "text": [], "tag": [], "alttext": None}
            self.items.append(item)
            break
        if tag == "math" and current is not None and current["alttext"] is None and attrs.get("alttext"):
            current["alttext"] = attrs["alttext"]
        if tag not in self._VOID:
            self._stack.append((tag, item, classes))

    def handle_startendtag(self, tag, attributes):
        self.handle_starttag(tag, attributes)
        if self._stack and self._stack[-1][0] == tag:
            self._stack.pop()

    def handle_endtag(self, tag):
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index][0] == tag:
                del self._stack[index:]
                break
        if self._title is not None and tag.startswith("h"):
            title, self._title = self._title, None
            self.items.append({"kind": "section", "id": title["id"], "level": title["level"],
                               "text": title["text"], "tag": title["tag"], "alttext": None})

    def handle_data(self, data):
        target = self._title if self._title is not None else self._current()
        if target is None:
            return
        if self._inside("ltx_tag"):
            target["tag"].append(data)
        elif target.get("kind") not in _CAPTIONED_KINDS or self._inside("ltx_caption"):
            target["text"].append(data)

    def _current(self):
        """The innermost item still open, which is the one the text belongs to."""
        for _, item, _ in reversed(self._stack):
            if item is not None:
                return item
        return None

    def _inside(self, name):
        return any(name in classes for _, _, classes in self._stack)


def html_inventory(text, url=None):
    """The inventory of an `arxiv.org/html/<id>` page, the second source of research-notes 06.

    The numbers are the ones LaTeXML printed, so they are exact; the pages are not, because an
    HTML rendering has none. Coverage is not complete and arXiv itself calls the rendering beta,
    so every item here says `provenance: html` and the record carries the note.
    """
    reader = _LatexmlReader()
    reader.feed(str(text or ""))
    record = {key: [] for key in ITEM_KEYS}
    record["references"] = []
    counters = {}
    for raw in reader.items:
        kind = raw["kind"]
        bucket = "sections" if kind == "section" else _BUCKETS[kind]
        counters[bucket] = counters.get(bucket, 0) + 1
        prefix = {"sections": "sec", "equations": "eq", "figures": "fig", "tables": "tab", "algorithms": "alg", "theorems": "thm"}[bucket]
        body = _tidy(html.unescape("".join(raw["text"])))
        tag = _tidy(html.unescape("".join(raw["tag"])))
        number = _TAG_NUMBER.search(tag).group(1) if tag and _TAG_NUMBER.search(tag) else None
        locator = "%s#%s" % (url or "html", raw["id"]) if raw.get("id") else (url or "html")
        item = _item("%s-%d" % (prefix, counters[bucket]), "section" if kind == "section" else kind,
                     locator, _HTML, number=number,
                     title=body if kind in ("section", "theorem", "algorithm") else None,
                     level=raw.get("level"),
                     latex=_tidy(html.unescape(raw["alttext"])) if raw.get("alttext") else None,
                     caption=body if kind in _CAPTIONED_KINDS else None,
                     confirm=True)
        record[bucket].append(item)
    record["metadata"] = {}
    record["counts"] = {
        "sections": len(record["sections"]), "appendices": 0,
        "section_headings": len(record["sections"]), "equations": len(record["equations"]),
        "figures": len(record["figures"]), "tables": len(record["tables"]),
        "algorithms": len(record["algorithms"]), "theorems": len(record["theorems"]),
        "references": 0, "labels": 0, "captions": len([item for item in record["figures"] + record["tables"] if item.get("caption")]),
        "refs": 0, "unresolved_inputs": 0,
    }
    record["environments"] = {}
    record["graphicspath"] = []
    return record


# --- building one reference's inventory ------------------------------------------------------------

# What TeX tries when an `\includegraphics` target carries no extension, in its own order.
GRAPHICS_EXTENSIONS = (".pdf", ".png", ".jpg", ".jpeg", ".eps", ".ps", ".gif", ".svg", ".tif", ".tiff")
RASTER_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif")
IMAGE_EXTENSIONS = GRAPHICS_EXTENSIONS
_RASTER_DPI = 150


def source_fetcher(email=None, tag=None):
    """The fetcher the e-print fetch runs on: the live seam, paced at arXiv's one request per 3 s.

    Unlike the scout's, this one records nothing. The tarball is its own cache: it is kept under
    `refs/<slug>/source/` with the ETag arXiv served it with, and a second copy under
    `research/.cache/` would be the same megabytes twice.
    """
    return Fetcher(UrllibBackend(), tag=tag, email=email)


def build_inventory(project, slug, fetcher=None, email=None, compile_source=True, rasterize=True, pdf=None, tools=None, run=None):
    """Write `refs/<slug>/inventory.json`: from the arXiv e-print source when there is one, else from a PDF.

    The arXiv chain of research-notes 06 Section 2, in order: the e-print from `/src/<id>` through
    the seam, the main file from `00README` or the `\\documentclass` grep, `latexpand`, the
    environments by regex, exact numbers from one `pdflatex` run when the source compiles, and
    `arxiv.org/html/<id>` when the tarball will not flatten.

    A reference without an arXiv id, or a `pdf` the owner hands over, goes to the non-arXiv chain
    of `wayline.pdf_inventory` instead (Section 1): the PDF given, else the one already kept under
    `refs/<slug>/source/`, else the open-access PDF the scout found. A PDF-only arXiv submission
    goes there too. `tools` and `run` are that chain's seams. Returns the inventory written.
    """
    project = Path(project)
    ledger = ledger_for(project)
    record = _read_json(ledger, "%s/%s/dossier.json" % (REFS, slug))
    if record is None:
        raise DossierError("refs/%s has no dossier.json; run wayline absorb --level 0 first" % slug)
    identifier = (record.get("identifiers") or {}).get("arxiv_id")
    if email is None:
        email = _email(project)
    if pdf is not None or not identifier:
        return _pdf_inventory(ledger, slug, record, pdf, fetcher, email, tools, run)
    previous = _read_json(ledger, "%s/%s/%s" % (REFS, slug, INVENTORY)) or {}
    etag = (previous.get("source") or {}).get("etag") if _kept_source(ledger, slug) else None
    fetcher = fetcher if fetcher is not None else source_fetcher(email=email)
    fetched = fetch_arxiv_source(fetcher, identifier, etag)

    notes, workspace = [], Path(tempfile.mkdtemp(prefix="wayline-arxiv-"))
    try:
        if fetched.kind == "pdf":
            return _pdf_submission(ledger, slug, identifier, fetched, workspace, tools, run)
        if fetched.from_cache and previous.get("source_type") == "pdf":
            # A 304 says nothing has changed, and what did not change is a PDF: there is no
            # tarball to flatten and no HTML rendering to fall back to, so the kept PDF is read again.
            return _pdf_unchanged(ledger, slug, fetched, previous, tools, run)
        if fetched.from_cache:
            files = _restore_source(ledger, slug, workspace)
            notes.append("arXiv answered 304 Not Modified; the source kept under refs/%s/%s/ is the one it served" % (slug, SOURCE))
            source = dict(previous.get("source") or {})
        else:
            files = extract_source(fetched.payload, workspace)
            ledger.remove_tree("%s/%s/%s" % (REFS, slug, SOURCE))
            _keep_source(ledger, slug, workspace, files)
            source = {"bytes": len(fetched.payload), "version": fetched.version}
        # Every run remakes the figure files, so a paper that lost a figure between versions does
        # not leave one behind that no inventory item names.
        ledger.remove_tree("%s/%s/%s" % (REFS, slug, FIGURES))
        inventory = _inventory_from_workspace(
            ledger, slug, identifier, workspace, files, fetcher, notes, compile_source, rasterize,
        )
        source.update({
            "kind": "tarball",  # what was fetched and kept; `source_type` says what was inventoried
            "url": fetched.url,
            "arxiv_id": identifier,
            "etag": fetched.etag,
            "fetched": now_ts(),
            "from_cache": bool(fetched.from_cache),
            "files": len(files),
        })
        source.update(inventory.pop("source_extra"))
        inventory["source"] = source
        inventory["notes"] = notes + inventory["notes"]
        inventory["created"] = previous.get("created") or now_ts()
        if previous:
            inventory["updated"] = now_ts()
        check(inventory, load_schema("inventory"), name="refs/%s/%s" % (slug, INVENTORY))
        ledger.write_json("%s/%s/%s" % (REFS, slug, INVENTORY), inventory, schema="inventory")
        return inventory
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def _inventory_from_workspace(ledger, slug, identifier, workspace, files, fetcher, notes, compile_source, rasterize):
    """The LaTeX inventory of an extracted e-print, or the HTML rendering's when it will not flatten."""
    main = main_tex(workspace)
    text, flattened_by, pages, settled = None, None, None, 0
    if main is None:
        notes.append("no .tex declaring a \\documentclass in the e-print (%d files)" % len(files))
    else:
        text, flattened_by, flatten_notes = flatten(workspace, main)
        notes.extend(flatten_notes)
        if not text.strip():
            notes.append("%s flattened to nothing" % main)
            text = None
    if text is None:
        return _html_fallback(slug, identifier, fetcher, notes)

    record = latex_inventory(text, FLAT)
    graphicspath = record.pop("graphicspath")
    if compile_source:
        aux, pages, note = compile_once(workspace, main)
        if note:
            notes.append(note)
        if aux:
            settled = apply_aux_numbers(record, aux_numbers(aux))
    else:
        notes.append("the compile was not run; the numbers are counted in document order")
    _fill_figures(ledger, slug, workspace, main, record, graphicspath, rasterize, notes)
    flat_path = ledger.write_markdown("%s/%s/%s/%s" % (REFS, slug, SOURCE, FLAT), text)
    provenance = {key: _field_provenance(record[key]) for key in ITEM_KEYS}
    provenance.update({
        "references": _LATEX if record["references"] else _NONE,
        "metadata": _LATEX, "raw_images": _LATEX, "text_layer": _LATEX,
        "page_count": _AUX if pages else _NONE,
    })
    inventory = {
        "schema_version": 1,
        "slug": slug,
        "source_type": "latex",
        "provenance": provenance,
        "counts": record.pop("counts"),
        "environments": record.pop("environments"),
        "page_count": pages,
        "text_layer": {"path": "%s/%s" % (SOURCE, flat_path.name), "chars": len(text), "provenance": _LATEX},
        "raw_images": _raw_images(workspace, files),
        "metadata": dict(record.pop("metadata"), arxiv_id=identifier),
        "notes": [],
        "source_extra": {"main": str(main), "flattened_by": flattened_by, "compiled": bool(pages is not None or settled)},
    }
    inventory.update(record)
    return inventory


def _field_provenance(items, default=_LATEX):
    """What filled a whole field: the compile, when it settled any of the field's items.

    Per field rather than per record, because a paper that labels its figures and not its
    equations gets exact figure numbers and counted equation numbers, and the record has to be
    able to say so. The per-item `provenance` is the exact answer; this is the summary.
    """
    return _AUX if any(item.get("provenance") == _AUX for item in items or []) else default


def _html_fallback(slug, identifier, fetcher, notes):
    """`https://arxiv.org/html/<id>`, the second source when the tarball will not flatten."""
    url = ARXIV_HTML % identifier
    notes.append("the tarball would not flatten; the inventory is the arXiv HTML rendering at %s, which arXiv calls beta and which is not complete" % url)
    response = fetcher.fetch(url)
    if not response.ok:
        raise DossierError("the tarball would not flatten and %s answered %d" % (url, response.status))
    record = html_inventory(response.text(), url)
    record.pop("graphicspath")
    return {
        "schema_version": 1,
        "slug": slug,
        "source_type": "html",
        "provenance": {
            "sections": _HTML, "appendices": _NONE, "equations": _HTML, "figures": _HTML,
            "tables": _HTML, "algorithms": _HTML, "theorems": _HTML, "references": _NONE,
            "metadata": _NONE, "raw_images": _NONE, "text_layer": _NONE, "page_count": _NONE,
        },
        "counts": record.pop("counts"),
        "environments": record.pop("environments"),
        "page_count": None,
        "text_layer": None,
        "raw_images": [],
        "metadata": dict(record.pop("metadata"), arxiv_id=identifier),
        "notes": [],
        "source_extra": {"main": None, "flattened_by": None, "compiled": False},
        **record,
    }


_ARXIV_PDF_NOTE = "arXiv served a PDF, which means the submission has no source; the inventory is the non-arXiv PDF chain's"


def _pdf_submission(ledger, slug, identifier, fetched, workspace, tools, run):
    """A PDF-only submission: arXiv has no source, so the PDF it served is inventoried as a PDF."""
    from wayline.pdf_inventory import build_pdf_inventory

    name = "%s.pdf" % slugify(identifier)
    downloaded = Path(workspace) / name
    downloaded.write_bytes(fetched.payload)
    source = {"name": name, "url": fetched.url, "arxiv_id": identifier, "version": fetched.version,
              "etag": fetched.etag, "from_cache": False}
    inventory = build_pdf_inventory(ledger, slug, downloaded, tools=tools, run=run, source=source)
    return _with_note(ledger, slug, inventory, _ARXIV_PDF_NOTE)


def _pdf_unchanged(ledger, slug, fetched, previous, tools, run):
    """A PDF-only submission arXiv has just said is still the one on disk: the kept PDF, read again."""
    from wayline.pdf_inventory import build_pdf_inventory

    kept = previous.get("source") or {}
    path = ledger.research / REFS / slug / str(kept.get("main") or "")
    if not kept.get("main") or not path.is_file():
        raise DossierError("arXiv answered 304 for refs/%s but its PDF is not kept under %s/; remove %s and fetch again"
                           % (slug, SOURCE, INVENTORY))
    source = {key: kept.get(key) for key in ("url", "arxiv_id", "version") if kept.get(key)}
    source.update({"name": path.name, "etag": fetched.etag, "from_cache": True})
    inventory = build_pdf_inventory(ledger, slug, path, tools=tools, run=run, source=source)
    return _with_note(ledger, slug, inventory, "%s; arXiv answered 304 Not Modified, so the kept PDF was read again" % _ARXIV_PDF_NOTE)


def _with_note(ledger, slug, inventory, note):
    inventory["notes"] = [note] + list(inventory.get("notes") or [])
    ledger.write_json("%s/%s/%s" % (REFS, slug, INVENTORY), inventory, schema="inventory")
    return inventory


def _pdf_inventory(ledger, slug, record, pdf, fetcher, email, tools, run):
    """The non-arXiv chain for one reference: the PDF given, the one kept, or the open-access one."""
    from wayline.pdf_inventory import PDF_NAME, build_pdf_inventory

    if pdf is not None:
        return build_pdf_inventory(ledger, slug, Path(pdf), tools=tools, run=run)
    previous = _read_json(ledger, "%s/%s/%s" % (REFS, slug, INVENTORY)) or {}
    kept_main = (previous.get("source") or {}).get("main")
    kept = ledger.research / REFS / slug / kept_main if kept_main else ledger.research / REFS / slug / SOURCE / PDF_NAME
    if kept.is_file():
        source = {key: value for key, value in (previous.get("source") or {}).items()
                  if key in ("url", "arxiv_id", "version", "etag")}
        source["name"] = kept.name
        return build_pdf_inventory(ledger, slug, kept, tools=tools, run=run, source=source)
    url = (record.get("open_access") or {}).get("pdf_url")
    if not url:
        raise DossierError(
            "refs/%s has no arXiv id, no PDF kept under %s/, and no open-access PDF the scout found; "
            "hand one over with wayline absorb --inventory %s --pdf <path>" % (slug, SOURCE, slug)
        )
    fetcher = fetcher if fetcher is not None else source_fetcher(email=email)
    response = fetcher.fetch(url)
    if not response.ok or response.body[:4] != _PDF_MAGIC:
        raise DossierError(
            "the open-access PDF of refs/%s at %s answered %d%s; hand one over with wayline absorb --inventory %s --pdf <path>"
            % (slug, url, response.status, "" if not response.ok else " with something that is not a PDF", slug)
        )
    workspace = Path(tempfile.mkdtemp(prefix="wayline-pdf-download-"))
    try:
        downloaded = workspace / PDF_NAME
        downloaded.write_bytes(response.body)
        return build_pdf_inventory(ledger, slug, downloaded, tools=tools, run=run, source={"url": url})
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def _kept_source(ledger, slug):
    """Whether the e-print arXiv served last time is still on disk, which is what the ETag is for.

    `flat.tex` does not count: the harness wrote it, and a directory holding only that is a
    reference whose source was never unpacked, not one worth asking arXiv to confirm.
    """
    root = ledger.research / REFS / slug / SOURCE
    if not root.is_dir():
        return False
    return any(path.is_file() and path.relative_to(root).as_posix() != FLAT for path in root.rglob("*"))


def _keep_source(ledger, slug, workspace, files):
    """Every extracted file into `refs/<slug>/source/`, through the ledger like any other write."""
    for relative in files:
        ledger.write_bytes("%s/%s/%s/%s" % (REFS, slug, SOURCE, relative), (workspace / relative).read_bytes())
    return files


def _restore_source(ledger, slug, workspace):
    """The kept source back into a workspace, so a 304 re-inventories without a second download."""
    root = ledger.research / REFS / slug / SOURCE
    files = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root).as_posix()
        if relative == FLAT:
            continue  # the harness wrote this one; it is not part of what arXiv served
        target = workspace / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
        files.append(relative)
    return sorted(files)


def _fill_figures(ledger, slug, workspace, main, record, graphicspath, rasterize, notes):
    """Every figure's `\\includegraphics` target resolved against the tarball, and an image file made.

    A raster is copied as it is; a PDF figure is rasterized with `pdftoppm`, which is the one
    thing research-notes 06 asks for here. Without poppler installed the target is still recorded
    and the note says no image file was made, because a missing tool is a smaller loss than a
    missing figure.
    """
    searched = graphicspath or []
    for item in record["figures"]:
        targets = item.get("graphics") or []
        resolved = [found for found in (_find_graphics(workspace, main, searched, target) for target in targets) if found]
        if targets and not resolved:
            notes.append("%s: no file in the e-print matches %s" % (item["id"], ", ".join(targets)))
        if resolved:
            item["graphics"] = resolved
        made = _figure_file(ledger, slug, workspace, item["id"], resolved, rasterize, notes)
        if made:
            item["file"] = made


def _find_graphics(workspace, main, graphicspath, target):
    """An `\\includegraphics` target as a path inside the tarball, the way TeX looks for it."""
    cleaned = _safe_member(str(target).strip())
    if not cleaned:
        return None
    bases = [Path(main).parent, Path(".")] + [Path(str(entry).strip("/")) for entry in graphicspath]
    for base in bases:
        for spelling in (cleaned,) + tuple(cleaned + suffix for suffix in GRAPHICS_EXTENSIONS):
            candidate = Path(str(base / spelling))
            if (workspace / candidate).is_file():
                return candidate.as_posix()
    return None


def _figure_file(ledger, slug, workspace, item_id, resolved, rasterize, notes):
    """The image a reader is shown for one figure, written under `refs/<slug>/figures/`.

    The first target that can become an image wins, and only a figure that yields none at all is
    noted: a paper that gives both an `.eps` and a `.png` of the same picture has an image file,
    and saying otherwise would be a complaint about nothing.
    """
    for relative in resolved:
        suffix = Path(relative).suffix.lower()
        if suffix in RASTER_EXTENSIONS:
            name = "%s/%s%s" % (FIGURES, item_id, suffix)
            ledger.write_bytes("%s/%s/%s" % (REFS, slug, name), (workspace / relative).read_bytes())
            return name
        raster = _rasterize(workspace / relative, workspace) if rasterize and suffix == ".pdf" else None
        if raster is not None:
            name = "%s/%s.png" % (FIGURES, item_id)
            ledger.write_bytes("%s/%s/%s" % (REFS, slug, name), raster)
            return name
    if resolved:
        notes.append(
            "%s: no image file was made from %s; a raster is copied as it is and a PDF is rasterized "
            "with pdftoppm, and neither applied here" % (item_id, ", ".join(resolved))
        )
    return None


def _rasterize(pdf, workspace):
    """A PDF figure's first page as PNG bytes, with `pdftoppm -r 150` (research-notes 06)."""
    if not shutil.which("pdftoppm"):
        return None
    out = Path(tempfile.mkdtemp(dir=str(workspace), prefix="raster-")) / "page"
    try:
        subprocess.run(
            ["pdftoppm", "-png", "-r", str(_RASTER_DPI), "-f", "1", "-l", "1", str(pdf), str(out)],
            capture_output=True, timeout=_TOOL_TIMEOUT_S, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    made = sorted(out.parent.glob("page*.png"))
    return made[0].read_bytes() if made else None


def _raw_images(workspace, files):
    """Every image the e-print carries, whatever the document does with it."""
    images = []
    for relative in files:
        suffix = Path(relative).suffix.lower()
        if suffix not in IMAGE_EXTENSIONS:
            continue
        path = workspace / relative
        images.append({
            "path": relative,
            "format": suffix.lstrip("."),
            "bytes": path.stat().st_size if path.is_file() else None,
            "provenance": _LATEX,
        })
    return images


def _read_json(ledger, relpath):
    try:
        return ledger.read_json(relpath)
    except (OSError, ValueError):
        return None


# --- the verb -----------------------------------------------------------------------------------


def scout_fetcher(project, email=None, fixtures=None):
    """The fetcher the scout runs on: the project's cache, or a directory of recorded responses."""
    if fixtures is not None:
        return recording_fetcher(fixtures, email=email)
    return caching_fetcher(Path(project) / "research" / CACHE, email=email)


def absorb_level_0(project, references=None, fetcher=None, email=None, ledger=None):
    """Resolve every reference and write its L0 dossier, node, and the query pack. Returns a report.

    A reference already on disk is resolved again and its dossier replaced, because the cache
    makes that free and a reference that was unresolved last week may resolve today. The slug of
    a dossier that already exists is kept, so a re-run never leaves two directories for one work.
    """
    project = Path(project)
    ledger = ledger_for(ledger if ledger is not None else project)
    if email is None:
        email = _email(project)
    fetcher = fetcher if fetcher is not None else scout_fetcher(project, email=email)
    references = references if references is not None else read_intake(project)
    scout = Scout(fetcher, email)

    known = _known_slugs(ledger)
    taken = set(known.values())
    report = {"project": str(project), "references": len(references), "written": [], "verified": 0, "unresolved": 0, "problems": [], "notes": []}
    if not email:
        report["notes"].append(
            "no owner address in %s; the requests carry no mailto, which is what the polite pools ask for "
            "(add \"owner_email\" to harness.json, or lay the project out with wayline init --email <address>)" % HARNESS_JSON
        )
    for reference in references:
        if not isinstance(reference, Reference):
            reference = parse_reference(reference)
        key = (reference.kind, reference.value.lower())
        try:
            resolved = scout.resolve(reference)
            slug = known.get(key) or slug_for(resolved, taken)
            dossier = l0_dossier(resolved, slug)
            write_l0(ledger, dossier)
        except (ValidationError, ValueError, OSError) as failure:
            report["problems"].append({"reference": reference.raw, "problem": str(failure)})
            continue
        known[key] = slug
        taken.add(slug)
        report["written"].append({"slug": slug, "existence": dossier["existence"], "resolved_by": dossier["resolved_by"], "reference": reference.raw})
        report["verified" if dossier["existence"] != UNRESOLVED else "unresolved"] += 1
    rebuild_query_pack(ledger, policy_for(project).get("kb", {}).get("query_pack_max_chars", QUERY_PACK_MAX))
    return report


def _known_slugs(ledger):
    """The slug each already-written dossier was filed under, by the question it answered."""
    known = {}
    directory = ledger.research / REFS
    if not directory.is_dir():
        return known
    for path in sorted(directory.glob("*/dossier.json")):
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            query = existing["query"]
            known[(query["kind"], str(query["value"]).lower())] = existing["slug"]
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return known


def all_slugs(ledger):
    """Every slug with a dossier on disk, in file order."""
    directory = ledger.research / REFS
    if not directory.is_dir():
        return []
    return sorted(path.parent.name for path in directory.glob("*/dossier.json"))


def read_dossier(project_or_ledger, slug):
    """`refs/<slug>/dossier.json`, read fresh; raises DossierError when there is none yet."""
    ledger = ledger_for(project_or_ledger)
    try:
        return ledger.read_json("%s/%s/dossier.json" % (REFS, slug))
    except (OSError, ValueError):
        raise DossierError("no dossier for %r; run `wayline absorb --level 0` first" % (slug,)) from None


def _write_dossier(ledger, dossier):
    check(dossier, load_schema("dossier"), name="refs/%s/dossier.json" % dossier["slug"])
    return ledger.write_json("%s/%s/dossier.json" % (REFS, dossier["slug"]), dossier)


def _update_node_level(ledger, slug, level):
    """Keep the knowledge-base node's level in step with its dossier's; a missing node is not an error."""
    path = "%s/%s.json" % (NODES_DIR, slug)
    try:
        node = ledger.read_json(path)
    except (OSError, ValueError):
        return
    if isinstance(node, dict):
        node["level"] = level
        ledger.write_json(path, node)


def _intake_text(project):
    """`INTAKE.md` whole, for the intent the L1 skim reads against; None when the project has none yet."""
    try:
        return (Path(project) / "research" / INTAKE).read_text(encoding="utf-8")
    except OSError:
        return None


# --- level 1: the skim ---------------------------------------------------------------------------


def _read_inventory(ledger, slug):
    """`refs/<slug>/inventory.json` (tickets 21 and 22), when a project already has one."""
    try:
        value = ledger.read_json("%s/%s/inventory.json" % (REFS, slug))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _inventory_sections(inventory):
    """Introduction, conclusion, figure captions, and results table headers, out of an inventory."""
    rendered = []
    for section in inventory.get("sections") or []:
        title = str(section.get("title") or "")
        if re.search(r"\bintroduction\b|\bconclusion\b", title, re.IGNORECASE):
            body = section.get("text")
            if body:
                rendered.append("## %s\n\n%s" % (title, body))
    captions = [figure.get("caption") for figure in (inventory.get("figures") or []) if figure.get("caption")]
    if captions:
        rendered.append("## Figure captions\n\n" + "\n".join("- %s" % caption for caption in captions))
    headers = [table.get("caption") for table in (inventory.get("tables") or []) if table.get("caption")]
    if headers:
        rendered.append("## Results table headers\n\n" + "\n".join("- %s" % header for header in headers))
    return rendered


def _read_text_layer(ledger, slug):
    """Whatever plain text a converter already dropped under `refs/<slug>/`, for a project with no inventory yet."""
    directory = ledger.research / REFS / slug
    for name in ("text.txt", "fulltext.txt"):
        path = directory / name
        if path.is_file():
            try:
                return path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                return None
    texts = []
    for path in sorted((directory / "source").glob("*.txt")) if (directory / "source").is_dir() else []:
        try:
            texts.append(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return "\n\n".join(texts) if texts else None


def l1_input(project_or_ledger, slug, max_chars=L1_MAX_CHARS):
    """The capped input for one L1 skim: title, abstract, and the inventory or the text layer.

    Tickets 21 and 22 build the inventory (sections, figures, tables); until a project has one for
    this slug, the skim falls back to whatever plain text a converter already left under the
    reference's own directory, and further back to the title and abstract L0 already verified.
    Returns `(text, cut)`; `cut` is true when there was more than `max_chars` would hold.
    """
    ledger = ledger_for(project_or_ledger)
    dossier = read_dossier(ledger, slug)
    parts = []
    title = (dossier.get("metadata") or {}).get("title")
    if title:
        parts.append("# %s" % title)
    abstract = dossier.get("abstract")
    if abstract:
        parts.append("## Abstract\n\n%s" % abstract)
    inventory = _read_inventory(ledger, slug)
    if inventory is not None:
        parts.extend(_inventory_sections(inventory))
    else:
        text_layer = _read_text_layer(ledger, slug)
        if text_layer:
            parts.append("## Text\n\n%s" % text_layer)
    text = ("\n\n".join(parts)).strip()
    text = (text + "\n") if text else ""
    cap = max(0, int(max_chars))
    cut = len(text) > cap
    return text[:cap], cut


L1_INSTRUCTIONS = (
    "You are skimming one reference for a research project, at a capped budget. Read the "
    "material below and return the structured result: one line on how this paper relates to "
    "the project's stated intent, and one line on what would make it worth a full read."
)


def l1_prompt(intent, capped_text, cut):
    """The whole prompt for one L1 call: the instructions, the intent, the capped paper, the cut notice."""
    parts = [L1_INSTRUCTIONS]
    if intent:
        parts.append("## The project's intent\n\n%s" % intent.strip())
    parts.append("## The paper\n\n%s" % (capped_text.strip() or "(nothing was readable for this reference)"))
    if cut:
        parts.append("[wayline: the paper's material was cut here at the L1 character cap; some of it was left out.]")
    return "\n\n".join(parts) + "\n"


def l1_request(project, slug, capped_text, cut, harness_root=None, intent=None):
    """The `LaunchRequest` for one L1 skim: the `reader` role, sonnet, medium effort (decision 9)."""
    harness_root = Path(harness_root or HARNESS_ROOT)
    role = worker.read_role("reader", harness_root, project)
    name = "l1-%s" % slug
    return worker.LaunchRequest(
        role=role.name, model="sonnet", effort="medium",
        prompt=l1_prompt(intent, capped_text, cut),
        agent_json=role.agent_json("sonnet", "medium", max_turns=6),
        allowed_tools=list(role.allowed_tools), disallowed_tools=list(role.disallowed_tools),
        settings_path=None, add_dirs=[], cwd=project,
        env=worker.session_env(project, name, 1, touches=(), harness_root=harness_root),
        schema_path=harness_root / "schemas" / ((role.output_schema or "l1_record") + ".json"),
        max_minutes=5,
    )


def absorb_level_1(project, slugs=None, launcher=None, harness_root=None, ledger=None):
    """Skim each slug at level 1: one `reader` call per paper, merged into its dossier. Returns a report.

    `slugs` defaults to every slug on disk not already at level 1 or above, so `wayline absorb
    --level 1` with no names catches a project up. A slug already skimmed is left alone: an L1
    call costs a turn, and a dossier already past level 0 does not need repeating.
    """
    project = Path(project)
    ledger = ledger_for(ledger if ledger is not None else project)
    launcher = launcher or worker.launch
    max_chars = (policy_for(project).get("absorb") or {}).get("l1_max_chars", L1_MAX_CHARS)
    intent = _intake_text(project)
    slugs = list(slugs) if slugs else [slug for slug in all_slugs(ledger) if read_dossier(ledger, slug).get("level", LEVEL_0) < LEVEL_1]
    report = {"project": str(project), "skimmed": [], "problems": []}
    for slug in slugs:
        try:
            dossier = read_dossier(ledger, slug)
            if dossier.get("level", LEVEL_0) >= LEVEL_1:
                report["skimmed"].append({"slug": slug, "status": "already level %d" % dossier["level"], "cut": False})
                continue
            capped, cut = l1_input(ledger, slug, max_chars)
            request = l1_request(project, slug, capped, cut, harness_root=harness_root, intent=intent)
            envelope = launcher(request)
            if not envelope.valid:
                raise DossierError("the L1 session for %s returned no valid structured result: %s"
                                   % (slug, "; ".join(envelope.errors) or "no reason given"))
            record = envelope.structured_output
            dossier["level"] = LEVEL_1
            dossier["relation_to_intent"] = record["relation_to_intent"]
            dossier["deserves_l2_if"] = record["deserves_l2_if"]
            dossier["updated"] = now_ts()
            _write_dossier(ledger, dossier)
            _update_node_level(ledger, slug, LEVEL_1)
            ledger.append_event("absorbed", {"slug": slug, "level": LEVEL_1, "session_id": envelope.session_id}, session_id=envelope.session_id)
            report["skimmed"].append({"slug": slug, "status": "skimmed", "cut": cut})
        except (DossierError, ValidationError, worker.LaunchError, OSError) as failure:
            report["problems"].append({"slug": slug, "problem": str(failure)})
    return report


# --- levels 1 and 2: promotion and demotion (Implementation Decisions 9) -------------------------


def _current_phase(events):
    """The phase the journal last moved to; P1 (where absorb runs) when the journal names none yet."""
    phase = None
    for event in events:
        if event.get("event") == "phase":
            candidate = (event.get("payload") or {}).get("to")
            if candidate:
                phase = candidate
    return phase or "P1"


def _l2_used_in_phase(events, phase):
    """`promoted` events to level 2 since the phase last started; a phase re-entered starts a fresh budget."""
    start = 0
    for index, event in enumerate(events):
        if event.get("event") == "phase" and (event.get("payload") or {}).get("to") == phase:
            start = index + 1
    used = 0
    for event in events[start:]:
        if event.get("event") == "promoted" and (event.get("payload") or {}).get("to_level") == LEVEL_2:
            used += 1
    return used


def promote(project_or_ledger, slug, trigger, phase=None, ticket=None, proposed_by=None, detail=None):
    """Promote `slug` to level 2 on `trigger`, inside `policy.absorb.l2_per_phase`, else open a decision ticket.

    `trigger` is one of the five of Implementation Decisions 9. Inside the current phase's budget
    the dossier is promoted at once and `promoted` is journaled with the trigger; beyond it, a
    `decision` ticket is opened (its `origin` carries the trigger and the budget it exceeded) and
    `ticket_created` and `decision_opened` are journaled. A slug already at level 2 is a no-op.
    Returns a dict describing what happened.
    """
    if trigger not in TRIGGERS:
        raise DossierError("promotion trigger %r is not one of %s" % (trigger, list(TRIGGERS)))
    ledger = ledger_for(project_or_ledger)
    dossier = read_dossier(ledger, slug)
    from_level = dossier.get("level", LEVEL_0)
    if from_level >= LEVEL_2:
        return {"promoted": False, "reason": "already level 2"}
    events, _ = ledger.read_events()
    phase = phase or _current_phase(events)
    limit = ((policy_for(ledger.project).get("absorb") or {}).get("l2_per_phase") or {}).get(phase)
    used = _l2_used_in_phase(events, phase)
    if limit is None or used < limit:
        dossier["level"] = LEVEL_2
        dossier["updated"] = now_ts()
        _write_dossier(ledger, dossier)
        _update_node_level(ledger, slug, LEVEL_2)
        ledger.append_event("promoted", {"slug": slug, "from_level": from_level, "to_level": LEVEL_2, "trigger": trigger}, ticket=ticket)
        return {"promoted": True, "phase": phase, "used": used + 1, "limit": limit}
    ticket_id = _open_promotion_decision(ledger, slug, trigger, phase, used, limit, proposed_by, ticket, detail)
    return {"promoted": False, "decision_ticket": ticket_id, "phase": phase, "used": used, "limit": limit}


def _open_promotion_decision(ledger, slug, trigger, phase, used, limit, proposed_by, ticket, detail):
    """A `decision` ticket asking whether `slug` still earns level 2 beyond the phase's budget."""
    if proposed_by is None:
        proposed_by = "worker:%d" % ticket if trigger == CONSULTANT_QUESTION and ticket else _TRIGGER_PROPOSED_BY[trigger]
    next_id = max((existing["id"] for existing in read_tickets(ledger.project)), default=0) + 1
    budget_text = "%d of %s L2 slot(s) already used" % (used, limit if limit is not None else "unlimited")
    origin = "%s; phase %s, %s" % (_TRIGGER_LABELS[trigger], phase, budget_text)
    if detail:
        origin += "; " + str(detail)
    fields = {
        "id": next_id, "title": "Promote %s to level 2?" % slug, "kind": DECISION_KIND,
        "difficulty": 1, "status": "open", "blocked_by": [], "blocking": None, "human_only": False,
        "touches": [], "role": "decider", "acceptance": {}, "proposed_by": proposed_by,
        "context_pack": ["%s/%s/dossier.json" % (REFS, slug)], "origin": origin,
        "demo": "Read refs/%s/dossier.json and decide whether it earns a full level-2 read." % slug,
    }
    body = (
        "## Decision\n\nPromote `%s` to level 2 (a full read)?\n\n"
        "Trigger: %s.\n\nBudget: phase %s allows %s level-2 read(s) at a time; %s.\n"
    ) % (slug, _TRIGGER_LABELS[trigger], phase, limit if limit is not None else "unlimited", budget_text)
    write_ticket(ledger, fields, body)
    ledger.append_event("ticket_created", {"ticket": next_id, "kind": DECISION_KIND, "proposed_by": proposed_by, "origin": origin, "blocked_by": []}, ticket=next_id)
    ledger.append_event("decision_opened", {"ticket": next_id, "blocking": None, "human_only": False}, ticket=next_id)
    return next_id


def demote(project_or_ledger, slug, to_level, trigger, ticket=None):
    """Lower `slug`'s dossier level, journaling `demoted` with `trigger` (free text: decision 9 names no fixed list)."""
    if to_level not in (LEVEL_0, LEVEL_1):
        raise DossierError("demote only lowers to level 0 or 1, got %r" % (to_level,))
    if not str(trigger or "").strip():
        raise DossierError("a demotion needs a trigger to journal")
    ledger = ledger_for(project_or_ledger)
    dossier = read_dossier(ledger, slug)
    from_level = dossier.get("level", LEVEL_0)
    if to_level >= from_level:
        raise DossierError("%s is at level %d already, not above %d" % (slug, from_level, to_level))
    dossier["level"] = to_level
    if to_level < LEVEL_1:
        dossier.pop("relation_to_intent", None)
        dossier.pop("deserves_l2_if", None)
    dossier["updated"] = now_ts()
    _write_dossier(ledger, dossier)
    _update_node_level(ledger, slug, to_level)
    ledger.append_event("demoted", {"slug": slug, "from_level": from_level, "to_level": to_level, "trigger": str(trigger)}, ticket=ticket)
    return {"from_level": from_level, "to_level": to_level}


# --- the minimal report: papers by level, and what was not read in full -------------------------


def render_levels_report(project):
    """Slugs grouped by level, and every open promotion decision (a paper not read in full) with why."""
    ledger = ledger_for(project)
    by_level = {LEVEL_0: [], LEVEL_1: [], LEVEL_2: []}
    for slug in all_slugs(ledger):
        try:
            dossier = read_dossier(ledger, slug)
        except DossierError:
            continue
        by_level.setdefault(dossier.get("level", LEVEL_0), []).append(slug)
    pending = []
    try:
        for fields in read_tickets(ledger.project):
            if fields["kind"] != DECISION_KIND or fields["status"] != "open":
                continue
            match = _PROMOTE_TITLE.match(fields["title"])
            if match:
                pending.append({"slug": match.group("slug"), "ticket": fields["id"], "reason": fields.get("origin")})
    except TicketError:
        pass
    return {"by_level": {level: sorted(slugs) for level, slugs in by_level.items()}, "not_read_in_full": pending}


def render_levels_text(report):
    lines = ["papers by level"]
    for level in sorted(report["by_level"]):
        slugs = report["by_level"][level]
        lines.append("  L%d  %-3d  %s" % (level, len(slugs), ", ".join(slugs)))
    if report["not_read_in_full"]:
        lines.append("not read in full:")
        for item in report["not_read_in_full"]:
            lines.append("  %-40s ticket %-4s %s" % (item["slug"], item["ticket"], item["reason"] or ""))
    else:
        lines.append("not read in full: none")
    return "\n".join(lines)


def absorb_command(args):
    if "--code" in args:
        from wayline.code_dossier import code_command

        return code_command(args)
    parser = argparse.ArgumentParser(prog="wayline absorb", description="build the dossiers for the references")
    parser.add_argument("slugs", nargs="*", help="level 1: the reference slug(s) to skim, every one below level 1 when omitted; level 2: the one promoted slug to read in full")
    parser.add_argument("--level", type=int, default=0, choices=[0, 1, 2], help="the dossier level to build")
    parser.add_argument("--fanout", choices=["workflow", "conductor"], help="level 2: override policy.absorb.fanout")
    parser.add_argument("--spot-check", action="store_true", help="level 2: take the queued depth spot-check right after the read")
    parser.add_argument("--inventory", metavar="SLUG", help="write refs/<slug>/inventory.json from the arXiv e-print source, or from a PDF when there is none")
    parser.add_argument("--pdf", metavar="PATH", help="with --inventory: inventory this PDF (kept under refs/<slug>/source/, never committed)")
    parser.add_argument("--report", action="store_true", help="print the papers-by-level report and exit; --level is ignored")
    parser.add_argument("--project", help="the project to absorb into; the active one by default")
    parser.add_argument("--fixtures", help="answer every request from this directory of recorded responses instead of the network")
    parser.add_argument("--json", action="store_true", help="print the report as JSON instead of text")
    options, code = parse_args(parser, args)
    if options is None:
        return code
    if options.inventory:
        return _inventory_command(options)
    if options.level == LEVEL_2 and not options.report:
        from wayline.absorb import level_2_command

        return level_2_command(options)
    try:
        project = find_project(options.project)
    except ProjectError as failure:
        print("wayline absorb: %s" % failure, file=sys.stderr)
        return 1
    if options.report:
        report = render_levels_report(project)
        print(json.dumps(report, ensure_ascii=False, indent=2) if options.json else render_levels_text(report))
        return 0
    try:
        if options.level == LEVEL_1:
            report = absorb_level_1(project, options.slugs or None)
        else:
            fetcher = scout_fetcher(project, email=_email(project), fixtures=options.fixtures) if options.fixtures else None
            report = absorb_level_0(project, fetcher=fetcher)
    except (ProjectError, ValidationError, ValueError, OSError) as failure:
        print("wayline absorb: %s" % failure, file=sys.stderr)
        return 1
    if options.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif options.level == LEVEL_1:
        print(_render_l1(report))
    else:
        print(_render(report))
    return 1 if report["problems"] else 0


def _inventory_command(options):
    """`wayline absorb --inventory <slug>`: one reference's source fetched, kept, and inventoried."""
    try:
        project = find_project(options.project)
        fetcher = recording_fetcher(options.fixtures, email=_email(project)) if options.fixtures else None
        inventory = build_inventory(project, options.inventory, fetcher=fetcher, pdf=options.pdf)
    except (DossierError, FetchError, ProjectError, ValidationError, ValueError, OSError) as failure:
        print("wayline absorb --inventory: %s" % failure, file=sys.stderr)
        return 1
    if options.json:
        print(json.dumps(inventory, ensure_ascii=False, indent=2))
    else:
        print(_render_inventory(inventory))
    return 0


def _render_inventory(inventory):
    source = inventory.get("source") or {}
    lines = ["%-12s %s  (%s, %s)" % (inventory["slug"], source.get("url", ""), inventory["source_type"], source.get("version") or "no version")]
    if inventory["source_type"] == "pdf":
        lines.append("  source     %s, %s pages, converter %s, references by %s" % (
            source.get("main"), inventory.get("page_count"), source.get("converter") or "none", source.get("references_by") or "none",
        ))
    else:
        lines.append("  source     %s files, main %s, flattened by %s%s" % (
            source.get("files"), source.get("main"), source.get("flattened_by"),
            ", compiled" if source.get("compiled") else ", not compiled",
        ))
    counts = inventory.get("counts") or {}
    if counts:
        lines.append("  found      " + ", ".join("%s %d" % (name, counts[name]) for name in sorted(counts) if counts[name]))
    environments = inventory.get("environments") or {}
    if environments:
        lines.append("  latex      " + ", ".join("%s %d" % (name, environments[name]) for name in sorted(environments)))
    for note in inventory.get("notes") or []:
        lines.append("  note       %s" % note)
    return "\n".join(lines)


def _email(project):
    """The address the polite pools are told about, from the project's `harness.json`."""
    try:
        return read_harness(project).get("owner_email")
    except (ProjectError, OSError, ValueError):
        return None


def _render(report):
    lines = ["references  %d  (%d verified, %d unresolved)" % (report["references"], report["verified"], report["unresolved"])]
    for written in report["written"]:
        lines.append("  %-10s %-50s %s" % (written["existence"], written["slug"], written["resolved_by"] or ""))
    for problem in report["problems"]:
        lines.append("  problem    %s: %s" % (problem["reference"], problem["problem"]))
    for note in report["notes"]:
        lines.append("  note       %s" % note)
    if not report["written"] and not report["problems"]:
        lines.append("  nothing to absorb; INTAKE.md names no references")
    return "\n".join(lines)


def _render_l1(report):
    lines = ["skimmed  %d" % len(report["skimmed"])]
    for item in report["skimmed"]:
        lines.append("  %-24s %-50s %s" % (item["status"], item["slug"], "(cut)" if item.get("cut") else ""))
    for problem in report["problems"]:
        lines.append("  problem                  %-50s %s" % (problem["slug"], problem["problem"]))
    if not report["skimmed"] and not report["problems"]:
        lines.append("  nothing to skim; every dossier is already level 1 or above")
    return "\n".join(lines)
