"""A project's tools, its packages, licensed software, and the `software` decision (ticket 82).

Every install runs against `ProjectMachine`, the tool runner's recordings (seam 6) that ticket 75's
`Machine` keeps for the harness's tools, extended to a project's: micromamba's dry run for Octave
and for R (`fixtures/tools/recorded/micromamba-dry-run-*.json`, run on the owner's workstation
2026-10-18 against conda-forge, trimmed to each package's name, version, and size), Julia's
published checksums and the headers of its tarball (recorded the same day), `R --version` and
`Rscript --version` from the workstation's R, and uv's freeze of a project venv it built. Octave,
Julia, and MATLAB are not on the workstation, so what `octave --version`, `julia --version`, and
`matlab -batch "ver"` print is written in each program's documented shape under
`fixtures/tools/written/`, not recorded. Nothing is downloaded, and nothing is written under the
owner's `~/.wayline/tools`: each test installs into a temporary tools home.
"""

import argparse
import gzip
import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from tests import machine as test_machine
from tests import test_conductor, test_plan
from tests.paths import FIXTURES_DIR
from tests.projects import ProjectTestCase, open_objective
from tests.test_tools import Machine, read_json, sha256
from wayline import batches, decider, decisions, plan, project, resources, schedule, software, tickets, worker
from wayline.conductor import Conductor
from wayline.jsonschema import check, load_schema
from wayline.ledger import Ledger
from wayline.tools import TOOLS_JSON, ToolOutput, Tools, ToolsError, record_entry, tool_entry

RECORDED = FIXTURES_DIR / "tools" / "recorded"
WRITTEN = FIXTURES_DIR / "tools" / "written"


def julia_tarball(version=software.JULIA_VERSION):
    """A tarball laid out as Julia's release is: one `julia-<version>/` folder with `bin/julia` and a library symlink.

    The gzip header's time is fixed, so every build has the same bytes and the same digest; with the build time in it, a
    test comparing a recorded digest with a second build failed whenever the two straddled a second.
    """
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as tar:
        body = b"#!/bin/sh\necho julia\n"
        info = tarfile.TarInfo("julia-%s/bin/julia" % version)
        info.size, info.mode = len(body), 0o755
        tar.addfile(info, io.BytesIO(body))
        lib = b"\x7fELF libjulia"
        info = tarfile.TarInfo("julia-%s/lib/libjulia.so.1.12" % version)
        info.size, info.mode = len(lib), 0o644
        tar.addfile(info, io.BytesIO(lib))
        link = tarfile.TarInfo("julia-%s/lib/libjulia.so" % version)
        link.type, link.linkname = tarfile.SYMTYPE, "libjulia.so.1.12"
        tar.addfile(link)
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", mtime=0) as packed:
        packed.write(raw.getvalue())
    return buffer.getvalue()


def julia_downloads(tarball=None):
    """Julia's tarball and its published checksums, the recorded file with the tarball's own line in place of the real one."""
    tarball = julia_tarball() if tarball is None else tarball
    url = software.julia_url()
    name = url.rsplit("/", 1)[-1]
    lines = [line if not line.endswith("  " + name) else "%s  %s" % (sha256(tarball), name)
             for line in (RECORDED / "julia-1.12.7.sha256").read_text(encoding="utf-8").splitlines()]
    return {url: tarball, software.julia_checksums_url(): ("\n".join(lines) + "\n").encode()}


class ProjectMachine(Machine):
    """Ticket 75's recordings, and what micromamba, Octave, R, Julia, uv, and MATLAB answer for a project's tools."""

    def __init__(self, downloads=None, fail=None, versions=None, matlab=None):
        super().__init__(downloads=downloads, fail=fail, versions=versions)
        self.downloads.update(julia_downloads())
        self.matlab = matlab
        # What Octave's `pkg list` prints, in its documented shape.
        self.octave_list = b"Package Name  | Version | Installation directory\n--------------+---------+-----------------------\n      signal  |   1.4.5 | /prefix/share/octave/packages/signal-1.4.5\n"

    def __call__(self, argv, cwd=None, timeout=None, env=None):
        argv = [str(part) for part in argv]
        name = Path(argv[0]).name
        if self.fail(argv):
            self.calls.append((argv, dict(env or {})))
            return ToolOutput(1, b"", b"error: the recorded failure")
        if name == "micromamba" and "--dry-run" in argv:
            self.calls.append((argv, dict(env or {})))
            which = "r" if "r-base" in argv else "octave"
            return ToolOutput(0, (RECORDED / ("micromamba-dry-run-%s.json" % which)).read_bytes(), b"")
        if name == "micromamba" and argv[1] in ("create", "install", "update") and "--dry-run" not in argv:
            self.calls.append((argv, dict(env or {})))
            prefix = Path(argv[argv.index("-p") + 1])
            (prefix / "bin").mkdir(parents=True, exist_ok=True)
            (prefix / "conda-meta").mkdir(exist_ok=True)
            for program in ("octave", "R", "Rscript", "pandoc", "pandoc-crossref"):
                (prefix / "bin" / program).write_text("#!/bin/sh\n", encoding="utf-8")
            return ToolOutput(0, b"", b"")
        if name == "curl" and "-fsSIL" in argv:
            self.calls.append((argv, dict(env or {})))
            return ToolOutput(0, (RECORDED / "julia-1.12.7-head.txt").read_bytes(), b"")
        if argv[1:] == ["--version"] and name in ("octave", "julia"):
            self.calls.append((argv, dict(env or {})))
            return ToolOutput(0, (WRITTEN / ("%s--version.txt" % name)).read_bytes(), b"")
        if argv[1:] == ["--version"] and name in ("R", "Rscript"):
            self.calls.append((argv, dict(env or {})))
            return ToolOutput(0, (RECORDED / ("%s--version.txt" % name)).read_bytes(), b"")
        if name == "uv" and argv[1:3] == ["pip", "freeze"] and ".venv" in argv[-1]:
            self.calls.append((argv, dict(env or {})))
            return ToolOutput(0, (RECORDED / "uv-pip-freeze-project.txt").read_bytes(), b"")
        if name == "Rscript" and argv[1] == "-e":
            self.calls.append((argv, dict(env or {})))
            Path(env["WAYLINE_LOCK"]).write_text('{"R": {"Version": "4.4.3"}, "Packages": {}}\n', encoding="utf-8")
            return ToolOutput(0, b"", b"")
        if name == "julia" and "-e" in argv:
            self.calls.append((argv, dict(env or {})))
            project = Path([part for part in argv if part.startswith("--project=")][0].split("=", 1)[1])
            project.mkdir(parents=True, exist_ok=True)
            (project / "Project.toml").write_text("[deps]\n", encoding="utf-8")
            (project / "Manifest.toml").write_text("# This file is machine-generated\njulia_version = \"1.12.7\"\n", encoding="utf-8")
            return ToolOutput(0, b"", b"")
        if name == "octave" and "--eval" in argv:
            self.calls.append((argv, dict(env or {})))
            if "'list'" in argv[-1]:
                return ToolOutput(0, self.octave_list, b"")
            return ToolOutput(0, b"", b"")
        if name == "matlab" and argv[1:] == ["-batch", "ver"]:
            self.calls.append((argv, dict(env or {})))
            if self.matlab is not None:
                return self.matlab
            return ToolOutput(0, (WRITTEN / "matlab-batch-ver.txt").read_bytes(), b"")
        return super().__call__(argv, cwd=cwd, timeout=timeout, env=env)


class ProjectToolInstallTest(ProjectTestCase):
    def setUp(self):
        super().setUp()
        self.root = self.temp / "tools"
        self.machine = ProjectMachine()

    def install(self, name, machine=None, **options):
        return software.install_project_tool(name, root=self.root, run=machine or self.machine, **options)

    def entry(self, name):
        return read_json(self.root / TOOLS_JSON)["tools"][name]

    def test_octave_comes_from_conda_forge_through_micromamba_into_a_prefix_of_its_own(self):
        self.install("octave")
        entry = self.entry("octave")
        prefix = self.root / "envs" / "octave"
        self.assertEqual(entry["executable"], str(prefix / "bin" / "octave"))
        self.assertEqual((entry["version"], entry["route"], entry["source"], entry["installer"]), ("10.3.0", "micromamba", "conda-forge", "harness"))
        self.assertTrue(entry["installed"])
        self.assertIsInstance(entry["env"], dict)
        self.assertEqual(entry["lock"]["path"], str(self.root / "locks" / "octave.txt"))
        self.assertEqual(entry["lock"]["sha256"], hashlib.sha256((RECORDED / "micromamba-env-export.txt").read_bytes()).hexdigest())
        calls = [argv for argv, _ in self.machine.ran("micromamba") if argv[1] in ("create", "install")]
        self.assertEqual(calls, [[str(self.root / "bin" / "micromamba"), "create", "-y", "-p", str(prefix), "-c", "conda-forge", "--override-channels", "octave"]])
        for _, env in self.machine.ran("micromamba"):
            self.assertEqual(env["MAMBA_ROOT_PREFIX"], str(self.root / "mamba"))

    def test_r_records_r_and_rscript_from_one_prefix(self):
        self.install("r")
        self.assertEqual(self.entry("r")["executable"], str(self.root / "envs" / "r" / "bin" / "R"))
        self.assertEqual(self.entry("rscript")["executable"], str(self.root / "envs" / "r" / "bin" / "Rscript"))
        self.assertEqual((self.entry("r")["version"], self.entry("rscript")["version"]), ("4.4.3", "4.4.3"))
        created = [argv for argv, _ in self.machine.ran("micromamba") if argv[1] == "create"]
        self.assertEqual(created[0][-2:], ["r-base", "r-renv"])

    def test_julia_comes_from_its_tarball_checked_against_the_published_checksums(self):
        self.install("julia")
        entry = self.entry("julia")
        folder = self.root / ("julia-%s" % software.JULIA_VERSION)
        self.assertEqual(entry["executable"], str(folder / "bin" / "julia"))
        self.assertEqual((entry["version"], entry["route"], entry["installer"]), ("1.12.7", "tarball", "harness"))
        self.assertEqual(entry["source"], software.julia_url())
        self.assertEqual(entry["digest"], "sha256:" + sha256(julia_tarball()))
        self.assertTrue((folder / "lib" / "libjulia.so").is_symlink())
        self.assertEqual(entry["env"]["JULIA_DEPOT_PATH"], str(self.root / "julia" / "depot"))

    def test_a_julia_tarball_whose_digest_does_not_match_is_refused_and_nothing_is_kept(self):
        machine = ProjectMachine()
        machine.downloads[software.julia_url()] = julia_tarball() + b"tampered"
        with self.assertRaises(ToolsError) as caught:
            self.install("julia", machine)
        self.assertIn("digest mismatch", str(caught.exception))
        self.assertFalse((self.root / ("julia-%s" % software.JULIA_VERSION)).exists())
        self.assertIsNone(Tools(self.root).entry("julia"))

    def test_nothing_is_ever_installed_with_root(self):
        for name in ("octave", "r", "julia"):
            self.install(name)
        for argv, _ in self.machine.calls:
            self.assertNotIn(Path(argv[0]).name, ("sudo", "su", "apt", "apt-get", "dnf", "yum", "pkexec"))

    def test_an_installed_tool_is_left_as_it_is(self):
        first = self.install("octave")
        calls = len(self.machine.calls)
        again = self.install("octave")
        self.assertEqual(again, first)
        self.assertEqual(len(self.machine.calls), calls, "an installed tool is not installed again")

    def test_changing_an_installed_tool_is_the_owners_word_alone(self):
        self.install("octave")
        for who in (None, "decider", "code"):
            with self.subTest(by=who), self.assertRaises(ToolsError) as caught:
                self.install("octave", change=True, by=who)
            self.assertIn("owner", str(caught.exception))
        self.install("octave", change=True, by="owner")
        updated = [argv for argv, _ in self.machine.ran("micromamba") if argv[1] == "update"]
        self.assertEqual(len(updated), 1)

    def test_licensed_software_is_never_installed_by_code(self):
        with self.assertRaises(ToolsError) as caught:
            self.install("matlab")
        self.assertIn("licensed", str(caught.exception))
        self.assertFalse(any(Path(argv[0]).name == "curl" for argv, _ in self.machine.calls))

    def test_a_name_that_is_no_project_tool_is_refused(self):
        with self.assertRaises(ToolsError):
            self.install("photoshop")


class LicensedSoftwareTest(ProjectTestCase):
    def setUp(self):
        super().setUp()
        self.root = self.temp / "tools"
        self.matlab = self.temp / "MATLAB" / "R2024b" / "bin" / "matlab"
        self.matlab.parent.mkdir(parents=True)
        self.matlab.write_text("#!/bin/sh\n", encoding="utf-8")

    def test_the_owner_says_where_and_code_records_it_after_one_ver_check(self):
        machine = ProjectMachine()
        entry = software.record_licensed("matlab", self.matlab, root=self.root, run=machine)
        self.assertEqual([argv for argv, _ in machine.calls], [[str(self.matlab), "-batch", "ver"]])
        recorded = read_json(self.root / TOOLS_JSON)["tools"]["matlab"]
        self.assertEqual(recorded, entry)
        self.assertEqual((entry["executable"], entry["installer"], entry["route"]), (str(self.matlab), "owner", "owner"))
        self.assertEqual((entry["version"], entry["release"]), ("24.2.0.2712019", "R2024b"))
        self.assertEqual(entry["toolboxes"], {"Optimization Toolbox": "24.2", "Signal Processing Toolbox": "24.2",
                                              "Statistics and Machine Learning Toolbox": "24.2"})
        self.assertNotIn("000000", json.dumps(recorded), "the license number is never kept")

    def test_a_failing_check_records_nothing(self):
        machine = ProjectMachine(matlab=ToolOutput(1, b"", b"License checkout failed.\nLicense Manager Error -9"))
        with self.assertRaises(ToolsError) as caught:
            software.record_licensed("matlab", self.matlab, root=self.root, run=machine)
        self.assertIn("License Manager Error -9", str(caught.exception))
        self.assertIsNone(Tools(self.root).entry("matlab"))

    def test_a_check_that_prints_no_version_records_nothing(self):
        machine = ProjectMachine(matlab=ToolOutput(0, b"hello\n", b""))
        with self.assertRaises(ToolsError):
            software.record_licensed("matlab", self.matlab, root=self.root, run=machine)
        self.assertIsNone(Tools(self.root).entry("matlab"))

    def test_the_place_is_an_absolute_path_that_exists(self):
        for where in ("matlab", str(self.temp / "nowhere" / "matlab"), ""):
            with self.subTest(where=where), self.assertRaises(ToolsError):
                software.record_licensed("matlab", where, root=self.root, run=ProjectMachine())


class ProjectPackagesTest(ProjectTestCase):
    """A project's packages go into its own environment with no ask, each gitignored and locked under `code/`."""

    def setUp(self):
        super().setUp()
        self.root = self.temp / "tools"
        self.project = self.temp / "toy"
        self.project.mkdir()
        project.init_project(self.project)
        self.machine = ProjectMachine()

    def packages(self, language, names, **options):
        return software.install_packages(self.project, language, names, root=self.root, run=self.machine, **options)

    def tracked(self, path):
        """Whether git would track the path: it is not ignored by the project's `.gitignore`."""
        done = subprocess.run(["git", "-C", str(self.project), "check-ignore", "-q", str(path)], capture_output=True)
        return done.returncode != 0

    def test_python_packages_go_through_the_harness_uv_into_the_project_venv(self):
        done = self.packages("python", ["six==1.17.0"])
        venv = self.project / ".venv"
        uv = str(self.root / "bin" / "uv")
        ran = [argv for argv, _ in self.machine.ran("uv")]
        self.assertIn([uv, "venv", "--python", sys.executable, str(venv)], ran)
        self.assertIn([uv, "pip", "install", "--python", str(venv / "bin" / "python"), "six==1.17.0"], ran)
        lock = self.project / "code" / "requirements.lock"
        self.assertEqual((done["environment"], done["lock"]), (str(venv), str(lock)))
        self.assertIn("six==1.17.0", lock.read_text(encoding="utf-8"))
        self.assertFalse(self.tracked(venv), "the venv is gitignored")
        self.assertTrue(self.tracked(lock), "the lock is tracked under code/")
        self.assertFalse(any(Path(argv[0]).name in ("pip", "pip3") or argv[1:3] == ["-m", "venv"] for argv, _ in self.machine.calls))

    def test_no_package_asks_or_opens_a_decision(self):
        self.packages("python", ["six"])
        self.assertEqual([fields for fields in tickets.read_tickets(self.project) if fields["kind"] == "decision"], [])

    def test_r_packages_come_from_conda_forge_into_a_project_library_locked_by_renv(self):
        software.install_project_tool("r", root=self.root, run=self.machine)
        done = self.packages("r", ["data.table"])
        library = self.project / ".wayline" / "packages" / "r"
        created = [argv for argv, _ in self.machine.ran("micromamba") if argv[1] == "create" and str(library) in argv]
        self.assertEqual(created[0][-2:], ["r-base=4.4.3", "r-data.table"])
        snapshot = self.machine.ran("Rscript")[-1]
        self.assertEqual(snapshot[1]["R_LIBS"], str(library / "lib" / "R" / "library"))
        lock = self.project / "code" / "renv.lock"
        self.assertEqual(done["lock"], str(lock))
        self.assertTrue(lock.is_file())
        self.assertFalse(self.tracked(library))
        self.assertTrue(self.tracked(lock))

    def test_julia_packages_go_into_the_project_environment_under_code(self):
        software.install_project_tool("julia", root=self.root, run=self.machine)
        done = self.packages("julia", ["DifferentialEquations"])
        argv, env = self.machine.ran("julia")[-1]
        self.assertIn("--project=%s" % (self.project / "code"), argv)
        self.assertEqual(argv[-1], "DifferentialEquations")
        self.assertEqual(env["JULIA_DEPOT_PATH"], str(self.root / "julia" / "depot"))
        self.assertEqual(done["lock"], str(self.project / "code" / "Manifest.toml"))
        self.assertTrue(self.tracked(self.project / "code" / "Manifest.toml"))

    def test_octave_forge_goes_into_the_shared_prefix_unless_two_projects_disagree(self):
        software.install_project_tool("octave", root=self.root, run=self.machine)
        done = self.packages("octave", ["signal"])
        self.assertEqual(done["environment"], str(self.root / "envs" / "octave"))
        self.assertIn("-global", self.machine.ran("octave")[-2][0][-1])
        self.assertIn("signal", (self.project / "code" / "octave-packages.lock").read_text(encoding="utf-8"))
        other = self.temp / "other"
        other.mkdir()
        project.init_project(other)
        agreeing = software.install_packages(other, "octave", ["signal=1.4.5"], root=self.root, run=self.machine)
        self.assertEqual(agreeing["environment"], str(self.root / "envs" / "octave"))
        self.machine.octave_list = self.machine.octave_list.replace(b"1.4.5", b"1.3.0")  # what its own prefix holds
        disagreeing = software.install_packages(other, "octave", ["signal=1.3.0"], root=self.root, run=self.machine)
        self.assertEqual(disagreeing["environment"], str(other / ".wayline" / "packages" / "octave"))
        argv, env = self.machine.ran("octave")[-2]
        self.assertNotIn("-global", argv[-1])
        self.assertEqual(env["WAYLINE_OCTAVE_PKG"], str(other / ".wayline" / "packages" / "octave"))

    def test_an_unpinned_package_the_shared_prefix_holds_is_not_upgraded_for_everyone(self):
        software.install_project_tool("octave", root=self.root, run=self.machine)
        self.packages("octave", ["signal"])
        installs = len([argv for argv, _ in self.machine.ran("octave") if "'install'" in argv[-1]])
        other = self.temp / "other"
        other.mkdir()
        project.init_project(other)
        software.install_packages(other, "octave", ["signal"], root=self.root, run=self.machine)
        self.assertEqual(len([argv for argv, _ in self.machine.ran("octave") if "'install'" in argv[-1]]), installs)
        self.assertIn("signal", (other / "code" / "octave-packages.lock").read_text(encoding="utf-8"))

    def test_a_pin_octave_forge_does_not_serve_is_refused(self):
        software.install_project_tool("octave", root=self.root, run=self.machine)
        self.packages("octave", ["signal"])
        other = self.temp / "other"
        other.mkdir()
        project.init_project(other)
        with self.assertRaises(ToolsError) as caught:
            software.install_packages(other, "octave", ["signal=1.3.0"], root=self.root, run=self.machine)
        self.assertIn("Octave Forge serves signal 1.4.5, not 1.3.0", str(caught.exception))

    def test_packages_of_a_tool_not_recorded_wait_for_its_software_decision(self):
        for language in ("r", "julia", "octave"):
            with self.subTest(language=language), self.assertRaises(ToolsError) as caught:
                self.packages(language, ["anything"])
            self.assertIn("software decision", str(caught.exception))

    def test_a_package_name_that_reads_as_a_flag_is_refused(self):
        for names in ([], ["--index-url=https://example.org"], ["six; rm -rf /"], [""]):
            with self.subTest(names=names), self.assertRaises(ToolsError):
                self.packages("python", names)


def experiment_ticket(identifier=1, **extra):
    value = {"id": identifier, "title": "Run the model %d" % identifier, "kind": "experiment", "difficulty": 2, "status": "open",
             "blocked_by": [], "touches": ["scripts/"], "role": "experimenter", "skills": [],
             "acceptance": {"machine": ["test -f scripts/run.m"], "quality": []}, "context_pack": ["research/INTAKE.md"],
             "origin": "research/INTAKE.md#the-intent", "proposed_by": "planner", "demo": "the model runs"}
    value.update(extra)
    return value


class JobToolTest(ProjectTestCase):
    """A job spec names a tool, and the job record carries every tool it called."""

    def setUp(self):
        super().setUp()
        self.project = self.temp / "toy"
        self.project.mkdir()
        project.init_project(self.project)
        self.ledger = Ledger(self.project)
        tickets.write_ticket(self.ledger, experiment_ticket(1, software=["octave"]), "## Demo\n\nthe model runs\n")
        self.root = Path(os.environ["WAYLINE_HOME"]) / "tools"
        self.octave = record_entry(self.root, "octave", tool_entry(
            "/opt/tools/envs/octave/bin/octave", "10.3.0", "micromamba", env={"OCTAVE_HOME": "/opt/tools/envs/octave"},
            lock={"path": "/opt/tools/locks/octave.txt", "sha256": "ab" * 32}))

    def test_job_add_writes_the_tools_executable_and_environment_into_command_and_env(self):
        [record] = resources.add_jobs(self.project, {"tool": "octave", "command": ["octave", "--eval", "run('scripts/run.m')"],
                                                     "env": {"SEED": "1"}}, ticket=1)
        self.assertEqual(record["command"], ["/opt/tools/envs/octave/bin/octave", "--eval", "run('scripts/run.m')"])
        self.assertEqual(record["env"], {"OCTAVE_HOME": "/opt/tools/envs/octave", "SEED": "1"})
        self.assertEqual(record["tools"], [{"name": "octave", "version": "10.3.0", "lock": "ab" * 32}])
        check(record, load_schema("job"))
        [arguments_only] = resources.add_jobs(self.project, {"tool": "octave", "command": ["--version"]}, ticket=1)
        self.assertEqual(arguments_only["command"], ["/opt/tools/envs/octave/bin/octave", "--version"])

    def test_the_specs_own_env_wins_over_the_tools_and_the_projects(self):
        record_entry(self.root, "julia", tool_entry("/opt/tools/julia-1.12.7/bin/julia", "1.12.7", "tarball",
                                                    env={"JULIA_DEPOT_PATH": "/opt/tools/julia/depot"}))
        [record] = resources.add_jobs(self.project, {"tool": "julia", "command": ["run.jl"], "env": {"JULIA_PROJECT": "/elsewhere"}},
                                      ticket=1)
        self.assertEqual(record["env"], {"JULIA_DEPOT_PATH": "/opt/tools/julia/depot", "JULIA_PROJECT": "/elsewhere"})

    def test_the_command_is_an_argv_that_names_the_tool_or_only_its_arguments(self):
        [absolute] = resources.add_jobs(self.project, {"tool": "octave", "command": ["/opt/tools/envs/octave/bin/octave", "--version"]},
                                        ticket=1)
        self.assertEqual(absolute["command"], ["/opt/tools/envs/octave/bin/octave", "--version"])
        record_entry(self.root, "r", tool_entry("/opt/tools/envs/r/bin/R", "4.4.3", "micromamba"))
        record_entry(self.root, "rscript", tool_entry("/opt/tools/envs/r/bin/Rscript", "4.4.3", "micromamba"))
        with self.assertRaises(resources.JobError) as caught:
            resources.add_jobs(self.project, {"tool": "r", "command": ["Rscript", "scripts/run.R"]}, ticket=1)
        self.assertIn("rscript", str(caught.exception))
        with self.assertRaises(resources.JobError):
            resources.add_jobs(self.project, {"tool": "octave", "command": "octave --eval 1"}, ticket=1)
        self.assertEqual(len(list((self.project / "research" / "jobs").glob("*.json"))), 1)

    def test_a_job_naming_a_tool_not_recorded_is_refused_and_nothing_is_written(self):
        with self.assertRaises(resources.JobError) as caught:
            resources.add_jobs(self.project, {"tool": "julia", "command": ["run.jl"]}, ticket=1)
        self.assertIn("julia", str(caught.exception))
        self.assertEqual(list((self.project / "research" / "jobs").glob("*.json")), [])

    def test_a_command_that_starts_with_a_recorded_executable_lists_its_tool(self):
        [record] = resources.add_jobs(self.project, {"command": ["/opt/tools/envs/octave/bin/octave", "--version"]}, ticket=1)
        self.assertEqual([tool["name"] for tool in record["tools"]], ["octave"])
        [plain] = resources.add_jobs(self.project, {"command": ["/usr/bin/python3", "scripts/run.py"]}, ticket=1)
        self.assertEqual(plain["tools"], [])

    def test_the_launch_journals_the_tools_the_job_calls(self):
        [record] = resources.add_jobs(self.project, {"tool": "octave", "command": ["--version"]}, ticket=1, backend="fake")
        fake = resources.FakeJobs()
        fake.script(["exited"])
        runner = resources.JobRunner(self.project, backend=fake)
        runner.launch(resources.spec_from_record(record))
        events, _ = self.ledger.read_events()
        launched = [event for event in events if event["event"] == "job_launched"]
        self.assertEqual(launched[-1]["payload"]["tools"], [{"name": "octave", "version": "10.3.0", "lock": "ab" * 32}])
        self.assertEqual(runner.read(record["id"])["tools"], record["tools"])

    def test_a_job_file_written_before_the_tools_field_still_validates(self):
        [record] = resources.add_jobs(self.project, {"command": ["/usr/bin/true"]}, ticket=1)
        record.pop("tools")
        check(record, load_schema("job"))


class TicketSoftwareTest(ProjectTestCase):
    """`ticket` and `plan` gain `software`: the graph carries it, and the plan check knows every name."""

    def setUp(self):
        super().setUp()
        self.project = self.temp / "toy"
        self.project.mkdir()
        project.init_project(self.project)
        self.ledger = Ledger(self.project)

    def test_a_ticket_names_its_tools_and_the_graph_carries_them(self):
        tickets.write_ticket(self.ledger, experiment_ticket(1, software=["octave", "r"]), "## Demo\n\nthe model runs\n")
        tickets.write_ticket(self.ledger, experiment_ticket(2), "## Demo\n\nthe model runs\n")
        [first, second] = tickets.read_tickets(self.project)
        self.assertEqual(first["software"], ["octave", "r"])
        graph, _ = tickets.refresh_graph(self.project)
        entries = {entry["id"]: entry for entry in graph["tickets"]}
        self.assertEqual(entries[1]["software"], ["octave", "r"])
        self.assertNotIn("software", entries[2], "a ticket that needs no tool keeps the graph entry it had")

    def test_the_plan_check_refuses_a_tool_the_harness_has_no_route_for(self):
        good = experiment_ticket(1, software=["octave", "matlab", "pandoc"])
        bad = experiment_ticket(2, software=["photoshop"])
        failures = plan.check_tickets([(good, ""), (bad, "")], [good, bad], self.project, base=False)
        self.assertEqual([failure for failure in failures if "tool" in failure],
                         ["ticket 2 needs the tool photoshop, which the harness has no route for and the owner records only as licensed "
                          "software; a ticket's software is one of %s" % ", ".join(software.known_tools())])

    def test_the_plan_schema_takes_software(self):
        schema = load_schema("plan")
        self.assertIn("software", schema["properties"]["tickets"]["items"]["properties"])
        self.assertIn("software", load_schema("ticket")["properties"])


class PlannedSoftwareTest(test_plan.PlanCase):
    def test_the_planner_sets_software_on_a_ticket(self):
        value = test_plan.cut()
        value["tickets"][0]["software"] = ["octave"]
        self.script(test_plan.planned(value))
        report = self.plan()
        self.assertIsNone(report["stopped"], report)
        self.assertEqual(self.ticket(1)["software"], ["octave"])
        self.assertNotIn("software", self.ticket(2))


class DryRunTest(ProjectTestCase):
    def setUp(self):
        super().setUp()
        self.root = self.temp / "tools"
        self.machine = ProjectMachine()

    def test_a_conda_forge_tool_states_its_download_from_micromamba_and_an_estimate_of_its_disk(self):
        recorded = json.loads((RECORDED / "micromamba-dry-run-octave.json").read_text(encoding="utf-8"))
        download = sum(item["size"] for item in recorded["actions"]["FETCH"])
        linked = sum(item["size"] for item in recorded["actions"]["LINK"])
        dry = software.dry_run("octave", root=self.root, run=self.machine)
        self.assertEqual((dry["route"], dry["download_bytes"], dry["packages"]), ("micromamba", download, len(recorded["actions"]["LINK"])))
        self.assertEqual(dry["disk_bytes"], linked * software.UNPACKED)
        self.assertTrue(dry["estimated"])
        self.assertFalse((self.root / "envs" / "octave").exists(), "a dry run installs nothing")

    def test_julia_states_the_size_its_server_publishes(self):
        dry = software.dry_run("julia", root=self.root, run=self.machine)
        self.assertEqual((dry["route"], dry["download_bytes"]), ("tarball", 289971949))
        self.assertEqual(dry["disk_bytes"], 289971949 * software.UNPACKED)

    def test_licensed_software_has_no_dry_run(self):
        dry = software.dry_run("matlab", root=self.root, run=self.machine)
        self.assertEqual((dry["route"], dry["download_bytes"], dry["disk_bytes"]), ("owner", None, None))


# --- the software decision, run by the conductor over a temporary project -----------------------------------------------


def code_ticket(identifier, name, **extra):
    """A one-file code ticket, in the shape of the one-ticket fixture's, that writes `<name>.txt`."""
    value = {"id": identifier, "title": "Write the %s file" % name, "kind": "code", "difficulty": 1, "status": "open", "blocked_by": [],
             "touches": ["%s.txt" % name], "role": "coder", "skills": [], "outputs": ["%s.txt" % name],
             "acceptance": {"machine": ["test -f %s.txt" % name], "quality": []}, "context_pack": ["research/INTAKE.md"],
             "origin": "research/INTAKE.md#the-intent", "proposed_by": "planner", "demo": "%s.txt exists on main" % name}
    value.update(extra)
    return value


def wrote(ticket_id, name):
    """The fake worker's done result and patch for a `code_ticket`."""
    envelope = test_conductor.done(ticket_id, outputs_written=["%s.txt" % name], summary="wrote %s.txt" % name)
    return envelope, test_conductor.patch({"%s.txt" % name: "%s\n" % name}, message="ticket %d: write %s.txt" % (ticket_id, name))


class SoftwareCase(test_conductor.ConductorCase):
    """The one-ticket fixture with tickets that need a project's tools, run wave by wave with the fake worker and the fake job runner.

    Ticket 1 needs no tool. Ticket 2 needs Octave, and ticket 3 Julia, unless a test says otherwise. Each dry-run job's log is
    what its verb prints on `ProjectMachine`, and each install job is played by the verb it runs, called in this process on
    the same recordings.
    """

    needs = {2: ["octave"], 3: ["julia"]}
    autonomy = "checkpoints"

    def setUp(self):
        super().setUp()
        if self.autonomy == "autonomous":
            open_objective(self.project)  # a raise to `autonomous` needs an open objective (ticket 76)
        project.set_autonomy(self.project, self.autonomy)
        names = {2: "octave", 3: "julia"}
        for identifier, tools in sorted(self.needs.items()):
            tickets.write_ticket(self.ledger, code_ticket(identifier, names.get(identifier, "t%d" % identifier), software=tools),
                                 "## Demo\n\nthe file exists\n")
        self.root = Path(os.environ["WAYLINE_HOME"]) / "tools"
        self.machine = ProjectMachine()
        self.fake = self.enterContext(worker.use_fake())
        self.jobs = self.enterContext(resources.use_fake_jobs())
        self.notified = []
        self.driven = self.conductor_for()

    def conductor_for(self):
        driven = Conductor(self.project, out=io.StringIO())
        driven.readings = test_machine.recorded
        driven.notify = lambda event, text, path, ticket: self.notified.append((event, ticket, text))
        driven.plan_pre_check = False
        return driven

    def wave(self, *scripted):
        for envelope, applied in scripted:
            ticket = envelope.structured_output["ticket_id"]
            self.fake.script(envelope, patch=applied, ticket=str(ticket))
        result = self.driven.wave()
        self.driven.settle()
        return result

    def said(self):
        return self.driven.out.getvalue()

    def launched(self):
        return [event["payload"]["ticket"] for event in self.events("ticket_launched")]

    def decision(self, name):
        found = [fields for fields in tickets.read_tickets(self.project) if fields.get("origin") == software.ask_origin(name)]
        self.assertEqual(len(found), 1, "one software decision about %s" % name)
        return found[0]

    def record(self, identifier):
        return decisions.decision_record(self.body_of(identifier))

    def body_of(self, identifier):
        fields = self.ticket(identifier)
        return tickets.read_ticket(tickets.tickets_dir(self.project) / tickets.filename(fields))[1]

    def dry_job(self, name):
        """The dry-run job of a tool: it belongs to the first ticket that waits on it."""
        waiting = min(identifier for identifier, tools in self.needs.items() if name in {software.provider(tool) for tool in tools})
        return "t%d-dryrun-%s-1" % (waiting, name)

    def script_dry_runs(self):
        """Each dry-run job's log: what `wayline tools install <name> --dry-run --json` prints, on the recordings."""
        names = sorted({software.provider(tool) for tools in self.needs.values() for tool in tools} - {None} - set(software.LICENSED))
        for name in names:
            dry = software.dry_run(name, root=self.temp / "dry-tools", run=self.machine)
            self.jobs.script(["exited"], log="micromamba: solving\n" + json.dumps(dry) + "\n", job_id=self.dry_job(name))

    def open_asks(self, *scripted):
        """Wave 1 launches ticket 1 and the dry-run jobs; wave 2 reads them and opens the asks."""
        self.script_dry_runs()
        self.wave(wrote(1, "hello"), *scripted)
        return self.wave()

    def play_install(self, identifier, name, attempt, machine=None, change=False):
        """What the install job does: `wayline tools install <name> --decision <id> --attempt <n>`, on the recordings."""
        options = argparse.Namespace(dry_run=False, project=str(self.project), decision=identifier, attempt=attempt, yes=False,
                                     change=change, at=None)
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return software.install_command(name, options, root=self.root, run=machine or self.machine, say=lambda line: None)


class SoftwareAskTest(SoftwareCase):
    def test_a_ticket_whose_tool_is_missing_is_not_launched_and_opens_one_decision_per_tool(self):
        self.script_dry_runs()
        result = self.wave(wrote(1, "hello"))
        self.assertFalse(result.ended, "the run goes on while the dry runs run")
        self.assertEqual([fields for fields in tickets.read_tickets(self.project) if software.asked(fields)], [],
                         "the dry run runs as a job, so no wave waits on it, and the ask opens once it ended")
        dry = json.loads((self.project / "research" / "jobs" / ("%s.json" % self.dry_job("octave"))).read_text(encoding="utf-8"))
        self.assertEqual((dry["ticket"], dry["command"][1:]), (2, ["tools", "install", "octave", "--dry-run", "--json"]))
        self.assertIn("ticket 2 waits: octave is not installed; its dry run runs as job %s" % self.dry_job("octave"), self.said())
        self.wave()
        self.assertEqual(self.launched(), [1], "only the ticket that needs no tool launches")
        octave, julia = self.decision("octave"), self.decision("julia")
        self.assertEqual((octave["kind"], octave["blocking"], octave["human_only"]), ("decision", "subgraph", False))
        self.assertIn(octave["id"], self.ticket(2)["blocked_by"])
        self.assertNotIn(octave["id"], self.ticket(3)["blocked_by"], "the octave ask pauses only the tickets that need octave")
        self.assertIn(julia["id"], self.ticket(3)["blocked_by"])
        self.assertNotIn(julia["id"], self.ticket(1)["blocked_by"])
        self.assertIn("ticket 2 needs octave: decision ticket %d asks whether to install it" % octave["id"], self.said())

    def test_the_ask_states_the_route_the_sizes_the_tickets_waiting_and_the_cost(self):
        self.open_asks()
        record = self.record(self.decision("octave")["id"])
        recorded = json.loads((RECORDED / "micromamba-dry-run-octave.json").read_text(encoding="utf-8"))
        download = sum(item["size"] for item in recorded["actions"]["FETCH"])
        self.assertEqual(record["question"], "Ticket 2 needs octave, which this machine does not have: install it?")
        self.assertEqual((record["options"], record["recommended"]), (["Install", "Not now", "Go without"], "Install"))
        evidence = "\n".join(record["evidence"])
        self.assertIn("route: conda-forge through the harness's micromamba (octave) into ~/.wayline/tools/envs/octave", evidence)
        self.assertIn("sizes from a dry run: %d MB to download" % round(download / 1e6), evidence)
        self.assertIn("waiting: ticket 2, and only it", evidence)
        self.assertIn("cost: no money (free software)", evidence)
        self.assertIn("route: Julia %s's release tarball" % software.JULIA_VERSION, "\n".join(self.record(self.decision("julia")["id"])["evidence"]))

    def test_each_ask_is_an_item_of_a_software_ask_batch(self):
        self.open_asks()
        found = {batch["decision"]: batch for batch in batches.read_batches(self.project)}
        octave = self.decision("octave")["id"]
        self.assertEqual(found[octave]["kind"], "software_ask")
        [item] = found[octave]["items"]
        self.assertEqual((item["ref"], item["marks"], item["default"]), ("software octave", ["approve", "decline"], "approve"))

    def test_a_second_wave_and_a_restarted_conductor_ask_nothing_twice(self):
        self.open_asks()
        before = (len(tickets.read_tickets(self.project)), len(batches.read_batches(self.project)), len(self.events("decision_opened")))
        self.wave()
        self.driven = self.conductor_for()
        self.wave()
        after = (len(tickets.read_tickets(self.project)), len(batches.read_batches(self.project)), len(self.events("decision_opened")))
        self.assertEqual(before, after)
        dry_runs = sorted(path.name for path in (self.project / "research" / "jobs").glob("*-dryrun-*.json"))
        self.assertEqual(dry_runs, [self.dry_job("octave") + ".json", self.dry_job("julia") + ".json"], "each dry run runs once")

    def test_the_run_ends_when_only_tickets_waiting_on_an_unanswered_ask_are_left(self):
        results = [self.open_asks()]
        for _ in range(4):
            if results[-1].ended:
                break
            results.append(self.wave())
        self.assertTrue(results[-1].ended)
        self.assertEqual(results[-1].reason, "frontier_empty")


class AnsweredInstallTest(SoftwareCase):
    needs = {2: ["octave"]}

    def setUp(self):
        super().setUp()
        self.open_asks()
        self.ask = self.decision("octave")["id"]

    def jobs_written(self):
        return sorted(path.name for path in (self.project / "research" / "jobs").glob("*-install-*.json"))

    def job(self, attempt):
        return "t%d-install-octave-%d" % (self.ask, attempt)

    def test_install_runs_as_a_job_and_the_ticket_launches_once_the_tool_is_recorded(self):
        project.answer(self.project, self.ask, "Install")
        self.jobs.script(["running", "exited"], job_id=self.job(1))
        result = self.wave()
        self.assertFalse(result.ended, "the run goes on while the install job runs")
        record = json.loads((self.project / "research" / "jobs" / ("%s.json" % self.job(1))).read_text(encoding="utf-8"))
        self.assertEqual(record["ticket"], self.ask)
        self.assertEqual(record["command"][1:], ["tools", "install", "octave", "--project", str(self.project), "--decision", str(self.ask),
                                                 "--attempt", "1"])
        self.assertTrue(record["command"][0].endswith("/bin/wayline"))
        self.assertEqual(self.launched(), [1])
        self.assertIn("ticket 2 waits: octave is being installed (decision ticket %d)" % self.ask, self.said())
        self.assertEqual(self.play_install(self.ask, "octave", 1), 0)
        self.wave(wrote(2, "octave"))  # octave is recorded, so ticket 2 launches, whatever the job's own poll reads yet
        self.assertEqual(self.launched(), [1, 2])
        self.wave()
        self.assertEqual([event["payload"]["exit_code"] for event in self.events("job_finished") if event["job"] == self.job(1)], [0])
        installed = self.events("tool_installed")
        self.assertEqual([(event["payload"]["outcome"], event["payload"]["attempt"], event["ticket"]) for event in installed],
                         [("installed", 1, self.ask)])
        self.assertEqual(Tools(self.root).entry("octave")["installer"], "harness")

    def test_a_failed_install_is_retried_once_then_the_decision_is_asked_again_with_the_error(self):
        project.answer(self.project, self.ask, "Install")
        failing = ProjectMachine(fail=lambda argv: Path(argv[0]).name == "micromamba" and "create" in argv and "--dry-run" not in argv)
        self.jobs.script(["exited"], job_id=self.job(1))
        self.wave()
        self.assertEqual(self.play_install(self.ask, "octave", 1, machine=failing), 1)
        self.jobs.script(["exited"], job_id=self.job(2))
        self.wave()  # attempt 1 ended without octave: attempt 2 is launched
        self.assertTrue((self.project / "research" / "jobs" / ("%s.json" % self.job(2))).is_file())
        self.assertEqual(self.play_install(self.ask, "octave", 2, machine=failing), 1)
        self.notified.clear()
        self.wave()  # attempt 2 ended without octave: the decision is asked again, carrying the error
        fields = self.ticket(self.ask)
        self.assertEqual(fields["status"], "open")
        evidence = "\n".join(self.record(self.ask)["evidence"])
        self.assertIn("asked again: installing octave failed 2 times; the last: micromamba create octave failed (exit 1: error: the recorded failure)",
                      evidence)
        self.assertNotIn("## Answer\n", self.body_of(self.ask))
        self.assertEqual([event["payload"]["by"] for event in self.events("ticket_rerun") if event["ticket"] == self.ask], ["code"])
        self.assertTrue(any(event == "decision_opened" and ticket == self.ask for event, ticket, _ in self.notified))
        self.assertEqual(len([batch for batch in batches.read_batches(self.project, status="open") if batch["decision"] == self.ask]), 1)
        self.assertEqual(self.launched(), [1])
        before = (len(self.events()), sorted(path.name for path in (self.project / "research" / "jobs").glob("*.json")))
        self.wave()
        self.driven = self.conductor_for()
        self.wave()
        self.assertEqual(sorted(path.name for path in (self.project / "research" / "jobs").glob("*.json")), before[1],
                         "an ask asked again launches nothing until it is answered again")
        self.assertEqual([event for event in self.events("ticket_rerun") if event["ticket"] == self.ask][1:], [])

    def test_not_now_leaves_the_ticket_waiting_and_go_without_lets_it_launch(self):
        project.answer(self.project, self.ask, "Not now")
        result = self.wave()
        self.assertEqual(self.jobs_written(), [])
        self.assertEqual(self.launched(), [1])
        self.assertIn("decision ticket %d was answered Not now" % self.ask, self.said())
        self.assertTrue(result.ended, "a ticket waiting on Not now keeps no run going")
        self.driven = self.conductor_for()
        self.ledger.append_event("ticket_rerun", {"ticket": self.ask, "by": "cli"}, ticket=self.ask)
        fields, body = tickets.read_ticket(tickets.tickets_dir(self.project) / tickets.filename(self.ticket(self.ask)))
        tickets.write_ticket(self.ledger, dict(fields, status="open"), tickets.retire_answer(body))
        project.answer(self.project, self.ask, "Go without")
        self.wave(wrote(2, "octave"))
        self.assertEqual(self.launched(), [1, 2])

    def test_a_mark_in_the_marks_view_settles_the_ask(self):
        [batch] = [batch for batch in batches.read_batches(self.project) if batch["decision"] == self.ask]
        batches.mark(self.project, batch["id"], 1, "approve")
        self.jobs.script(["running"], job_id=self.job(1))
        self.wave()
        [answer] = [event["payload"] for event in self.events("decision") if event["ticket"] == self.ask]
        self.assertEqual((answer["answer"], answer["decided_by"]), ("Install", "human"))
        self.assertIn("mark", answer["rationale"])
        self.assertTrue(batches.read_batch(self.project, batch["id"])["items"][0]["acted"], "the decision answered is final")
        self.wave()
        self.assertTrue((self.project / "research" / "jobs" / ("%s.json" % self.job(1))).is_file())

    def test_an_answer_settles_the_open_item_and_the_first_answer_wins(self):
        [batch] = [batch for batch in batches.read_batches(self.project) if batch["decision"] == self.ask]
        batches.mark(self.project, batch["id"], 1, "decline")
        project.answer(self.project, self.ask, "Install")  # given after the mark, before any wave read it
        self.wave()
        self.wave()
        self.assertEqual(self.jobs_written(), [], "the mark came first: Not now")
        [batch] = [batch for batch in batches.read_batches(self.project) if batch["decision"] == self.ask]
        self.assertEqual(batch["items"][0]["mark"], "decline")
        self.assertTrue(batch["items"][0]["acted"], "the decision is answered: the mark does no more, so no click changes it")
        self.assertEqual(self.launched(), [1])

    def test_an_earlier_mark_is_the_answer_the_install_job_reads_too(self):
        [batch] = [batch for batch in batches.read_batches(self.project) if batch["decision"] == self.ask]
        batches.mark(self.project, batch["id"], 1, "approve")
        project.answer(self.project, self.ask, "Not now")  # given after the mark, before any wave read it
        self.jobs.script(["running"], job_id=self.job(1))
        self.wave()
        self.assertEqual(self.jobs_written(), [self.job(1) + ".json"], "the mark came first: Install")
        self.assertEqual(self.play_install(self.ask, "octave", 1), 0, "the install job reads the same answer")

    def test_a_launch_the_job_runner_refuses_is_said_and_fails_no_wave(self):
        project.answer(self.project, self.ask, "Install")  # nothing is scripted for the install job, so the fake refuses it
        self.wave()  # the refusal is said, and the wave goes on to its end
        self.assertIn("decision ticket %d: the install job %s could not be launched" % (self.ask, self.job(1)), self.said())
        self.assertEqual(self.launched(), [1])

    def test_an_answer_given_first_settles_the_item(self):
        project.answer(self.project, self.ask, "Go without")
        self.wave(wrote(2, "octave"))
        [batch] = [batch for batch in batches.read_batches(self.project) if batch["decision"] == self.ask]
        item = batch["items"][0]
        self.assertEqual((item["mark"], item["note"], item["by"], batch["status"]), ("decline", "Go without", "owner", "closed"))


class AutonomyTest(unittest.TestCase):
    """Who answers a `software` decision, under each autonomy, read from the decisions view of a replayed journal."""

    def test_the_owner_answers_under_interactive_and_checkpoints_and_the_decider_under_autonomous(self):
        free = {"id": 7, "kind": "decision", "human_only": False}
        licensed_or_gap = {"id": 8, "kind": "decision", "human_only": True}
        for autonomy, who in (("interactive", True), ("checkpoints", True), ("autonomous", False)):
            with self.subTest(autonomy=autonomy):
                self.assertEqual(schedule.awaits_owner(free, autonomy, decider=True), who)
                self.assertTrue(schedule.awaits_owner(licensed_or_gap, autonomy, decider=True))


class AutonomousSoftwareTest(SoftwareCase):
    needs = {2: ["octave"], 3: ["matlab"]}
    autonomy = "autonomous"

    def test_the_decider_takes_a_free_tool_and_never_licensed_software(self):
        self.open_asks()
        octave, matlab = self.decision("octave"), self.decision("matlab")
        self.assertFalse(octave["human_only"])
        self.assertTrue(matlab["human_only"], "licensed software is the owner's alone")
        view = decisions.decisions_view(self.project)
        awaits = {entry["id"]: entry["awaits"] for entry in view["open"]}
        self.assertEqual((awaits[octave["id"]], awaits[matlab["id"]]), ("decider", "owner"))
        with self.assertRaises(project.ProjectError):
            decisions.decide(self.project, matlab["id"], "/opt/matlab/bin/matlab", "the decider would record it")
        decisions.decide(self.project, octave["id"], "Install", "free software through conda-forge")
        self.jobs.script(["running"], job_id="t%d-install-octave-1" % octave["id"])
        self.wave()
        self.wave()
        self.assertTrue((self.project / "research" / "jobs" / ("t%d-install-octave-1.json" % octave["id"])).is_file())

    def test_a_project_that_holds_the_class_software_human_only_keeps_every_ask_for_the_owner(self):
        path = self.project / "harness.json"
        harness = json.loads(path.read_text(encoding="utf-8"))
        harness["human_only"] = ["goal", "data", software.SOFTWARE]
        path.write_text(json.dumps(harness, indent=2) + "\n", encoding="utf-8")
        self.open_asks()
        self.assertTrue(self.decision("octave")["human_only"])

    def test_the_setup_question_lists_every_tool_the_planned_work_needs(self):
        asked_once = software.setup_question(self.project, tools=Tools(self.root), run=self.machine)
        self.assertEqual([tool["name"] for tool in asked_once["tools"]], ["matlab", "octave"])
        self.assertIn("- octave through micromamba", asked_once["question"])
        self.assertIn("- matlab (licensed: you install it and say where; ticket 3)", asked_once["question"])
        software.install_project_tool("octave", root=self.root, run=self.machine)
        self.assertEqual([tool["name"] for tool in software.setup_question(self.project, tools=Tools(self.root), run=self.machine)["tools"]],
                         ["matlab"])

    def test_the_setup_question_is_the_tools_needs_verb(self):
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            code = software.needs_command(["--project", str(self.project), "--json"], root=self.root, run=self.machine)
        self.assertEqual(code, 0)
        self.assertEqual([tool["name"] for tool in json.loads(out.getvalue())["tools"]], ["matlab", "octave"])


class LicensedAskTest(SoftwareCase):
    needs = {2: ["matlab"]}

    def setUp(self):
        super().setUp()
        self.wave(wrote(1, "hello"))
        self.ask = self.decision("matlab")["id"]
        self.matlab = self.temp / "MATLAB" / "bin" / "matlab"
        self.matlab.parent.mkdir(parents=True)
        self.matlab.write_text("#!/bin/sh\n", encoding="utf-8")

    def test_the_ask_asks_where_it_is_and_a_passing_check_job_records_it(self):
        record = self.record(self.ask)
        self.assertEqual(record["question"], "Ticket 2 needs matlab, licensed software this machine does not have recorded: where did you install it?")
        self.assertEqual(record["options"][1:], ["Not now", "Go without"])
        self.assertTrue(self.ticket(self.ask)["human_only"])
        project.answer(self.project, self.ask, "It is at %s" % self.matlab)
        job = "t%d-check-matlab-1" % self.ask
        self.jobs.script(["running", "exited"], log=(WRITTEN / "matlab-batch-ver.txt").read_text(encoding="utf-8"), job_id=job)
        self.wave()
        launched = json.loads((self.project / "research" / "jobs" / ("%s.json" % job)).read_text(encoding="utf-8"))
        self.assertEqual(launched["command"], [str(self.matlab), "-batch", "ver"])
        self.wave()
        self.wave(wrote(2, "matlab"))
        entry = Tools(self.root).entry("matlab")
        self.assertEqual((entry["installer"], entry["version"], entry["executable"]), ("owner", "24.2.0.2712019", str(self.matlab)))
        self.assertIn("Signal Processing Toolbox", entry["toolboxes"])
        self.assertEqual([event["payload"]["outcome"] for event in self.events("tool_installed")], ["recorded"])
        self.assertEqual(self.launched(), [1, 2])

    def test_a_failing_check_keeps_the_decision_open(self):
        project.answer(self.project, self.ask, str(self.matlab))
        job = "t%d-check-matlab-1" % self.ask
        self.jobs.script(["running", resources.JobState("failed", result="exit-code", exit_code=1, reason="exited 1")],
                         log="License checkout failed.\nLicense Manager Error -9\n", job_id=job)
        self.wave()
        self.wave()
        self.wave()
        self.assertEqual(self.ticket(self.ask)["status"], "open")
        self.assertIn("License Manager Error -9", "\n".join(self.record(self.ask)["evidence"]))
        self.assertIsNone(Tools(self.root).entry("matlab"))
        self.assertEqual([event["payload"]["outcome"] for event in self.events("tool_installed")], ["failed"])
        self.assertEqual(self.launched(), [1])

    def test_an_answer_naming_no_path_asks_again(self):
        project.answer(self.project, self.ask, "Install")
        self.wave()
        self.assertEqual(self.ticket(self.ask)["status"], "open")
        self.assertIn("names no absolute path", "\n".join(self.record(self.ask)["evidence"]))

    def test_the_asks_own_first_option_asks_again_for_the_path(self):
        project.answer(self.project, self.ask, software.WHERE % "matlab")
        self.wave()
        self.assertEqual(self.ticket(self.ask)["status"], "open")
        self.assertIn("names no absolute path", "\n".join(self.record(self.ask)["evidence"]))


class GapTest(SoftwareCase):
    needs = {2: ["octave"]}

    def setUp(self):
        super().setUp()
        software.install_project_tool("octave", root=self.root, run=self.machine)
        envelope, applied = wrote(2, "octave")
        envelope.structured_output.update(status="blocked", blocked_on="software octave: it lacks the signal package's fir1")
        self.wave(wrote(1, "hello"), (envelope, applied))
        self.driven.settle()
        self.wave()
        found = [fields for fields in tickets.read_tickets(self.project) if (software.asked(fields) or (None, False))[1]]
        self.assertEqual(len(found), 1)
        self.gap = found[0]

    def test_a_gap_ends_the_worker_blocked_and_code_opens_the_owners_decision(self):
        self.assertEqual(self.ticket(2)["status"], "blocked")
        [blocked] = self.events("ticket_blocked")
        self.assertEqual(blocked["payload"]["path"], "software octave: it lacks the signal package's fir1")
        self.assertTrue(self.gap["human_only"], "changing an installed tool is the owner's word")
        self.assertIn(self.gap["id"], self.ticket(2)["blocked_by"])
        self.assertIn("lacks what its code needs (it lacks the signal package's fir1)", self.record(self.gap["id"])["question"])
        with self.assertRaises(project.ProjectError):
            decisions.decide(self.project, self.gap["id"], "Install", "the decider would change it")

    def test_go_without_opens_the_blocked_ticket_again(self):
        project.answer(self.project, self.gap["id"], "Go without")
        self.wave(wrote(2, "octave"))  # opened again, and launched in the same wave
        self.assertIn("ticket 2 is open again: decision ticket %d answered its gap in octave" % self.gap["id"], self.said())
        self.assertEqual(self.launched().count(2), 2)
        self.wave()
        self.assertEqual(self.ticket(2)["status"], "done")

    def test_install_changes_the_installed_tool_on_the_owners_word_and_opens_the_ticket_again(self):
        project.answer(self.project, self.gap["id"], "Install")
        job = "t%d-install-octave-1" % self.gap["id"]
        self.jobs.script(["exited"], job_id=job)
        self.wave()
        command = json.loads((self.project / "research" / "jobs" / ("%s.json" % job)).read_text(encoding="utf-8"))["command"]
        self.assertEqual(command[-1], "--change")
        self.assertEqual(self.ticket(2)["status"], "blocked", "the ticket waits while the tool is changed")
        self.assertEqual(self.play_install(self.gap["id"], "octave", 1, change=True), 0)
        self.assertEqual(len([argv for argv, _ in self.machine.ran("micromamba") if argv[1] == "update"]), 1)
        self.wave(wrote(2, "octave"))
        self.assertEqual(self.launched().count(2), 2)

    def test_go_without_opens_the_ticket_once_and_only_from_that_gap(self):
        project.answer(self.project, self.gap["id"], "Go without")
        envelope, applied = wrote(2, "octave")
        envelope.structured_output.update(status="blocked", blocked_on="software octave: it lacks the signal package's fir1")
        self.wave((envelope, applied))  # opened again, launched, and blocked on the same gap again
        self.wave()
        self.wave()
        self.assertEqual(self.ticket(2)["status"], "blocked", "the same gap after Go without is not opened again by itself")
        self.assertEqual(self.launched().count(2), 2)
        self.assertEqual(len([event for event in self.events("ticket_rerun") if event["ticket"] == 2]), 1)

    def test_a_ticket_blocked_for_another_reason_is_left_to_the_planner(self):
        envelope, applied = wrote(2, "octave")
        envelope.structured_output.update(status="blocked", blocked_on="software octave: it lacks the signal package's fir1")
        project.answer(self.project, self.gap["id"], "Go without")
        outside, applied = wrote(2, "octave")
        outside.structured_output.update(touched_outside_declared=["elsewhere.txt"])
        self.wave((outside, applied))  # opened from the gap, launched, and blocked on its touch set
        self.wave()
        self.assertEqual(self.ticket(2)["status"], "blocked")
        self.assertEqual(self.launched().count(2), 2, "a touch-set block is the planner's to re-cut, not the gap's to open")


class LicensedGapTest(SoftwareCase):
    needs = {2: ["matlab"]}

    def test_a_gap_in_licensed_software_is_answered_with_where_the_owner_changed_it(self):
        matlab = self.temp / "MATLAB" / "bin" / "matlab"
        matlab.parent.mkdir(parents=True)
        matlab.write_text("#!/bin/sh\n", encoding="utf-8")
        software.record_licensed("matlab", matlab, root=self.root, run=self.machine)
        envelope, applied = wrote(2, "matlab")
        envelope.structured_output.update(status="blocked", blocked_on="software matlab: it lacks the Wavelet Toolbox")
        self.wave(wrote(1, "hello"), (envelope, applied))
        self.wave()
        [gap] = [fields for fields in tickets.read_tickets(self.project) if (software.asked(fields) or (None, False))[1]]
        self.assertEqual(self.record(gap["id"])["options"][0], software.WHERE % "matlab")
        project.answer(self.project, gap["id"], "Added the toolbox; it is still at %s" % matlab)
        job = "t%d-check-matlab-1" % gap["id"]
        self.jobs.script(["exited"], log=(WRITTEN / "matlab-batch-ver.txt").read_text(encoding="utf-8"), job_id=job)
        self.wave()
        self.assertTrue((self.project / "research" / "jobs" / ("%s.json" % job)).is_file(), "a licensed gap is checked, not installed")
        self.wave(wrote(2, "matlab"))
        self.assertEqual([event["payload"]["outcome"] for event in self.events("tool_installed")], ["recorded"])
        self.assertEqual(self.launched().count(2), 2)


class NoRouteTest(SoftwareCase):
    """A name with no project route (a harness tool) opens no ask, and `rscript` is asked about as R, which installs it."""

    needs = {2: ["git"], 3: ["rscript"]}

    def test_a_harness_tool_opens_no_ask_and_rscript_asks_about_r(self):
        self.open_asks()
        origins = sorted(fields["origin"] for fields in tickets.read_tickets(self.project) if software.asked(fields))
        self.assertEqual(origins, ["software r"])
        self.assertIn(self.decision("r")["id"], self.ticket(3)["blocked_by"])
        self.assertIn("ticket 2 waits: git is a harness tool that tools.json does not record", self.said())
        self.assertEqual(self.launched(), [1])

    def test_a_gap_in_a_harness_tool_opens_no_ask(self):
        envelope, applied = wrote(1, "hello")
        envelope.structured_output.update(status="blocked", blocked_on="software git: it lacks git-lfs")
        self.script_dry_runs()
        self.wave((envelope, applied))
        self.wave()
        self.assertEqual(self.ticket(1)["status"], "blocked")
        self.assertIn("ticket 1 is blocked on software git: it lacks git-lfs; the planner re-cuts it", self.said())
        self.assertEqual([fields for fields in tickets.read_tickets(self.project) if (software.asked(fields) or (None, False))[1]], [])


class QuietSettleTest(ProjectTestCase):
    def test_a_project_where_nothing_names_software_reads_no_journal(self):
        toy = self.temp / "toy"
        toy.mkdir()
        project.init_project(toy)
        with mock.patch.object(Ledger, "read_events", side_effect=AssertionError("the journal was read")):
            settled = software.settle(toy, lambda: self.fail("no job runner is made"), tools=Tools(self.temp / "tools"))
        self.assertEqual((settled.in_flight, settled.waiting, settled.waived), ([], {}, set()))


class InstallVerbTest(SoftwareCase):
    needs = {2: ["octave"]}

    def options(self, **values):
        base = {"dry_run": False, "project": str(self.project), "decision": None, "attempt": None, "yes": False, "change": False, "at": None}
        base.update(values)
        return argparse.Namespace(**base)

    def run_verb(self, name, **values):
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            code = software.install_command(name, self.options(**values), root=self.root, run=self.machine, say=lambda line: None)
        return code, err.getvalue()

    def test_a_projects_tool_installs_only_after_a_yes(self):
        code, err = self.run_verb("octave")
        self.assertEqual(code, 2)
        self.assertIn("only after a yes", err)
        self.assertIsNone(Tools(self.root).entry("octave"))
        self.open_asks()
        ask = self.decision("octave")["id"]
        code, err = self.run_verb("octave", decision=ask)
        self.assertEqual(code, 1)
        self.assertIn("is not answered Install", err)
        project.answer(self.project, ask, "Not now")
        self.assertEqual(self.run_verb("octave", decision=ask)[0], 1)
        self.assertEqual(self.run_verb("octave", yes=True)[0], 0, "the owner's yes in the setup conversation")
        self.assertEqual(Tools(self.root).entry("octave")["version"], "10.3.0")

    def test_a_change_needs_the_owners_word(self):
        self.open_asks()
        ask = self.decision("octave")["id"]
        decisions.decide(self.project, ask, "Install", "free software through conda-forge")
        self.assertEqual(self.run_verb("octave", decision=ask)[0], 0, "the decider's Install installs a free tool")
        code, err = self.run_verb("octave", decision=ask, change=True)
        self.assertEqual(code, 1)
        self.assertIn("not to change it", err)
        self.assertEqual([argv for argv, _ in self.machine.ran("micromamba") if argv[1] == "update"], [])
        self.assertEqual(self.run_verb("octave", yes=True, change=True)[0], 0, "the owner's word in the conversation")
        self.assertEqual(len([argv for argv, _ in self.machine.ran("micromamba") if argv[1] == "update"]), 1)

    def test_the_cli_records_licensed_software_only_where_the_owner_says(self):
        matlab = self.temp / "opt" / "matlab"
        matlab.parent.mkdir(parents=True)
        matlab.write_text("#!/bin/sh\n", encoding="utf-8")
        code, err = self.run_verb("matlab")
        self.assertEqual(code, 2)
        self.assertIn("licensed software", err)
        self.assertEqual(self.run_verb("matlab", at=str(matlab))[0], 0)
        self.assertEqual(Tools(self.root).entry("matlab")["installer"], "owner")
        self.assertEqual([event["payload"]["outcome"] for event in self.events("tool_installed")], ["recorded"])

    def test_the_package_verb_installs_with_no_ask(self):
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            code = software.package_command(["python", "six==1.17.0", "--project", str(self.project)], root=self.root, run=self.machine)
        self.assertEqual(code, 0)
        self.assertIn("requirements.lock", out.getvalue())
        self.assertTrue((self.project / "code" / "requirements.lock").is_file())


class IrreversibleListTest(unittest.TestCase):
    def test_installing_free_software_is_neither_irreversible_nor_a_global_harness_change(self):
        for answer in ("Install", "Install octave through micromamba from conda-forge into ~/.wayline/tools/envs/octave",
                       "Not now", "Go without"):
            with self.subTest(answer=answer):
                self.assertIsNone(decider.irreversible_class(answer, "Ticket 2 needs octave, which this machine does not have: install it?"))


if __name__ == "__main__":
    unittest.main()
