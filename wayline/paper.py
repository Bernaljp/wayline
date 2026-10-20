"""The paper on request (Implementation Decisions 13 and 11; BRIEF 13.3; ticket 53).

`wayline paper --venue <slug>` after the report, or `wayline paper` and the decider picks the venue
that fits best from `guidelines/` (`decider.decide_venue`, journaled as a `decision`). Then, in order:

1. **`paper_started`** is journaled with the venue.
2. **The draft.** One `writer` session (`policy.roles.writer`, `opus xhigh`), read-only, on the
   `paper_draft` schema, is given the venue's guidelines, the findings grouped by claim with their tags,
   the references the linter can resolve, the manifested results a figure may draw, and `REPORT.md` to
   read. It returns the whole manuscript in Markdown and the figures it asks for; code writes it to
   `research/paper/paper.md`, since the ledger is the only writer of `research/` (decision 2).
3. **The figures.** Each figure the draft asks for is requested from the figure role (ticket 50) with
   the venue's `target`: the column width, the smallest type, the resolution, and the formats the
   venue takes. A figure whose request has not changed is not drawn again: a verified one is placed as
   it is, and one that waited (the owner's pick, a window) is resumed. A verified figure is copied into
   `research/paper/figures/` and its placeholder line becomes the image and the figure role's caption,
   which sit between the records markers because the figure role's own `provenance` check and honesty
   verdict are what trace them; everything else the writer wrote is prose the linter reads. A figure
   the paper asked for files no proposal (ticket 66): what the figure role has to say about the text,
   its `findings_for_text`, goes on the next build's list for the writer drafting that text, once.
4. **Every build is checked.** The sentence classifier and the provenance linter of ticket 40 run on
   the draft, and the seven checks of ticket 52 on `research/paper/` against the venue's
   `guidelines.json`. A lint problem, a failing check, a figure that could not be placed, or a caption
   that names another figure under `figures/` goes back to the same writer session with the list, up
   to `MAX_BUILDS` builds; a draft still failing after that is left for the owner with its list, and
   no verdict is spent on it. The next build sends a caption that named another figure back to the
   figure role as a guided revision that drops the reference, and a build whose figures had new
   points for the text is followed by one that gives them to the writer, though it failed nothing.
5. **The gate.** A draft that builds is gated by the two-thread kill argument (`gates.kill_argument`)
   and then one independent verdict, the read (`gates.PAPER_READ`), all fresh verifier sessions on the
   table's model for the writer's. A fail files a `writing` ticket that scopes the claims down, unless
   an open one for the same point stands; the next `wayline paper` gives the writer the open ones to
   answer, and the read is not spent on a draft the kill argument already sent back. A draft that
   passes both cancels the scope-down tickets it answered.
6. **On request, the claims are sampled.** `wayline paper --verify` takes the verifier's sample of the
   draft's tagged claims, as `wayline report --verify` does of the report's (decision 11: every claim
   in the report and the paper, by sampling), after a gate that passed.

It stops there: the owner reads `research/paper/`, and `research/paper/build.json` says what every
build found and what the gate decided. Nothing here, and no verb, action, or role anywhere in the
harness, submits a paper: this module imports no network seam, the writer and the verifier cannot
reach the network, and no venue's submission step is ever taken.
"""

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from wayline import HARNESS_ROOT, decider, figure_checks, figure_role, gates, guidelines, provenance, tickets, worker
from wayline.cli import parse_args
from wayline.ledger import PAPER_STARTED, Ledger
from wayline.project import ProjectError, find_project, policy_for, steer_ticket

__all__ = [
    "PaperError", "Paper", "PAPER_PATH", "BUILD_PATH", "MAX_BUILDS", "FIGURE_TARGET", "READ_QUESTION", "READ_SCOPE", "READ_TITLE",
    "venues", "venue_lines", "figure_target", "figure_request", "caption_revision", "named_figures", "draw", "assemble", "fence_references", "check_build", "write_paper",
    "summary", "render", "paper_command",
]

PAPER_DIR = "paper"                       # research/paper/
PAPER_MD = "paper.md"
PAPER_PATH = "research/%s/%s" % (PAPER_DIR, PAPER_MD)
BUILD_JSON = "build.json"
BUILD_PATH = "research/%s/%s" % (PAPER_DIR, BUILD_JSON)
FIGURES_DIR = "figures"                   # research/paper/figures/<figure_id>.<png|pdf>
DRAFT_SCHEMA = "paper_draft"
WRITER = provenance.WRITER
SESSIONS = "paper"                        # research/sessions/paper/<n>
WRITER_BUDGET = "large"                   # a whole manuscript, read from the ledger, is the largest thing the writer does

# A draft goes back to the writer at most this many times in all. Three is the report's own lesson (M5): the
# redraft that answers the list is usually the second, and a third that still fails is a draft the owner reads.
MAX_BUILDS = 3

# The figure role's target where `guidelines.json` is silent. `figure_spec` names formats and a resolution but
# no column width: 89 mm is the single column of the Nature and Cell families, which the M7 figure was drawn at,
# and 6 pt the smallest type those families print. A venue's own `min_dpi` wins over 300 when it is higher.
FIGURE_TARGET = {"width_mm": 89, "max_height_mm": 120, "min_font_pt": 6, "min_dpi": 300}
FIGURE_TICKET = figure_role.PAPER_TICKET  # `figure_request.ticket`: no ticket asked for it, the paper did
REVISION_FIELDS = ("mode", "revision_of", "change_requests")

# What a figure result's status means for the draft. A figure that waits is the owner's or a window's, not the
# writer's to fix, so it holds the gate rather than going back to the writer.
PLACED, WAITING, FAILED = "placed", "waiting", "failed"
WAITS = ("candidates_ranked", "selected", "blocked")

# What one `wayline paper` came to; `held` is a draft that builds but waits on a figure.
PASSED, GATE_FAILED, BUILD_FAILED, HELD = "passed", "gate_failed", "build_failed", "held"

READ_QUESTION = "Would a reader at this venue find the draft's claims carried by the run's evidence and the draft complete as a paper?"
READ_SCOPE = (
    "Read the draft as the venue's reviewer would, against the run's findings, the report, the manifest, and the "
    "venue's guidelines at the paths below. It fails on a claim the findings or the references do not carry, a result "
    "stated past what its artifact says, a limitation or a negative result the report records and the draft leaves "
    "out, or a section the guidelines require that says nothing. Whether the science is interesting, or the prose "
    "could be better, is not your question. Every finding is at a path and a locator you read. You are the one "
    "independent verdict on this draft; a separate pair of sessions wrote and adjudicated the case against it."
)
READ_TITLE = "Scope the paper's claims the independent read did not accept"
READ_ORIGIN = PAPER_PATH + "#read"

_PLACEHOLDER = re.compile(r"^[ \t]*\{figure:([^{}\s]+)\}[ \t]*$", re.M)
_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$")
_ENTRY = re.compile(r"^\s*(?:\[\d+\]|\d+\.|[-*])\s+\S")   # a reference entry: `[1] ...`, `1. ...`, `- ...`
REFERENCE_HEADINGS = ("references", "reference list", "bibliography", "literature cited", "works cited", "cited literature")
_CAPTION_LEAD = re.compile(r"^\s*\**\s*(?:figure|fig\.?)\s*\d+\s*[.:|]\s*\**\s*", re.IGNORECASE)

_ID_TOKEN = r"(?<![A-Za-z0-9_-])%s(?![A-Za-z0-9_-])"   # a figure id standing whole, not inside a longer name
_COMPOUND = re.compile(r"[_\d-]")

RESUME_BUILD = (
    "The draft you returned was written to research/paper/ and built. The build failed on the items below. "
    "Return the whole draft again, through the structured output, with each one answered: a claim sentence ends "
    "with a tag that resolves, a check the venue's guidelines fail is met, and a figure that could not be placed "
    "is asked for again with a claim its data supports or taken out. Do not answer an item by deleting the evidence "
    "it asks for; scope the claim down instead. An `untagged_claim` is a sentence the classifier read as a claim, "
    "and it reads a statement of the study's scope or limits as one too: rewording it rarely changes that. End it "
    "with the tag of the artifact that bounds it (the result, the generator's settings, the split it was measured "
    "on), or leave the sentence out and say in `notes` what the owner should add by hand.\n\n%s"
)


class PaperError(ValueError):
    """A paper nobody could draft: no report yet, a venue with no guidelines, a writer with no usable answer."""


@dataclass
class Paper:
    """What one `wayline paper` came to: the venue, every build, the gate, and the tickets it filed."""

    venue: str
    path: Path
    status: str                               # passed | gate_failed | build_failed | held
    builds: list = field(default_factory=list)
    decided: object = None                    # the decider's `Outcome`, when it picked the venue
    kill: object = None                       # the kill argument's adjudication, a `gates.Verdict`
    read: object = None                       # the one independent verdict, a `gates.Verdict`
    tickets: list = field(default_factory=list)   # the scope-down tickets standing open after the gate
    claims: object = None                     # `provenance.verify_claims`'s outcome, under --verify
    notes: list = field(default_factory=list)


# --- the venue ------------------------------------------------------------------------------------


def venues(harness_root=HARNESS_ROOT):
    """`{slug: display name}` for every venue `guidelines/` holds a `guidelines.json` for."""
    found = {}
    for path in sorted((Path(harness_root) / guidelines.GUIDELINES_DIR).glob("*/" + guidelines.GUIDELINES_JSON)):
        try:
            found[path.parent.name] = guidelines.read_guidelines(path)["display_name"]
        except (guidelines.GuidelinesError, ValueError, KeyError):
            continue
    return found


def venue_lines(harness_root=HARNESS_ROOT):
    """One line of evidence per venue for the decider: what each asks of a paper, off its `guidelines.json`."""
    lines = []
    for slug in venues(harness_root):
        record = guidelines.read_guidelines(harness_root, slug)
        limits, spec, style = record["length_limits"], record["figure_spec"], record["reference_style"]
        size = ("%d words" % limits["word_count"] if limits["word_count"] else
                "%d pages" % limits["page_count"] if limits["page_count"] else "no length limit")
        forms = [form["name"] for form in record["reporting_checklists"] if form["required"]]
        lines.append("%s (%s): %s; sections %s; up to %s display items; %s citations; required forms: %s; guidelines at %s" % (
            slug, record["display_name"], size, ", ".join(record["required_structure"]) or "free",
            spec["max_count"] if spec["max_count"] is not None else "any number of", style["citation"] or "unstated",
            ", ".join(forms) or "none", Path(harness_root) / guidelines.GUIDELINES_DIR / slug / guidelines.GUIDELINES_JSON))
    return lines


def _choose_venue(project, harness_root, policy):
    known = venues(harness_root)
    if not known:
        raise PaperError("guidelines/ holds no venue; run `wayline guidelines build`")
    evidence = venue_lines(harness_root) + [
        "the run's report: research/REPORT.md; its findings: research/findings.jsonl; the intent: research/INTAKE.md",
        "nothing is submitted: the venue decides the guidelines the draft is written and checked under, and the owner "
        "can draft for another venue with wayline paper --venue <slug>",
    ]
    outcome = decider.decide_venue(project, known, evidence, harness_root=harness_root, policy=policy)
    if outcome.status != "decided":
        raise PaperError("the decider did not pick a venue (%s); name one with --venue <slug>, one of %s"
                         % (outcome.why, ", ".join(sorted(known))))
    return outcome


# --- the figures ----------------------------------------------------------------------------------


def figure_target(record, project):
    """The figure role's `target` at a venue: its formats and resolution, the house library, the column width."""
    spec = record["figure_spec"]
    accepted = {str(name).lower() for name in spec["formats"]}
    formats = [name for name in ("pdf", "png") if not accepted or name in accepted] or ["pdf", "png"]
    try:
        library = json.loads((Path(project) / "figures" / "style.json").read_text(encoding="utf-8")).get("library")
    except (OSError, ValueError, AttributeError):
        library = None
    target = dict(FIGURE_TARGET, venue=record["venue"], max_words=None, formats=formats, library=library or "matplotlib")
    if spec["min_dpi"]:
        target["min_dpi"] = max(int(spec["min_dpi"]), FIGURE_TARGET["min_dpi"])
    return target


def figure_request(asked, record, project, manifest):
    """The `figure_request/1` for one figure the draft asks for, or a string saying why there can be none.

    The data are manifested results only: a figure draws what the run produced and the manifest hashed, which is
    what the figure role's `provenance` check and the linter hold it to.
    """
    entries = {entry.get("path"): entry for entry in manifest.get("entries") or []}
    missing = [path for path in asked["data"] if path not in entries]
    if missing:
        return "its data %s %s not in research/manifest.json" % (", ".join(missing), "is" if len(missing) == 1 else "are")
    return {
        "schema": "figure_request/1", "ticket": FIGURE_TICKET, "figure_id": asked["figure_id"], "mode": "unguided",
        "kind": "result", "register": "quantitative",
        "claim": {"claim_id": asked["figure_id"], "text": " ".join(asked["claim"].split()), "claim_type": asked["claim_type"],
                  "evidence": list(asked.get("evidence") or [])},
        "data": [{"path": path, "sha256": entries[path]["sha256"], "run_id": entries[path].get("run_id")} for path in asked["data"]],
        "target": figure_target(record, project),
    }


def draw(project, request, *, harness_root=None, policy=None, say=None):
    """The figure role on one request: `(figure_result, reason)`, drawing nothing a previous build already has.

    The same request as the one on disk is not drawn again: a result that waited is resumed (the owner may have
    picked since), and any other is returned as it is, verified or failed, since drawing it again would spend the
    same sessions on the same answer. A changed request is a new version of the figure; a request that differs only
    in the venue's name, at the same size, type, resolution, formats, and library, is not a change.
    """
    previous = _figure_on_disk(project, request)
    if previous is not None:
        if previous.get("status") in WAITS:
            return figure_role.resume_figure(project, request["figure_id"], harness_root=harness_root, policy=policy, say=say)
        return previous, None
    return figure_role.make(project, request, harness_root=harness_root, policy=policy, say=say)


def _figure_on_disk(project, request):
    """The result on disk of the figure `request` draws, or None when it has to be drawn.

    A caption revision that did not verify (refused, failing its checks or its honesty verdict) is not the figure its
    own request draws: the revision replaced the verified result, so the figure is drawn again from that request, and
    its new caption is checked like any other, rather than the paper placing it nowhere from then on.
    """
    previous = figure_role.read_result(project, request["figure_id"])
    try:
        asked = json.loads((Path(project) / figure_role.FIGURES / request["figure_id"] / figure_role.REQUEST_JSON).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        asked = None
    if not isinstance(previous, dict) or not _drawn_alike(asked, request):
        return None
    failed_revision = (isinstance(asked, dict) and asked.get("mode") == "guided" and request.get("mode") != "guided"
                       and previous.get("status") not in WAITS + ("verified",))
    return None if failed_revision else previous


def _drawn_alike(asked, request):
    """Whether the request on disk, `asked`, draws the figure `request` asks for: equal, the target's `venue` label aside.

    Against an unguided request a guided revision on disk counts as the figure it revised: the paper sends a figure
    back only to fix its caption, and the next build, asking for the same figure, is given the revision rather than
    a new figure drawn from the start. A guided request is compared whole.
    """
    guided = isinstance(request, dict) and request.get("mode") == "guided"

    def unlabelled(value):
        if not isinstance(value, dict):
            return value
        value = dict(value, target={key: item for key, item in (value.get("target") or {}).items() if key != "venue"})
        return value if guided else {key: item for key, item in value.items() if key not in REVISION_FIELDS}
    return unlabelled(asked) == unlabelled(request)


def _figure_ids(project):
    """Every figure under the project's `figures/`: a directory holding a request or a result, this draft's or not."""
    try:
        found = sorted((Path(project) / figure_role.FIGURES).iterdir())
    except OSError:
        return []
    return [path.name for path in found
            if path.is_dir() and ((path / figure_role.REQUEST_JSON).is_file() or (path / figure_role.RESULT_JSON).is_file())]


def named_figures(caption, figure_id, project):
    """The other figures under the project's `figures/` that a caption names by id, in order.

    An id with a `_`, a `-`, or a digit in it is no word prose writes by chance, so it names its figure wherever it
    stands whole, in any case: the M7 run's "the ceiling_gap figure". An id that is a plain word (`depth`) names its
    figure only when it is written as one, in backticks or beside the word figure, since a caption says "depth" of
    its own axes all the time.
    """
    named = []
    for other in _figure_ids(project):
        if other == figure_id:
            continue
        word = re.escape(other)
        if _COMPOUND.search(other):
            pattern = _ID_TOKEN % word
        else:
            pattern = r"`%s`|\bfig(?:ure|\.)?\s+%s\b|\b%s\s+fig(?:ure\b|\.|\b)" % (word, word, word)
        if re.search(pattern, caption, re.IGNORECASE):
            named.append(other)
    return named


def caption_revision(request, names, version):
    """The guided revision that sends a figure back to have its caption drop the other figures it names.

    It is the figure's own request, drawn again from its `figure_result.json` with one change request, from the
    paper; its id carries the version that named them, so a revision that still names one is asked for anew.
    """
    named = ", ".join("figure `%s`" % name for name in names)
    return dict(request, mode="guided", revision_of="%s/%s/%s" % (figure_role.FIGURES, request["figure_id"], figure_role.RESULT_JSON),
                change_requests=[{"id": "drop-figure-references-v%d" % version, "from": "paper", "text": (
                    "Take %s out of the caption, and change nothing else: a caption describes its own figure and names no "
                    "other, since cross-references between figures are the writer's, in the text." % named)}])


def _revision(project, request, names):
    """The request to send for a figure whose caption named `names`: its caption revision, or `request` itself.

    Only a verified figure drawn from this same request is revised; a request that changed draws the figure anew, a
    caption and all, and that caption is checked like any other.
    """
    previous = _figure_on_disk(project, request)
    if previous is None or previous.get("status") != "verified":
        return request
    return caption_revision(request, names, previous.get("version") or 1)


def _figure_file(result, target, project):
    """The file the draft points at: PNG where the venue takes it (or names no format), PDF where it takes only that."""
    final = result.get("final") or {}
    order = ("png", "pdf") if "png" in target["formats"] else ("pdf", "png")
    for kind in order:
        path = final.get(kind)
        if path and (Path(project) / path).is_file():
            return Path(project) / path
    return None


def _caption(result, project):
    """The figure role's caption as text: `final.caption` is the path of its `caption.md` (ticket 50), never the words.

    The M7 run placed the path itself as every legend, and the kill argument's adjudication caught it; the next
    draft left the checks' `[[mixed-data]]` markers in, and it caught those too.
    """
    path = (result.get("final") or {}).get("caption")
    try:
        text = (Path(project) / path).read_text(encoding="utf-8") if path else None
    except (OSError, ValueError):
        return None
    # `[[mixed-data]]` is for `mixed_data_disclosed` to find beside the caption's own words; a reader has the words.
    return " ".join(text.replace(figure_checks.MIXED_DATA_MARKER, " ").split()) if text else None


def _place(project, draft, record, policy, harness_root, draw_figure, say, revise=None):
    """Every figure the draft asks for, drawn or taken as it is: `(placed, points)`.

    `placed` is `{figure_id: {state, file, caption, why}}`, with `names` on a placed figure whose caption names
    another figure under `figures/`. `points` are the figure role's `findings_for_text`, each with its figure and
    version. `revise` maps a figure the last build found naming others to their ids, and it is sent back to have
    its caption drop them.
    """
    manifest = provenance.read_manifest(project)
    placed, points = {}, []
    for asked in draft["figures"]:
        figure_id = asked["figure_id"]
        request = figure_request(asked, record, project, manifest)
        if isinstance(request, str):
            placed[figure_id] = {"state": FAILED, "why": request}
            continue
        if (revise or {}).get(figure_id):
            request = _revision(project, request, revise[figure_id])
        try:
            result, reason = draw_figure(project, request, harness_root=harness_root, policy=policy, say=say)
        except (gates.UsageLimited, gates.FableHeld):
            raise  # a window or the hold on Fable stops the whole paper, as it stops the writer (the caller's to say)
        except figure_role.FigureError as failure:
            placed[figure_id] = {"state": FAILED, "why": "the figure role refused the request: %s" % failure}
            continue
        except (gates.GateError, worker.LaunchError, worker.RoleError) as failure:
            placed[figure_id] = {"state": WAITING, "why": "the figure role stopped: %s" % failure}
            continue
        points.extend({"figure_id": figure_id, "version": result.get("version"), "text": provenance.one_line(finding["text"]),
                       "manuscript_locator": finding.get("manuscript_locator")}
                      for finding in result.get("findings_for_text") or [] if isinstance(finding, dict) and finding.get("text"))
        status = result.get("status")
        source = _figure_file(result, request["target"], project) if status == "verified" else None
        caption = _caption(result, project) if source is not None else None
        if source is not None and caption:
            placed[figure_id] = {"state": PLACED, "file": source, "caption": caption, "status": status, "version": result.get("version")}
            names = named_figures(caption, figure_id, project)
            if names:
                placed[figure_id]["names"] = names
        elif source is not None:
            placed[figure_id] = {"state": FAILED, "status": status,
                                 "why": "verified, but its caption %s cannot be read" % (result.get("final") or {}).get("caption")}
        elif status in WAITS or status == "verified":
            placed[figure_id] = {"state": WAITING, "status": status,
                                 "why": reason or ("verified with no file on disk" if status == "verified" else status)}
        else:
            findings = (result.get("honesty_verdict") or {}).get("findings") or []
            failed = [check["id"] for check in result.get("checks") or [] if not check.get("pass")]
            why = "the figure role ended %s%s%s" % (status, ": %s" % reason if reason else "",
                                                    "; failed checks %s" % ", ".join(failed) if failed else "")
            if findings:
                why += "; the honesty verdict found: %s" % "; ".join(" ".join(str(item.get("text", "")).split()) for item in findings)
            placed[figure_id] = {"state": FAILED, "status": status, "why": why}
    return placed, points


def _new_points(points, builds):
    """The figure role's points for the text that no earlier build listed for the writer.

    A figure not drawn again hands back the same points, and the writer is told each once.
    """
    told = {(item["figure_id"], item["text"]) for build in builds for item in build.get("for_writer") or []}
    fresh = []
    for point in points:
        if (point["figure_id"], point["text"]) not in told:
            told.add((point["figure_id"], point["text"]))
            fresh.append(point)
    return fresh


def _point_lines(points):
    return "\n".join("- figure `%s`%s: %s" % (point["figure_id"], ", at %s" % provenance.one_line(point["manuscript_locator"])
                                              if point.get("manuscript_locator") else "", point["text"]) for point in points)


def _build_message(failures, points):
    """What the writer is resumed with after a build: its list, and the figure role's points for the text."""
    if not failures:
        return RESUME_TEXT % _point_lines(points)
    return RESUME_BUILD % "\n".join(failures) + (TEXT_POINTS % _point_lines(points) if points else "")


# --- a build --------------------------------------------------------------------------------------


def assemble(markdown, placed):
    """The draft with each placeholder line replaced: `(text, problems, files)`.

    A placed figure becomes its image line and its caption, numbered in order, between the records markers; a
    figure that waits leaves a marked gap; a failed one, or a placeholder for a figure the draft never asked for,
    is a problem for the writer. `files` maps `figures/<name>` in the paper to the file it is copied from.
    """
    problems, files, number = [], {}, 0
    seen = set()

    def replace(match):
        nonlocal number
        figure_id = match.group(1)
        seen.add(figure_id)
        figure = placed.get(figure_id)
        if figure is None:
            problems.append({"problem": "figure", "detail": "the draft places {figure:%s} and asks for no figure %s" % (figure_id, figure_id)})
            return ""
        if figure["state"] == FAILED:
            problems.append({"problem": "figure", "detail": "figure %s could not be placed: %s" % (figure_id, figure["why"])})
            return ""
        if figure["state"] == WAITING:
            return "\n".join([provenance.RECORDS_BEGIN, "*[Figure %s is not drawn yet: %s.]*" % (figure_id, figure["why"]), provenance.RECORDS_END])
        if figure.get("names"):
            problems.append({"problem": "figure", "detail": (
                "figure %s's caption names %s, which is not its own: a caption describes its own figure, and a cross-reference "
                "between figures is yours, in the text. The next build has the figure role drop it from the caption; keep "
                "asking for figure %s as it is" % (figure_id, ", ".join("figure %s" % name for name in figure["names"]), figure_id))})
        number += 1
        name = "%s/%s%s" % (FIGURES_DIR, figure_id, figure["file"].suffix.lower())
        files[name] = figure["file"]
        caption = " ".join(_CAPTION_LEAD.sub("", figure["caption"]).split())
        return "\n".join([provenance.RECORDS_BEGIN, "![Figure %d](%s)" % (number, name), "",
                          "**Figure %d.** %s" % (number, caption), provenance.RECORDS_END])

    text = fence_references(_PLACEHOLDER.sub(replace, markdown))
    for figure_id in sorted(set(placed) - seen):
        problems.append({"problem": "figure", "detail": "figure %s was asked for and placed nowhere: put {figure:%s} on a line of its own "
                                                        "where it goes, or stop asking for it" % (figure_id, figure_id)})
    return text.rstrip("\n") + "\n", problems, files


def fence_references(text):
    """The draft with the entries of its reference list between the records markers, and nothing else of it.

    A reference entry names a source; it claims nothing, and it is what a `ref` tag's claim cites. Left in the prose,
    each entry is a sentence the classifier has to be asked about and may call a claim, and an entry cannot end
    with a tag. Only the entries are fenced (a line opening `[1]`, `1.`, `-`, or `*`): the M7 run's writer moved
    untagged sentences under `## References` when the whole section was fenced, and prose there is linted like prose
    anywhere. The markers are comments, so the seven checks still count the references.
    """
    out, in_section, fenced = [], False, False

    def close():
        nonlocal fenced
        if fenced:
            while out and not out[-1].strip():
                out.pop()
            out.append(provenance.RECORDS_END)
            out.append("")
            fenced = False

    for line in text.split("\n"):
        heading = _HEADING.match(line)
        if heading:
            close()
            in_section = heading.group(1).strip().lower() in REFERENCE_HEADINGS
            out.append(line)
            continue
        if in_section and _ENTRY.match(line):
            if not fenced:
                out.append(provenance.RECORDS_BEGIN)
                fenced = True
            out.append(line)
        elif in_section and line.strip():
            close()
            out.append(line)
        else:
            out.append(line)
    close()
    while out and not out[-1].strip():
        out.pop()
    return "\n".join(out)


def check_build(project, record, text, *, harness_root=HARNESS_ROOT, policy=None):
    """The linter and the seven checks on the draft as written: `(lint, findings)`.

    The classifier classifies every prose sentence its cache does not hold (a haiku batch through the launcher),
    the linter reads the tagged text, and the seven checks read `research/paper/` against `guidelines.json` with
    the project's manifest and references for the provenance cross-check.
    """
    texts = [sentence.text for sentence in provenance.prose_sentences(text)]
    classes = provenance.classify(project, texts, harness_root=harness_root, policy=policy)
    lint = provenance.lint(project, text, classes)
    findings = guidelines.run_checks(guidelines.Manuscript(Path(project) / "research" / PAPER_DIR), record, project=project)
    return lint, findings


def _owners(finding, record, files):
    """Whether a failing check is one no redraft can meet: a placed figure's format at a venue taking neither PDF nor PNG.

    The figure role draws PDF and PNG only, so at a venue that takes TIFF or EPS alone the conversion is the owner's.
    """
    accepted = {str(name).lower() for name in record["figure_spec"]["formats"]}
    return (finding.check == "figures" and accepted and not accepted & {"pdf", "png"}
            and any(finding.message.startswith("%s is " % Path(name).name) for name in files))


def _failures(lint, findings, figure_problems, record, files):
    """The build's list for the writer, and the notes for the owner: `(failures, notes)`."""
    listed = ["- lint `%s`: %s (%s%s)" % (problem["problem"], provenance.one_line(problem["sentence"]),
                                          "tag `%s`: " % problem["tag"] if problem["tag"] else "", problem["detail"])
              for problem in lint.problems]
    failing = [finding for finding in findings if finding.level == "fail"]
    listed += ["- check `%s`: %s" % (finding.check, finding.message) for finding in failing if not _owners(finding, record, files)]
    listed += ["- figure: %s" % problem["detail"] for problem in figure_problems]
    notes = ["%s: the figure role draws PDF and PNG, so converting it for the venue is the owner's" % finding.message
             for finding in failing if _owners(finding, record, files)]
    return listed, notes


# --- the writer -----------------------------------------------------------------------------------


def _references(project):
    """The references a `ref` tag can name: a verified dossier with a knowledge-base node, as the linter resolves them."""
    research = Path(project) / "research"
    found = []
    for node_path in sorted((research / "kb" / "nodes").glob("*.json")):
        slug = node_path.stem
        try:
            dossier = json.loads((research / "refs" / slug / "dossier.json").read_text(encoding="utf-8"))
            node = json.loads(node_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(dossier, dict) or dossier.get("existence") != "verified" or not isinstance(node, dict):
            continue
        identifiers = dossier.get("identifiers") or {}
        found.append("- `%s`: %s (%s)%s, level %s; its record is research/refs/%s/" % (
            slug, node.get("title") or (dossier.get("metadata") or {}).get("title") or slug, node.get("year") or "no year",
            ", doi %s" % identifiers["doi"] if identifiers.get("doi") else "", node.get("level", dossier.get("level")), slug))
    return found


def _scope_downs(project):
    """The open `writing` tickets a gate filed against the paper (origin the paper, or its read), oldest first."""
    try:
        listed = tickets.read_tickets(project)
    except tickets.TicketError:
        return []
    return [fields for fields in listed
            if fields["kind"] == "writing" and fields.get("origin") in (PAPER_PATH, READ_ORIGIN)
            and fields["status"] not in tickets.SATISFIED + ("parked",)]


def _open_scope_downs(project):
    """The scope-down tickets as the writer's prompt lists them, for it to answer this time."""
    return ["- research/tickets/%s: %s" % (tickets.filename(fields), fields["title"]) for fields in _scope_downs(project)]


def _guideline_summary(record):
    keep = ("display_name", "length_limits", "required_structure", "structure_flexible", "figure_spec", "reference_style",
            "reporting_checklists", "template")
    summary = {key: record[key] for key in keep}
    summary["reporting_checklists"] = [{key: form.get(key) for key in ("name", "required", "study_types")} for form in record["reporting_checklists"]]
    return json.dumps(summary, ensure_ascii=False, indent=1)


def _documents_and_concerns(project):
    """The project's documents index and its concerns, inlined for the writer when it has them (decision 17; ticket 96),
    through the records inliner the decider and the planner read them with."""
    from wayline import decider  # the decider imports the gates and the grill, as this module's callers do

    entries = decider.documents_and_concerns(project)
    if not entries:
        return []
    text, _ = decider.inline_records(entries, None, "The project's own writing and the points the work must answer. Each "
                                     "concern for the paper order is yours to answer in the text; a concern tied to an "
                                     "objective is answered by its findings; a declined one keeps its reason.",
                                     heading="# The project's documents and concerns")
    return [""] + text.rstrip("\n").split("\n")


def writer_prompt(role, project, record, harness_root=HARNESS_ROOT):
    """The writer's prompt for a paper: the venue, the evidence, the references, the results, the form, the schema."""
    context = provenance.report_context(project)
    evidence = provenance.report_evidence(context)
    slug = record["venue"]
    lines = [
        "# The paper you are drafting",
        "",
        "Draft a paper for %s from what this run established. It is a draft the owner reads; nothing is submitted. "
        "Write under C8: every claim sentence ends with provenance tags that resolve, copied from the evidence below. "
        "Read `research/REPORT.md` for the whole run first; the findings and the references below are what you may "
        "claim from." % record["display_name"],
        "",
        "## The venue's guidelines",
        "",
        "From `%s`; `source.md` beside it says which fields are verified. The seven mechanical checks read this record "
        "and nothing else, and they run on every build: the length with the venue's exclusions, the sections, the "
        "figures and their legends, the citation form and count, the reporting checklists, the template, and the tags."
        % (Path(harness_root) / guidelines.GUIDELINES_DIR / slug / guidelines.GUIDELINES_JSON),
        "",
        "```json",
        _guideline_summary(record),
        "```",
        "",
        "## The form",
        "",
        "- Markdown. The first line is `# <title>`; then one `## ` heading per section the venue asks for, named as it "
        "names them, the abstract under `## Abstract`.",
        "- A figure is a line of its own holding only `{figure:<figure_id>}`, where it goes, and an entry in `figures`: "
        "the claim it carries and the manifested results it draws. The figure role draws it at this venue's size and "
        "writes its caption; do not write one. A figure the run's data cannot carry is refused, so ask only for what "
        "the findings say.",
        "- Cite a reference in the venue's citation form (`numbered` is `[1]`, `author-date` is `(Author, 2021)`) and "
        "list each under `## References`; its claim sentence also ends with `{ref:<slug>#<locator>}`.",
        "- A required reporting checklist that is a form the authors fill in is the owner's: say so in `notes` rather "
        "than writing a section named after it.",
        "",
    ]
    for goal in evidence.get("goals") or []:
        lines.extend(["The goal %s: `%s`, direction %s, target %s, on the held-out split `%s`." % (
            goal.get("id"), goal.get("metric"), goal.get("direction"), goal.get("target"), goal.get("held_out_split")), ""])
    lines.extend(["# The evidence", "", "Each finding carries the tags that trace it; a claim sentence of yours ends with the tags "
                  "of the findings it rests on, copied exactly.", ""])
    for group in evidence["groups"]:
        lines.extend(["## Group `%s`" % group["group"], ""])
        for item in group["findings"]:
            lines.extend(provenance.finding_lines(item))
        lines.append("")
    lines.extend(["## Negative results", ""])
    for item in evidence["negative"]:
        lines.extend(provenance.finding_lines(item))
    if not evidence["negative"]:
        lines.append("None was recorded.")
    lines.extend(["", "# The references a `ref` tag can name", ""])
    lines.extend(_references(project) or ["None: the draft cites no reference with a `ref` tag."])
    lines.extend(["", "# The results a figure can draw", "", "Paths in `research/manifest.json`, with the run that produced each:", ""])
    entries = context.manifest.get("entries") or []
    lines.extend("- `%s` (run %s)" % (entry.get("path"), entry.get("run_id")) for entry in entries[:200])
    if len(entries) > 200:
        lines.append("- [wayline: %d more in research/manifest.json]" % (len(entries) - 200))
    lines.extend(_documents_and_concerns(project))
    scope_downs = _open_scope_downs(project)
    if scope_downs:
        lines.extend(["", "# What the last gate left standing", "",
                      "The kill argument or the independent read failed an earlier draft and filed these. Read each and "
                      "answer its points in this draft, with the evidence it asks for or a claim scoped down:", ""] + scope_downs)
    lines.extend(["", "Return the draft through the structured output; the harness writes it to `research/paper/` and builds it."])
    return provenance.joined("\n".join(lines), role.protocol, worker.schema_section("# The draft", DRAFT_SCHEMA))


def _answer(request, session_id=None, message=None):
    """One writer turn: a launch, or a resume carrying the build's list; the schema is checked and asked for once more."""
    envelope = worker.launch(request) if session_id is None else worker.resume(request, session_id, message)
    provenance.raise_if_refused(envelope, "writer", request.model)
    problem = provenance.schema_problem(envelope, DRAFT_SCHEMA)
    if problem is not None and envelope.session_id:
        envelope = worker.resume(request, envelope.session_id, provenance.RESUME_STRUCTURED % problem)
        provenance.raise_if_refused(envelope, "writer", request.model)
        problem = provenance.schema_problem(envelope, DRAFT_SCHEMA)
    if problem is not None:
        raise PaperError("the writer's draft could not be used: %s" % problem)
    return envelope


# --- the gate -------------------------------------------------------------------------------------


def _gate_paths(record, harness_root, placed_files):
    paths = [PAPER_PATH, provenance.REPORT_PATH, "research/findings.jsonl", "research/manifest.json",
             str(Path(harness_root).resolve() / guidelines.GUIDELINES_DIR / record["venue"] / guidelines.GUIDELINES_JSON)]
    if placed_files:
        paths.append("research/%s/%s/" % (PAPER_DIR, FIGURES_DIR))
    return paths


def _read_ticket(project, book, read, paths):
    """The `writing` ticket a failed read scopes the claims down with, unless one stands open already."""
    if gates.open_writing_ticket(project, READ_ORIGIN) is not None:
        return None
    body = "\n".join([
        "## What the independent read did not accept",
        "",
        "Verifier session `%s` (%s) read the draft against the run's evidence and the venue's guidelines and found:"
        % (read.session_id, read.model),
        "",
        gates.findings_text(read.findings),
        "",
        "Scope each claim to what the artifacts support, or add the evidence the point asks for, then run "
        "`wayline paper` again: the writer is given this ticket with the next draft.",
        "",
        "## The paths the read opened",
        "",
    ] + ["- `%s`" % item for item in paths])
    return gates.file_writing_ticket(
        # No touch set: the paper lives under research/, which only code writes (ticket 73).
        project, book, title=READ_TITLE, touches=[], inputs=list(paths),
        quality=["Does every point the independent read raised now have the evidence it asked for or a claim scoped down?"],
        origin=READ_ORIGIN, demo="`wayline paper` drafts again and the independent read passes.", body=body,
    )


def _gate(project, book, record, author, policy, harness_root, placed_files):
    """The kill argument, then the one independent verdict: `(kill, read, notes)`, `read` None when it was not spent.

    Every thread is a fresh verifier session. A failed kill argument sends the draft back through its `writing`
    ticket, and the read is not spent on a draft already going back (the owner orders by token cost). A gate that
    passes both cancels the scope-down tickets earlier drafts left open, since this draft answered them.
    """
    paths = _gate_paths(record, harness_root, placed_files)
    earlier = [fields["id"] for fields in _scope_downs(project)]
    kill = gates.kill_argument(paths, project=project, author_model=author, subject_kind="paper", subject=PAPER_PATH,
                               harness_root=harness_root, policy=policy, ledger=book)
    if not kill.passed:
        return kill, None, ["the read was not spent: the kill argument already sends this draft back"]
    read = gates.verdict("paper", PAPER_PATH, READ_QUESTION, paths, READ_SCOPE, project=project, author_model=author,
                         verdict_type=gates.PAPER_READ, harness_root=harness_root, policy=policy, ledger=book)
    if not read.passed:
        _read_ticket(project, book, read, paths)
        return kill, read, []
    for identifier in earlier:
        steer_ticket(project, "cancel", identifier)
    return kill, read, ["cancelled scope-down ticket(s) %s, which this draft answered" % ", ".join(map(str, earlier))] if earlier else []


# --- the whole ------------------------------------------------------------------------------------


def _verdict_record(taken):
    if taken is None:
        return None
    return {"pass": taken.passed, "session_id": taken.session_id, "model": taken.model, "fallback_from": taken.fallback_from,
            "findings": [dict(finding) for finding in taken.findings]}


def summary(paper):
    """What one `wayline paper` came to, as `build.json` and `--json` both give it."""
    return {"venue": paper.venue, "path": str(paper.path), "status": paper.status,
            "venue_decided_by": "decider" if paper.decided is not None else "owner", "builds": paper.builds,
            "kill_argument": _verdict_record(paper.kill), "read": _verdict_record(paper.read), "tickets": paper.tickets,
            "claims": paper.claims, "notes": paper.notes, "submitted": False}


def _write_build(book, paper):
    book.write_json("%s/%s" % (PAPER_DIR, BUILD_JSON), dict(summary(paper), schema_version=1))


_TAKE_POINTS = ("take each into the text at the place it names, its claim tagged like any other, or say in `notes` why "
                "the text stands as it is")
RESUME_TEXT = (
    "The draft you returned was written to research/paper/ and built, and the figure role, drawing the figures it asks "
    "for, has points for the text they bear on. Return the whole draft again, through the structured output; "
    + _TAKE_POINTS + ":\n\n%s"
)
TEXT_POINTS = "\n\nThe figure role, drawing the figures the draft asks for, also has points for the text they bear on; " + _TAKE_POINTS + ":\n\n%s"


RESUME_GATE = (
    "The draft built, and the gate failed it: the points below stand, each at the locator the verifier read it at. "
    "Return the whole draft again, through the structured output, with each one answered: the evidence it asks for "
    "where the run has it, or the claim scoped down to what the artifacts support. Do not answer a point by "
    "asserting it away, and say in `notes` what only the owner can supply.\n\n%s"
)


RESUME_VENUE = (
    "The owner has moved this draft to %s. From this build on it is checked against that venue's guidelines, "
    "below, in place of the last venue's; write for its readers and its limits.\n\n```json\n%s\n```\n\n"
)


def _last_build(book, venue):
    """What a `--continue` takes up: `(venue, builds, session_id, message, last venue)` off `build.json`, or a `PaperError`.

    A draft left failing its build is resumed with that build's list; one the gate failed, with the points the kill
    argument or the read left standing, which is how a fail scopes the claims down with the same writer session.
    Whatever its status, a draft whose last build brought the figure role's points for the text, which no writer has
    read, is resumed with them too. `venue` moves the draft to another venue, which the command says to the writer
    with that venue's guidelines.
    """
    try:
        last = book.read_json("%s/%s" % (PAPER_DIR, BUILD_JSON))
    except (OSError, ValueError):
        raise PaperError("%s is not there; --continue takes up a draft `wayline paper` left failing its build" % BUILD_PATH) from None
    if not isinstance(last, dict):
        raise PaperError("%s is not a build record" % BUILD_PATH)
    builds = last.get("builds") or []
    points = builds[-1].get("for_writer") or [] if builds else []   # the last build's points, which no later build gave the writer
    if (last.get("status") not in (BUILD_FAILED, GATE_FAILED) and not points) or not builds or not builds[-1].get("session_id"):
        raise PaperError("the last draft is %s, neither failing its build nor failed by the gate, and it leaves no point for "
                         "the text unread; run wayline paper without --continue" % last.get("status"))
    if last["status"] == GATE_FAILED:
        failed = [taken for taken in (last.get("kill_argument"), last.get("read")) if taken and not taken.get("pass")]
        message = RESUME_GATE % "\n".join(gates.findings_text(taken["findings"]) for taken in failed)
        message += TEXT_POINTS % _point_lines(points) if points else ""
    else:
        message = _build_message(builds[-1]["failures"], points)
    return venue or last["venue"], builds, builds[-1]["session_id"], message, last["venue"]


def write_paper(project, venue=None, *, harness_root=HARNESS_ROOT, policy=None, draw_figure=None, say=None, verify=False,
                carry_on=False):
    """Draft `research/paper/` for `venue` (the decider's pick when None), build it until it passes or `MAX_BUILDS`, and gate it.

    Returns a `Paper`. `draw_figure` stands in for `draw`, the figure role's door, in a test; `say` hears progress;
    `verify` samples the draft's tagged claims after a gate that passed. `carry_on` (`--continue`) takes up the last
    draft that failed its build or the gate: the same writer session is resumed with that build's list or the points
    that stood, for up to `MAX_BUILDS` more builds, so the figures it asked for, and their requests, stay as they were;
    with `venue` it moves the draft there.
    Raises `PaperError` before anything is journaled when there is no report or the venue has no guidelines, and lets
    a usage window's refusal (`provenance.UsageLimited`, `gates.UsageLimited`) or the hold on Fable out to the caller.
    """
    project = Path(project).resolve()
    say = say or (lambda text: None)
    draw_figure = draw_figure or draw
    book = Ledger(project)
    if not (book.research / provenance.REPORT).is_file():
        raise PaperError("%s is not there; the paper is drafted after the report: run wayline report first" % provenance.REPORT_PATH)
    policy = policy_for(project, harness_root) if policy is None else policy
    decided, earlier, session_id, message = None, [], None, None
    if carry_on:
        venue, earlier, session_id, message, drafted_for = _last_build(book, venue)
    elif venue is None:
        decided = _choose_venue(project, harness_root, policy)
        venue = decided.answer
        say("venue     %s, the decider's pick (confidence %s): %s" % (venue, decided.confidence, " ".join(decided.rationale.split())))
    try:
        record = guidelines.read_guidelines(harness_root, venue)
    except guidelines.GuidelinesError as failure:
        raise PaperError("%s; the venues with guidelines are %s" % (failure, ", ".join(sorted(venues(harness_root))) or "none")) from None
    if carry_on and venue != drafted_for:
        message = RESUME_VENUE % (record["display_name"], _guideline_summary(record)) + message
    book.append_event(PAPER_STARTED, {"venue": venue})
    role = worker.read_role(WRITER, harness_root, project)
    request = provenance.structured_request(project, role, policy, harness_root, writer_prompt(role, project, record, harness_root),
                                  DRAFT_SCHEMA, WRITER_BUDGET, provenance.session_dir(project, SESSIONS), read_only=True)
    paper = Paper(venue=venue, path=book.research / PAPER_DIR / PAPER_MD, status=BUILD_FAILED, decided=decided, builds=list(earlier))
    files, waiting = {}, []
    for number in range(len(earlier) + 1, len(earlier) + MAX_BUILDS + 1):
        say("build %d    the writer on %s %s%s" % (number, request.model, request.effort, "" if session_id is None else ", with the list"))
        envelope = _answer(request, session_id, message)
        session_id = envelope.session_id or session_id
        draft = envelope.structured_output
        revise = {figure_id: figure["names"] for figure_id, figure in (paper.builds[-1].get("figures") or {}).items()
                  if figure.get("names")} if paper.builds else {}
        placed, points = _place(project, draft, record, policy, harness_root, draw_figure, say, revise)
        text, figure_problems, files = assemble(draft["markdown"], placed)
        book.remove_tree("%s/%s" % (PAPER_DIR, FIGURES_DIR))
        for name, source in files.items():
            book.write_bytes("%s/%s" % (PAPER_DIR, name), source.read_bytes())
        book.write_markdown("%s/%s" % (PAPER_DIR, PAPER_MD), text)
        lint, findings = check_build(project, record, text, harness_root=harness_root, policy=policy)
        failures, owners = _failures(lint, findings, figure_problems, record, files)
        waiting = sorted(figure_id for figure_id, figure in placed.items() if figure["state"] == WAITING)
        for_writer = _new_points(points, paper.builds)
        paper.builds.append({
            "build": number, "session_id": envelope.session_id, "model": envelope.model,
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "lint": {"pass": lint.passed, "claims": lint.claims, "tagged": lint.tagged, "problems": lint.problems},
            "checks": [finding._asdict() for finding in findings],
            "figures": {figure_id: {key: str(value) if isinstance(value, Path) else value for key, value in figure.items()}
                        for figure_id, figure in placed.items()},
            "failures": failures, "for_writer": for_writer, "owners": owners, "notes": draft["notes"],
        })
        say("build %d    linter %s (%d claims, %d tagged), checks %s, %d figure(s) placed%s%s" % (
            number, "pass" if lint.passed else "FAIL", lint.claims, lint.tagged, guidelines.worst(findings), len(files),
            ", %d failure(s)" % len(failures) if failures else "",
            ", %d point(s) for the text" % len(for_writer) if for_writer else ""))
        if not failures and not for_writer:
            break
        message = _build_message(failures, for_writer)
    if paper.builds[-1]["failures"]:
        paper.notes.append("the draft still failed its build after %d builds; no verdict was spent on it; "
                           "wayline paper --continue gives the same writer session %d more" % (MAX_BUILDS, MAX_BUILDS))
    if paper.builds[-1]["for_writer"]:
        late = sorted({item["figure_id"] for item in paper.builds[-1]["for_writer"]})
        paper.notes.append("%s had points for the text after the last build, so no writer has read them: build.json keeps them "
                           "under for_writer, and wayline paper --continue gives them to the writer"
                           % ", ".join("figure %s" % figure_id for figure_id in late))
    paper.notes.extend(paper.builds[-1]["owners"])
    if draft["notes"].strip():
        paper.notes.append("the writer: %s" % " ".join(draft["notes"].split()))
    if not paper.builds[-1]["failures"]:
        if waiting:
            paper.status = HELD
            paper.notes.append("figure(s) %s are not drawn yet; `wayline figure resume <figure_id>` once settled, then "
                               "wayline paper again. No verdict was spent on an unfinished draft" % ", ".join(waiting))
        else:
            say("gate      the kill argument and the independent read, on the verifier for %s" % request.model)
            paper.kill, paper.read, notes = _gate(project, book, record, request.model, policy, harness_root, files)
            paper.notes.extend(notes)
            paper.status = PASSED if paper.kill.passed and paper.read.passed else GATE_FAILED
            paper.tickets = [fields["id"] for fields in _scope_downs(project)] if paper.status == GATE_FAILED else []
            if verify and paper.status == PASSED:
                say("claims    the verifier's sample of the draft's tagged claims")
                paper.claims = provenance.verify_claims(project, harness_root=harness_root, policy=policy,
                                                        document=PAPER_PATH, prose_author=request.model)
                paper.tickets = paper.claims["tickets"]
    _write_build(book, paper)
    return paper


# --- the command ----------------------------------------------------------------------------------


def paper_command(args):
    """`wayline paper [--venue <slug>] [--continue] [--project <path>] [--verify] [--json]`."""
    parser = argparse.ArgumentParser(prog="wayline paper", description=(
        "draft research/paper/ under a venue's guidelines, build it with the linter and the seven checks, and gate it "
        "with the kill argument and one independent read; nothing is submitted"))
    parser.add_argument("--venue", help="the venue's slug under guidelines/ (default: the decider picks the best fit)")
    parser.add_argument("--project", help="the project (default: the active one)")
    parser.add_argument("--continue", dest="carry_on", action="store_true",
                        help="take up the last draft that failed its build or the gate: resume its writer session with what failed")
    parser.add_argument("--verify", action="store_true",
                        help="after a gate that passed, take a verdict on a sample of the draft's tagged claims (10 percent, at least ten)")
    parser.add_argument("--json", action="store_true", help="print the outcome as JSON")
    options, code = parse_args(parser, args)
    if options is None:
        return code
    try:
        project = find_project(options.project)
    except ProjectError as failure:
        print("wayline paper: %s" % failure, file=sys.stderr)
        return 2
    say = (lambda text: None) if options.json else print
    try:
        paper = write_paper(project, options.venue, say=say, verify=options.verify, carry_on=options.carry_on)
    except (PaperError, provenance.ProvenanceError, gates.GateError, guidelines.GuidelinesError, worker.LaunchError,
            worker.RoleError, tickets.TicketError, decider.DeciderError) as failure:
        print("wayline paper: %s" % failure, file=sys.stderr)
        return 1
    if options.json:
        print(json.dumps(summary(paper), ensure_ascii=False, indent=2))
    else:
        print(render(paper))
    return 0 if paper.status == PASSED and not (paper.claims and paper.claims["failed"]) else 1


def render(paper):
    """What the owner reads at the command: where the draft is, how it built, what the gate said, what was filed."""
    last = paper.builds[-1] if paper.builds else None
    lines = ["paper     %s (%s)" % (paper.path, paper.venue)]
    if last is not None:
        lines.append("builds    %d; the last: linter %s, %d of %d claim sentence(s) tagged; checks %s" % (
            len(paper.builds), "pass" if last["lint"]["pass"] else "FAIL", last["lint"]["tagged"], last["lint"]["claims"],
            guidelines.worst(guidelines.Finding(**finding) for finding in last["checks"])))
        lines.extend("  %s" % failure for failure in last["failures"])
    for name, taken in (("kill arg", paper.kill), ("read", paper.read)):
        if taken is not None:
            lines.append("%-9s %s, verifier session %s on %s%s" % (name, "pass" if taken.passed else "FAIL", taken.session_id, taken.model,
                                                                  " in place of %s" % taken.fallback_from if taken.fallback_from else ""))
            lines.extend("  - [%s] %s" % (finding.get("severity"), " ".join(str(finding.get("text", "")).split())) for finding in taken.findings)
    if paper.claims is not None:
        lines.append("claims    %d of %d tagged claims sampled: %d passed, %d failed, %d already had a verdict" % (
            paper.claims["sampled"], paper.claims["claims"], len(paper.claims["passed"]), len(paper.claims["failed"]),
            paper.claims["already_verdicted"]))
    if paper.tickets:
        lines.append("open      writing ticket(s) %s, to scope the claims down" % ", ".join(map(str, paper.tickets)))
    lines.extend("note      %s" % note for note in paper.notes)
    lines.append("status    %s; the owner reads research/paper/ and research/paper/build.json. Nothing was submitted." % paper.status)
    return "\n".join(lines)
