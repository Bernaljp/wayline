"""The manifest and findings provenance (Implementation Decisions 6 and 2). Built by ticket 18.

`results/` lives outside git (Implementation Decisions 1 already ignores it); every artifact a
finding will ever cite is hashed into `research/manifest.json` first, by `register_artifact`,
so `add_finding` can refuse a finding whose provenance points anywhere else. Findings are
numbered sequentially in `research/findings.jsonl`; `render_findings` renders `findings.md`
from them, grouped by ticket, negative results marked, and `add_finding` calls it after every
change so the two files never drift.

The claim linter of Implementation Decisions 11 (`{res:...}` / `{ref:...}` tags in REPORT.md)
is ticket 40's; this module owns the manifest, the findings ledger it resolves against, and the
sentence pass both the linter and the guidelines checks walk a draft with.
"""

import hashlib
import json
import re
import subprocess
from collections import namedtuple
from pathlib import Path

from wayline import POLICY_PATH
from wayline.ledger import Ledger, now_ts

__all__ = [
    "ProvenanceError", "MANIFEST", "FINDINGS", "FINDINGS_MD", "RUN_ID_RE",
    "sha256_of", "read_manifest", "manifest_paths", "register_artifact",
    "read_findings", "add_finding", "render_findings",
    "commit_threshold_bytes", "oversized_tracked_files",
    "TAG_RE", "RES_TAG_RE", "REF_TAG_RE", "Sentence", "sentences", "parse_tag", "strip_tags",
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

# Where one sentence ends: a full stop, question mark or exclamation mark, then any closing
# quotes, then the provenance tags that belong to the sentence just ended, and then either the
# start of the next sentence or the end of the text. Requiring a capital (or a quote or a bracket)
# after the space is what keeps "Fig. 1", "e.g. the" and "0.5" from each becoming two sentences;
# it is a heuristic, and a draft that opens a sentence with a lowercase symbol name joins the one
# before it. The linter classifies sentences and this decides what a sentence is, so both halves
# of the provenance work see exactly the same units.
_BOUNDARY = re.compile(r"""[.!?]["')\]]*(?:\s*\{(?:res|ref):[^{}]+\})*(?=\s+["'(\[A-Z]|\s*$)""")

Sentence = namedtuple("Sentence", "text tags")

_HASH_CHUNK = 1 << 20  # 1 MiB


class ProvenanceError(ValueError):
    """A finding whose provenance does not resolve, or an artifact that cannot be manifested."""


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


def add_finding(project_or_ledger, text, provenance, ticket, negative=False):
    """Append one finding to `findings.jsonl`, journal `finding`, and re-render `findings.md`.

    `provenance` is one locator or a list of them, each `<manifested path>#<locator>`. Refused
    (raises `ProvenanceError`, without writing anything) when a locator carries no `#<locator>`
    half or its artifact half is not a path in `manifest.json`; register the artifact first. The
    caller (the conductor, for a worker's finding) journals the refusal on the ticket itself.
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
        finding = {
            "id": _next_finding_id(findings),
            "ticket": ticket,
            "text": text,
            "provenance": locators,
            "negative": bool(negative),
            "ts": now_ts(),
        }
        book.append_line(FINDINGS, json.dumps(finding, ensure_ascii=False))
        book.append_event(
            "finding",
            {"id": finding["id"], "ticket": ticket, "text": text, "provenance": locators, "negative": finding["negative"]},
            ticket=ticket,
        )
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
                locators = ", ".join(finding.get("provenance") or [])
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
    pattern = RES_TAG_RE if kind == "res" else REF_TAG_RE
    found = pattern.match(rest)
    return kind, (found.groupdict() if found else None)


def strip_tags(text):
    """`text` with its provenance tags taken off, for a word count that does not count markup."""
    return TAG_RE.sub("", str(text or "")).strip()


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
