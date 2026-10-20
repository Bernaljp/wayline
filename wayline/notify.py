"""The notifier (Implementation Decisions 7): one function that reaches the owner and never raises.

`notify(event, text)` journals `notified` before it tries any channel, with the channel, `ok`, and
the exit code still null. That first line is the claim: whoever decides which notifications are
due (the tick, ticket 14) sees it even when a channel hangs or the process dies mid-send, so a
failing channel costs one missed message rather than a message every fifteen minutes. Then it runs
`notify-send`, which reaches a desktop session when one is logged in; on a nonzero exit, and when
`harness.json.notify.hermes_python` names an interpreter, it runs `hermes send` to Telegram, which
is how the owner's phone is reached (research-notes 05, A7). A second `notified` records how it
went: the channel whose exit code it carries (the last one that ran), `ok`, and that exit code,
null when the channel timed out. `channel: none` means no channel could run at all.

wayline does not depend on hermes and ships no Telegram sender: the interpreter is whatever `init`
detected, and without one the notifier stops at `notify-send`.

**What the autonomy holds back** (decision 17; ticket 89). After setup, under `interactive`, every notice reaches
the owner as it arises; under `checkpoints`, a decision ticket notifies as it opens and every other notice waits
for the next conversation or the end notice; under `autonomous`, only the end notice of a run and the login's
expiry notify. `holds` is that rule, which the tick applies too; a notice it holds is neither sent nor journaled,
and the end notice's "M waiting on you" carries it.

`WAYLINE_NOTIFY=none` keeps every channel off: both `notified` lines are journaled as always, the
second with `channel: none`, and nothing reaches a desktop or a phone. The test suite sets it, as it
sets `WAYLINE_UNITS=none`, because the conductor notifies as it opens a decision ticket (ticket 35)
and a test project laid out by `init` may carry the owner's own hermes interpreter.
"""

import json
import logging
import os
import subprocess
from pathlib import Path

from wayline.ledger import NOTIFIED, Ledger
from wayline.project import HARNESS_JSON, is_project, read_active

__all__ = ["notify", "holds", "held_back", "END_NOTICES", "notify_send_argv", "hermes_argv", "NOTIFY_SEND", "HERMES", "NO_CHANNEL"]

_log = logging.getLogger("wayline.notify")

NOTIFY_SEND = "notify-send"
HERMES = "hermes"
NO_CHANNEL = "none"
APP_NAME = "wayline"
SUBJECT = "[wayline]"
# `notify-send` answers at once or not at all; `hermes send` goes over the network to Telegram.
NOTIFY_SEND_TIMEOUT_S = 15
HERMES_TIMEOUT_S = 120
# The variable that turns every channel off (`none`); a `run` passed in is a test's own channel and still runs.
NOTIFY_ENV = "WAYLINE_NOTIFY"


# The notices a run's end sends, one per end: `run_ended`, and `goal_reached` when that was its reason (decision 7).
END_NOTICES = ("run_ended", "goal_reached")
DECISION_OPENED = "decision_opened"
LOGIN_ORIGIN = "tick: the login"  # the origin of the tick's login tickets (`tick.LOGIN_ORIGIN`)


def holds(event, autonomy, setup_ended, login=False):
    """Whether the autonomy holds this notice back rather than sending it as it arises (decision 17).

    Nothing is held before setup ends, and the end notice never is. `login` says a `decision_opened` is the tick's
    ticket about the login's expiry, which notifies under every autonomy.
    """
    if not setup_ended or event in END_NOTICES:
        return False
    if autonomy == "autonomous":
        return not (event == DECISION_OPENED and login)
    if autonomy == "checkpoints":
        return event != DECISION_OPENED
    return False


def held_back(project, event, ticket=None, events=None):
    """`holds` for one notice of a project, read from its `harness.json`, its journal, and the ticket it is about.

    Anything that cannot be read holds nothing back: a notice sent that could have waited costs one message, and one
    held that should have gone out costs the owner the news.
    """
    try:
        from wayline.stopping import setup_ended_at  # the stopping module imports the goal module, which imports the gates
        autonomy = json.loads((Path(project) / HARNESS_JSON).read_text(encoding="utf-8")).get("autonomy")
        if events is None:
            events, _ = Ledger(project).read_events()
        login = False
        if event == DECISION_OPENED and ticket is not None:
            from wayline.tickets import read_tickets
            origin = {fields["id"]: fields for fields in read_tickets(project)}.get(ticket, {}).get("origin")
            login = str(origin or "").startswith(LOGIN_ORIGIN)
        return holds(event, autonomy, setup_ended_at(events) is not None, login)
    except Exception:  # the notifier never raises, and neither does what it asks first
        _log.exception("could not read what holds %r back", event)
        return False


def notify_send_argv(summary, body):
    return [NOTIFY_SEND, "-a", APP_NAME, "-u", "normal", summary, body]


def hermes_argv(hermes_python, text):
    return [hermes_python, "-m", "hermes_cli.main", "send", "--to", "telegram", "--subject", SUBJECT, text]


def notify(event, text, project=None, ticket=None, run=None):
    """Tell the owner that `event` happened, in `text`. Returns what happened; never raises.

    `project` is the project whose journal records it, the active one by default; with none, the
    owner is still notified and nothing is journaled. `run(argv, timeout)` stands in for
    `subprocess.run` in tests. The result is `{"event", "channel", "ok", "exit_code", "journaled"}`.
    With `WAYLINE_NOTIFY=none` and no `run`, no channel is tried.
    """
    outcome = {"event": event, "channel": NO_CHANNEL, "ok": False, "exit_code": None, "journaled": False}
    try:
        project = _project(project)
        if project is not None and held_back(project, event, ticket):
            outcome["held"] = True  # the autonomy keeps it for the next conversation or the end notice
            return outcome
        ledger = _ledger(project)
        outcome["journaled"] = _journal(ledger, {"event": event, "channel": None, "ok": None, "exit_code": None}, ticket)
        name = " (%s)" % project.name if project is not None else ""
        attempts = [(NOTIFY_SEND, notify_send_argv("wayline: %s%s" % (event, name), str(text)), NOTIFY_SEND_TIMEOUT_S)]
        hermes = _hermes_python(project)
        if hermes:
            attempts.append((HERMES, hermes_argv(hermes, str(text)), HERMES_TIMEOUT_S))
        if run is None and os.environ.get(NOTIFY_ENV) == NO_CHANNEL:
            attempts = []
        for channel, argv, timeout in attempts:
            ran, code = _attempt(argv, timeout, run)
            if not ran:
                continue
            outcome.update(channel=channel, exit_code=code, ok=code == 0)
            if code == 0:
                break
        payload = {key: outcome[key] for key in ("event", "channel", "ok", "exit_code")}
        outcome["journaled"] = _journal(ledger, payload, ticket) and outcome["journaled"]
    except Exception:  # the notifier is called from failure paths; it must never add one
        _log.exception("notify(%r) failed", event)
    return outcome


def _project(project):
    try:
        candidate = Path(project) if project is not None else read_active()
        return candidate.resolve() if candidate is not None and is_project(candidate) else None
    except (OSError, ValueError):
        return None


def _ledger(project):
    try:
        return Ledger(project) if project is not None else None
    except Exception:
        _log.exception("no ledger for %s", project)
        return None


def _journal(ledger, payload, ticket):
    if ledger is None:
        return False
    try:
        ledger.append_event(NOTIFIED, payload, ticket=ticket)
        return True
    except Exception:
        _log.exception("could not journal notified %r", payload)
        return False


def _hermes_python(project):
    """`harness.json.notify.hermes_python`, read tolerantly: an unreadable file means no Telegram."""
    if project is None:
        return None
    try:
        value = json.loads((project / HARNESS_JSON).read_text(encoding="utf-8")).get("notify", {}).get("hermes_python")
    except (OSError, ValueError, AttributeError):
        return None
    return value if isinstance(value, str) and value else None


def _attempt(argv, timeout, run):
    """Run one channel. Returns `(ran, exit_code)`: not ran when the executable is missing, no code on a timeout."""
    try:
        if run is not None:
            done = run(argv, timeout)
        else:
            done = subprocess.run(argv, capture_output=True, text=True, check=False,
                                  stdin=subprocess.DEVNULL, timeout=timeout)
    except FileNotFoundError:
        return False, None
    except Exception:  # a timeout, or anything else: the channel ran and did not deliver, so fall through
        _log.warning("%s did not finish", argv[0], exc_info=True)
        return True, None
    if done.returncode != 0:
        # Routine on a workstation reached over SSH, where `notify-send` has no daemon to talk to.
        _log.info("%s exited %s: %s", argv[0], done.returncode, (getattr(done, "stderr", "") or "").strip())
    return True, done.returncode
