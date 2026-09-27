"""The paper on request: the venue, the writer's builds, the figures, and the gate (ticket 53).

Every model call goes through the fake launcher: the writer and the verifier by scripted envelopes, the
classifier by the responder of `tests.test_report`, the decider by a scripted decision. The figure role is
stood in for at its one door (`draw_figure`), except where the test is about that door. What is asserted is what
the owner and the next component see: `research/paper/` on disk, its `build.json`, the journal's
`paper_started`, `decision`, and `verdict` events, the requests the figure role was sent, and the `writing`
tickets a failed gate files.
"""

import io
import json
import shutil
import struct
import unittest
import zlib
from contextlib import redirect_stderr, redirect_stdout

from tests.paths import FIXTURES_DIR
from tests.projects import ProjectTestCase
from tests.test_report import Classifier
from wayline import HARNESS_ROOT, cli, decider, dashboard, figure_role, gates, paper, provenance, tickets, worker
from wayline.ledger import Ledger
from wayline.worker import Envelope

ENDED_RUN = FIXTURES_DIR / "projects" / "ended-run"

INTERACTIONS = "{res:t3-a1/results/interactions/summary.json#auroc_mean}"
BASELINE = "{res:t2-a1/results/baseline/summary.json#auroc_mean}"
DEPTH = "{res:t4-a1/results/depth/summary.json#auroc_mean}"
PAPER_A = "{ref:paper-a#s3}"

GOOD = "\n".join([
    "# Interaction terms carry the held-out gain",
    "",
    "## Abstract",
    "",
    "Pairwise interaction terms raise the held-out AUROC to 0.861." + INTERACTIONS,
    "",
    "## Results",
    "",
    "The baseline reaches a held-out AUROC of 0.812." + BASELINE,
    "AUROC means the area under the receiver operating characteristic curve.",
    "Interaction features helped tabular classifiers before [1]." + PAPER_A,
    "Depth alone does not reach the goal." + DEPTH,
    "",
    "## References",
    "",
    "[1] Interaction features for tabular classification, 2021.",
    "",
])
UNTAGGED = GOOD.replace("The baseline reaches a held-out AUROC of 0.812." + BASELINE, "The baseline reaches a held-out AUROC of 0.812.")
WITH_FIGURE = GOOD.replace("## References", "{figure:gain}\n\n## References")

GAIN = {"figure_id": "gain", "claim": "Pairwise interaction terms raise the held-out AUROC over the baseline.",
        "claim_type": "comparison", "data": ["results/interactions/summary.json", "results/baseline/summary.json"],
        "evidence": [INTERACTIONS, BASELINE]}


def draft(markdown=GOOD, figures=(), notes=""):
    return Envelope(structured_output={"markdown": markdown, "figures": list(figures), "notes": notes})


def verdict(passed=True, text="The abstract states 0.861 as a gain without its interval.", locator="research/paper/paper.md#abstract"):
    findings = [] if passed else [{"text": text, "locator": locator, "severity": "major"}]
    return Envelope(structured_output={"pass": passed, "findings": findings, "question_limit": "Only this draft against its paths."})


def decision(answer):
    return Envelope(structured_output={"question": "as asked", "options": [], "answer": answer,
                                       "rationale": "arXiv takes the draft as it is and names no form.", "confidence": 0.8,
                                       "decided_by": "decider", "reversible": True, "timestamp": None})


def png(path, dpi=300):
    """A one-pixel RGB PNG whose `pHYs` says `dpi`, which is all the figure check reads of it."""
    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
    per_metre = round(dpi / 0.0254)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
                     + chunk(b"pHYs", struct.pack(">IIB", per_metre, per_metre, 1))
                     + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00")) + chunk(b"IEND", b""))
    return path


class Figures:
    """The figure role's door, scripted: records every request and answers each with the next result."""

    def __init__(self, project, *statuses):
        self.project, self.statuses, self.requests = project, list(statuses), []

    def __call__(self, project, request, **options):
        self.requests.append(request)
        status = self.statuses.pop(0) if self.statuses else "verified"
        result = {"schema": "figure_result/1", "figure_id": request["figure_id"], "version": len(self.requests), "status": status}
        if status == "verified":
            png(self.project / "figures" / request["figure_id"] / "final.png")
            result["final"] = {"png": "figures/%s/final.png" % request["figure_id"], "pdf": None,
                               "caption": "Figure 1. Held-out AUROC by arm. (a) Each arm's mean over three seeds."}
            return result, None
        if status == "honesty_failed":
            result["honesty_verdict"] = {"type": "B", "verdict": "fail", "findings": [{"text": "the bars hide the overlap of the intervals"}]}
            return result, None
        return result, "the pick is the owner's: decision ticket 12"


class PaperCase(ProjectTestCase):
    """A writable copy of the ended run with its report on disk, and the launcher faked."""

    def setUp(self):
        super().setUp()
        self.project = self.temp / "ended-run"
        shutil.copytree(ENDED_RUN, self.project)
        self.book = Ledger(self.project)
        self.book.write_markdown("REPORT.md", "# Report: ended-run\n\nThe report as rendered.\n")
        self.calls = []

    def write(self, *writer, verifier=(), deciders=(), venue="arxiv", draw_figure=None, verify=False):
        """`write_paper` with the writer's and the verifier's envelopes scripted in order."""
        with worker.use_fake() as fake:
            self.classifier = Classifier()
            for _ in range(6):
                fake.script(respond=self.classifier, role="classifier")
            for envelope in writer:
                fake.script(envelope, role="writer")
            for envelope in verifier:
                fake.script(envelope, role="verifier")
            for envelope in deciders:
                fake.script(envelope, role="decider")
            try:
                return paper.write_paper(self.project, venue, draw_figure=draw_figure, verify=verify)
            finally:
                self.calls = list(fake.calls)

    def events(self, name):
        found, _ = self.book.read_events()
        return [event for event in found if event["event"] == name]

    def paper_verdicts(self):
        """The `verdict` payloads about the paper: the fixture's journal already holds its tickets' own."""
        return [event["payload"] for event in self.events("verdict") if event["payload"]["subject_kind"] == "paper"]

    def calls_of(self, role):
        return [call for call in self.calls if call.request.role == role]

    def text(self):
        return (self.project / "research" / "paper" / "paper.md").read_text(encoding="utf-8")

    def build(self):
        return json.loads((self.project / "research" / "paper" / "build.json").read_text(encoding="utf-8"))


PASSING_GATE = (verdict(), verdict(), verdict())   # the memo finds no case, the adjudication and the read pass


class DraftTest(PaperCase):
    def test_a_draft_that_builds_is_written_linted_checked_and_gated(self):
        written = self.write(draft(), verifier=PASSING_GATE)
        self.assertEqual(written.status, paper.PASSED)
        self.assertEqual(len(written.builds), 1)
        self.assertIn("Pairwise interaction terms raise the held-out AUROC to 0.861." + INTERACTIONS, self.text())
        self.assertEqual([event["payload"] for event in self.events("paper_started")], [{"venue": "arxiv"}])
        build = self.build()
        self.assertEqual((build["status"], build["venue"], build["submitted"]), ("passed", "arxiv", False))
        self.assertTrue(build["builds"][0]["lint"]["pass"])
        self.assertEqual(build["builds"][0]["lint"]["claims"], build["builds"][0]["lint"]["tagged"])
        self.assertEqual({finding["check"] for finding in build["builds"][0]["checks"]},
                         {"length", "structure", "figures", "references", "reporting_checklists", "template", "provenance"})

    def test_the_writer_is_one_read_only_session_on_the_writer_s_tier(self):
        self.write(draft(), verifier=PASSING_GATE)
        (call,) = self.calls_of("writer")
        self.assertEqual((call.request.model, call.request.effort), ("opus", "xhigh"))
        self.assertFalse(set(call.request.allowed_tools) - set(provenance.READ_ONLY_TOOLS))
        self.assertTrue(str(call.request.schema_path).endswith("paper_draft.json"))
        for said in ("arXiv", "research/REPORT.md", INTERACTIONS, "`paper-a`", "`results/interactions/summary.json` (run t3-a1)",
                     "{figure:<figure_id>}"):
            self.assertIn(said, call.request.prompt)

    def test_the_reference_list_is_not_read_as_claims(self):
        self.write(draft(), verifier=PASSING_GATE)
        sent = [text for batch in self.classifier.batches for text in batch]
        self.assertFalse([text for text in sent if "2021" in text and text.startswith("[1]")])
        self.assertIn("[1] Interaction features for tabular classification, 2021.", self.text())

    def test_a_reference_list_under_another_name_is_fenced_too(self):
        for heading in ("Works cited", "Reference list", "Bibliography"):
            fenced = paper.fence_references("## Results\n\nIt holds.\n\n## %s\n\n[1] A paper, 2021.\n" % heading)
            self.assertEqual([sentence.text for sentence in provenance.prose_sentences(fenced)], ["It holds."], heading)

    def test_no_report_means_no_paper_and_nothing_journaled(self):
        (self.project / "research" / "REPORT.md").unlink()
        with self.assertRaisesRegex(paper.PaperError, "wayline report first"):
            self.write(draft())
        self.assertEqual(self.events("paper_started"), [])
        self.assertEqual(self.calls, [])

    def test_a_venue_with_no_guidelines_is_refused_with_the_ones_there_are(self):
        with self.assertRaisesRegex(paper.PaperError, "nature-methods"):
            self.write(draft(), venue="the-lancet")
        self.assertEqual(self.events("paper_started"), [])


class BuildTest(PaperCase):
    def test_a_lint_failure_goes_back_to_the_same_writer_session_with_the_list(self):
        written = self.write(draft(UNTAGGED), draft(), verifier=PASSING_GATE)
        self.assertEqual((written.status, len(written.builds)), (paper.PASSED, 2))
        first, second = self.calls_of("writer")
        self.assertEqual((first.kind, second.kind), ("launch", "resume"))
        self.assertIn("untagged_claim", second.message)
        self.assertIn("The baseline reaches a held-out AUROC of 0.812.", second.message)
        self.assertFalse(self.build()["builds"][0]["lint"]["pass"])

    def test_a_failing_check_of_the_venue_goes_back_with_its_message(self):
        # PLOS Computational Biology is not structure-flexible, so a missing section fails the draft there.
        written = self.write(*[draft()] * paper.MAX_BUILDS, venue="plos-compbiol")
        self.assertEqual(written.status, paper.BUILD_FAILED)
        second = self.calls_of("writer")[1]
        self.assertIn("check `structure`: missing sections", second.message)
        self.assertIn("Author summary", second.message)

    def test_a_draft_that_never_builds_spends_no_verdict(self):
        written = self.write(*[draft(UNTAGGED)] * paper.MAX_BUILDS)
        self.assertEqual((written.status, len(written.builds)), (paper.BUILD_FAILED, paper.MAX_BUILDS))
        self.assertEqual(self.calls_of("verifier"), [])
        self.assertEqual(self.paper_verdicts(), [])
        self.assertIn("no verdict was spent", " ".join(written.notes))
        self.assertEqual(self.build()["status"], "build_failed")


class FigureTest(PaperCase):
    def test_a_figure_is_asked_for_at_the_venue_s_target_and_placed_with_its_caption(self):
        figures = Figures(self.project)
        written = self.write(draft(WITH_FIGURE, [GAIN]), verifier=PASSING_GATE, draw_figure=figures)
        self.assertEqual(written.status, paper.PASSED)
        (request,) = figures.requests
        self.assertEqual(request["target"]["venue"], "arxiv")
        self.assertEqual(request["target"]["formats"], ["pdf", "png"])
        self.assertEqual((request["target"]["width_mm"], request["target"]["min_dpi"]), (89, 300))
        manifest = {entry["path"]: entry for entry in provenance.read_manifest(self.project)["entries"]}
        self.assertEqual(request["data"], [{"path": path, "sha256": manifest[path]["sha256"], "run_id": manifest[path]["run_id"]}
                                           for path in GAIN["data"]])
        self.assertEqual((request["claim"]["text"], request["kind"], request["mode"]), (GAIN["claim"], "result", "unguided"))
        text = self.text()
        self.assertIn("\n".join([provenance.RECORDS_BEGIN, "![Figure 1](figures/gain.png)", "",
                                 "**Figure 1.** Held-out AUROC by arm. (a) Each arm's mean over three seeds.", provenance.RECORDS_END]), text)
        self.assertNotIn("{figure:", text)
        self.assertTrue((self.project / "research" / "paper" / "figures" / "gain.png").is_file())
        figures_check = [finding for finding in self.build()["builds"][0]["checks"] if finding["check"] == "figures"]
        self.assertEqual([finding["level"] for finding in figures_check], ["ok"])

    def test_the_venue_s_resolution_and_formats_reach_the_target(self):
        record = json.loads((HARNESS_ROOT / "guidelines" / "plos-compbiol" / "guidelines.json").read_text(encoding="utf-8"))
        record["figure_spec"]["min_dpi"] = 600
        record["figure_spec"]["formats"] = ["PDF", "TIFF"]
        target = paper.figure_target(record, self.project)
        self.assertEqual((target["min_dpi"], target["formats"], target["library"]), (600, ["pdf"], "matplotlib"))

    def test_a_figure_the_role_failed_goes_back_to_the_writer_with_the_verdict(self):
        figures = Figures(self.project, "honesty_failed")
        written = self.write(draft(WITH_FIGURE, [GAIN]), draft(), verifier=PASSING_GATE, draw_figure=figures)
        self.assertEqual((written.status, len(written.builds)), (paper.PASSED, 2))
        message = self.calls_of("writer")[1].message
        self.assertIn("figure gain could not be placed: the figure role ended honesty_failed", message)
        self.assertIn("the bars hide the overlap of the intervals", message)

    def test_a_request_the_figure_role_refuses_goes_back_to_the_writer(self):
        def refuse(project, request, **options):
            raise figure_role.FigureError("the request is not a figure_request/1: target: bad")
        written = self.write(draft(WITH_FIGURE, [GAIN]), draft(), verifier=PASSING_GATE, draw_figure=refuse)
        self.assertEqual(written.status, paper.PASSED)
        self.assertIn("figure gain could not be placed: the figure role refused the request", self.calls_of("writer")[1].message)

    def test_a_window_that_refuses_the_figure_role_stops_the_paper(self):
        def refused(project, request, **options):
            raise gates.UsageLimited("the figure critic was refused by the usage limit")
        with self.assertRaises(gates.UsageLimited):
            self.write(draft(WITH_FIGURE, [GAIN]), draw_figure=refused)
        self.assertEqual(self.calls_of("verifier"), [])

    def test_a_format_only_the_owner_can_convert_is_a_note_not_a_failure(self):
        # PLOS Computational Biology takes TIFF and EPS, which the figure role does not draw.
        record = paper.guidelines.read_guidelines(HARNESS_ROOT, "plos-compbiol")
        finding = paper.guidelines.Finding("figures", "fail", "gain.png is PNG; PLOS Computational Biology accepts EPS, TIFF.")
        lint = provenance.Lint(passed=True, claims=0, tagged=0, unclassified=0)
        failures, notes = paper._failures(lint, [finding], [], record, {"figures/gain.png": None})
        self.assertEqual(failures, [])
        self.assertEqual(notes, ["gain.png is PNG; PLOS Computational Biology accepts EPS, TIFF.: the figure role draws PDF and PNG, "
                                 "so converting it for the venue is the owner's"])

    def test_data_outside_the_manifest_is_refused_without_drawing(self):
        figures = Figures(self.project)
        asked = dict(GAIN, data=["results/nowhere.json"])
        self.write(draft(WITH_FIGURE, [asked]), draft(), verifier=PASSING_GATE, draw_figure=figures)
        self.assertEqual(figures.requests, [])
        self.assertIn("results/nowhere.json is not in research/manifest.json", self.calls_of("writer")[1].message)

    def test_a_figure_that_waits_on_the_owner_holds_the_gate(self):
        written = self.write(draft(WITH_FIGURE, [GAIN]), draw_figure=Figures(self.project, "candidates_ranked"))
        self.assertEqual(written.status, paper.HELD)
        self.assertEqual(self.calls_of("verifier"), [])
        self.assertIn("*[Figure gain is not drawn yet: the pick is the owner's: decision ticket 12.]*", self.text())

    def test_a_placeholder_for_no_figure_and_a_figure_placed_nowhere_are_both_listed(self):
        text, problems, files = paper.assemble(GOOD + "\n{figure:other}\n", {"gain": {"state": paper.PLACED}})
        self.assertEqual(files, {})
        self.assertEqual([problem["detail"].split(":")[0] for problem in problems],
                         ["the draft places {figure", "figure gain was asked for and placed nowhere"])

    def test_the_same_request_is_not_drawn_again(self):
        request = paper.figure_request(GAIN, paper.guidelines.read_guidelines(HARNESS_ROOT, "arxiv"), self.project,
                                       provenance.read_manifest(self.project))
        directory = self.project / "figures" / "gain"
        directory.mkdir(parents=True)
        (directory / "request.json").write_text(json.dumps(request), encoding="utf-8")
        (directory / "figure_result.json").write_text(json.dumps({"figure_id": "gain", "version": 1, "status": "verified"}), encoding="utf-8")
        with worker.use_fake() as fake:
            result, reason = paper.draw(self.project, request)
            self.assertEqual(fake.calls, [])
        self.assertEqual((result["status"], reason), ("verified", None))


class GateTest(PaperCase):
    def test_both_verdicts_are_journaled_on_the_paper_on_the_writer_s_verifier(self):
        self.write(draft(), verifier=PASSING_GATE)
        verdicts = self.paper_verdicts()
        self.assertEqual([(payload["subject_kind"], payload["subject"], payload["verdict_type"]) for payload in verdicts],
                         [("paper", paper.PAPER_PATH, gates.KILL_ARGUMENT), ("paper", paper.PAPER_PATH, gates.PAPER_READ)])
        calls = self.calls_of("verifier")
        self.assertEqual(len(calls), 3)
        self.assertEqual({(call.request.model, call.request.effort) for call in calls}, {("opus", "max")})
        self.assertEqual(len({call.request.run_dir for call in calls}), 3)
        for call in calls:
            self.assertIn(paper.PAPER_PATH, call.request.prompt)
            self.assertIn("guidelines/arxiv/guidelines.json", call.request.prompt)

    def test_a_kill_argument_that_stands_files_a_writing_ticket_and_spends_no_read(self):
        written = self.write(draft(), verifier=(verdict(False), verdict(False)))
        self.assertEqual(written.status, paper.GATE_FAILED)
        self.assertEqual(len(self.calls_of("verifier")), 2)
        self.assertIsNone(written.read)
        (ticket,) = [fields for fields in tickets.read_tickets(self.project) if fields["id"] in written.tickets]
        self.assertEqual((ticket["kind"], ticket["origin"], ticket["touches"]), ("writing", paper.PAPER_PATH, [paper.PAPER_PATH]))
        self.assertFalse(self.build()["kill_argument"]["pass"])
        self.assertIsNone(self.build()["read"])

    def test_a_point_that_stands_again_files_no_second_ticket(self):
        first = self.write(draft(), verifier=(verdict(False), verdict(False)))
        again = self.write(draft(), verifier=(verdict(False), verdict(False)))
        self.assertEqual(first.tickets, again.tickets)
        self.assertEqual(len([fields for fields in tickets.read_tickets(self.project) if fields["kind"] == "writing"]), 1)

    def test_a_read_that_fails_files_a_ticket_the_next_draft_is_given_and_a_pass_cancels(self):
        written = self.write(draft(), verifier=(verdict(), verdict(), verdict(False)))
        self.assertEqual(written.status, paper.GATE_FAILED)
        (ticket,) = [fields for fields in tickets.read_tickets(self.project) if fields["id"] in written.tickets]
        self.assertEqual((ticket["title"], ticket["origin"]), (paper.READ_TITLE, paper.PAPER_PATH + "#read"))
        passed = self.write(draft(), verifier=PASSING_GATE)
        prompt = self.calls_of("writer")[0].request.prompt
        self.assertIn("# What the last gate left standing", prompt)
        self.assertIn(tickets.filename(ticket), prompt)
        self.assertEqual((passed.status, passed.tickets), (paper.PASSED, []))
        cancels = [event["payload"] for event in self.events("control") if event["payload"].get("command") == "cancel"]
        self.assertEqual([payload["args"]["ticket"] for payload in cancels], [ticket["id"]])

    def test_verify_samples_the_draft_s_claims_after_a_gate_that_passed(self):
        claims = [verdict() for _ in range(4)]
        written = self.write(draft(), verifier=PASSING_GATE + tuple(claims), verify=True)
        self.assertEqual(written.status, paper.PASSED)
        self.assertEqual(written.claims["sampled"], written.claims["claims"])
        sampled = [payload for payload in (event["payload"] for event in self.events("verdict")) if payload["subject_kind"] == "claim"]
        self.assertEqual(len(sampled), written.claims["claims"])
        self.assertTrue(all(payload["subject"].startswith(paper.PAPER_PATH + "#claim-") for payload in sampled))


class VenueTest(PaperCase):
    def test_without_a_venue_the_decider_picks_one_and_it_is_journaled(self):
        written = self.write(draft(), verifier=PASSING_GATE, deciders=[decision("arxiv")], venue=None)
        self.assertEqual(written.venue, "arxiv")
        (event,) = self.events("decision")[-1:]
        self.assertEqual((event["payload"]["answer"], event["payload"]["decided_by"], event["payload"]["ticket"]),
                         ("paper venue: arxiv", "decider", None))
        self.assertEqual([event["payload"] for event in self.events("paper_started")], [{"venue": "arxiv"}])
        prompt = self.calls_of("decider")[0].request.prompt
        self.assertIn("- subject: the venue of the paper", prompt)
        for slug in ("nature-methods", "plos-compbiol", "arxiv", "neurips"):
            self.assertIn(slug, prompt)
        self.assertEqual(self.build()["venue_decided_by"], "decider")

    def test_a_decider_that_names_no_venue_stops_before_the_paper_starts(self):
        with self.assertRaisesRegex(paper.PaperError, "did not pick a venue"):
            self.write(draft(), deciders=[decision("a good journal")], venue=None)
        self.assertEqual(self.events("paper_started"), [])
        self.assertEqual(self.calls_of("writer"), [])

    def test_the_answer_is_read_for_one_whole_slug(self):
        known = {"nature": "Nature", "nature-methods": "Nature Methods", "arxiv": "arXiv"}
        self.assertEqual(decider.venue_of("nature-methods", known), "nature-methods")
        self.assertEqual(decider.venue_of("Nature Methods fits: the run is a method.", known), "nature-methods")
        self.assertEqual(decider.venue_of("Nature Methods", known), "nature-methods")
        self.assertEqual(decider.venue_of("I would send it to `nature`.", known), "nature")
        self.assertEqual(decider.venue_of("option 1", known), "arxiv")
        self.assertIsNone(decider.venue_of("nature or arxiv", known))

    def test_the_report_lists_the_venue_among_the_decider_s_decisions(self):
        self.write(draft(), verifier=PASSING_GATE, deciders=[decision("arxiv")], venue=None)
        section = "\n".join(provenance._decider_decisions(provenance.report_context(self.project)))
        self.assertIn("The paper's venue: **paper venue: arxiv**", section)


class NothingIsSubmittedTest(unittest.TestCase):
    def test_no_verb_or_dashboard_action_submits(self):
        for verb in cli.VERBS:
            self.assertNotIn("submit", verb.name)
            self.assertNotRegex(verb.usage, r"\bsubmit")
        self.assertFalse([action for action in dashboard.ACTIONS if "submit" in action])

    def test_the_paper_reaches_no_network_and_its_roles_cannot(self):
        source = (HARNESS_ROOT / "wayline" / "paper.py").read_text(encoding="utf-8")
        for seam in ("wayline.fetch", "from wayline import fetch", "urllib", "http.client", "socket", "subprocess"):
            self.assertNotIn(seam, source)
        for name in ("writer", "verifier"):
            role = worker.read_role(name, HARNESS_ROOT)
            self.assertIn("WebFetch", role.disallowed_tools)
            self.assertIn("WebSearch", role.disallowed_tools)
            self.assertFalse([tool for tool in role.allowed_tools if any(word in tool for word in ("curl", "wget", "push", "gh "))])


class CommandTest(PaperCase):
    def test_the_command_prints_what_the_owner_reads_and_exits_0_on_a_pass(self):
        with worker.use_fake() as fake:
            fake.script(respond=Classifier(), role="classifier")
            fake.script(draft(), role="writer")
            for envelope in PASSING_GATE:
                fake.script(envelope, role="verifier")
            out = io.StringIO()
            with redirect_stdout(out), redirect_stderr(io.StringIO()):
                code = cli.main(["paper", "--project", str(self.project), "--venue", "arxiv"])
        self.assertEqual(code, 0, out.getvalue())
        self.assertIn("status    passed", out.getvalue())
        self.assertIn("Nothing was submitted.", out.getvalue())

    def test_a_gate_that_fails_exits_1(self):
        with worker.use_fake() as fake:
            fake.script(respond=Classifier(), role="classifier")
            fake.script(draft(), role="writer")
            for envelope in (verdict(), verdict(), verdict(False)):
                fake.script(envelope, role="verifier")
            out = io.StringIO()
            with redirect_stdout(out), redirect_stderr(io.StringIO()):
                code = cli.main(["paper", "--project", str(self.project), "--venue", "arxiv"])
        self.assertEqual(code, 1)
        self.assertIn("open      writing ticket(s)", out.getvalue())


if __name__ == "__main__":
    unittest.main()
