"""Type-A acceptance and the per-launch settings (Implementation Decisions 4).

Two things live here, both halves of the same contract between the conductor and a worker.

**The per-launch settings.** `hooks/worker-settings.json` is the template: the three guards
registered with `args: []` (exec form) and a 30 second timeout, plus the `permissions.deny`
first layer. `worker_settings` renders it with `${CLAUDE_PROJECT_DIR}` replaced by the absolute
harness path, because hooks and settings load from the worktree cwd only and the worktree holds
no copy of `hooks/`. The renderer refuses a template whose handlers have drifted from the
shape the research note verified, so the file and the code cannot disagree silently.

**`wayline accept`.** The stop guard blocks a worker's stop while `TICKET_ACCEPTANCE_FILE` is
missing. `wayline accept`, run by the worker inside its worktree, executes the ticket's
`acceptance.machine` commands and writes that file, whether they passed or failed: a failure
the worker can read and fix is the point, and a worker that can never write the file would
loop until the eight-block cap. The conductor never trusts the file; it reruns acceptance
itself after the worker exits.

The Type-B half (the verifier launch and the verdict record) is ticket 32's.
"""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from wayline import HARNESS_ROOT, POLICY_PATH
from wayline.frontmatter import FrontmatterError, load_document
from wayline.jsonschema import check, load_schema
from wayline.ledger import now_ts

__all__ = [
    "GateError",
    "GUARDS",
    "HOOK_TIMEOUT_S",
    "accept",
    "acceptance_file_record",
    "read_ticket",
    "run_machine_acceptance",
    "worker_settings",
    "write_worker_settings",
]

# The three guards of Implementation Decisions 4, in the order the template registers them.
GUARDS = ("touch_set_guard.sh", "command_guard.sh", "stop_guard.sh")

# A timed-out PreToolUse hook does not block, so the timeout is explicit and short
# (research-notes 03, "Timeouts").
HOOK_TIMEOUT_S = 30

# The placeholder the template carries; the renderer replaces it with the harness path.
PLACEHOLDER = "${CLAUDE_PROJECT_DIR}"

# How much of a command's output the acceptance record keeps.
TAIL_CHARS = 4000

# The exit code a killed-after-timeout command reports, as `timeout(1)` reports it.
TIMEOUT_EXIT_CODE = 124

# How long to wait for a killed command's output before giving up on it.
DRAIN_SECONDS = 5


class GateError(ValueError):
    """A gate that cannot be run or a settings template that cannot be rendered."""


# --- the per-launch settings -------------------------------------------------------------------


def worker_settings(harness_root=HARNESS_ROOT):
    """The per-launch settings as a dict, rendered from `hooks/worker-settings.json`.

    Every hook command is an absolute path into the harness checkout, and every handler is
    checked for the exec form (`args: []`) and the explicit 30 second timeout.
    """
    root = Path(harness_root).resolve()
    template = root / "hooks" / "worker-settings.json"
    try:
        text = template.read_text(encoding="utf-8")
    except OSError as failure:
        raise GateError("the settings template %s cannot be read: %s" % (template, failure)) from None
    if PLACEHOLDER not in text:
        raise GateError("the settings template %s carries no %s to replace" % (template, PLACEHOLDER))
    try:
        settings = json.loads(text.replace(PLACEHOLDER, str(root)))
    except ValueError as failure:
        raise GateError("the settings template %s is not JSON: %s" % (template, failure)) from None
    _check_handlers(settings, template)
    return settings


def _check_handlers(settings, template):
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict) or not hooks:
        raise GateError("the settings template %s registers no hooks" % template)
    registered = set()
    for event, matchers in hooks.items():
        for matcher in matchers:
            for handler in matcher.get("hooks", []):
                command = handler.get("command")
                if handler.get("type") != "command":
                    raise GateError("%s: the %s handler %r is not a command hook" % (template, event, command))
                if handler.get("args") != []:
                    raise GateError("%s: the %s handler %r needs \"args\": [] to run in exec form" % (template, event, command))
                if handler.get("timeout") != HOOK_TIMEOUT_S:
                    raise GateError("%s: the %s handler %r needs \"timeout\": %d; a timed-out PreToolUse hook does not block" % (template, event, command, HOOK_TIMEOUT_S))
                script = Path(command)
                if not script.is_file():
                    raise GateError("%s: the %s hook script %s does not exist" % (template, event, script))
                if not os.access(script, os.X_OK):
                    raise GateError("%s: the %s hook script %s is not executable" % (template, event, script))
                registered.add(script.name)
    missing = [guard for guard in GUARDS if guard not in registered]
    if missing:
        raise GateError("%s: the guard(s) %s are not registered" % (template, ", ".join(missing)))
    deny = (settings.get("permissions") or {}).get("deny")
    if not deny:
        raise GateError("%s: permissions.deny is the cheap first layer and must not be empty" % template)


def write_worker_settings(path, harness_root=HARNESS_ROOT):
    """Write the per-launch `settings.json` for one worker launch; returns the path."""
    return _write_json(path, worker_settings(harness_root))


def _write_json(path, value):
    """Write JSON by temp file and rename, so no reader ever sees a half-written file.

    The stop guard only tests that the acceptance file exists, so a torn write would let a
    worker stop while the conductor later read nothing it could parse.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / ("." + target.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, target)
    return target


# --- reading a ticket --------------------------------------------------------------------------


def read_ticket(project, ticket_id):
    """The frontmatter of `research/tickets/NN-slug.md` whose `id` is `ticket_id`.

    `tickets.py` owns the ticket directory once ticket 02 lands; `accept` needs one ticket and
    reads it here so that the worktree verb does not wait on the graph.
    """
    try:
        wanted = int(ticket_id)
    except (TypeError, ValueError):
        raise GateError("a ticket id is an integer, got %r" % (ticket_id,)) from None
    directory = Path(project).resolve() / "research" / "tickets"
    if not directory.is_dir():
        raise GateError("%s does not exist; is %s a wayline project?" % (directory, project))
    for path in sorted(directory.glob("*.md")):
        try:
            frontmatter, _ = load_document(path.read_text(encoding="utf-8"))
        except (OSError, FrontmatterError) as failure:
            raise GateError("%s cannot be read: %s" % (path, failure)) from None
        if frontmatter.get("id") != wanted:
            continue
        check(frontmatter, load_schema("ticket"), name="ticket %s" % path.name)
        return frontmatter
    raise GateError("no ticket in %s has id %d" % (directory, wanted))


def _policy_value(project, key, fallback):
    """A policy value: `policy.json`, overridden by the project's `harness.json` `policy` block."""
    value = fallback
    for path, section in ((POLICY_PATH, None), (Path(project) / "harness.json", "policy")):
        try:
            loaded = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if section is not None:
            loaded = loaded.get(section) or {}
        if key in loaded:
            value = loaded[key]
    return value


# --- running the machine acceptance --------------------------------------------------------------


def run_machine_acceptance(commands, cwd, timeout_s):
    """Run each Type-A command with `shell=True` in `cwd`; returns one result record each.

    A command that outlives `timeout_s` has its whole process group killed and reports exit
    code 124, as `timeout(1)` does, so a hung check cannot hold the worker open.
    """
    results = []
    for command in commands:
        results.append(_run_one(command, cwd, timeout_s))
    return results


def _run_one(command, cwd, timeout_s):
    started = time.monotonic()
    process = subprocess.Popen(
        command,
        shell=True,
        cwd=str(cwd),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        start_new_session=True,
    )
    try:
        output, _ = process.communicate(timeout=timeout_s)
        exit_code = process.returncode
    except subprocess.TimeoutExpired:
        _kill_group(process)
        output, note = _drain(process)
        output = output + "\nwayline accept: killed after %s seconds.%s\n" % (timeout_s, note)
        exit_code = TIMEOUT_EXIT_CODE
    return {
        "cmd": command,
        "exit_code": exit_code,
        "seconds": round(time.monotonic() - started, 3),
        "tail": _tail(output),
    }


def _kill_group(process):
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        process.kill()


def _drain(process):
    """What the killed command already wrote, without waiting on a process that outlived it.

    A command that starts something with `setsid` or `nohup` leaves a process outside the
    group the timeout kills, and that process still holds the pipe. Reading it to the end
    would hang `wayline accept` forever, the acceptance file would never be written, and
    the stop guard would keep refusing the stop. So the read is bounded and the pipe is
    dropped; the record says the output was lost.
    """
    try:
        return (process.communicate(timeout=DRAIN_SECONDS)[0] or ""), ""
    except subprocess.TimeoutExpired:
        pass
    try:
        process.stdout.close()
    except (OSError, AttributeError):
        pass
    process.kill()
    try:
        process.wait(timeout=DRAIN_SECONDS)
    except subprocess.TimeoutExpired:
        pass
    return "", " A process outlived the command and held its output open; the output was dropped."


def _tail(text):
    text = text or ""
    if len(text) <= TAIL_CHARS:
        return text
    return "...\n" + text[-TAIL_CHARS:]


def acceptance_file_record(results, where):
    """The record the stop guard looks for: `ran_at`, `where`, `results`, `pass`."""
    return {
        "ran_at": now_ts(),
        "where": where,
        "results": list(results),
        "pass": all(result["exit_code"] == 0 for result in results),
    }


# --- the verb ------------------------------------------------------------------------------------

USAGE = "usage: wayline accept [--where worktree|rebased|main]"

WHERE_VALUES = ("worktree", "rebased", "main")


def accept(args):
    """`wayline accept`: run the ticket's machine acceptance here and write the acceptance file.

    Reads `WAYLINE_PROJECT`, `WAYLINE_TICKET` and `TICKET_ACCEPTANCE_FILE` from the environment,
    which the conductor exports at launch. Exit code 0 when every command passed, 1 when one
    failed, 2 when the gate could not be run at all.
    """
    where = "worktree"
    remaining = list(args)
    while remaining:
        argument = remaining.pop(0)
        if argument == "--where":
            if not remaining:
                return _fail("--where needs a value. " + USAGE)
            where = remaining.pop(0)
        elif argument.startswith("--where="):
            where = argument.split("=", 1)[1]
        elif argument in ("-h", "--help"):
            print(USAGE)
            return 0
        else:
            return _fail("unexpected argument %r. %s" % (argument, USAGE))
    if where not in WHERE_VALUES:
        return _fail("--where is one of %s, got %r" % (", ".join(WHERE_VALUES), where))

    try:
        project = _required_environment("WAYLINE_PROJECT")
        ticket_id = _required_environment("WAYLINE_TICKET")
        destination = Path(_required_environment("TICKET_ACCEPTANCE_FILE"))
        ticket = read_ticket(project, ticket_id)
    except ValueError as failure:  # GateError, or a ticket the schema refuses
        return _fail(str(failure))

    commands = (ticket.get("acceptance") or {}).get("machine") or []
    timeout_s = _policy_value(project, "acceptance_timeout_s", 600)
    if not isinstance(timeout_s, (int, float)) or timeout_s <= 0:
        return _fail("policy.acceptance_timeout_s is %r; it must be a positive number of seconds" % (timeout_s,))
    results = run_machine_acceptance(commands, Path.cwd(), timeout_s)
    record = acceptance_file_record(results, where)

    try:
        _write_json(destination, record)
    except OSError as failure:
        return _fail("TICKET_ACCEPTANCE_FILE %s cannot be written: %s" % (destination, failure))

    print(_summary(ticket, record, destination))
    return 0 if record["pass"] else 1


def _required_environment(name):
    value = os.environ.get(name)
    if not value:
        raise GateError("%s is not set; the conductor exports it at launch and `wayline accept` needs it" % name)
    return value


def _fail(message):
    print("wayline accept: " + message, file=sys.stderr)
    return 2


def _summary(ticket, record, destination):
    lines = ["ticket %s: %s" % (ticket["id"], ticket["title"])]
    if not record["results"]:
        lines.append("no machine acceptance on this ticket; nothing to run.")
    for result in record["results"]:
        mark = "ok  " if result["exit_code"] == 0 else "FAIL"
        lines.append("%s %6.1fs  %s" % (mark, result["seconds"], result["cmd"]))
        if result["exit_code"] != 0 and result["tail"].strip():
            lines.extend("     " + line for line in result["tail"].strip().splitlines()[-20:])
    lines.append("%s: %s" % ("pass" if record["pass"] else "fail", destination))
    return "\n".join(lines)
