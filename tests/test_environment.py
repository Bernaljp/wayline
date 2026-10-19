"""Moving a project's environment (ticket 83): `wayline switch --environment shared|conda|venv|container`.

Every build runs against `EnvironmentMachine`, the tool runner's recordings (seam 6) that ticket 82's
`ProjectMachine` keeps for a project's tools, extended to the environments: what uv answers for a
venv, what micromamba answers for a prefix built from an explicit lock, and what SingularityCE 3.8.1
printed on the owner's workstation on 2026-10-19 for a rootless sandbox build from `docker://`, the
SIF built from it, and its version (`fixtures/tools/recorded/singularity-*.txt`), with Docker refusing
the account (`docker-info-refused.txt`). Nothing is downloaded and nothing is built: each test works
in a temporary project and a temporary tools home.
"""

import io
import json
import os
import shutil
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from tests.paths import FIXTURES_DIR
from tests.projects import ProjectTestCase
from tests.test_software import RECORDED, WRITTEN, ProjectMachine, experiment_ticket
from wayline import environment, project, replay, resources, software
from wayline import tools as toolbox
from wayline.jsonschema import ValidationError, check, load_schema
from wayline.ledger import Ledger
from wayline.tools import ToolOutput, Tools, record_entry, tool_entry

LOCK = b"# uv pip freeze of <project>/.venv (wayline tools package python)\nsix==1.17.0\n"


class EnvironmentMachine(ProjectMachine):
    """Ticket 82's recordings, and what uv, micromamba, Python, Docker, and Singularity answer for an environment's build."""

    def __init__(self, fail=None, versions=None, docker=False, python="3.12.3", freeze=None):
        super().__init__(fail=fail)
        self.docker = docker
        self.python = python
        self.freeze = freeze
        self.tool_versions = dict(versions or {})

    def __call__(self, argv, cwd=None, timeout=None, env=None):
        argv = [str(part) for part in argv]
        name = Path(argv[0]).name
        if name == "singularity" and argv[1] == "exec" and not self.fail(argv):
            self.calls.append((argv, dict(env or {})))
            return self.inside(argv, env)
        if self.fail(argv):
            self.calls.append((argv, dict(env or {})))
            return ToolOutput(1, b"", b"error: the recorded failure")
        if name == "docker" and argv[1] == "info":
            self.calls.append((argv, dict(env or {})))
            if self.docker:
                return ToolOutput(0, b"27.3.1\n", b"")
            return ToolOutput(1, b"", (RECORDED / "docker-info-refused.txt").read_bytes())
        if name == "docker" and argv[1] == "pull":
            self.calls.append((argv, dict(env or {})))
            return ToolOutput(0, b"", b"")
        if name == "singularity" and argv[1:] == ["--version"]:
            self.calls.append((argv, dict(env or {})))
            return ToolOutput(0, (RECORDED / "singularity--version.txt").read_bytes(), b"")
        if name == "singularity" and argv[1:3] == ["build", "--sandbox"]:
            self.calls.append((argv, dict(env or {})))
            sandbox = Path(argv[3])
            for folder in ("usr/local/bin", "etc/ssl/certs", "opt", "tmp"):
                (sandbox / folder).mkdir(parents=True, exist_ok=True)
            return ToolOutput(0, b"", (RECORDED / "singularity-build-sandbox.txt").read_bytes())
        if name == "singularity" and argv[1] == "build":
            self.calls.append((argv, dict(env or {})))
            Path(argv[2]).write_bytes(b"SIF image of " + argv[3].encode())
            return ToolOutput(0, b"", (RECORDED / "singularity-build-sif.txt").read_bytes())
        if name == "uv" and argv[1:3] == ["pip", "sync"]:
            self.calls.append((argv, dict(env or {})))
            return ToolOutput(0, b"", b"")
        if name == "uv" and argv[1:3] == ["pip", "freeze"] and ".venv" not in argv[-1]:
            self.calls.append((argv, dict(env or {})))
            return ToolOutput(0, self.freeze if self.freeze is not None else b"six==1.17.0\n", b"")
        if name == "python" and argv[1:] == ["--version"]:
            self.calls.append((argv, dict(env or {})))
            return ToolOutput(0, ("Python %s\n" % self.python).encode(), b"")
        if argv[1:] == ["--version"] and name in self.tool_versions:
            self.calls.append((argv, dict(env or {})))
            return ToolOutput(0, self.tool_versions[name].encode(), b"")
        if name == "micromamba" and "--file" in argv:
            self.calls.append((argv, dict(env or {})))
            prefix = Path(argv[argv.index("-p") + 1])
            (prefix / "bin").mkdir(parents=True, exist_ok=True)
            (prefix / "conda-meta").mkdir(exist_ok=True)
            for program in ("octave", "R", "Rscript"):
                (prefix / "bin" / program).write_text("#!/bin/sh\n", encoding="utf-8")
            return ToolOutput(0, b"", b"")
        if name == "micromamba" and any(part.startswith("python=") for part in argv):
            self.calls.append((argv, dict(env or {})))
            prefix = Path(argv[argv.index("-p") + 1])
            (prefix / "bin").mkdir(parents=True, exist_ok=True)
            (prefix / "bin" / "python").write_text("#!/bin/sh\n", encoding="utf-8")
            return ToolOutput(0, b"", b"")
        return super().__call__(argv, cwd=cwd, timeout=timeout, env=env)

    def inside(self, argv, env):
        """A command inside the sandbox or the image: the sandbox's files change as the command would change them."""
        image = next(part for part in argv[2:] if not part.startswith("-") and argv[argv.index(part) - 1] not in ("--bind", "--env", "--pwd"))
        inner = argv[argv.index(image) + 1:]
        program = Path(inner[0]).name
        if program == "micromamba":
            prefix = inner[inner.index("-p") + 1]
            target = Path(image) / prefix.lstrip("/")
            (target / "bin").mkdir(parents=True, exist_ok=True)
            (target / "conda-meta").mkdir(exist_ok=True)
            for made in ("octave", "R", "Rscript", "python"):
                (target / "bin" / made).write_text("#!/bin/sh\n", encoding="utf-8")
            return ToolOutput(0, b"", b"")
        if program == "python" and inner[1:] == ["--version"]:
            return ToolOutput(0, ("Python %s\n" % self.python).encode(), b"")
        if program == "uv" and inner[1:3] == ["pip", "freeze"]:
            return ToolOutput(0, self.freeze if self.freeze is not None else b"six==1.17.0\n", b"")
        if program == "uv":
            return ToolOutput(0, b"", b"")
        if inner[1:] == ["--version"] and program in self.tool_versions:
            return ToolOutput(0, self.tool_versions[program].encode(), b"")
        if inner[1:] == ["--version"] and program in ("octave", "julia"):
            return ToolOutput(0, (WRITTEN / ("%s--version.txt" % program)).read_bytes(), b"")
        if inner[1:] == ["--version"] and program in ("R", "Rscript"):
            return ToolOutput(0, (RECORDED / ("%s--version.txt" % program)).read_bytes(), b"")
        if program == "octave" and "--eval" in inner and "'list'" in inner[-1]:
            return ToolOutput(0, self.octave_list, b"")
        if program == "matlab" and inner[1:] == ["-batch", "ver"]:
            return ToolOutput(0, (WRITTEN / "matlab-batch-ver.txt").read_bytes(), b"")
        return ToolOutput(0, b"", b"")

    def inner(self, program):
        """The commands run inside the sandbox or the image whose program is `program`."""
        found = []
        for argv, _ in self.ran("singularity"):
            if argv[1] != "exec":
                continue
            image = next(part for part in argv[2:] if not part.startswith("-") and argv[argv.index(part) - 1] not in ("--bind", "--env", "--pwd"))
            inner = argv[argv.index(image) + 1:]
            if Path(inner[0]).name == program:
                found.append(inner)
        return found


class EnvironmentTestCase(ProjectTestCase):
    """A temporary project with a Python lock and its venv, and a temporary tools home with uv and micromamba."""

    def setUp(self):
        super().setUp()
        self.project = self.temp / "proj"
        self.project.mkdir()
        project.init_project(self.project)
        self.root = toolbox.tools_home()
        self.root.mkdir(parents=True, exist_ok=True)
        for name in ("uv", "micromamba"):
            executable = self.root / "bin" / name
            executable.parent.mkdir(parents=True, exist_ok=True)
            executable.write_text("#!/bin/sh\n", encoding="utf-8")
            record_entry(self.root, name, tool_entry(executable, "1", "release",
                                                     env=toolbox.uv_env(self.root) if name == "uv" else toolbox.mamba_env(self.root)))
        (self.project / "code").mkdir(exist_ok=True)
        (self.project / "code" / "requirements.lock").write_bytes(LOCK)
        venv = self.project / ".venv"
        (venv / "bin").mkdir(parents=True)
        (venv / "bin" / "python").write_text("#!/bin/sh\n", encoding="utf-8")
        (venv / "pyvenv.cfg").write_text("home = /usr/bin\nimplementation = CPython\nversion_info = 3.12.3\n", encoding="utf-8")
        self.machine = EnvironmentMachine()

    def tools(self):
        return Tools(self.root)

    def move(self, kind, machine=None, **options):
        return environment.move(self.project, kind, run=machine or self.machine, tools=self.tools(), **options)

    def harness(self):
        return json.loads((self.project / "harness.json").read_text(encoding="utf-8"))

    def controls(self):
        events, _ = Ledger(self.project).read_events()
        return [event["payload"] for event in events if event["event"] == "control"]

    def add_octave(self):
        """Octave recorded in the tools home as ticket 82 installs it, with its lock, and a ticket that names it."""
        prefix = self.root / "envs" / "octave"
        (prefix / "bin").mkdir(parents=True)
        (prefix / "bin" / "octave").write_text("#!/bin/sh\n", encoding="utf-8")
        lock = toolbox._write_lock(self.root, "octave", (RECORDED / "micromamba-env-export.txt").read_bytes())
        record_entry(self.root, "octave", tool_entry(prefix / "bin" / "octave", "10.3.0", "micromamba", source="conda-forge", lock=lock,
                                                     prefix=str(prefix)))
        (self.project / "code" / "octave-packages.lock").write_bytes(self.machine.octave_list)
        return prefix


class SettingTest(EnvironmentTestCase):
    def test_a_project_without_the_key_behaves_as_shared(self):
        self.assertNotIn("environment", self.harness())
        self.assertEqual(environment.setting(self.project), "shared")

    def test_the_schema_holds_the_four_environments_and_nothing_else(self):
        schema = load_schema("harness")
        for kind in ("shared", "conda", "venv", "container"):
            check(dict(self.harness(), environment=kind), schema)
        with self.assertRaises(ValidationError):
            check(dict(self.harness(), environment="docker"), schema)
        self.assertEqual(environment.KINDS, ("shared", "conda", "venv", "container"))


class VenvMoveTest(EnvironmentTestCase):
    def test_venv_is_built_through_uv_from_the_lock_checked_and_only_then_switched(self):
        report = self.move("venv")
        place = self.project / ".wayline" / "env-venv"
        uv = str(self.root / "bin" / "uv")
        built = [argv for argv, _ in self.machine.ran("uv")]
        self.assertEqual(built[0], [uv, "venv", "--python", "3.12", str(place)])
        self.assertEqual(built[1], [uv, "pip", "sync", "--python", str(place / "bin" / "python"), str(self.project / "code" / "requirements.lock")])
        self.assertIn([str(place / "bin" / "python"), "--version"], [argv for argv, _ in self.machine.ran("python")])
        self.assertEqual((report["from"], report["to"], report["changed"]), ("shared", "venv", True))
        self.assertEqual(self.harness()["environment"], "venv")
        self.assertEqual(self.controls(), [{"command": "environment", "args": {"environment": "venv", "from": "shared"}, "by": "cli"}])
        self.assertEqual(environment.setting(self.project), "venv")

    def test_a_failed_check_changes_nothing_and_names_the_failing_step(self):
        machine = EnvironmentMachine(python="3.11.9")
        with self.assertRaises(environment.MoveError) as caught:
            self.move("venv", machine=machine)
        self.assertIn("check python", str(caught.exception))
        self.assertIn("printed version 3.11 inside the venv environment", str(caught.exception))
        self.assertNotIn("environment", self.harness())
        self.assertEqual(self.controls(), [])
        self.assertFalse((self.project / ".wayline" / "env-venv").exists(), "a half-built place is not left behind")
        self.assertIsNone(environment.move_in_progress(self.project))

    def test_a_failed_build_changes_nothing_and_names_the_failing_step(self):
        machine = EnvironmentMachine(fail=lambda argv: argv[1:3] == ["pip", "sync"])
        with self.assertRaises(environment.MoveError) as caught:
            self.move("venv", machine=machine)
        self.assertIn("build python packages", str(caught.exception))
        self.assertIn("the recorded failure", str(caught.exception))
        self.assertNotIn("environment", self.harness())
        self.assertEqual(self.controls(), [])

    def test_packages_that_differ_from_the_lock_fail_the_check(self):
        machine = EnvironmentMachine(freeze=b"six==1.16.0\n")
        with self.assertRaises(environment.MoveError) as caught:
            self.move("venv", machine=machine)
        self.assertIn("six==1.17.0", str(caught.exception))
        self.assertNotIn("environment", self.harness())


class CondaMoveTest(EnvironmentTestCase):
    def test_conda_builds_one_prefix_from_the_explicit_locks_and_checks_each_tool_inside_it(self):
        self.add_octave()
        report = self.move("conda")
        prefix = self.project / ".wayline" / "env"
        micromamba = str(self.root / "bin" / "micromamba")
        calls = [argv for argv, _ in self.machine.ran("micromamba")]
        self.assertEqual(calls[0], [micromamba, "create", "-y", "-p", str(prefix), "--file", str(self.root / "locks" / "octave.txt")])
        self.assertEqual(calls[1], [micromamba, "install", "-y", "-p", str(prefix), "-c", "conda-forge", "--override-channels", "python=3.12"])
        for _, env in self.machine.ran("micromamba"):
            self.assertEqual(env["MAMBA_ROOT_PREFIX"], str(self.root / "mamba"))
        self.assertIn([str(self.root / "bin" / "uv"), "pip", "sync", "--python", str(prefix / "bin" / "python"),
                       str(self.project / "code" / "requirements.lock")], [argv for argv, _ in self.machine.ran("uv")])
        octave = [argv for argv, _ in self.machine.ran("octave")]
        self.assertIn([str(prefix / "bin" / "octave"), "--no-gui", "--eval", "pkg('install', '-forge', '-global', 'signal')"], octave)
        self.assertIn([str(prefix / "bin" / "octave"), "--version"], octave)
        self.assertIn([str(prefix / "bin" / "octave"), "--no-gui", "--eval", "pkg('list')"], octave)
        self.assertEqual(report["record"]["tools"]["octave"]["version"], "10.3.0")
        self.assertEqual(report["record"]["tools"]["python"]["version"], "3.12")
        self.assertEqual(self.harness()["environment"], "conda")
        stored = json.loads((self.project / ".wayline" / "env.json").read_text(encoding="utf-8"))
        self.assertEqual(stored["conda"]["place"], str(prefix))

    def test_conda_forges_own_installers_beside_the_lock_pass_and_any_other_package_fails(self):
        # What `uv pip freeze` printed of a conda-forge Python in the live build of 2026-10-19 (docs/verification/m8.md).
        frozen = b"pip @ file:///home/conda/feedstock-root/build-artifacts/pip-1785914405025/work\nsix==1.17.0\n"
        self.assertTrue(self.move("conda", machine=EnvironmentMachine(freeze=frozen))["changed"])
        self.move("shared")
        with self.assertRaises(environment.MoveError) as caught:
            self.move("conda", machine=EnvironmentMachine(freeze=frozen + b"numpy==2.3.1\n"))
        self.assertIn("not locked numpy==2.3.1", str(caught.exception))

    def test_a_lock_that_changed_since_it_was_recorded_is_refused(self):
        self.add_octave()
        (self.root / "locks" / "octave.txt").write_text("@EXPLICIT\nhttps://elsewhere/octave.conda\n", encoding="utf-8")
        with self.assertRaises(environment.MoveError) as caught:
            self.move("conda")
        self.assertEqual(caught.exception.step, "build octave")
        self.assertIn("changed since", str(caught.exception))
        self.assertEqual(self.machine.ran("micromamba"), [])
        self.assertNotIn("environment", self.harness())

    def test_a_tool_whose_version_differs_inside_fails_its_check_and_the_prefix_is_removed(self):
        self.add_octave()
        machine = EnvironmentMachine(versions={"octave": "GNU Octave, version 9.4.0\n"})
        machine.octave_list = self.machine.octave_list
        with self.assertRaises(environment.MoveError) as caught:
            self.move("conda", machine=machine)
        self.assertEqual(caught.exception.step, "check octave")
        self.assertIn("9.4.0", str(caught.exception))
        self.assertFalse((self.project / ".wayline" / "env").exists())
        self.assertNotIn("environment", self.harness())
        self.assertNotIn("conda", environment.records(self.project))


class ContainerMoveTest(EnvironmentTestCase):
    def setUp(self):
        super().setUp()
        self.add_octave()
        self.singularity = self.temp / "opt" / "singularity" / "bin" / "singularity"
        self.singularity.parent.mkdir(parents=True)
        self.singularity.write_text("#!/bin/sh\n", encoding="utf-8")
        self.docker = self.temp / "usr" / "bin" / "docker"
        self.docker.parent.mkdir(parents=True)
        self.docker.write_text("#!/bin/sh\n", encoding="utf-8")
        self.which = {"singularity": str(self.singularity), "docker": str(self.docker)}.get

    def move(self, kind, machine=None, **options):
        options.setdefault("which", self.which)
        return super().move(kind, machine=machine, **options)

    def test_the_image_is_built_without_root_through_a_sandbox_from_docker_and_micromamba(self):
        report = self.move("container")
        image = self.project / ".wayline" / "env.sif"
        sandbox = self.project / ".wayline" / "env.sandbox"
        singularity = str(self.singularity)
        builds = [argv for argv, _ in self.machine.ran("singularity") if argv[1] == "build"]
        self.assertEqual(builds[0], [singularity, "build", "--sandbox", str(sandbox), "docker://debian:bookworm-slim"])
        self.assertEqual(builds[-1], [singularity, "build", str(self.project / ".wayline" / "env.sif.new"), str(sandbox)])
        self.assertEqual(image.read_bytes(), b"SIF image of " + str(sandbox).encode())
        self.assertFalse(sandbox.exists(), "the sandbox goes once the image is built")
        mamba = self.machine.inner("micromamba")
        self.assertEqual(mamba[0], ["/usr/local/bin/micromamba", "create", "-y", "-p", "/opt/env", "--file", "/opt/wayline/locks/octave.txt"])
        self.assertEqual(mamba[1][-1], "python=3.12")
        execs = [argv for argv, _ in self.machine.ran("singularity") if argv[1] == "exec" and "--writable" in argv]
        self.assertTrue(execs)
        for argv in execs:
            self.assertNotIn("--fakeroot", argv)
        self.assertIn(["/usr/local/bin/uv", "pip", "sync", "--python", "/opt/env/bin/python", "/opt/wayline/locks/requirements.lock"],
                      self.machine.inner("uv"))
        self.assertIn(["/opt/env/bin/octave", "--version"], self.machine.inner("octave"))
        self.assertIn(["/opt/env/bin/python", "--version"], self.machine.inner("python"))
        self.assertEqual([argv[1] for argv, _ in self.machine.ran("docker")], ["info"], "Docker is asked and, refused, never used")
        self.assertEqual(report["record"]["image"], str(image))
        self.assertEqual(report["record"]["base"], "docker://debian:bookworm-slim")
        self.assertEqual(self.harness()["environment"], "container")
        self.assertEqual(toolbox.Tools(self.root).entry("singularity")["executable"], singularity, "recorded as a system tool")

    def test_docker_is_used_only_where_the_account_reaches_it(self):
        machine = EnvironmentMachine(docker=True)
        machine.octave_list = self.machine.octave_list
        report = self.move("container", machine=machine)
        self.assertEqual([argv[1:] for argv, _ in machine.ran("docker")],
                         [["info", "--format", "{{.ServerVersion}}"], ["pull", "debian:bookworm-slim"]])
        self.assertEqual(report["record"]["base"], "docker-daemon://debian:bookworm-slim")

    def test_matlab_stays_bound_in_from_the_host(self):
        matlab = self.temp / "MATLAB" / "R2025b" / "bin" / "matlab"
        matlab.parent.mkdir(parents=True)
        matlab.write_text("#!/bin/sh\n", encoding="utf-8")
        record_entry(self.root, "matlab", tool_entry(matlab, "24.2.0.2712019", "owner", installer="owner"))
        self.write_ticket(1, software=["matlab"])
        report = self.move("container")
        self.assertEqual(report["record"]["tools"]["matlab"]["executable"], str(matlab))
        self.assertIn(str(matlab.parent.parent), report["record"]["binds"])
        checked = [argv for argv, _ in self.machine.ran("singularity") if argv[1] == "exec" and str(matlab) in argv]
        self.assertEqual(len(checked), 1)
        self.assertEqual(checked[0][-2:], ["-batch", "ver"])
        self.assertIn(str(matlab.parent.parent), checked[0][checked[0].index("--bind") + 1:])

    def test_without_singularity_the_move_is_refused_and_says_so(self):
        with self.assertRaises(environment.MoveError) as caught:
            self.move("container", which={}.get)
        self.assertEqual(caught.exception.step, "build base image")
        self.assertIn("SingularityCE", str(caught.exception))
        self.assertNotIn("environment", self.harness())

    def write_ticket(self, identifier, **fields):
        from wayline import tickets
        tickets.write_ticket(Ledger(self.project), experiment_ticket(identifier, **fields), "## Demo\n\nthe model runs\n")

class MoveRulesTest(EnvironmentTestCase):
    def test_a_move_is_accepted_with_a_conductor_running_and_journaled_for_it(self):
        heartbeat = Ledger(self.project).heartbeat().acquire()
        self.addCleanup(heartbeat.release)
        heartbeat.write(pid=4242, started_at="2026-10-19T10:00:00.000Z", last_wave_at=None, harness_tag="v0.0.0")
        report = self.move("venv")
        self.assertEqual(report["conductor"]["pid"], 4242)
        self.assertEqual(self.harness()["environment"], "venv")
        self.assertEqual(self.controls()[-1]["command"], "environment")

    def test_a_project_already_there_with_everything_built_changes_nothing(self):
        self.move("venv")
        calls = len(self.machine.calls)
        report = self.move("venv")
        self.assertFalse(report["changed"])
        self.assertEqual(len(self.machine.calls), calls, "nothing is built again")
        self.assertEqual(len(self.controls()), 1)

    def test_a_tool_recorded_after_the_move_is_built_in_when_the_owner_moves_there_again(self):
        self.move("conda")
        self.add_octave()
        report = self.move("conda")
        self.assertTrue(report["changed"])
        self.assertIn("octave", report["record"]["tools"])

    def test_a_failed_rebuild_of_the_environment_the_project_is_in_puts_the_old_one_back(self):
        self.move("conda")
        prefix = self.project / ".wayline" / "env"
        (prefix / "kept").write_text("the prefix jobs ran in\n", encoding="utf-8")
        self.add_octave()
        with self.assertRaises(environment.MoveError) as caught:
            self.move("conda", machine=EnvironmentMachine(versions={"octave": "GNU Octave, version 9.4.0\n"}))
        self.assertIn("stays in conda", str(caught.exception))
        self.assertEqual((prefix / "kept").read_text(encoding="utf-8"), "the prefix jobs ran in\n")
        self.assertFalse((self.project / ".wayline" / "env.previous").exists())
        self.assertEqual(self.harness()["environment"], "conda")
        self.assertNotIn("octave", environment.records(self.project)["conda"]["tools"])

    def test_a_failed_check_of_a_new_image_leaves_the_image_the_project_runs(self):
        singularity = self.temp / "singularity"
        singularity.write_text("#!/bin/sh\n", encoding="utf-8")
        which = {"singularity": str(singularity)}.get
        self.move("container", which=which)
        image = self.project / ".wayline" / "env.sif"
        before = image.read_bytes()
        image.write_bytes(b"the image jobs run\n")
        self.add_octave()
        with self.assertRaises(environment.MoveError) as caught:
            self.move("container", machine=EnvironmentMachine(versions={"octave": "GNU Octave, version 9.4.0\n"}), which=which)
        self.assertEqual(caught.exception.step, "check octave")
        self.assertEqual(image.read_bytes(), b"the image jobs run\n")
        self.assertEqual([path.name for path in (self.project / ".wayline").iterdir() if path.name.startswith("env.s")], ["env.sif"])
        self.assertTrue(before)

    def test_a_lock_changed_after_the_move_builds_the_environment_again(self):
        self.move("conda")
        calls = len(self.machine.calls)
        (self.project / "code" / "requirements.lock").write_bytes(LOCK + b"scipy==1.16.2\n")
        machine = EnvironmentMachine(freeze=b"scipy==1.16.2\nsix==1.17.0\n")
        report = self.move("conda", machine=machine)
        self.assertTrue(report["changed"], "the prefix is built again from the new lock")
        self.assertTrue(machine.ran("micromamba"))
        self.assertFalse(self.move("conda", machine=machine)["changed"])
        self.assertGreater(calls, 0)

    def test_an_interrupted_rebuild_puts_the_old_prefix_back(self):
        self.move("conda")
        prefix = self.project / ".wayline" / "env"
        (prefix / "kept").write_text("kept\n", encoding="utf-8")
        self.add_octave()

        def interrupted(argv, cwd=None, timeout=None, env=None):
            if Path(argv[0]).name == "micromamba":
                raise KeyboardInterrupt
            return self.machine(argv, cwd=cwd, timeout=timeout, env=env)

        with self.assertRaises(KeyboardInterrupt):
            self.move("conda", machine=interrupted)
        self.assertEqual((prefix / "kept").read_text(encoding="utf-8"), "kept\n")
        self.assertIsNone(environment.move_in_progress(self.project))

    def test_jobs_are_refused_while_the_environment_the_project_is_in_is_rebuilt(self):
        self.move("venv")
        (self.project / "code" / "requirements.lock").write_bytes(LOCK + b"scipy==1.16.2\n")
        seen = []

        def build_step(argv, cwd=None, timeout=None, env=None):
            if Path(argv[0]).name == "uv" and argv[1] == "venv":
                with self.assertRaises(toolbox.ToolsError) as caught:
                    environment.inside(self.project, ["python", "fit.py"], {})
                seen.append(str(caught.exception))
            return self.machine(argv, cwd=cwd, timeout=timeout, env=env)

        self.machine.freeze = b"scipy==1.16.2\nsix==1.17.0\n"
        self.move("venv", machine=build_step)
        self.assertIn("being rebuilt", seen[0])

    def test_a_refusal_before_the_build_names_where_the_project_stays(self):
        self.move("venv")
        (self.project / "code" / "renv.lock").write_text("{}\n", encoding="utf-8")
        with self.assertRaises(environment.MoveError) as caught:
            self.move("conda")
        self.assertIn("stays in venv", str(caught.exception))

    def test_the_decider_never_sets_the_environment(self):
        with self.assertRaises(project.ProjectError) as caught:
            self.move("container", by="decider")
        self.assertIn("owner's word", str(caught.exception))
        self.assertEqual(self.machine.calls, [])
        self.assertNotIn("environment", self.harness())

    def test_an_unknown_environment_is_refused(self):
        with self.assertRaises(project.ProjectError):
            self.move("docker")

    def test_a_rebuild_is_refused_while_a_job_still_runs_in_the_place_it_would_replace(self):
        self.move("venv")
        self.move("shared")
        jobs = self.project / "research" / "jobs"
        jobs.mkdir(parents=True, exist_ok=True)
        (jobs / "t1-fit-1.json").write_text(json.dumps({"id": "t1-fit-1", "status": "running", "environment": "venv"}), encoding="utf-8")
        with self.assertRaises(environment.MoveError) as caught:
            self.move("venv")
        self.assertEqual(caught.exception.step, "start")
        self.assertIn("t1-fit-1", str(caught.exception))
        self.assertIn("stays in shared", str(caught.exception))
        self.assertTrue((self.project / ".wayline" / "env-venv").exists(), "the place the job runs in is left as it is")

    def test_the_move_under_way_is_shown_and_a_second_one_is_refused(self):
        seen = []

        def build_step(argv, cwd=None, timeout=None, env=None):
            if Path(argv[0]).name == "uv" and argv[1] == "venv":
                seen.append(environment.move_in_progress(self.project))
                with self.assertRaises(environment.MoveError) as caught:
                    environment.move(self.project, "conda", run=self.machine, tools=self.tools())
                seen.append(caught.exception.step)
            return self.machine(argv, cwd=cwd, timeout=timeout, env=env)

        self.move("venv", machine=build_step)
        self.assertEqual((seen[0]["from"], seen[0]["to"], seen[0]["pid"]), ("shared", "venv", os.getpid()))
        self.assertEqual(seen[1], "start")
        self.assertIsNone(environment.move_in_progress(self.project))

    def test_back_to_shared_is_checked_too_and_journaled(self):
        self.add_octave()
        self.move("conda")
        report = self.move("shared")
        self.assertEqual((report["from"], report["to"]), ("conda", "shared"))
        self.assertEqual(self.harness()["environment"], "shared")
        self.assertIn([str(self.root / "envs" / "octave" / "bin" / "octave"), "--version"], [argv for argv, _ in self.machine.ran("octave")])
        self.assertEqual([control["args"] for control in self.controls()],
                         [{"environment": "conda", "from": "shared"}, {"environment": "shared", "from": "conda"}])

    def test_the_build_places_are_gitignored(self):
        ignored = (self.project / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn(".wayline/env*", ignored)


class ResolveAfterTheSwitchTest(EnvironmentTestCase):
    """`wayline job add` and `wayline tools run` resolve each tool through the project's environment once it switched."""

    def setUp(self):
        super().setUp()
        self.add_octave()
        from wayline import tickets
        tickets.write_ticket(Ledger(self.project), experiment_ticket(1, software=["octave"]), "## Demo\n\nthe model runs\n")
        self.singularity = self.temp / "opt" / "singularity" / "bin" / "singularity"
        self.singularity.parent.mkdir(parents=True)
        self.singularity.write_text("#!/bin/sh\n", encoding="utf-8")
        self.which = {"singularity": str(self.singularity)}.get

    def add(self, spec, **options):
        [record] = resources.add_jobs(self.project, spec, ticket=1, tools=self.tools(), **options)
        check(record, load_schema("job"))
        return record

    def image_prefix(self):
        """What runs a command in the image: the project is bound in when it lies outside the home, which a test's temporary one does."""
        binds = [] if Path.home().resolve() in self.project.resolve().parents else ["--bind", str(self.project.resolve())]
        return [str(self.singularity), "exec", "--nv"] + binds + [str(self.project.resolve() / ".wayline" / "env.sif")]

    def test_before_any_move_a_job_runs_as_tools_json_records_its_tool(self):
        record = self.add({"tool": "octave", "command": ["--eval", "1"]})
        self.assertEqual(record["command"], [str(self.root / "envs" / "octave" / "bin" / "octave"), "--eval", "1"])
        self.assertEqual(record["environment"], "shared")

    def test_after_a_move_to_conda_the_tool_is_the_prefixs(self):
        self.move("conda")
        record = self.add({"tool": "octave", "command": ["octave", "--eval", "1"]})
        prefix = self.project.resolve() / ".wayline" / "env"
        self.assertEqual(record["command"], [str(prefix / "bin" / "octave"), "--eval", "1"])
        self.assertEqual(record["environment"], "conda")
        self.assertEqual(record["tools"][0]["name"], "octave")
        self.assertEqual(record["tools"][0]["version"], "10.3.0", "the same version, rebuilt from the same lock")
        plain = self.add({"command": ["python", "scripts/fit.py"]})
        self.assertEqual(plain["command"], [str(prefix / "bin" / "python"), "scripts/fit.py"])
        self.assertTrue(plain["env"]["PATH"].startswith(str(prefix / "bin") + ":"))

    def test_after_a_move_to_a_container_the_tool_runs_inside_the_image(self):
        self.move("container", which=self.which)
        record = self.add({"tool": "octave", "command": ["--eval", "1"]})
        self.assertEqual(record["command"], self.image_prefix() + ["/opt/env/bin/octave", "--eval", "1"])
        self.assertEqual(record["environment"], "container")
        self.assertEqual(record["env"]["LC_ALL"], "C.UTF-8", "the image's own locale, not the host's")
        plain = self.add({"command": ["python", "scripts/fit.py"], "env": {"SEED": "1"}})
        self.assertEqual(plain["command"], self.image_prefix() + ["python", "scripts/fit.py"])
        self.assertEqual(plain["env"], {"SEED": "1", "SINGULARITYENV_PREPEND_PATH": "/opt/env/bin", "LC_ALL": "C.UTF-8"})

    def test_matlab_runs_from_the_host_bound_into_the_image(self):
        matlab = self.temp / "MATLAB" / "R2024b" / "bin" / "matlab"
        matlab.parent.mkdir(parents=True)
        matlab.write_text("#!/bin/sh\n", encoding="utf-8")
        record_entry(self.root, "matlab", tool_entry(matlab, "24.2.0.2712019", "owner", installer="owner"))
        from wayline import tickets
        tickets.write_ticket(Ledger(self.project), experiment_ticket(2, software=["matlab"]), "## Demo\n\nthe fit runs\n")
        self.move("container", which=self.which)
        record = self.add({"tool": "matlab", "command": ["-batch", "fit"]})
        prefix = self.image_prefix()
        self.assertEqual(record["command"], prefix[:-1] + ["--bind", str(matlab.parent.parent), prefix[-1], str(matlab), "-batch", "fit"])

    def test_a_job_naming_no_tool_keeps_the_path_it_had_after_the_prefix(self):
        self.move("conda")
        with mock.patch.dict(os.environ, {"PATH": "/usr/local/cuda/bin:/usr/bin"}):
            record = self.add({"command": ["bash", "run.sh"]})
        prefix = self.project.resolve() / ".wayline" / "env"
        self.assertEqual(record["env"]["PATH"], "%s/bin:/usr/local/cuda/bin:/usr/bin" % prefix)

    def test_julia_activates_the_projects_environment_after_a_move(self):
        julia = self.root / "julia-1.12.7"
        (julia / "bin").mkdir(parents=True)
        (julia / "bin" / "julia").write_text("#!/bin/sh\n", encoding="utf-8")
        record_entry(self.root, "julia", tool_entry(julia / "bin" / "julia", "1.12.7", "tarball"))
        from wayline import tickets
        tickets.write_ticket(Ledger(self.project), experiment_ticket(2, software=["julia"]), "## Demo\n\nthe fit runs\n")
        self.move("conda")
        record = self.add({"tool": "julia", "command": ["fit.jl"]})
        self.assertEqual(record["env"]["JULIA_PROJECT"], str(self.project / "code"))
        self.assertTrue(record["env"]["JULIA_DEPOT_PATH"].endswith("julia-depot"))

    def test_matlab_through_a_link_is_bound_by_its_own_root(self):
        matlab = self.temp / "MATLAB" / "R2024b" / "bin" / "matlab"
        matlab.parent.mkdir(parents=True)
        matlab.write_text("#!/bin/sh\n", encoding="utf-8")
        link = self.temp / "local" / "bin" / "matlab"
        link.parent.mkdir(parents=True)
        link.symlink_to(matlab)
        record_entry(self.root, "matlab", tool_entry(link, "24.2.0.2712019", "owner", installer="owner"))
        from wayline import tickets
        tickets.write_ticket(Ledger(self.project), experiment_ticket(2, software=["matlab"]), "## Demo\n\nthe fit runs\n")
        report = self.move("container", which=self.which)
        self.assertEqual(report["record"]["binds"], [str(matlab.resolve().parent.parent)])
        self.assertEqual(report["record"]["tools"]["matlab"]["executable"], str(matlab.resolve()))

    def test_a_tool_recorded_after_the_move_is_refused_until_the_environment_is_built_again(self):
        self.move("venv")
        record_entry(self.root, "julia", tool_entry("/opt/tools/julia-1.12.7/bin/julia", "1.12.7", "tarball"))
        with self.assertRaises(resources.JobError) as caught:
            self.add({"tool": "julia", "command": ["run.jl"]})
        self.assertIn("wayline switch --environment venv", str(caught.exception))

    def test_the_harness_and_the_machines_tools_stay_as_tools_json_records_them(self):
        pandoc = self.root / "envs" / "pandoc" / "bin" / "pandoc"
        record_entry(self.root, "pandoc", tool_entry(pandoc, "3.11", "micromamba"))
        self.move("container", which=self.which)
        resolved = environment.resolve(self.project, "pandoc", self.tools())
        self.assertEqual(resolved.argv, [str(pandoc)])

    def test_a_software_decisions_own_job_is_the_harnesss_and_runs_outside(self):
        self.move("conda")
        record = self.add({"command": ["/opt/wayline/bin/wayline", "tools", "install", "r"]}, environment="shared")
        self.assertEqual(record["command"], ["/opt/wayline/bin/wayline", "tools", "install", "r"])
        self.assertEqual(record["environment"], "shared")

    def test_tools_run_resolves_through_the_environment(self):
        self.move("container", which=self.which)
        machine = EnvironmentMachine()
        done = toolbox.run_recorded("octave", ["--version"], tools=self.tools(), run=machine, project=self.project)
        self.assertEqual(done.returncode, 0)
        self.assertEqual(machine.calls[-1][0], self.image_prefix() + ["/opt/env/bin/octave", "--version"])
        shared = toolbox.run_recorded("octave", ["--version"], tools=self.tools(), run=machine)
        self.assertEqual(machine.calls[-1][0], [str(self.root / "envs" / "octave" / "bin" / "octave"), "--version"])
        self.assertEqual(shared.returncode, 0)


class JobAcrossTheSwitchTest(EnvironmentTestCase):
    """A job launched before the switch finishes where it started; every job launched after it runs in the new environment."""

    def test_a_replayed_journal_keeps_each_job_where_it_was_launched(self):
        self.add_octave()
        from wayline import tickets
        tickets.write_ticket(Ledger(self.project), experiment_ticket(1, software=["octave"]), "## Demo\n\nthe model runs\n")
        fake = resources.FakeJobs()
        fake.script(["running"], job_id="t1-before")
        fake.script(["running"], job_id="t1-after")
        fake.script(["exited"], job_id="t1-before")
        runner = resources.JobRunner(self.project, backend=fake)
        [before] = resources.add_jobs(self.project, {"id": "t1-before", "tool": "octave", "command": ["--eval", "fit"]}, ticket=1,
                                      backend="fake", tools=self.tools())
        runner.launch(resources.spec_from_record(before))
        self.move("conda")
        [after] = resources.add_jobs(self.project, {"id": "t1-after", "tool": "octave", "command": ["--eval", "fit"]}, ticket=1,
                                     backend="fake", tools=self.tools())
        runner.launch(resources.spec_from_record(after))
        # The job of before the switch is relaunched by its footprint ladder after it: it keeps its own command.
        relaunched = runner.read("t1-before")
        runner.launch(resources.spec_from_record(relaunched))
        ledger = Ledger(self.project)
        ledger.append_event("job_finished", {"exit_code": 0, "seconds": 3, "outputs_ok": True}, ticket=1, job="t1-before")

        events, _ = ledger.read_events()
        view = replay.replay(events)
        self.assertEqual(view.environment, "conda")
        self.assertEqual((view.jobs["t1-before"]["environment"], view.jobs["t1-before"]["status"]), ("shared", "exited"))
        self.assertEqual(view.jobs["t1-after"]["environment"], "conda")
        launched = [(event["job"], event["payload"]["environment"]) for event in events if event["event"] == "job_launched"]
        self.assertEqual(launched, [("t1-before", "shared"), ("t1-after", "conda"), ("t1-before", "shared")])
        shared_octave = str(self.root / "envs" / "octave" / "bin" / "octave")
        self.assertEqual(runner.read("t1-before")["command"], [shared_octave, "--eval", "fit"])
        self.assertEqual(runner.read("t1-after")["command"], [str(self.project.resolve() / ".wayline" / "env" / "bin" / "octave"), "--eval", "fit"])


class SwitchVerbTest(EnvironmentTestCase):
    def switch(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = project.switch_command(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_the_verb_moves_the_project_and_says_where_it_runs_now(self):
        machine = self.machine
        real = environment.move
        with mock.patch.object(environment, "move", lambda target, kind, **options: real(target, kind, run=machine, tools=self.tools(), **options)):
            code, out, err = self.switch("--environment", "venv", "--project", str(self.project))
        self.assertEqual(code, 0, err)
        self.assertIn("environment moved from shared to venv", out)
        self.assertEqual(self.harness()["environment"], "venv")

    def test_a_refused_move_prints_the_failing_step_and_changes_nothing(self):
        machine = EnvironmentMachine(python="3.11.9")
        real = environment.move
        with mock.patch.object(environment, "move", lambda target, kind, **options: real(target, kind, run=machine, tools=self.tools(), **options)):
            code, out, err = self.switch("--environment", "venv", "--project", str(self.project))
        self.assertEqual(code, 1)
        self.assertIn("failed at `check python`", err)
        self.assertNotIn("environment", self.harness())

    def test_the_environment_is_given_on_its_own(self):
        code, _, err = self.switch("--environment", "conda", "--fallback", "auto")
        self.assertEqual(code, 2)
        self.assertIn("--environment", err)


class DeciderNeverMovesTest(unittest.TestCase):
    def test_an_answer_that_moves_the_environment_is_the_owners(self):
        from wayline.decider import irreversible_class
        for text in ("Move the project to a container.", "wayline switch --environment conda", "switch the environment to venv",
                     "move it into a Singularity image", "change the project's environment to shared", "switch to conda",
                     "move the project to conda", "rebuild the environment as a container", "run it in a container"):
            with self.subTest(text=text):
                self.assertEqual(irreversible_class(text), "environment")
        for text in ("Install", "run the fit inside the job", "keep the environment variable SEED at 1", "Go without",
                     "set the seed to 3", "install conda-forge's r-base"):
            with self.subTest(text=text):
                self.assertIsNone(irreversible_class(text))

    def test_the_decider_is_told_the_environment_is_not_its_to_set(self):
        from types import SimpleNamespace

        from wayline import decider
        subject = decider.Subject(kind="ticket", key="3", question="Install octave?", options=["Install", "Not now"])
        role = SimpleNamespace(protocol="", output_schema=None)
        prompt = " ".join(decider.decider_prompt(role, subject, "", {"human_only": ["goal", "data"]}, "/tmp/project").split())
        self.assertIn("Moving the project's environment (`wayline switch --environment`", prompt)
        self.assertIn("the owner's word alone", prompt)


if __name__ == "__main__":
    unittest.main()
