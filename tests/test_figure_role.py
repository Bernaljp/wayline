"""The figure role (Implementation Decisions 13; research-notes 11 Sections 1 and 4; ticket 50).

Every session runs over the fake launcher: the designer's drafts and finish, the critic's ranking, and
the verifier's verdicts. The project is a copy of `fixtures/figures/project`, whose `fig1` passes all
19 machine checks, with a small plot index, a `harness.json`, and an empty ticket directory, so a pick
or a refusal can open its decision ticket. The checks are faked except where a test says otherwise.
"""

import contextlib
import io
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.paths import FIXTURES_DIR, HARNESS_ROOT, LEDGER_FIXTURE
from wayline import changes, cli, decisions, figure_checks, figure_role, figures, worker
from wayline.jsonschema import load_schema, validate
from wayline.ledger import DECISION, Ledger
from wayline.project import ProjectError, answer
from wayline.tickets import read_tickets
from wayline.worker import Envelope

FIXTURE = FIXTURES_DIR / "figures" / "project"
FIG1 = "figures/fig1"
PNG = FIXTURE / FIG1 / "fig1.png"
ZORDER = "Give panel-box patches a negative zorder."
LIBRARY_WIDE = "A symbol legend reads better typeset than laid out by hand."
LIBRARIES = ("matplotlib", "seaborn", "altair", "plotnine", "ggplot2", "tikz", "vega", "plotly", "bokeh")


def entry(identifier, chart, family, library, pitfalls=()):
    return {
        "id": identifier, "family": family, "chart_type": chart,
        "data_shape": {"n_variables": None, "variable_types": [], "grouping": "unspecified", "notes": ""},
        "when_to_use": None, "when_not_to_use": None,
        "library_implementations": [{"library": library, "function_or_geom": "plot",
                                     "snippet_locator": {"source_url": "https://example.org/%s" % identifier, "anchor": chart}}],
        "gallery_links": [], "known_pitfalls": list(pitfalls), "source_site": "example", "source_license": "MIT",
        "last_verified": "2026-09-12", "last_crawled": "2026-09-12",
    }


INDEX = {"schema_version": 1, "built": "2026-09-12", "source_counts": {}, "entries": [
    entry("barplot-matplotlib", "Barplot", "ranking", "matplotlib", (ZORDER, LIBRARY_WIDE)),
    entry("lollipop-matplotlib", "Lollipop plot", "ranking", "matplotlib", (LIBRARY_WIDE,)),
    entry("violin-seaborn", "Violin plot", "distribution", "seaborn"),
    entry("stream-altair", "Streamgraph", "evolution", "altair"),
    entry("barplot-seaborn", "Barplot", "ranking", "seaborn"),
]}


def passing_checks(project, request, result, policy=None):
    return [figure_checks.check_outcome(check_id, True, "ok") for check_id in figure_checks.CHECK_IDS]


def failing_checks(*failed):
    def checks(project, request, result, policy=None):
        return [figure_checks.check_outcome(check_id, check_id not in failed, "detail of %s" % check_id)
                for check_id in figure_checks.CHECK_IDS]
    return checks


def candidates_in(prompt):
    """`[(index_id, script, png, pitfalls)]` read back off a drafts prompt."""
    found = []
    for block in re.split(r"\n## \d+\. ", prompt)[1:]:
        block = block.split("\n# ", 1)[0]
        found.append((re.match(r"`([^`]+)`", block).group(1), re.search(r"draft script: `([^`]+)`", block).group(1),
                      re.search(r"draft PNG: `([^`]+)`", block).group(1), re.findall(r"(?m)^  - (.+)$", block)))
    return found


def verdict(passed=True, findings=()):
    return Envelope(session_id="s-verify", model="fable",
                    structured_output={"pass": passed, "findings": list(findings), "question_limit": "does the figure overclaim"})


class FigureRoleCase(unittest.TestCase):
    autonomy = "autonomous"

    def setUp(self):
        self.temp = Path(tempfile.mkdtemp(prefix="wayline-figure-role-"))
        self.addCleanup(shutil.rmtree, self.temp, ignore_errors=True)
        self.project = (self.temp / "project").resolve()
        shutil.copytree(FIXTURE, self.project)
        harness = json.loads((LEDGER_FIXTURE / "harness.json").read_text(encoding="utf-8"))
        harness["autonomy"] = self.autonomy
        (self.project / "harness.json").write_text(json.dumps(harness), encoding="utf-8")
        (self.project / "research" / "tickets").mkdir(parents=True, exist_ok=True)
        figures.write_index(self.project / "figures" / "plot_index.json", INDEX)
        self.request = json.loads((FIXTURE / "request.json").read_text(encoding="utf-8"))
        self.fake = self.enterContext(worker.use_fake())
        self.notified = []

    # --- the scripted sessions -----------------------------------------------------------------

    def script_drafts(self, fail=(), missing=(), skip_pitfalls=(), extra_pitfall=None, traps=()):
        def respond(request, message):
            drafts = []
            for identifier, script, png, pitfalls in candidates_in(request.prompt):
                consulted = [] if identifier in skip_pitfalls else list(pitfalls)
                if extra_pitfall and message is None:
                    consulted.append(extra_pitfall)
                if identifier in fail:
                    drafts.append({"index_id": identifier, "rendered": False, "generator": None, "png": None,
                                   "error": "KeyError: 'method'", "pitfalls_consulted": consulted})
                    continue
                if identifier not in missing:
                    for relative, source in ((script, None), (png, PNG)):
                        target = self.project / relative
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(source.read_bytes() if source else b"print('draft')\n")
                drafts.append({"index_id": identifier, "rendered": True, "generator": script, "png": png, "error": None,
                               "pitfalls_consulted": consulted})
            return Envelope(session_id="s-draw", model="opus", structured_output={"drafts": drafts, "traps_hit": list(traps)})
        self.fake.script(respond=respond, role="figure-designer")

    def script_ranking(self, totals=None, disorder=False):
        def respond(request, message):
            ids = re.findall(r"(?m)^- `([^`]+)`: .*\. PNG `", request.prompt)
            ranking = []
            for rank, identifier in enumerate(ids, start=1):
                total = (totals or {}).get(identifier, 20 - 3 * rank)
                share = total / 4.0
                ranking.append({"index_id": identifier, "rank": rank, "reasons": "rank %d for its shape" % rank,
                                "score": {key: share for key in figure_role.RUBRIC}})
            if disorder and message is None and len(ranking) > 1:
                ranking[0]["score"] = {key: 0 for key in figure_role.RUBRIC}
            return Envelope(session_id="s-critic", model="opus", structured_output={"ranking": ranking})
        self.fake.script(respond=respond, role="figure-critic")

    def finish_value(self, **fields):
        value = {"drew_final": True, "inputs": [{"path": "results/t7-a1/scores.csv", "panels": ["a"]},
                                                {"path": "results/t8-a1/timing.csv", "panels": ["b"]}],
                 "schematic_elements": [], "selection_statistics": [], "findings_for_text": [], "traps_hit": [],
                 "equations": [], "applied": [], "refusals": []}
        value.update(fields)
        return value

    def script_finish(self, **fields):
        self.fake.script(Envelope(session_id="s-finish", model="opus", structured_output=self.finish_value(**fields)),
                         role="figure-designer")

    def script_verdict(self, passed=True, findings=()):
        self.fake.script(verdict(passed, findings), role="verifier")

    def make(self, request=None, checks=passing_checks, autonomy=None):
        return figure_role.make(self.project, request or self.request, checks=checks, autonomy=autonomy,
                                notify=lambda *args: self.notified.append(args))

    def resume(self, checks=passing_checks):
        return figure_role.resume_figure(self.project, "fig1", checks=checks, notify=lambda *args: self.notified.append(args))

    def happy_path(self, **finish):
        self.script_drafts()
        self.script_ranking()
        self.script_finish(**finish)
        self.script_verdict()

    # --- reading back ----------------------------------------------------------------------------

    def events(self, name):
        events, _ = Ledger(self.project).read_events()
        return [event for event in events if event["event"] == name]

    def written(self):
        return json.loads((self.project / FIG1 / "figure_result.json").read_text(encoding="utf-8"))

    def calls(self, role):
        return [call for call in self.fake.calls if call.request.role == role]

    def assert_written_and_journaled(self, result, status):
        self.assertEqual(result["status"], status)
        self.assertEqual(validate(self.written(), load_schema("figure_result")), [])
        self.assertEqual(self.written(), result)
        journaled = self.events("figure_result")[-1]
        self.assertEqual(journaled["payload"]["status"], status)
        self.assertEqual(journaled["payload"]["path"], FIG1 + "/figure_result.json")
        self.assertEqual(journaled["ticket"], 49)


class ShapeTest(unittest.TestCase):
    def test_a_csv_is_classified_by_its_columns(self):
        shape = figure_role.classify_shape(FIXTURE, [{"path": "results/t8-a1/timing.csv", "sha256": "0" * 64}])
        self.assertEqual(shape["structure"], "table")
        self.assertEqual(shape["rows"], 3)
        self.assertEqual(shape["variable_types"], ["categorical", "numeric", "numeric"])
        self.assertEqual(shape["family_hint"], ["ranking", "correlation"])

    def test_json_columns_a_time_axis_and_a_matrix(self):
        temp = Path(tempfile.mkdtemp(prefix="wayline-shape-"))
        self.addCleanup(shutil.rmtree, temp, ignore_errors=True)
        (temp / "curve.json").write_text(json.dumps({"step": [1, 2, 3, 4], "loss": [0.9, 0.5, 0.4, 0.3]}), encoding="utf-8")
        (temp / "matrix.json").write_text(json.dumps([[1, 0.2], [0.2, 1]]), encoding="utf-8")
        (temp / "seeds.csv").write_text("arm,seed,auroc\nraw,1,0.8\nraw,2,0.82\nflag,1,0.9\nflag,2,0.88\n", encoding="utf-8")
        curve = figure_role.classify_shape(temp, [{"path": "curve.json"}])
        self.assertEqual(curve["variable_types"], ["time", "numeric"])
        self.assertEqual(curve["family_hint"][0], "evolution")
        self.assertEqual(figure_role.classify_shape(temp, [{"path": "matrix.json"}])["family_hint"], ["correlation"])
        seeds = figure_role.classify_shape(temp, [{"path": "seeds.csv"}])
        self.assertEqual(seeds["grouping"], ["arm"])
        self.assertIn("distribution", seeds["family_hint"])  # repeated measures per arm: the spread is there to show

    def test_the_biggest_table_inside_a_nested_result_stands_for_it(self):
        temp = Path(tempfile.mkdtemp(prefix="wayline-shape-"))
        self.addCleanup(shutil.rmtree, temp, ignore_errors=True)
        (temp / "analysis.json").write_text(json.dumps({
            "bootstrap": {"seed": 0}, "cost": {"values": [0.1, 0.2], "mean": 0.15},
            "auroc": {"raw": [0.76, 0.77, 0.78], "raw_x3x4": [0.85, 0.84, 0.86], "raw_x1x2": [0.76, 0.77, 0.78]},
            "runs": {"list": [{"arm": "raw", "seed": 1}, {"arm": "raw", "seed": 2}]}}), encoding="utf-8")
        shape = figure_role.classify_shape(temp, [{"path": "analysis.json"}])
        self.assertEqual(shape["inputs"][0]["records_under"], "auroc")
        self.assertEqual((shape["rows"], shape["n_variables"]), (3, 3))

    def test_the_claim_goes_before_a_shape_it_disagrees_with(self):
        request = json.loads((FIXTURE / "request.json").read_text(encoding="utf-8"))
        taken = figure_role.take_candidates(request, {"family_hint": ["evolution"]}, INDEX)
        self.assertEqual([candidate["family"] for candidate in taken], ["ranking", "distribution", "evolution", "ranking"])

    def test_a_missing_file_is_said_to_be_missing(self):
        shape = figure_role.classify_shape(FIXTURE, [{"path": "results/nothing.csv"}])
        self.assertEqual(shape["inputs"][0]["structure"], "missing")

    def test_claim_types_map_to_families(self):
        self.assertEqual(figure_role.claim_families("comparison"), ("ranking", "distribution"))
        self.assertEqual(figure_role.claim_families("trend over seeds"), ("evolution",))
        self.assertEqual(figure_role.claim_families("something else"), ())


class CandidatesTest(unittest.TestCase):
    def setUp(self):
        self.request = json.loads((FIXTURE / "request.json").read_text(encoding="utf-8"))
        self.shape = {"family_hint": ["ranking"]}

    def test_the_projects_library_first_then_the_claims_other_families(self):
        taken = figure_role.take_candidates(self.request, self.shape, INDEX)
        self.assertEqual([candidate["index_id"] for candidate in taken],
                         ["barplot-matplotlib", "violin-seaborn", "lollipop-matplotlib"])
        self.assertTrue(all(candidate["library"] == "matplotlib" for candidate in taken))

    def test_pitfalls_come_from_the_index_entry_or_the_librarys_shared_ones(self):
        taken = {candidate["index_id"]: candidate for candidate in figure_role.take_candidates(self.request, self.shape, INDEX)}
        self.assertEqual(taken["barplot-matplotlib"]["pitfalls"], [ZORDER, LIBRARY_WIDE])
        self.assertEqual(taken["violin-seaborn"]["pitfalls"], [LIBRARY_WIDE])  # drawn in matplotlib: the library's own

    def test_the_cap_the_exclusions_and_the_families_the_request_names(self):
        request = dict(self.request, candidates={"max": 1, "exclude_index_ids": ["barplot-matplotlib"]})
        self.assertEqual([c["index_id"] for c in figure_role.take_candidates(request, self.shape, INDEX)], ["lollipop-matplotlib"])
        request = dict(self.request, candidates={"families": ["evolution"]})
        self.assertEqual([c["index_id"] for c in figure_role.take_candidates(request, self.shape, INDEX)], ["stream-altair"])
        policy = {"figures": {"candidates": {"max": 2}}}
        self.assertEqual(len(figure_role.take_candidates(self.request, self.shape, INDEX, policy=policy)), 2)

    def test_a_chart_type_is_taken_once(self):
        taken = figure_role.take_candidates(self.request, self.shape, INDEX)
        self.assertNotIn("barplot-seaborn", [candidate["index_id"] for candidate in taken])

    def test_a_framework_figure_takes_the_structure_index(self):
        request = dict(self.request, kind="framework", register="conceptual")
        taken = figure_role.take_candidates(request, self.shape, INDEX)
        self.assertEqual([candidate["index_id"] for candidate in taken], ["pipeline", "funnel-and-fan", "grid", "before-and-after"])


class RolesTest(unittest.TestCase):
    def test_the_prompts_carry_doctrine_and_never_a_library_fact(self):
        for path in (HARNESS_ROOT / "roles" / "figure-designer" / "agent.md", HARNESS_ROOT / "roles" / "figure-critic" / "agent.md",
                     HARNESS_ROOT / "prompts" / "roles" / "figure-designer.md", HARNESS_ROOT / "prompts" / "roles" / "figure-critic.md"):
            text = path.read_text(encoding="utf-8").lower()
            for library in LIBRARIES:
                self.assertNotRegex(text, r"\b%s\b" % library, "%s names %s" % (path.name, library))
        designer = worker.read_role("figure-designer", HARNESS_ROOT)
        for doctrine in ("Conceptual labels, real shapes", "Structure spends no color", "One ramp per quantity",
                         "Required versus optional is line style", "Verify every equation", "Select for representativeness",
                         "Never draw a capability", "self-declaring", "Keep the load-bearing negative", "nearest honest alternative",
                         "describes its own figure and names no other"):
            self.assertIn(doctrine, designer.system_prompt)

    def test_the_critic_reads_only_and_the_designer_writes_only_under_the_figure(self):
        critic = worker.read_role("figure-critic", HARNESS_ROOT)
        self.assertEqual(critic.allowed_tools, ["Read", "Glob", "Grep"])
        for tool in ("Edit", "Write", "Bash"):
            self.assertIn(tool, critic.disallowed_tools)
        designer = worker.read_role("figure-designer", HARNESS_ROOT)
        self.assertIn("Bash(git *)", designer.disallowed_tools)
        self.assertEqual((designer.kinds, critic.kinds), ([], []))


class UnguidedTest(FigureRoleCase):
    def test_ranked_candidates_a_decider_pick_and_a_verified_figure(self):
        self.happy_path()
        result, reason = self.make()
        self.assertIsNone(reason)
        self.assert_written_and_journaled(result, "verified")
        ranked = [candidate for candidate in result["candidates"] if candidate["rank"]]
        self.assertEqual([candidate["rank"] for candidate in ranked], [1, 2, 3])
        self.assertEqual(ranked[0]["score"]["total"], 17)
        self.assertEqual(ranked[0]["pitfalls_consulted"], [ZORDER, LIBRARY_WIDE])
        self.assertEqual(result["selected"], {"rank": 1, "by": "decider", "margin": 3, "margin_low": False})
        self.assertEqual(result["critic"], {"session": "s-critic", "model": "opus", "rubric_version": "1"})
        self.assertEqual(result["final"]["generator"], FIG1 + "/fig1.py")
        self.assertEqual({entry["run_id"] for entry in result["final"]["inputs"]}, {"t7-a1", "t8-a1"})
        self.assertEqual(result["final"]["output_sha256"]["png"], figure_role.sha256_of(self.project / FIG1 / "fig1.png"))
        self.assertEqual(result["honesty_verdict"]["verdict"], "pass")
        self.assertEqual([entry["role"] for entry in result["sessions"]],
                         ["figure-designer", "figure-critic", "figure-designer", "verifier"])

    def test_every_session_is_fresh_and_the_designer_writes_only_under_the_figure(self):
        self.happy_path()
        self.make()
        self.assertEqual([call.kind for call in self.fake.calls], ["launch"] * 4)
        drafts, finish = self.calls("figure-designer")
        self.assertEqual(drafts.request.env["TICKET_TOUCHES"], FIG1 + "/")
        self.assertEqual(finish.request.env["TICKET_TOUCHES"], FIG1 + "/")
        self.assertEqual(Path(drafts.request.schema_path).name, "figure_drafts.json")
        self.assertEqual(Path(finish.request.schema_path).name, "figure_finish.json")
        self.assertIn("## Drafts", drafts.request.prompt)
        self.assertNotIn("## Finish", drafts.request.prompt)
        self.assertIn("## Finish", finish.request.prompt)
        self.assertIn("gid", finish.request.prompt)  # the check contract, for this matplotlib target
        critic = self.calls("figure-critic")[0].request
        self.assertNotIn("TICKET_TOUCHES", critic.env)
        self.assertEqual((critic.model, critic.effort), ("opus", "high"))
        for identifier, _, png, _ in candidates_in(drafts.request.prompt):
            self.assertIn(png, critic.prompt)
        verifier = self.calls("verifier")[0].request
        self.assertIn(FIG1 + "/caption.md", verifier.prompt)
        self.assertIn(FIG1 + "/checks.json", verifier.prompt)
        self.assertIn(FIG1 + "/request.json", verifier.prompt)

    def test_a_low_margin_is_flagged(self):
        self.script_drafts()
        self.script_ranking(totals={"barplot-matplotlib": 16, "violin-seaborn": 15, "lollipop-matplotlib": 10})
        self.script_finish()
        self.script_verdict()
        result, _ = self.make()
        self.assertEqual(result["selected"], {"rank": 1, "by": "decider", "margin": 1, "margin_low": True})

    def test_a_draft_that_failed_is_recorded_and_left_out_of_the_ranking(self):
        self.script_drafts(fail=("lollipop-matplotlib",), missing=("violin-seaborn",))
        self.script_ranking()
        self.script_finish()
        self.script_verdict()
        result, _ = self.make()
        by_id = {candidate["index_id"]: candidate for candidate in result["candidates"]}
        self.assertEqual(by_id["lollipop-matplotlib"]["error"], "KeyError: 'method'")
        self.assertIn("not a file", by_id["violin-seaborn"]["error"])
        self.assertEqual([c["rank"] for c in result["candidates"] if c["rendered"]], [1])
        self.assertNotIn("lollipop-matplotlib", self.calls("figure-critic")[0].request.prompt)
        self.assertEqual(result["selected"]["margin"], None)

    def test_pitfalls_the_index_did_not_list_are_sent_back_once(self):
        self.script_drafts(extra_pitfall="an invented pitfall")
        self.script_drafts()  # the resume, which lists only what was listed
        self.script_ranking()
        self.script_finish()
        self.script_verdict()
        result, _ = self.make()
        self.assertEqual(result["status"], "verified")
        resumed = [call for call in self.fake.calls if call.kind == "resume"]
        self.assertEqual(len(resumed), 1)
        self.assertIn("an invented pitfall", resumed[0].message)

    def test_drawing_without_reading_the_pitfalls_is_sent_back_and_then_blocks(self):
        self.script_drafts(skip_pitfalls=("barplot-matplotlib",))
        self.script_drafts(skip_pitfalls=("barplot-matplotlib",))  # the resume, no better
        result, reason = self.make()
        self.assertEqual([call.kind for call in self.fake.calls], ["launch", "resume"])
        self.assert_written_and_journaled(result, "blocked")
        self.assertIn("without reading any of its 2 listed pitfalls", reason)
        self.assertEqual(self.events("figure_result")[-1]["payload"]["reason"], reason)
        self.assertEqual(self.calls("figure-critic"), [])

    def test_a_ranking_that_contradicts_its_scores_is_sent_back(self):
        self.script_drafts()
        self.script_ranking(disorder=True)
        self.script_ranking(disorder=True)  # the resume: `disorder` only bites on a launch
        self.script_finish()
        self.script_verdict()
        result, _ = self.make()
        self.assertEqual(result["status"], "verified")
        critic = self.calls("figure-critic")
        self.assertEqual([call.kind for call in critic], ["launch", "resume"])
        self.assertIn("more than the rank above it", critic[1].message)

    def test_no_candidate_blocks_before_any_session(self):
        figures.write_index(self.project / "figures" / "plot_index.json", {"entries": []})
        result, reason = self.make()
        self.assert_written_and_journaled(result, "blocked")
        self.assertIn("build-index", reason)
        self.assertEqual(self.fake.calls, [])

    def test_nothing_rendered_blocks_before_the_critic(self):
        self.script_drafts(fail=("barplot-matplotlib", "lollipop-matplotlib", "violin-seaborn"))
        result, reason = self.make()
        self.assert_written_and_journaled(result, "blocked")
        self.assertIn("no draft rendered", reason)
        self.assertEqual(self.calls("figure-critic"), [])


class ChecksAndVerdictTest(FigureRoleCase):
    def test_a_failed_check_goes_back_once_then_fails_without_a_verdict(self):
        self.script_drafts()
        self.script_ranking()
        self.script_finish()
        self.fake.script(Envelope(session_id="s-finish", model="opus", structured_output=self.finish_value()), role="figure-designer")
        result, reason = self.make(checks=failing_checks("caption_lint"))
        self.assert_written_and_journaled(result, "failed_checks")
        self.assertIn("caption_lint", reason)
        repair = [call for call in self.calls("figure-designer") if call.kind == "resume"]
        self.assertEqual(len(repair), 1)
        self.assertIn("detail of caption_lint", repair[0].message)
        self.assertEqual(self.calls("verifier"), [])
        self.assertNotIn("honesty_verdict", result)

    def test_a_repair_that_passes_goes_on_to_the_verdict(self):
        outcomes = iter([failing_checks("palette"), passing_checks])
        self.script_drafts()
        self.script_ranking()
        self.script_finish()
        self.fake.script(Envelope(session_id="s-finish", model="opus", structured_output=self.finish_value()), role="figure-designer")
        self.script_verdict()
        result, _ = self.make(checks=lambda *args, **kwargs: next(outcomes)(*args, **kwargs))
        self.assertEqual(result["status"], "verified")

    def test_an_honesty_fail_carries_its_rules(self):
        self.script_drafts()
        self.script_ranking()
        self.script_finish()
        self.script_verdict(False, [{"text": "[selection_artifact] Panel a shows the three best seeds only.", "locator": "figures/fig1/fig1.png",
                                     "severity": "blocker"},
                                    {"text": "The layout implies X causes the speedup.", "locator": "figures/fig1/caption.md", "severity": "major"}])
        result, _ = self.make()
        self.assert_written_and_journaled(result, "honesty_failed")
        self.assertEqual([(f["rule"], f["text"]) for f in result["honesty_verdict"]["findings"]],
                         [("selection_artifact", "Panel a shows the three best seeds only."),
                          ("implied_claim", "The layout implies X causes the speedup.")])
        verdicts = self.events("verdict")
        self.assertEqual([(v["payload"]["subject_kind"], v["payload"]["verdict_type"]) for v in verdicts], [("figure", "figure_honesty")])

    def test_each_equation_gets_a_sub_verdict_and_a_mismatch_fails_the_figure(self):
        self.script_drafts()
        self.script_ranking()
        self.script_finish(equations=[{"id": "auroc", "drawn": "AUROC = P(s+ > s-)", "implementation": "results/t7-a1/scores.csv:1-4"},
                                      {"id": "speed", "drawn": "v = 1/t", "implementation": "results/t8-a1/timing.csv:1-4"}])
        self.script_verdict(True)
        self.script_verdict(False, [{"text": "The code computes 1/(t+1).", "locator": "results/t8-a1/timing.csv:2", "severity": "blocker"}])
        self.script_verdict(True)
        result, _ = self.make()
        self.assertEqual(result["status"], "honesty_failed")
        self.assertEqual(result["honesty_verdict"]["findings"][0]["rule"], "equation_mismatch")
        self.assertIn("1/(t+1)", result["honesty_verdict"]["findings"][0]["text"])
        types = [v["payload"]["verdict_type"] for v in self.events("verdict")]
        self.assertEqual(types, ["equation_match", "equation_match", "figure_honesty"])
        report = json.loads((self.project / FIG1 / "checks.json").read_text(encoding="utf-8"))
        self.assertEqual([item["pass"] for item in report["equation_verdicts"]], [True, False])

    def test_a_finish_that_could_not_run_leaves_the_pick_standing(self):
        self.script_drafts()
        self.script_ranking()
        result, reason = self.make()  # no finish scripted: the launch fails
        self.assert_written_and_journaled(result, "selected")
        self.assertIn("the pick stands", reason)
        self.script_finish()
        self.script_verdict()
        result, _ = self.resume()
        self.assert_written_and_journaled(result, "verified")
        self.assertEqual(len(self.calls("figure-critic")), 1)  # nothing before the finish is taken again

    def test_a_verdict_that_could_not_be_taken_is_taken_on_resume(self):
        self.script_drafts()
        self.script_ranking()
        self.script_finish()
        result, reason = self.make()  # no verifier scripted
        self.assert_written_and_journaled(result, "blocked")
        self.assertIn("figure_honesty verdict could not be taken", reason)
        self.assertTrue(all(check["pass"] for check in result["checks"]))
        self.script_verdict()
        result, _ = self.resume()
        self.assert_written_and_journaled(result, "verified")
        self.assertEqual(len(self.calls("figure-designer")), 2)

    def test_the_verifier_budget_is_honored(self):
        self.script_drafts()
        self.script_ranking()
        self.script_finish(equations=[{"id": "auroc", "drawn": "A", "implementation": "results/t7-a1/scores.csv:1-4"}])
        result, reason = self.make(dict(self.request, budget={"verifier_sessions": 1}))
        self.assertEqual(result["status"], "blocked")
        self.assertIn("need 2 verifier session(s)", reason)
        self.assertEqual(self.calls("verifier"), [])

    def test_the_real_checks_pass_on_the_fixture_figure(self):
        if shutil.which("pdffonts") is None or figure_checks.Tools().argv("ruff") is None:
            self.skipTest("poppler and ruff are needed for the real checks")
        try:
            import matplotlib  # noqa: F401
        except ImportError:
            self.skipTest("matplotlib is needed to regenerate the fixture figure")
        self.happy_path()
        result, reason = self.make(checks=None)
        failed = [check for check in result.get("checks") or [] if not check["pass"]]
        self.assertEqual(failed, [], reason)
        self.assertEqual(result["status"], "verified")
        self.assertEqual(len(result["checks"]), 19)
        self.assertEqual(result["final"]["crops"], [FIG1 + "/crops/a.png", FIG1 + "/crops/b.png"])


class HumanPickTest(FigureRoleCase):
    autonomy = "checkpoints"

    def test_the_pick_waits_for_the_owner_and_resume_finishes_their_rank(self):
        self.script_drafts()
        self.script_ranking()
        result, reason = self.make()
        self.assert_written_and_journaled(result, "candidates_ranked")
        self.assertNotIn("selected", result)
        (ticket,) = [t for t in read_tickets(self.project) if t["kind"] == "decision"]
        self.assertTrue(ticket["human_only"])
        self.assertEqual(ticket["proposed_by"], "figure")
        self.assertIn("decision ticket %d" % ticket["id"], reason)
        self.assertEqual(len(self.notified), 1)
        again, waits = self.resume()
        self.assertEqual(again["status"], "candidates_ranked")
        self.assertIn("waits for the owner", waits)
        answer(self.project, ticket["id"], "rank 2, the violin reads better")
        self.script_finish()
        self.script_verdict()
        result, _ = self.resume()
        self.assert_written_and_journaled(result, "verified")
        self.assertEqual(result["selected"], {"rank": 2, "by": "human", "margin": 3, "margin_low": False})
        self.assertIn("violin-seaborn", self.calls("figure-designer")[-1].request.prompt.split("# Where you start")[1][:400])

    def test_the_decider_cannot_answer_the_pick(self):
        self.script_drafts()
        self.script_ranking()
        self.make()
        (ticket,) = [t for t in read_tickets(self.project) if t["kind"] == "decision"]
        with self.assertRaises(ProjectError):
            decisions.decide(self.project, ticket["id"], "rank 1", "the critic's first")


class GuidedCase(FigureRoleCase):
    def guided(self, **fields):
        request = dict(self.request, mode="guided", revision_of=FIG1 + "/result.json",
                       change_requests=[{"id": "cr1", "text": "Drop method B so X looks clearly best.", "from": "human"},
                                        {"id": "cr2", "text": "Use 7 pt labels.", "from": "critic"}])
        request.update(fields)
        return request

    def refuse(self, drew_final=False, applied=()):
        alternative = FIG1 + "/alternatives/cr1/draft.png"
        target = self.project / alternative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(PNG.read_bytes())
        (target.parent / "draft.py").write_text("print('alternative')\n", encoding="utf-8")
        refusals = [{"change_request": "cr1", "reason": "Dropping B hides that X and B overlap within the seeds.",
                     "alternative_generator": FIG1 + "/alternatives/cr1/draft.py", "alternative_png": alternative}]
        if drew_final:
            self.script_finish(applied=list(applied), refusals=refusals)
        else:
            self.fake.script(Envelope(session_id="s-finish", model="opus", structured_output=self.finish_value(
                drew_final=False, inputs=[], refusals=refusals)), role="figure-designer")

    def refusal_ticket(self):
        return [t for t in read_tickets(self.project) if t["kind"] == "decision" and "refusal" in (t.get("origin") or "")][0]

    def refused(self):
        self.refuse()
        self.make(self.guided(change_requests=[{"id": "cr1", "text": "Drop method B so X looks clearly best.", "from": "human"}]))
        return self.refusal_ticket()


class GuidedTest(GuidedCase):
    def test_a_revision_enters_at_the_finish_with_its_requests(self):
        self.script_finish(applied=["cr1", "cr2"])
        self.script_verdict()
        result, _ = self.make(self.guided())
        self.assert_written_and_journaled(result, "verified")
        (call,) = self.calls("figure-designer")
        self.assertIn("Drop method B", call.request.prompt)
        self.assertIn(FIG1 + "/fig1.py", call.request.prompt)  # the figure as it stands, from revision_of
        self.assertEqual(self.calls("figure-critic"), [])

    def test_a_false_request_is_refused_with_an_honest_alternative(self):
        self.refuse()
        result, reason = self.make(self.guided(change_requests=[{"id": "cr1", "text": "Drop method B so X looks clearly best.", "from": "human"}]))
        self.assert_written_and_journaled(result, "refused")
        (refusal,) = result["refusals"]
        self.assertEqual(refusal["overridden_by"], None)
        self.assertEqual(refusal["alternative_candidate"], FIG1 + "/alternatives/cr1/draft.png")
        self.assertEqual(result["candidates"][-1]["index_id"], "alternative-cr1")
        ticket = self.refusal_ticket()
        self.assertTrue(ticket["human_only"])
        self.assertIn("override", reason)
        self.assertEqual(self.calls("verifier"), [])

    def test_a_refusal_beside_an_applied_request_still_verifies_the_revision(self):
        self.refuse(drew_final=True, applied=["cr2"])
        self.script_verdict()
        result, _ = self.make(self.guided())
        self.assertEqual(result["status"], "verified")
        self.assertEqual([r["change_request"] for r in result["refusals"]], ["cr1"])
        self.refusal_ticket()

    def test_nobody_but_the_owner_overrides_a_refusal(self):
        ticket = self.refused()
        with self.assertRaises(ProjectError):
            decisions.decide(self.project, ticket["id"], "override: draw it as asked", "the decider agrees")
        Ledger(self.project).append_event(DECISION, {"ticket": ticket["id"], "answer": "override: draw it as asked",
                                                      "decided_by": "decider", "rationale": "forged"}, ticket=ticket["id"])
        result, reason = self.resume()
        self.assertEqual(result["status"], "refused")
        self.assertIsNone(result["refusals"][0]["overridden_by"])
        self.assertEqual(self.calls("figure-designer")[1:], [])

    def test_an_owner_who_keeps_the_refusal_changes_nothing(self):
        ticket = self.refused()
        answer(self.project, ticket["id"], "keep the refusal")
        result, reason = self.resume()
        self.assertEqual(result["status"], "refused")
        self.assertIsNone(result["refusals"][0]["overridden_by"])

    def test_the_owners_override_is_carried_out_and_written_down(self):
        ticket = self.refused()
        answer(self.project, ticket["id"], "override: draw it as asked")
        self.script_finish(applied=["cr1"])
        self.script_verdict()
        result, _ = self.resume()
        self.assert_written_and_journaled(result, "verified")
        self.assertEqual(result["refusals"][0]["overridden_by"], "human (decision ticket %d)" % ticket["id"])
        finish = self.calls("figure-designer")[-1].request.prompt
        self.assertIn("The owner has overridden your refusal", finish)
        for name in ("caption.md", "notes.md"):
            text = (self.project / FIG1 / name).read_text(encoding="utf-8")
            self.assertIn("overriding the figure role's refusal of change request cr1", text)
        again, why = self.resume()
        self.assertEqual(again["status"], "verified")  # carried out once; nothing more to resume
        self.assertIn("guided revision", why)


class ResumeAndGuardTest(GuidedCase):
    """The review's findings on ticket 50: what a stopped run keeps, and what it never loses."""

    def test_a_failed_sub_verdict_survives_a_held_honesty_verdict(self):
        self.script_drafts()
        self.script_ranking()
        self.script_finish(equations=[{"id": "speed", "drawn": "v = 1/t", "implementation": "results/t8-a1/timing.csv:1-4"}])
        self.script_verdict(False, [{"text": "The code computes 1/(t+1).", "locator": "results/t8-a1/timing.csv:2", "severity": "blocker"}])
        result, reason = self.make()  # the honesty verdict is not scripted: it cannot be taken
        self.assertEqual(result["status"], "blocked")
        report = json.loads((self.project / FIG1 / "checks.json").read_text(encoding="utf-8"))
        self.assertEqual([item["pass"] for item in report["equation_verdicts"]], [False])
        self.script_verdict(True)
        result, _ = self.resume()
        self.assert_written_and_journaled(result, "honesty_failed")
        self.assertEqual(result["honesty_verdict"]["findings"][0]["rule"], "equation_mismatch")
        self.assertEqual(len(self.calls("verifier")), 2)  # the sub-verdict was not taken twice

    def test_an_override_a_window_stopped_is_still_owed(self):
        ticket = self.refused()
        answer(self.project, ticket["id"], "override: draw it as asked")
        result, reason = self.resume()  # no finish scripted: the pass cannot run
        self.assertEqual(result["status"], "blocked")
        self.assertIsNone(result["refusals"][0]["overridden_by"])
        self.script_finish(applied=["cr1"])
        self.script_verdict()
        result, _ = self.resume()
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["refusals"][0]["overridden_by"], "human (decision ticket %d)" % ticket["id"])

    def test_every_request_is_applied_or_refused_and_drew_final_false_needs_them_all_refused(self):
        refusal = {"change_request": "cr1", "reason": "Dropping B hides the overlap.", "alternative_generator": None, "alternative_png": None}
        self.fake.script(Envelope(session_id="s-finish", model="opus", structured_output=self.finish_value(
            drew_final=False, inputs=[], refusals=[refusal])), role="figure-designer")
        self.script_finish(applied=["cr2"], refusals=[refusal])
        self.script_verdict()
        result, _ = self.make(self.guided())
        self.assertEqual(result["status"], "verified")
        (resumed,) = [call for call in self.fake.calls if call.kind == "resume"]
        self.assertIn("drew_final is false", resumed.message)
        self.assertIn("cr2 is neither", resumed.message)
        self.assertEqual(result["applied"], ["cr2"])

    def test_the_override_pass_starts_from_the_revision_and_keeps_what_it_applied(self):
        self.refuse(drew_final=True, applied=["cr2"])
        self.script_verdict()
        self.make(self.guided())
        answer(self.project, self.refusal_ticket()["id"], "override: draw it as asked")
        self.script_finish(applied=["cr1"])
        self.script_verdict()
        result, _ = self.resume()
        self.assertEqual(result["status"], "verified")
        prompt = self.calls("figure-designer")[-1].request.prompt
        self.assertIn("as the earlier pass of this revision left it", prompt)
        self.assertIn("Already carried out in it, to keep:\n- `cr2`", prompt)
        self.assertEqual(result["applied"], ["cr1", "cr2"])

    def test_a_repair_does_not_duplicate_an_alternative_nor_drop_the_override(self):
        self.refuse(drew_final=True, applied=["cr2"])
        refusal = self.fake.queue[-1].envelope.structured_output["refusals"]
        self.fake.script(Envelope(session_id="s-finish", model="opus", structured_output=self.finish_value(applied=["cr2"], refusals=refusal)),
                         role="figure-designer")
        self.script_verdict()
        outcomes = iter([failing_checks("palette"), passing_checks])
        result, _ = self.make(self.guided(), checks=lambda *args, **kwargs: next(outcomes)(*args, **kwargs))
        self.assertEqual(result["status"], "verified")
        self.assertEqual([c["index_id"] for c in result["candidates"]].count("alternative-cr1"), 1)

    def test_stale_crops_are_never_read(self):
        stale = self.project / FIG1 / "crops" / "z.png"
        stale.parent.mkdir(parents=True, exist_ok=True)
        stale.write_bytes(PNG.read_bytes())
        self.happy_path()
        result, _ = self.make()
        self.assertEqual(result["final"]["crops"], [])
        self.assertNotIn("crops/z.png", self.calls("verifier")[0].request.prompt)

    def test_drafts_the_critic_never_ranked_are_ranked_on_resume(self):
        self.script_drafts()
        result, reason = self.make()  # no critic scripted
        self.assertEqual(result["status"], "blocked")
        self.script_ranking()
        self.script_finish()
        self.script_verdict()
        result, _ = self.resume()
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["version"], 1)
        self.assertEqual(len(self.calls("figure-designer")), 2)  # the drafts once, the finish once

    def test_data_that_changed_since_the_request_blocks_before_any_session(self):
        (self.project / "results" / "t7-a1" / "scores.csv").write_text("method,auroc\nX,0.99\n", encoding="utf-8")
        result, reason = self.make()
        self.assertEqual(result["status"], "blocked")
        self.assertIn("results/t7-a1/scores.csv no longer has the sha256", reason)
        self.assertEqual(self.fake.calls, [])

    def test_an_unreadable_index_is_a_blocked_result_not_a_traceback(self):
        (self.project / "figures" / "plot_index.json").write_text("{not json", encoding="utf-8")
        result, reason = self.make()
        self.assert_written_and_journaled(result, "blocked")
        self.assertIn("cannot be read", reason)
        taken = figure_role.take_candidates(dict(self.request, kind="framework", register="conceptual"), {}, INDEX, {"layouts": 1})
        self.assertEqual(taken, [])


class HandOnTest(FigureRoleCase):
    def test_findings_for_the_text_become_proposals(self):
        self.happy_path(findings_for_text=[{"text": "The runtime advantage of X holds only on the small datasets.",
                                            "manuscript_locator": "results.md#S3", "suggested_ticket": True}])
        self.make()
        parked, admitted = self.events("proposal_parked"), self.events("proposal_admitted")
        self.assertEqual(len(parked) + len(admitted), 1)
        outcome = (parked + admitted)[0]["payload"]
        self.assertEqual(outcome["kind"], "writing")
        self.assertEqual(outcome["from"], 49)
        self.make  # a result carried again proposes nothing twice
        figure_role.write_result(self.project, self.written())
        self.assertEqual(len(self.events("proposal_parked")) + len(self.events("proposal_admitted")), 1)

    def test_a_figure_the_paper_asked_for_files_no_proposal(self):
        self.happy_path(findings_for_text=[{"text": "The runtime advantage of X holds only on the small datasets.",
                                            "manuscript_locator": "results.md#S3", "suggested_ticket": True}])
        result, _ = self.make(dict(self.request, ticket=figure_role.PAPER_TICKET))
        self.assertEqual(result["findings_for_text"][0]["manuscript_locator"], "results.md#S3")
        self.assertEqual(self.events("proposal_parked") + self.events("proposal_admitted"), [])
        self.assertEqual([ticket for ticket in read_tickets(self.project) if ticket["kind"] == "writing"], [])

    def test_promoted_traps_reach_the_evolve_loop_and_fold_into_the_index(self):
        trap = {"library": "matplotlib", "chart_type": "Barplot", "description": "Error bars vanished under the bars at zorder 2.",
                "fix": "Draw the error bars at zorder 3.", "promote_to_index": True}
        self.script_drafts(traps=[trap, dict(trap, description="not worth keeping", promote_to_index=False)])
        self.script_ranking()
        self.script_finish()
        self.script_verdict()
        self.make()
        (item,) = self.events("feedback")
        self.assertEqual(item["payload"]["source"], "figure")
        text = (self.project / "research" / "feedback" / (item["payload"]["id"] + ".md")).read_text(encoding="utf-8")
        self.assertIn("Error bars vanished", text)
        self.assertNotIn("not worth keeping", text)
        self.assertEqual([entry["id"] for entry in changes.pending_feedback(self.project)], [item["payload"]["id"]])
        figure_role.write_result(self.project, self.written())
        self.assertEqual(len(self.events("feedback")), 1)  # filed once
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["figures", "fold-traps", FIG1 + "/figure_result.json", "--project", str(self.project)])
        self.assertEqual(code, 0, out.getvalue())
        index = figures.load_index(self.project / "figures" / "plot_index.json")
        barplot = next(entry for entry in index["entries"] if entry["id"] == "barplot-matplotlib")
        self.assertIn("Error bars vanished under the bars at zorder 2.", barplot["known_pitfalls"])


class VerbTest(FigureRoleCase):
    def test_make_and_resume_from_the_command_line(self):
        self.happy_path()
        path = self.temp / "request.json"
        path.write_text(json.dumps(self.request), encoding="utf-8")
        out = io.StringIO()
        with contextlib.redirect_stdout(out), mock.patch.object(figure_role.figure_checks, "run_checks", passing_checks):
            code = cli.main(["figure", "make", str(path), "--project", str(self.project)])
        self.assertEqual(code, 0, out.getvalue())
        self.assertIn("figure fig1, version 1: verified", out.getvalue())
        self.assertIn("picked rank 1 by the decider", out.getvalue())
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["figure", "resume", "fig1", "--project", str(self.project)])
        self.assertIn("guided revision", out.getvalue())

    def test_a_request_the_schema_refuses_is_refused_before_anything_runs(self):
        with self.assertRaises(figure_role.FigureError):
            figure_role.make(self.project, dict(self.request, mode="guided"))
        self.assertEqual(self.fake.calls, [])


if __name__ == "__main__":
    unittest.main()
