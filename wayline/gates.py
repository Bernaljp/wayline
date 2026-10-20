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

**The Type-B half** (Implementation Decisions 11). `verdict` launches one fresh verifier session
through the launcher seam, on the model `policy.verifier` gives for the author's model, with the
paths and the one question it answers, and returns the validated verdict after journaling it.
`kill_argument` is the same gate twice: one session writes the strongest rejection memo, a second
adjudicates it point by point, and a fail files the `writing` ticket that scopes the claims down.
Nothing is acquitted by its author: a verdict is always a fresh launch carrying none of the author's
context (never the session that wrote the work, a resume of it, or a subagent inside it), with none
of the author's skills, and the paths are the subject rather than anyone's account of it. The model
table is the default choice of a verifier, not that rule, so a verdict may come from the author's own
model in such a session. While Fable's weekly window is spent, a verdict whose table verifier is Fable
is taken on Opus at the table's effort under the fallback consent `auto`, and waits otherwise
(decision 15).
"""

import json
import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from wayline import HARNESS_ROOT
from wayline import pacing, worker
from wayline.jsonschema import ValidationError, check, load_schema
from wayline.ledger import K_SUBJECT_KIND, PAYLOAD_ENUMS, TICKET_CREATED, VERDICT, ledger_for, now_ts
from wayline.project import fable_hold, policy_for, rung_named
from wayline.tickets import (
    DOCS, SATISFIED, machine_acceptance, next_id, read_ticket, read_tickets, tickets_dir, touches_problems, works_in_the_harness,
    write_ticket,
)
from wayline.tickets import relative_path as ticket_relative_path

__all__ = [
    "GateError",
    "raise_if_refused",
    "GUARDS",
    "HOOK_TIMEOUT_S",
    "accept",
    "acceptance_file_record",
    "ticket_by_id",
    "run_machine_acceptance",
    "worker_settings",
    "write_worker_settings",
    "Ask",
    "Verdict",
    "VERIFIER",
    "VERDICT_TYPES",
    "CLAIM_SUPPORT",
    "file_writing_ticket",
    "SEVERITIES",
    "SUBJECT_KINDS",
    "findings_text",
    "kill_argument",
    "take_verdict",
    "ticket_asks", "owed_asks", "code_rule_text",
    "UsageLimited",
    "FableHeld",
    "fallback_now",
    "verifies_on_fable",
    "verdict",
    "verdict_for",
    "verdict_dir",
    "verdict_env",
    "verdict_prompt",
    "verifier_tier",
    "verdict_tier",
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


def ticket_by_id(project, ticket_id):
    """The frontmatter of the one ticket whose `id` is `ticket_id`.

    `tickets.py` owns reading and validating a ticket file, so this only finds the file.
    It reads that one rather than the whole directory on purpose: an unrelated ticket the
    planner left half-written must not stop a worker running its own acceptance.
    """
    try:
        wanted = int(ticket_id)
    except (TypeError, ValueError):
        raise GateError("a ticket id is an integer, got %r" % (ticket_id,)) from None
    directory = tickets_dir(project)
    if not directory.is_dir():
        raise GateError("%s does not exist; is %s a wayline project?" % (directory, project))
    for path in sorted(directory.glob("*.md")):
        leading = re.match(r"(\d+)-", path.name)
        if not leading or int(leading.group(1)) != wanted:
            continue
        try:
            frontmatter, _ = read_ticket(path)
        except OSError as failure:
            raise GateError("%s cannot be read: %s" % (path, failure)) from None
        return frontmatter
    raise GateError("no ticket in %s has id %d" % (directory, wanted))


def _policy_value(project, key, fallback):
    """A policy value: the harness defaults under the project's `harness.json` `policy` overrides."""
    return policy_for(project).get(key, fallback)


# --- running the machine acceptance --------------------------------------------------------------


def run_machine_acceptance(commands, cwd, timeout_s):
    """Run each Type-A command with `shell=True` in `cwd`; returns one result record each.

    A command that outlives `timeout_s` has its whole process group killed and reports exit
    code 124, as `timeout(1)` does, so a hung check cannot hold the worker open.

    Python writes no bytecode while the acceptance runs: the conductor runs it on `main` in the project's own
    checkout, and a `__pycache__/` left there is a change outside `research/` that refuses the next `run`.
    """
    # The harness's own `bin/` first, as a worker has it: a criterion that runs `wayline` (every docs ticket's
    # build does) runs this checkout's, not whichever the conductor's PATH found, or none under a unit.
    path = os.pathsep.join([str(HARNESS_ROOT / "bin")] + ([os.environ["PATH"]] if os.environ.get("PATH") else []))
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PATH=path)
    results = []
    for command in commands:
        results.append(run_shell(command, cwd, timeout_s, env=env))
    return results


def run_shell(command, cwd, timeout_s, env=None, label="wayline accept"):
    """Run one shell command in `cwd` under `timeout_s`; returns `{cmd, exit_code, seconds, tail}`.

    stdout and stderr arrive interleaved in `tail`, as a person would have seen them. `env`
    replaces the environment when given; intake passes the sample artifact to a goal's
    `eval_command` this way.
    """
    started = time.monotonic()
    process = subprocess.Popen(
        command,
        shell=True,
        cwd=str(cwd),
        env=env,
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
        output = output + "\n%s: killed after %s seconds.%s\n" % (label, timeout_s, note)
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
        ticket = ticket_by_id(project, ticket_id)
    except ValueError as failure:  # GateError, or a ticket the schema refuses
        return _fail(str(failure))

    commands = machine_acceptance(ticket)
    timeout_s = _policy_value(project, "acceptance_timeout_s", 600)
    if not isinstance(timeout_s, (int, float)) or timeout_s <= 0:
        return _fail("policy.acceptance_timeout_s is %r; it must be a positive number of seconds" % (timeout_s,))
    # What the worker could only stage (Claude Code refuses its writes under .claude/) is put where the criteria look.
    for touch in worker.place_staged(Path.cwd(), ticket.get("touches") or []):
        print("placed %s from %s" % (touch, worker.staged_path(touch)))
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


# --- the Type-B half: the verifier and the verdict (Implementation Decisions 11) ----------------

VERIFIER = "verifier"          # <harness>/roles/verifier/
VERDICT_SCHEMA = "verdict"     # <harness>/schemas/verdict.json
VERDICTS = "verdicts"          # <project>/research/sessions/verdicts/<subject>/<n>

# The severities a finding carries, worst first; `blocker` fails a subject on its own.
SEVERITIES = ("blocker", "major", "minor")

# What a verdict can be about, read off the journal's own enum so the gate cannot ask for a
# verdict it would then be unable to journal, after the session had been spent.
SUBJECT_KINDS = PAYLOAD_ENUMS[(VERDICT, K_SUBJECT_KIND)]

# `verdict_type`: which of the spec's Type-B questions a verdict answered. The spec's "what gets
# a verdict" list is longer than this; each remaining entry arrives with the ticket that builds
# the gate asking it (the spec, the dossier depth spot-check, sampled claims, figures, the docs).
QUALITY = "quality"                      # the ticket's own acceptance.quality criteria
DIFF = "diff"                            # difficulty 3: an independent read of the diff
RESULT = "result"                        # difficulty 4 and 5: an independent read of the result
KILL_MEMO = "kill_argument_memo"         # the first thread: the strongest rejection memo
KILL_ARGUMENT = "kill_argument"          # the second thread: the memo adjudicated point by point
CLAIM_SUPPORT = "claim_support"          # a sampled report claim: do its cited artifacts support it
DEPTH_SPOT_CHECK = "depth_spot_check"    # an L2 dossier: were its most important items and its flaws read in depth
SPEC_COVERAGE = "spec_coverage"          # the spec: does every claim have an experiment, and every experiment defend a claim
FIGURE_HONESTY = "figure_honesty"        # a figure: does it assert something the data does not (ticket 50)
EQUATION_MATCH = "equation_match"        # one equation a figure typesets: does it match the code that computes it (ticket 50)
DOCS_READ = "docs_read"                  # a docs ticket: is the site clear and complete against the package's purpose
PAPER_READ = "paper_read"                # the paper: the one independent verdict that gates the draft beside the kill argument (ticket 53)
NUMBERS_MATCH = "numbers_match"          # a finding's sentence whose numbers code could not match at its locators (ticket 90)
VERDICT_TYPES = (QUALITY, DIFF, RESULT, KILL_MEMO, KILL_ARGUMENT, CLAIM_SUPPORT, DEPTH_SPOT_CHECK, SPEC_COVERAGE,
                 FIGURE_HONESTY, EQUATION_MATCH, DOCS_READ, PAPER_READ, NUMBERS_MATCH)

# What an independent read of a done ticket reads, by the ticket's effective difficulty.
DIFFICULTY_VERDICTS = {3: DIFF, 4: RESULT, 5: RESULT}

# A verdict is one question, so it takes the policy's own smallest budget. The spec gives roles a
# model and an effort and no budget, and a session with no cap on its turns is not a thing to
# launch overnight.
VERDICT_BUDGET = "small"

RESUME_VERDICT = (
    "The verdict you returned could not be used: %s.\n\n"
    "Return the verdict now, through the structured output, matching the schema this session was "
    "launched with. Do not start new work and do not widen the question."
)


class UsageLimited(GateError):
    """A session a usage window refused: a closed window rather than a bad answer, so it is never resumed.

    `limit` is the `pacing.Limit` that said so. The conductor journals it, keeps the verdict queued,
    and launches it again, fresh, once the window allows (decision 15).
    """

    def __init__(self, message, limit=None):
        super().__init__(message)
        self.limit = limit


class FableHeld(GateError):
    """A verdict on Fable asked for while the hold on Fable's weekly window stands and the consent waits.

    Nothing was launched. Under `wait`, or under `ask` before an answer, a verdict whose table verifier
    is Fable waits for the reset (decision 15), so the gate raises this before a session is spent. It
    is not a verdict against the subject: the ask stays queued, and it is taken once the window resets
    or the consent falls back. `resets_at` is the hold's reset and `consent` the consent it waits under.
    """

    def __init__(self, message, resets_at=None, consent=None):
        super().__init__(message)
        self.resets_at = resets_at
        self.consent = consent


@dataclass
class Ask:
    """One verdict waiting to be taken: the five values `verdict` needs, and who is owed it.

    The conductor queues these after `ticket_done` and drains them as model work; nothing about
    an ask is a verdict yet. `author_model` is the model that wrote the subject, which is what
    `policy.verifier` is keyed by. `role` is the judging role: the verifier, except where a
    decision names another role that may judge (the critic's depth spot-check of a dossier).
    """

    subject_kind: str
    subject: str
    question: str
    paths: list
    scope_limit: str
    verdict_type: str
    author_model: str
    ticket: Optional[int] = None
    role: str = VERIFIER
    rung: Optional[int] = None  # the rung the judged ticket attempt ran on (decision 16); None off a ticket
    code_rule: Optional[dict] = None  # the parameters and not_methods this verdict must judge, one by one (ticket 107)


@dataclass
class Verdict:
    """One taken verdict: the record of the `verdict` schema, plus what it was about.

    `passed` is the schema's `pass`, spelled so it is not the keyword; `payload` spells it back
    for the journal. `fallback_from` names the Fable rung (`r7 fable high`, decision 16) a verdict
    taken on Opus in place of a verifier on Fable came from, while Fable's weekly window was spent
    (decision 15).
    """

    subject_kind: str
    subject: str
    verdict_type: str
    passed: bool
    question_limit: str
    findings: list = field(default_factory=list)
    session_id: Optional[str] = None
    model: Optional[str] = None
    ticket: Optional[int] = None
    fallback_from: Optional[str] = None
    proposals: list = field(default_factory=list)
    rung: Optional[int] = None
    # The model the verdict's own session ran on, when its result named another than the one it was launched
    # with (decision 16); None when it ran as asked, which is every recorded verdict.
    model_ran: Optional[str] = None
    # The judgment of a ticket's parameter reasons and `not_methods` (ticket 107), when the question listed them.
    code_rule: Optional[dict] = None
    # Every `rate_limit_event` the verdict's sessions wrote, for the conductor to fold into its readings as it
    # does a worker's: a refusal can ride a session that still answered (decision 15). Never journaled.
    rate_limit_events: list = field(default_factory=list, compare=False, repr=False)

    @property
    def payload(self):
        """The `verdict` journal event's payload (Implementation Decisions 2).

        `rung` is the index of the rung the judged ticket attempt ran on (decision 16), absent on a verdict
        about anything but a ticket; `fallback_from` only on a verdict taken by fallback; `model_ran` only on
        one whose own session ran on another model than it was launched with (decision 16).
        """
        payload = {
            "subject_kind": self.subject_kind, "subject": self.subject,
            "verdict_type": self.verdict_type, "pass": self.passed,
            "session_id": self.session_id, "model": self.model,
            "findings": [dict(finding) for finding in self.findings],
        }
        if self.rung is not None:
            payload["rung"] = self.rung
        if self.fallback_from:
            payload["fallback_from"] = self.fallback_from
        if self.model_ran:
            payload["model_ran"] = self.model_ran
        return payload


def verifier_tier(policy, author_model):
    """The verifier's `(model, effort)` for an author on `author_model`, from `policy.verifier`.

    The table is keyed by family, so an author on a full version name (`claude-opus-4-8`) reads its family's
    row (decision 16). The verifier's effort is the table's, which the cap of decision 16 does not bind.
    The table is the default choice of a verifier, not the rule that makes a verdict one (decision 11):
    an entry naming the author's own model is taken as it stands, because what keeps a verdict from
    being the author's word is a fresh session carrying none of the author's context, and every verdict
    `take_verdict` launches is one. An author the table does not name, and an effort the launcher does
    not know, are refused by name.
    """
    table = (policy or {}).get("verifier") or {}
    entry = table.get(pacing.family(author_model) or author_model)
    if not isinstance(entry, dict) or not entry.get("model") or not entry.get("effort"):
        raise GateError("policy.verifier gives no model and effort for an author on %r; it names %s"
                        % (author_model, ", ".join(sorted(table)) or "nothing"))
    if entry["effort"] not in worker.EFFORTS:
        raise GateError("policy.verifier gives the effort %r for an author on %s; it is one of %s"
                        % (entry["effort"], author_model, ", ".join(worker.EFFORTS)))
    return entry["model"], entry["effort"]


def verdict_tier(policy, author_model, fall_back=False):
    """The `(model, effort, fallback_from)` a verdict on work written on `author_model` is taken at (decision 15).

    The table's verifier, unless it is on Fable and `fall_back` is true: then Opus at the table's effort
    (`fable high` becomes `opus high`), and `fallback_from` names the Fable rung it came from, `r7 fable
    high` (decision 16). A verifier on any other model is the table's under every consent, since Fable is
    the only model with a weekly window of its own.
    """
    model, effort = verifier_tier(policy, author_model)
    if model == pacing.FABLE and fall_back:
        return pacing.OPUS, effort, rung_named(policy, model, effort)
    return model, effort, None


def verifies_on_fable(policy, author_model):
    """Whether the table's verifier for work written on `author_model` is Fable.

    A table the gate refuses is not: the gate refuses it by name when the verdict is taken, which is where
    the owner should read why.
    """
    try:
        return verifier_tier(policy, author_model)[0] == pacing.FABLE
    except GateError:
        return False


def _fall_back_for(project, policy, author_model, fall_back, what):
    """Whether a verdict on work written on `author_model` falls back now: `fall_back` when the caller decided, else `fallback_now`.

    The conductor decides from the consent it read for its wave, and the claim sampler once for its pass,
    so neither falls back for one verdict and waits for the next. A caller that passes None (the depth
    spot-check, the kill argument) has the journal decide, and only for a verifier on Fable: a verifier on
    any other model is the table's.
    """
    if fall_back is not None:
        return bool(fall_back)
    if verifier_tier(policy, author_model)[0] != pacing.FABLE:
        return False
    return fallback_now(project, what)


def fallback_now(project, what="a verdict on Fable"):
    """Whether a verdict whose verifier is Fable, taken outside the conductor, falls back to Opus now (decision 15).

    False while no hold stands (`project.fable_hold`), so it is taken on Fable, and true under a hold and the
    consent `auto`. Under a hold and `wait`, or `ask` before an answer, it raises `FableHeld` for `what`
    before any session is spent.
    """
    hold = fable_hold(project)
    if hold is None:
        return False
    if not hold["falls_back"]:  # `auto`, or `ask` answered `fall back` for the window (`project.falls_back_now`)
        raise FableHeld("%s runs on Fable, whose weekly window is held until %s; under the fallback consent %s it "
                        "waits for the reset" % (what, hold["resets_at"], hold["consent"] if hold["stated"] else "ask (unset)"),
                        resets_at=hold["resets_at"], consent=hold["consent"])
    return True


def verdict_dir(project, subject_kind, subject):
    """The session directory for one verdict: `research/sessions/verdicts/<subject>/<n>`.

    `<n>` is the first free number under the subject, so a subject verdicted twice keeps both
    streams. A gate that runs more than one session (the kill argument) takes this once and puts
    each thread in a directory under it, so the two threads of one gate stay together.
    """
    base = Path(project) / "research" / "sessions" / VERDICTS / _subject_slug(subject_kind, subject)
    number = 1
    while (base / str(number)).exists():
        number += 1
    return base / str(number)


def _subject_slug(subject_kind, subject):
    """A directory name for one subject: its kind and its path, with the separators flattened."""
    text = re.sub(r"[^a-z0-9]+", "-", ("%s-%s" % (subject_kind, subject)).lower()).strip("-")
    return text[:80].rstrip("-") or "subject"


def verdict_env(project, run_dir):
    """The environment one verifier session runs under, and the two variables it deliberately lacks.

    Without `TICKET_TOUCHES` the touch-set guard blocks every write and the command guard every
    deletion, which is what read-only means for a session that runs under the same guards as a
    worker. Without `TICKET_ACCEPTANCE_FILE` the stop guard lets the session stop, which it must:
    a verifier has no acceptance to run, and a stop blocked forever would spend the whole session
    on the eight-block cap. `PATH` is left alone because a verifier runs no `wayline` command.
    """
    return {"WAYLINE_PROJECT": str(project), "WAYLINE_RUN": str(run_dir)}


def verdict_prompt(role, subject_kind, subject, question, paths, scope_limit, cwd=None, memo=None):
    """The verifier's prompt: the question, the scope limit, the paths, the protocol, the schema.

    No `/wayline-<skill>` line and no inlined skill: the verifier carries none of the author's
    skills (decision 11). A path that is not there is said to be missing where it is listed, so a
    session cannot mistake an absent artifact for one it read.
    """
    lines = [
        "# The verdict you are being asked for",
        "",
        "- subject: the %s `%s`" % (subject_kind, subject),
        "- the question: %s" % question.strip().replace("\n", "\n  "),
        "- your scope limit: %s" % scope_limit.strip().replace("\n", "\n  "),
        "",
        "You did not write this and you are not being asked to fix it. Answer the question above "
        "from the paths below, and answer nothing wider.",
        "",
        "# The paths",
        "",
        "This is the subject. Open them yourself; no summary of them was given to you, on purpose.",
        "",
    ]
    root = Path(cwd) if cwd else None
    for entry in paths or []:
        text = str(entry)
        missing = ""
        if root is not None and not _exists_under(root, text):
            missing = "  [wayline: this path is not there. It is something you could not check, not something that passed.]"
        lines.append("- `%s`%s" % (text, missing))
    if not paths:
        lines.append("- [wayline: no path was given with this question. Say so as a finding rather than answering it.]")
    parts = ["\n".join(lines)]
    if memo is not None:
        parts.append("\n".join([
            "# The rejection memo to adjudicate",
            "",
            "Another verifier session wrote this against the same paths. Take it point by point: a "
            "point the artifacts answer does not stand, a point they do not answer stands and is "
            "your finding, at the locator you read it at.",
            "",
            findings_text(memo, empty="[wayline: the memo session found no case to make against "
                                      "these paths, so there is nothing here to adjudicate.]"),
        ]))
    parts.append(worker.protocol_for(role.protocol, "verdict"))
    parts.append(worker.schema_section("# The verdict", role.output_schema or VERDICT_SCHEMA))
    return "\n\n".join(part.strip("\n") for part in parts if part and part.strip()) + "\n"


def _exists_under(root, entry):
    """Whether a listed path is there, reading `path#anchor` and `path:1-20` as the path part."""
    path = str(entry).split("#", 1)[0]
    if re.search(r":\d+(-\d+)?$", path):
        path = path.rsplit(":", 1)[0]
    candidate = Path(path)
    return (candidate if candidate.is_absolute() else root / candidate).exists()


def findings_text(findings, empty="no finding was named"):
    """Findings as one block of text, worst first: the failure output, and the memo's own points.

    One renderer for both, because they are the same three fields and a reader who has learned
    to read one should not have to learn the other. `empty` is what stands in for no finding at
    all, which means something different to each caller.
    """
    if not findings:
        return empty
    order = {name: index for index, name in enumerate(SEVERITIES)}
    ranked = sorted(findings, key=lambda finding: order.get(finding.get("severity"), len(SEVERITIES)))
    return "\n".join("- [%s] %s (%s)" % (finding.get("severity", "?"), (finding.get("text") or "").strip(),
                                         finding.get("locator", "?")) for finding in ranked)


def verdict(subject_kind, subject, question, paths, scope_limit, *, project, author_model,
            verdict_type, ticket=None, harness_root=HARNESS_ROOT, policy=None, ledger=None,
            cwd=None, memo=None, run_dir=None, role=VERIFIER, fall_back=None, rung=None, code_rule=None):
    """One Type-B verdict, journaled: every verdict in the harness comes through here.

    A verdict is journaled because its session id and its model are the whole of what makes it
    worth anything later: a record that says the work passed, without saying who read it and on
    what, is the author's word again.
    """
    taken = take_verdict(subject_kind, subject, question, paths, scope_limit, project=project,
                         author_model=author_model, verdict_type=verdict_type, ticket=ticket,
                         harness_root=harness_root, policy=policy, cwd=cwd, memo=memo,
                         run_dir=run_dir, role=role, fall_back=fall_back, rung=rung, code_rule=code_rule)
    ledger_for(ledger or Path(project).resolve()).append_event(
        VERDICT, taken.payload, ticket=taken.ticket, session_id=taken.session_id)
    return taken


def verdict_for(ask, **context):
    """The verdict one `Ask` asks for: `verdict`, with the ask's own five values and its author.

    The conductor's queue holds asks rather than argument lists, so this is where an ask is
    turned back into the call of the gate; `context` is the project, the policy, the ledger, and
    the harness root, which belong to the caller rather than to the ask.
    """
    return verdict(ask.subject_kind, ask.subject, ask.question, ask.paths, ask.scope_limit,
                   author_model=ask.author_model, verdict_type=ask.verdict_type,
                   ticket=ask.ticket, role=ask.role, rung=ask.rung, code_rule=ask.code_rule, **context)


def take_verdict(subject_kind, subject, question, paths, scope_limit, *, project, author_model,
                 verdict_type, ticket=None, harness_root=HARNESS_ROOT, policy=None,
                 cwd=None, memo=None, run_dir=None, role=VERIFIER, fall_back=None, rung=None, code_rule=None):
    """One verifier session, validated but not journaled; `verdict` is this plus the journal.

    `role` names the judging role, the verifier unless a decision names another; whichever it
    is, its sidecar has to carry `may_judge`, and it runs on the verifier's tier for the author.

    The verifier runs on the model and effort `policy.verifier` gives for `author_model`, which may
    be the author's own model: the session is always a fresh launch carrying none of the author's
    context, never a resume of the authoring session or a subagent inside it. A verifier on Fable is
    taken on Opus at the table's effort when `fall_back` is true (`verdict_tier`); `fall_back=None`
    reads the hold from the journal and raises `FableHeld` before a session is spent when the verdict
    waits (decision 15). A depth spot-check that would run on Haiku is refused.

    The session is given the paths and the one question; a session that
    returns something the `verdict` schema refuses is resumed once with the reason, and a second
    unusable answer raises rather than counting as a fail. A verdict nobody could take is not a
    verdict against the subject. A session a usage window refused is never resumed, since a resume
    would be refused the same way: it raises `UsageLimited`, and the verdict is launched again,
    fresh, once the window allows (decision 15).

    The one caller that stops here rather than going through `verdict` is the kill argument's
    first thread: a rejection memo is one thread's case against the work, not a judgment of it,
    and journaling it as a `verdict` would leave a failing Type-B verdict in the ledger against
    a paper the second thread went on to clear.

    `code_rule` is a ticket's parameters and not_methods the question listed (ticket 107): an answer that does not judge
    every one of them is resumed like any other unusable answer.
    """
    if verdict_type not in VERDICT_TYPES:
        raise GateError("verdict_type is one of %s, got %r" % (", ".join(VERDICT_TYPES), verdict_type))
    if subject_kind not in SUBJECT_KINDS:
        raise GateError("subject_kind is one of %s, got %r" % (", ".join(SUBJECT_KINDS), subject_kind))
    if not str(subject or "").strip() or not str(question or "").strip() or not str(scope_limit or "").strip():
        raise GateError("a verdict needs a subject, a question, and a scope limit; got %r, %r, %r"
                        % (subject, question, scope_limit))
    project = Path(project).resolve()
    policy = policy_for(project, harness_root) if policy is None else policy
    what = "the %s verdict on the %s %s" % (verdict_type, subject_kind, subject)
    model, effort, fallback_from = verdict_tier(policy, author_model,
                                                _fall_back_for(project, policy, author_model, fall_back, what))
    if verdict_type == DEPTH_SPOT_CHECK and model == pacing.HAIKU:
        raise GateError("%s would run on haiku, and a depth spot-check never goes to Haiku (decision 15); "
                        "policy.verifier gives haiku for an author on %s" % (what, author_model))
    role = worker.read_role(role, harness_root, project)
    if role.may_judge is not True:
        raise GateError("%s: the %s role has to carry may_judge, and a Type-B verdict comes "
                        "from nothing else" % (role.source, role.name))
    run_dir = Path(run_dir) if run_dir else verdict_dir(project, subject_kind, subject)
    cwd = Path(cwd) if cwd else project
    prompt = verdict_prompt(role, subject_kind, subject, question, paths, scope_limit, cwd=cwd, memo=memo)
    request = worker.LaunchRequest(
        role=role.name, model=model, effort=effort, prompt=prompt,
        agent_json=role.agent_json(model, effort, _budget(policy, "max_turns")),
        allowed_tools=list(role.allowed_tools),
        disallowed_tools=list(role.disallowed_tools),
        settings_path=write_worker_settings(run_dir / "settings.json", harness_root),
        add_dirs=[str(Path(harness_root).resolve()), str(project)],
        cwd=cwd,
        env=verdict_env(project, run_dir),
        schema_path=Path(harness_root).resolve() / "schemas" / (VERDICT_SCHEMA + ".json"),
        max_minutes=_budget(policy, "max_minutes"),
    )
    envelope = worker.launch(request)
    raise_if_refused(envelope, model, what)
    heard = list(envelope.rate_limit_events)
    problem = _unusable(envelope, code_rule)
    if problem is not None and envelope.session_id:
        envelope = worker.resume(request, envelope.session_id, RESUME_VERDICT % problem)
        raise_if_refused(envelope, model, what)
        heard += envelope.rate_limit_events
        problem = _unusable(envelope, code_rule)
    if problem is not None:
        raise GateError("%s could not be taken: %s" % (what, problem))
    returned = envelope.structured_output
    return Verdict(
        subject_kind=subject_kind, subject=str(subject), verdict_type=verdict_type,
        passed=bool(returned["pass"]), question_limit=returned["question_limit"],
        findings=list(returned.get("findings") or []),
        session_id=envelope.session_id, model=envelope.model, ticket=ticket, fallback_from=fallback_from,
        proposals=list(returned.get("proposals") or []), rung=rung, code_rule=returned.get("code_rule"),
        # What the verifier's own session ran on, when the result named another model than it was launched with
        # (decision 16): a verdict stands or falls on who read the work, so the journal says which model did.
        model_ran=None if worker.ran_as_asked(model, envelope) else worker.model_ran(envelope),
        rate_limit_events=heard,
    )


def _budget(policy, key):
    """`policy.budget.small`'s turns or minutes, or None when the policy carries neither."""
    return ((policy.get("budget") or {}).get(VERDICT_BUDGET) or {}).get(key)


def raise_if_refused(envelope, model, what):
    """Raise `UsageLimited` for a session a usage window stopped without a usable answer (decision 15)."""
    if envelope.valid:
        return
    limit = pacing.hit_limit(envelope, worker.stderr_of(envelope), time.time(), model=model)
    if limit is None:
        return
    window = "Fable's weekly window" if limit.model == pacing.FABLE else "the %s window" % limit.window
    until = pacing.iso(limit.resets_at) if limit.resets_at is not None else "an unknown time"
    raise UsageLimited("%s was refused by the usage limit on %s until %s" % (what, window, until), limit)


def _unusable(envelope, code_rule=None):
    """Why this envelope is not a verdict the harness can act on, or None when it is one.

    The launcher already validated the structured output against the schema it passed; it is
    validated again here for the same reason the conductor reruns acceptance, and then read for
    the two answers the schema cannot refuse but nobody can act on: a pass carrying a blocker,
    and a fail carrying nothing that says what to fix.
    """
    if not envelope.valid:
        return "; ".join(envelope.errors) or "the session returned no structured verdict"
    try:
        check(envelope.structured_output, load_schema(VERDICT_SCHEMA), name="verdict")
    except ValidationError as failure:
        return str(failure)
    returned = envelope.structured_output
    blockers = [finding for finding in (returned.get("findings") or [])
                if finding.get("severity") == "blocker"]
    if returned["pass"] and blockers:
        return ("the verdict passed and carries %d blocking finding(s); a blocker fails the subject"
                % len(blockers))
    if not returned["pass"] and not returned.get("findings"):
        return "the verdict failed and named no finding, so nothing says what to fix"
    rule = returned.get("code_rule") or {}
    if code_rule:
        judged = {(entry.get("method"), entry.get("name")) for entry in rule.get("parameters") or []}
        judged |= {(None, entry.get("name")) for entry in rule.get("not_methods") or []}
        asked = [(entry.get("method"), entry.get("name")) for entry in code_rule.get("parameters") or []]
        asked += [(None, entry.get("name")) for entry in code_rule.get("not_methods") or []]
        missing = [name if method is None else "%s %s" % (method, name) for method, name in asked if (method, name) not in judged]
        if missing:
            return ("the question listed the ticket's reasons and not_methods to judge, and `code_rule` does not judge %s"
                    % ", ".join(missing))
    unheld = [entry for entry in (rule.get("parameters") or []) + (rule.get("not_methods") or []) if entry.get("holds") is False]
    if returned["pass"] and unheld:
        return ("the verdict passed and judges %d of the ticket's reasons or not_methods not to hold (`code_rule`); one that "
                "does not hold fails the verdict, with a finding that says so" % len(unheld))
    return None


# --- what a done ticket earns (decision 11, "what gets a verdict") -----------------------------


DOCS_QUESTION = (
    "Is the documentation site ticket %d left clear and complete against the package's purpose: could "
    "someone who did not write the package learn it from the tutorials, do a task from the how-to "
    "guides, find every public function and class in the reference, understand the design from the "
    "explanation, and trust that the examples and the gallery show what the package does?"
)
DOCS_SCOPE = (
    "The site's sources under `docs/` against the package's purpose as `research/INTAKE.md`, "
    "`research/SPEC.md`, and `README.md` state it, and against the package's code. `wayline docs build` "
    "has already checked the structure, the docstrings' presence, the examples, the warnings, and the "
    "links (its record is `research/.cache/docs/checks.json`), so do not re-check those; judge what "
    "a check cannot: whether a reader could use the package from this site. A page that says "
    "something the code does not do is a finding at that page and line."
)
DOCS_READ_PATHS = ("docs/", ".readthedocs.yaml", "research/INTAKE.md", "research/SPEC.md", "README.md",
                   "research/.cache/docs/checks.json")


CODE_RULE_QUESTION = (
    "Besides, the rule from code to Methods (ticket 107) left these for you to judge. For each parameter, does its "
    "one-sentence reason justify its value to a reader of the paper's Methods? For each function the worker says is not "
    "a method, is it indeed not a method the Methods should describe? Give your judgment of every item in `code_rule`; "
    "an item that does not hold fails this verdict, with a finding that says why."
)


def code_rule_text(rule):
    """The parameters' reasons and the `not_methods` of one ticket, as the lines a verdict's question lists."""
    lines = [CODE_RULE_QUESTION]
    parameters = (rule or {}).get("parameters") or []
    if parameters:
        lines.append("Parameters:")
        for entry in parameters:
            value = entry.get("value")
            default = entry.get("default")
            said = " = %s" % value if value is not None else ""
            said += " (default %s)" % default if default is not None else (" (its own default)" if value is not None else "")
            where = " at %s:%s" % (entry["path"], entry["line"]) if entry.get("path") and entry.get("line") else ""
            lines.append("- `%s` `%s`%s%s: %s" % (entry.get("method"), entry.get("name"), said, where, entry.get("reason")))
    not_methods = (rule or {}).get("not_methods") or []
    if not_methods:
        lines.append("Not methods:")
        lines.extend("- `%s`: %s" % (entry.get("name"), entry.get("why")) for entry in not_methods)
    return "\n".join(lines)


def _with_code_rule(ask, rule):
    ask.question = "%s\n\n%s" % (ask.question.rstrip(), code_rule_text(rule))
    ask.code_rule = rule
    return ask


def ticket_asks(ticket, difficulty, author_model, ticket_path, commit=None, outputs=(), rung=None, no_diff=False, code_rule=None):
    """The verdicts one done ticket earns: its own quality criteria, and an independent read.

    `rung` is the rung the attempt that wrote the work ran on, carried into each verdict's journal event
    (decision 16); the read a ticket earns stays keyed to its difficulty level, not its rung.

    Decision 11 lists the two separately, so a difficulty-4 ticket with quality criteria earns
    both: the criteria it set itself, and a read of the result by someone who did not write it.
    Both have to pass before the ticket is accepted. A difficulty-3 ticket is read as its diff, a
    difficulty-4 or -5 ticket as its result; a difficulty-1 or -2 ticket earns a verdict only
    through its own quality criteria. A `docs` ticket's independent read is the docs read at every
    difficulty, one read of the site for clarity and completeness (decision 13). `no_diff` is a ticket whose integration added no commit of its
    own (its work is findings, say): its commit would be whatever `main` stood at, so it is read as
    its result instead of as a diff that is not its own.

    `code_rule` is the ticket's `parameters` reasons and `not_methods` (ticket 107), which the verifier's existing verdict
    judges: the independent read carries them, else the quality verdict; a ticket that earns neither earns a read of its
    diff for them, since nobody else would judge the reasons.
    """
    identifier = ticket["id"]
    subject = str(ticket_path)
    paths = [subject] + [str(item) for item in outputs or ()]
    asks = []
    criteria = [str(item) for item in ((ticket.get("acceptance") or {}).get("quality") or []) if str(item).strip()]
    if criteria:
        asks.append(Ask(
            subject_kind="ticket", subject=subject,
            question="Does the work of ticket %d meet the quality criteria the ticket set?\n%s"
                     % (identifier, "\n".join("%d. %s" % (number, text)
                                              for number, text in enumerate(criteria, start=1))),
            paths=paths,
            scope_limit="Only the %s above, and only about ticket %d's work. A problem elsewhere "
                        "in the project is a minor finding at most, never a fail."
                        % ("one criterion" if len(criteria) == 1 else "%d criteria" % len(criteria),
                           identifier),
            verdict_type=QUALITY, author_model=author_model, ticket=identifier, rung=rung,
        ))
    if ticket.get("kind") == DOCS:
        # The site's one independent read, whatever the difficulty (decision 13): the machine checks
        # have said it builds and is complete by inventory; only a reader can say it can be used.
        asks.append(Ask(
            subject_kind="ticket", subject=subject,
            question=DOCS_QUESTION % identifier,
            paths=paths + [path for path in DOCS_READ_PATHS if path not in paths],
            scope_limit=DOCS_SCOPE,
            verdict_type=DOCS_READ, author_model=author_model, ticket=identifier, rung=rung,
        ))
        return asks
    read = DIFFICULTY_VERDICTS.get(difficulty)
    if read == DIFF and no_diff:
        read = RESULT
    if read == DIFF:
        asks.append(Ask(
            subject_kind="ticket", subject=subject,
            question="Does the diff of commit %s do what ticket %d asked, and do it correctly?"
                     % ((commit or "HEAD")[:12], identifier),
            paths=paths,
            scope_limit="Read the diff itself with `git show %s`, not the files as they now stand, "
                        "and judge only what that diff changed, against the ticket."
                        % (commit or "HEAD"),
            verdict_type=DIFF, author_model=author_model, ticket=identifier, rung=rung,
        ))
    elif read == RESULT:
        asks.append(Ask(
            subject_kind="ticket", subject=subject,
            question="Do ticket %d's own artifacts support what its result claims, and does the "
                     "work answer the ticket?" % identifier,
            paths=paths,
            scope_limit="The ticket's `## Result` section and the artifacts it wrote, at the paths "
                        "listed. A claim the artifacts do not carry is a finding at the path where "
                        "you looked for it.",
            verdict_type=RESULT, author_model=author_model, ticket=identifier, rung=rung,
        ))
    if code_rule and ((code_rule.get("parameters") or []) or (code_rule.get("not_methods") or [])):
        carrier = next((ask for ask in asks if ask.verdict_type in (DIFF, RESULT)), None) or (asks[0] if asks else None)
        if carrier is None:
            carrier = Ask(
                subject_kind="ticket", subject=subject,
                question="Do the reasons ticket %d's result gives for its parameters and its not_methods hold against "
                         "its diff, commit %s?" % (identifier, (commit or "HEAD")[:12]),
                paths=paths,
                scope_limit="Only the items listed below, read against the diff with `git show %s`." % (commit or "HEAD"),
                verdict_type=RESULT if no_diff else DIFF, author_model=author_model, ticket=identifier, rung=rung,
            )
            asks.append(carrier)
        _with_code_rule(carrier, code_rule)
    return asks


def owed_asks(ticket, difficulty, author_model, commit, passed, rung=None, no_diff=False, code_rule=None):
    """What a done ticket is still owed: `(earned, owed)`, the verdicts it earned and the ones the journal does not hold as passed.

    `passed` is the verdict types the journal holds as passed since the ticket was last done
    (`replay.View.passed`). A ticket that earned verdicts and is owed none is owed its acceptance, which a
    conductor killed between the last pass and `ticket_accepted` never journaled. The conductor's restart
    and the tick both read it here, so what the tick relaunches a conductor for is what that conductor then does.

    A harness ticket that works on a branch of the harness repository (a global change, ticket 45) earns
    none and is owed none: it is never integrated into the project, and the owner reads the branch.
    """
    if works_in_the_harness(ticket):
        return [], []
    earned = ticket_asks(ticket, difficulty, author_model, ticket_relative_path(ticket), commit=commit,
                         outputs=ticket.get("outputs") or [], rung=rung, no_diff=no_diff, code_rule=code_rule)
    passed = set(passed or ())
    return earned, [ask for ask in earned if ask.verdict_type not in passed]


# --- the kill argument (decision 11; BRIEF 3.2, 13.3) ------------------------------------------

MEMO_QUESTION = "What is the single strongest case for rejecting this work?"
MEMO_SCOPE = (
    "Write the rejection a hostile reviewer would write, from the paths below and nothing else. "
    "Every objection is a finding at the path and the locator you read it at, at the severity you "
    "would defend. `pass` is false when you have a case to make, and true only when the paths "
    "leave you nothing to argue against. Do not soften the case, and do not invent an objection "
    "the paths do not support: an objection that turns out to be answered costs the memo its "
    "credibility, not the work its claim."
)
ADJUDICATION_QUESTION = "Does the rejection memo hold, point by point, against the artifacts?"
ADJUDICATION_SCOPE = (
    "Take each point of the memo in turn against the paths below. A point the artifacts answer "
    "does not stand and is not your finding. A point they do not answer stands: it is a finding at "
    "the locator you looked at. `pass` is true when nothing stands that the work still claims."
)

WRITING_TITLE = "Scope the claims the kill argument left standing"
WRITING_ROLE = "writer"
WRITING_DIFFICULTY = 3


def kill_argument(paths, *, project, author_model, subject_kind="paper", subject=None,
                  harness_root=HARNESS_ROOT, policy=None, ledger=None, cwd=None, fall_back=None):
    """The two-thread gate: one session writes the memo, a second adjudicates it, one verdict comes back.

    Both threads are the verifier role on separate fresh sessions, on the model `policy.verifier`
    gives for the author's, so neither carries the author's context and neither carries the other's.
    Whether a verifier on Fable falls back to Opus is decided once, before the memo is spent, and both
    threads run on that model (decision 15). The adjudication is the
    one verdict: the memo is the case against the work rather than a judgment of it, and it is
    not journaled as a verdict, though its session is on disk in `memo/` beside the
    adjudication's. A fail scopes the claims down rather than blocking forever: a `writing`
    ticket is filed with the points that still stand, and the writer takes it from there.

    A memo that finds nothing is an answer, not a failure. Its `pass` is then true, the
    adjudicating thread is told the memo had no case, and the gate passes, because the strongest
    rejection anyone could write against these paths was empty.
    """
    paths = [str(item) for item in (paths or [])]
    if not paths:
        raise GateError("a kill argument is run against paths; none were given")
    project = Path(project).resolve()
    subject = str(subject or paths[0])
    run_dir = verdict_dir(project, subject_kind, subject)
    policy = policy_for(project, harness_root) if policy is None else policy
    fall_back = _fall_back_for(project, policy, author_model, fall_back,
                               "the kill argument on the %s %s" % (subject_kind, subject))
    common = dict(project=project, author_model=author_model, harness_root=harness_root,
                  policy=policy, cwd=cwd, fall_back=fall_back)
    memo = take_verdict(subject_kind, subject, MEMO_QUESTION, paths, MEMO_SCOPE,
                        verdict_type=KILL_MEMO, run_dir=run_dir / "memo", **common)
    adjudication = verdict(subject_kind, subject, ADJUDICATION_QUESTION, paths, ADJUDICATION_SCOPE,
                           verdict_type=KILL_ARGUMENT, run_dir=run_dir / "adjudication",
                           memo=memo.findings, ledger=ledger, **common)
    if not adjudication.passed:
        _file_writing_ticket(project, ledger, adjudication, paths, memo)
    return adjudication


def _file_writing_ticket(project, ledger, adjudication, paths, memo):
    """File the `writing` ticket a failed kill argument scopes the claims down with; returns its id.

    The touch set is the subject itself, because scoping a claim down is an edit to the document
    that makes it. A subject that already has an open one gets no second: the open ticket is the
    one the next draft answers, and its id is returned.
    """
    standing = open_writing_ticket(project, adjudication.subject)
    if standing is not None:
        return standing
    body = "\n".join([
        "## What the kill argument left standing",
        "",
        "The rejection memo was written by verifier session `%s` (%s) and adjudicated by verifier "
        "session `%s` (%s), which read the paths below and found that these points still stand. "
        "Scope the claims to what the artifacts support, or add the evidence the point asks for; "
        "do not answer a point by asserting it away."
        % (memo.session_id, memo.model, adjudication.session_id, adjudication.model),
        "",
        findings_text(adjudication.findings),
        "",
        "## The paths both threads read",
        "",
    ] + ["- `%s`" % item for item in paths])
    return file_writing_ticket(
        # A subject under research/ (the paper, a report) is written by code, so the scope-down
        # carries no touch of it; the correction travels in the result the writer is given.
        project, ledger, title=WRITING_TITLE, touches=[] if touches_problems([adjudication.subject], project) else [adjudication.subject],
        inputs=list(paths),
        quality=["Does every point the kill argument left standing now have either the "
                 "evidence it asked for or a claim scoped down to what the artifacts support?"],
        origin=adjudication.subject,
        demo="The kill argument runs again on %s and these points no longer stand." % adjudication.subject,
        body=body,
    )


def open_writing_ticket(project, origin):
    """The id of an open `writing` ticket filed with `origin`, or None: what keeps a gate from filing one twice."""
    for fields in read_tickets(project):
        if fields["kind"] == "writing" and fields.get("origin") == origin and fields["status"] not in SATISFIED + ("parked",):
            return fields["id"]
    return None


def file_writing_ticket(project, ledger, *, title, touches, inputs, quality, origin, demo, body):
    """File one `writing` ticket on the verifier's behalf and journal `ticket_created`; returns its id.

    What files one: a failed kill argument, and a sampled report claim its artifacts do not support
    (ticket 40). The verifier is the ticket's author: no planner, worker, decider, human, or evolve
    pass proposed it, and naming one of them would be a lie in the file a person reads. `body` is
    the markdown after the `## Demo` section, which this writes from `demo`.
    """
    project = Path(project).resolve()
    problems = touches_problems(touches, project)
    if problems:
        # The planner's own rule (decision 1): a touch under `research/` is one the hook denies,
        # so the ticket could never be done. Nothing is written.
        raise GateError("a scope-down titled %r cannot be filed: %s" % (title, "; ".join(problems)))
    ledger = ledger_for(ledger or project)
    identifier = next_id(project)
    fields = {
        "id": identifier,
        "title": title,
        "kind": "writing",
        "difficulty": WRITING_DIFFICULTY,
        "status": "open",
        "blocked_by": [],
        "touches": list(touches),
        "role": WRITING_ROLE,
        "skills": [],
        "inputs": list(inputs),
        "outputs": list(touches),
        "acceptance": {"machine": [], "quality": list(quality)},
        "context_pack": list(inputs),
        "origin": origin,
        "proposed_by": VERIFIER,
        "demo": demo,
    }
    text = "\n".join(["## Demo", "", demo, "", body.strip("\n")]) + "\n"
    write_ticket(ledger, fields, text)
    ledger.append_event(TICKET_CREATED, {
        "ticket": identifier, "kind": fields["kind"], "proposed_by": VERIFIER,
        "origin": fields["origin"], "blocked_by": [],
    }, ticket=identifier)
    return identifier
