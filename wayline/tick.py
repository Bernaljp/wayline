"""The tick's machinery (Implementation Decisions 7): the user units, the detached conductor, the token file.

Ticket 13 builds what the tick runs under and how the conductor leaves the shell; the tick itself,
`wayline tick`, is ticket 14, and it relaunches the conductor through `launch_detached` here.

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

import getpass
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

from wayline import HARNESS_ROOT
from wayline.ledger import atomic_write
from wayline.project import home

__all__ = [
    "UnitError", "UnitsOff", "TICK_SERVICE", "TICK_TIMER", "DASHBOARD_SERVICE", "UNITS", "CONDUCTOR_UNIT",
    "UNITS_ENV", "ENV_FILE", "TOKEN_VARIABLE", "unit_directory", "stamp_path", "env_path", "unit_files",
    "install_units", "uninstall_units", "detach_argv", "launch_detached", "ensure_dashboard",
    "write_env_file", "offer_env_file", "use_fake_systemd", "FakeSystemd",
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
