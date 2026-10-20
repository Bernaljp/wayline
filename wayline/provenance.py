"""The manifest and findings provenance (Implementation Decisions 6 and 2). Built by ticket 18.

`results/` lives outside version control (Implementation Decisions 1 already ignores it); every artifact a
finding will ever cite is hashed into `research/manifest.json` first, by `register_artifact`, so a
finding's provenance resolves to a file the manifest holds. Findings are written through the ledger
call of `wayline.sections` (`file_finding`), which clusters each into its result (`wayline.results`).

Ticket 40 added the rest of Implementation Decisions 11 (C8): the claim markup
(`{res:<run-id>/<artifact>#<locator>}` and `{ref:<slug>#<locator>}` at the end of a claim
sentence), the sentence classifier and its cache, the linter (Type-A) that resolves every tag
against the manifest and the knowledge base, the verifier's sample of tagged claims (Type-B,
through the gate of `wayline.gates`), and `REPORT.md` itself. The report lives here because decision 1's
module list has no `report` module and BRIEF 10 gives the writer "role + provenance.py".

Since ticket 90 `REPORT.md` is the general report: about the research, always current, and written by code alone
(`render_report`), from the results, the objectives, the concerns, the passages, and the spec. No writer session
drafts any of it. What wayline did is `research/ACCOUNT.md`, which `wayline.account` renders in the same pass. The
numbers check at acceptance is `wayline.numbers`.
"""

import argparse
import hashlib
import json
import math
import random
import re
import subprocess
import sys
from collections import namedtuple
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from wayline import HARNESS_ROOT, POLICY_PATH, gates, ledger, pacing, sections, tickets, worker
from wayline.cli import parse_args
from wayline.jsonschema import ValidationError, check, load_schema
from wayline.ledger import Ledger, now_ts
from wayline.project import ProjectError, fable_falls_back, find_project, policy_for, read_harness
from wayline.objectives import ObjectivesUnreadable, read_objectives

__all__ = [
    "ProvenanceError", "MANIFEST", "FINDINGS", "RUN_ID_RE",
    "sha256_of", "read_manifest", "manifest_paths", "register_artifact",
    "read_findings", "current_findings",
    "commit_threshold_bytes", "oversized_tracked_files",
    "TAG_RE", "RES_TAG_RE", "REF_TAG_RE", "REF_IDENTIFIER_TAG_RE", "Sentence", "sentences", "parse_tag", "ref_slug", "identifier_index", "strip_tags",
    "REPORT", "CLAIMS_CACHE", "SECTIONS", "SENTENCE_CLASSES", "RECORDS_BEGIN", "RECORDS_END",
    "UsageLimited", "Lint", "Claim", "Rendered", "prose_sentences", "sentence_hash", "render_citations", "restore_tags",
    "read_claims_cache", "classify", "lint", "lint_report", "tagged_claims", "sample_size", "sample_claims",
    "claim_subject", "claim_paths", "verify_claims", "report_evidence", "finding_tags", "finding_text", "finding_line",
    "tagged_text", "render_report", "report_command",
    "ANY_TAG_RE", "TAG_KINDS", "REF_TITLE_TAG_RE", "CODE_TAG_RE", "DOC_TAG_RE", "UNRESOLVED_CODE", "UNRESOLVED_DOC", "DOC_ONLY_CLAIM",
    "PLOT_TAG_RE", "UNRESOLVED_PLOT",
    "code_reader", "main_reader", "code_tag_problem", "end_kinds", "lint_passages", "lint_result", "result_sentences", "resolver_for",
]

MANIFEST = "manifest.json"
FINDINGS = "findings.jsonl"

RUN_ID_RE = re.compile(r"^t[0-9]+-a[0-9]+$")

# The provenance markup of Implementation Decisions 11: a claim sentence ends with one or more
# `{res:<run-id>/<artifact>#<locator>}` or `{ref:<slug>#<locator>}`.
TAG_RE = re.compile(r"\{(res|ref):([^{}]+)\}")
RES_TAG_RE = re.compile(r"^(?P<run_id>t[0-9]+-a[0-9]+)/(?P<artifact>[^#]+)#(?P<locator>.+)$")
REF_TAG_RE = re.compile(r"^(?P<slug>[a-z0-9][a-z0-9._-]*)#(?P<locator>.+)$")
# A `ref` tag may name its work by identifier in place of the slug (decision 17; ticket 98): `{ref:doi:10.1038/x#abstract}`,
# `{ref:arxiv:1802.03426#abstract}`, mapped to a slug through position's identifier index. An inherited citation is
# an identifier tag with no locator; a slug always names one.
REF_IDENTIFIER_TAG_RE = re.compile(r"^(?P<identifier>(?:[Dd][Oo][Ii]|[Aa][Rr][Xx][Ii][Vv]):[^#\s]+)(?:#(?P<locator>.+))?$")
# The third identifier form (ticket 88): `{ref:title:<exact title>}`, which an inherited citation with neither a DOI nor an
# arXiv id carries (ticket 93), mapped through the identifier index's titles. The title holds spaces; its locator holds none.
REF_TITLE_TAG_RE = re.compile(r"^(?P<identifier>[Tt][Ii][Tt][Ll][Ee]:[^#]*\S)(?:#(?P<locator>[^#\s]+))?$")
# What the project's code does (decision 17; ticket 88): `{code:<path>#<symbol>}` or `{code:<path>#L10-L42}`, the path
# from the project's root (`code/phase.py`) or from inside `code/` (`phase.py`), resolved against `main` at a render and
# against the ticket's worktree at its acceptance.
CODE_TAG_RE = re.compile(r"^(?P<path>[^#\s]+)#(?P<locator>L[1-9][0-9]*(?:-L?[1-9][0-9]*)?|[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)$")
# Inherited text (ticket 93): `{doc:<document>#<locator>}`, provenance and never a citation.
DOC_TAG_RE = re.compile(r"^(?P<document>[A-Za-z0-9._-]+)#(?P<locator>[^#\s]+)$")
# Every provenance tag a sentence may end with, the two of decision 11 and the two of decision 17.
ANY_TAG_RE = re.compile(r"\{(res|ref|code|doc):([^{}]+)\}")
TAG_KINDS = ("res", "ref", "code", "doc")
# A plot of a drawing (decision 17; ticket 100): `{plot:R4.3}`, a table `{plot:R4.T1}`, which a section cites where the
# reader should look. It is no provenance tag: it never ends a claim's support, and it resolves against `plots.json`.
PLOT_TAG_RE = re.compile(r"\{plot:([^{}]*)\}")
_PLOT_ID = re.compile(r"^R[1-9][0-9]*\.T?[1-9][0-9]*$")

# Where one sentence ends: a full stop, question mark or exclamation mark, then any closing
# quotes, then the provenance tags that belong to the sentence just ended, and then either the
# start of the next sentence or the end of the text. Requiring a capital (or a quote or a bracket)
# after the space is what keeps "Fig. 1", "e.g. the" and "0.5" from each becoming two sentences;
# it is a heuristic, and a draft that opens a sentence with a lowercase symbol name joins the one
# before it. The linter classifies sentences and this decides what a sentence is, so both halves
# of the provenance work see exactly the same units.
# An inherited passage's `{doc:...}` tag (ticket 93) ends its sentence too, though it is no `res` or `ref` tag, and so
# does the mark a section's render writes after an inherited claim (`[unchecked]`, `[unverifiable: <reason>]`).
_MARK = r"(?:\s*\[(?:unchecked|unverifiable: [^\[\]]*)\])"
_BOUNDARY = re.compile(r"""[.!?]["')\]]*(?:\s*\{(?:res|ref|code|doc):[^{}]+\})*""" + _MARK + r"""?(?=\s+["'(\[A-Z]|\s*$)""")
_ANY_TAG = re.compile(r"\{(?:res|ref|code|doc):[^{}]+\}|" + _MARK)

Sentence = namedtuple("Sentence", "text tags")

_HASH_CHUNK = 1 << 20  # 1 MiB


class ProvenanceError(ValueError):
    """A finding whose provenance does not resolve, or an artifact that cannot be manifested."""


class UsageLimited(ProvenanceError, gates.UsageLimited):
    """A session the usage limit refused: a closed window rather than a bad answer, so never resumed.

    It is the gate's `UsageLimited` too, so whatever catches a refused verdict catches a refused
    writer or classifier as well, with the `limit` that refused it.
    """


def _ledger(project_or_ledger):
    return project_or_ledger if isinstance(project_or_ledger, Ledger) else Ledger(project_or_ledger)


def sha256_of(path):
    """The sha256 of a file's bytes, read in chunks so a large result artifact is not loaded whole."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(_HASH_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


# --- the manifest --------------------------------------------------------------------------


def read_manifest(project_or_ledger):
    """`research/manifest.json`, or the empty manifest when `init` has not written one yet."""
    book = _ledger(project_or_ledger)
    try:
        return book.read_json(MANIFEST)
    except FileNotFoundError:
        return {"entries": []}


def manifest_paths(manifest):
    return {entry["path"] for entry in manifest.get("entries", [])}


def register_artifact(project_or_ledger, path, job, run_id, ticket):
    """Hash `path` (relative to the project) into `manifest.json` and journal `manifest`.

    `run_id` is `t<ticket>-a<attempt>`, the attempt that produced or registered the artifact
    (Implementation Decisions 6); `job` is the job id when a job wrote the file, else None. A
    second registration of the same path (a rerun that overwrote its own output) replaces the
    entry rather than appending a stale sibling, so the manifest always names the file that is
    actually on disk. The read, hash, and write happen under the ledger's lock, so two workers
    registering artifacts at once cannot lose one entry to the other's write.
    """
    book = _ledger(project_or_ledger)
    relative = Path(path)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise ProvenanceError("register_artifact takes a path relative to the project, got %r" % (path,))
    if not RUN_ID_RE.match(run_id or ""):
        raise ProvenanceError("run_id must be t<ticket>-a<attempt>, got %r" % (run_id,))
    absolute = book.project / relative
    try:
        size = absolute.stat().st_size
        digest = sha256_of(absolute)
    except OSError as failure:
        raise ProvenanceError("%s cannot be manifested: %s" % (absolute, failure)) from None
    relpath = relative.as_posix()
    entry = {"path": relpath, "size": size, "sha256": digest, "job": job, "run_id": run_id, "ticket": ticket, "ts": now_ts()}
    with book.lock():
        manifest = read_manifest(book)
        entries = [existing for existing in manifest.get("entries", []) if existing["path"] != relpath]
        entries.append(entry)
        book.write_json(MANIFEST, {"entries": entries}, schema="manifest")
        book.append_event("manifest", {"path": relpath, "sha256": digest, "size": size, "job": job, "run_id": run_id}, ticket=ticket)
    return entry


# --- findings --------------------------------------------------------------------------------


def read_findings(project_or_ledger):
    """Every line of `research/findings.jsonl`, in file order."""
    book = _ledger(project_or_ledger)
    path = book.research / FINDINGS
    if not path.exists():
        return []
    findings = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                findings.append(json.loads(line))
    return findings


def current_findings(project_or_ledger):
    """The findings no later finding replaces, in file order (ticket 106)."""
    findings = read_findings(project_or_ledger)
    replaced = {finding.get("replaces") for finding in findings if finding.get("replaces")}
    return [finding for finding in findings if finding.get("id") not in replaced]


def _cited(finding):
    """A written finding's locators: a list, or one locator as an older finding carries it."""
    provenance = finding.get("provenance")
    if isinstance(provenance, str):
        return [provenance] if provenance else []
    return list(provenance or [])


# --- the sentence pass -------------------------------------------------------------------------
#
# One walk over a draft's prose, shared by the claim linter of Implementation Decisions 11 and by
# the guidelines checks of decision 13, so a sentence means the same thing to both and a draft is
# read once rather than twice. Nothing here classifies a sentence: that is one model call per
# batch and it is the linter's, not this module's.


def sentences(text):
    """The prose of `text` as `Sentence(text, tags)`, each sentence carrying the tags it ends with.

    `text` is prose, not markup: strip the LaTeX or Markdown first (the guidelines module does it
    while it is counting words anyway). A sentence with no tag carries an empty tuple, which is
    what the linter's classifier is handed and what the mechanical cross-check counts.
    """
    text = str(text or "")
    # Boundaries are found with every tag's inside masked, so a title in a tag (`{ref:title:What Does BERT Look At? An
    # Analysis}`) never ends a sentence; the masked text has the same length, so it slices the text itself.
    masked = ANY_TAG_RE.sub(lambda found: "{%s:%s}" % (found.group(1), "x" * len(found.group(2))), text)
    found, start = [], 0
    for boundary in _BOUNDARY.finditer(masked):
        found.append(text[start:boundary.end()])
        start = boundary.end()
    found.append(text[start:])
    result = []
    for chunk in found:
        body = chunk.strip()
        if body:
            result.append(Sentence(body, tuple("%s:%s" % (kind, rest) for kind, rest in ANY_TAG_RE.findall(body))))
    return result


def parse_tag(tag):
    """One tag as `(kind, parts)`, or `(kind, None)` when it is malformed; `(None, None)` for a non-tag.

    `parts` is the named groups of the tag's shape: a `res` tag resolves to a run id, an artifact
    and a locator, a `ref` tag to a slug (or an `identifier`: `doi:`, `arxiv:`, or `title:`) and a
    locator, a `code` tag to a path and a symbol or a line range, a `doc` tag to a document and a
    locator. A tag whose halves are there but empty is malformed, which is the case the linter
    refuses and the guidelines check reports.
    """
    kind, _, rest = str(tag or "").partition(":")
    if kind not in TAG_KINDS or not rest:
        return None, None
    if kind == "ref":
        for pattern in (REF_IDENTIFIER_TAG_RE, REF_TITLE_TAG_RE):
            named = pattern.match(rest)
            if named is not None:
                prefix, _, value = named.group("identifier").partition(":")
                return kind, {"identifier": "%s:%s" % (prefix.lower(), value.strip()), "locator": named.group("locator")}
    pattern = {"res": RES_TAG_RE, "ref": REF_TAG_RE, "code": CODE_TAG_RE, "doc": DOC_TAG_RE}[kind]
    found = pattern.match(rest)
    return kind, (found.groupdict() if found else None)


def ref_slug(parts, index):
    """The slug a parsed `ref` tag names: its own, or its identifier's through `index` (position's identifier index); None when unknown."""
    if not parts:
        return None
    if parts.get("slug"):
        return parts["slug"]
    from wayline.position import slug_for_identifier  # position reaches this module through specify and the decider
    return slug_for_identifier(index or {}, parts.get("identifier"))


# --- the `code` tag ---------------------------------------------------------------------------------
#
# A `code` tag says what the project's code does, so it resolves only while the code still does it: the file is
# there and defines the symbol, or holds the lines. A reader is `path -> text or None`, over a checkout's working
# tree (a ticket's worktree at its acceptance) or over a branch (`main`, at a render), read with `git show`.

CODE_DIR = "code"
_LINE_RANGE = re.compile(r"^L([1-9][0-9]*)(?:-L?([1-9][0-9]*))?$")


def code_reader(root, ref=None):
    """`path -> text` over `root`'s working tree, or over branch `ref` of the git repository at `root`; None for a file not there."""
    root = Path(root)

    def read(path):
        relative = Path(path)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            return None
        if ref is None:
            try:
                return (root / relative).read_text(encoding="utf-8", errors="replace")
            except OSError:
                return None
        done = subprocess.run(["git", "-C", str(root), "show", "%s:%s" % (ref, relative.as_posix())], capture_output=True)
        return done.stdout.decode("utf-8", errors="replace") if done.returncode == 0 else None

    read.where = "on %s" % ref if ref else "in the worktree"
    return read


def main_reader(project):
    """What a render resolves `code` tags against: the project's `main`, or its working tree when it has no `main`."""
    done = subprocess.run(["git", "-C", str(project), "rev-parse", "--verify", "-q", "main^{commit}"], capture_output=True)
    return code_reader(project, "main" if done.returncode == 0 else None)


def _python_names(text):
    """Every name a Python file defines: functions and classes by qualified name (`Model.step`) and module-level names."""
    import ast
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return None
    names = set()

    def walk(body, prefix):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(prefix + node.name)
                walk(node.body, prefix + node.name + ".")
            elif not prefix and isinstance(node, (ast.Assign, ast.AnnAssign)):
                for target in (node.targets if isinstance(node, ast.Assign) else [node.target]):
                    if isinstance(target, ast.Name):
                        names.add(target.id)

    walk(tree.body, "")
    return names


def code_tag_problem(read, parts):
    """Why a parsed `code` tag does not resolve through `read` (a `code_reader`), or None when it does.

    The path is the project's (`code/phase.py`) or `code/`'s own (`phase.py`). A line range resolves inside the
    file; a symbol resolves when a Python file defines it (by its qualified name or its last part) and, in any
    other language, when the file names it as a word.
    """
    path = str(parts["path"])
    path = path[2:] if path.startswith("./") else path
    candidates = [path] if path.startswith(CODE_DIR + "/") else [path, "%s/%s" % (CODE_DIR, path)]
    where = getattr(read, "where", "")
    text = candidate = None
    for candidate in candidates:
        text = read(candidate)
        if text is not None:
            break
    if text is None:
        return "%s is not a file %s" % (" or ".join(candidates), where)
    locator = parts["locator"]
    lines = _LINE_RANGE.match(locator)
    if lines:
        start, end = int(lines.group(1)), int(lines.group(2) or lines.group(1))
        count = len(text.splitlines())
        if end < start:
            return "%s names lines %d to %d, which run backwards" % (candidate, start, end)
        if end > count:
            return "%s has %d lines %s, so it holds no lines %d to %d" % (candidate, count, where, start, end)
        return None
    names = _python_names(text) if candidate.endswith(".py") else None
    if names is not None:
        if locator in names or any(name.split(".")[-1] == locator for name in names):
            return None
    elif re.search(r"(?<!\w)%s(?!\w)" % re.escape(locator.split(".")[-1]), text):
        return None
    return "%s defines no %s %s" % (candidate, locator, where)


def identifier_index(project):
    """Position's identifier index over the project's dossiers, `{}` when there are none to read."""
    from wayline.position import identifier_index as index_of
    try:
        return index_of(project)
    except (OSError, ValueError):
        return {}


def strip_tags(text):
    """`text` with its provenance tags taken off, `doc` tags too, for a word count that does not count markup."""
    return _ANY_TAG.sub("", str(text or "")).strip()


# --- the commit-threshold check ---------------------------------------------------------------


def commit_threshold_bytes(project):
    """`policy.artifacts.commit_threshold_bytes`, a project's `harness.json` overriding the shipped default."""
    policy = json.loads(Path(POLICY_PATH).read_text(encoding="utf-8"))
    value = policy["artifacts"]["commit_threshold_bytes"]
    try:
        harness = json.loads((Path(project) / "harness.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        harness = {}
    override = ((harness.get("policy") or {}).get("artifacts") or {}).get("commit_threshold_bytes")
    return value if override is None else override


def oversized_tracked_files(project, threshold=None):
    """Every git-tracked file under `project` heavier than `threshold` bytes, as a warning list.

    A soft default (Implementation Decisions 6): nothing here refuses anything. `results/` is
    already git-ignored by `init`, so this only ever catches a file the owner or a ticket chose
    to commit; the warning names the manifest as the place a heavier file belongs instead.
    """
    project = Path(project)
    threshold = commit_threshold_bytes(project) if threshold is None else threshold
    done = subprocess.run(["git", "-C", str(project), "ls-files"], capture_output=True, text=True)
    if done.returncode != 0:
        return []
    warnings = []
    for relative in done.stdout.splitlines():
        if not relative:
            continue
        try:
            size = (project / relative).stat().st_size
        except OSError:
            continue
        if size > threshold:
            warnings.append({
                "path": relative,
                "size": size,
                "threshold": threshold,
                "note": "%s is %d bytes, over commit_threshold_bytes (%d); consider the manifest instead of committing it" % (relative, size, threshold),
            })
    return warnings


# --- the report (ticket 40) ----------------------------------------------------------------------
#
# REPORT.md is rendered by code from the ledger. The writer's prose is the only model-authored text
# in it, and every prose sentence of it, the findings included, is classified and linted. In the
# order a render runs them: the prose of a tagged markdown document, the sentence classifier and its
# cache, the linter, the writer, the eleven sections, the citations the tags render as, the render
# itself, and the verifier's sampled verdicts on the claims of the rendered file.

REPORT = "REPORT.md"
REPORT_PATH = "research/" + REPORT
CLAIMS_CACHE = ".cache/claims.json"
CLASSIFIER = "classifier"
WRITER = "writer"
CLASSES_SCHEMA = "claim_classes"

CLAIM = "claim"
DEFINITION = "definition"
TRANSITION = "transition"
METHOD_DESCRIPTION = "method_description"
SENTENCE_CLASSES = (CLAIM, DEFINITION, TRANSITION, METHOD_DESCRIPTION)

# What the linter reports, one kind per problem.
UNTAGGED_CLAIM = "untagged_claim"
UNCLASSIFIED = "unclassified"
MALFORMED_TAG = "malformed_tag"
UNRESOLVED_RES = "unresolved_res"
UNRESOLVED_REF = "unresolved_ref"
UNRESOLVED_CODE = "unresolved_code"  # a `code` tag whose file no longer defines its symbol or holds its lines (ticket 88)
UNRESOLVED_DOC = "unresolved_doc"  # a `doc` tag naming a document the project does not keep (ticket 88)
UNRESOLVED_PLOT = "unresolved_plot"  # a `plot` tag naming no current plot of `plots.json` (ticket 100)
# What the linter lists rather than fails before the paper order (ticket 88): a claim whose only tags are `doc` tags,
# which say where inherited text came from and never what supports it.
DOC_ONLY_CLAIM = "doc_only_claim"

# One `haiku --effort low` call classifies at most this many sentences.
CLASSIFY_BATCH = 40

# Code-rendered listings sit between these two lines. They are records of the journal, whose
# provenance is the journal itself, so the classifier never reads them and the linter never checks
# them; the prose around them (the findings and the writer's paragraphs) is what C8 is about.
RECORDS_BEGIN = "<!-- wayline:records -->"
RECORDS_END = "<!-- /wayline:records -->"

# The general report's sections, in decision 17's order (ticket 90). What wayline did (the decisions made for the owner,
# what waits on the owner, the tickets closed, the judgments on Opus while Fable was spent, the papers by level, what
# was not pursued, the global changes proposed, and the resources spent) is the account's (`wayline.account`, ticket 89).
SECTIONS = (
    "What the project is",
    "Headlines",
    "The results",
    "Objectives",
    "Results beyond the objectives",
    "Inherited claims not yet checked",
    "What can and cannot be inferred",
)
SUPPLEMENTARY = "Supplementary references"

# A session that drafts or classifies reads at most; it writes nothing under `research/`.
READ_ONLY_TOOLS = ("Read", "Glob", "Grep")
WRITE_TOOLS = ("Edit", "Write", "NotebookEdit", "Bash")

RESUME_STRUCTURED = (
    "The answer you returned could not be used: %s.\n\n"
    "Return it again now, through the structured output, matching the schema this session was "
    "launched with. Change nothing else."
)

CLAIM_QUESTION = "Do the cited artifacts, at their locators, support this sentence as it is written?\n\n> %s"
CLAIM_SCOPE = (
    "Only this one sentence, and only the tags it carries. A `res` tag names a result file and a "
    "key, line, or heading in it; a `ref` tag names a reference whose record is under "
    "`research/refs/<slug>/` and a locator in the paper. Open each one. The sentence passes when "
    "what you read there says what the sentence says, numbers and direction included; a sentence "
    "that says more than the artifacts do fails, with a finding at the tag you read. Whether the "
    "claim matters, or is well written, is not your question."
)
CLAIM_TITLE = "Scope down a report claim its artifacts do not support"
# What a scope-down ticket's findings cite: the M5 run's cited the report's own tags, and the ledger refused them.
PROVENANCE_FORM = ("A finding's provenance is the artifact's path in the project and a locator, the form the manifest "
                   "resolves (`analysis/ablation/signal-4.json#paired_gain`), never a report tag such as "
                   "`{res:<run>/<path>}`: the ledger refuses a provenance it cannot find in `manifest.json` or on disk.")

VENUE_PREFIX = "paper venue: "  # the answer a `decision` on the paper's venue opens with (`decider.VENUE_ANSWER`, ticket 53)

# The tags a claim sentence ends with: after its full stop, as code writes a finding's, or just before it, as a worker
# writes a passage's (`... least squares {code:code/phase.py#fit}.`); a tag with words after it is inside the sentence.
_TAGS_AT_END = re.compile(r"""(?:\{(?:res|ref|code|doc):[^{}]+\}\s*)+[.!?"')\]]*\s*$""")
_FOOTNOTE = re.compile(r"^\[\^(\d+)\]:\s*`(res|ref):([^`]+)`\s*$")
_CITATION = re.compile(r"\[\^(\d+)\](?!:)")
_LIST_ITEM = re.compile(r"^(?:[-*+]|\d+[.)])\s+")
_FENCE = re.compile(r"^(`{3,}|~{3,})")
_RUN_TICKET = re.compile(r"^t([0-9]+)-a[0-9]+$")


def prose_sentences(markdown):
    """The prose of a markdown document as `Sentence`s: what the classifier reads and the linter checks.

    Prose is paragraphs, list items, and block quotes. Headings, tables, code blocks, HTML comment
    lines, footnote definitions, and everything between `RECORDS_BEGIN` and `RECORDS_END` are not.
    A paragraph's lines are joined before it is split, so a sentence wrapped across lines is one.
    """
    blocks, current = [], []
    in_records, fence = False, None

    def flush():
        if current:
            blocks.append(" ".join(current))
            current.clear()

    for raw in str(markdown or "").splitlines():
        line = raw.strip()
        if fence is not None:
            if line.startswith(fence):
                fence = None
            continue
        if in_records:
            if line == RECORDS_END:
                in_records = False
            continue
        if line == RECORDS_BEGIN:
            flush()
            in_records = True
            continue
        opened = _FENCE.match(line)
        if opened:
            flush()
            fence = opened.group(1)
            continue
        if not line or line.startswith(("#", "|", "<!--")) or _FOOTNOTE.match(line):
            flush()
            continue
        if line.startswith(">"):
            line = line.lstrip(">").strip()
        item = _LIST_ITEM.match(line)
        if item:
            flush()
            line = line[item.end():]
        current.append(line)
    flush()
    return [sentence for block in blocks for sentence in sentences(block)]


def sentence_hash(text):
    """The cache key of one sentence: its words, tags taken off and whitespace collapsed.

    Adding, fixing, or removing a tag leaves the key alone, because a tag says where a claim comes
    from and not what kind of sentence it is; changing a word changes the key.
    """
    return hashlib.sha256(" ".join(strip_tags(text).split()).encode("utf-8")).hexdigest()


# --- citations ------------------------------------------------------------------------------------


def render_citations(markdown):
    """The tags of a document rendered as numbered footnote citations, with the references listed at the end.

    A tag's number is the order of its first appearance, and a tag cited twice keeps its number.
    `restore_tags` reads the rendered form back, which is how the linter checks a report on disk.
    """
    numbers = {}

    def cite(match):
        tag = "%s:%s" % (match.group(1), match.group(2))
        numbers.setdefault(tag, len(numbers) + 1)
        return "[^%d]" % numbers[tag]

    body = TAG_RE.sub(cite, str(markdown or "")).rstrip("\n")
    if not numbers:
        return body + "\n"
    lines = [
        body, "", "## " + SUPPLEMENTARY, "", RECORDS_BEGIN,
        "Each citation is a provenance tag: `res:<run-id>/<artifact>#<locator>` names a result in "
        "`research/manifest.json`, and `ref:<slug>#<locator>` a reference under `research/refs/<slug>/`.",
        RECORDS_END, "",
    ]
    lines.extend("[^%d]: `%s`" % (number, tag) for tag, number in numbers.items())
    return "\n".join(lines) + "\n"


def restore_tags(markdown):
    """A document rendered by `render_citations` with its citations turned back into tags.

    A citation whose number has no reference line is left as it is, so the sentence reads as
    untagged to the linter, which is what it is.
    """
    text = str(markdown or "")
    lines = text.splitlines()
    tags = {}
    for line in lines:
        found = _FOOTNOTE.match(line.strip())
        if found:
            tags[found.group(1)] = "{%s:%s}" % (found.group(2), found.group(3))
    restored = [
        line if _FOOTNOTE.match(line.strip())
        else _CITATION.sub(lambda match: tags.get(match.group(1), match.group(0)), line)
        for line in lines
    ]
    return "\n".join(restored) + ("\n" if text.endswith("\n") else "")


# --- the classifier -------------------------------------------------------------------------------


def read_claims_cache(project_or_ledger):
    """`research/.cache/claims.json` as `{sentence hash: class}`; empty when absent or unreadable."""
    book = _ledger(project_or_ledger)
    try:
        data = book.read_json(CLAIMS_CACHE)
    except (OSError, ValueError):
        return {}
    classes = data.get("classes") if isinstance(data, dict) else None
    if not isinstance(classes, dict):
        return {}
    return {digest: kind for digest, kind in classes.items() if kind in SENTENCE_CLASSES}


def classify(project, texts, *, harness_root=HARNESS_ROOT, policy=None, offline=False, batch_size=CLASSIFY_BATCH):
    """Classify every sentence of `texts` the cache does not already hold; returns the whole cache.

    Sentences are sent in batches of `batch_size`, one `classifier` session per batch on the model
    `policy.roles.classifier` gives, through the launcher. The session sees numbered sentences with
    their tags taken off; code maps the numbers back and writes each batch into the cache as it
    lands, so a failure in the third batch keeps the first two. `offline` launches nothing and
    returns the cache as it is: what it does not cover stays unclassified.
    """
    project = Path(project).resolve()
    book = Ledger(project)
    cache = read_claims_cache(book)
    pending, queued = [], set()
    for text in texts:
        body = " ".join(strip_tags(text).split())
        digest = sentence_hash(text)
        if not body or digest in cache or digest in queued:
            continue
        queued.add(digest)
        pending.append((digest, body))
    if offline or not pending:
        return cache
    if not isinstance(batch_size, int) or batch_size < 1:
        raise ProvenanceError("batch_size is a positive integer, got %r" % (batch_size,))
    policy = policy_for(project, harness_root) if policy is None else policy
    role = worker.read_role(CLASSIFIER, harness_root, project)
    for start in range(0, len(pending), batch_size):
        batch = pending[start:start + batch_size]
        answered = _classify_batch(project, role, policy, harness_root, batch)
        with book.lock():
            cache = read_claims_cache(book)
            cache.update(answered)
            book.write_json(CLAIMS_CACHE, {"schema_version": 1, "classes": dict(sorted(cache.items()))})
    return cache


def _classify_batch(project, role, policy, harness_root, batch):
    lines = [
        "# The sentences",
        "",
        "Classify every numbered sentence below; the number in brackets is how you refer to it.",
        "",
    ]
    lines.extend("[%d] %s" % (number, body) for number, (_, body) in enumerate(batch, start=1))
    prompt = joined("\n".join(lines), role.protocol, worker.schema_section("# The classes", CLASSES_SCHEMA))
    request = structured_request(project, role, policy, harness_root, prompt, CLASSES_SCHEMA, "small",
                       session_dir(project, CLASSIFIER))
    envelope = _launch_structured(request, lambda answer: _classes_problem(answer, len(batch)), "sentence classifier")
    by_number = {entry["n"]: entry["class"] for entry in envelope.structured_output["classes"]}
    return {digest: by_number[number] for number, (digest, _) in enumerate(batch, start=1)}


def _classes_problem(envelope, count):
    problem = schema_problem(envelope, CLASSES_SCHEMA)
    if problem is not None:
        return problem
    numbers = [entry["n"] for entry in envelope.structured_output["classes"]]
    expected = set(range(1, count + 1))
    parts = []
    missing = sorted(expected - set(numbers))
    if missing:
        parts.append("no class for sentence(s) %s" % ", ".join(map(str, missing)))
    extra = sorted(set(numbers) - expected)
    if extra:
        parts.append("a class for sentence(s) %s, which the batch does not have" % ", ".join(map(str, extra)))
    repeated = sorted({number for number in numbers if numbers.count(number) > 1})
    if repeated:
        parts.append("more than one class for sentence(s) %s" % ", ".join(map(str, repeated)))
    return "; ".join(parts) or None


# --- the linter (Type-A) --------------------------------------------------------------------------


@dataclass
class Lint:
    """What the linter found in one document: whether it passes, the counts, every problem, and what it lists.

    A problem is `{sentence, problem, tag, detail}`, `problem` one of the kinds above, with `passage` naming the
    passage it is in when the linter read passages. `claims` counts the sentences classified as claims and `tagged`
    those of them that end with a tag. `listed` holds what is shown and never failed (ticket 88): before the paper
    order, a claim tagged only `doc` and an untagged claim in an owner's passage; at an acceptance, a sentence the
    classifier has not classified.
    """

    passed: bool
    claims: int
    tagged: int
    unclassified: int
    problems: list = field(default_factory=list)
    listed: list = field(default_factory=list)


class _Resolver:
    """What a tag resolves against: `manifest.json` for `res`, a verified dossier and a node for `ref`, the code for
    `code` (`code_read`, `main` by default), and the project's documents for `doc`.

    `own_run` is `(run_id, root)` at a ticket's acceptance: a `res` tag of the attempt's own run names a file of its
    worktree, which the manifest takes in only once the ticket is integrated.
    """

    def __init__(self, project, code_read=None, own_run=None):
        self.project = Path(project)
        entries = read_manifest(self.project).get("entries", [])
        self.manifested = {(entry.get("run_id"), entry.get("path")) for entry in entries}
        self._index = None
        self._code_read = code_read
        self._documents = None
        self._plots = None
        self.own_run = own_run

    def index(self):
        if self._index is None:
            self._index = identifier_index(self.project)
        return self._index

    def code_read(self):
        if self._code_read is None:
            self._code_read = main_reader(self.project)
        return self._code_read

    def plots(self):
        if self._plots is None:
            try:
                record = json.loads((self.project / "research" / "plots.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                record = None
            self._plots = {str(plot.get("id")): plot for plot in (record or {}).get("plots") or [] if isinstance(plot, dict)}
        return self._plots

    def plot_problem(self, identifier):
        """Why a `{plot:<id>}` tag does not resolve, or None: it names a current plot or table of `plots.json`."""
        if not _PLOT_ID.match(identifier):
            return UNRESOLVED_PLOT, "`plot:%s` names no plot: a plot is `R<n>.<k>` and a table `R<n>.T<k>`" % identifier
        plot = self.plots().get(identifier)
        if plot is None:
            return UNRESOLVED_PLOT, "research/plots.json holds no plot %s" % identifier
        if plot.get("status") != "current":
            return UNRESOLVED_PLOT, "%s was retired; cite a current plot of %s" % (identifier, plot.get("result"))
        return None

    def documents(self):
        if self._documents is None:
            from wayline.documents import read_documents  # documents imports the ledger's neighbours
            try:
                self._documents = {str(document.get("id")) for document in read_documents(self.project) if isinstance(document, dict)}
            except (OSError, ValueError):
                self._documents = set()
        return self._documents

    def problem(self, tag):
        if tag.startswith("res:unmanifested/"):
            return UNRESOLVED_RES, "%s is not in manifest.json" % tag[len("res:unmanifested/"):].partition("#")[0]
        kind, parts = parse_tag(tag)
        if kind is None or parts is None:
            return MALFORMED_TAG, ("`%s` is none of `res:<run-id>/<artifact>#<locator>`, `ref:<slug>#<locator>`, "
                                   "`code:<path>#<symbol>` (or `#L<a>-L<b>`), and `doc:<document>#<locator>`" % tag)
        if kind == "res":
            if (parts["run_id"], parts["artifact"]) in self.manifested:
                return None
            if self.own_run is not None and parts["run_id"] == self.own_run[0] and _inside_file(self.own_run[1], parts["artifact"]):
                return None
            runs = sorted(run for run, path in self.manifested if path == parts["artifact"])
            if runs:
                return UNRESOLVED_RES, "manifest.json has %s from run %s, not from run %s" % (parts["artifact"], ", ".join(runs), parts["run_id"])
            return UNRESOLVED_RES, "%s is not in manifest.json" % parts["artifact"]
        if kind == "code":
            found = code_tag_problem(self.code_read(), parts)
            return None if found is None else (UNRESOLVED_CODE, found)
        if kind == "doc":
            if parts["document"] in self.documents():
                return None
            return UNRESOLVED_DOC, "research/documents.json keeps no document %s" % parts["document"]
        slug = ref_slug(parts, self.index())
        if slug is None:
            return UNRESOLVED_REF, "no dossier is filed under %s; check it with `wayline scout`" % parts.get("identifier")
        research = self.project / "research"
        try:
            dossier = json.loads((research / "refs" / slug / "dossier.json").read_text(encoding="utf-8"))
        except OSError:
            return UNRESOLVED_REF, "research/refs/%s/ holds no dossier.json" % slug
        except ValueError:
            return UNRESOLVED_REF, "research/refs/%s/dossier.json is not JSON" % slug
        if not isinstance(dossier, dict) or dossier.get("existence") != "verified":
            return UNRESOLVED_REF, "research/refs/%s/dossier.json does not say existence: verified" % slug
        if not (research / "kb" / "nodes" / (slug + ".json")).is_file():
            return UNRESOLVED_REF, "research/kb/ holds no node %s" % slug
        return None


def _inside_file(root, relative):
    """Whether `relative` is a file of the worktree `root` that its branch carries to `main`: there, and not git-ignored
    (an output under `results/` stays behind in the worktree, so no manifest will ever hold it from this run)."""
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or not path.parts or not (Path(root) / path).is_file():
        return False
    ignored = subprocess.run(["git", "-C", str(root), "check-ignore", "-q", "--", path.as_posix()], capture_output=True)
    return ignored.returncode != 0


def end_kinds(text):
    """The kinds of the tags a sentence ends with, in order; empty for a sentence that ends with none."""
    found = _TAGS_AT_END.search(text)
    return [kind for kind, _ in ANY_TAG_RE.findall(found.group(0))] if found else []


class _Pass:
    """One linter pass: the problems, the listed sentences, and the counts, over sentences fed in one at a time."""

    def __init__(self, resolver, classes, doc_only_fails, unclassified_fails, unresolved_ref_fails=True):
        self.resolver, self.classes = resolver, classes
        self.doc_only_fails, self.unclassified_fails = doc_only_fails, unclassified_fails
        self.unresolved_ref_fails = unresolved_ref_fails
        self.problems, self.listed = [], []
        self.claims = self.tagged = self.unclassified = 0

    def read(self, sentence, extra=None, owner=False, tagged_by_provenance=False):
        """Lint one sentence. `owner`: an owner's passage, whose untagged claim is listed; `tagged_by_provenance`: a
        finding with no tag of its own, which its provenance tags when Results renders it."""
        extra = dict(extra or {})
        for tag in sentence.tags:
            found = self.resolver.problem(tag)
            if found is not None:
                listed = found[0] == UNRESOLVED_REF and not self.unresolved_ref_fails
                (self.listed if listed else self.problems).append(dict(extra, sentence=sentence.text, problem=found[0], tag=tag,
                                                                       detail=found[1]))
        for identifier in PLOT_TAG_RE.findall(sentence.text):
            found = self.resolver.plot_problem(identifier.strip())
            if found is not None:
                self.problems.append(dict(extra, sentence=sentence.text, problem=found[0], tag="plot:%s" % identifier, detail=found[1]))
        if not strip_tags(sentence.text) or tagged_by_provenance:
            return
        kind = self.classes.get(sentence_hash(sentence.text))
        ends = end_kinds(sentence.text)
        if kind == CLAIM:
            self.claims += 1
            if ends and any(end != "doc" for end in ends):
                self.tagged += 1
            elif ends:
                entry = dict(extra, sentence=sentence.text, problem=DOC_ONLY_CLAIM, tag=None,
                             detail="its only tags are `doc` tags, which say where inherited text came from and never what supports it")
                (self.problems if self.doc_only_fails else self.listed).append(entry)
            else:
                detail = ("its tags are inside it; a claim sentence ends with them" if sentence.tags
                          else "a claim sentence ends with at least one provenance tag")
                entry = dict(extra, sentence=sentence.text, problem=UNTAGGED_CLAIM, tag=None, detail=detail)
                (self.listed if owner else self.problems).append(entry)
        elif kind is None and not ends:
            self.unclassified += 1
            entry = dict(extra, sentence=sentence.text, problem=UNCLASSIFIED, tag=None,
                         detail="not classified yet, so nothing says it is not a claim; render without --offline")
            (self.problems if self.unclassified_fails else self.listed).append(entry)

    def result(self):
        return Lint(passed=not self.problems, claims=self.claims, tagged=self.tagged, unclassified=self.unclassified,
                    problems=self.problems, listed=self.listed)


def lint(project, markdown, classes, doc_only_fails=False, code_read=None):
    """The Type-A provenance check of one tagged document against a project's ledger.

    Every tag in the prose must resolve: a `res` tag to the run and the path of an entry in
    `manifest.json`, a `ref` tag to a reference whose `dossier.json` says `existence: verified` and
    that has a knowledge-base node, a `code` tag to what the project's `main` (or `code_read`) holds,
    and a `doc` tag to a document the project keeps. Every sentence `classes` calls a claim must end
    with at least one tag; one whose only tags are `doc` tags is listed, or failed when
    `doc_only_fails` (the paper, after the order). An untagged sentence `classes` does not cover
    fails too, because nothing then says it is not a claim. Records (between `RECORDS_BEGIN` and
    `RECORDS_END`) are not read.
    """
    linted = _Pass(_Resolver(project, code_read), classes, doc_only_fails, unclassified_fails=True)
    for sentence in prose_sentences(markdown):
        linted.read(sentence)
    return linted.result()


def resolver_for(project):
    """What tags resolve against for one project, read once and shared by several linter passes: the manifest, the
    identifier index, the documents, and `main`'s code, each read the first time a tag needs it."""
    return _Resolver(project)


def lint_passages(project, items, classes, code_root=None, code_read=None, own_run=None, unclassified_fails=False, resolver=None,
                  unresolved_ref_fails=False):
    """The linter over passages and findings (decision 17; ticket 88): every tag resolves, every claim ends tagged.

    `items` are passages (`{id, by, text}`) or findings (`{id, text, provenance}`); each problem and listed sentence
    names the `passage` it is in. Before the paper order an untagged claim in an owner's passage, a claim tagged
    only `doc`, and a `ref` tag naming a work not resolved (ticket 105) are listed, never failed (the last fails with
    `unresolved_ref_fails`, a section's reading after the order); a finding with no tag of its own is tagged by its provenance. `code` tags
    resolve against `code_root`'s working tree (a ticket's worktree), or `code_read`, or the project's `main`; `resolver`,
    from `resolver_for`, is one several passes share (a render of every section). An
    unclassified sentence is listed unless `unclassified_fails`.
    """
    read = code_read or (code_reader(code_root) if code_root is not None else None)
    resolver = resolver if resolver is not None else _Resolver(project, read, own_run)
    # Before the paper order a citation of a work not yet resolved is listed, never failed (ticket 105): References says
    # where it stands, and the check at acceptance (`references.check_references`) sends back a work no service knows.
    linted = _Pass(resolver, classes, doc_only_fails=False, unclassified_fails=unclassified_fails, unresolved_ref_fails=unresolved_ref_fails)
    for item in items:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "")
        finding = "provenance" in item and "by" not in item
        own_tags = bool(ANY_TAG_RE.search(text))
        extra = {"passage": item.get("id")}
        for sentence in prose_sentences(text):
            linted.read(sentence, extra, owner=item.get("by") == "owner", tagged_by_provenance=finding and not own_tags)
    return linted.result()


def lint_result(project, result, classes, code_root=None, run_id=None):
    """The linter on one ticket result's passages and findings at its acceptance (decision 17; ticket 88).

    `code_root` is the ticket's worktree, which `code` tags and the attempt's own `res` tags (`run_id`) resolve
    against. A problem sends the worker back; what is listed does not.
    """
    result = result if isinstance(result, dict) else {}
    items = [dict(item, id="passage %d" % index) for index, item in enumerate(result.get("passages") or [], start=1)
             if isinstance(item, dict)]
    items += [dict(item, id="finding %d" % index) for index, item in enumerate(result.get("findings") or [], start=1)
              if isinstance(item, dict)]
    own = (run_id, code_root) if run_id and code_root is not None else None
    return lint_passages(project, items, classes, code_root=code_root, own_run=own)


def result_sentences(result):
    """The sentences of a result's passages and findings the classifier is asked about: those ending with no tag,
    leaving out a finding with no tag of its own, which its provenance tags."""
    texts = []
    for name in ("passages", "findings"):
        for item in (result or {}).get(name) or []:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "")
            if name == "findings" and not ANY_TAG_RE.search(text):
                continue
            texts.extend(sentence.text for sentence in prose_sentences(text)
                         if strip_tags(sentence.text) and not end_kinds(sentence.text))
    return texts


# --- the verifier's sample (Type-B) ---------------------------------------------------------------


@dataclass(frozen=True)
class Claim:
    """One tagged claim sentence: its text, its tags, its hash, and the tickets its `res` tags came from."""

    text: str
    tags: tuple
    digest: str
    tickets: tuple = ()


def tagged_claims(markdown, classes):
    """The tagged claim sentences of a document, in document order, each once."""
    found, seen = [], set()
    for sentence in prose_sentences(markdown):
        digest = sentence_hash(sentence.text)
        if classes.get(digest) != CLAIM or not any(kind != "doc" for kind in end_kinds(sentence.text)):
            continue
        if (digest, sentence.tags) in seen:
            continue
        seen.add((digest, sentence.tags))
        producers = set()
        for tag in sentence.tags:
            kind, parts = parse_tag(tag)
            run = _RUN_TICKET.match(parts["run_id"]) if kind == "res" and parts else None
            if run:
                producers.add(int(run.group(1)))
        found.append(Claim(sentence.text, sentence.tags, digest, tuple(sorted(producers))))
    return found


def sample_size(count, policy):
    """How many of `count` tagged claims the verifier samples before the difficulty-5 claims are added."""
    rules = (policy or {}).get("provenance") or {}
    rate, minimum = rules.get("sample", 0.10), rules.get("min", 10)
    return min(count, max(math.ceil(round(rate * count, 9)), minimum))


def sample_claims(claims, policy, difficulties, seed=None):
    """The claims the verifier reads: `policy.provenance.sample` of them, at least `min`, plus every difficulty-5 one.

    The share and the minimum are taken of all the tagged claims and drawn from the ones that are
    not difficulty-5 claims; every claim a difficulty-5 ticket produced is then added on top, when
    `all_difficulty_5` says so. A claim comes from a ticket when one of its `res` tags names a run of
    that ticket; `difficulties` maps a ticket id to its effective difficulty. The draw is seeded,
    by default from the claims themselves, so the same report samples the same claims.
    """
    claims = list(claims)
    rules = (policy or {}).get("provenance") or {}
    every_hardest = rules.get("all_difficulty_5", True)
    forced = [claim for claim in claims
              if every_hardest and any(difficulties.get(ticket) == tickets.HARDEST for ticket in claim.tickets)]
    rest = [claim for claim in claims if claim not in forced]
    if seed is None:
        seed = hashlib.sha256("\n".join(claim.digest for claim in claims).encode("utf-8")).hexdigest()
    drawn = random.Random(seed).sample(rest, min(len(rest), sample_size(len(claims), policy)))
    chosen = set(forced) | set(drawn)
    return [claim for claim in claims if claim in chosen]


def claim_subject(claim, document=REPORT_PATH):
    """The verdict subject of one claim: the report and a hash of the sentence with its tags.

    A claim whose tags change is a new subject and is read again; the same claim in a later render
    is the same subject, and the verdict it already has stands.
    """
    digest = hashlib.sha256((claim.digest + "\n" + "\n".join(claim.tags)).encode("utf-8")).hexdigest()
    return "%s#claim-%s" % (document, digest[:16])


def claim_paths(claim, index=None):
    """What the verifier opens for one claim: each tag's artifact, with its locator."""
    paths = []
    for tag in claim.tags:
        kind, parts = parse_tag(tag)
        if kind == "res" and parts:
            paths.append("%s#%s" % (parts["artifact"], parts["locator"]))
        elif kind == "ref" and parts:
            slug = ref_slug(parts, index)
            paths.append("research/refs/%s/#%s" % (slug or parts.get("identifier"), parts["locator"] or "dossier"))
        elif kind == "code" and parts:
            path = parts["path"] if parts["path"].startswith(CODE_DIR + "/") else "%s/%s" % (CODE_DIR, parts["path"])
            paths.append("%s#%s" % (path, parts["locator"]))
    return paths


def verify_claims(project, *, harness_root=HARNESS_ROOT, policy=None, seed=None, document=REPORT_PATH, prose_author=None):
    """Sample the tagged claims of `research/REPORT.md`, or of `document`, and take one Type-B verdict on each.

    `document` is the paper's `research/paper/paper.md` when `wayline paper --verify` samples it (decision 11: every
    claim in the report and the paper, by sampling), with `prose_author` the model the paper's writer ran on.

    Every verdict goes through `gates.verdict` with `subject_kind: claim`, so it is journaled with
    its session and its model, on the verifier the table gives for the claim's author: the ticket that
    wrote the finding for a finding's sentence, the writer for the prose. While Fable's weekly window is
    spent, a claim whose verifier is Fable is judged by a fresh Opus session at the table's effort under
    the fallback consent `auto`; otherwise it waits, listed under `waiting`, for a later pass (decision 15).
    A claim that already has a verdict is not read again, whatever model took it. A failing claim files
    one `writing` ticket, unless an open one for the same claim is already there. Returns what happened,
    as a dict.
    """
    project = Path(project).resolve()
    book = Ledger(project)
    policy = policy_for(project, harness_root) if policy is None else policy
    try:
        text = (project / document).read_text(encoding="utf-8")
    except OSError:
        raise ProvenanceError("%s is not there; %s first" % (document, "render it with wayline report" if document == REPORT_PATH
                                                               else "draft it")) from None
    context = report_context(project)
    claims = tagged_claims(restore_tags(text), read_claims_cache(book))
    difficulties = {number: fields.get("pinned_difficulty") or fields.get("difficulty")
                    for number, fields in context.tickets.items()}
    chosen = sample_claims(claims, policy, difficulties, seed)
    verdicted = {(event.get("payload") or {}).get("subject") for event in context.events
                 if event.get("event") == ledger.VERDICT and (event.get("payload") or {}).get("subject_kind") == CLAIM}
    authors = _finding_authors(context)
    writer_model = prose_author or _role_tier(policy, WRITER)[0]  # the paper's writer; every claim of the report is a finding's
    outcome = {"claims": len(claims), "sampled": len(chosen), "already_verdicted": 0, "passed": [], "failed": [], "tickets": [],
               "waiting": [], "fell_back": []}
    try:
        # Decided once for the pass, so a hold that begins or ends during it cannot split the claims between Fable and Opus.
        fall_back, held = gates.fallback_now(project, "the claim verdicts"), False
    except gates.FableHeld:
        fall_back, held = False, True
    index = identifier_index(project)
    for claim in chosen:
        subject = claim_subject(claim, document)
        if subject in verdicted:
            outcome["already_verdicted"] += 1
            continue
        from_finding = claim.digest in authors
        author = authors.get(claim.digest) or writer_model
        if held and gates.verifies_on_fable(policy, author):
            outcome["waiting"].append(subject)
            continue
        taken = gates.verdict(
            CLAIM, subject, CLAIM_QUESTION % one_line(claim.text), claim_paths(claim, index), CLAIM_SCOPE,
            project=project, author_model=author, verdict_type=gates.CLAIM_SUPPORT, harness_root=harness_root,
            policy=policy, ledger=book, fall_back=fall_back,
        )
        verdicted.add(subject)
        if taken.fallback_from:
            outcome["fell_back"].append(subject)
        if taken.passed:
            outcome["passed"].append(subject)
            continue
        outcome["failed"].append(subject)
        filed = _claim_ticket(project, book, claim, subject, taken, from_finding, document)
        if filed is not None:
            outcome["tickets"].append(filed)
    return outcome


def _finding_authors(context):
    """`{sentence hash: model alias}` for every sentence the report renders from a finding."""
    models = {}
    for event in context.events:
        if event.get("event") == ledger.TICKET_LAUNCHED:
            payload = event.get("payload") or {}
            models[payload.get("ticket")] = payload.get("model")
    authors = {}
    for finding in context.findings:
        for sentence in prose_sentences(finding_line(finding, context.manifest)):
            authors[sentence_hash(sentence.text)] = models.get(finding.get("ticket"))
    return authors


def _claim_ticket(project, book, claim, subject, taken, from_finding, document=REPORT_PATH):
    if gates.open_writing_ticket(project, subject) is not None:
        return None
    paths = claim_paths(claim, identifier_index(project))
    remedy = ("The sentence is a finding as its ticket recorded it, and the report renders findings as "
              "recorded. Return in the result a finding that says only what the artifact supports, with its "
              "provenance; the ledger records it and the next render reads it."
              if from_finding else
              "The sentence is the writer's prose. Return in the result, as a finding with its provenance, "
              "what the artifacts do support; the prose is redrafted from the findings when they change.")
    body = "\n".join([
        "## The claim the verifier could not support",
        "",
        "> %s" % one_line(claim.text),
        "",
        "Verifier session `%s` (%s) opened the cited artifacts and found:" % (taken.session_id, taken.model),
        "",
        gates.findings_text(taken.findings),
        "",
        remedy,
        "",
        PROVENANCE_FORM,
        "",
        "## The artifacts the verifier opened",
        "",
    ] + ["- `%s`" % path for path in paths])
    return gates.file_writing_ticket(
        # No touch set: REPORT.md and the ledger are written by code, so the correction travels in
        # the result, never as an edit a later render would overwrite.
        project, book, title=CLAIM_TITLE, touches=[], inputs=[document] + paths,
        quality=["Does every claim sentence the verifier could not support now say only what its cited artifacts do?"],
        origin=subject, demo="wayline %s --verify reads this claim again and its verdict passes."
        % ("report" if document == REPORT_PATH else "paper"), body=body,
    )


# --- what the report is rendered from -------------------------------------------------------------


def report_evidence(context):
    """What a writer is given (the paper's, ticket 53): the goals, the findings grouped by claim, the negative results, each with its tags."""
    groups = [
        {"group": key, "findings": [_evidence_item(finding, context.manifest) for finding in members]}
        for key, members in _claim_groups(context).items()
    ]
    negative = [_evidence_item(finding, context.manifest) for finding in context.findings if finding.get("negative")]
    goals = [dict({key: (record["measure"] or {}).get(key) for key in ("metric", "direction", "target", "held_out_split")}, id=record["id"])
             for record in context.goals]
    return {"goals": goals, "groups": groups, "negative": negative}


def _evidence_item(finding, manifest):
    return {"id": finding.get("id"), "ticket": finding.get("ticket"), "text": one_line(finding.get("text")),
            "tags": finding_tags(finding, manifest)}


def finding_lines(item):
    """One evidence item as the paper's writer reads it: the finding, then its tags."""
    return ["- `%s` (ticket %s): %s" % (item["id"], item["ticket"], item["text"]),
            "  tags: %s" % " ".join("`{%s}`" % tag for tag in item["tags"])]


@dataclass
class _Context:
    project: Path
    events: list
    harness: dict
    tickets: dict
    findings: list
    manifest: dict
    goals: list  # the objectives with a measure, any status, from `objectives.json` (ticket 87)
    notes: list
    objectives: list = field(default_factory=list)  # every objective, any status (ticket 90)
    results: list = field(default_factory=list)     # the live results with a current finding (`results.read_results`)
    concerns: list = field(default_factory=list)
    spec: dict = None
    unchecked: dict = field(default_factory=dict)    # section -> the current inherited claims not yet checked
    unverifiable: list = field(default_factory=list)  # the current inherited claims the project could not check


def report_context(project):
    project = Path(project).resolve()
    book = Ledger(project)
    notes = []
    events, _ = book.read_events()
    try:
        harness = read_harness(project)
    except (ProjectError, OSError, ValueError) as failure:
        harness = {}
        notes.append("harness.json could not be read: %s" % failure)
    try:
        by_id = {fields["id"]: fields for fields in tickets.read_tickets(project)}
    except tickets.TicketError as failure:
        by_id = {}
        notes.append("the tickets could not be read: %s" % failure)
    try:
        objectives = read_objectives(project)
    except (ObjectivesUnreadable, OSError) as failure:
        objectives = []
        notes.append(str(failure))
    goals = [record for record in objectives if record.get("measure")]
    context = _Context(project, events, harness, by_id, read_findings(book), read_manifest(book), goals, notes, objectives=objectives)
    from wayline import concerns, results  # both read the ledger's neighbours, which reach this module through the gates
    try:
        context.results = results.read_results(book)
    except (OSError, ValueError) as failure:
        notes.append("the results could not be read: %s" % failure)
    try:
        context.concerns = concerns.read_concerns(book)
    except (OSError, ValueError) as failure:
        notes.append(str(failure))
    try:
        spec = book.read_json("spec.json")
        context.spec = spec if isinstance(spec, dict) else None
    except FileNotFoundError:
        context.spec = None
    except (OSError, ValueError) as failure:
        notes.append("research/spec.json could not be read: %s" % failure)
    for name in sections.INHERITED:
        for item in sections.arrange(sections.section_items(book, name)).current():
            if sections.is_inherited(item) and item.get("standing") == sections.UNCHECKED:
                context.unchecked.setdefault(name, []).append(item)
            elif sections.is_inherited(item) and item.get("standing") == sections.UNVERIFIABLE:
                context.unverifiable.append(item)
    return context


def finding_tags(finding, manifest):
    """A finding's provenance as `res` tags, each run id read from the manifest entry of its artifact.

    A locator whose artifact the manifest does not hold gets the run id `unmanifested`, which is not
    a run id, so the tag is malformed and the linter says so rather than the report hiding it.
    """
    runs = {entry.get("path"): entry.get("run_id") for entry in manifest.get("entries", [])}
    tags = []
    for locator in _cited(finding):
        artifact, _, rest = str(locator).partition("#")
        tags.append("res:%s/%s#%s" % (runs.get(artifact) or "unmanifested", artifact, rest))
    return tags


def tagged_text(text, tags):
    """`text` with `tags` at the end of every sentence of it: a finding's provenance holds for all of it."""
    marks = "".join("{%s}" % tag for tag in tags)
    parts = sentences(text) or ([Sentence(str(text).strip(), ())] if str(text or "").strip() else [])
    return " ".join(part.text + marks for part in parts)


def finding_text(finding, manifest):
    """A finding as the reports print it: its own text when it carries tags, else its text with its provenance as `res` tags."""
    text = one_line(finding.get("text"))
    if ANY_TAG_RE.search(text):
        return text
    return tagged_text(text, finding_tags(finding, manifest))


def finding_line(finding, manifest):
    """One current finding as the general report lists it: its id, marked negative, a replacement's one-line note, its text."""
    marks = []
    if finding.get("negative"):
        marks.append("(negative)")
    if finding.get("replaces"):
        marks.append("(replaces `%s`%s)" % (finding["replaces"], ": %s" % finding["evidence"] if finding.get("evidence") else ""))
    return "- `%s` %s%s" % (finding.get("id"), "".join(mark + " " for mark in marks), finding_text(finding, manifest))


def _claim_groups(context):
    """The positive findings by the claim their ticket traces to (its `origin`), else by their ticket."""
    groups = {}
    for finding in context.findings:
        if finding.get("negative"):
            continue
        owner = context.tickets.get(finding.get("ticket")) or {}
        key = owner.get("origin") or "ticket %s" % finding.get("ticket")
        groups.setdefault(key, []).append(finding)
    return groups


# --- the general report (ticket 90) ---------------------------------------------------------------
#
# Code alone writes every line: what it writes itself (the project, the headlines, the objectives' records, the counts,
# the inferences) sits between the records marks, so the classifier never reads it; the findings are the prose, as their
# tickets recorded them, linted and sampled. Only current findings show.

ACTIVE = ("open", "answered")  # the objectives shown first, in id order; parked ones follow; dropped and reframed get a line
NO_REPORT = "none yet"


def _the_project(context):
    spec = context.spec
    if spec is None:
        return _records(["No spec yet: `research/spec.json` is written by `wayline specify`, and this section opens with its summary."])
    summary = one_line(spec.get("summary"))
    if summary:
        return _records([summary])
    lines = []
    if one_line(spec.get("question")):
        lines.append(one_line(spec.get("question")))
    data = [one_line(item.get("text")) for item in spec.get("data") or [] if isinstance(item, dict) and one_line(item.get("text"))]
    if data:
        lines.extend(["", "The data: %s" % " ".join(data)])
    return _records(lines or ["The spec has no summary, question, or data to say what the project is."])


def _cell(text):
    return one_line(text).replace("|", "\\|")


def _headlines(context):
    if not context.results:
        return _records(["No result yet: a result is one Results heading with its current findings, and the first arrives with a finding."])
    return _records(["- %s %s (%s): %s" % (result.id, result.heading, result.standing,
                                          sections.first_sentence(finding_text(result.current[-1], context.manifest)))
                     for result in context.results])


def _current_report(context, result):
    """The link to a result's current report, the newest `research/reports/R<n>-<version>.md`, or "none yet" (ticket 100 writes them)."""
    folder = context.project / "research" / "reports"
    found = []
    for path in folder.glob("%s-*.md" % result.id) if folder.is_dir() else ():
        version = path.stem[len(result.id) + 1:]
        if version.isdigit():
            found.append((int(version), path.name))
    if not found:
        return NO_REPORT
    name = max(found)[1]
    return "[%s](reports/%s)" % (name[:-3], name)


def _counts(result):
    parts = ["%d current" % len(result.current)]
    if result.negative:
        parts.append("%d negative" % result.negative)
    if result.replaced:
        parts.append("%d replaced" % result.replaced)
    return ", ".join(parts)


def _results_table(context):
    if not context.results:
        return _records(["No result yet."])
    lines = ["| Result | Objectives | Standing | Findings | Current report | Last change |", "|---|---|---|---|---|---|"]
    for result in context.results:
        standing = result.standing if result.standing == "supported" else "**%s**" % result.standing  # a negative result flagged
        lines.append("| %s %s | %s | %s | %s | %s | %s |" % (
            result.id, _cell(result.heading), ", ".join(result.objectives) or "none", standing, _counts(result),
            _current_report(context, result), str(result.changed or "")[:10] or "unknown"))
    return lines


def _result_block(context, result, level="####"):
    lines = ["%s %s. %s (%s)" % (level, result.id, result.heading, result.standing), ""]
    lines.extend(finding_line(finding, context.manifest) for finding in result.current)
    return lines + [""]


def _goal_lines(context, record):
    measure = record["measure"]
    target = measure.get("target")
    lines = ["Goal: `%s`, direction %s, target %s, on the held-out split `%s`." % (
        measure.get("metric"), measure.get("direction"), _number(target) if target is not None else "none", measure.get("held_out_split"))]
    kept = [event.get("payload") or {} for event in context.events if event.get("event") == ledger.PROGRESS
            and (event.get("payload") or {}).get("goal") == record["id"] and (event.get("payload") or {}).get("kept")]
    lines.append("Kept values: %s." % ("; ".join("%s from run `%s` (ticket %s)" % (_number(payload.get("value")), payload.get("run_id"),
                                                                                 payload.get("ticket")) for payload in kept) or "none yet"))
    discarded = _discarded_means(context.events, record["id"])
    if discarded:
        lines.append("Discarded changes: %s." % "; ".join(
            "ticket %s: mean %s against the best %s, standard deviation %s, seeds %s" % (
                payload.get("ticket"), _number(mean), _number(payload.get("best")), _number(payload.get("sd")), payload.get("seeds"))
            for payload, mean in discarded))
    return lines


def _concern_line(concern):
    text = one_line(((concern.get("sources") or [{}])[0]).get("text"))
    status = concern.get("status")
    if status == "answered" and concern.get("answer"):
        status = "answered: %s" % one_line(concern["answer"])
    elif status == "declined" and concern.get("reason"):
        status = "declined: %s" % one_line(concern["reason"])
    return "- %s (%s): %s" % (concern.get("id"), status, text)


def _stop(text):
    """One line of text ending as a sentence does."""
    text = one_line(text)
    return text if not text or text[-1] in ".!?" else text + "."


def _objective_order(record):
    found = re.match(r"^O([1-9][0-9]*)$", str(record.get("id")))
    return int(found.group(1)) if found else 0


def _paragraphs(facts):
    """Records one fact a paragraph, except a list's items, which stay together under the line that opens them."""
    lines = []
    for fact in facts:
        if lines and not (fact.startswith("- ") and (lines[-1].startswith("- ") or lines[-1].endswith(":"))):
            lines.append("")
        lines.append(fact)
    return lines


def _objectives_section(context):
    """Each objective in id order, open and answered first, then parked; dropped and reframed one line each. Returns
    `(lines, shown)`, `shown` the ids of the results it presented."""
    ordered = sorted(context.objectives, key=_objective_order)
    if not ordered:
        return _records(["No objective is recorded yet: `wayline objective add` records one."]), set()
    lines, shown = [], set()
    for record in [item for item in ordered if item.get("status") in ACTIVE] + [item for item in ordered if item.get("status") == "parked"]:
        identifier = record["id"]
        lines.extend(["### %s. %s" % (identifier, one_line(record.get("text"))), ""])
        status, facts = record.get("status"), []
        if status == "answered":
            facts.append("Status: answered. Answer: %s" % _stop(record.get("answer") or "none was given"))
        elif status == "parked":
            facts.append("Status: parked.%s" % (" Why: %s" % _stop(record["answer"]) if record.get("answer") else ""))
        else:
            facts.append("Status: open.")
        if record.get("evidence"):
            facts.append("Evidence: %s." % ", ".join("`%s`" % item for item in record["evidence"]))
        if record.get("measure"):
            facts.extend(_goal_lines(context, record))
        tied = [concern for concern in context.concerns if identifier in (concern.get("objectives") or [])]
        if tied:
            facts.append("Concerns:")
            facts.extend(_concern_line(concern) for concern in tied)
        mine = [result for result in context.results if identifier in result.objectives]
        if not mine:
            facts.append("No result yet.")
        lines.extend(_records(_paragraphs(facts)) + [""])
        for result in mine:
            shown.add(result.id)
            lines.extend(_result_block(context, result))
    gone = [item for item in ordered if item.get("status") in ("dropped", "reframed")]
    if gone:
        rows = ["Dropped and reframed:"]
        for record in gone:
            if record.get("status") == "reframed":
                rows.append("- %s (reframed as %s): %s" % (record["id"], record.get("reframed_as"), one_line(record.get("text"))))
            else:
                rows.append("- %s (dropped): %s%s" % (record["id"], one_line(record.get("text")),
                                                      " %s" % _stop(record["answer"]) if record.get("answer") else ""))
        lines.extend(_records(rows) + [""])
    return (lines[:-1] if lines and lines[-1] == "" else lines), shown


def _beyond(context, shown):
    rest = [result for result in context.results if result.id not in shown]
    if not rest:
        return _records(["Every result serves an objective shown above."])
    lines = []
    for result in rest:
        lines.extend(_result_block(context, result, level="###"))
    return lines[:-1]


def _unchecked_section(context):
    if not context.unchecked:
        return _records(["No inherited claim waits to be checked."])
    return _records(["- %s: %d" % (sections.TITLES[name], len(context.unchecked[name]))
                     for name in sections.INHERITED if context.unchecked.get(name)])


def _inferences(context):
    supported = [result for result in context.results if result.standing == "supported"]
    other = [result for result in context.results if result.standing != "supported"]
    lines = ["Can be inferred:"]
    lines.extend("- %s %s (supported): %d current finding%s." % (result.id, result.heading, len(result.current),
                                                                  "" if len(result.current) == 1 else "s") for result in supported)
    if not supported:
        lines.append("- nothing yet: no result stands supported.")
    lines.extend(["", "Cannot be inferred:"])
    rows = ["- %s %s (%s): %s." % (result.id, result.heading, result.standing,
                                   "its current finding%s negative" % (" is" if len(result.current) == 1 else "s are all")
                                   if result.standing == "negative" else
                                   "%d of its %d current findings %s negative" % (result.negative, len(result.current),
                                                                                  "is" if result.negative == 1 else "are"))
            for result in other]
    unchecked = sum(len(items) for items in context.unchecked.values())
    if unchecked:
        rows.append("- %d inherited claim%s not yet checked by this project's evidence." % (unchecked, "" if unchecked == 1 else "s"))
    rows.extend("- The inherited claim %s could not be checked: %s." % (item.get("id"), one_line(item.get("reason") or "no reason given"))
                for item in context.unverifiable)
    lines.extend(rows or ["- nothing the ledger holds is negative, mixed, or unchecked."])
    lines.extend(["", "Open questions:"])
    questions = ["- %s %s" % (record["id"], one_line(record.get("text"))) for record in sorted(context.objectives, key=_objective_order)
                 if record.get("status") == "open"]
    questions += ["- %s %s" % (concern.get("id"), one_line(((concern.get("sources") or [{}])[0]).get("text")))
                  for concern in context.concerns if concern.get("status") == "open"]
    lines.extend(questions or ["- none: no objective and no concern is open."])
    return _records(lines)


def _body(context):
    objectives, shown = _objectives_section(context)
    parts = (_the_project(context), _headlines(context), _results_table(context), objectives, _beyond(context, shown),
             _unchecked_section(context), _inferences(context))
    lines = []
    for number, part in enumerate(parts, start=1):
        lines.extend(["## %d. %s" % (number, SECTIONS[number - 1]), ""] + list(part) + [""])
    return "\n".join(lines)


def _banner(context, result, notes, edited):
    lines = [
        "# Report: %s" % context.project.name,
        "",
        RECORDS_BEGIN,
        "Code renders this general report from the ledger alone, after every integration and at the tick, and never reads it "
        "back: an edit of it is kept in git as it stood and is not taken in. It was rendered from `research/journal.jsonl` "
        "(%d events), `findings.jsonl`, `results.json`, `objectives.json`, `concerns.json`, `passages.jsonl`, `spec.json`, "
        "and `manifest.json`. The provenance linter %s: %d claim sentence(s), %d tagged." % (
            len(context.events), "passed" if result.passed else "FAILED", result.claims, result.tagged),
        "",
        "What wayline did, what it decided for you, and what waits on you are in [ACCOUNT.md](ACCOUNT.md).",
    ]
    if edited is not None:
        when, commit = edited
        lines.extend(["", "%s was edited by hand (noticed %s). The edit was kept as it stood (%s) and is not taken in: the report "
                      "is rendered from the ledger, and what you want it to say goes to the conversation." % (
                          REPORT, (str(when)[:16].replace("T", " ") + "Z") if when else "at an earlier render",
                          "commit `%s`" % commit[:12] if commit else "it could not be committed")])
    if result.problems:
        lines.extend(["", "The linter failed on these sentences; the report does not pass until each one ends with a tag that resolves, or is rewritten:", ""])
        # Tags are taken off the sentence and the tag is named without its braces, so that a tag
        # the linter refused is not rendered as a citation in the report that refused it.
        lines.extend("- `%s` %s (%s%s)" % (problem["problem"], one_line(strip_tags(problem["sentence"])),
                                           "tag `%s`: " % problem["tag"] if problem["tag"] else "", problem["detail"])
                     for problem in result.problems)
    if context.notes or notes:
        lines.append("")
        lines.extend("- note: %s" % note for note in context.notes + list(notes))
    lines.extend([RECORDS_END, "", ""])
    return "\n".join(lines)


def _discarded_means(events, goal):
    """Each `discarded` payload of the goal `goal` (its id), with its change's mean: the unkept `progress` of its ticket just before it.

    The conductor journals an evaluation's `progress` and then its `discarded` (ticket 39), so pairing each
    discard with the reading before it gives every attempt of a ticket its own mean.
    """
    last, pairs = {}, []
    for event in events:
        payload = event.get("payload") or {}
        if payload.get("goal") != goal:
            continue
        if event.get("event") == ledger.PROGRESS and not payload.get("kept"):
            last[payload.get("ticket")] = payload.get("value")
        elif event.get("event") == ledger.DISCARDED:
            pairs.append((payload, last.pop(payload.get("ticket"), None)))
    return pairs


# --- the render -----------------------------------------------------------------------------------


@dataclass
class Rendered:
    """One render: where `REPORT.md` was written, its sha256, the linter's result, the notes, and the edit it kept."""

    path: Path
    sha256: str
    lint: Lint
    notes: list = field(default_factory=list)
    edited: object = None  # the commit an edit by hand was kept in, "" when it could not be committed, None for no edit


def _last_edit(events):
    """`(when, commit)` of the general report's last render that noticed an edit by hand, or None."""
    for event in reversed(events):
        payload = event.get("payload") or {}
        if event.get("event") == ledger.REPORT_RENDERED and not payload.get("report") and "edited" in payload:
            return event.get("ts"), payload.get("edited") or ""
    return None


def render_report(project, *, harness_root=HARNESS_ROOT, policy=None, offline=False):
    """Render `research/REPORT.md`, the general report, from the ledger alone, lint it, write it, and journal `report_rendered`.

    Code writes every line (decision 17; ticket 90): no writer session drafts any of it. The classifier is asked about
    the findings' sentences the cache does not hold, unless `offline`, which launches nothing at all and is how the
    conductor renders after every integration and the tick renders when the journal moved. The linter runs on the
    tagged text, and the tags are rendered as citations in the file written. A report that fails the linter is
    written all the same, with the offending sentences at its top.

    The edit rule: an edit of the file since the last render (its hash against the last `report_rendered`) is
    committed as it stood, journaled as `edited` on this render, listed in the banner from then on, and never taken in.
    The account renders in the same pass, then the outline and References; a merge taken on the outline's proposals is made first.
    """
    project = Path(project).resolve()
    book = Ledger(project)
    from wayline import account, outline  # the account reads the decisions module, which imports this one through the gates
    notes = []
    try:
        outline.take_marks(project)  # a merge the owner took on the outline's proposals is in the report it renders
    except (ValueError, OSError) as failure:
        notes.append("the marks on the outline's proposals could not be taken: %s" % failure)
    if not offline:
        # The classifier is a session: it runs before the lock, so no other writer of the ledger waits on it, and the
        # render under the lock reads what it cached.
        texts = [sentence.text for sentence in prose_sentences(_body(report_context(project)))]
        try:
            classify(project, texts, harness_root=harness_root, policy=policy)
        except UsageLimited as refused:
            notes.append("%s; the sentences it did not reach are unclassified" % refused)
    with book.lock():
        context = report_context(project)
        body = _body(context)
        result = lint(project, body, read_claims_cache(book))
        edited = account.take_edit(project, REPORT, None, context.events)
        stamp = now_ts()  # the edit is noticed at the time its render is journaled, which later banners read back
        noticed = (stamp, edited) if edited is not None else _last_edit(context.events)
        path = book.write_markdown(REPORT, render_citations(_banner(context, result, notes, noticed) + body))
        digest = sha256_of(path)
        payload = {"sha256": digest, "claims": result.claims, "tagged": result.tagged, "linter_pass": result.passed}
        if edited is not None:
            payload["edited"] = edited or None
        book.append_event(ledger.REPORT_RENDERED, payload, ts=stamp)
    # The account renders in the same pass (decision 17; ticket 89): what wayline did, beside the research.
    try:
        account.render_account(project)
    except (ValueError, OSError) as failure:
        notes.append("ACCOUNT.md could not be rendered: %s" % failure)
    # And the outline (ticket 104): the shape of the paper, from the same ledger, with the owner's edit of it taken in.
    try:
        outline.render_outline(project)
    except (ValueError, OSError) as failure:
        notes.append("OUTLINE.md could not be rendered: %s" % failure)
    # And References (ticket 105): a retry the tick ran may have found a work, or a flag given up, with no section changed.
    from wayline import references  # the references module imports this one
    try:
        references.render_references(project)
    except (ValueError, OSError) as failure:
        notes.append("References could not be rendered: %s" % failure)
    return Rendered(path, digest, result, notes, edited)


def lint_report(project):
    """The linter on the `REPORT.md` on disk, with the classes the cache holds: what `wayline report` last wrote."""
    project = Path(project).resolve()
    text = (project / "research" / REPORT).read_text(encoding="utf-8")
    return lint(project, restore_tags(text), read_claims_cache(project))


def report_command(args):
    """`wayline report [--project <path>] [--offline] [--verify] [--json]`."""
    parser = argparse.ArgumentParser(prog="wayline report", description="render research/REPORT.md, the general report, from the ledger and lint its claims")
    parser.add_argument("--project", help="the project (default: the active one)")
    parser.add_argument("--offline", action="store_true",
                        help="launch no session: nothing new is classified, and an untagged sentence the cache does not cover fails the linter")
    parser.add_argument("--verify", action="store_true",
                        help="after a passing render, take a verdict on a sample of the tagged claims (10 percent, at least ten, every difficulty-5 claim)")
    parser.add_argument("--json", action="store_true", help="print the outcome as JSON")
    options, code = parse_args(parser, args)
    if options is None:
        return code
    try:
        project = find_project(options.project)
    except ProjectError as failure:
        print("wayline report: %s" % failure, file=sys.stderr)
        return 2
    try:
        rendered = render_report(project, offline=options.offline)
        verified = verify_claims(project) if options.verify and rendered.lint.passed else None
        if verified and verified["fell_back"]:
            # The account lists the verdicts taken by fallback from the journal, which the sampling has just added to;
            # nothing the classifier read changed, so the render launches nothing.
            rendered = render_report(project, offline=True)
    except (ProvenanceError, gates.GateError, worker.LaunchError, worker.RoleError, tickets.TicketError) as failure:
        print("wayline report: %s" % failure, file=sys.stderr)
        return 1
    outcome = {
        "report": str(rendered.path), "sha256": rendered.sha256, "linter_pass": rendered.lint.passed,
        "claims": rendered.lint.claims, "tagged": rendered.lint.tagged, "problems": rendered.lint.problems,
        "notes": rendered.notes, "verify": verified,
    }
    if options.json:
        print(json.dumps(outcome, ensure_ascii=False, indent=2))
    else:
        print(_render_outcome(outcome, options.verify))
    failed = not rendered.lint.passed or bool(verified and verified["failed"])
    return 1 if failed else 0


def _render_outcome(outcome, asked_to_verify):
    lines = ["report    %s" % outcome["report"],
             "linter    %s: %d claim sentence(s), %d tagged" % ("pass" if outcome["linter_pass"] else "FAIL", outcome["claims"], outcome["tagged"])]
    for problem in outcome["problems"]:
        lines.append("  %-15s %s" % (problem["problem"], one_line(problem["sentence"])))
        lines.append("  %-15s %s" % ("", problem["detail"]))
    for note in outcome["notes"]:
        lines.append("note      %s" % note)
    verified = outcome["verify"]
    if verified is not None:
        lines.append("verifier  %d of %d tagged claims sampled: %d passed, %d failed, %d already had a verdict%s%s" % (
            verified["sampled"], verified["claims"], len(verified["passed"]), len(verified["failed"]), verified["already_verdicted"],
            ", %d judged on Opus in place of Fable" % len(verified["fell_back"]) if verified.get("fell_back") else "",
            ", %d wait for Fable's weekly window" % len(verified["waiting"]) if verified.get("waiting") else ""))
        if verified["tickets"]:
            lines.append("          writing ticket(s) filed: %s" % ", ".join(map(str, verified["tickets"])))
    elif asked_to_verify:
        lines.append("verifier  not run: the linter failed, and a claim that does not resolve is not one to sample")
    return "\n".join(lines)


# --- shared helpers -------------------------------------------------------------------------------


def _records(lines):
    return [RECORDS_BEGIN] + list(lines) + [RECORDS_END]


def one_line(text):
    return " ".join(str(text if text is not None else "").split())


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _number(value):
    if isinstance(value, float):
        return ("%.4f" % value).rstrip("0").rstrip(".")
    return str(value)


def joined(*parts):
    return "\n\n".join(part.strip("\n") for part in parts if part and part.strip()) + "\n"


def session_dir(project, name):
    """`research/sessions/<name>/<n>`, the first free number: every classifier and writer session keeps its stream."""
    base = Path(project) / "research" / "sessions" / name
    number = 1
    while (base / str(number)).exists():
        number += 1
    return base / str(number)


def _role_tier(policy, name):
    entry = ((policy or {}).get("roles") or {}).get(name) or {}
    if not entry.get("model") or not entry.get("effort"):
        raise ProvenanceError("policy.roles gives no model and effort for the %s" % name)
    return entry["model"], entry["effort"]


def structured_request(project, role, policy, harness_root, prompt, schema, budget, run_dir, read_only=False):
    """The launch of a session that returns one structured answer and writes nothing.

    Launched like a verifier: without `TICKET_TOUCHES`, so the touch-set guard blocks every write
    and the command guard every deletion, and without `TICKET_ACCEPTANCE_FILE`, so the stop guard
    lets it stop.
    """
    model, effort = _role_tier(policy, role.name)
    if model == pacing.FABLE and fable_falls_back(project):
        model = pacing.OPUS  # Fable's weekly window is spent and the consent is auto: the same effort, on Opus (decision 15)
    sizes = (policy.get("budget") or {}).get(budget) or {}
    allowed, disallowed = list(role.allowed_tools), list(role.disallowed_tools)
    if read_only:
        allowed = [tool for tool in allowed if tool in READ_ONLY_TOOLS]
        disallowed.extend(tool for tool in WRITE_TOOLS if tool not in disallowed)
    return worker.LaunchRequest(
        role=role.name, model=model, effort=effort, prompt=prompt,
        agent_json=role.agent_json(model, effort, sizes.get("max_turns")),
        allowed_tools=allowed, disallowed_tools=disallowed,
        settings_path=gates.write_worker_settings(run_dir / "settings.json", harness_root),
        add_dirs=[str(Path(project))] if read_only else [],
        cwd=Path(project), env=gates.verdict_env(project, run_dir),
        schema_path=Path(harness_root).resolve() / "schemas" / (schema + ".json"),
        max_minutes=sizes.get("max_minutes"),
    )


def _launch_structured(request, problem_of, what):
    """Launch, check the answer, resume once with the reason when it is unusable, and raise when it still is."""
    envelope = worker.launch(request)
    raise_if_refused(envelope, what, request.model)
    problem = problem_of(envelope)
    if problem is not None and envelope.session_id:
        envelope = worker.resume(request, envelope.session_id, RESUME_STRUCTURED % problem)
        raise_if_refused(envelope, what, request.model)
        problem = problem_of(envelope)
    if problem is not None:
        raise ProvenanceError("the %s's answer could not be used: %s" % (what, problem))
    return envelope


def raise_if_refused(envelope, what, model=None):
    """Raise `UsageLimited` for a session that returned nothing because a usage window refused it.

    docs/verification/m5.md: the live writer on fable came back after one turn with
    `status: rejected` on the `seven_day_overage_included` window and no structured output. A
    resume would be refused the same way, and the message the answer "could not be used" would
    send the owner looking for a bug in a prompt. Every form of a refusal counts (decision 15): the
    rejected event, a 429, the "hit your" or "reached your" limit text, a subagent's failed task.
    """
    if envelope.valid:
        return
    limit = pacing.hit_limit(envelope, worker.stderr_of(envelope), datetime.now(timezone.utc).timestamp(), model=model)
    if limit is None:
        return
    refused = [event for event in envelope.rate_limit_events if event.status == "rejected" and event.rate_limit_type]
    window = (refused[-1].rate_limit_type if refused
              else pacing.FABLE_LIMIT_TYPE if limit.model == pacing.FABLE else limit.window)
    until = (datetime.fromtimestamp(limit.resets_at, timezone.utc).strftime("%Y-%m-%d %H:%MZ")
             if limit.resets_at else "an unknown time")
    raise UsageLimited("the %s was refused by the usage limit on the %s window until %s" % (what, window, until), limit)


def schema_problem(envelope, schema):
    if not envelope.valid:
        return "; ".join(envelope.errors) or "the session returned no structured answer"
    try:
        check(envelope.structured_output, load_schema(schema), name=schema)
    except ValidationError as failure:
        return str(failure)
    return None
