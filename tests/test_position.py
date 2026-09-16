"""The position memo, phase P2 (ticket 29; Implementation Decisions 10 and 1).

The critic is driven through the fake launcher (seam 1) over the project of ticket 30's recorded grill:
its four dossiers (three verified, one unresolved), an intake, and a goal. The critic's answer is
`fixtures/position/memo.json`, the toy intent's memo, or a copy of it broken on purpose. The scout
runs on the suite's recorded responses, so a citation no dossier holds is resolved offline. What is
asserted is what the owner and the decider see: `research/POSITION.md` and `research/position.json`,
the launch request, the resume messages, the journal's `phase`, and `status`.
"""

import copy
import io
import json
import shutil
import unittest
import unittest.mock
from contextlib import redirect_stderr, redirect_stdout

from tests.paths import FIXTURES_DIR, HARNESS_ROOT
from tests.projects import ProjectTestCase
from wayline import cli, dashboard, decider, gates, grill, position, project, worker
from wayline.fetch import recording_fetcher
from wayline.ledger import Ledger
from wayline.scout import Scout
from wayline.worker import Envelope

INPUT = FIXTURES_DIR / "skill" / "wayline-grill" / "input"
RECORDED = FIXTURES_DIR / "skill" / "wayline-grill" / "recorded"
MEMO = json.loads((FIXTURES_DIR / "position" / "memo.json").read_text(encoding="utf-8"))
RECORDINGS = FIXTURES_DIR / "fetch"
EMAIL = "owner@example.org"
GOAL = {
    "metric": "auroc", "direction": "up", "target": 0.85, "dataset_or_split": None, "held_out_split": "split_b",
    "eval_command": "python3 toy/eval.py {artifact}", "baseline": {"value": None, "source": None},
    "budget": {"gpu_hours": None, "wallclock": 4, "usage_windows": None}, "stop_when": "goal_reached",
}
INTAKE = """# Intake

## Intent

Find whether adding feature interaction terms improves held-out AUROC on the synthetic set.

## Constraints

- CPU only for the core comparison.
"""


def memo(**changes):
    value = copy.deepcopy(MEMO)
    value.update(changes)
    return value


def written(value, session="critic-session"):
    return Envelope(session_id=session, structured_output=value, num_turns=9, duration_ms=60000)


def run(*args):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(list(args))
    return code, out.getvalue(), err.getvalue()


class CriticRoleTest(unittest.TestCase):
    """Criterion 1: `roles/critic/`, read-only, on opus high, with a position protocol of its own."""

    def setUp(self):
        self.role = worker.read_role(position.CRITIC)
        self.policy = json.loads((HARNESS_ROOT / "policy.json").read_text(encoding="utf-8"))

    def test_the_critic_reads_only(self):
        self.assertEqual(self.role.allowed_tools, ["Read", "Glob", "Grep"])
        for tool in ("Edit", "Write", "NotebookEdit", "Bash", "Agent", "WebFetch", "WebSearch", "Workflow", "Skill"):
            self.assertIn(tool, self.role.disallowed_tools)
        self.assertEqual(self.role.kinds, [])

    def test_the_tier_is_opus_high_by_policy(self):
        self.assertEqual(position.critic_tier(self.policy), ("opus", "high", None))
        fable = {"roles": {"critic": {"model": "fable", "effort": "high"}}}
        self.assertEqual(position.critic_tier(fable, fall_back=True), ("opus", "high", "fable"))
        with self.assertRaises(position.PositionError):
            position.critic_tier({"roles": {}})

    def test_the_verdict_and_the_memo_each_get_their_own_protocol(self):
        memo_protocol = worker.protocol_for(self.role.protocol, "position")
        verdict_protocol = worker.protocol_for(self.role.protocol, "verdict")
        self.assertIn("## Position", memo_protocol)
        self.assertNotIn("## Verdict", memo_protocol)
        self.assertIn("## Verdict", verdict_protocol)
        self.assertNotIn("hostile reviewer", verdict_protocol)
        prompt = gates.verdict_prompt(self.role, "dossier", "research/refs/x/dossier.md", "Does it hold?", ["a"], "only a")
        self.assertIn("question_limit", prompt)
        self.assertNotIn("## Position", prompt)


class CheckMemoTest(unittest.TestCase):
    """What the schema cannot say: the ranking, the radius, the revised target, one row per reference."""

    def test_the_toy_memo_passes_under_exploratory(self):
        self.assertEqual(position.check_memo(memo(), "exploratory"), [])

    def test_a_direction_beyond_the_radius(self):
        failures = position.check_memo(memo(), "moderate")
        self.assertEqual(failures, ["direction 3 (Where the products stop helping) is exploratory, farther than the "
                                    "project's radius moderate"])
        self.assertEqual(len(position.check_memo(memo(), "strict")), 2)

    def test_directions_not_nearest_first(self):
        value = memo()
        value["directions"].reverse()
        self.assertIn("the directions are not nearest first: exploratory, moderate, strict",
                      position.check_memo(value, "exploratory"))

    def test_the_revised_target_follows_the_verdict(self):
        value = memo()
        value["goal_feasibility"] = {"verdict": "out_of_reach", "reasoning": "The ceiling is 0.75.", "revised_target": None}
        self.assertEqual(position.check_memo(value, "exploratory"), ["the goal is out of reach and no revised target is given"])
        value["goal_feasibility"] = {"verdict": "reachable", "reasoning": "Easily.", "revised_target": {"value": 0.8, "why": "x"}}
        self.assertEqual(position.check_memo(value, "exploratory"), ["the goal is reachable, so it takes no revised target"])

    def test_a_reference_named_twice_and_a_schema_failure(self):
        value = memo()
        value["prior_work"].append(dict(value["prior_work"][0]))
        self.assertEqual(position.check_memo(value, "exploratory"), ["the reference paper-a is named more than once"])
        broken = memo()
        del broken["directions"][2]
        self.assertIn("minItems", position.check_memo(broken, "exploratory")[0])


class PositionCase(ProjectTestCase):
    """The recorded grill's project with an intake and a goal, the fake launcher and an offline scout in place."""

    autonomy = "checkpoints"
    radius = "exploratory"

    def setUp(self):
        super().setUp()
        self.project = self.temp / "toy"
        project.init_project(self.project, harness_root=HARNESS_ROOT, git=False, hermes_python=None, owner_email=None)
        research = self.project / "research"
        shutil.copytree(INPUT / "research" / "refs", research / "refs", dirs_exist_ok=True)
        self.ledger = Ledger(self.project)
        self.ledger.write_json("GOAL.json", GOAL, schema="goal")
        self.ledger.write_markdown("INTAKE.md", INTAKE)
        harness = project.read_harness(self.project)
        harness["radius"] = self.radius
        (self.project / project.HARNESS_JSON).write_text(json.dumps(harness, indent=2) + "\n", encoding="utf-8")
        project.set_autonomy(self.project, self.autonomy)
        self.scout = Scout(recording_fetcher(RECORDINGS, email=EMAIL), EMAIL)
        self.notified = []
        self.fake = self.enterContext(worker.use_fake())

    def notify(self, event, text, path, ticket):
        self.notified.append((event, text))

    def take(self, *envelopes):
        for envelope in envelopes:
            self.fake.script(envelope, role=position.CRITIC)
        return position.position(self.project, scout=self.scout, notify=self.notify)

    def calls(self, role=position.CRITIC):
        return [call for call in self.fake.calls if call.request.role == role]

    def record(self):
        return json.loads((self.project / "research" / "position.json").read_text(encoding="utf-8"))

    def text(self):
        return (self.project / "research" / "POSITION.md").read_text(encoding="utf-8")

    def phases(self):
        events, _ = self.ledger.read_events()
        return [event for event in events if event["event"] == "phase"]


class LaunchTest(PositionCase):
    """Criterion 1: one critic session through the launcher, with only the dossiers, the intake, and the goal."""

    def test_the_launch(self):
        report = self.take(written(memo()))
        self.assertIsNone(report["stopped"], report)
        (call,) = self.calls()
        request = call.request
        self.assertEqual((call.kind, request.model, request.effort), ("launch", "opus", "high"))
        self.assertEqual(request.schema_path, HARNESS_ROOT / "schemas" / "position.json")
        refs = self.project / "research" / "refs"
        self.assertEqual(request.cwd, refs)
        self.assertEqual(request.add_dirs, [str(refs)])
        scoped = "//%s/**" % str(refs.resolve()).strip("/")
        self.assertEqual(request.allowed_tools, ["Read(%s)" % scoped, "Glob(%s)" % scoped, "Grep(%s)" % scoped])
        self.assertEqual(worker.read_role(position.CRITIC).allowed_tools, ["Read", "Glob", "Grep"])
        self.assertNotIn("TICKET_TOUCHES", request.env)
        self.assertEqual(request.env["WAYLINE_RUN"], str(self.project / "research" / "sessions" / "position" / "1"))

    def test_only_the_reading_tools_are_scoped(self):
        self.assertEqual(position.scoped_tools(["Read", "Bash(ls *)", "Grep"], "/a b/refs"),
                         ["Read(//a b/refs/**)", "Bash(ls *)", "Grep(//a b/refs/**)"])

    def test_the_prompt_holds_the_intake_the_goal_and_the_dossiers_and_nothing_else(self):
        research = self.project / "research"
        for name in ("DECISIONS.md", "CONTEXT.md"):
            shutil.copy(RECORDED / "research" / name, research / name)
        shutil.copy(INPUT / "research" / "POSITION.md", research / "POSITION.md")
        self.ledger.write_markdown("SPEC.md", "# Spec: a secret spec\n")
        self.take(written(memo()))
        prompt = self.calls()[0].request.prompt
        self.assertIn("## research/INTAKE.md", prompt)
        self.assertIn("CPU only for the core comparison.", prompt)
        self.assertIn("## research/GOAL.json", prompt)
        self.assertIn('"held_out_split": "split_b"', prompt)
        for slug in ("paper-a", "paper-b", "paper-c", "paper-d"):
            self.assertIn("## research/refs/%s/dossier.json" % slug, prompt)
        self.assertIn("the project's radius: `exploratory`", prompt)
        self.assertIn("## Position", prompt)
        self.assertNotIn("## Verdict", prompt)
        self.assertIn("`directions` (array of object with distance (required)", prompt)
        for foreign in ("DECISIONS.md", "CONTEXT.md", "a secret spec", "The critic's memo for the toy intent"):
            self.assertNotIn(foreign, prompt)

    def test_the_inputs_are_cut_at_the_context_cap(self):
        self.ledger.write_markdown("INTAKE.md", "# Intake\n\n" + "x" * 50000 + "\n")
        text, cut = position.inputs_text(self.project, 30000)
        self.assertTrue(cut)
        self.assertIn("[wayline: cut here at the context cap;", text)
        self.assertIn("[wayline: left out at the context cap; open the path yourself.]", text)

    def test_no_intake_or_no_goal_is_refused_before_a_session(self):
        (self.project / "research" / "GOAL.json").unlink()
        with self.assertRaises(position.PositionError) as raised:
            self.take()
        self.assertIn("run wayline intake --goal first", str(raised.exception))
        self.assertEqual(self.calls(), [])

    def test_a_memo_failing_its_checks_is_returned_once(self):
        wide = memo()
        wide["directions"].reverse()
        report = self.take(written(wide), written(memo()))
        self.assertIsNone(report["stopped"])
        first, second = self.calls()
        self.assertEqual((first.kind, second.kind), ("launch", "resume"))
        self.assertEqual(second.session_id, "critic-session")
        self.assertIn("- the directions are not nearest first: exploratory, moderate, strict", second.message)
        self.assertEqual(self.record()["memo"], memo())

    def test_a_memo_failing_twice_writes_nothing(self):
        wide = memo()
        wide["directions"].reverse()
        report = self.take(written(wide), written(wide))
        self.assertIn("failed its checks twice", report["stopped"])
        self.assertTrue(report["failures"])
        self.assertFalse((self.project / "research" / "POSITION.md").exists())
        self.assertEqual(self.phases(), [])

    def test_an_unreadable_memo_is_returned_once(self):
        report = self.take(Envelope(session_id="critic-session", structured_output=None, errors=["no structured output"]),
                               written(memo()))
        self.assertIsNone(report["stopped"])
        self.assertIn("could not be read", self.calls()[1].message)

    def test_the_hold_on_fables_window_stops_it_before_a_session(self):
        policy = project.policy_for(self.project)
        policy["roles"]["critic"] = {"model": "fable", "effort": "high"}
        with unittest.mock.patch.object(gates, "fallback_now", side_effect=gates.FableHeld("held", resets_at="later", consent="wait")):
            report = position.position(self.project, policy=policy, scout=self.scout, notify=self.notify)
        self.assertIn("Fable's weekly window is held until later", report["stopped"])
        self.assertEqual(self.calls(), [])


class CitationTest(PositionCase):
    """Criterion 2: every row a citation the scout verified, else dropped with a note."""

    def test_rows_match_dossiers_by_slug_doi_and_title_and_an_unresolved_one_is_dropped(self):
        kept, dropped, written_slugs = position.verify_citations(self.project, memo(), scout=self.scout)
        self.assertEqual([row["citation"]["slug"] for row in kept], ["paper-a", "paper-b", "paper-c"])
        self.assertEqual(kept[1]["citation"]["identifier"], "doi:10.5555/wayline.fixture.paper-b")
        self.assertEqual([row["reference"] for row in dropped], ["paper-d"])
        self.assertEqual(dropped[0]["reason"], "research/refs/paper-d/dossier.json says existence: unresolved")
        self.assertEqual(written_slugs, [])
        self.assertEqual(self.scout.fetcher.requests, [])

    def test_a_work_no_dossier_holds_is_resolved_by_the_scout_and_filed(self):
        value = memo()
        value["prior_work"].append({"reference": "arXiv:1706.03762", "reports": "Attention alone suffices for translation.",
                                    "bearing": "A method to reuse.", "locator": None})
        kept, dropped, written_slugs = position.verify_citations(self.project, value, scout=self.scout)
        (slug,) = written_slugs
        self.assertEqual(kept[-1]["citation"]["slug"], slug)
        self.assertEqual(kept[-1]["citation"]["identifier"], "arXiv:1706.03762")
        self.assertEqual(kept[-1]["citation"]["resolved_by"], "arxiv")
        filed = json.loads((self.project / "research" / "refs" / slug / "dossier.json").read_text(encoding="utf-8"))
        self.assertEqual(filed["existence"], "verified")
        self.assertIn(slug, (self.project / "research" / "kb" / "query_pack.md").read_text(encoding="utf-8"))

    def test_a_work_the_scout_cannot_resolve_is_dropped_and_not_filed(self):
        value = memo()
        value["prior_work"] = [{"reference": "doi:10.9999/not-recorded", "reports": "r", "bearing": "b", "locator": None},
                               {"reference": "https://example.org/a-blog-post", "reports": "r", "bearing": "b", "locator": None}]
        kept, dropped, written_slugs = position.verify_citations(self.project, value, scout=self.scout)
        self.assertEqual(kept, [])
        self.assertEqual([row["reason"] for row in dropped], [
            "the scout could not resolve it (existence: unresolved)",
            "it names no dossier, DOI, arXiv id, or title the scout can look up",
        ])
        self.assertEqual(written_slugs, [])
        self.assertEqual(sorted(path.name for path in (self.project / "research" / "refs").iterdir()),
                         ["paper-a", "paper-b", "paper-c", "paper-d"])

    def test_two_names_for_one_dossier_keep_one_row(self):
        value = memo()
        value["prior_work"][1]["reference"] = "research/refs/paper-a"
        kept, dropped, _ = position.verify_citations(self.project, value, scout=self.scout)
        self.assertEqual([row["citation"]["slug"] for row in kept], ["paper-a", "paper-c"])
        self.assertIn("research/refs/paper-a again", dropped[0]["reason"])


class MemoTest(PositionCase):
    """Criterion 2: `POSITION.md` is rendered by code from the validated memo."""

    def test_the_rendered_memo(self):
        self.take(written(memo()))
        text = self.text()
        record = self.record()
        self.assertEqual(text, position.render_position(record))
        self.assertEqual(record["session_id"], "critic-session")
        self.assertTrue(record["model"].startswith("claude-opus"), record["model"])
        headings = [line for line in text.split("\n") if line.startswith("## ")]
        self.assertEqual(headings, ["## Closest prior work", "## Feasibility", "## Goal feasibility", "## The hostile reviewer",
                                    "## Three directions, by distance from the intent"])
        self.assertIn("| paper-a: *Interaction features for tabular classification* (2021), "
                      "doi:10.5555/wayline.fixture.paper-a | Pairwise products", text)
        self.assertIn("| verified (crossref) |", text)
        self.assertIn("*paper-d* was dropped from the table: research/refs/paper-d/dossier.json says existence: unresolved.", text)
        self.assertIn("**Feasible.** No GPU is needed", text)
        self.assertIn("The goal: auroc at least 0.85 on split_b.", text)
        self.assertIn("**Uncertain.**", text)
        self.assertIn("Revised target: **0.83**.", text)
        self.assertIn("4. Trying every pairwise product", text)
        self.assertIn("Nearest first, none farther than the radius `exploratory`.", text)
        self.assertIn("1. **The comparison as stated** (strict):", text)
        self.assertIn("3. **Where the products stop helping** (exploratory):", text)

    def test_a_pipe_in_a_cell_does_not_break_the_table(self):
        value = memo()
        value["prior_work"][0]["reports"] = "AUROC | accuracy both rose"
        self.take(written(value))
        self.assertIn("AUROC \\| accuracy both rose", self.text())

    def test_the_phase_moves_to_p2_with_the_session_and_never_back(self):
        self.take(written(memo()))
        (event,) = self.phases()
        self.assertEqual(event["payload"], {"from": None, "to": "P2"})
        self.assertEqual(event["session_id"], "critic-session")
        self.ledger.append_event("phase", {"from": "P2", "to": "P3"})
        self.take(written(memo(), session="second"))
        self.assertEqual([event["payload"]["to"] for event in self.phases()], ["P2", "P3"])
        self.assertEqual(self.record()["session_id"], "second")

    def test_the_decider_reads_the_memo(self):
        self.take(written(memo()))
        records, _ = decider.records_text(self.project)
        self.assertIn("## research/POSITION.md", records)
        self.assertIn("Revised target: **0.83**.", records)


class ShownTest(PositionCase):
    """Criterion 3, the owner's side: notified, and first in `status` and the dashboard."""

    def test_the_owner_is_notified_and_the_verb_prints_the_memo(self):
        self.fake.script(written(memo()), role=position.CRITIC)
        code, out, err = run("position", "--project", str(self.project))
        self.assertEqual(code, 0, err)
        self.assertIn("wrote research/POSITION.md: 3 prior work(s) cited, 1 dropped, on claude-opus", out)
        self.assertIn("## The hostile reviewer", out)
        events, _ = self.ledger.read_events()
        self.assertIn("position", [event["payload"]["event"] for event in events if event["event"] == "notified"])

    def test_the_notice_names_the_verdicts(self):
        self.take(written(memo()))
        (notice,) = self.notified
        self.assertEqual(notice[0], "position")
        self.assertIn("feasible; the goal is uncertain, revised target 0.83", notice[1])

    def test_status_leads_with_the_memo_until_the_project_moves_past_p2(self):
        self.take(written(memo()))
        view = project.status_view(self.project, refresh=False)
        self.assertTrue(view["position"]["first"])
        self.assertEqual(view["position"]["handed_to"], "owner")
        lines = project.render_status(view).split("\n")
        self.assertTrue(lines[3].startswith("position memo  research/POSITION.md: read it before the grill"), lines[:6])
        self.assertIn("feasibility feasible   goal uncertain, revised target 0.83   prior work 3 cited, 1 dropped   objections 4",
                      lines[4])
        self.assertEqual(lines[5], "  1. The comparison as stated (strict)")
        self.ledger.append_event("phase", {"from": "P2", "to": "P3"})
        view = project.status_view(self.project, refresh=False)
        self.assertFalse(view["position"]["first"])
        self.assertNotIn("position memo", project.render_status(view))

    def test_status_without_a_memo(self):
        view = project.status_view(self.project, refresh=False)
        self.assertIsNone(view["position"])
        self.assertNotIn("position memo", project.render_status(view))

    def test_the_dashboard_overview_carries_the_memo(self):
        self.take(written(memo()))
        view = dashboard.overview_view(self.project)
        self.assertTrue(view["position"]["first"])
        self.assertIn("## Closest prior work", view["position"]["text"])

    def test_the_dashboard_renders_the_memo_first(self):
        script = (HARNESS_ROOT / "dashboard" / "app.js").read_text(encoding="utf-8")
        start = script.index("function renderOverview(")
        body = script[start:script.index("\n}\n", start)]
        self.assertIn("view.position && view.position.first", body)
        self.assertLess(body.index("view.position"), body.index("fields(["))
        self.assertIn("renderMarkdown(view.position.text)", body)


class AutonomousTest(PositionCase):
    """Criterion 3, the decider's side: under autonomous the memo is handed on, not shown."""

    autonomy = "autonomous"

    def test_the_memo_goes_to_the_decider_with_the_grills_open_questions(self):
        research = self.project / "research"
        for name in ("DECISIONS.md", "CONTEXT.md"):
            shutil.copy(RECORDED / "research" / name, research / name)
        share = grill.decider_share(grill.read_records(self.project))
        self.assertTrue(share)
        for _ in share:
            self.fake.script(Envelope(session_id="decider-session", structured_output={
                "question": "q", "options": [], "answer": "the first", "rationale": "the memo's nearest direction",
                "confidence": 0.7, "decided_by": "decider", "reversible": True, "timestamp": None}), role=decider.DECIDER)
        report = self.take(written(memo()))
        self.assertIsNone(report["stopped"], report)
        self.assertIn("handed to the decider, which reads research/POSITION.md with every decision it takes", report["did"])
        self.assertEqual(self.notified, [])
        launches = self.calls(decider.DECIDER)
        self.assertEqual(len(launches), len(share))
        self.assertIn("Revised target: **0.83**.", launches[0].request.prompt)
        self.assertFalse(self.record() is None)
        self.assertEqual(sum(line.startswith("the decider on ") for line in report["did"]), len(share))

    def test_status_does_not_lead_with_a_memo_the_decider_has(self):
        report = self.take(written(memo()))
        self.assertEqual(self.calls(decider.DECIDER), [])
        self.assertEqual(report["view"]["handed_to"], "decider")
        self.assertNotIn("## Closest prior work", position.render_report(report))
        view = project.status_view(self.project, refresh=False)
        self.assertFalse(view["position"]["first"])
        self.assertNotIn("position memo", project.render_status(view))


class StrictRadiusTest(PositionCase):
    radius = "strict"

    def test_the_prompt_names_the_radius_and_a_wider_memo_goes_back(self):
        narrow = memo()
        for direction in narrow["directions"]:
            direction["distance"] = "strict"
        report = self.take(written(memo()), written(narrow))
        self.assertIsNone(report["stopped"])
        self.assertIn("the project's radius: `strict`", self.calls()[0].request.prompt)
        self.assertIn("farther than the project's radius strict", self.calls()[1].message)
        self.assertIn("Nearest first, none farther than the radius `strict`.", self.text())


if __name__ == "__main__":
    unittest.main()
