"""The user units, `run --detach`, the dashboard start, and the token file (Implementation Decisions 7).

The user manager is `tick.use_fake_systemd`, which keeps its unit directory and its timer stamps
under the test's temporary directory; what is asserted is the files on disk, the commands the
manager was given in order, and what `init` and `run` print.
"""

import io
import os
import re
import stat
import sys
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from tests.paths import HARNESS_ROOT, SPEC_PATH
from tests.projects import ProjectTestCase, tree_hash
from tests.test_conductor import ConductorCase, done, patch, run_verb
from wayline import project, tick, worker

SYSTEMCTL = ["systemctl", "--user"]


def spec_units():
    """The three unit files as decision 7 of the spec prints them, by name."""
    text = SPEC_PATH.read_text(encoding="utf-8")
    block = text[text.index("# wayline-tick.service"):]
    block = block[:block.index("```")]
    block = "\n".join(line[2:] if line.startswith("  ") else line for line in block.split("\n"))  # the spec indents it under a bullet
    units = {}
    for chunk in re.split(r"^# (wayline-[a-z-]+\.(?:service|timer))\n", block, flags=re.M)[1:]:
        if chunk.startswith("wayline-"):
            name = chunk
        else:
            units[name] = chunk.strip() + "\n"
    return units


class FakeManagerCase(ProjectTestCase):
    def setUp(self):
        super().setUp()
        context = tick.use_fake_systemd(self.temp / "machine")
        self.manager = context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)


class UnitFilesTest(ProjectTestCase):
    def test_the_units_are_the_ones_decision_7_gives(self):
        home = "/home/owner"
        placeholders = {"<abs interpreter>": "/usr/bin/python3", "<abs harness dir>": "/opt/wayline", "<abs home>": home}
        expected = {}
        for name, text in spec_units().items():
            for placeholder, value in placeholders.items():
                text = text.replace(placeholder, value)
            expected[name] = text
        self.assertEqual(sorted(expected), sorted(tick.UNITS))
        self.assertEqual(tick.unit_files("/opt/wayline", "/usr/bin/python3", home + "/.wayline"), expected)

    def test_by_default_the_units_run_this_checkout_with_this_interpreter(self):
        service = tick.unit_files()[tick.TICK_SERVICE]
        self.assertIn("ExecStart=%s -m wayline tick\n" % sys.executable, service)
        self.assertIn("WorkingDirectory=%s\n" % HARNESS_ROOT, service)
        self.assertIn("EnvironmentFile=-%s/env\n" % self.wayline_home, service)


class InstallTest(FakeManagerCase):
    def test_install_writes_the_units_reloads_and_enables_the_timer_and_the_dashboard(self):
        report = tick.install_units()
        directory = self.manager.units
        self.assertEqual(report["directory"], str(directory))
        self.assertEqual(sorted(report["written"]), sorted(tick.UNITS))
        for name, text in tick.unit_files().items():
            self.assertEqual((directory / name).read_text(encoding="utf-8"), text)
        self.assertEqual(self.manager.calls, [
            SYSTEMCTL + ["daemon-reload"],
            SYSTEMCTL + ["enable", "--now", "wayline-tick.timer", "wayline-dashboard.service"],
        ])
        self.assertTrue((directory / "timers.target.wants" / "wayline-tick.timer").is_symlink())
        self.assertEqual(self.manager.active, {"wayline-tick.timer", "wayline-dashboard.service"})
        self.assertEqual(report["problems"], [])

    def test_a_second_install_changes_nothing(self):
        tick.install_units()
        before = tree_hash(self.manager.root)
        report = tick.install_units()
        self.assertEqual(report["written"], [])
        self.assertEqual(tree_hash(self.manager.root), before)

    def test_a_stale_unit_is_rewritten(self):
        tick.install_units()
        (self.manager.units / tick.TICK_SERVICE).write_text("[Service]\nExecStart=/old/python -m wayline tick\n", encoding="utf-8")
        self.assertEqual(tick.install_units()["written"], [tick.TICK_SERVICE])

    def test_a_manager_that_refuses_is_a_problem_and_the_files_are_still_written(self):
        self.manager.answer("systemctl", "--user", "enable", returncode=1, stderr="Failed to connect to bus: No medium found")
        report = tick.install_units()
        self.assertEqual(len(report["problems"]), 1)
        self.assertIn("Failed to connect to bus", report["problems"][0])
        self.assertTrue((self.manager.units / tick.TICK_TIMER).is_file())


class UninstallTest(FakeManagerCase):
    def setUp(self):
        super().setUp()
        # What this machine's unit directory held before any wayline unit: another service, enabled.
        units = self.manager.units
        (units / "default.target.wants").mkdir(parents=True)
        (units / "hermes-gateway.service").write_text("[Service]\nExecStart=/bin/true\n", encoding="utf-8")
        (units / "default.target.wants" / "hermes-gateway.service").symlink_to(units / "hermes-gateway.service")
        self.before = tree_hash(units)

    def test_uninstall_removes_exactly_the_three_units_and_the_stamp(self):
        tick.install_units()
        self.assertTrue(tick.stamp_path().exists())
        self.manager.calls.clear()
        report = tick.uninstall_units()
        self.assertEqual(self.manager.calls, [
            SYSTEMCTL + ["disable", "--now", "wayline-tick.timer", "wayline-dashboard.service"],
            SYSTEMCTL + ["stop", "wayline-tick.service"],
            SYSTEMCTL + ["clean", "--what=state", "wayline-tick.timer"],
            SYSTEMCTL + ["daemon-reload"],
            SYSTEMCTL + ["reset-failed", "wayline-tick.service", "wayline-tick.timer", "wayline-dashboard.service"],
        ])
        self.assertEqual(tree_hash(self.manager.units), self.before)
        self.assertFalse(tick.stamp_path().exists())
        self.assertEqual(sorted(report["removed"]), sorted(tick.UNITS))

    def test_without_a_manager_the_files_the_links_and_the_stamp_still_go(self):
        tick.install_units()
        self.manager.answer("systemctl", returncode=1, stderr="Failed to connect to bus")
        report = tick.uninstall_units()
        self.assertEqual(tree_hash(self.manager.units), self.before)
        self.assertFalse(tick.stamp_path().exists())
        self.assertEqual(len(report["notes"]), 4)

    def test_nothing_touches_the_crontab(self):
        tick.install_units()
        tick.uninstall_units()
        self.assertEqual({call[0] for call in self.manager.calls}, {"systemctl"})
        self.assertFalse(any("crontab" in part for call in self.manager.calls for part in call))


class UnitsOffTest(ProjectTestCase):
    """The suite runs with `WAYLINE_UNITS=none`: nothing reaches the owner's manager or unit directory."""

    def test_the_suite_turns_the_units_off(self):
        self.assertEqual(os.environ.get(tick.UNITS_ENV), "none")

    def test_with_the_units_off_nothing_is_installed_uninstalled_or_started(self):
        self.assertEqual(tick.install_units()["skipped"], "WAYLINE_UNITS=none")
        self.assertEqual(tick.uninstall_units()["skipped"], "WAYLINE_UNITS=none")
        self.assertEqual(tick.ensure_dashboard()[0], "off")
        with self.assertRaises(tick.UnitsOff):
            tick.launch_detached(self.temp)

    def test_an_unknown_backend_is_refused(self):
        with mock.patch.dict(os.environ, {tick.UNITS_ENV: "cron"}):
            with self.assertRaises(tick.UnitError):
                tick.install_units()

    def test_an_unknown_backend_never_fails_the_dashboard_start(self):
        with mock.patch.dict(os.environ, {tick.UNITS_ENV: "off"}):
            state, detail = tick.ensure_dashboard()
        self.assertEqual(state, "failed")
        self.assertIn("WAYLINE_UNITS=off", detail)


class InitVerbTest(FakeManagerCase):
    def init(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = project.init_command(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_init_installs_the_units_once_per_machine(self):
        code, out, _ = self.init(str(self.temp / "one"), "--no-git")
        self.assertEqual(code, 0)
        self.assertIn("wrote wayline-tick.timer", out)
        self.assertIn("enabled wayline-tick.timer wayline-dashboard.service", out)
        code, out, _ = self.init(str(self.temp / "two"), "--no-git")
        self.assertEqual(code, 0)
        self.assertNotIn("wrote wayline-tick", out)
        self.assertIn("enabled wayline-tick.timer wayline-dashboard.service", out)

    def test_init_says_what_the_manager_refused(self):
        self.manager.answer("systemctl", "--user", "enable", returncode=1, stderr="Failed to connect to bus")
        code, out, _ = self.init(str(self.temp / "one"), "--no-git")
        self.assertEqual(code, 0)
        self.assertIn("Failed to connect to bus", out)

    def test_uninstall_units_takes_no_path_and_removes_the_units(self):
        self.init(str(self.temp / "one"), "--no-git")
        code, out, _ = self.init("--uninstall-units")
        self.assertEqual(code, 0)
        self.assertIn("removed wayline-tick.service", out)
        self.assertFalse((self.manager.units / tick.TICK_TIMER).exists())
        code, _, err = self.init(str(self.temp / "one"), "--uninstall-units")
        self.assertEqual(code, 2)
        self.assertIn("no path", err)

    def test_init_needs_a_path(self):
        code, _, err = self.init()
        self.assertEqual(code, 2)
        self.assertIn("path", err)


class DetachTest(ConductorCase):
    def setUp(self):
        super().setUp()
        context = tick.use_fake_systemd(self.temp / "machine")
        self.manager = context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)

    def launches(self):
        return self.manager.commands("systemd-run")

    def test_detach_starts_the_conductor_as_the_transient_unit(self):
        code, out, err = run_verb(["--detach", "--project", str(self.project)])
        self.assertEqual(code, 0, err)
        [argv] = self.launches()
        self.assertEqual(argv[:6], ["systemd-run", "--user", "--unit=wayline-conductor", "-p",
                                    "WorkingDirectory=%s" % HARNESS_ROOT, "-p"])
        self.assertEqual(argv[6], "EnvironmentFile=-%s/env" % self.wayline_home)
        self.assertEqual(argv[-7:], [sys.executable, "-m", "wayline", "run", "--resume", "--project", str(self.project.resolve())])
        self.assertNotIn("--collect", argv)
        self.assertIn("wayline-conductor", out)
        self.assertEqual(self.events("run_started"), [])  # nothing ran in this process

    def test_detach_carries_the_wayline_settings_and_the_wave_cap(self):
        with mock.patch.dict(os.environ, {"WAYLINE_LAUNCHER": "fake"}):
            code, _, err = run_verb(["--detach", "--max-waves", "3", "--project", str(self.project)])
        self.assertEqual(code, 0, err)
        [argv] = self.launches()
        self.assertIn("WAYLINE_LAUNCHER=fake", argv)
        self.assertIn("WAYLINE_HOME=%s" % self.wayline_home, argv)
        self.assertIn("PATH=%s" % os.environ["PATH"], argv)  # the manager's PATH lacks ~/.local/bin
        self.assertEqual(argv[-2:], ["--max-waves", "3"])

    def test_a_conductor_unit_still_running_is_not_doubled(self):
        self.manager.answer("systemctl", "--user", "show", stdout="LoadState=loaded\nActiveState=active\nSubState=running\n")
        code, _, err = run_verb(["--detach", "--project", str(self.project)])
        self.assertEqual(code, 1)
        self.assertIn("already active", err)
        self.assertEqual(self.launches(), [])

    def test_a_failed_conductor_unit_is_reset_before_the_launch(self):
        self.manager.answer("systemctl", "--user", "show", stdout="LoadState=loaded\nActiveState=failed\nSubState=failed\n")
        code, _, err = run_verb(["--detach", "--project", str(self.project)])
        self.assertEqual(code, 0, err)
        verbs = [call[2] if call[0] == "systemctl" else "systemd-run" for call in self.manager.calls]
        self.assertLess(verbs.index("reset-failed"), verbs.index("systemd-run"))

    def test_detach_refuses_what_the_foreground_run_refuses(self):
        (self.project / "stray.txt").write_text("mine\n", encoding="utf-8")
        code, _, err = run_verb(["--detach", "--project", str(self.project)])
        self.assertEqual(code, 2)
        self.assertIn("stray.txt", err)
        self.assertEqual(self.launches(), [])

    def test_a_refused_systemd_run_exits_1_with_what_it_said(self):
        self.manager.answer("systemd-run", returncode=1, stderr="Failed to start transient service unit: Unit wayline-conductor.service already exists.")
        code, _, err = run_verb(["--detach", "--project", str(self.project)])
        self.assertEqual(code, 1)
        self.assertIn("already exists", err)

    def test_the_run_prints_the_dashboard_and_starts_it_when_it_is_not_active(self):
        with worker.use_fake() as fake:
            fake.script(done(), patch=patch())
            code, out, err = run_verb(["--project", str(self.project)])
        self.assertEqual(code, 0, err)
        self.assertIn("dashboard  http://127.0.0.1:8765/", out)
        self.assertIn("ssh -o ServerAliveInterval=30", out)
        self.assertIn(SYSTEMCTL + ["start", "wayline-dashboard.service"], self.manager.calls)

    def test_an_active_dashboard_is_left_alone(self):
        self.manager.active.add(tick.DASHBOARD_SERVICE)
        code, out, err = run_verb(["--detach", "--project", str(self.project)])
        self.assertEqual(code, 0, err)
        self.assertIn("dashboard  http://127.0.0.1:8765/", out)
        self.assertNotIn(SYSTEMCTL + ["start", "wayline-dashboard.service"], self.manager.calls)

    def test_a_dashboard_that_will_not_start_says_how_to_get_one(self):
        self.manager.answer("systemctl", "--user", "start", returncode=5, stderr="Unit wayline-dashboard.service not found.")
        code, out, err = run_verb(["--detach", "--project", str(self.project)])
        self.assertEqual(code, 0, err)
        self.assertIn("not found", out)
        self.assertIn("wayline init", out)


class _Terminal(io.StringIO):
    def isatty(self):
        return True


class EnvFileTest(FakeManagerCase):
    def test_the_file_is_0600_and_carries_the_token(self):
        path = tick.write_env_file("  sk-ant-oat01-abc\n")
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertIn("CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-abc\n", path.read_text(encoding="utf-8"))
        self.assertEqual(path, self.wayline_home / "env")

    def test_a_token_with_spaces_is_refused(self):
        with self.assertRaises(tick.UnitError):
            tick.write_env_file("two words")
        self.assertFalse(tick.env_path().exists())

    def test_away_from_a_terminal_nothing_is_asked(self):
        ran = []
        note = tick.offer_env_file(stream=io.StringIO("y\n"), setup_token=lambda: ran.append(1) or 0)
        self.assertEqual(ran, [])
        self.assertIn("setup-token", note)
        self.assertFalse(tick.env_path().exists())

    def test_at_a_terminal_a_yes_runs_setup_token_and_writes_the_pasted_token(self):
        out = io.StringIO()
        note = tick.offer_env_file(stream=_Terminal("y\n"), out=out, setup_token=lambda: 0, read_token=lambda prompt: "sk-ant-oat01-xyz\n")
        self.assertIn("Only the wayline units load it", out.getvalue())
        self.assertIn("wrote", note)
        self.assertIn("CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-xyz\n", tick.env_path().read_text(encoding="utf-8"))
        self.assertEqual(stat.S_IMODE(tick.env_path().stat().st_mode), 0o600)

    def test_a_no_or_a_failed_setup_token_writes_nothing(self):
        tick.offer_env_file(stream=_Terminal("\n"), out=io.StringIO(), setup_token=lambda: 0, read_token=lambda prompt: "tok")
        self.assertFalse(tick.env_path().exists())
        note = tick.offer_env_file(stream=_Terminal("y\n"), out=io.StringIO(), setup_token=lambda: 1, read_token=lambda prompt: "tok")
        self.assertIn("exited 1", note)
        self.assertFalse(tick.env_path().exists())

    def test_a_cancelled_paste_or_an_interrupted_setup_token_is_a_note_not_a_traceback(self):
        def interrupt(*_):
            raise KeyboardInterrupt

        note = tick.offer_env_file(stream=_Terminal("y\n"), out=io.StringIO(), setup_token=lambda: 0, read_token=interrupt)
        self.assertIn("not written: cancelled", note)
        note = tick.offer_env_file(stream=_Terminal("y\n"), out=io.StringIO(), setup_token=interrupt)
        self.assertIn("interrupted", note)
        self.assertFalse(tick.env_path().exists())

    def test_an_existing_file_is_never_offered_again(self):
        tick.write_env_file("sk-ant-oat01-abc")
        asked = []
        self.assertIsNone(tick.offer_env_file(stream=_Terminal("y\n"), out=io.StringIO(), setup_token=lambda: asked.append(1) or 0))
        self.assertEqual(asked, [])


class HermesDetectionTest(ProjectTestCase):
    def test_init_records_the_hermes_interpreter_when_the_machine_has_one(self):
        fake_home = self.temp / "owner"
        python = fake_home / ".hermes" / "hermes-agent" / "venv" / "bin" / "python"
        with mock.patch.dict(os.environ, {"HOME": str(fake_home)}):
            self.assertIsNone(project.detect_hermes())
            python.parent.mkdir(parents=True)
            python.write_text("#!/bin/sh\n", encoding="utf-8")
            study = self.temp / "study"
            project.init_project(study, harness_root=self.fake_harness(), git=False, owner_email=None)
        self.assertEqual(project.read_harness(study)["notify"]["hermes_python"], str(python))
