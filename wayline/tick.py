"""The tick and its machinery (Implementation Decisions 7): the tick, the user units, the detached conductor, the token file.

Ticket 13 built what the tick runs under and how the conductor leaves the shell; ticket 14 built the
tick itself, `wayline tick`, which relaunches the conductor through `launch_detached` here.

- **The tick.** What `wayline-tick.service` runs every fifteen minutes, doing what the owner would
  otherwise do by hand. Under `flock -n ~/.wayline/tick.lock` it reads the active project, checks the
  login (a `human_only` decision ticket when it nears its end), reads `/usage` with its Fable line and
  journals `pacing` on a change, and stops there while a conductor is alive and waving. Otherwise,
  whatever the window says, it polls the jobs, runs the output check due on the ones that exited,
  renders `REPORT.md` offline when the journal moved, and sends the notifications the owner is owed;
  then it relaunches the conductor when work remains and the window is open, or when a decision was
  answered after the run last ended or paused. `tick()` takes a `Machine`, whose clock, heartbeat,
  notifier, and relaunch the tests replace; `/usage` and `claude auth status` go through the launcher seam.

- **The user units.** `init` writes `wayline-tick.service`, `wayline-tick.timer`, and
  `wayline-dashboard.service` into `~/.config/systemd/user/` exactly as decision 7 gives them, runs
  `daemon-reload`, and enables the timer and the dashboard with `--now`. The files are per machine,
  not per project, so a second `init` rewrites nothing and only asks the manager again, which is a
  no-op for units already enabled. `init --uninstall-units` disables them, stops a tick mid-run,
  cleans the timer's `Persistent=true` stamp, and removes exactly those three files. Nothing here
  reads or writes the crontab, which is shared with other tools on this machine (research-notes 05, A6).
- **The detached conductor.** `wayline run --detach` starts `wayline run --resume` as the transient
  unit `wayline-conductor`, never with `--collect`, so a conductor that failed stays loaded for the
  owner to read (`systemctl --user status wayline-conductor`) until the next launch resets it.
- **The dashboard.** `wayline run` does not host it (decision 8): it starts
  `wayline-dashboard.service` when the service is not active, so the dashboard outlives every conductor.
- **The token file.** `~/.wayline/env` carries `CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token`.
  Every unit loads it with `EnvironmentFile=-`, and nothing else does: the one-year token outranks the
  owner's `/login` (research-notes 02), so it belongs in the units' environment, never in a shell profile.

`WAYLINE_UNITS=none` turns the manager off for a process and its children: `init` writes no unit,
`run` starts no dashboard, and `--detach` is refused. The suite sets it, so no test reaches the
owner's user manager; `use_fake_systemd()` stands in for the manager and the two directories it owns.
"""

import argparse
import csv
import fcntl
import getpass
import json
import os
import re
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from wayline import HARNESS_ROOT, pacing, replay
from wayline.ledger import (
    DECISION, DECISION_OPENED, NOTIFIED, PACING, PAUSED, REPORT_RENDERED, RUN_ENDED, RUN_STARTED, TICKET_CREATED,
    TICKET_NEEDS_HUMAN, Ledger, atomic_write, read_heartbeat,
)
from wayline.project import ProjectError, home, is_project, policy_for, read_active, read_harness, read_jobs
from wayline.resources import LIVE_JOB_STATUSES
from wayline.tickets import DECISION as DECISION_KIND
from wayline.tickets import (
    SATISFIED, frontier, is_open_decision, next_id, read_tickets, refresh_graph, relative_path, write_ticket,
)

__all__ = [
    "UnitError", "UnitsOff", "TICK_SERVICE", "TICK_TIMER", "DASHBOARD_SERVICE", "UNITS", "CONDUCTOR_UNIT",
    "UNITS_ENV", "ENV_FILE", "TOKEN_VARIABLE", "unit_directory", "stamp_path", "env_path", "unit_files",
    "install_units", "uninstall_units", "detach_argv", "launch_detached", "ensure_dashboard",
    "write_env_file", "offer_env_file", "use_fake_systemd", "FakeSystemd",
    "TICK_LOCK", "LOGIN_ORIGIN", "FINAL_ENDS", "Machine", "TickResult", "tick", "tick_command", "tick_lock",
    "check_login", "read_credentials", "login_expiry", "credentials_path", "read_usage", "poll_jobs", "due_checks",
    "render_report", "report_due", "due_notifications", "send_due_notifications", "owed_verdicts", "work_remaining",
    "window_closed", "fable_spent", "answered_since_end", "relaunch_decision", "relaunch", "pid_alive",
]

TICK_SERVICE = "wayline-tick.service"
TICK_TIMER = "wayline-tick.timer"
DASHBOARD_SERVICE = "wayline-dashboard.service"
UNITS = (TICK_SERVICE, TICK_TIMER, DASHBOARD_SERVICE)
# What `enable --now` starts: the timer fires the tick service, which nothing enables on its own.
ENABLED = (TICK_TIMER, DASHBOARD_SERVICE)
# Where `enable` links each enabled unit, from its `WantedBy=`.
WANTS = {TICK_TIMER: "timers.target.wants", DASHBOARD_SERVICE: "default.target.wants"}
CONDUCTOR_UNIT = "wayline-conductor"

UNITS_ENV = "WAYLINE_UNITS"
SYSTEMD = "systemd"
NONE = "none"

ENV_FILE = "env"
TICK_LOG = "tick.log"
TOKEN_VARIABLE = "CLAUDE_CODE_OAUTH_TOKEN"
SYSTEMCTL_TIMEOUT_S = 60
# The `ActiveState` values of a unit that is still doing something; any other loaded state is finished.
BUSY_STATES = ("active", "activating", "deactivating", "reloading", "refreshing")

# Decision 7's three units, with the placeholders the spec writes as <abs interpreter>, <abs harness
# dir>, and <abs home>/.wayline. `tests/test_units.py` compares them with the spec's block.
TICK_SERVICE_TEXT = """\
[Unit]
Description=wayline tick
[Service]
Type=oneshot
EnvironmentFile=-{state}/env
ExecStart={python} -m wayline tick
WorkingDirectory={harness}
RuntimeMaxSec=20min
StandardOutput=append:{state}/tick.log
StandardError=append:{state}/tick.log
"""

TICK_TIMER_TEXT = """\
[Unit]
Description=wayline tick timer
[Timer]
OnCalendar=*:0/15
Persistent=true
AccuracySec=1min
[Install]
WantedBy=timers.target
"""

DASHBOARD_SERVICE_TEXT = """\
[Unit]
Description=wayline dashboard
[Service]
EnvironmentFile=-{state}/env
ExecStart={python} -m wayline serve
WorkingDirectory={harness}
Restart=on-failure
[Install]
WantedBy=default.target
"""

ENV_EXPLAINED = (
    "The units can carry a one-year login token from `{command}` in {path} (mode 0600).\n"
    "Only the wayline units load it (the tick, the dashboard, a detached conductor); your shell never does,\n"
    "because the token outranks your /login everywhere it is set. Without it the units run on your /login."
)


class UnitError(ValueError):
    """A unit the manager refused, or a launch that would double a running conductor."""


class UnitsOff(UnitError):
    """`WAYLINE_UNITS=none`: this process does not reach the user manager."""


# --- where the units live -----------------------------------------------------------------------------


def unit_directory():
    """`~/.config/systemd/user`, where the user manager reads unit files (`$XDG_CONFIG_HOME` when set)."""
    if _FAKE is not None:
        return _FAKE.units
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "systemd" / "user"


def stamp_path():
    """The file `Persistent=true` keeps the timer's last elapse in (research-notes 05, R11)."""
    if _FAKE is not None:
        return _FAKE.stamps / ("stamp-" + TICK_TIMER)
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "systemd" / "timers" / ("stamp-" + TICK_TIMER)


def env_path():
    return home() / ENV_FILE


def unit_files(harness_root=None, interpreter=None, wayline_home=None):
    """The three unit files by name, with absolute paths for this harness checkout and interpreter."""
    python = os.path.abspath(interpreter or sys.executable)
    values = {
        "python": '"%s"' % python if any(character.isspace() for character in python) else python,
        "harness": os.path.abspath(harness_root or HARNESS_ROOT),
        "state": os.path.abspath(wayline_home or home()),
    }
    return {
        TICK_SERVICE: TICK_SERVICE_TEXT.format(**values),
        TICK_TIMER: TICK_TIMER_TEXT,
        DASHBOARD_SERVICE: DASHBOARD_SERVICE_TEXT.format(**values),
    }


# --- the manager ---------------------------------------------------------------------------------------


def _backend():
    if _FAKE is not None:
        return "fake"
    value = os.environ.get(UNITS_ENV) or SYSTEMD
    if value not in (SYSTEMD, NONE):
        raise UnitError("%s=%s names no backend; it is %s or %s" % (UNITS_ENV, value, SYSTEMD, NONE))
    return value


def units_off():
    return _backend() == NONE


def _execute(argv):
    """Run one `systemctl --user` or `systemd-run --user` command; a missing executable is exit 127."""
    if _backend() == NONE:
        raise UnitsOff("%s=%s: this process does not reach the user manager" % (UNITS_ENV, NONE))
    if _FAKE is not None:
        return _FAKE(list(argv))
    try:
        return subprocess.run(argv, capture_output=True, text=True, check=False, stdin=subprocess.DEVNULL,
                              timeout=SYSTEMCTL_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError) as failure:
        return subprocess.CompletedProcess(argv, 127, "", str(failure))


def systemctl(*args):
    return _execute(["systemctl", "--user", *args])


def _said(done):
    return (done.stderr or done.stdout or "").strip() or "no output"


def _spelled(argv):
    return " ".join(argv)


# --- install and uninstall -------------------------------------------------------------------------------


def install_units(harness_root=None, interpreter=None):
    """Write the three units where they differ, reload the manager, enable the timer and the dashboard.

    Returns `{"directory", "written", "enabled", "problems", "skipped"}`: `written` names the files this
    call changed, so a second install reports none, and `problems` carries every command the manager
    refused. A refusal is reported, not raised, because the project `init` laid out is still good.
    `skipped` is the reason nothing was done when the units are off.
    """
    report = {"directory": None, "written": [], "enabled": [], "problems": [], "skipped": None}
    if units_off():
        report["skipped"] = "%s=%s" % (UNITS_ENV, NONE)
        return report
    directory = unit_directory()
    report["directory"] = str(directory)
    state = home()
    # `StandardOutput=append:` needs the log's directory to exist when the tick first runs.
    state.mkdir(parents=True, exist_ok=True)
    directory.mkdir(parents=True, exist_ok=True)
    for name, text in unit_files(harness_root, interpreter, state).items():
        path = directory / name
        try:
            current = path.read_text(encoding="utf-8")
        except (OSError, ValueError):
            current = None
        if current != text:
            atomic_write(path, text)
            report["written"].append(name)
    for args in (("daemon-reload",), ("enable", "--now", *ENABLED)):
        done = systemctl(*args)
        if done.returncode != 0:
            report["problems"].append("systemctl --user %s exited %d: %s" % (_spelled(args), done.returncode, _said(done)))
        elif args[0] == "enable":
            report["enabled"] = list(ENABLED)
    return report


def uninstall_units():
    """Disable, stop, clean, and remove exactly the three units, and nothing else (decision 7).

    The manager's refusals are notes rather than failures: a unit that was never installed makes
    `disable` exit nonzero, and that is the state an uninstall wants. Whatever the manager could not
    do is still done on disk: the three files, the two `enable` links, and the timer's stamp.
    """
    report = {"directory": None, "removed": [], "notes": [], "skipped": None}
    if units_off():
        report["skipped"] = "%s=%s" % (UNITS_ENV, NONE)
        return report
    directory = unit_directory()
    report["directory"] = str(directory)
    for args in (("disable", "--now", *ENABLED), ("stop", TICK_SERVICE), ("clean", "--what=state", TICK_TIMER)):
        done = systemctl(*args)
        if done.returncode != 0:
            report["notes"].append("systemctl --user %s exited %d: %s" % (_spelled(args), done.returncode, _said(done)))
    for name in UNITS:
        path = directory / name
        if path.is_file() or path.is_symlink():
            path.unlink()
            report["removed"].append(name)
    for name, wants in WANTS.items():
        link = directory / wants / name
        if link.is_symlink():
            link.unlink()
            report["removed"].append("%s/%s" % (wants, name))
            # `enable` made the directory when the link was its first; `disable` removes it again when empty.
            if not any(link.parent.iterdir()):
                link.parent.rmdir()
    stamp = stamp_path()
    if stamp.exists():
        stamp.unlink()
        report["removed"].append(str(stamp))
    done = systemctl("daemon-reload")
    if done.returncode != 0:
        report["notes"].append("systemctl --user daemon-reload exited %d: %s" % (done.returncode, _said(done)))
    systemctl("reset-failed", *UNITS)  # errors ignored: a unit that is not failed is what we want
    return report


# --- the detached conductor --------------------------------------------------------------------------------


def detach_argv(project, run_args=(), harness_root=None, interpreter=None, environ=None):
    """The `systemd-run` line that starts `wayline run --resume` on `project` as `wayline-conductor`.

    The unit loads `~/.wayline/env` like the installed units do, and it carries `PATH` and every
    `WAYLINE_*` variable of the process that asked for it (the harness home, the launcher, the job
    backend), because a transient unit starts from the manager's environment, not the caller's.
    """
    environ = os.environ if environ is None else environ
    argv = [
        "systemd-run", "--user", "--unit=" + CONDUCTOR_UNIT,
        "-p", "WorkingDirectory=" + os.path.abspath(harness_root or HARNESS_ROOT),
        "-p", "EnvironmentFile=-" + str(Path(os.path.abspath(home())) / ENV_FILE),
        "--expand-environment=no",
    ]
    for key in sorted(environ):
        # PATH too: the manager's lacks `~/.local/bin`, where the executable workers run is installed.
        if key.startswith("WAYLINE_") or key == "PATH":
            argv += ["-E", "%s=%s" % (key, environ[key])]
    argv += [os.path.abspath(interpreter or sys.executable), "-m", "wayline", "run", "--resume",
             "--project", os.path.abspath(project), *run_args]
    return argv


def _show(unit):
    fields = {}
    for line in systemctl("show", unit, "-p", "LoadState,ActiveState,SubState").stdout.splitlines():
        key, _, value = line.partition("=")
        fields[key.strip()] = value.strip()
    return fields


def launch_detached(project, run_args=()):
    """Start the conductor on `project` as the transient unit; returns the `systemd-run` output.

    A unit of that name still running is refused, because a second conductor would only lose the
    heartbeat's lock. A finished one is reset first: without `--collect` a failed conductor stays
    loaded, and `systemd-run` refuses a loaded name.
    """
    unit = CONDUCTOR_UNIT + ".service"
    fields = _show(unit)
    if fields.get("LoadState") not in (None, "", "not-found"):
        if fields.get("ActiveState") in BUSY_STATES:
            raise UnitError("%s is already %s; systemctl --user status %s shows it, and wayline stop ends it"
                            % (unit, fields.get("ActiveState"), CONDUCTOR_UNIT))
        systemctl("reset-failed", unit)
    argv = detach_argv(project, run_args)
    done = _execute(argv)
    if done.returncode != 0:
        raise UnitError("systemd-run refused the conductor: %s" % _said(done))
    return (done.stdout or done.stderr or "").strip()


def ensure_dashboard():
    """Start `wayline-dashboard.service` unless it is active. Returns `(state, detail)`.

    `state` is `active` (left alone), `started`, `off` (the units are off here), or `failed` with
    what the manager said, which is usually that `init` has not installed the unit yet.
    """
    try:
        if systemctl("is-active", DASHBOARD_SERVICE).stdout.strip() == "active":
            return "active", ""
        done = systemctl("start", DASHBOARD_SERVICE)
    except UnitsOff as off:
        return "off", str(off)
    except UnitError as failure:  # an unknown WAYLINE_UNITS; the dashboard is a view and never fails a run
        return "failed", str(failure)
    if done.returncode == 0:
        return "started", ""
    return "failed", _said(done)


# --- the token file -----------------------------------------------------------------------------------------


def write_env_file(token, path=None):
    """Write `CLAUDE_CODE_OAUTH_TOKEN=<token>` to `~/.wayline/env`, 0600 from the first byte."""
    token = (token or "").strip()
    if not token or any(character.isspace() for character in token):
        raise UnitError("a setup token is one word with no spaces; nothing was written")
    path = Path(path) if path is not None else env_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        os.close(os.open(path, os.O_WRONLY | os.O_CREAT, 0o600))
    os.chmod(path, 0o600)
    atomic_write(path, "# loaded only by the wayline user units (EnvironmentFile=-); never source it in a shell\n"
                       "%s=%s\n" % (TOKEN_VARIABLE, token))
    return path


def offer_env_file(stream=None, out=None, setup_token=None, read_token=None):
    """At a terminal, with no token file yet, offer to write one from `claude setup-token`.

    Returns a note for `init` to print, or None when there is nothing to say. Away from a terminal
    nothing is asked, because `init` is also what scripts and the suite call.
    """
    path = env_path()
    if units_off() or path.exists():
        return None
    from wayline import worker  # the launcher module is the one place that names and starts the executable
    command = worker.setup_token_command()
    stream = stream if stream is not None else sys.stdin
    out = out if out is not None else sys.stdout
    if not (hasattr(stream, "isatty") and stream.isatty()):
        return "no %s: the units run on your /login; wayline init at a terminal offers to write one from %s" % (path, command)
    print(ENV_EXPLAINED.format(path=path, command=command), file=out)
    print("run %s and write the token there now? [y/N] " % command, end="", file=out, flush=True)
    try:
        answer = (stream.readline() or "").strip().lower()
    except (OSError, ValueError, KeyboardInterrupt):
        answer = ""
    if answer not in ("y", "yes"):
        return "no %s written; the units run on your /login" % path
    try:
        code = (setup_token or worker.setup_token)()
    except KeyboardInterrupt:
        return "%s interrupted; nothing written" % command
    except (OSError, ValueError) as failure:
        return "%s could not run (%s); nothing written" % (command, failure)
    if code != 0:
        return "%s exited %s; nothing written" % (command, code)
    try:
        token = (read_token or getpass.getpass)("paste the token it printed (not echoed): ")
        write_env_file(token, path)
    except (EOFError, KeyboardInterrupt):
        return "%s not written: cancelled" % path
    except (UnitError, OSError) as failure:
        return "%s not written: %s" % (path, failure)
    return "wrote %s (0600); the units load it from their next start" % path


# --- the fake manager (tests) ---------------------------------------------------------------------------------

_FAKE = None


class FakeSystemd:
    """A user manager in a directory: records every command and keeps the unit state they imply.

    `enable --now` links the units and starts them (the timer writes its stamp, as `Persistent=true`
    does), `disable --now` unlinks and stops them, `clean --what=state` removes the stamp, and
    `is-active` answers from that state. `answer(*prefix, ...)` scripts a reply for the commands that
    start with `prefix`, the latest script winning, which is how a refusal is simulated.
    """

    def __init__(self, root):
        self.root = Path(root)
        self.units = self.root / "config" / "systemd" / "user"
        self.stamps = self.root / "share" / "systemd" / "timers"
        self.calls = []
        self.active = set()
        self._answers = []

    def answer(self, *prefix, returncode=0, stdout="", stderr=""):
        self._answers.append((tuple(prefix), returncode, stdout, stderr))

    def commands(self, program="systemctl"):
        return [call for call in self.calls if call[0] == program]

    def __call__(self, argv):
        self.calls.append(argv)
        for prefix, returncode, stdout, stderr in reversed(self._answers):
            if tuple(argv[:len(prefix)]) == prefix:
                return subprocess.CompletedProcess(argv, returncode, stdout, stderr)
        return subprocess.CompletedProcess(argv, 0, self._simulate(argv), "")

    def _simulate(self, argv):
        if argv[:2] != ["systemctl", "--user"]:
            return "Running as unit: %s.service\n" % CONDUCTOR_UNIT
        verb, rest = argv[2], argv[3:]
        names = [name for name in rest if not name.startswith("-")]
        if verb == "enable":
            for name in names:
                link = self.units / WANTS[name] / name
                link.parent.mkdir(parents=True, exist_ok=True)
                if not link.is_symlink():
                    link.symlink_to(self.units / name)
                if "--now" in rest:
                    self._start(name)
        elif verb == "disable":
            for name in names:
                link = self.units / WANTS[name] / name
                if link.is_symlink():
                    link.unlink()
                if link.parent.is_dir() and not any(link.parent.iterdir()):
                    link.parent.rmdir()
                self.active.discard(name)
        elif verb == "start":
            self._start(names[0])
        elif verb == "stop":
            self.active.difference_update(names)
        elif verb == "clean":
            stamp = self.stamps / ("stamp-" + names[0])
            if stamp.exists():
                stamp.unlink()
        elif verb == "is-active":
            return "active\n" if names[0] in self.active else "inactive\n"
        elif verb == "show":
            return "LoadState=not-found\nActiveState=inactive\nSubState=dead\n"
        return ""

    def _start(self, name):
        self.active.add(name)
        if name == TICK_TIMER:
            self.stamps.mkdir(parents=True, exist_ok=True)
            (self.stamps / ("stamp-" + name)).touch()


@contextmanager
def use_fake_systemd(root):
    """Stand a `FakeSystemd` under `root` in for the user manager for the length of a block."""
    global _FAKE
    previous, _FAKE = _FAKE, FakeSystemd(root)
    try:
        yield _FAKE
    finally:
        _FAKE = previous


# --- the tick (ticket 14) ---------------------------------------------------------------------------------------

TICK_LOCK = "tick.lock"
CREDENTIALS_FILE = ".credentials.json"
DAY_S = 24 * 3600
LOGIN_WARNING_DAYS = 3  # `policy.tick.login_warning_days` as decision 14 ships it
HEARTBEAT_STALE_S = 300  # `policy.heartbeat_stale_s` as decision 14 ships it
AUTONOMOUS = "autonomous"

# How a tick ended, as `TickResult.ended` names it.
NO_PROJECT = "no_project"
LAPSED = "lapsed"
CONDUCTOR_ALIVE = "conductor_alive"
RELAUNCHED = "relaunched"
NOT_RELAUNCHED = "not_relaunched"

# The ends of a run that only an answer undoes: the owner stopped it, the goal was reached, a strict
# stall stopped it to report, or `switch` took the project away. A relaunch after one of them would
# undo, fifteen minutes later, the reason the run ended.
FINAL_ENDS = ("stopped", "goal_reached", "stall_strict", "switched")

# The login tickets the tick opens are told apart by their `origin`, which records the expiry it warned of.
LOGIN_ORIGIN = "tick: the login"
LAPSED_ORIGIN = LOGIN_ORIGIN + " lapsed"
_EXPIRES_RE = re.compile(r"expires at (\S+)\Z")

# The notification decision 7 calls "goal reached": the `run_ended` whose reason is `goal_reached`.
GOAL_REACHED = "goal_reached"


@dataclass
class Machine:
    """Everything the tick reads or starts outside the ledger. The defaults are this machine's; the tests pass fakes.

    `heartbeat(project)` reads `research/conductor.json`; `alive(pid)` asks the kernel; `credentials` is
    `~/.claude/.credentials.json` and `environ` is where a setup token would show; `poll_jobs`, `checks`,
    and `render` take the project; `notify(event, text, project, ticket)` reaches the owner; and
    `relaunch(project)` starts the conductor as `wayline-conductor`. `/usage` and `claude auth status` are
    not here: they go through the launcher seam (`wayline.worker`), whose fake the tests script.
    """

    clock: Callable[[], float] = time.time
    heartbeat: Optional[Callable] = None
    alive: Optional[Callable] = None
    credentials: Optional[Path] = None
    environ: Optional[dict] = None
    poll_jobs: Optional[Callable] = None
    checks: Optional[Callable] = None
    render: Optional[Callable] = None
    notify: Optional[Callable] = None
    relaunch: Optional[Callable] = None

    def __post_init__(self):
        self.heartbeat = self.heartbeat or read_heartbeat
        self.alive = self.alive or pid_alive
        self.credentials = credentials_path() if self.credentials is None else Path(self.credentials)
        self.environ = os.environ if self.environ is None else self.environ
        self.poll_jobs = self.poll_jobs or poll_jobs
        self.checks = self.checks or due_checks
        self.render = self.render or render_report
        self.notify = self.notify or send_notification
        self.relaunch = self.relaunch or relaunch


@dataclass
class TickResult:
    """What one tick did: the project, how it ended and why, and what each step came to."""

    project: Optional[str] = None
    ended: Optional[str] = None
    why: Optional[str] = None
    login: Optional[dict] = None
    pacing: Optional[dict] = None
    jobs: list = field(default_factory=list)
    checks: list = field(default_factory=list)
    report: Optional[str] = None
    notified: list = field(default_factory=list)
    relaunched: bool = False
    problems: list = field(default_factory=list)


def tick(project=None, machine=None, harness_root=None, out=None):
    """One tick over the active project, or over `project`: the tick contract of decision 7. Returns a `TickResult`.

    In order: the login; `/usage`; the heartbeat, stopping while the conductor is alive and has waved
    within `policy.heartbeat_stale_s`; then, whatever the window says, the jobs, the checks that are due,
    `REPORT.md`, and the notifications; last, the relaunch. A step that fails is said and kept in
    `problems`, and the steps after it still run, because a report that cannot render must not keep the
    conductor from its relaunch. A lapsed login polls the jobs and ends the tick: everything after that
    needs the subscription, or a conductor that could not run on it. The lock is `tick_command`'s.
    """
    machine = Machine() if machine is None else machine
    out = sys.stdout if out is None else out
    result = TickResult()
    now = machine.clock()

    def say(message):
        print(message, file=out, flush=True)

    def step(name, action):
        try:
            return action()
        except Exception as failure:  # one broken step must not stop the ones after it
            result.problems.append("%s: %s" % (name, failure))
            say("  %s failed: %s: %s" % (name, type(failure).__name__, failure))
            return None

    def end(ended, why):
        result.ended, result.why = ended, why
        say("  " + why)
        return result

    chosen = read_active() if project is None else Path(project)
    if chosen is None or not is_project(chosen):
        say("tick %s" % pacing.iso(now))
        return end(NO_PROJECT, "no active project; nothing to do" if chosen is None else "%s is not a project; nothing to do" % chosen)
    project = chosen.resolve()
    result.project = str(project)
    say("tick %s  %s" % (pacing.iso(now), project))
    ledger = Ledger(project)
    policy = step("policy", lambda: policy_for(project, harness_root)) or {}
    days = (policy.get("tick") or {}).get("login_warning_days", LOGIN_WARNING_DAYS)

    result.login = step("login", lambda: check_login(project, ledger, machine, now, days, say))
    if result.login is not None and result.login["lapsed"]:
        result.jobs = step("jobs", lambda: machine.poll_jobs(project)) or []
        _say_jobs(result.jobs, say)
        return end(LAPSED, "the login lapsed: the jobs were polled, and nothing that needs the subscription runs until it is renewed")

    result.pacing = step("usage", lambda: read_usage(project, ledger, policy, now, say))
    record = step("heartbeat", lambda: machine.heartbeat(project))
    record = record if isinstance(record, dict) else {}
    pid = record.get("pid")
    alive = isinstance(pid, int) and not isinstance(pid, bool) and bool(step("heartbeat", lambda: machine.alive(pid)))
    beat = pacing.epoch(record.get("last_wave_at") or record.get("started_at"))
    age = None if beat is None else now - beat
    stale_s = policy.get("heartbeat_stale_s", HEARTBEAT_STALE_S)
    if alive and age is not None and age < stale_s:
        return end(CONDUCTOR_ALIVE, "conductor pid %d is alive and waved %ds ago; it does the rest" % (pid, age))
    if alive:
        say("  conductor pid %d is alive but has not waved for %s (heartbeat_stale_s %s)"
            % (pid, "unknown" if age is None else "%ds" % age, stale_s))
    else:
        say("  no conductor is running%s" % ("" if pid is None else " (the heartbeat's pid %s is gone)" % pid))

    result.jobs = step("jobs", lambda: machine.poll_jobs(project)) or []
    _say_jobs(result.jobs, say)
    result.checks = step("checks", lambda: machine.checks(project)) or []
    for check in result.checks:
        say("  job %s (ticket %s): %s" % (check["job"], check["ticket"],
                                          "its outputs parse" if check["outputs_ok"] else "; ".join(check["problems"])))
    events = step("report", lambda: ledger.read_events()[0])
    if events is not None and report_due(events):
        result.report = step("report", lambda: machine.render(project))
        if result.report:
            say("  rendered %s" % result.report)
    result.notified = step("notifications", lambda: send_due_notifications(project, ledger, machine, now, say)) or []

    if alive:
        return end(NOT_RELAUNCHED, "not relaunched: conductor pid %d still holds the project (systemctl --user status %s, or wayline stop)"
                   % (pid, CONDUCTOR_UNIT))
    decided = step("relaunch", lambda: relaunch_decision(project, ledger, policy, result.pacing, now))
    if decided is None:
        return end(NOT_RELAUNCHED, "not relaunched: whether to relaunch could not be decided")
    reason, why = decided
    if reason is None:
        return end(NOT_RELAUNCHED, "not relaunched: " + why)
    try:
        said = machine.relaunch(project)
    except Exception as failure:  # the units are off, the manager refused, or the run would refuse to start
        result.problems.append("relaunch: %s" % failure)
        return end(NOT_RELAUNCHED, "not relaunched although %s: %s" % (reason, failure))
    result.relaunched = True
    return end(RELAUNCHED, "relaunched %s: %s%s" % (CONDUCTOR_UNIT, reason, "  (%s)" % said if said else ""))


def _say_jobs(jobs, say):
    for job in jobs:
        say("  job %s (ticket %s): %s%s" % (job["job"], job["ticket"], job["now"],
                                           "" if job["now"] == job["was"] else ", was %s" % job["was"]))


def _ts(seconds):
    """An epoch second as the journal spells a timestamp, so the events a tick writes agree with its clock."""
    return pacing.iso(seconds).replace("Z", ".000Z")


def _harness(project):
    try:
        return read_harness(project)
    except (ProjectError, ValueError, OSError):
        return {}


def thresholds_for(project, policy, view):
    """`(stop_at, cheap_at)` as the conductor paces by them: `policy.pacing`, `harness.json`'s, then a `control pacing` event's."""
    return pacing.thresholds(policy.get("pacing"), _harness(project).get("pacing"), view.thresholds)


# --- the login ---


def credentials_path():
    """`~/.claude/.credentials.json`, where Claude Code keeps the `/login` credential on Linux (research-notes 02)."""
    base = os.environ.get("CLAUDE_CONFIG_DIR")
    return (Path(base).expanduser() if base else Path.home() / ".claude") / CREDENTIALS_FILE


def read_credentials(path):
    """`claudeAiOauth` from the credentials file, or None when there is none to read."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    oauth = data.get("claudeAiOauth") if isinstance(data, dict) else None
    return oauth if isinstance(oauth, dict) else None


def login_expiry(oauth):
    """When the stored login ends, in epoch seconds: the later of `expiresAt` and `refreshTokenExpiresAt` (milliseconds); None when neither is there."""
    values = [(oauth or {}).get(key) for key in ("expiresAt", "refreshTokenExpiresAt")]
    seconds = [value / 1000 for value in values if isinstance(value, (int, float)) and not isinstance(value, bool)]
    return max(seconds) if seconds else None


def check_login(project, ledger, machine, now, warning_days, say):
    """The login check of decision 7: `claude auth status`, then when the stored login ends. Returns what it found.

    The stored login lasts as long as its longest-lived credential. `expiresAt` is the access token's,
    which Claude Code refreshes by itself every few hours; `refreshTokenExpiresAt` is the refresh token's,
    which only `/login` renews. So the later of the two is when the login ends, and a `human_only` decision
    ticket asks the owner to sign in again once that is `warning_days` away or past. Units that load
    `CLAUDE_CODE_OAUTH_TOKEN` from `~/.wayline/env` run on that one-year token, which outranks the stored
    login (research-notes 02), so the file says nothing about them and only `auth status` is read.

    Returns `{"logged_in", "expires_at", "token", "lapsed", "ticket"}`: `logged_in` is None when `auth status`
    could not say, and `lapsed` is True when it said there is no login or the stored login has ended.
    """
    from wayline import worker  # the launcher module is the one place that runs the executable
    token = bool(machine.environ.get(TOKEN_VARIABLE))
    try:
        status = worker.auth_status()
    except worker.LaunchError as failure:
        status = None
        say("  login: %s could not run (%s)" % (worker.auth_status_command(), failure))
    logged_in = bool(status.get("logged_in")) if isinstance(status, dict) else None
    expiry = None if token else login_expiry(read_credentials(machine.credentials))
    lapsed = logged_in is False or (expiry is not None and expiry <= now)
    login = {"logged_in": logged_in, "expires_at": expiry, "token": token, "lapsed": lapsed, "ticket": None}
    if lapsed or (expiry is not None and expiry - now <= warning_days * DAY_S):
        login["ticket"] = open_login_ticket(project, ledger, machine, now, expiry, logged_in is False, warning_days, say)
    elif expiry is not None:
        say("  login: the stored login ends at %s, in %.1f days" % (pacing.iso(expiry), (expiry - now) / DAY_S))
    elif token:
        say("  login: the units run on the setup token in %s" % env_path())
    else:
        say("  login: %s" % ("logged in; no expiry could be read" if logged_in else "nothing could be read"))
    return login


def open_login_ticket(project, ledger, machine, now, expiry, logged_out, warning_days, say):
    """Open the `human_only` decision ticket that asks the owner to sign in again, and notify them; its id, or None.

    One ticket asks at a time, so an open login ticket is left to ask. A warning is not asked again for
    the same login: a closed ticket that warned of an expiry within `warning_days` of this one was
    answered. A lapse is asked again at most every `warning_days` while the login stays lapsed. The owner
    is notified here rather than at the tick's notification step, which a live conductor keeps the tick
    from reaching; the notifier's claim keeps that step from sending it twice.
    """
    from wayline import worker  # the launcher module names the executable's commands
    lapsed = logged_out or (expiry is not None and expiry <= now)
    window = warning_days * DAY_S
    if logged_out:
        summary, origin = "%s reports no login" % worker.auth_status_command(), LAPSED_ORIGIN + " (auth status reports no login)"
    elif lapsed:
        summary, origin = "the login ended at %s" % pacing.iso(expiry), "%s at %s" % (LAPSED_ORIGIN, pacing.iso(expiry))
    else:
        summary = "the login ends in %.1f days, at %s" % ((expiry - now) / DAY_S, pacing.iso(expiry))
        origin = "%s expires at %s" % (LOGIN_ORIGIN, pacing.iso(expiry))
    asked = [ticket for ticket in read_tickets(project)
             if ticket["kind"] == DECISION_KIND and str(ticket.get("origin") or "").startswith(LOGIN_ORIGIN)]
    for ticket in asked:
        if ticket["status"] not in SATISFIED + ("parked",):
            say("  login: %s; ticket %d already asks the owner to sign in again" % (summary, ticket["id"]))
            return ticket["id"]
    if lapsed:
        opened = _opened_at(ledger)
        recent = [ticket["id"] for ticket in asked
                  if ticket["origin"].startswith(LAPSED_ORIGIN) and now - opened.get(ticket["id"], float("-inf")) < window]
        if recent:
            say("  login: %s; ticket %d asked less than %s days ago and was answered" % (summary, recent[-1], warning_days))
            return None
    else:
        for ticket in asked:
            match = _EXPIRES_RE.search(ticket["origin"])
            warned = pacing.epoch(match.group(1)) if match else None
            if warned is not None and abs(warned - expiry) < window:
                say("  login: %s; ticket %d warned of it and was answered" % (summary, ticket["id"]))
                return None
    identifier = next_id(project)
    fields = {
        "id": identifier, "title": "Sign in again: the login lapsed" if lapsed else "Renew the login before it ends",
        "kind": DECISION_KIND, "difficulty": 1, "status": "open", "blocked_by": [], "blocking": None, "human_only": True,
        "touches": [], "role": "decider", "acceptance": {}, "proposed_by": "tick", "context_pack": [], "origin": origin,
        "demo": "Run %s on the workstation, check %s, then wayline answer %d \"renewed\"."
                % (worker.login_command(), worker.auth_status_command(), identifier),
    }
    later = ("the tick asks again in %s days while the login stays lapsed" % warning_days if lapsed
             else "the tick asks again once the login lapses")
    body = (
        "## Decision\n\n%s. Every session the harness launches needs the login: once it ends, the workers, the "
        "verdicts, and the decider fail until someone signs in again.\n\n"
        "Options:\n\n"
        "- `renewed`: you ran `%s` on the workstation, or wrote a token from `%s` into %s.\n"
        "- `later`: %s.\n\n"
        "Recommended: `renewed`, once `%s` reports the login.\n\n"
        "Answer with `wayline answer %d \"renewed\"`. Only the owner answers it: the decider runs on the same login.\n"
    ) % (summary[0].upper() + summary[1:], worker.login_command(), worker.setup_token_command(), env_path(), later,
         worker.auth_status_command(), identifier)
    write_ticket(ledger, fields, body)
    ledger.append_event(TICKET_CREATED, {"ticket": identifier, "kind": DECISION_KIND, "proposed_by": "tick", "origin": origin,
                                         "blocked_by": []}, ticket=identifier, ts=_ts(now))
    ledger.append_event(DECISION_OPENED, {"ticket": identifier, "blocking": None, "human_only": True}, ticket=identifier, ts=_ts(now))
    machine.notify(DECISION_OPENED, "%s: ticket %d (human only): %s. Sign in again on the workstation with %s, then "
                   "wayline answer %d \"renewed\"" % (project.name, identifier, summary, worker.login_command(), identifier),
                   project, identifier)
    say("  login: %s; opened ticket %d and notified the owner" % (summary, identifier))
    return identifier


def _opened_at(ledger):
    """When each ticket was created, in epoch seconds, as its `ticket_created` says."""
    events, _ = ledger.read_events()
    return {(event.get("payload") or {}).get("ticket"): pacing.epoch(event.get("ts"))
            for event in events if event.get("event") == TICKET_CREATED and pacing.epoch(event.get("ts")) is not None}


# --- the window ---


def read_usage(project, ledger, policy, now, say):
    """`claude -p "/usage"` through the launcher seam, its Fable line included, with `pacing` journaled when the reading changed.

    Returns the reading (`five_hour`, `seven_day`, `fable`, `action`), or None when `/usage` gave none. The
    action is the conductor's, from the all-models windows under the project's thresholds; a conductor
    running or relaunched takes the event in as a reading taken when it was journaled.
    """
    from wayline import worker  # the launcher module is the one place that runs the executable
    try:
        text = worker.usage()
    except worker.LaunchError as failure:
        say("  usage: /usage could not be read (%s)" % failure)
        return None
    usage = pacing.parse_usage(text, now) if text is not None else None
    if usage is None:
        say("  usage: %s" % ("/usage printed none of the windows" if text is not None else "no reading"))
        return None
    events, _ = ledger.read_events()
    view = replay.replay(events)
    stop_at, cheap_at = thresholds_for(project, policy, view)
    known = usage.five_hour is not None or usage.seven_day is not None
    action = pacing.action_for(usage.five_hour, usage.seven_day, stop_at, cheap_at) if known else view.pacing["action"]
    reading = {"five_hour": usage.five_hour, "seven_day": usage.seven_day, "fable": usage.fable, "action": action}
    changed = reading != view.pacing
    if changed:
        ledger.append_event(PACING, reading, ts=_ts(now))
    say("  usage: five_hour %s, seven_day %s, fable %s: %s%s"
        % (usage.five_hour, usage.seven_day, usage.fable, action, "; journaled pacing" if changed else ""))
    return reading


def window_closed(view, reading, stop_at, now):
    """Why the windows every model draws on keep a conductor from launching, or None when they are open.

    The freshest word wins. The tick's own `/usage` reading of both windows under `stop_at` opens them,
    even before a pause's `resets_at` (which is now plus five hours when no signal named the reset), and a
    reading at or above `stop_at` keeps them closed, since a conductor started then would launch nothing
    that needs a model. Without a reading the pause decides: open once its `resets_at` has passed.
    """
    readings = [reading.get(name) for name in pacing.WINDOWS if reading.get(name) is not None] if reading else []
    if readings:
        return None if max(readings) < stop_at else "/usage reads %s, at or above stop_at %s" % (max(readings), stop_at)
    resets = pacing.epoch((view.pause or {}).get("resets_at"))
    if view.pause is not None and resets is not None and resets > now:
        return "the run is paused until %s" % view.pause.get("resets_at")
    return None


def fable_spent(view, reading, stop_at, now):
    """Whether Fable's weekly window is still spent: the tick's reading of the Fable line of `/usage` first, else the hold's `resets_at`."""
    fable = reading.get(pacing.FABLE) if reading else None
    if fable is not None:
        return fable >= stop_at
    resets = pacing.epoch((view.hold or {}).get("resets_at"))
    return view.hold is not None and resets is not None and resets > now


# --- jobs, checks, the report, the notifications ---


def poll_jobs(project):
    """Poll every job the ledger calls running through the job runner, which writes what it reads into `jobs/<id>.json`.

    Returns `{"job", "ticket", "was", "now"}` per job polled. Nothing is journaled here: `job_finished`,
    `job_retried`, and `job_failed` are the conductor's, which alone registers the outputs and steps the
    retry ladder (ticket 19). A `pending` job was never launched and has nothing to poll.
    """
    jobs, _ = read_jobs(project)
    running = [job for job in jobs if job["status"] == "running"]
    if not running:
        return []
    from wayline import resources  # the runner asks the user manager for its backend only when there is a job to poll
    runner = resources.JobRunner(project)
    polled = []
    for job in running:
        state = runner.poll(resources.handle_for(job))
        polled.append({"job": job["id"], "ticket": job["ticket"], "was": job["status"], "now": state.name})
    return polled


def due_checks(project):
    """The output check of decision 6 on every job that exited 0 while its ticket still runs: each expected output exists and parses.

    Returns `{"job", "ticket", "outputs_ok", "problems"}` per job checked. The conductor's wave closes the
    ticket, checking again, registering the outputs, and journaling `job_finished` (ticket 19); until one
    does, the tick's log says whether a finished job left what its ticket expects.
    """
    jobs, _ = read_jobs(project)
    running = {ticket["id"] for ticket in read_tickets(project) if ticket["status"] == "running"}
    checked = []
    for job in jobs:
        attempts = job.get("attempts") or []
        if job["status"] != "exited" or not attempts or attempts[-1].get("exit_code") != 0 or job["ticket"] not in running:
            continue
        problems = [problem for problem in (output_problem(job["cwd"], output) for output in job.get("expected_outputs") or [])
                    if problem is not None]
        checked.append({"job": job["id"], "ticket": job["ticket"], "outputs_ok": not problems, "problems": problems})
    return checked


def output_problem(cwd, output):
    """What is wrong with one expected output: missing, or not parsing as the JSON or CSV its name says. None when nothing is."""
    path = Path(output) if os.path.isabs(output) else Path(cwd) / output
    if not path.is_file():
        return "%s is missing" % output
    try:
        if path.suffix.lower() == ".json":
            with open(path, encoding="utf-8") as handle:
                json.load(handle)
        elif path.suffix.lower() == ".csv":
            with open(path, newline="", encoding="utf-8") as handle:
                if next(csv.reader(handle), None) is None:
                    return "%s is an empty CSV" % output
    except (OSError, ValueError, csv.Error) as failure:
        return "%s does not parse: %s" % (output, failure)
    return None


def report_due(events):
    """Whether the journal gained anything since `REPORT.md` was last rendered, beside the notifications and the render itself."""
    last = max((index for index, event in enumerate(events) if event.get("event") == REPORT_RENDERED), default=-1)
    return any(event.get("event") not in (NOTIFIED, REPORT_RENDERED) for event in events[last + 1:])


def render_report(project):
    """`REPORT.md` rendered from the ledger and linted, launching no session (`wayline report --offline`, ticket 40); its path."""
    from wayline import provenance  # the report pulls in the gates and the launcher
    return str(provenance.render_report(project, offline=True).path)


def send_notification(event, text, project, ticket):
    """The notifier of decision 7 (`wayline.notify.notify`), which journals its claim before any channel runs."""
    from wayline import notify
    return notify.notify(event, text, project=project, ticket=ticket)


def send_due_notifications(project, ledger, machine, now, say):
    """Send every notification `due_notifications` finds through `machine.notify`; returns what was sent and how it went."""
    events, _ = ledger.read_events()
    view = replay.replay(events)
    graph, _ = refresh_graph(project, ledger=ledger, events=events, write=False)
    titles = {ticket["id"]: ticket["title"] for ticket in read_tickets(project)}
    sent = []
    for event, ticket, text in due_notifications(project.name, events, graph, view, titles, now):
        outcome = machine.notify(event, text, project, ticket) or {}
        sent.append({"event": event, "ticket": ticket, "channel": outcome.get("channel"), "ok": outcome.get("ok")})
        say("  notified %s%s: %s through %s" % (event, "" if ticket is None else " (ticket %d)" % ticket,
                                                 "delivered" if outcome.get("ok") else "not delivered", outcome.get("channel")))
    return sent


def due_notifications(name, events, graph, view, titles, now):
    """The notifications the owner is owed: `(event, ticket, text)` for each event of decision 7 that still stands and was never claimed.

    The events are `decision_opened`, `ticket_needs_human`, a `paused` of the run, and the last
    `run_ended` (`goal_reached` when that was its reason); the login's expiry is its ticket's
    `decision_opened`. A `notified` for the same event and ticket after it is the notifier's claim, final
    even when no channel delivered, so a failing channel costs one message and not one every tick (ticket
    13). What no longer stands is not sent late: a decision answered since, a ticket that no longer needs a
    human, a pause that has ended, a run started again. The hold on Fable's weekly window pauses no run and
    is not sent; under consent `ask` its decision ticket is. `name` is the project's, which starts each text.
    """
    entries = {entry["id"]: entry for entry in graph["tickets"]}
    claimed, latest = {}, {}
    started = ended = None
    for index, event in enumerate(events):
        kind, payload = event.get("event"), event.get("payload") or {}
        ticket = payload.get("ticket", event.get("ticket"))
        if kind == NOTIFIED:
            claimed[(payload.get("event"), event.get("ticket"))] = index
        elif kind in (DECISION_OPENED, TICKET_NEEDS_HUMAN) and isinstance(ticket, int):
            latest[(kind, ticket)] = (index, payload)
        elif kind == PAUSED and payload.get("model") is None:
            latest[(PAUSED, None)] = (index, payload)
        elif kind == RUN_STARTED:
            started = index
        elif kind == RUN_ENDED:
            ended = (index, payload)
    if ended is not None and (started is None or started < ended[0]):
        latest[(GOAL_REACHED if ended[1].get("reason") == GOAL_REACHED else RUN_ENDED, None)] = ended
    due = []
    for (kind, ticket), (index, payload) in latest.items():
        if claimed.get((kind, ticket), -1) > index:
            continue
        text = _notification(kind, ticket, payload, entries.get(ticket), titles.get(ticket), view, now)
        if text is not None:
            due.append((index, kind, ticket, "%s: %s" % (name, text)))
    return [(kind, ticket, text) for _, kind, ticket, text in sorted(due, key=lambda item: item[0])]


def _notification(kind, ticket, payload, entry, title, view, now):
    """The text of one notification, or None when what it would say no longer stands."""
    if kind == DECISION_OPENED:
        if entry is None or not is_open_decision(entry):
            return None
        return "ticket %d asks: %s%s; wayline answer %d \"<answer>\"" % (
            ticket, title or "a decision", " (human only)" if entry.get("human_only") else "", ticket)
    if kind == TICKET_NEEDS_HUMAN:
        if entry is None or entry["status"] != "needs_human":
            return None
        return "ticket %d needs a human: %s" % (ticket, payload.get("question") or title or "its ticket file says why")
    if kind == PAUSED:
        resets = pacing.epoch((view.pause or {}).get("resets_at"))
        if view.pause is None or resets is None or resets <= now:
            return None
        return "the run is paused on the %s window until %s; running workers finish and nothing that needs a model starts" % (
            view.pause.get("window") or "unknown", view.pause.get("resets_at"))
    if kind == GOAL_REACHED:
        return "the goal is reached and the run ended"
    return "the run ended (%s); wayline status shows what is left" % (payload.get("reason") or "no reason given")


# --- the relaunch ---


def owed_verdicts(project, graph, view, policy):
    """Every done ticket owed a verdict no conductor took, and whether one of its verdicts runs on Fable.

    The rule is `Conductor._requeue_verdicts`': the verdicts a done ticket earned (`gates.ticket_asks`)
    less the ones the journal holds as passed. A ticket any of whose verdicts runs on Fable waits whole
    while Fable is spent, as the conductor holds it. Returns `{"ticket", "on_fable"}` per ticket.
    """
    from wayline import gates  # the gates import the launcher, which `init` does not need
    fields = {ticket["id"]: ticket for ticket in read_tickets(project)}
    owed = []
    for entry in graph["tickets"]:
        known = view.tickets.get(entry["id"])
        launched = known.latest if known is not None else None
        if entry["status"] != "done" or launched is None or not launched.model or entry["id"] not in fields:
            continue
        ticket = fields[entry["id"]]
        earned = gates.ticket_asks(ticket, entry.get("difficulty", ticket["difficulty"]), launched.model, relative_path(ticket),
                                   commit=view.integrated.get(entry["id"]), outputs=ticket.get("outputs") or [])
        passed = {item["verdict_type"] for item in view.verdicts.get(entry["id"], []) if item.get("pass")}
        asks = [ask for ask in earned if ask.verdict_type not in passed]
        if asks:
            owed.append({"ticket": entry["id"], "on_fable": any(_verifies_on_fable(gates, policy, ask) for ask in asks)})
    return owed


def _verifies_on_fable(gates, policy, ask):
    try:
        return gates.verifier_tier(policy, ask.author_model)[0] == pacing.FABLE
    except gates.GateError:
        return False  # the gate refuses the table by name when the verdict is taken


def work_remaining(project, graph, view, policy, fable_is_spent, autonomy):
    """What a relaunched conductor would find to do, as phrases, and what waits on Fable instead (None when nothing does).

    Work is a ticket on the frontier, a running ticket (a worker to re-adopt or a result to carry), a job
    the ledger calls live, or a done ticket owed a verdict. A decision ticket on the frontier is work only
    when the decider may take it, not `human_only` and under `autonomous`; the others wait for the owner,
    whose answer relaunches the conductor. A verdict queue that waits only on Fable is work once Fable's
    weekly window has reset (decision 15); until then a conductor would hold all of it.
    """
    work = []
    ready = [entry for entry in frontier(graph)
             if entry["kind"] != DECISION_KIND or (autonomy == AUTONOMOUS and not entry.get("human_only"))]
    if ready:
        work.append("%d ticket(s) on the frontier" % len(ready))
    running = [entry for entry in graph["tickets"] if entry["status"] == "running"]
    if running:
        work.append("%d ticket(s) running" % len(running))
    jobs, _ = read_jobs(project)
    live = [job for job in jobs if job["status"] in LIVE_JOB_STATUSES]
    if live:
        work.append("%d job(s) live" % len(live))
    owed = owed_verdicts(project, graph, view, policy)
    waiting = None
    if owed and fable_is_spent and all(item["on_fable"] for item in owed):
        waiting = "%d ticket(s) wait for a verdict on Fable, whose weekly window is spent" % len(owed)
    elif owed:
        work.append("%d ticket(s) owed a verdict" % len(owed))
    return work, waiting


def answered_since_end(events):
    """Whether a `decision` was journaled after the last `run_ended` or `paused`."""
    boundary = max((index for index, event in enumerate(events) if event.get("event") in (RUN_ENDED, PAUSED)), default=-1)
    return any(event.get("event") == DECISION for event in events[boundary + 1:])


def relaunch_decision(project, ledger, policy, reading, now):
    """`(reason, None)` when the conductor is to be relaunched, else `(None, why not)`: the last step of the tick contract.

    A `decision` journaled after the last `run_ended` or `paused` relaunches it, since applying an answer
    needs no model. Otherwise it is relaunched when work remains (`work_remaining`) and the window is open
    (`window_closed`). A project never run is the owner's to start, and a run that ended for one of
    `FINAL_ENDS` is relaunched only by an answer.
    """
    events, _ = ledger.read_events()
    view = replay.replay(events)
    if view.run is None:
        return None, "the project has never been run; wayline run starts it"
    if answered_since_end(events):
        return "a decision was answered after the run last ended or paused", None
    if view.run.get("ended") in FINAL_ENDS:
        return None, "the last run ended %s, which only an answer or the owner undoes" % view.run["ended"]
    graph, _ = refresh_graph(project, ledger=ledger, events=events, write=False)
    stop_at, _ = thresholds_for(project, policy, view)
    autonomy = view.autonomy or _harness(project).get("autonomy")
    work, waiting = work_remaining(project, graph, view, policy, fable_spent(view, reading, stop_at, now), autonomy)
    if not work:
        return None, "no work remains" + ("; " + waiting if waiting else "")
    closed = window_closed(view, reading, stop_at, now)
    if closed is not None:
        return None, "%s, but %s" % (", ".join(work), closed)
    return "%s, and the window is open" % ", ".join(work), None


def relaunch(project):
    """Start `wayline run --resume` on the project as `wayline-conductor`, unless the run would refuse to start."""
    from wayline import conductor  # the conductor imports this module
    problems = conductor.refuse_to_start(project)
    if problems:
        raise UnitError("the conductor would refuse to start: " + "; ".join(problems))
    return launch_detached(project)


def pid_alive(pid):
    """Whether a process with this pid exists: the heartbeat's pid, as decision 7 reads it."""
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OverflowError, ValueError):
        return False
    return True


# --- the verb ---


@contextmanager
def tick_lock(path=None):
    """`flock -n ~/.wayline/tick.lock` for a block: yields True when this process holds it, False when another tick does.

    The timer never starts a second tick while one is running (a oneshot unit that is still active is
    not started again); the lock covers a tick run by hand beside it.
    """
    path = Path(path) if path is not None else home() / TICK_LOCK
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        yield True
    finally:
        os.close(fd)


def tick_command(args):
    """`wayline tick [--project <path>]`: one tick, unless another holds the lock. Exit 1 when a step failed."""
    from wayline.cli import parse_args
    parser = argparse.ArgumentParser(prog="wayline tick", description="one tick of the recurrent job: the login, /usage, "
                                     "the heartbeat, the jobs, the due checks, REPORT.md, the notifications, and the relaunch")
    parser.add_argument("--project", help="tick this project rather than the active one")
    options, code = parse_args(parser, args)
    if options is None:
        return code
    with tick_lock() as held:
        if not held:
            print("tick %s  another tick holds %s; this one exits" % (pacing.iso(time.time()), home() / TICK_LOCK), flush=True)
            return 0
        result = tick(project=options.project)
    return 1 if result.problems else 0
