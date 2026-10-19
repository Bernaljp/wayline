"""Phase P0: intake, which takes information only (Implementation Decisions 10 and 17; BRIEF 6.4; ticket 80).

Each test lays out a project with `init`, hands `wayline intake` one of the shapes an owner arrives
with, and reads back what a later phase sees: `research/INTAKE.md` (through the dossier module's own
reference reader, which is what `absorb` uses), `harness.json`, and the journal. A goal is not
intake's: `wayline objective add` records it as an objective with a measure (ticket 76).
"""

import importlib.util
import io
import json
import re
import shutil
import subprocess
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from tests.paths import FIXTURES_DIR, HARNESS_ROOT
from tests.projects import ProjectTestCase
from wayline import cli, intake
from wayline.dossier import read_intake
from wayline.intake import IntakeError, drop_material, dropped_materials
from wayline.ledger import Ledger
from wayline.project import init_project, read_harness

SECTIONS = ["Intent", "References", "Data", "Code", "Constraints", "Autonomy", "Radius", "Budgets",
            "Decisions that stay human-only"]

# A PDF as a publisher ships one: the DOI sits in the uncompressed XMP packet, the text does not.
PDF = b"""%PDF-1.7
1 0 obj << /Type /Metadata /Subtype /XML /Length 120 >> stream
<x:xmpmeta xmlns:x="adobe:ns:meta/"><prism:doi>10.1038/s41592-019-0686-2</prism:doi></x:xmpmeta>
endstream endobj
%%EOF
"""


def run(*args, stdin=None):
    """`wayline intake ...` in-process; returns (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err), mock.patch("sys.stdin", io.StringIO(stdin or "")):
        code = cli.main(["intake", *args])
    return code, out.getvalue(), err.getvalue()


def sections(text):
    """The `## ` headings of a markdown file, in order, with the body under each."""
    found, current = [], None
    for line in text.splitlines():
        if line.startswith("## "):
            current = [line[3:].strip(), []]
            found.append(current)
        elif current is not None:
            current[1].append(line)
    return [(name, "\n".join(body).strip()) for name, body in found]


class IntakeTestCase(ProjectTestCase):
    def setUp(self):
        super().setUp()
        self.project = self.temp / "project"
        init_project(self.project, harness_root=HARNESS_ROOT, git=False, hermes_python=None, owner_email=None)
        self.owner = self.temp / "owner"  # what the owner hands over lives outside the project
        self.owner.mkdir()

    def intake_md(self):
        return (self.project / "research" / "INTAKE.md").read_text(encoding="utf-8")

    def section(self, name):
        return dict(sections(self.intake_md()))[name]

    def goal_path(self):
        return self.project / "research" / "GOAL.json"

    def decisions(self):
        events, _ = Ledger(self.project).read_events()
        return [event for event in events if event["event"] == "decision"]

    def write(self, name, text, root=None):
        path = (root or self.owner) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path


class VagueIntentWithReferencesTest(IntakeTestCase):
    """A paragraph, a reference list, and a PDF."""

    def setUp(self):
        super().setUp()
        references = self.write("refs.md", "# what I have been reading\n\n- arXiv:1706.03762\n"
                                           "- https://doi.org/10.1371/journal.pcbi.1008074\n"
                                           "- Highly accurate protein structure prediction with AlphaFold\n")
        pdf = self.owner / "scipy.pdf"
        pdf.write_bytes(PDF)
        self.code, self.out, self.err = run(
            "--project", str(self.project), "I think interaction terms help on the synthetic set, maybe?",
            str(references), str(pdf))

    def test_the_intake_succeeds(self):
        self.assertEqual(self.code, 0, self.err)
        self.assertIn("INTAKE.md", self.out)

    def test_every_section_is_present_in_order_and_none_is_empty(self):
        found = sections(self.intake_md())
        self.assertEqual([name for name, _ in found], SECTIONS)
        for name, body in found:
            self.assertTrue(body, "section %s is empty" % name)

    def test_the_intent_is_the_owners_words(self):
        self.assertIn("I think interaction terms help on the synthetic set, maybe?", self.section("Intent"))

    def test_absorb_reads_every_reference_including_the_one_inside_the_pdf(self):
        found = {(reference.kind, reference.value) for reference in read_intake(self.project)}
        self.assertEqual(found, {
            ("arxiv", "1706.03762"),
            ("doi", "10.1371/journal.pcbi.1008074"),
            ("title", "Highly accurate protein structure prediction with AlphaFold"),
            ("doi", "10.1038/s41592-019-0686-2"),
        })

    def test_no_goal_is_written_or_journaled(self):
        self.assertFalse(self.goal_path().exists())
        self.assertEqual(self.decisions(), [])
        self.assertNotIn("GOAL.json", self.out)

    def test_harness_json_keeps_the_defaults_and_records_the_human_only_classes(self):
        harness = read_harness(self.project)
        self.assertEqual(harness["autonomy"], "checkpoints")
        self.assertEqual(harness["radius"], "moderate")
        self.assertEqual(harness["human_only"], ["objective", "data"])
        self.assertIn("`objective`", self.section("Decisions that stay human-only"))
        self.assertIn("`data`", self.section("Decisions that stay human-only"))


class PrecisePlanWithARepositoryTest(IntakeTestCase):
    """A plan, the repository it builds on, a data pointer, and every setting stated."""

    def setUp(self):
        super().setUp()
        self.repository = self.owner / "analysis"
        self.repository.mkdir()
        (self.repository / "train.py").write_text("print('train')\n", encoding="utf-8")
        git = ["git", "-C", str(self.repository), "-c", "user.name=owner", "-c", "user.email=owner@example.org"]
        subprocess.run(git + ["init", "-q", "-b", "main"], check=True)
        subprocess.run(git + ["add", "."], check=True)
        subprocess.run(git + ["commit", "-qm", "start"], check=True)
        self.head = subprocess.run(git + ["rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
        plan = self.write("plan.md", "# Plan\n\n1. Fit the baseline on split_a.\n2. Add pairwise interaction terms.\n"
                                     "3. Report held-out AUROC on split_b with three seeds.\n")
        data = self.write("data/cells.csv", "x,y\n1,0\n")
        self.code, self.out, self.err = run(
            "--project", str(self.project), "--plan", str(plan), str(self.repository), "--data", str(data),
            "--data", "split_b is held out and never leaves this machine",
            "--constraint", "no new dependencies beyond scikit-learn",
            "--autonomy", "autonomous", "--radius", "strict",
            "--gpu-hours", "10", "--wallclock-hours", "48", "--usage-windows", "4",
            "--human-only", "baselines: which baselines the claims are compared against")

    def test_the_intake_succeeds_without_a_goal(self):
        self.assertEqual(self.code, 0, self.err)
        self.assertFalse(self.goal_path().exists())
        self.assertEqual(self.decisions(), [])

    def test_the_plan_is_quoted_whole_as_the_intent(self):
        intent = self.section("Intent")
        self.assertIn("plan.md", intent)
        for step in ("Fit the baseline on split_a.", "Add pairwise interaction terms.", "three seeds."):
            self.assertIn(step, intent)

    def test_the_repository_is_pinned_to_its_commit(self):
        code = self.section("Code")
        self.assertIn(self.head, code)
        self.assertIn("main", code)

    def test_a_repository_the_work_builds_on_is_not_absorbed(self):
        """Only the spec's `clone` is the project's own (ticket 85); a repository handed over loose is listed, pinned."""
        self.assertFalse((self.project / "code").exists())
        self.assertNotIn("code_repository", read_harness(self.project))

    def test_the_data_pointers_are_listed_as_given(self):
        data = self.section("Data")
        self.assertIn("cells.csv", data)
        self.assertIn("a file", data)
        self.assertIn("split_b is held out and never leaves this machine", data)

    def test_there_are_no_references_and_absorb_looks_nothing_up(self):
        self.assertEqual(read_intake(self.project), [])

    def test_a_later_intake_that_names_no_class_keeps_the_ones_the_owner_added(self):
        code, _, err = run("--project", str(self.project), "--intent", "the same question, restated")
        self.assertEqual(code, 0, err)
        harness = read_harness(self.project)
        self.assertEqual(harness["human_only"], ["objective", "data", "baselines"])
        self.assertEqual((harness["autonomy"], harness["radius"]), ("autonomous", "strict"))

    def test_the_settings_land_in_harness_json_and_in_intake_md(self):
        harness = read_harness(self.project)
        self.assertEqual(harness["autonomy"], "autonomous")
        self.assertEqual(harness["radius"], "strict")
        self.assertEqual(harness["budgets"], {"gpu_hours": 10, "wallclock_hours": 48, "usage_windows": 4})
        self.assertEqual(harness["human_only"], ["objective", "data", "baselines"])
        self.assertIn("`autonomous`", self.section("Autonomy"))
        self.assertIn("`strict`", self.section("Radius"))
        self.assertIn("48", self.section("Budgets"))
        self.assertIn("which baselines the claims are compared against", self.section("Decisions that stay human-only"))
        self.assertIn("no new dependencies beyond scikit-learn", self.section("Constraints"))


class IntakeTakesInformationOnlyTest(IntakeTestCase):
    """Ticket 80: intake takes no goal. A goal is an objective with a measure, which `wayline objective add` records."""

    def test_the_goal_flag_is_gone(self):
        template = self.intake_md()
        code, _, err = run("--project", str(self.project), "--intent", "find out whether it works", "--goal", "goal.json")
        self.assertEqual(code, 2, err)
        self.assertIn("--goal", err)
        self.assertEqual(self.intake_md(), template)
        self.assertFalse(self.goal_path().exists())

    def test_a_spec_that_carries_a_goal_or_a_sample_is_refused_with_where_the_goal_goes(self):
        for field in ("goal", "sample", "rationale"):
            with self.subTest(field=field):
                spec = {"intent": "find out whether it works", field: {"metric": "auroc"} if field == "goal" else "x"}
                code, _, err = run("--project", str(self.project), "--from", "-", stdin=json.dumps(spec))
                self.assertEqual(code, 2, err)
                self.assertIn(field, err)
                self.assertIn("wayline objective add", err)
        self.assertFalse(self.goal_path().exists())
        self.assertEqual(self.decisions(), [])

    def test_the_intake_says_where_objectives_and_goals_are_recorded(self):
        code, _, err = run("--project", str(self.project), "--intent", "find out whether it works")
        self.assertEqual(code, 0, err)
        intro = self.intake_md().split("\n## ", 1)[0]
        self.assertIn("wayline objective add", intro)
        self.assertIn("OBJECTIVES.md", intro)
        self.assertNotIn("Goal", [name for name, _ in sections(self.intake_md())])

    def test_the_template_has_no_goal_section_and_tells_the_owner_what_to_hand_over(self):
        template = (HARNESS_ROOT / "templates" / "project" / "research" / "INTAKE.md").read_text(encoding="utf-8")
        self.assertEqual([name for name, _ in sections(template)], SECTIONS)
        self.assertNotIn("GOAL.json", template)
        self.assertIn("wayline objective add", template)

    def test_a_harness_json_that_names_goal_is_read_as_objective(self):
        harness = read_harness(self.project)
        harness["human_only"] = ["goal", "data", "methods"]
        (self.project / "harness.json").write_text(json.dumps(harness, indent=2) + "\n", encoding="utf-8")
        code, _, err = run("--project", str(self.project), "--intent", "find out whether it works", "--human-only", "goal")
        self.assertEqual(code, 0, err)
        self.assertEqual(read_harness(self.project)["human_only"], ["objective", "data", "methods"])
        classes = self.section("Decisions that stay human-only")
        self.assertIn("`objective`", classes)
        self.assertNotIn("`goal`", classes)



class SpecOnStdinTest(IntakeTestCase):
    """The skill's path: one JSON spec on stdin, the ledger writing what the conversation settled."""

    def test_a_spec_on_stdin_writes_the_same_intake_the_flags_do(self):
        spec = {"intent": "does it help?", "references": ["10.1038/s41586-020-2649-2"], "data": ["data/ lives on the NAS"],
                "constraints": ["finish by October"], "autonomy": "interactive", "radius": "exploratory",
                "budgets": {"gpu_hours": 2}, "human_only": ["methods"]}
        code, _, err = run("--project", str(self.project), "--from", "-", stdin=json.dumps(spec))
        self.assertEqual(code, 0, err)
        harness = read_harness(self.project)
        self.assertEqual((harness["autonomy"], harness["radius"]), ("interactive", "exploratory"))
        self.assertEqual(harness["human_only"], ["objective", "data", "methods"])
        self.assertEqual(harness["budgets"]["gpu_hours"], 2)
        self.assertEqual([reference.value for reference in read_intake(self.project)], ["10.1038/s41586-020-2649-2"])

    def test_a_spec_with_a_field_intake_does_not_know_is_refused(self):
        code, _, err = run("--project", str(self.project), "--from", "-", stdin=json.dumps({"intent": "x", "deadline": "soon"}))
        self.assertEqual(code, 2)
        self.assertIn("deadline", err)
        self.assertEqual(self.intake_md(), (HARNESS_ROOT / "templates" / "project" / "research" / "INTAKE.md").read_text(encoding="utf-8"))

    def test_an_intake_with_no_intent_and_no_plan_is_refused(self):
        code, _, err = run("--project", str(self.project), "--reference", "arXiv:1706.03762")
        self.assertEqual(code, 2)
        self.assertIn("intent", err)

    def test_a_path_that_does_not_exist_is_refused_rather_than_read_as_the_intent(self):
        code, _, err = run("--project", str(self.project), "the intent", str(self.owner / "missing" / "refs.md"))
        self.assertEqual(code, 2)
        self.assertIn("refs.md", err)


class DashboardDropTest(IntakeTestCase):
    """The dashboard's drop zone (ticket 35): a file kept under `research/intake/`, taken into INTAKE.md, and kept by every later intake."""

    INTENT = "Find whether the interaction term helps."
    REFERENCES = b"- 10.1234/wayline.drop.one\n- arXiv:2401.00002\n"

    def setUp(self):
        super().setUp()
        code, _, err = run("--intent", self.INTENT, "--project", str(self.project))
        self.assertEqual(code, 0, err)

    def test_a_reference_list_goes_under_the_references_and_every_other_section_is_kept(self):
        before = self.intake_md()
        report = drop_material(self.project, "refs.md", self.REFERENCES)
        self.assertEqual({key: report[key] for key in ("path", "size", "already", "taken")},
                         {"path": "research/intake/refs.md", "size": len(self.REFERENCES), "already": False, "taken": ["References"]})
        self.assertEqual((self.project / "research" / "intake" / "refs.md").read_bytes(), self.REFERENCES)
        self.assertEqual(self.section("References"),
                         "- 10.1234/wayline.drop.one\n- arXiv:2401.00002\n\nRead from `research/intake/refs.md` as a reference list.")
        self.assertEqual([item for item in sections(self.intake_md()) if item[0] != "References"],
                         [item for item in sections(before) if item[0] != "References"])

    def test_a_plan_goes_under_the_intent_and_a_data_file_under_the_data(self):
        self.assertEqual(drop_material(self.project, "plan.md", b"First fit the baseline.\nThen add the interaction term.\n")["taken"], ["Intent"])
        intent = self.section("Intent")
        self.assertTrue(intent.startswith(self.INTENT))
        self.assertIn("The owner's plan, from `research/intake/plan.md`:\n\n> First fit the baseline.\n> Then add the interaction term.", intent)
        self.assertEqual(drop_material(self.project, "table.csv", b"gene,cell\nA,1\n")["taken"], ["Data"])
        self.assertEqual(self.section("Data"), "- `research/intake/table.csv` (a file, 14 bytes)")

    def test_the_same_bytes_twice_are_kept_once_and_other_bytes_of_the_same_name_beside_them(self):
        drop_material(self.project, "refs.md", self.REFERENCES)
        text = self.intake_md()
        again = drop_material(self.project, "refs.md", self.REFERENCES)
        self.assertEqual((again["path"], again["already"], again["taken"]), ("research/intake/refs.md", True, []))
        self.assertEqual(self.intake_md(), text)
        other = drop_material(self.project, "refs.md", b"- 10.1234/wayline.drop.two\n")
        self.assertEqual((other["path"], other["already"], other["taken"]), ("research/intake/refs-2.md", False, ["References"]))
        self.assertIn("- 10.1234/wayline.drop.two", self.section("References"))

    def test_without_an_intake_the_file_waits_and_the_next_intake_takes_it(self):
        (self.project / "research" / "INTAKE.md").unlink()
        self.assertIsNone(drop_material(self.project, "refs.md", self.REFERENCES)["taken"])
        self.assertFalse((self.project / "research" / "INTAKE.md").exists())
        code, _, err = run("--intent", self.INTENT, "--project", str(self.project))
        self.assertEqual(code, 0, err)
        self.assertIn("- 10.1234/wayline.drop.one", self.section("References"))

    def test_a_later_intake_keeps_what_was_dropped_and_lists_it_once_when_it_is_named_again(self):
        drop_material(self.project, "refs.md", self.REFERENCES)
        kept = self.project / "research" / "intake" / "refs.md"
        code, _, err = run("--intent", "A narrower intent.", "--reference", "10.5555/named.at.intake", str(kept), "--project", str(self.project))
        self.assertEqual(code, 0, err)
        references = self.section("References")
        self.assertIn("- 10.5555/named.at.intake", references)
        self.assertEqual(references.count("10.1234/wayline.drop.one"), 1)
        self.assertEqual(dropped_materials(self.project), [kept])

    def test_what_the_drop_refuses_keeps_nothing(self):
        for name, data, message in ((".hidden", b"x", "plain file name"), ("a/b.md", b"x", "plain file name"), ("", b"x", "plain file name"),
                                    ("empty.md", b"", "empty")):
            with self.subTest(name=name):
                with self.assertRaises(IntakeError) as caught:
                    drop_material(self.project, name, data)
                self.assertIn(message, str(caught.exception))
        with mock.patch.object(intake, "DROP_MAX_BYTES", 4):
            with self.assertRaises(IntakeError) as caught:
                drop_material(self.project, "big.md", b"12345")
        self.assertIn("wayline intake <path>", str(caught.exception))
        self.assertEqual(dropped_materials(self.project), [])


class RecordedIntakeFixtureTest(IntakeTestCase):
    """The skill's fixture: a recorded session's files pass the structural checks it declares."""

    FIXTURE = FIXTURES_DIR / "skill" / "wayline-intake"

    def test_the_recording_passes_every_structural_check(self):
        record = json.loads((self.FIXTURE / "fixture.json").read_text(encoding="utf-8"))
        recorded = self.FIXTURE / "recorded"
        kinds = {check["check"] for check in record["structural"]}
        self.assertTrue({"file_exists", "file_absent", "python", "tool_used"} <= kinds, kinds)
        for check_record in record["structural"]:
            with self.subTest(check=check_record):
                self.assertEqual(structural(check_record, recorded, self.FIXTURE), [])

    def test_the_checks_catch_an_intake_that_lost_a_section_or_invented_a_goal(self):
        record = json.loads((self.FIXTURE / "fixture.json").read_text(encoding="utf-8"))
        broken = self.temp / "broken"
        shutil.copytree(self.FIXTURE / "recorded", broken)
        text = (broken / "research" / "INTAKE.md").read_text(encoding="utf-8")
        (broken / "research" / "INTAKE.md").write_text(text.replace("## Radius", "## Scope"), encoding="utf-8")
        (broken / "research" / "GOAL.json").write_text("{}", encoding="utf-8")
        failures = [problem for check_record in record["structural"] for problem in structural(check_record, broken, self.FIXTURE)]
        self.assertTrue(any("Radius" in problem for problem in failures), failures)
        self.assertTrue(any("GOAL.json" in problem for problem in failures), failures)


def structural(record, root, fixture_dir):
    """The structural checks this fixture uses, evaluated the way research-notes 07 defines them.

    The runner of ticket 44 owns the whole vocabulary; until it lands this is the part of it the
    recorded intake needs, so the recording is checked by the suite rather than by nobody.
    """
    kind = record["check"]
    if kind == "file_exists":
        return [] if (root / record["path"]).is_file() else ["%s does not exist" % record["path"]]
    if kind == "file_absent":
        return [] if not (root / record["path"]).exists() else ["%s exists and must not" % record["path"]]
    if kind == "python":
        spec = importlib.util.spec_from_file_location("fixture_checks", fixture_dir / record["file"])
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return list(getattr(module, record["fn"])(root))
    if kind in ("tool_used", "tool_not_used"):
        # A recording of several turns of one session holds one trace per turn; the checks read them all.
        traces = sorted(root.glob("trace-*.jsonl"))
        if not traces:
            return ["no trace-*.jsonl in the recording"]
        pattern = re.compile(record.get("input_matches", ""))
        used = False
        for trace in traces:
            for line in trace.read_text(encoding="utf-8").splitlines():
                inner = json.loads(line).get("message")
                for block in (inner.get("content") if isinstance(inner, dict) else None) or []:
                    if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") == record["tool"]:
                        used = used or bool(pattern.search(json.dumps(block.get("input"), ensure_ascii=False)))
        if kind == "tool_used":
            return [] if used else ["no %s call matching %r in the trace" % (record["tool"], record.get("input_matches"))]
        return ["a %s call matching %r is in the trace" % (record["tool"], record.get("input_matches"))] if used else []
    return ["check %r is not one this test evaluates" % kind]
