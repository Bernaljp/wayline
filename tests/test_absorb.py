"""The L2 absorb (Implementation Decisions 9): chunking, both fan-outs, the coverage audit, the spot-check.

Every model call runs over the fake launcher. The workflow fan-out's session is answered by a
`respond` function that plays the saved workflow: it reads the `args` the session prompt carries
and writes the run file a real Workflow run would leave under `~/.claude/projects/`, into a
temporary directory the test names as the projects directory. The paper is the fixture under
`fixtures/absorb/`, whose inventory the harness's own LaTeX chain read out of `flat.tex`.
"""

import json
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.paths import FIXTURES_DIR, HARNESS_ROOT, SCHEMAS_DIR
from wayline import gates, worker
from wayline.absorb import (
    ARGS_MARKER, CONDUCTOR, WORKFLOW, absorb_level_2, audit_coverage, chunk_inventory, find_run_file,
    spot_check_ask, take_spot_check, text_layer, write_chunks,
)
from wayline.dossier import DossierError, absorb_command, read_dossier
from wayline.jsonschema import load_schema, validate
from wayline.ledger import Ledger
from wayline.worker import Envelope

FIXTURE = FIXTURES_DIR / "absorb"
SLUG = "suite-2026-tiny-absorb-paper"
ANNOTATIONS = ("$schema", "title", "description")
READ_ONLY_REMOVALS = ("Edit", "Write", "NotebookEdit", "Bash", "WebFetch", "WebSearch")
OBLIGATION = re.compile(r"^- `([a-z]+-[0-9]+)`", re.MULTILINE)


def inventory():
    return json.loads((FIXTURE / "inventory.json").read_text(encoding="utf-8"))


def items_by_id(record=None):
    record = record or inventory()
    return {item["id"]: item for key in ("sections", "appendices", "equations", "figures", "tables", "algorithms", "theorems")
            for item in record.get(key) or []}


def entry_for(item):
    """A reader's entry for one item, valid against `dossier_entry`."""
    importance = {"equation": 5, "section": 4}.get(item["kind"], 3)
    entry = {
        "item_id": item["id"], "locator": item["locator"], "kind": item["kind"],
        "content": item.get("latex") or item.get("title") or item.get("caption") or item["id"],
        "importance": importance, "relation_to_intent": "", "oddities": [],
    }
    if item["kind"] == "figure":
        entry.update(what_it_shows="Points rising left to right with a straight line through them.",
                     supports_cited_claim="The introduction claims a line fits the points; the image shows it does.",
                     anything_odd="")
    return entry


def sections(flaw_locator="tab-1", claim_locator="flat.tex:10"):
    empty = {key: [] for key in ("method", "claims", "results", "assumptions", "limitations", "flaws_found",
                                 "reusable_ideas", "open_questions", "relation_to_intent")}
    empty["method"] = [{"text": "The model is a line.", "locators": ["flat.tex:13", "eq-1"]}]
    empty["claims"] = [{"text": "A line fits the points.", "locators": [claim_locator]}]
    empty["flaws_found"] = [{"text": "The error of 0.1 is reported without a unit.", "locators": [flaw_locator]}]
    return empty


def args_from(prompt):
    body = prompt.split(ARGS_MARKER, 1)[1].split("```json\n", 1)[1].split("\n```", 1)[0]
    return json.loads(body)


class AbsorbTestCase(unittest.TestCase):
    """A bare project holding one promoted paper: its L2-level dossier, the inventory, the source, the figure."""

    def setUp(self):
        self.temp = Path(tempfile.mkdtemp(prefix="wayline-absorb-test-"))
        self.addCleanup(shutil.rmtree, self.temp, ignore_errors=True)
        self.project = (self.temp / "project").resolve()
        self.refs = self.project / "research" / "refs" / SLUG
        (self.refs / "source").mkdir(parents=True)
        (self.refs / "figures").mkdir()
        shutil.copy(FIXTURE / "inventory.json", self.refs / "inventory.json")
        shutil.copy(FIXTURE / "source" / "flat.tex", self.refs / "source" / "flat.tex")
        shutil.copy(FIXTURE / "figures" / "fig-1.png", self.refs / "figures" / "fig-1.png")
        (self.project / "research" / "INTAKE.md").write_text(
            "# Intake\n\n## The intent\n\nFind out whether a line is enough.\n", encoding="utf-8")
        self.ledger = Ledger(self.project)
        self.write_dossier(level=2)
        self.projects_dir = self.temp / "claude-projects"
        self.fake = self.enterContext(worker.use_fake())

    def write_dossier(self, level):
        self.ledger.write_json("refs/%s/dossier.json" % SLUG, {
            "schema_version": 1, "slug": SLUG, "level": level, "existence": "verified", "resolved_by": "arxiv",
            "query": {"kind": "arxiv", "value": "2609.00001"}, "identifiers": {"arxiv_id": "2609.00001"},
            "metadata": {"title": "A tiny paper for the absorb workflow"}, "abstract": None,
            "created": "2026-09-13T12:00:00.000Z",
        }, schema="dossier")

    def play_workflow(self, drop=(), sections_value=None, session_id="session-1", status="completed"):
        """A `respond` for the absorb session that does what `absorb.js` would, and writes its run file."""

        def respond(request, message):
            args = args_from(request.prompt)
            known = items_by_id()
            entries = [dict(entry_for(known[item_id]), chunk_id=chunk["id"])
                       for chunk in args["chunks"] for item_id in chunk["obligations"] if item_id not in drop]
            result = {"entries": entries, "sections": sections() if sections_value is None else sections_value, "failures": []}
            run = self.projects_dir / "-tmp-project" / session_id / "workflows"
            run.mkdir(parents=True, exist_ok=True)
            (run / "wf_0001.json").write_text(json.dumps({
                "runId": "wf_0001", "status": status, "result": result, "agentCount": len(args["chunks"]) + 1,
                "totalTokens": 123456, "durationMs": 45000,
            }), encoding="utf-8")
            return Envelope(session_id=session_id, result_text="wf_0001 completed")

        return respond

    def absorb(self, **options):
        return absorb_level_2(self.project, SLUG, projects_dir=self.projects_dir, **options)


class ChunkingTest(unittest.TestCase):
    def setUp(self):
        self.inventory = inventory()
        self.layer = text_layer((FIXTURE / "source" / "flat.tex").read_text(encoding="utf-8"), "source/flat.tex")

    def test_one_chunk_per_section_and_one_per_figure_and_table(self):
        chunks = chunk_inventory(self.inventory, self.layer, max_chars=30000)
        self.assertEqual([chunk["kind"] for chunk in chunks], ["text", "text", "text", "text", "figure", "table"])
        self.assertEqual([chunk["id"] for chunk in chunks], ["c-001", "c-002", "c-003", "c-004", "c-005", "c-006"])
        self.assertEqual(chunks[4]["images"], ["figures/fig-1.png"])
        self.assertEqual(chunks[4]["obligations"], ["fig-1"])
        self.assertEqual(chunks[5]["obligations"], ["tab-1"])

    def test_equations_algorithms_and_theorems_ride_with_their_section(self):
        chunks = chunk_inventory(self.inventory, self.layer, max_chars=30000)
        method = next(chunk for chunk in chunks if "sec-2" in chunk["obligations"])
        self.assertEqual(method["obligations"], ["sec-2", "eq-1", "sec-3", "eq-2", "alg-1"])
        results = next(chunk for chunk in chunks if "sec-4" in chunk["obligations"])
        self.assertEqual(results["obligations"], ["sec-4", "thm-1"])

    def test_every_inventory_item_is_on_exactly_one_obligation_list(self):
        chunks = chunk_inventory(self.inventory, self.layer, max_chars=30000)
        listed = [item for chunk in chunks for item in chunk["obligations"]]
        self.assertEqual(sorted(listed), sorted(items_by_id(self.inventory)))

    def test_a_section_longer_than_the_cap_is_cut_into_parts_that_each_keep_its_item(self):
        chunks = chunk_inventory(self.inventory, self.layer, max_chars=120)
        parts = [chunk for chunk in chunks if "sec-3" in chunk["obligations"]]
        self.assertGreater(len(parts), 1)
        for chunk in chunks:
            if chunk["kind"] == "text":
                self.assertLessEqual(chunk["chars"], 120 + max(len(line) for line in self.layer.lines))
        riders = [item for chunk in chunks for item in chunk["obligations"] if not item.startswith(("sec-", "app-"))]
        self.assertEqual(sorted(riders), ["alg-1", "eq-1", "eq-2", "fig-1", "tab-1", "thm-1"])
        headings = {item for chunk in chunks for item in chunk["obligations"] if item.startswith(("sec-", "app-"))}
        self.assertEqual(headings, {"sec-1", "sec-2", "sec-3", "sec-4", "app-1"})

    def test_a_subsection_gets_its_own_chunk_when_it_does_not_fit_beside_its_section(self):
        chunks = chunk_inventory(self.inventory, self.layer, max_chars=400)
        fitting = next(chunk for chunk in chunks if "sec-3" in chunk["obligations"])
        self.assertNotIn("sec-2", fitting["obligations"])

    def test_a_pdf_item_is_placed_by_its_title_on_its_page(self):
        text = "A tiny paper\nAbstract words\n\f1 Introduction\nWe begin.\nLemma 1. Tiny.\n\f2 Method\nWe fit.\n"
        record = {
            "sections": [
                {"id": "sec-1", "kind": "section", "number": "1", "title": "Introduction", "page": 2, "locator": "paper.pdf#page=2"},
                {"id": "sec-2", "kind": "section", "number": "2", "title": "Method", "page": 3, "locator": "paper.pdf#page=3"},
            ],
            "theorems": [{"id": "thm-1", "kind": "theorem", "title": "Lemma 1. Tiny.", "page": 2, "locator": "text.txt:5"}],
            "equations": [{"id": "eq-1", "kind": "equation", "latex": "y", "page": 3, "bbox": [0, 700, 10, 710], "locator": "paper.pdf#page=3"}],
        }
        chunks = chunk_inventory(record, text_layer(text, "text.txt"), max_chars=30000)
        self.assertEqual([chunk["obligations"] for chunk in chunks], [["sec-1", "thm-1"], ["sec-2", "eq-1"]])

    def test_headings_placed_on_the_same_line_share_its_text(self):
        """A heading nothing places takes the line of the one before it, and a reader for it gets that text too."""
        text = "\n".join("line %d" % number for number in range(1, 41))
        record = {"sections": [
            {"id": "sec-1", "kind": "section", "title": "One", "locator": "text.txt:1"},
            {"id": "sec-2", "kind": "section", "title": "Two", "locator": "grobid#div2"},
            {"id": "sec-3", "kind": "section", "title": "Three", "locator": "text.txt:30"},
        ]}
        chunks = chunk_inventory(record, text_layer(text, "text.txt"), max_chars=30000)
        self.assertEqual([(chunk["obligations"], chunk["lines"]) for chunk in chunks],
                         [(["sec-1", "sec-2"], [1, 29]), (["sec-3"], [30, 40])])

    def test_a_figure_drawn_from_several_files_points_at_every_panel(self):
        record = {"figures": [{"id": "fig-1", "kind": "figure", "file": "figures/fig-1.png", "locator": "flat.tex:3",
                               "graphics": ["Figures/left.png", "vis/right.pdf"]}]}
        self.assertEqual(chunk_inventory(record, None)[0]["images"], ["figures/fig-1.png", "source/vis/right.pdf"])

    def test_without_a_text_layer_every_item_still_lands_on_a_list(self):
        chunks = chunk_inventory(self.inventory, None, max_chars=30000)
        listed = [item for chunk in chunks for item in chunk["obligations"]]
        self.assertEqual(sorted(set(listed)), sorted(items_by_id(self.inventory)))


class ChunkFilesTest(AbsorbTestCase):
    def test_the_manifest_and_one_file_per_chunk_are_written_under_the_reference(self):
        layer = text_layer((self.refs / "source" / "flat.tex").read_text(encoding="utf-8"), "source/flat.tex")
        manifest = write_chunks(self.ledger, SLUG, inventory(), layer, "Find out whether a line is enough.")
        on_disk = json.loads((self.refs / "absorb" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(on_disk["chunks"], manifest["chunks"])
        self.assertEqual(manifest["items"], 11)
        method = next(chunk for chunk in manifest["chunks"] if "sec-2" in chunk["obligations"])
        text = (self.project / method["path"]).read_text(encoding="utf-8")
        self.assertIn("13| \\begin{equation}", text)
        self.assertIn("- `eq-1`: equation", text)
        self.assertIn("Find out whether a line is enough.", text)
        figure = next(chunk for chunk in manifest["chunks"] if chunk["kind"] == "figure")
        self.assertEqual(figure["images"], ["research/refs/%s/figures/fig-1.png" % SLUG])
        self.assertIn(figure["images"][0], (self.project / figure["path"]).read_text(encoding="utf-8"))

    def test_a_figure_s_other_panels_are_listed_when_the_kept_source_has_them(self):
        record = inventory()
        record["figures"][0]["graphics"] = ["figures/plot.png", "figures/plot-right.png", "figures/not-kept.png"]
        (self.refs / "source" / "figures").mkdir()
        (self.refs / "source" / "figures" / "plot-right.png").write_bytes((FIXTURE / "figures" / "fig-1.png").read_bytes())
        manifest = write_chunks(self.ledger, SLUG, record, None, None)
        figure = next(chunk for chunk in manifest["chunks"] if chunk["kind"] == "figure")
        self.assertEqual(figure["images"], ["research/refs/%s/figures/fig-1.png" % SLUG,
                                            "research/refs/%s/source/figures/plot-right.png" % SLUG])
        text = (self.project / figure["path"]).read_text(encoding="utf-8")
        self.assertIn("one file per panel", text)
        self.assertNotIn("not-kept.png", text)

    def test_a_second_write_replaces_the_first_chunks(self):
        layer = text_layer((self.refs / "source" / "flat.tex").read_text(encoding="utf-8"), "source/flat.tex")
        write_chunks(self.ledger, SLUG, inventory(), layer, None, max_chars=120)
        many = len(list((self.refs / "absorb" / "chunks").iterdir()))
        write_chunks(self.ledger, SLUG, inventory(), layer, None, max_chars=30000)
        self.assertLess(len(list((self.refs / "absorb" / "chunks").iterdir())), many)


class WorkflowScriptTest(unittest.TestCase):
    """`workflows/absorb.js` carries the reader's and the synthesizer's schemas verbatim."""

    def setUp(self):
        self.script = (HARNESS_ROOT / "workflows" / "absorb.js").read_text(encoding="utf-8")

    def embedded(self, name):
        match = re.search(r"/\* wayline:schema %s \*/ (\{.*?\}) /\* /wayline:schema \*/" % name, self.script, re.DOTALL)
        self.assertIsNotNone(match, "absorb.js embeds no %s schema" % name)
        return json.loads(match.group(1))

    def schema_file(self, name):
        schema = json.loads((SCHEMAS_DIR / (name + ".json")).read_text(encoding="utf-8"))
        return {key: value for key, value in schema.items() if key not in ANNOTATIONS}

    def test_the_embedded_schemas_are_the_schema_files(self):
        for name in ("dossier_entry_list", "dossier_sections"):
            with self.subTest(schema=name):
                self.assertEqual(self.embedded(name), self.schema_file(name))

    def test_the_list_s_entry_is_the_dossier_entry_schema(self):
        self.assertEqual(self.schema_file("dossier_entry_list")["properties"]["entries"]["items"], self.schema_file("dossier_entry"))

    def test_the_script_is_the_saved_workflow_absorb_over_the_two_roles(self):
        self.assertTrue(self.script.startswith("export const meta = {\n  name: 'absorb',"))
        self.assertIn("pipeline(", self.script)
        self.assertIn("agentType: 'reader'", self.script)
        self.assertIn("agentType: 'synthesizer'", self.script)
        self.assertIn("return { entries, sections, failures }", self.script)
        for forbidden in ("Date.now", "Math.random", "new Date()", "require(", "import "):
            self.assertNotIn(forbidden, self.script)


class WorkflowFanoutTest(AbsorbTestCase):
    def test_a_whole_read_merges_entries_writes_the_dossier_and_journals_absorbed(self):
        self.fake.script(respond=self.play_workflow(), role="absorb")
        report = self.absorb(fanout=WORKFLOW)

        self.assertTrue(report["pass"])
        self.assertEqual(report["coverage"], {"pass": True, "items": 11, "covered": 11, "missing": []})
        self.assertEqual((report["chunks"], report["entries"], report["allow_rules"]), (6, 11, "narrow"))
        self.assertEqual(report["cost"], {"agents": 7, "tokens": 123456, "duration_ms": 45000})

        lines = (self.refs / "entries.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 11)
        for line in lines:
            self.assertEqual(validate(json.loads(line), load_schema("dossier_entry")), [])
        dossier = read_dossier(self.ledger, SLUG)
        self.assertEqual(dossier["level"], 2)
        self.assertEqual(dossier["l2"]["fanout"], "workflow")
        self.assertTrue(dossier["l2"]["run_file"].endswith("wf_0001.json"))
        self.assertEqual(dossier["l2"]["sections"]["flaws_found"][0]["locators"], ["tab-1"])
        markdown = (self.refs / "dossier.md").read_text(encoding="utf-8")
        self.assertIn("## Flaws found", markdown)
        self.assertIn("The model is a line. [flat.tex:13; eq-1]", markdown)
        self.assertIn("What it shows: Points rising", markdown)

        events, _ = self.ledger.read_events()
        absorbed = [event for event in events if event["event"] == "absorbed"]
        self.assertEqual(absorbed[-1]["payload"], {"slug": SLUG, "level": 2, "session_id": "session-1",
                                                   "chunks": 6, "entries": 11, "coverage_pass": True})

    def test_the_session_is_launched_as_decision_9_gives_it(self):
        self.fake.script(respond=self.play_workflow(), role="absorb")
        self.absorb(fanout=WORKFLOW)
        request = self.fake.calls[0].request
        self.assertEqual(request.prompt.splitlines()[0], "/absorb research/refs/%s/absorb/manifest.json" % SLUG)
        self.assertEqual(request.allowed_tools, ["Workflow(absorb)", "Skill(absorb)", "Read", "Glob", "Grep"])
        for tool in READ_ONLY_REMOVALS:
            self.assertIn(tool, request.disallowed_tools)
        self.assertNotIn("Workflow", request.disallowed_tools)
        self.assertEqual(Path(request.cwd), self.project)
        self.assertEqual(request.env["CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS"], "0")
        self.assertIsNone(request.schema_path)
        agents = request.agent_json
        self.assertEqual({name: (agents[name]["model"], agents[name]["effort"]) for name in agents},
                         {"absorb": ("sonnet", "low"), "reader": ("sonnet", "medium"), "synthesizer": ("opus", "high")})
        args = args_from(request.prompt)
        self.assertEqual(args["reader"], {"model": "sonnet", "effort": "medium"})
        self.assertEqual(sum(len(chunk["obligations"]) for chunk in args["chunks"]), 11)

    def test_a_missing_item_fails_the_audit_with_the_missing_items(self):
        self.fake.script(respond=self.play_workflow(drop=("eq-2", "tab-1")), role="absorb")
        report = self.absorb(fanout=WORKFLOW)
        self.assertFalse(report["pass"])
        self.assertEqual(report["coverage"]["missing"], ["eq-2", "tab-1"])
        events, _ = self.ledger.read_events()
        self.assertFalse([event for event in events if event["event"] == "absorbed"][-1]["payload"]["coverage_pass"])
        self.assertIn("missing eq-2, tab-1", (self.refs / "dossier.md").read_text(encoding="utf-8"))

    def test_refused_narrow_rules_are_retried_with_the_broad_ones(self):
        self.fake.script(Envelope(session_id="session-0", permission_denials=[
            {"tool_name": "Skill", "tool_use_id": "t1", "tool_input": {"skill": "absorb"}}]), role="absorb")
        self.fake.script(respond=self.play_workflow(session_id="session-2"), role="absorb")
        report = self.absorb(fanout=WORKFLOW)
        self.assertEqual(len(self.fake.calls), 2)
        self.assertEqual(self.fake.calls[1].request.allowed_tools, ["Workflow", "Skill", "Read", "Glob", "Grep"])
        self.assertEqual(report["allow_rules"], "broad")
        self.assertEqual(report["session_ids"], ["session-0", "session-2"])
        self.assertTrue(report["pass"])
        self.assertTrue(any("narrow rules" in problem for problem in report["problems"]))

    def test_a_session_that_leaves_no_run_file_brings_nothing_back_and_writes_nothing(self):
        self.fake.script(Envelope(session_id="session-9", result_text="I could not start it."), role="absorb")
        with self.assertRaises(DossierError) as raised:
            self.absorb(fanout=WORKFLOW)
        self.assertIn("left no workflow run file", str(raised.exception))
        self.assertNotIn("l2", read_dossier(self.ledger, SLUG))
        self.assertFalse((self.refs / "entries.jsonl").exists())

    def test_a_paper_that_was_not_promoted_is_refused(self):
        self.write_dossier(level=1)
        with self.assertRaises(DossierError) as raised:
            self.absorb(fanout=WORKFLOW)
        self.assertIn("promotion", str(raised.exception))
        self.assertEqual(self.fake.calls, [])

    def test_a_paper_without_an_inventory_is_refused(self):
        (self.refs / "inventory.json").unlink()
        with self.assertRaises(DossierError):
            self.absorb(fanout=WORKFLOW)

    def test_a_sentence_locator_that_names_nothing_is_recorded(self):
        self.fake.script(respond=self.play_workflow(sections_value=sections(claim_locator="elsewhere.tex:3")), role="absorb")
        report = self.absorb(fanout=WORKFLOW)
        self.assertEqual(report["unresolved_locators"], ["elsewhere.tex:3"])

    def test_the_run_file_is_found_by_session_id_whatever_the_cwd_slug(self):
        run = self.projects_dir / "-some-other-slug" / "abc" / "workflows"
        run.mkdir(parents=True)
        (run / "wf_1.json").write_text(json.dumps({"status": "failed"}), encoding="utf-8")
        (run / "wf_2.json").write_text(json.dumps({"status": "completed"}), encoding="utf-8")
        self.assertEqual(find_run_file("abc", self.projects_dir).name, "wf_2.json")
        self.assertIsNone(find_run_file("nope", self.projects_dir))


class ConductorFanoutTest(AbsorbTestCase):
    """The fallback: one reader launch per chunk and one synthesizer, behind the same function."""

    def reader(self, drop=(), only_missing=False):
        known = items_by_id()

        def respond(request, message):
            if message is not None:
                wanted = re.findall(r"([a-z]+-[0-9]+)", message.split(":", 1)[1].split(".", 1)[0])
            else:
                wanted = OBLIGATION.findall(request.prompt.split("## The obligation list", 1)[1].split("\n## ", 1)[0])
            return Envelope(structured_output={"entries": [entry_for(known[item]) for item in wanted if item not in drop]})

        return respond

    def script_readers(self, count=6, **options):
        for _ in range(count):
            self.fake.script(respond=self.reader(**options), role="reader")

    def test_every_chunk_gets_a_reader_and_the_synthesizer_writes_the_sections(self):
        self.script_readers()
        self.fake.script(Envelope(structured_output=sections()), role="synthesizer")
        report = self.absorb(fanout=CONDUCTOR)
        self.assertTrue(report["pass"])
        self.assertEqual(report["coverage"]["covered"], 11)
        self.assertEqual([call.request.role for call in self.fake.calls], ["reader"] * 6 + ["synthesizer"])
        first = self.fake.calls[0].request
        self.assertEqual(Path(first.schema_path).name, "dossier_entry_list.json")
        self.assertEqual(first.allowed_tools, ["Read", "Glob", "Grep"])
        for tool in READ_ONLY_REMOVALS:
            self.assertIn(tool, first.disallowed_tools)
        self.assertEqual((first.model, first.effort), ("sonnet", "medium"))
        synthesizer = self.fake.calls[-1].request
        self.assertEqual((synthesizer.model, synthesizer.effort), ("opus", "high"))
        self.assertIn('"item_id": "fig-1"', synthesizer.prompt)
        dossier = read_dossier(self.ledger, SLUG)
        self.assertEqual(dossier["l2"]["fanout"], "conductor")
        self.assertIsNone(dossier["l2"]["allow_rules"])
        self.assertEqual(dossier["l2"]["cost"]["agents"], 7)
        chunks = {json.loads(line)["chunk_id"] for line in (self.refs / "entries.jsonl").read_text(encoding="utf-8").splitlines()}
        self.assertEqual(chunks, {"c-001", "c-002", "c-003", "c-004", "c-005", "c-006"})

    def test_a_reader_that_leaves_an_item_out_is_resumed_once_for_it(self):
        self.fake.script(respond=self.reader(), role="reader")
        self.fake.script(respond=self.reader(drop=("eq-2",)), role="reader")
        self.fake.script(respond=self.reader(), role="reader")  # the resume of the second chunk
        self.script_readers(count=4)
        self.fake.script(Envelope(structured_output=sections()), role="synthesizer")
        report = self.absorb(fanout=CONDUCTOR)
        resumes = [call for call in self.fake.calls if call.kind == "resume"]
        self.assertEqual(len(resumes), 1)
        self.assertIn("eq-2", resumes[0].message)
        self.assertTrue(report["coverage"]["pass"])
        self.assertEqual(report["failures"], [])

    def test_an_item_still_missing_after_the_resume_is_a_failure_of_its_chunk_and_fails_the_audit(self):
        self.fake.script(respond=self.reader(), role="reader")
        self.fake.script(respond=self.reader(drop=("eq-2",)), role="reader")
        self.fake.script(respond=self.reader(drop=("eq-2",)), role="reader")
        self.script_readers(count=4)
        self.fake.script(Envelope(structured_output=sections()), role="synthesizer")
        report = self.absorb(fanout=CONDUCTOR)
        self.assertEqual(report["coverage"]["missing"], ["eq-2"])
        self.assertEqual(report["failures"][0]["chunk"], "c-002")
        self.assertEqual(report["failures"][0]["missing"], ["eq-2"])

    def test_a_launcher_passed_without_a_resumer_resumes_nothing(self):
        self.fake.script(respond=self.reader(), role="reader")
        self.fake.script(respond=self.reader(drop=("eq-2",)), role="reader")
        self.script_readers(count=4)
        self.fake.script(Envelope(structured_output=sections()), role="synthesizer")
        report = self.absorb(fanout=CONDUCTOR, launcher=self.fake.launch)
        self.assertEqual([call for call in self.fake.calls if call.kind == "resume"], [])
        self.assertEqual(report["coverage"]["missing"], ["eq-2"])
        self.assertTrue(any("no resumer" in problem for problem in report["problems"]))

    def test_a_launcher_passed_with_its_resumer_resumes_through_it(self):
        self.fake.script(respond=self.reader(), role="reader")
        self.fake.script(respond=self.reader(drop=("eq-2",)), role="reader")
        self.fake.script(respond=self.reader(), role="reader")
        self.script_readers(count=4)
        self.fake.script(Envelope(structured_output=sections()), role="synthesizer")
        report = self.absorb(fanout=CONDUCTOR, launcher=self.fake.launch, resumer=self.fake.resume)
        self.assertEqual(len([call for call in self.fake.calls if call.kind == "resume"]), 1)
        self.assertTrue(report["coverage"]["pass"])

    def test_the_policy_picks_the_fan_out_when_none_is_named(self):
        (self.project / "harness.json").write_text(json.dumps({"policy": {"absorb": {"fanout": "conductor"}}}), encoding="utf-8")
        self.script_readers()
        self.fake.script(Envelope(structured_output=sections()), role="synthesizer")
        self.assertEqual(self.absorb()["fanout"], "conductor")

    def test_a_reader_the_usage_limit_refused_is_not_resumed(self):
        """Ticket 54 (decision 15): a refused session is never resumed, and its chunk fails with the reason."""
        self.fake.script(respond=self.reader(), role="reader")
        self.fake.script(Envelope(api_error_status=429, is_error=True, exit_code=1, session_id="refused-reader",
                                  errors=["You've hit your session limit · resets 3:45pm (UTC)"]), role="reader")
        self.script_readers(count=4)
        self.fake.script(Envelope(structured_output=sections()), role="synthesizer")
        report = self.absorb(fanout=CONDUCTOR)
        self.assertEqual([call for call in self.fake.calls if call.kind == "resume"], [])
        self.assertEqual(report["failures"][0]["chunk"], "c-002")
        self.assertIn("never resumed", report["failures"][0]["reason"])


class CoverageAuditTest(unittest.TestCase):
    def test_a_figure_answered_without_saying_what_it_shows_is_not_covered(self):
        record = inventory()
        entries = [entry_for(item) for item in items_by_id(record).values()]
        for entry in entries:
            if entry["item_id"] == "fig-1":
                for key in ("what_it_shows", "supports_cited_claim", "anything_odd"):
                    entry.pop(key)
        coverage = audit_coverage(record, entries)
        self.assertEqual((coverage["pass"], coverage["missing"]), (False, ["fig-1"]))

    def test_the_spot_check_takes_the_five_most_important_items_and_every_flaw(self):
        record = inventory()
        entries = [entry_for(item) for item in items_by_id(record).values()]
        ask, chosen, flaws = spot_check_ask(SLUG, record, entries, sections(), "sonnet", "research/refs/%s/source/flat.tex" % SLUG)
        self.assertEqual(chosen, ["eq-1", "eq-2", "sec-1", "sec-2", "sec-3"])
        self.assertEqual(flaws, 1)
        self.assertEqual((ask.role, ask.verdict_type, ask.subject_kind), ("critic", gates.DEPTH_SPOT_CHECK, "dossier"))
        self.assertIn("reported without a unit", ask.question)
        self.assertIn("research/refs/%s/entries.jsonl" % SLUG, ask.paths)


class SpotCheckTest(AbsorbTestCase):
    def test_the_queued_spot_check_is_taken_by_the_critic_and_recorded(self):
        self.fake.script(respond=self.play_workflow(), role="absorb")
        report = self.absorb(fanout=WORKFLOW)
        self.assertEqual(read_dossier(self.ledger, SLUG)["l2"]["spot_check"]["status"], "queued")
        self.assertEqual(report["spot_check"].role, "critic")

        self.fake.script(Envelope(structured_output={"pass": True, "findings": [], "question_limit": "the listed items and flaws"}), role="critic")
        verdict = take_spot_check(self.project, SLUG)
        self.assertTrue(verdict.passed)
        critic = self.fake.calls[-1].request
        # The readers wrote on sonnet and the synthesizer on opus: the critic is on neither.
        self.assertEqual((critic.role, critic.model), ("critic", "fable"))
        record = read_dossier(self.ledger, SLUG)["l2"]["spot_check"]
        self.assertEqual((record["status"], record["author_model"]), ("passed", "opus"))
        self.assertIn("Depth spot-check: passed by the critic.", (self.refs / "dossier.md").read_text(encoding="utf-8"))
        events, _ = self.ledger.read_events()
        verdicts = [event for event in events if event["event"] == "verdict"]
        self.assertEqual(verdicts[-1]["payload"]["verdict_type"], "depth_spot_check")
        self.assertEqual(verdicts[-1]["payload"]["subject_kind"], "dossier")
        with self.assertRaises(DossierError):
            take_spot_check(self.project, SLUG)

    def test_a_policy_that_sends_every_author_to_an_author_s_model_is_a_problem(self):
        (self.project / "harness.json").write_text(json.dumps(
            {"policy": {"verifier": {"opus": {"model": "sonnet", "effort": "high"}}}}), encoding="utf-8")
        self.fake.script(respond=self.play_workflow(), role="absorb")
        report = self.absorb(fanout=WORKFLOW)
        self.assertTrue(any("depth spot-check" in problem for problem in report["problems"]))


class VerbTest(AbsorbTestCase):
    def test_level_2_reads_one_paper_at_a_time(self):
        self.assertEqual(absorb_command(["--level", "2", "one", "two"]), 2)

    def test_a_role_the_gate_cannot_read_exits_1_rather_than_raising(self):
        (self.project / "harness.json").write_text("{}\n", encoding="utf-8")
        (self.project / ".claude" / "agents").mkdir(parents=True)
        (self.project / ".claude" / "agents" / "critic.md").write_text("---\nname: critic\n---\n\nNo description.\n", encoding="utf-8")
        self.fake.script(respond=self.play_workflow(), role="absorb")
        config = self.temp / "claude-config"
        self.projects_dir = config / "projects"
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(config)}):
            code = absorb_command(["--level", "2", SLUG, "--project", str(self.project), "--spot-check"])
        self.assertEqual(code, 1)
        self.assertEqual(read_dossier(self.ledger, SLUG)["l2"]["spot_check"]["status"], "queued")


if __name__ == "__main__":
    unittest.main()
