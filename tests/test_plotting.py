"""The plotting library switch (Implementation Decision 17; ticket 102).

Plain functions over a temporary project: `harness.json`'s `plotting` with each value and without the key,
`wayline switch --plotting` writing `harness.json` and then journaling `control`, the install of a library's
tools through the tool runner's recordings (seam 6, `tests.test_software.ProjectMachine`) into a temporary tools
home, a drawing's brief naming its library, the clean room running an R script, and the decider refused.
"""

import json
import os
import stat
import sys
from pathlib import Path
from unittest import mock

from tests.projects import ProjectTestCase
from tests.test_results import file
from tests.test_software import ProjectMachine
from tests.test_tools import read_json
from wayline import drawing_checks, drawings, plotting, project as projects
from wayline.jsonschema import ValidationError, check, load_schema
from wayline.ledger import Ledger
from wayline.tools import TOOLS_JSON, ToolOutput, Tools, record_entry, tool_entry

R1 = "Do the products raise the AUROC?"


class PlottingMachine(ProjectMachine):
    """The recordings, and what the tools venv and an R prefix answer for the plotting libraries' own packages."""

    def __init__(self, **options):
        super().__init__(versions={"altair": "5.5.0", "vl-convert-python": "1.8.0"}, **options)

    def __call__(self, argv, cwd=None, timeout=None, env=None):
        argv = [str(part) for part in argv]
        if Path(argv[0]).name == "Rscript" and argv[1] == "-e" and "packageVersion" in argv[2]:
            self.calls.append((argv, dict(env or {})))
            return ToolOutput(0, b"3.5.2", b"")
        return super().__call__(argv, cwd=cwd, timeout=timeout, env=env)


class PlottingCase(ProjectTestCase):
    def setUp(self):
        super().setUp()
        self.project = self.temp / "plotting-project"
        projects.init_project(self.project, harness_root=self.fake_harness(), git=False)
        self.ledger = Ledger(self.project)
        self.root = self.temp / "tools"
        self.machine = PlottingMachine()

    def harness(self):
        return json.loads((self.project / "harness.json").read_text(encoding="utf-8"))

    def controls(self):
        return [event["payload"] for event in self.ledger.read_events()[0]
                if event["event"] == "control" and event["payload"]["command"] == "plotting"]

    def record(self, *names):
        """Record `names` in the temporary tools home as if they were installed, each with an executable that exists."""
        for name in names:
            executable = self.root / "bin" / name
            executable.parent.mkdir(parents=True, exist_ok=True)
            executable.write_text("#!/bin/sh\n", encoding="utf-8")
            record_entry(self.root, name, tool_entry(executable, "1.0", "uv"))

    def switch(self, library, **options):
        return plotting.set_plotting(self.project, library, root=self.root, run=self.machine, **options)


class SchemaTest(PlottingCase):
    def test_each_library_is_in_the_schema_and_nothing_else(self):
        schema = load_schema("harness")
        for library in ("matplotlib", "altair", "ggplot2"):
            check(dict(self.harness(), plotting=library), schema)
        with self.assertRaises(ValidationError):
            check(dict(self.harness(), plotting="plotly"), schema)

    def test_a_project_without_the_key_draws_with_matplotlib_and_seaborn(self):
        self.assertNotIn("plotting", self.harness())
        self.assertEqual(plotting.setting(self.harness()), "matplotlib")
        self.assertEqual(plotting.setting({"plotting": "ggplot2"}), "ggplot2")


class SwitchTest(PlottingCase):
    def test_switch_writes_harness_json_first_and_then_journals_control(self):
        self.record("altair")
        seen = []
        real = projects.control

        def control(project, command, args=None, by="cli"):
            seen.append(self.harness().get("plotting"))
            return real(project, command, args, by=by)

        with mock.patch.object(projects, "control", control):
            report = self.switch("altair")
        self.assertEqual(seen, ["altair"], "harness.json held the setting when control was journaled")
        self.assertEqual((report["from"], report["to"], report["changed"]), ("matplotlib", "altair", True))
        [event] = self.controls()
        self.assertEqual(event["args"], {"plotting": "altair", "from": "matplotlib"})
        self.assertEqual(event["by"], "cli")

    def test_the_same_library_again_changes_nothing(self):
        self.record("altair")
        self.switch("altair")
        report = self.switch("altair")
        self.assertFalse(report["changed"])
        self.assertEqual(len(self.controls()), 1)

    def test_switching_back_to_matplotlib_is_allowed_at_any_time(self):
        self.record("altair", "matplotlib", "seaborn")
        self.switch("altair")
        self.switch("matplotlib", by="dashboard")
        self.assertEqual(self.harness()["plotting"], "matplotlib")
        self.assertEqual(self.controls()[-1]["by"], "dashboard")

    def test_accepted_with_a_conductor_running(self):
        self.record("altair")
        with mock.patch.object(projects, "conductor_holder", return_value={"pid": 4242}):
            report = self.switch("altair")
        self.assertEqual(report["conductor"], {"pid": 4242})
        self.assertEqual(self.harness()["plotting"], "altair")

    def test_the_decider_has_no_path_to_change_it(self):
        self.record("altair")
        for by in ("decider", "conductor", "code"):
            with self.assertRaises(projects.ProjectError):
                self.switch("altair", by=by)
        self.assertNotIn("plotting", self.harness())
        self.assertEqual(self.controls(), [])
        from wayline import decider
        self.assertNotIn("plotting", Path(decider.__file__).read_text(encoding="utf-8"))

    def test_the_verb(self):
        self.record("ggplot2")
        from wayline import cli
        with mock.patch.object(plotting, "tools_home", return_value=self.root), mock.patch.object(plotting, "run_tool", self.machine):
            code = cli.main(["switch", "--plotting", "ggplot2", "--project", str(self.project)])
        self.assertEqual(code, 0)
        self.assertEqual(self.harness()["plotting"], "ggplot2")


class InstallTest(PlottingCase):
    def test_altair_is_installed_into_the_tools_venv_through_uv_on_the_owners_word(self):
        self.switch("altair")
        entry = read_json(self.root / TOOLS_JSON)["tools"]["altair"]
        self.assertEqual((entry["route"], entry["version"]), ("uv", "5.5.0"))
        self.assertEqual(entry["executable"], str(self.root / "venv" / "bin" / "python"))
        installs = [argv for argv, _ in self.machine.ran("uv") if argv[1:3] == ["pip", "install"]]
        self.assertEqual(installs[-1][-2:], ["vl-convert-python", "altair"])
        installed = [event["payload"] for event in self.ledger.read_events()[0] if event["event"] == "tool_installed"]
        self.assertEqual([(item["name"], item["outcome"]) for item in installed], [("altair", "installed")])
        self.assertEqual(self.harness()["plotting"], "altair")

    def test_ggplot2_comes_with_r_from_conda_forge(self):
        self.switch("ggplot2")
        tools = read_json(self.root / TOOLS_JSON)["tools"]
        self.assertEqual(tools["ggplot2"]["executable"], str(self.root / "envs" / "r" / "bin" / "Rscript"))
        self.assertEqual(tools["ggplot2"]["version"], "3.5.2")
        self.assertIn("rscript", tools)
        made = [argv for argv, _ in self.machine.ran("micromamba") if argv[1] in ("create", "install")]
        for package in ("r-base", "r-ggplot2", "r-svglite", "r-jsonlite"):
            self.assertIn(package, made[0])

    def test_ggplot2_beside_an_installed_r_names_only_its_own_packages(self):
        from wayline import software
        software.install_project_tool("r", root=self.root, run=self.machine)
        self.machine.calls.clear()
        self.switch("ggplot2")
        [made] = [argv for argv, _ in self.machine.ran("micromamba") if argv[1] in ("create", "install")]
        self.assertEqual(made[1], "install")
        self.assertNotIn("r-base", made)
        self.assertEqual(made[-3:], ["r-ggplot2", "r-svglite", "r-jsonlite"])

    def test_the_dashboard_calls_a_project_function(self):
        self.record("altair")
        projects.set_plotting(self.project, "altair", by="dashboard", root=self.root, run=self.machine)
        self.assertEqual(self.controls()[-1]["by"], "dashboard")

    def test_recorded_tools_are_not_installed_again(self):
        self.record("altair")
        self.switch("altair")
        self.assertEqual(self.machine.calls, [])

    def test_a_failed_install_leaves_the_setting_unchanged_and_says_why(self):
        self.machine = PlottingMachine(fail=lambda argv: argv[1:3] == ["pip", "install"])
        with self.assertRaises(projects.ProjectError) as caught:
            self.switch("altair")
        self.assertIn("altair", str(caught.exception))
        self.assertIn("recorded failure", str(caught.exception))
        self.assertNotIn("plotting", self.harness())
        self.assertEqual(self.controls(), [])
        installed = [event["payload"] for event in self.ledger.read_events()[0] if event["event"] == "tool_installed"]
        self.assertEqual([(item["name"], item["outcome"]) for item in installed], [("altair", "failed")])


class DrawingTest(PlottingCase):
    def setUp(self):
        super().setUp()
        (self.project / "results").mkdir(exist_ok=True)
        (self.project / "results" / "summary.json").write_text('{"auroc": 0.71}\n', encoding="utf-8")
        from wayline.provenance import register_artifact
        register_artifact(self.ledger, "results/summary.json", None, "t2-a1", 2)
        file(self.ledger, "t2-a1-f1", "The products raise the AUROC to 0.71.", R1)

    def ticket(self, identifier):
        from wayline import tickets
        return {fields["id"]: fields for fields in tickets.read_tickets(self.project)}[identifier]

    def test_the_next_drawing_runs_in_the_chosen_library_and_its_brief_names_it(self):
        self.record("ggplot2")
        self.switch("ggplot2")
        [identifier] = drawings.open_drawings(self.project, drawings.RUN_END)
        self.assertEqual(drawings.read_records(self.project, "R1")[-1]["library"], "ggplot2")
        text = drawings.brief(self.project, self.ticket(identifier))
        self.assertIn("R with ggplot2", text)
        self.assertIn("wayline tools run ggplot2 --", text)
        self.assertIn(".R", text)

    def test_a_drawing_keeps_the_library_it_was_opened_in(self):
        self.record("altair", "matplotlib")
        [identifier] = drawings.open_drawings(self.project, drawings.RUN_END)
        self.switch("altair")
        self.assertEqual(drawings.library_of(self.project, self.ticket(identifier)), "matplotlib")
        text = drawings.brief(self.project, self.ticket(identifier))
        self.assertIn("matplotlib and seaborn", text)
        self.assertEqual(plotting.interpreter("matplotlib", Tools(self.root)), str(self.root / "bin" / "matplotlib"))
        self.assertEqual(plotting.interpreter("altair", Tools(self.root)), str(self.root / "bin" / "altair"))
        self.assertIsNone(plotting.interpreter("ggplot2", Tools(self.root)))

    def test_a_script_in_another_language_than_the_drawings_library_fails_it_unrun(self):
        self.record("ggplot2")
        self.switch("ggplot2")
        [identifier] = drawings.open_drawings(self.project, drawings.RUN_END)
        worktree = self.temp / "worktree"
        folder = worktree / "drawings" / "R1-1"
        folder.mkdir(parents=True)
        (folder / "draw.py").write_text("print(1)\n", encoding="utf-8")
        (folder / "numbers.json").write_text("{}\n", encoding="utf-8")
        (folder / "drawing.json").write_text(json.dumps({"script": "draw.py", "numbers": "numbers.json", "synthesis": "s",
                                                          "headline": "h", "inputs": ["results/summary.json"]}), encoding="utf-8")
        checked = drawings.check(self.project, self.ticket(identifier), worktree)
        self.assertTrue(any("not a .R script" in problem for problem in checked.problems), checked.problems)

    def test_a_record_from_before_the_switch_is_matplotlib(self):
        self.assertEqual(plotting.setting({}), drawings.library_of_record({}))


class CleanRoomTest(PlottingCase):
    def test_an_r_script_is_rerun_by_the_libraries_rscript(self):
        rscript = self.temp / "Rscript"
        rscript.write_text("#!/bin/sh\n[ \"$1\" = --vanilla ] || exit 3\ncd \"$(dirname \"$2\")\" && echo drawn > out.svg\n", encoding="utf-8")
        rscript.chmod(rscript.stat().st_mode | stat.S_IEXEC)
        source = self.temp / "drawing"
        source.mkdir()
        (source / "draw.R").write_text("library(ggplot2)\n", encoding="utf-8")
        room = drawing_checks.rerun(self.project, source, "drawings/R1-1", "draw.R", [], str(rscript))
        try:
            self.assertTrue(room.ran)
            self.assertEqual(room.returncode, 0, room.error)
            self.assertEqual((room.root / "drawings" / "R1-1" / "out.svg").read_text(encoding="utf-8").strip(), "drawn")
        finally:
            room.close()

    def test_a_script_of_another_language_is_not_rerun(self):
        room = drawing_checks.rerun(self.project, self.temp, "d", "draw.jl", [], sys.executable)
        self.assertFalse(room.ran)
