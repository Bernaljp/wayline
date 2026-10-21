"""The position memo, phase P2 (ticket 29; Implementation Decisions 10, 1, and 17; ticket 80).

The critic is driven through the fake launcher (seam 1) over the project of ticket 30's recorded grill:
its four dossiers (three verified, one unresolved), an intake, and two objectives, one of them a goal,
with no `GOAL.json`. The critic's answer is
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
from tests.projects import ProjectTestCase, open_goal, open_objective
from wayline import cli, dashboard, decider, gates, grill, position, project, sections, worker
from wayline.fetch import recording_fetcher
from wayline.ledger import Ledger
from wayline.scout import Scout
from wayline.worker import Envelope

INPUT = FIXTURES_DIR / "skill" / "wayline-grill" / "input"
RECORDED = FIXTURES_DIR / "skill" / "wayline-grill" / "recorded"
MEMO = json.loads((FIXTURES_DIR / "position" / "memo.json").read_text(encoding="utf-8"))
RECORDINGS = FIXTURES_DIR / "fetch"
EMAIL = "owner@example.org"
GOAL_QUESTION = "Do pairwise products raise the held-out AUROC on the synthetic set?"
OBJECTIVE_QUESTION = "Below what interaction strength do the products stop helping?"
MEASURE = {"metric": "auroc", "direction": "up", "target": 0.85, "held_out_split": "split_b", "eval_command": "echo auroc: 0.5",
           "baseline": {"value": None, "source": None}, "dataset_or_split": None, "min_seeds": None}
# The objectives the memo's rows answer, as `objectives.json` holds them: a goal and an objective without a measure.
OBJECTIVES = [
    {"id": "O1", "text": GOAL_QUESTION, "measure": MEASURE, "status": "open", "answer": None, "evidence": [], "reframed_as": None},
    {"id": "O2", "text": OBJECTIVE_QUESTION, "measure": None, "status": "open", "answer": None, "evidence": [], "reframed_as": None},
]
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

    def test_a_review_ticket_gets_the_verdict_protocol_only(self):
        ticket = {"id": 7, "title": "Review the dossier", "kind": "review", "role": "critic", "difficulty": 2,
                  "touches": [], "acceptance": [], "skills": [], "blocked_by": [], "status": "ready", "attempt": 0}
        prompt = worker.assemble_prompt(ticket, self.role).text
        self.assertIn("## Verdict", prompt)
        self.assertNotIn("## Position", prompt)
        self.assertNotIn("position memo", prompt)


class CheckMemoTest(unittest.TestCase):
    """What the schema cannot say: the ranking, the radius, one row per objective, the revised target, one row per reference."""

    def check(self, value, radius="exploratory", objectives=OBJECTIVES):
        return position.check_memo(value, radius, objectives)

    def test_the_toy_memo_passes_under_exploratory(self):
        self.assertEqual(self.check(memo()), [])

    def test_a_direction_beyond_the_radius(self):
        failures = self.check(memo(), "moderate")
        self.assertEqual(failures, ["direction 3 (Where the products stop helping) is exploratory, farther than the "
                                    "project's radius moderate"])
        self.assertEqual(len(self.check(memo(), "strict")), 2)

    def test_directions_not_nearest_first(self):
        value = memo()
        value["directions"].reverse()
        self.assertIn("the directions are not nearest first: exploratory, moderate, strict", self.check(value))

    def test_the_memo_has_objectives_in_place_of_the_goal_feasibility(self):
        schema = json.loads((HARNESS_ROOT / "schemas" / "position.json").read_text(encoding="utf-8"))
        self.assertIn("objectives", schema["required"])
        self.assertNotIn("goal_feasibility", schema["properties"])
        row = schema["properties"]["objectives"]["items"]
        self.assertEqual(row["required"], ["id", "verdict", "reasoning", "revised_target"])
        self.assertEqual(row["properties"]["verdict"]["enum"], ["reachable", "uncertain", "out_of_reach"])
        self.assertIn("goal_feasibility", self.check(dict(memo(), goal_feasibility={}))[0], "the old field is refused")

    def test_one_row_per_objective(self):
        value = memo()
        del value["objectives"][1]
        self.assertEqual(self.check(value), ["the objective O2 has no row in objectives"])
        value = memo()
        value["objectives"].append(dict(value["objectives"][0]))
        self.assertEqual(self.check(value), ["the objective O1 has more than one row in objectives"])
        value = memo()
        value["objectives"][1]["id"] = "O9"
        self.assertEqual(self.check(value), ["a row of objectives names O9, which the project does not hold",
                                             "the objective O2 has no row in objectives"])

    def test_a_closed_objective_takes_no_row_and_a_parked_one_does(self):
        closed = [dict(OBJECTIVES[0]), dict(OBJECTIVES[1], status="answered")]
        self.assertEqual(self.check(memo(), objectives=closed),
                         ["a row of objectives names O2, which is answered; the memo rows only the open and parked objectives"])
        parked = [dict(OBJECTIVES[0]), dict(OBJECTIVES[1], status="parked")]
        self.assertEqual(self.check(memo(), objectives=parked), [])

    def test_the_revised_target_follows_the_verdict_on_a_goal_and_an_objective_takes_none(self):
        value = memo()
        value["objectives"][0].update(verdict="out_of_reach", reasoning="The ceiling is 0.75.", revised_target=None)
        self.assertEqual(self.check(value), ["the goal O1 is out of reach and no revised target is given"])
        value["objectives"][0].update(verdict="reachable", reasoning="Easily.", revised_target={"value": 0.8, "why": "x"})
        self.assertEqual(self.check(value), ["the goal O1 is reachable, so it takes no revised target"])
        value = memo()
        value["objectives"][1]["revised_target"] = {"value": 0.8, "why": "x"}
        self.assertEqual(self.check(value), ["O2 has no measure, so it takes no revised target"])

    def test_a_direction_names_only_objectives_the_project_holds_or_proposes_new_ones(self):
        value = memo()
        value["directions"][0]["objectives"] = [{"id": "O7", "text": "a question nobody recorded"}]
        self.assertEqual(self.check(value), ["direction 1 (The comparison as stated) names O7, which the project does not hold"])
        value["directions"][0]["objectives"] = [{"id": None, "text": "A question of its own?"}]
        self.assertEqual(self.check(value), [], "an objective with no id is a proposal")

    def test_a_project_with_no_objectives_is_positioned_and_its_directions_propose_them(self):
        value = memo(objectives=[])
        for direction in value["directions"]:
            direction["objectives"] = [{"id": None, "text": "Does it work?"}]
        self.assertEqual(self.check(value, objectives=[]), [])

    def test_a_reference_named_twice_and_a_schema_failure(self):
        value = memo()
        value["prior_work"].append(dict(value["prior_work"][0]))
        self.assertEqual(self.check(value), ["the reference paper-a is named more than once"])
        broken = memo()
        del broken["directions"][2]
        self.assertIn("minItems", self.check(broken)[0])


class PositionCase(ProjectTestCase):
    """The recorded grill's project with an intake and two objectives, one a goal, the fake launcher and an offline scout in place."""

    autonomy = "checkpoints"
    radius = "exploratory"

    def setUp(self):
        super().setUp()
        self.project = self.temp / "toy"
        project.init_project(self.project, harness_root=HARNESS_ROOT, git=False, hermes_python=None, owner_email=None)
        research = self.project / "research"
        shutil.copytree(INPUT / "research" / "refs", research / "refs", dirs_exist_ok=True)
        self.ledger = Ledger(self.project)
        self.ledger.write_markdown("INTAKE.md", INTAKE)
        harness = project.read_harness(self.project)
        harness["radius"] = self.radius
        (self.project / project.HARNESS_JSON).write_text(json.dumps(harness, indent=2) + "\n", encoding="utf-8")
        self.record_objectives()
        project.set_autonomy(self.project, self.autonomy)
        self.scout = Scout(recording_fetcher(RECORDINGS, email=EMAIL), EMAIL)
        self.notified = []
        self.fake = self.enterContext(worker.use_fake())

    def record_objectives(self):
        open_goal(self.project, GOAL_QUESTION, **{key: MEASURE[key] for key in ("target", "held_out_split")})
        open_objective(self.project, OBJECTIVE_QUESTION)

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
    """Criterion 1: one critic session through the launcher, with only the dossiers, the intake, and the objectives."""

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

    def test_the_prompt_holds_the_intake_the_objectives_and_the_dossiers_and_nothing_else(self):
        research = self.project / "research"
        for name in ("DECISIONS.md", "CONTEXT.md"):
            shutil.copy(RECORDED / "research" / name, research / name)
        shutil.copy(INPUT / "research" / "POSITION.md", research / "POSITION.md")
        self.ledger.write_markdown("SPEC.md", "# Spec: a secret spec\n")
        self.take(written(memo()))
        prompt = self.calls()[0].request.prompt
        self.assertIn("## research/INTAKE.md", prompt)
        self.assertIn("CPU only for the core comparison.", prompt)
        self.assertIn("## research/OBJECTIVES.md", prompt)
        self.assertIn("## O1 %s" % GOAL_QUESTION, prompt)
        self.assertIn("on the held-out split `split_b`", prompt)
        self.assertIn("## O2 %s" % OBJECTIVE_QUESTION, prompt)
        self.assertIn("one row in `objectives` for each of O1, O2", prompt)
        self.assertNotIn("GOAL.json", prompt)
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

    def test_no_intake_is_refused_before_a_session(self):
        (self.project / "research" / "INTAKE.md").unlink()
        with self.assertRaises(position.PositionError) as raised:
            self.take()
        self.assertIn("run wayline intake first", str(raised.exception))
        self.assertEqual(self.calls(), [])

    def test_the_critics_protocol_reads_objectives_and_not_the_goal_file(self):
        protocol = worker.protocol_for(worker.read_role(position.CRITIC).protocol, "position")
        self.assertNotIn("GOAL.json", protocol)
        self.assertNotIn("goal_feasibility", protocol)
        self.assertIn("OBJECTIVES.md", protocol)
        self.assertIn("Each names the objectives it would pursue, as\n   proposals", protocol)

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

    def test_a_reference_that_is_only_markup_is_dropped_not_raised(self):
        value = memo()
        value["prior_work"] = [{"reference": "<>", "reports": "r", "bearing": "b", "locator": None}]
        kept, dropped, _ = position.verify_citations(self.project, value, scout=self.scout)
        self.assertEqual(kept, [])
        self.assertTrue(dropped[0]["reason"].startswith("it names nothing the scout can read"), dropped)

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
        self.assertEqual(headings, ["## Closest prior work", "## Feasibility", "## Objectives", "## The hostile reviewer",
                                    "## Three directions, by distance from the intent"])
        self.assertIn("- **paper-a**\n  - title: *Interaction features for tabular classification* (2021)\n"
                      "  - identifier: doi:10.5555/wayline.fixture.paper-a\n  - what it reports: Pairwise products", text)
        self.assertIn("  - scout: verified (crossref)", text)
        self.assertNotIn("|---|", text)
        self.assertIn("### What the references lack", text)
        self.assertIn("the scout searched the literature for each at setup", text)
        self.assertIn("- A gradient-boosted tree baseline", text)
        self.assertIn("Dropped, because the scout did not verify them:\n\n- *paper-d*: research/refs/paper-d/dossier.json says "
                      "existence: unresolved.", text)
        self.assertIn("**Feasible.** No GPU is needed", text)
        self.assertIn("### O1 %s\n\nA goal: `auroc` up to 0.85 on the held-out split `split_b`" % GOAL_QUESTION, text)
        self.assertIn("**Uncertain.** The generator draws", text)
        self.assertIn("Revised target: **0.83**. The goal is the owner's to change; this is a proposal.", text)
        self.assertIn("- why it is reachable: Below the likely ceiling", text)
        self.assertIn("### O2 %s\n\nAn objective without a measure.\n\n**Reachable.** Sweeping" % OBJECTIVE_QUESTION, text)
        self.assertEqual([(row["id"], row["text"], row["status"]) for row in record["objectives"]],
                         [("O1", GOAL_QUESTION, "open"), ("O2", OBJECTIVE_QUESTION, "open")])
        self.assertTrue(record["objectives"][0]["measure"].startswith("`auroc` up to 0.85 on the held-out split `split_b`"))
        self.assertIsNone(record["objectives"][1]["measure"])
        self.assertNotIn("goal", record)
        self.assertIn("4. Trying every pairwise product", text)
        self.assertIn("Nearest first, none farther than the radius `exploratory`.", text)
        self.assertIn("1. **The comparison as stated** (strict):", text)
        self.assertIn("3. **Where the products stop helping** (exploratory):", text)
        self.assertIn("The objectives each direction names are proposals", text)
        self.assertIn("   - would pursue O1: %s" % GOAL_QUESTION, text)
        self.assertIn("   - proposes a new objective: Does a flexible model without products match the products on the synthetic set?", text)
        self.assertIn("   - would pursue O2: %s" % OBJECTIVE_QUESTION, text)

    def test_the_introduction_is_seeded_from_the_verified_prior_work_once(self):
        """Ticket 86: code seeds the Introduction with one passage per verified row, by the position step, never twice."""
        self.take(written(memo()))
        record = self.record()
        seeded = [item for item in sections.read_passages(self.project) if item["section"] == "introduction"]
        self.assertEqual([item["by"] for item in seeded], ["step:position"] * len(record["prior_work"]))
        self.assertEqual({item["heading"] for item in seeded}, {"Prior work"})
        first = seeded[0]
        self.assertIn("*Interaction features for tabular classification* (2021) reports: Pairwise products", first["text"])
        self.assertTrue(first["text"].endswith("{ref:paper-a#%s}" % position.ref_locator(record["prior_work"][0])), first["text"])
        self.assertNotIn("paper-d", " ".join(item["text"] for item in seeded), "a dropped row seeds nothing")
        introduction = (self.project / "research" / "sections" / "introduction.md").read_text(encoding="utf-8")
        self.assertIn("## Prior work", introduction)
        position.write_memo(self.project, record["memo"], scout=self.scout)
        self.assertEqual(len([item for item in sections.read_passages(self.project) if item["section"] == "introduction"]), len(seeded))

    def test_lists_and_paragraphs_in_prose_are_kept(self):
        value = memo()
        value["feasibility"]["reasoning"] = "Three changes are needed:\n1. **Seeds.** Run several.\n2. Add a baseline.\n\n\n\nThe rest holds."
        value["objectives"][0]["reasoning"] = "- first problem\n- second problem\n  continued"
        value["hostile_review"][0] = "Two points:\n- one\n- two"
        value["prior_work"][0]["reports"] = "AUROC | accuracy both rose"
        self.take(written(value))
        text = self.text()
        self.assertIn("**Feasible.** Three changes are needed:\n\n1. **Seeds.** Run several.\n2. Add a baseline.\n\nThe rest holds.\n", text)
        self.assertIn("**Uncertain.**\n\n- first problem\n- second problem\n  continued\n", text)
        self.assertIn("1. Two points:\n\n   - one\n   - two\n2. A logistic", text)
        self.assertIn("  - what it reports: AUROC | accuracy both rose", text)

    def test_a_heading_in_prose_is_escaped(self):
        value = memo()
        value["feasibility"]["reasoning"] = "Fine.\n## Not a heading"
        self.take(written(value))
        self.assertIn("\\## Not a heading", self.text())
        self.assertEqual([line for line in self.text().split("\n") if line.startswith("## Not")], [])

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


class NoMeasureTest(PositionCase):
    """Ticket 80: a project with objectives and none with a measure, and no `GOAL.json`, is positioned."""

    def record_objectives(self):
        open_objective(self.project, GOAL_QUESTION)
        open_objective(self.project, OBJECTIVE_QUESTION)

    def test_position_runs_without_a_goal_and_rows_each_objective(self):
        value = memo()
        value["objectives"][0].update(verdict="uncertain", revised_target=None)
        self.assertFalse((self.project / "research" / "GOAL.json").exists())
        report = self.take(written(value))
        self.assertIsNone(report["stopped"], report)
        self.assertEqual(len(self.calls()), 1, "nothing was returned to the critic")
        text = self.text()
        self.assertIn("### O1 %s\n\nAn objective without a measure.\n\n**Uncertain.**" % GOAL_QUESTION, text)
        self.assertNotIn("Revised target", text)
        self.assertEqual([row["measure"] for row in self.record()["objectives"]], [None, None])
        self.assertEqual([item["id"] for item in report["view"]["objectives"]], ["O1", "O2"])

    def test_a_revised_target_on_an_objective_goes_back_to_the_critic(self):
        report = self.take(written(memo()), written(dict(memo(), objectives=[
            dict(memo()["objectives"][0], revised_target=None), memo()["objectives"][1]])))
        self.assertIsNone(report["stopped"], report)
        self.assertIn("O1 has no measure, so it takes no revised target", self.calls()[1].message)


class ObjectivesReadOnceTest(PositionCase):
    """The memo is asked for, checked against, and kept with the objectives read before the session."""

    def test_an_objective_recorded_during_the_session_is_not_kept_as_one_the_memo_read(self):
        def respond(request, message):
            open_objective(self.project, "A question recorded while the critic was reading?")
            return written(memo())

        self.fake.script(respond=respond, role=position.CRITIC)
        report = position.position(self.project, scout=self.scout, notify=self.notify)
        self.assertIsNone(report["stopped"], report)
        self.assertEqual([row["id"] for row in self.record()["objectives"]], ["O1", "O2"])
        self.assertNotIn("O3", self.text())


class NoObjectiveTest(PositionCase):
    """A project with neither objectives nor `GOAL.json` is positioned too: its directions propose the objectives."""

    def record_objectives(self):
        pass

    autonomy = "interactive"

    def test_position_runs_and_the_directions_propose(self):
        value = memo(objectives=[])
        for direction in value["directions"]:
            direction["objectives"] = [{"id": None, "text": "Do pairwise products help?"}]
        report = self.take(written(value))
        self.assertIsNone(report["stopped"], report)
        text = self.text()
        self.assertIn("## Objectives\n\nNo objective is recorded yet; the directions below propose them.", text)
        self.assertIn("[wayline: no objective is recorded yet; propose them in the directions]", self.calls()[0].request.prompt)


class ShownTest(PositionCase):
    """Criterion 3, the owner's side: notified, and first in `status` and the dashboard."""

    def test_the_owner_is_notified_and_the_verb_prints_the_memo(self):
        self.fake.script(written(memo()), role=position.CRITIC)
        from tests.scout_net import quiet_search
        with quiet_search():  # the memo's missing prior work is searched at setup (ticket 99), always live
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
        self.assertIn("feasible; objectives O1 uncertain (revised target 0.83), O2 reachable", notice[1])

    def test_status_leads_with_the_memo_until_the_project_moves_past_p2(self):
        self.take(written(memo()))
        view = project.status_view(self.project, refresh=False)
        self.assertTrue(view["position"]["first"])
        self.assertEqual(view["position"]["handed_to"], "owner")
        lines = project.render_status(view).split("\n")
        self.assertTrue(lines[3].startswith("position memo  research/POSITION.md: read it before the grill"), lines[:6])
        self.assertIn("feasibility feasible   objectives O1 uncertain (revised target 0.83), O2 reachable   prior work 3 cited, "
                      "1 dropped   objections 4", lines[4])
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
        self.assertIn("renderMarkdown(view.position.text, ", body)


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
