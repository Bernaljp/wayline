"""The manifest and findings provenance (Implementation Decisions 6 and 2). Built by ticket 18.

`results/` lives outside git (Implementation Decisions 1 already ignores it); every artifact a
finding will ever cite is hashed into `research/manifest.json` first, by `register_artifact`,
so `add_finding` can refuse a finding whose provenance points anywhere else. Findings are
numbered sequentially in `research/findings.jsonl`; `render_findings` renders `findings.md`
from them, grouped by ticket, negative results marked, and `add_finding` calls it after every
change so the two files never drift.

Ticket 40 added the rest of Implementation Decisions 11 (C8): the claim markup
(`{res:<run-id>/<artifact>#<locator>}` and `{ref:<slug>#<locator>}` at the end of a claim
sentence), the sentence classifier and its cache, the linter (Type-A) that resolves every tag
against the manifest and the knowledge base, the verifier's sample of tagged claims (Type-B,
through the gate of `wayline.gates`), the writer's prose, and `REPORT.md` itself, which
`render_report` renders from the journal, the findings, the tickets, and the goals of
`objectives.json` (ticket 87: `GOAL.json` retired). The report lives here because decision 1's module list has no `report` module and BRIEF 10 gives the writer
"role + provenance.py".
"""

import argparse
import hashlib
import json
import math
import random
import re
import subprocess
import sys
from collections import Counter, namedtuple
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from wayline import HARNESS_ROOT, POLICY_PATH, gates, ledger, pacing, sections, tickets, worker
from wayline.cli import parse_args
from wayline.jsonschema import ValidationError, check, load_schema
from wayline.ledger import Ledger, now_ts
from wayline.project import NEEDS_HUMAN_NOTES, ProjectError, fable_falls_back, find_project, policy_for, read_harness
from wayline.objectives import ObjectivesUnreadable, read_objectives

__all__ = [
    "ProvenanceError", "MANIFEST", "FINDINGS", "FINDINGS_MD", "RUN_ID_RE",
    "sha256_of", "read_manifest", "manifest_paths", "register_artifact",
    "read_findings", "current_findings", "add_finding", "render_findings",
    "commit_threshold_bytes", "oversized_tracked_files",
    "TAG_RE", "RES_TAG_RE", "REF_TAG_RE", "REF_IDENTIFIER_TAG_RE", "Sentence", "sentences", "parse_tag", "ref_slug", "identifier_index", "strip_tags",
    "REPORT", "CLAIMS_CACHE", "PROSE_CACHE", "SECTIONS", "SENTENCE_CLASSES", "RECORDS_BEGIN", "RECORDS_END",
    "UsageLimited", "Lint", "Claim", "Rendered", "prose_sentences", "sentence_hash", "render_citations", "restore_tags",
    "read_claims_cache", "classify", "lint", "lint_report", "tagged_claims", "sample_size", "sample_claims",
    "claim_subject", "claim_paths", "verify_claims", "report_evidence", "draft_prose", "finding_tags",
    "tagged_text", "render_report", "report_command",
]

MANIFEST = "manifest.json"
FINDINGS = "findings.jsonl"
FINDINGS_MD = "findings.md"

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
_BOUNDARY = re.compile(r"""[.!?]["')\]]*(?:\s*\{(?:res|ref|doc):[^{}]+\})*""" + _MARK + r"""?(?=\s+["'(\[A-Z]|\s*$)""")
_ANY_TAG = re.compile(r"\{(?:res|ref|doc):[^{}]+\}|" + _MARK)

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


def _next_finding_id(findings):
    highest = 0
    for finding in findings:
        match = re.match(r"^f-(\d+)$", finding.get("id", ""))
        if match:
            highest = max(highest, int(match.group(1)))
    return "f-%04d" % (highest + 1)


def _locators(provenance):
    locators = [provenance] if isinstance(provenance, str) else list(provenance)
    if not locators:
        raise ProvenanceError("a finding needs at least one provenance locator")
    return locators


def _cited(finding):
    """A written finding's locators: `add_finding` writes a list, and the conductor one locator per finding."""
    provenance = finding.get("provenance")
    if isinstance(provenance, str):
        return [provenance] if provenance else []
    return list(provenance or [])


def add_finding(project_or_ledger, text, provenance, ticket, negative=False, heading=None, replaces=None, objectives=()):
    """Append one finding to `findings.jsonl`, journal `finding`, and re-render `findings.md` and the Results section.

    `replaces` names the id of an earlier finding this one replaces: that one is no longer current,
    and `current_findings` leaves it out (ticket 106).

    `provenance` is one locator or a list of them, each `<manifested path>#<locator>`. Refused
    (raises `ProvenanceError`, without writing anything) when a locator carries no `#<locator>`
    half or its artifact half is not a path in `manifest.json`; register the artifact first. The
    caller (the conductor, for a worker's finding) journals the refusal on the ticket itself.
    A finding is a Results passage (decision 17): `heading` is the one it stands under, `replaces`
    the finding a scope-down narrows (refused when no finding has that id), and `objectives` its ticket's.
    """
    book = _ledger(project_or_ledger)
    locators = _locators(provenance)
    with book.lock():
        manifested = manifest_paths(read_manifest(book))
        for locator in locators:
            artifact, sep, rest = locator.partition("#")
            if not sep or not artifact or not rest:
                raise ProvenanceError("provenance %r must be <path>#<locator>, with both halves non-empty" % (locator,))
            if artifact not in manifested:
                raise ProvenanceError("provenance %r cites %r, which is not in manifest.json; register_artifact it first" % (locator, artifact))
        findings = read_findings(book)
        finding = sections.file_finding(book, {
            "id": _next_finding_id(findings),
            "ticket": ticket,
            "text": text,
            "provenance": locators,
            "negative": bool(negative),
            "heading": heading,
            "replaces": replaces,
            "objectives": list(objectives or []),
            "ts": now_ts(),
        })
        render_findings(book)
    return finding


def render_findings(project_or_ledger):
    """Rewrite `findings.md` from `findings.jsonl`, grouped by ticket, negative results marked.

    Called by `add_finding` after every change; also callable on its own to rebuild the file
    (a fresh project, or a `findings.jsonl` edited by hand).
    """
    book = _ledger(project_or_ledger)
    findings = read_findings(book)
    lines = ["# Findings", ""]
    if not findings:
        lines.append("None yet.")
    else:
        by_ticket = {}
        for finding in findings:
            by_ticket.setdefault(finding.get("ticket"), []).append(finding)
        for ticket in sorted(by_ticket, key=lambda value: (value is None, value)):
            lines.append("## Ticket %s" % (ticket if ticket is not None else "(none)"))
            lines.append("")
            for finding in by_ticket[ticket]:
                mark = " (negative)" if finding.get("negative") else ""
                locators = ", ".join(_cited(finding))
                lines.append("- `%s`%s %s (%s)" % (finding["id"], mark, finding["text"], locators))
            lines.append("")
    return book.write_markdown(FINDINGS_MD, "\n".join(lines))


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
    found, start = [], 0
    for boundary in _BOUNDARY.finditer(text):
        found.append(text[start:boundary.end()])
        start = boundary.end()
    found.append(text[start:])
    result = []
    for chunk in found:
        body = chunk.strip()
        if body:
            result.append(Sentence(body, tuple("%s:%s" % (kind, rest) for kind, rest in TAG_RE.findall(body))))
    return result


def parse_tag(tag):
    """One tag as `(kind, parts)`, or `(kind, None)` when it is malformed; `(None, None)` for a non-tag.

    `parts` is the named groups of the tag's shape: a `res` tag resolves to a run id, an artifact
    and a locator, a `ref` tag to a slug and a locator. A tag whose halves are there but empty is
    malformed, which is the case the linter refuses and the guidelines check reports.
    """
    kind, _, rest = str(tag or "").partition(":")
    if kind not in ("res", "ref") or not rest:
        return None, None
    if kind == "ref":
        named = REF_IDENTIFIER_TAG_RE.match(rest)
        if named is not None:
            prefix, _, value = named.group("identifier").partition(":")
            return kind, {"identifier": "%s:%s" % (prefix.lower(), value), "locator": named.group("locator")}
    pattern = RES_TAG_RE if kind == "res" else REF_TAG_RE
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
PROSE_CACHE = ".cache/report_prose.json"
CLASSIFIER = "classifier"
WRITER = "writer"
CLASSES_SCHEMA = "claim_classes"
PROSE_SCHEMA = "report_prose"

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

# One `haiku --effort low` call classifies at most this many sentences.
CLASSIFY_BATCH = 40

# Code-rendered listings sit between these two lines. They are records of the journal, whose
# provenance is the journal itself, so the classifier never reads them and the linter never checks
# them; the prose around them (the findings and the writer's paragraphs) is what C8 is about.
RECORDS_BEGIN = "<!-- wayline:records -->"
RECORDS_END = "<!-- /wayline:records -->"

# The sections of Implementation Decisions 11, in its order.
SECTIONS = (
    "Decisions by the decider",
    "Open decision tickets and tickets that need a human",
    "Goal trajectory",
    "Findings by claim",
    "Tickets closed: done and accepted",
    "Judged on Opus while Fable was spent",
    "Negative results",
    "Papers by level, and promotions not read in full",
    "Not pursued",
    "Proposed global harness changes",
    "Resources spent",
    "The run's events",
)
SUPPLEMENTARY = "Supplementary references"

# A session that drafts or classifies reads at most; it writes nothing under `research/`.
READ_ONLY_TOOLS = ("Read", "Glob", "Grep")
WRITE_TOOLS = ("Edit", "Write", "NotebookEdit", "Bash")

# The events the report lists one by one under "the run's events"; the rest are counted.
MILESTONES = ("run_started", "run_ended", "phase", "paused", "unpaused", "stall", "switched", "pinned", "tagged")

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

_TAGS_AT_END = re.compile(r"(?:\{(?:res|ref):[^{}]+\}\s*)+$")
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
    """What the linter found in one document: whether it passes, the counts, and every problem.

    A problem is `{sentence, problem, tag, detail}`, `problem` one of the five kinds above. `claims`
    counts the sentences classified as claims and `tagged` those of them that end with a tag.
    """

    passed: bool
    claims: int
    tagged: int
    unclassified: int
    problems: list = field(default_factory=list)


class _Resolver:
    """What a tag resolves against: `manifest.json` for `res`, a verified dossier and a node for `ref`."""

    def __init__(self, project):
        self.project = Path(project)
        entries = read_manifest(self.project).get("entries", [])
        self.manifested = {(entry.get("run_id"), entry.get("path")) for entry in entries}
        self._index = None

    def index(self):
        if self._index is None:
            self._index = identifier_index(self.project)
        return self._index

    def problem(self, tag):
        if tag.startswith("res:unmanifested/"):
            return UNRESOLVED_RES, "%s is not in manifest.json" % tag[len("res:unmanifested/"):].partition("#")[0]
        kind, parts = parse_tag(tag)
        if kind is None or parts is None:
            return MALFORMED_TAG, "`%s` is neither `res:<run-id>/<artifact>#<locator>` nor `ref:<slug>#<locator>`" % tag
        if kind == "res":
            if (parts["run_id"], parts["artifact"]) in self.manifested:
                return None
            runs = sorted(run for run, path in self.manifested if path == parts["artifact"])
            if runs:
                return UNRESOLVED_RES, "manifest.json has %s from run %s, not from run %s" % (parts["artifact"], ", ".join(runs), parts["run_id"])
            return UNRESOLVED_RES, "%s is not in manifest.json" % parts["artifact"]
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


def lint(project, markdown, classes):
    """The Type-A provenance check of one tagged document against a project's ledger.

    Every tag in the prose must resolve: a `res` tag to the run and the path of an entry in
    `manifest.json`, a `ref` tag to a reference whose `dossier.json` says `existence: verified` and
    that has a knowledge-base node. Every sentence `classes` calls a claim must end with at least
    one tag. An untagged sentence `classes` does not cover fails too, because nothing then says it
    is not a claim. Records (between `RECORDS_BEGIN` and `RECORDS_END`) are not read.
    """
    resolver = _Resolver(project)
    problems, claims, tagged, unclassified = [], 0, 0, 0
    for sentence in prose_sentences(markdown):
        for tag in sentence.tags:
            found = resolver.problem(tag)
            if found is not None:
                problems.append({"sentence": sentence.text, "problem": found[0], "tag": tag, "detail": found[1]})
        if not strip_tags(sentence.text):
            continue
        kind = classes.get(sentence_hash(sentence.text))
        ends_tagged = bool(_TAGS_AT_END.search(sentence.text))
        if kind == CLAIM:
            claims += 1
            if ends_tagged:
                tagged += 1
            else:
                detail = ("its tags are inside it; a claim sentence ends with them" if sentence.tags
                          else "a claim sentence ends with at least one provenance tag")
                problems.append({"sentence": sentence.text, "problem": UNTAGGED_CLAIM, "tag": None, "detail": detail})
        elif kind is None and not ends_tagged:
            unclassified += 1
            problems.append({"sentence": sentence.text, "problem": UNCLASSIFIED, "tag": None,
                             "detail": "not classified yet, so nothing says it is not a claim; render without --offline"})
    return Lint(passed=not problems, claims=claims, tagged=tagged, unclassified=unclassified, problems=problems)


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
        if classes.get(digest) != CLAIM or not _TAGS_AT_END.search(sentence.text):
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
    writer_model = prose_author or _prose_author(book, policy)
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


def _prose_author(book, policy):
    """The model the cached prose was written on: Opus when the writer fell back (decision 15), else `policy.roles.writer`'s."""
    try:
        cached = book.read_json(PROSE_CACHE)
    except (OSError, ValueError):
        cached = None
    if isinstance(cached, dict) and cached.get("fallback_from") == pacing.FABLE:
        return pacing.OPUS
    return _role_tier(policy, WRITER)[0]


def _finding_authors(context):
    """`{sentence hash: model alias}` for every sentence the report renders from a finding."""
    models = {}
    for event in context.events:
        if event.get("event") == ledger.TICKET_LAUNCHED:
            payload = event.get("payload") or {}
            models[payload.get("ticket")] = payload.get("model")
    authors = {}
    for finding in context.findings:
        for sentence in prose_sentences(_finding_item(finding, context.manifest)):
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


# --- the writer -----------------------------------------------------------------------------------


def report_evidence(context):
    """What the writer is given: the goals, the findings grouped by claim, the negative results, each with its tags."""
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


def draft_prose(project, evidence, *, harness_root=HARNESS_ROOT, policy=None, offline=False):
    """The writer's prose for `evidence`, as `(prose, note)`: from the cache when the evidence is unchanged.

    One `writer` session through the launcher, read-only, on the model `policy.roles.writer` gives,
    or on Opus at the same effort while Fable's weekly window is spent under the fallback consent
    `auto` (decision 15), with the `report_prose` schema; a group the prompt did not name is dropped. The answer is cached
    under `research/.cache/report_prose.json` with the hash of the evidence, so a render that changes
    nothing the writer read launches nothing. `offline` launches nothing: prose drafted for other
    evidence is not used, and `note` says why the report has none.
    """
    project = Path(project).resolve()
    book = Ledger(project)
    if not evidence["groups"] and not evidence["negative"]:
        return {"groups": [], "negative_results": ""}, None
    key = hashlib.sha256(json.dumps(evidence, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    try:
        cached = book.read_json(PROSE_CACHE)
    except (OSError, ValueError):
        cached = None
    if isinstance(cached, dict) and cached.get("input_sha256") == key and isinstance(cached.get("prose"), dict):
        # Prose that failed the linter is served all the same; `render_report` resumes its writer when it may launch.
        return cached["prose"], None
    if offline:
        return None, ("the writer's prose is from findings that have changed since, so it is left out; "
                      "no writer session was launched" if cached else
                      "the writer's prose has not been drafted; no writer session was launched")
    policy = policy_for(project, harness_root) if policy is None else policy
    role = worker.read_role(WRITER, harness_root, project)
    request = structured_request(project, role, policy, harness_root, _writer_prompt(role, evidence), PROSE_SCHEMA, "medium",
                       session_dir(project, WRITER), read_only=True)
    try:
        envelope = _launch_structured(request, lambda answer: schema_problem(answer, PROSE_SCHEMA), "writer")
    except UsageLimited as refused:
        return None, "%s, so the report is rendered without the writer's prose" % refused
    return _keep_prose(book, policy, request, envelope, evidence, key), None


def _keep_prose(book, policy, request, envelope, evidence, key, session_id=None):
    """The prose of the writer's `envelope`, cached with no linter result yet."""
    returned = envelope.structured_output
    named = {group["group"] for group in evidence["groups"]}
    prose = {
        "groups": [group for group in returned["groups"] if group["group"] in named],
        "negative_results": returned["negative_results"] if evidence["negative"] else "",
    }
    fell_back = request.model != _role_tier(policy, WRITER)[0]
    book.write_json(PROSE_CACHE, {"schema_version": 1, "input_sha256": key, "session_id": envelope.session_id or session_id,
                                  "model": envelope.model, "fallback_from": pacing.FABLE if fell_back else None,
                                  "prose": prose, "lint": None})
    return prose


RESUME_PROSE = (
    "The report was rendered from your paragraphs and the provenance linter failed on the sentences below. "
    "Return every paragraph again, through the structured output, with each one answered: a claim sentence ends "
    "with the tags of the findings it rests on, copied exactly from the evidence. An `untagged_claim` is a sentence "
    "the classifier read as a claim, and it reads a statement of the study's scope or limits as one too: rewording "
    "it rarely changes that. End it with a tag, or leave the sentence out.\n\n%s"
)


def writer_failures(result, prose):
    """The linter's problems on sentences of the writer's `prose`, one line each: the sentence and why."""
    if not prose:
        return []
    written = {sentence_hash(sentence.text) for text in [group["text"] for group in prose["groups"]]
               + [prose["negative_results"]] for sentence in prose_sentences(text)}
    return ["- `%s` %s (%s%s)" % (problem["problem"], one_line(problem["sentence"]),
                                  "tag `%s`: " % problem["tag"] if problem["tag"] else "", problem["detail"])
            for problem in result.problems
            # An unclassified sentence is the classifier's gap, which a redraft does not close.
            if problem["problem"] != UNCLASSIFIED and sentence_hash(problem["sentence"]) in written]


def _record_prose_lint(book, failures):
    """Record beside the cached prose whether the linter passed it, and on what."""
    try:
        cached = book.read_json(PROSE_CACHE)
    except (OSError, ValueError):
        return
    if isinstance(cached, dict):
        cached["lint"] = {"pass": not failures, "failures": failures}
        book.write_json(PROSE_CACHE, cached)


def redraft_prose(project, evidence, failures, *, harness_root=HARNESS_ROOT, policy=None):
    """The writer's session resumed with the linter's `failures`, its new prose cached; a fresh launch when none is on record."""
    project = Path(project).resolve()
    book = Ledger(project)
    policy = policy_for(project, harness_root) if policy is None else policy
    try:
        cached = book.read_json(PROSE_CACHE)
    except (OSError, ValueError):
        cached = None
    session_id = cached.get("session_id") if isinstance(cached, dict) else None
    key = hashlib.sha256(json.dumps(evidence, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    role = worker.read_role(WRITER, harness_root, project)
    request = structured_request(project, role, policy, harness_root, _writer_prompt(role, evidence), PROSE_SCHEMA, "medium",
                       session_dir(project, WRITER), read_only=True)
    if not session_id:
        envelope = _launch_structured(request, lambda answer: schema_problem(answer, PROSE_SCHEMA), "writer")
        return _keep_prose(book, policy, request, envelope, evidence, key)
    envelope = worker.resume(request, session_id, RESUME_PROSE % "\n".join(failures))
    raise_if_refused(envelope, "writer", request.model)
    problem = schema_problem(envelope, PROSE_SCHEMA)
    if problem is not None and envelope.session_id:
        envelope = worker.resume(request, envelope.session_id, RESUME_STRUCTURED % problem)
        raise_if_refused(envelope, "writer", request.model)
        problem = schema_problem(envelope, PROSE_SCHEMA)
    if problem is not None:
        raise ProvenanceError("the writer's answer could not be used: %s" % problem)
    return _keep_prose(book, policy, request, envelope, evidence, key, session_id)


def finding_lines(item):
    """One evidence item as the writer reads it, the report's prose and the paper's alike: the finding, then its tags."""
    return ["- `%s` (ticket %s): %s" % (item["id"], item["ticket"], item["text"]),
            "  tags: %s" % " ".join("`{%s}`" % tag for tag in item["tags"])]


def _writer_prompt(role, evidence):
    lines = [
        "# The report you are writing prose for",
        "",
        "Code renders every section of `research/REPORT.md` from the ledger. You write two kinds of "
        "paragraph and nothing else: one for each claim group below, saying what its findings "
        "establish together, and one on the negative results. The findings themselves are listed "
        "under your paragraphs as they were recorded, so do not copy them out one by one.",
        "",
    ]
    for goal in evidence.get("goals") or []:
        lines.extend(["The goal %s: `%s`, direction %s, target %s, on the held-out split `%s`." % (
            goal.get("id"), goal.get("metric"), goal.get("direction"), goal.get("target"), goal.get("held_out_split")), ""])
    lines.extend([
        "# The evidence",
        "",
        "Each finding carries the tags that trace it. A claim sentence of yours ends with the tags of "
        "the findings it rests on, copied exactly.",
        "",
    ])
    for group in evidence["groups"]:
        lines.extend(["## Group `%s`" % group["group"], ""])
        for item in group["findings"]:
            lines.extend(finding_lines(item))
        lines.append("")
    lines.extend(["## Negative results", ""])
    if evidence["negative"]:
        for item in evidence["negative"]:
            lines.extend(finding_lines(item))
    else:
        lines.append("None was recorded: return the empty string for `negative_results`.")
    lines.extend(["", "Return the paragraphs through the structured output; the harness writes them into the report."])
    return joined("\n".join(lines), role.protocol, worker.schema_section("# The prose", PROSE_SCHEMA))


# --- what the report is rendered from -------------------------------------------------------------


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
        goals = [record for record in read_objectives(project) if record.get("measure")]
    except (ObjectivesUnreadable, OSError) as failure:
        goals = []
        notes.append(str(failure))
    return _Context(project, events, harness, by_id, read_findings(book), read_manifest(book), goals, notes)


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


def _finding_item(finding, manifest):
    return "- `%s` (ticket %s): %s" % (finding.get("id"), finding.get("ticket"),
                                        tagged_text(one_line(finding.get("text")), finding_tags(finding, manifest)))


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


# --- the sections ---------------------------------------------------------------------------------


def _decider_decisions(context):
    lines = []
    for event in context.events:
        payload = event.get("payload") or {}
        if event.get("event") != ledger.DECISION or payload.get("decided_by") != "decider":
            continue
        ticket = payload.get("ticket")
        title = (context.tickets.get(ticket) or {}).get("title")
        # A question of the grill has no ticket; its answer opens with the question it settles. A parked proposal
        # the decider reconsidered has none either, and its answer opens with `proposal <id>:` (ticket 31).
        if ticket is not None:
            subject = "Ticket %s%s" % (ticket, ", *%s*" % title if title else "")
        elif str(payload.get("answer") or "").startswith("proposal "):
            subject = "A parked proposal"
        elif str(payload.get("answer") or "").startswith(VENUE_PREFIX):
            subject = "The paper's venue"  # `wayline paper` without `--venue` (ticket 53)
        else:
            subject = "The grill"
        lines.append("- %s: **%s** (confidence %s, %s)" % (
            subject, one_line(payload.get("answer")), _number(payload.get("confidence")), _when(event)))
        if payload.get("rationale"):
            lines.append("  - rationale: %s" % one_line(payload["rationale"]))
    return _records(lines or ["No decision was made by the decider."])


def _open_questions(context):
    """The decision tickets still open and the tickets waiting for a person.

    A ticket the escalation chain left with nowhere to climb carries `reason: top_rung` on its
    `ticket_needs_human`, and its item says "at the ladder's top rung" (decision 16; ticket 61).
    """
    asked, why = {}, {}
    for event in context.events:
        if event.get("event") == ledger.TICKET_NEEDS_HUMAN:
            payload = event.get("payload") or {}
            asked[payload.get("ticket")] = payload.get("question")
            why[payload.get("ticket")] = NEEDS_HUMAN_NOTES.get(payload.get("reason"))
    lines = []
    for number in sorted(context.tickets):
        fields = context.tickets[number]
        if tickets.is_open_decision(fields):
            lines.append("- Decision ticket %d, *%s*: blocking `%s`%s; origin `%s`" % (
                number, fields["title"], fields.get("blocking") or "none",
                ", human only" if fields.get("human_only") else "", fields.get("origin") or "none"))
    for number in sorted(context.tickets):
        fields = context.tickets[number]
        if fields["status"] == "needs_human":
            lines.append("- Ticket %d, *%s*, needs a human%s: %s" % (
                number, fields["title"], ", %s" % why[number] if why.get(number) else "",
                one_line(asked.get(number) or "no question was journaled")))
    return _records(lines or ["No decision ticket is open and no ticket needs a human."])


def _trajectory(context):
    """Each goal's trajectory, from its own `progress` and `discarded` events (ticket 87: keep-if-better runs per goal)."""
    if not context.goals:
        return _records(["No quantitative goal: no objective in `research/objectives.json` has a measure."])
    from wayline import stopping  # the stopping module imports the goal module, which imports the gates
    lines = ["Stopping rule: %s." % stopping.describe_rule(stopping.rule_of(context.harness))]
    for record in context.goals:
        goal, identifier = record["measure"], record["id"]
        readings = [event.get("payload") or {} for event in context.events
                    if event.get("event") == ledger.PROGRESS and (event.get("payload") or {}).get("goal") == identifier]
        lines.extend(["", "Goal %s (%s): `%s`, direction `%s`, target %s on the held-out split `%s`." % (
            identifier, record.get("status"), goal.get("metric"), goal.get("direction"), _number(goal.get("target")),
            goal.get("held_out_split"))])
        if not readings:
            lines.append("No `progress` reading was journaled.")
        else:
            lines.extend(["", "```"] + _chart(readings, goal) + ["```"])
        kept = [payload for payload in readings if payload.get("kept")]
        lines.extend(["", "Kept readings:"])
        lines.extend(["- %s from run `%s` (ticket %s)" % (_number(payload.get("value")), payload.get("run_id"), payload.get("ticket"))
                      for payload in kept] or ["- none"])
        lines.extend(["", "Discarded changes:"])
        lines.extend(["- ticket %s: mean %s against the best %s, standard deviation %s, seeds %s" % (
            payload.get("ticket"), _number(mean), _number(payload.get("best")), _number(payload.get("sd")), payload.get("seeds"))
            for payload, mean in _discarded_means(context.events, identifier)] or ["- none"])
    return _records(lines)


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


def _chart(readings, goal, width=40):
    """The trajectory drawn in text: one bar per reading, the target marked, kept or not said."""
    target = goal.get("target")
    values = [payload["value"] for payload in readings if _is_number(payload.get("value"))]
    scale = values + ([target] if _is_number(target) else [])
    if not scale:
        return ["no reading is a number"]
    low, high = min(scale), max(scale)
    span = (high - low) or abs(high) or 1.0
    low, high = low - span * 0.25, high + span * 0.05

    def position(value):
        return max(0, min(width, int(round((value - low) / (high - low) * width))))

    mark = position(target) if _is_number(target) else None
    rows = []
    for payload in readings:
        value = payload.get("value")
        state = "kept" if payload.get("kept") else "not kept"
        if not _is_number(value):
            rows.append("%8s %s  %-8s ticket %-4s %s" % ("?", " " * width, payload.get("run_id"), payload.get("ticket"), state))
            continue
        cells = ["#"] * position(value) + ["."] * (width - position(value))
        if mark is not None and mark < width:
            cells[mark] = "|"
        rows.append("%8s %s  %-8s ticket %-4s %s" % (_number(value), "".join(cells), payload.get("run_id"), payload.get("ticket"), state))
    if mark is not None:
        rows.append("%8s %s^ target %s" % ("", " " * mark, _number(target)))
    return rows


def _findings_section(context, prose):
    groups = _claim_groups(context)
    if not groups:
        return _records(["No finding was recorded."])
    paragraphs = {group["group"]: group["text"] for group in (prose or {}).get("groups") or []}
    lines = []
    for key, members in groups.items():
        lines.extend(["### %s" % key, ""])
        if paragraphs.get(key, "").strip():
            lines.extend([one_line(paragraphs[key]), ""])
        lines.extend(_finding_item(finding, context.manifest) for finding in members)
        lines.append("")
    return lines[:-1]


def _closed(context):
    verdicts = {}
    for event in context.events:
        payload = event.get("payload") or {}
        if event.get("event") == ledger.VERDICT and payload.get("subject_kind") == "ticket" and payload.get("pass"):
            verdicts[event.get("ticket")] = payload
    ordered = [context.tickets[number] for number in sorted(context.tickets)]
    accepted = [fields for fields in ordered if fields["status"] == "accepted"]
    done = [fields for fields in ordered if fields["status"] == "done"]
    lines = ["Accepted, meaning the machine checks and a Type-B verdict passed (%d):" % len(accepted)]
    for fields in accepted:
        verdict = verdicts.get(fields["id"]) or {}
        lines.append("- Ticket %d, *%s* (%s, difficulty %s): verdict `%s` on %s" % (
            fields["id"], fields["title"], fields["kind"], fields.get("difficulty"),
            verdict.get("verdict_type") or "not journaled", verdict.get("model") or "no journaled model"))
    lines.extend(["", "Done, meaning the machine checks passed and no verdict has (%d):" % len(done)])
    lines.extend("- Ticket %d, *%s* (%s, difficulty %s)" % (fields["id"], fields["title"], fields["kind"], fields.get("difficulty"))
                 for fields in done)
    return _records(lines + _docs_site(context))


def _docs_site(context):
    """The documentation site, which is part of done whenever a `code` ticket added public API (decisions 11, 13).

    Nothing when no ticket declared public API and none is a `docs` ticket. Otherwise the declaring
    tickets, the `docs` tickets and their statuses, the last build on `main` (`docs.read_record`), and
    every declaring ticket no closed `docs` ticket waits on, which is the site still owed.
    """
    from wayline import docs  # the docs module reads the code dossier's inventory; keep this module's import light
    from wayline.plan import adds_public_api

    bodies = {}
    for path in sorted(tickets.tickets_dir(context.project).glob("*.md")):
        try:
            fields, body = tickets.read_ticket(path)
        except (OSError, tickets.TicketError, ValueError):
            continue
        bodies[fields["id"]] = body
    declared = [context.tickets[number] for number in sorted(context.tickets)
                if context.tickets[number]["kind"] == "code" and adds_public_api(bodies.get(number, ""))]
    documenting = [context.tickets[number] for number in sorted(context.tickets) if context.tickets[number]["kind"] == "docs"]
    if not declared and not documenting:
        return []
    lines = ["", "The documentation site, part of done because %s:" % (
        "ticket(s) %s added public API" % ", ".join(str(fields["id"]) for fields in declared)
        if declared else "the graph holds docs tickets")]
    for fields in documenting:
        lines.append("- Ticket %d, *%s* (docs): %s" % (fields["id"], fields["title"], fields["status"]))
    record = docs.read_record(context.project)
    if record is None:
        lines.append("- The site has not been built on `main` (no `%s`)." % docs.CHECKS_JSON.as_posix())
    else:
        failed = [check["check"] for check in record.get("checks") or [] if not check.get("pass")]
        lines.append("- The site `%s`, built %s: %s." % (
            record.get("site") or docs.SITE_INDEX.as_posix(), record.get("ran_at") or "at an unrecorded time",
            "every machine check passed" if not failed else "the %s check(s) failed" % ", ".join(failed)))
    # A closed docs ticket documents what it waits on, directly or through the tickets it waits on.
    documented = set()
    for item in documenting:
        if item["status"] in tickets.SATISFIED:
            documented |= _upstream(context.tickets, item["id"])
    for fields in declared:
        if fields["id"] not in documented:
            lines.append("- Owed: ticket %d added public API and no closed docs ticket documents it." % fields["id"])
    return lines


def _upstream(by_id, identifier):
    """Every ticket `identifier` waits on, through any chain of `blocked_by`."""
    seen, stack = set(), list((by_id.get(identifier) or {}).get("blocked_by") or [])
    while stack:
        number = stack.pop()
        if number not in seen:
            seen.add(number)
            stack.extend((by_id.get(number) or {}).get("blocked_by") or [])
    return seen


def _fell_back(context):
    """Every verdict and decision taken on Opus in place of Fable while its weekly window was spent (decision 15).

    Nothing is taken again after the reset, so this is where the owner reads which judgments ran by fallback.
    """
    lines = []
    for event in context.events:
        payload = event.get("payload") or {}
        if not payload.get("fallback_from"):
            continue
        if event.get("event") == ledger.VERDICT:
            ticket = event.get("ticket")
            lines.append("- Verdict `%s` on the %s `%s`%s: %s on %s in place of %s, session `%s` (%s)" % (
                payload.get("verdict_type"), payload.get("subject_kind"), payload.get("subject"),
                " (ticket %s)" % ticket if ticket is not None else "", "passed" if payload.get("pass") else "failed",
                payload.get("model") or "an unnamed model", payload["fallback_from"],
                payload.get("session_id") or event.get("session_id") or "unknown", _when(event)))
        elif event.get("event") == ledger.DECISION:
            ticket = payload.get("ticket")
            title = (context.tickets.get(ticket) or {}).get("title")
            subject = "the grill" if ticket is None else "ticket %s%s" % (ticket, ", *%s*" % title if title else "")
            lines.append("- Decision by the %s on %s: **%s** on %s in place of %s (%s)" % (
                payload.get("decided_by"), subject, one_line(payload.get("answer")), payload.get("model") or "an unnamed model",
                payload["fallback_from"], _when(event)))
    if not lines:
        return _records(["Nothing was judged by fallback: every verdict and decision ran on the model its table gives."])
    return _records(["Taken on Opus while Fable's weekly window was spent, under the fallback consent. None of them is "
                     "taken again on Fable after the reset.", ""] + lines)


def _negative_section(context, prose):
    negative = [finding for finding in context.findings if finding.get("negative")]
    if not negative:
        return _records(["No negative result was recorded."])
    lines = []
    paragraph = (prose or {}).get("negative_results") or ""
    if paragraph.strip():
        lines.extend([one_line(paragraph), ""])
    lines.extend(_finding_item(finding, context.manifest) for finding in negative)
    return lines


def _papers(context):
    from wayline.dossier import render_levels_report  # lazy: the dossier module pulls in the fetch seam

    levels = render_levels_report(context.project)
    lines = []
    for level in sorted(levels["by_level"]):
        slugs = levels["by_level"][level]
        named = ", ".join("`%s`%s" % (slug, "" if _existence(context.project, slug) == "verified" else " (unresolved)")
                          for slug in slugs)
        lines.append("- Level %d (%d): %s" % (level, len(slugs), named or "none"))
    promoted = {}
    for event in context.events:
        payload = event.get("payload") or {}
        name = event.get("event")
        if name == ledger.PROMOTED and payload.get("to_level") == 2:
            promoted[payload.get("slug")] = (event, payload)
        elif (name == ledger.ABSORBED and payload.get("level") == 2) or name == ledger.DEMOTED:
            promoted.pop(payload.get("slug"), None)
    unread = ["- `%s`: promoted to level 2 on `%s` (%s), and no level-2 absorb is journaled" % (
        slug, payload.get("trigger"), _when(event)) for slug, (event, payload) in promoted.items()]
    unread.extend("- `%s`: a promotion beyond the phase's reading budget waits on decision ticket %s (%s)" % (
        item["slug"], item["ticket"], item["reason"] or "no reason recorded") for item in levels["not_read_in_full"])
    lines.extend(["", "Promotions not read in full:"] + (unread or ["- none"]))
    return _records(lines)


def _not_pursued(context):
    last = {}
    for event in context.events:
        if event.get("event") in (ledger.PROPOSAL_ADMITTED, ledger.PROPOSAL_PARKED):
            payload = event.get("payload") or {}
            last[payload.get("id")] = (event.get("event"), payload)
    lines = ["- Proposal `%s` from ticket %s (%s): parked, reason `%s`" % (
        identifier, payload.get("from"), payload.get("kind"), payload.get("reason"))
        for identifier, (name, payload) in last.items() if name == ledger.PROPOSAL_PARKED]
    lines.extend("- Ticket %d, *%s* (%s): parked" % (number, context.tickets[number]["title"], context.tickets[number]["kind"])
                 for number in sorted(context.tickets) if context.tickets[number]["status"] == "parked")
    return _records(lines or ["Nothing was parked."])


def _global_changes(context):
    autonomy = context.harness.get("autonomy")
    if autonomy == "autonomous":
        lines = ["Autonomy is `autonomous`, so every global change below is a proposal and none was applied."]
    else:
        lines = ["Autonomy is `%s`: a global change is applied only by the owner, through `wayline promote`." % autonomy]
    from wayline import changes as records  # the evolve loop (ticket 45) imports the gates, which import this module
    # A record the project keeps says what it would change, where it stands, and the command that applies a proposal;
    # one only the journal names (a record file removed by hand, a journal older than ticket 45) is named from its event.
    kept = records.proposal_lines(context.project)
    held = {record["id"] for record in records.read_changes(context.project)}
    changes = kept + ["- Change record `%s`: mechanism `%s`, fixture `%s`" % (
        payload.get("id"), payload.get("mechanism"), payload.get("fixture"))
        for payload in (event.get("payload") or {} for event in context.events if event.get("event") == ledger.CHANGE_RECORD)
        if payload.get("scope_kind") == "global" and payload.get("id") not in held]
    return _records(lines + (changes or ["- none"]))


def _resources(context):
    stopped = [event.get("payload") or {} for event in context.events if event.get("event") == ledger.PAUSED]
    paused = [payload for payload in stopped if payload.get("model") != pacing.FABLE]
    held = [payload for payload in stopped if payload.get("model") == pacing.FABLE]
    lines = ["Usage windows: the run paused %d time(s) on a closed window." % len(paused)]
    lines.extend("- `%s` window at utilization %s, reset at %s" % (
        payload.get("window"), _number(payload.get("utilization")), payload.get("resets_at")) for payload in paused)
    if held:
        # The hold of decision 15 paused nothing: every launch not on Fable went on.
        lines.append("Fable's weekly window held the launches on Fable %d time(s), while everything else kept launching." % len(held))
        lines.extend("- held at utilization %s until %s" % (_number(payload.get("utilization")), payload.get("resets_at"))
                     for payload in held)
    peaks = {}
    for event in context.events:
        payload = event.get("payload") or {}
        readings = []
        if event.get("event") == ledger.PACING:
            readings = [(window, payload.get(window)) for window in pacing.READINGS]
        elif event.get("event") == ledger.PAUSED:
            window = pacing.FABLE if payload.get("model") == pacing.FABLE else payload.get("window")
            readings = [(window, payload.get("utilization"))] if window in pacing.READINGS else []
        for window, value in readings:
            if _is_number(value):
                peaks[window] = max(peaks.get(window, value), value)
    if peaks:
        lines.append("Highest utilization read: %s." % ", ".join("%s %s" % (window, _number(value)) for window, value in sorted(peaks.items())))
    closed = [number for number in sorted(context.tickets) if context.tickets[number]["status"] in tickets.SATISFIED]
    spent = {}
    for event in context.events:
        if event.get("event") == ledger.TICKET_RESULT:
            payload = event.get("payload") or {}
            turns, sessions, milliseconds = spent.get(payload.get("ticket"), (0, 0, 0))
            spent[payload.get("ticket")] = (turns + (payload.get("turns") or 0), sessions + 1, milliseconds + (payload.get("duration_ms") or 0))
    lines.extend(["", "Turns per closed ticket:"])
    total = 0
    for number in closed:
        turns, sessions, milliseconds = spent.get(number, (0, 0, 0))
        total += turns
        lines.append("- Ticket %d: %d turns in %d session(s), %.1f minutes" % (number, turns, sessions, milliseconds / 60000))
    if closed:
        lines.append("Total: %d turns over %d closed tickets, %.1f per ticket." % (total, len(closed), total / len(closed)))
    else:
        lines.append("- no ticket was closed")
    launched = {}
    seconds_by_job = {}
    for event in context.events:
        payload = event.get("payload") or {}
        if event.get("event") == ledger.JOB_LAUNCHED:
            launched[payload.get("job")] = payload
        elif event.get("event") == ledger.JOB_FINISHED and _is_number(payload.get("seconds")):
            seconds_by_job[payload.get("job")] = payload["seconds"]
    gpu_seconds = core_seconds = 0
    for job, seconds in seconds_by_job.items():
        spec = launched.get(job) or {}
        cores = spec.get("cores")
        gpu_seconds += seconds * len(spec.get("gpu_uuids") or [])
        core_seconds += seconds * (len(cores) if isinstance(cores, list) else cores if _is_number(cores) else 0)
    lines.extend(["", "Jobs: %d finished, %.2f GPU-hours, %.1f core-hours." % (
        len(seconds_by_job), gpu_seconds / 3600, core_seconds / 3600)])
    return _records(lines)


def _events(context):
    counts = Counter(event.get("event") for event in context.events)
    lines = ["%d events in `research/journal.jsonl`." % len(context.events), "", "| Event | Count |", "|---|---|"]
    lines.extend("| `%s` | %d |" % (name, counts[name]) for name in ledger.EVENTS if counts.get(name))
    lines.extend(["", "Milestones:"])
    milestones = ["- %s `%s` %s" % (_when(event), event.get("event"), _payload_text(event.get("payload")))
                  for event in context.events if event.get("event") in MILESTONES]
    return _records(lines + (milestones or ["- none"]))


def _body(context, prose):
    sections = (
        _decider_decisions(context), _open_questions(context), _trajectory(context),
        _findings_section(context, prose), _closed(context), _fell_back(context), _negative_section(context, prose),
        _papers(context), _not_pursued(context), _global_changes(context), _resources(context), _events(context),
    )
    lines = []
    for number, section in enumerate(sections, start=1):
        lines.extend(["## %d. %s" % (number, SECTIONS[number - 1]), ""] + list(section) + [""])
    return "\n".join(lines)


def _banner(context, result, notes):
    lines = [
        "# Report: %s" % context.project.name,
        "",
        RECORDS_BEGIN,
        "Rendered by `wayline report` from `research/journal.jsonl` (%d events), `findings.jsonl`, "
        "`manifest.json`, `objectives.json`, and the tickets. The provenance linter %s: %d claim sentence(s), "
        "%d tagged." % (len(context.events), "passed" if result.passed else "FAILED", result.claims, result.tagged),
    ]
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


# --- the render -----------------------------------------------------------------------------------


@dataclass
class Rendered:
    """One render: where `REPORT.md` was written, its sha256, the linter's result, and the notes."""

    path: Path
    sha256: str
    lint: Lint
    notes: list = field(default_factory=list)


def render_report(project, *, harness_root=HARNESS_ROOT, policy=None, offline=False, draft=True):
    """Render `research/REPORT.md` from the ledger, lint it, write it, and journal `report_rendered`.

    The writer drafts the prose (unless `draft` is False or the cache already holds prose for these
    findings), the classifier classifies every prose sentence the cache does not hold, the linter
    runs on the tagged text, and the tags are rendered as citations in the file written. A report
    that fails the linter is written all the same, with the offending sentences at its top: the
    report is the stopping point, and one that failed says so where the owner reads it. Before
    that, a failure on the writer's own sentences resumes the writer's session with the list, for
    at most `paper.MAX_BUILDS` drafts, and the cache records each draft's result, so a failing
    draft is redrafted by the next render that may launch rather than reused. `offline` launches no session at all, which is how the tick renders.
    """
    project = Path(project).resolve()
    book = Ledger(project)
    policy = policy_for(project, harness_root) if policy is None else policy
    context = report_context(project)
    from wayline.paper import MAX_BUILDS  # paper imports this module
    notes = []
    evidence = report_evidence(context)
    may_launch = draft and not offline
    prose, note = draft_prose(project, evidence, harness_root=harness_root, policy=policy, offline=not may_launch)
    if note:
        notes.append(note)
    for number in range(1, MAX_BUILDS + 1):
        body = _body(context, prose)
        texts = [sentence.text for sentence in prose_sentences(body)]
        try:
            classes = classify(project, texts, harness_root=harness_root, policy=policy, offline=offline)
        except UsageLimited as refused:
            classes = read_claims_cache(book)
            notes.append("%s; the sentences it did not reach are unclassified" % refused)
        result = lint(project, body, classes)
        failures = writer_failures(result, prose)
        if not may_launch:
            break
        if prose:
            _record_prose_lint(book, failures)
        if not failures:
            break
        if number == MAX_BUILDS:
            notes.append("the writer's prose still failed the linter after %d drafts" % MAX_BUILDS)
            break
        try:
            prose = redraft_prose(project, evidence, failures, harness_root=harness_root, policy=policy)
        except UsageLimited as refused:
            notes.append("%s, so the writer's failing prose was not redrafted" % refused)
            break
    path = book.write_markdown(REPORT, render_citations(_banner(context, result, notes) + body))
    digest = sha256_of(path)
    book.append_event(ledger.REPORT_RENDERED, {"sha256": digest, "claims": result.claims, "tagged": result.tagged,
                                               "linter_pass": result.passed})
    return Rendered(path, digest, result, notes)


def lint_report(project):
    """The linter on the `REPORT.md` on disk, with the classes the cache holds: what `wayline report` last wrote."""
    project = Path(project).resolve()
    text = (project / "research" / REPORT).read_text(encoding="utf-8")
    return lint(project, restore_tags(text), read_claims_cache(project))


def report_command(args):
    """`wayline report [--project <path>] [--offline] [--no-draft] [--verify] [--json]`."""
    parser = argparse.ArgumentParser(prog="wayline report", description="render research/REPORT.md from the ledger and lint its claims")
    parser.add_argument("--project", help="the project (default: the active one)")
    parser.add_argument("--offline", action="store_true",
                        help="launch no session: nothing new is classified or drafted, and an untagged sentence the cache does not cover fails the linter")
    parser.add_argument("--no-draft", action="store_true", help="use the writer's cached prose rather than drafting it again")
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
        rendered = render_report(project, offline=options.offline, draft=not options.no_draft)
        verified = verify_claims(project) if options.verify and rendered.lint.passed else None
        if verified and verified["fell_back"]:
            # The report lists the verdicts taken by fallback from the journal, which the sampling has just added to;
            # nothing the writer or the classifier read changed, so the render launches nothing.
            rendered = render_report(project, offline=True, draft=False)
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


def _when(event):
    stamp = str(event.get("ts") or "")
    return stamp[:16].replace("T", " ") + "Z" if len(stamp) >= 16 else stamp or "?"


def _payload_text(payload):
    return ", ".join("%s %s" % (key, json.dumps(value, ensure_ascii=False)) for key, value in (payload or {}).items())


def _existence(project, slug):
    try:
        return json.loads((Path(project) / "research" / "refs" / slug / "dossier.json").read_text(encoding="utf-8")).get("existence")
    except (OSError, ValueError, AttributeError):
        return None


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
