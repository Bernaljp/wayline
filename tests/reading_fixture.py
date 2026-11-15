"""The composed paper the reading view is tested on (ticket 141), modelled on the M8 toy's `research/paper/`.

Synthetic and invented, like every fixture. The parts are written as the toy's writer wrote them: the Results under an
objective's heading (`{#O1}`) and its results' headings (`{#R1}`, `{#R2}`), every claim sentence ending with its tags,
a `res` tag on an analysis file's key and one on a test file's pinned value (`BASE_AUROC`), `code` tags in Methods, a
verified reference and one still to be resolved in the Introduction, the owner's own passage in the Discussion, inline
and display math, and one main-text figure, F1, drawn by the figure role. Around the parts, what a run leaves: the
manifest with the two runs' files, the findings each result clusters (R1 and R2 under O1, R3 under O2, which is
parked), the claim classes the linter cached, a claim verdict that passed, a numbers check whose verifier failed, a
build whose sampled gate failed one claim, and two alternative titles.
"""

import hashlib
import json

from tests.compile_fixture import png
from tests.test_references_rendered import dossier
from wayline import dossier as dossiers
from wayline import objectives, paper, provenance, sections
from wayline.ledger import Ledger

TITLE = "An explicit product column raises the AUROC of a logistic model on one synthetic generator"
ALTERNATIVE = "A product column and the Bayes ceiling"
BASE_AUROC = "0.8352720450281426"

# The sentences the tests name, each as the part holds it, tags and all.
GAIN = ("Over 20 paired seeds the column lifts the mean held-out AUROC from 0.7681 to 0.8552, a mean paired gain of "
        "0.0872. {res:t12-a1/analysis/E2/paired.json#mean_auroc_without} {res:t12-a1/analysis/E2/paired.json#mean_auroc_with} "
        "{res:t12-a1/analysis/E2/paired.json#paired_gain}")
CLOSES = "The gain closes 0.990 of the gap to the Bayes ceiling. {res:t12-a1/analysis/E2/paired.json#gap_closed}"
POSITIVE = "All 20 per-seed differences are positive. {res:t12-a1/analysis/E2/paired.json#n_positive_d}"
PINNED = ("At the base commit the smoke run gives a held-out AUROC of %s. {res:t3-a1/tests/test_train.py#BASE_AUROC}"
          % BASE_AUROC)
ARMS = "Both arms draw identical initial weights from the shared seed. {code:src/toy/train.py#ready_interactions}"
UNTAGGED = "Interaction terms are known to help linear models on data with planted products."
TRANSITION = "The next two sections take these in turn."
LOST = "The first handed-over work could not be read, and it has not been verified (to be resolved). {ref:paper-a#existence}"
RULES = "Rule ensembles find which variables interact. {ref:friedman-2008-rules#abstract}"
OWNERS = "The generator is synthetic, so the gain says nothing about data from outside it."
EARLIER = "An earlier draft reported the same lift. {doc:D1#p3}"
PARKED = "The goal run reaches 0.8503 on held-out rows. {res:t12-a1/analysis/E2/paired.json#goal_run_auroc}"

TEXTS = {
    "title": TITLE + "\n",
    "abstract": ("We ask whether an explicit product column, $x_3x_4$, raises the held-out AUROC of a logistic model. "
                 "{res:t12-a1/analysis/E2/paired.json#paired_gain} " + GAIN + "\n"),
    "introduction": ("## Interactions in linear models {#introduction-interactions}\n\n" + UNTAGGED + " " + RULES + "\n\n"
                     + LOST + " " + TRANSITION + "\n"),
    "results": ("## Does the product column help, and by how much? {#O1}\n\n"
                "### The column lifts the AUROC to near the ceiling {#R1}\n\n" + GAIN + " " + CLOSES + " " + POSITIVE + "\n\n"
                "As @fig:F1 shows, the lift holds at every seed. {res:t12-a1/analysis/E2/paired.json#n_positive_d}\n\n"
                "### Adding the flags leaves the default run unchanged {#R2}\n\n" + PINNED + "\n\n"
                "## Does the project meet its goal? {#O2}\n\n### The goal run {#R3}\n\n" + PARKED + "\n"),
    "discussion": "## Scope {#discussion-scope}\n\n" + OWNERS + " " + EARLIER + "\n",
    "methods": ("## The two arms {#methods-arms}\n\nEach label is drawn from the log-odds "
                "$\\mu(x)=0.6x_1-0.4x_2+1.1\\,x_3x_4$. {code:src/toy/generate.py#L23-L39} " + ARMS + "\n"),
    "supplement": "Nothing is placed in the supplement.\n",
    "front": "# Front matter\n\n## Authors\n\n- Ada Lovelace^1^\n",
}

PAIRED = {"mean_auroc_without": 0.7681, "mean_auroc_with": 0.8552, "paired_gain": 0.0872, "gap_closed": 0.99,
          "n_positive_d": 20, "goal_run_auroc": 0.8503}
TEST_TRAIN = "import unittest\n\nBASE_AUROC = %s\n\n\nclass Smoke(unittest.TestCase):\n    pass\n" % BASE_AUROC
TRAIN = "def ready_interactions(rows):\n    return rows\n"
GENERATE = "".join("# line %d\n" % number for number in range(1, 23)) + "".join(
    "mu = 0.6 * x1  # line %d\n" % number for number in range(23, 40))

FIGURE_ID = "paper-r1-main"
FIGURE_CAPTION = "**The column lifts every seed.** Paired AUROC with and without the column, one line per seed. {plot:R1.1}"
HONESTY_FINDING = "The panel's y axis starts at 0.7, which the caption says."


def sentence_digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def claim_subject(text):
    """The verdict subject a sampled claim of the paper is judged under, as the paper's builds name it."""
    found = provenance.prose_sentences(text)[0]
    return provenance.claim_subject(provenance.Claim(found.text, found.tags, provenance.sentence_hash(found.text)),
                                    "research/paper")


def _verdict(book, subject, verdict_type, passed, findings=(), ticket=None, session="a1b2c3d4"):
    book.append_event("verdict", {"subject_kind": "claim", "subject": subject, "verdict_type": verdict_type, "pass": passed,
                                  "session_id": session, "model": "claude-opus-5-5", "findings": list(findings), "rung": None,
                                  "fallback_from": None, "model_ran": "claude-opus-5-5"}, ticket=ticket, session_id=session)


def make_reading_paper(project):
    """Write the composed paper and what a run leaves around it into an initialized `project`; returns its ledger."""
    book = Ledger(project)
    for relative, text in (("analysis/E2/paired.json", json.dumps(PAIRED, indent=1) + "\n"),
                           ("tests/test_train.py", TEST_TRAIN), ("code/src/toy/train.py", TRAIN),
                           ("code/src/toy/generate.py", GENERATE)):
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    provenance.register_artifact(book, "analysis/E2/paired.json", None, "t12-a1", 12)
    provenance.register_artifact(book, "tests/test_train.py", None, "t3-a1", 3)

    objectives.add_objective(project, "Does the product column help, and by how much?")
    objectives.add_objective(project, "Does the project meet its goal?")
    objectives.change_objective(project, "O2", "parked", by="owner")
    for identifier, ticket, text, heading, goal, cited in (
            ("t12-a1-f1", 12, GAIN, "The column lifts the AUROC to near the ceiling", "O1", "analysis/E2/paired.json#paired_gain"),
            ("t3-a1-f1", 3, PINNED, "Adding the flags leaves the default run unchanged", "O1", "tests/test_train.py#BASE_AUROC"),
            ("t12-a1-f2", 12, PARKED, "The goal run", "O2", "analysis/E2/paired.json#goal_run_auroc")):
        sections.file_finding(book, {"id": identifier, "ticket": ticket, "text": text, "provenance": [cited], "negative": False,
                                     "heading": heading, "replaces": None, "objectives": [goal]})
    sections.add_passage(book, "discussion", "Scope", OWNERS, by="owner")

    dossiers.write_l0(book, dossier("friedman-2008-rules", title="Predictive learning via rule ensembles",
                                    authors=("J. Friedman", "B. Popescu"), year=2008, container="Annals of Applied Statistics",
                                    identifiers={"doi": "10.5555/rules"}))
    dossiers.write_l0(book, dossier("paper-a", existence="unresolved", query={"kind": "title", "value": "materials/paper-a.pdf"}))

    for part, text in TEXTS.items():
        book.write_markdown("paper/%s.md" % part, text)
    book.write_markdown("paper/alternatives/title-1.md", TITLE + "\n")
    book.write_markdown("paper/alternatives/title-2.md", ALTERNATIVE + "\n\n<!-- why: shorter -->\n")
    book.write_bytes("paper/figures/F1/F1.png", png())
    book.write_markdown("paper/figures/F1/caption.md", FIGURE_CAPTION + "\n")

    figure = project / "figures" / FIGURE_ID
    (figure / "final").mkdir(parents=True, exist_ok=True)
    (figure / "final" / "F1.py").write_text("print('draws F1')\n", encoding="utf-8")
    (figure / "final" / "F1.png").write_bytes(png())
    (figure / "candidates").mkdir(parents=True, exist_ok=True)
    (figure / "candidates" / "c1.png").write_bytes(png())
    (figure / "figure_result.json").write_text(json.dumps({
        "schema": "figure_result/1", "ticket": "paper", "figure_id": FIGURE_ID, "version": 1, "status": "verified",
        "candidates": [{"rank": 1, "index_id": "paired_lines", "chart_type": "paired lines", "png": "figures/%s/candidates/c1.png" % FIGURE_ID,
                        "rendered": True},
                       {"rank": 2, "index_id": "box_by_arm", "chart_type": "box by arm", "png": None, "rendered": False,
                        "error": "the library could not draw it"}],
        "selected": {"rank": 1, "by": "decider", "margin": 0.4, "margin_low": False},
        "final": {"generator": "figures/%s/final/F1.py" % FIGURE_ID, "png": "figures/%s/final/F1.png" % FIGURE_ID, "pdf": None,
                  "caption": FIGURE_CAPTION, "notes": "one line per seed",
                  "inputs": [{"path": "analysis/E2/paired.json", "sha256": "0" * 64, "run_id": "t12-a1"}]},
        "checks": [{"id": "fonts_embedded", "type": "A", "pass": True, "tool": "pdffonts", "detail": "every font embedded"},
                   {"id": "min_font_size", "type": "A", "pass": True, "tool": "svg", "detail": "the smallest text is 7 pt"}],
        "honesty_verdict": {"type": "B", "verdict": "pass", "session": "e5f6", "model": "claude-opus-5-5",
                            "findings": [{"rule": "implied_claim", "text": HONESTY_FINDING, "locator": None}]},
    }, indent=1) + "\n", encoding="utf-8")

    classes = {provenance.sentence_hash(text): provenance.CLAIM for text in (UNTAGGED, OWNERS)}
    classes[provenance.sentence_hash(TRANSITION)] = provenance.TRANSITION
    book.write_json(provenance.CLAIMS_CACHE, {"schema_version": 1, "classes": classes})

    _verdict(book, claim_subject(GAIN), "claim_support", True, ticket=None)
    _verdict(book, "ticket 12#numbers-%s" % sentence_digest(CLOSES), "numbers_match", False, ticket=12,
             findings=[{"severity": "major", "text": "gap_closed holds 0.99, which the sentence writes as 0.990 of the gap; "
                                                   "the analysis file does not hold the third place", "locator": "analysis/E2/paired.json#gap_closed"}])
    _verdict(book, claim_subject(POSITIVE), "claim_support", False,
             findings=[{"severity": "major", "text": "n_positive_d counts seeds, not differences", "locator": "analysis/E2/paired.json#n_positive_d"}])

    plain = " ".join(provenance.strip_tags(POSITIVE).split())
    book.write_json("paper/paper.json", {
        "version": 2, "order": 2, "by": "owner", "commit": None, "composed": "2026-10-25T14:16:00.380Z", "model": "claude-opus-5-5",
        "parts": {part: {"version": 2, "inputs": "0" * 64, "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}
                  for part, text in TEXTS.items()},
        "tables": [], "alternatives": ["title-1", "title-2"],
        "answers": [{"ref": "reference:paper-a", "text": "Unresolved reference paper-a", "mark": paper.TO_BE_RESOLVED, "by": "code",
                     "batch": None, "item": None, "note": None}],
        "unchecked": None, "left_out": [], "proposals": [], "reworded": [], "kept_edits": [],
        "figures": {"venue": None, "limit": None, "figures": [
            {"id": "F1", "result": "R1", "main": True, "panels": ["R1.1"], "line": "F1 (R1): R1.1", "figure_id": FIGURE_ID,
             "key": "0" * 64, "status": "verified", "version": 1, "reused": False, "reason": None, "findings_for_text": []}],
            "tables": [], "moved": [], "without": ["R2", "R3"]},
        "builds": [{"build": 1, "passed": False, "gates": [
            {"gate": "kill_argument", "pass": True, "session_id": "k1", "model": "claude-opus-5-5", "fallback_from": None,
             "points": [], "note": None},
            {"gate": "sampled_verdicts", "pass": False, "session_id": None, "model": None, "fallback_from": None,
             "points": ['the claim "%s" is not supported: n_positive_d counts seeds, not differences' % plain],
             "note": "3 claim(s) never sampled, 2 drawn, 2 judged now"}]}],
        "gated": True, "outcome": None, "usage": None,
    }, schema="paper")
    book.append_event("paper_order", {"order": 2, "action": "ordered", "by": "owner", "run": "stopped", "batch": None, "venue": None})
    book.append_event("paper_order", {"order": 2, "action": "composed", "by": "owner", "version": 2, "commit": None,
                                      "parts": list(paper.PARTS), "build": 1})
    return book
