"""The consultant (Implementation Decisions 9; map ticket 41): one question about one dossier.

One role definition, two entry points. From code, `ask` launches the `consultant` role through
the launcher with the question as the prompt, the dossier directory `research/refs/<slug>` as
`--add-dir`, the read-only tools, and the `consultant_answer` schema; `wayline consult <slug>
"<question>"` is that function on the command line, and the only form a worker calls. In a
Workflow script the same role is `agent(question, {agentType: 'consultant', schema})`, whose
answer the script returns to code (`workflows/absorb.js` does, for a reader's clarification
question), and `record_exchange` records it the same way.

Every answer is validated again in code, including the one rule the schema leaves out: an answer
read in the source names a locator. The ledger appends the exchange to `refs/<slug>/qa_log.md`
and journals `consulted`; `promote_requested: true` goes to `dossier.promote` with the
`consultant_question` trigger, which promotes inside the phase's budget or opens a decision
ticket beyond it. A question asked under `WAYLINE_TICKET` counts against that ticket, and the
question past `policy.consultant.max_questions_per_ticket` is refused before a session starts.

A consult launched from inside a worker inherits the worker's environment, so the request blanks
the two variables that are the worker's alone: `TICKET_ACCEPTANCE_FILE`, which would make the
stop guard hold the consultant until the worker's acceptance ran, and `TICKET_TOUCHES`, which
would let the guards pass writes the consultant has no business making.
"""

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

from wayline import HARNESS_ROOT, gates, pacing, worker
from wayline.cli import parse_args
from wayline.dossier import CONSULTANT_QUESTION, LEVEL_1, LEVEL_2, REFS, DossierError, promote, read_dossier
from wayline.jsonschema import ValidationError, load_schema, validate
from wayline.ledger import CONSULTED, LedgerError, ledger_for, now_ts
from wayline.project import ProjectError, find_project, policy_for

__all__ = [
    "ROLE", "SCHEMA", "QA_LOG", "SESSIONS", "ConsultError", "ConsultRefused",
    "questions_asked", "question_limit", "consult_prompt", "consult_request", "check_answer",
    "record_exchange", "ask", "consult_command",
]

ROLE = "consultant"
SCHEMA = "consultant_answer"
QA_LOG = "qa_log.md"
SESSIONS = "sessions/consult"      # research/sessions/consult/<slug>/<n>/
TIER = ("sonnet", "medium")        # the fallback when a policy carries no `roles.consultant`
MAX_TURNS = 20
MAX_MINUTES = 10
CLI_BY = "cli"

_SPACES = re.compile(r"\s+")

RESUME = (
    "The answer you returned could not be used: %s. Return it again through the structured output; "
    "an answer read in the dossier's files names at least one locator, and one the files do not "
    "carry says not_in_source: true."
)


class ConsultError(ValueError):
    """A question the consultant could not answer usably: no dossier, no valid answer, no session."""


class ConsultRefused(ConsultError):
    """The question past the ticket's `policy.consultant.max_questions_per_ticket`."""


# --- the count -----------------------------------------------------------------------------------


def questions_asked(project_or_ledger, ticket):
    """How many `consulted` events the journal holds for `ticket`."""
    events, _ = ledger_for(project_or_ledger).read_events()
    return sum(1 for event in events if event.get("event") == CONSULTED and event.get("ticket") == ticket)


def question_limit(policy):
    return int(((policy or {}).get("consultant") or {}).get("max_questions_per_ticket", worker.CONSULT_MAX))


# --- the request ---------------------------------------------------------------------------------


def consult_prompt(slug, question, dossier_dir, level):
    """The question first, as the spec's launch line has it, then where the dossier is."""
    return (
        "%s\n\n"
        "[wayline: this question is about the paper `%s`. Its dossier is the directory `%s`, at level %d; "
        "answer from the files in it alone, and return the consultant_answer through the structured output.]\n"
    ) % (question.strip(), slug, dossier_dir, level)


def _session_dir(project, slug):
    """The first free `research/sessions/consult/<slug>/<n>`, claimed by creating it."""
    base = Path(project) / "research" / SESSIONS / slug
    base.mkdir(parents=True, exist_ok=True)
    number = 1
    while True:
        candidate = base / str(number)
        try:
            candidate.mkdir()
            return candidate
        except FileExistsError:
            number += 1


def consult_request(project, slug, question, level, harness_root=None, policy=None):
    """The `LaunchRequest` for one question: the consultant's role, tier, tools, and schema."""
    project = Path(project).resolve()
    harness_root = Path(harness_root or HARNESS_ROOT).resolve()
    policy = policy if policy is not None else policy_for(project, harness_root)
    tier = ((policy.get("roles") or {}).get(ROLE) or {})
    model, effort = tier.get("model") or TIER[0], tier.get("effort") or TIER[1]
    role = worker.read_role(ROLE, harness_root, project)
    dossier_dir = project / "research" / REFS / slug
    run_dir = _session_dir(project, slug)
    return worker.LaunchRequest(
        role=role.name, model=model, effort=effort,
        prompt=consult_prompt(slug, question, dossier_dir, level),
        agent_json=role.agent_json(model, effort, max_turns=MAX_TURNS),
        allowed_tools=list(role.allowed_tools), disallowed_tools=list(role.disallowed_tools),
        settings_path=gates.write_worker_settings(run_dir / "settings.json", harness_root),
        add_dirs=[dossier_dir], cwd=project,
        env={"WAYLINE_PROJECT": str(project), "WAYLINE_RUN": str(run_dir),
             "TICKET_ACCEPTANCE_FILE": "", "TICKET_TOUCHES": ""},
        schema_path=harness_root / "schemas" / (SCHEMA + ".json"),
        max_minutes=MAX_MINUTES,
    )


# --- the answer ----------------------------------------------------------------------------------


def check_answer(value):
    """The problems with an answer, as strings; empty when code accepts it."""
    if not isinstance(value, dict):
        return ["the answer is %s, not an object" % type(value).__name__]
    problems = ["%s: %s" % (error.path, error.message) for error in validate(value, load_schema(SCHEMA))]
    if not problems and not value["not_in_source"] and not value["locators"]:
        problems.append("an answer read in the source names at least one locator; this one names none")
    return problems


def _one_line(text):
    return _SPACES.sub(" ", str(text)).strip()


def _log_line(ts, by, session_id, question, answer):
    notes = [ts, by]
    if session_id:
        notes.append("session %s" % session_id)
    notes.append("confidence %s" % answer["confidence"])
    if answer["not_in_source"]:
        notes.append("not in source")
    if answer["promote_requested"]:
        notes.append("promotion requested")
    locators = "; ".join(_one_line(locator) for locator in answer["locators"]) or "none"
    return "- %s. Q: %s A: %s Locators: %s" % (" · ".join(notes), _one_line(question), _one_line(answer["answer"]), locators)


QA_HEADER = (
    "# Questions asked about `%s`\n\n"
    "One line per exchange with the consultant, appended by the ledger: when, who asked, the session, "
    "the confidence, the question, the answer, and where the answer was read.\n\n"
)


def _refusal(ticket, asked, limit):
    return ConsultRefused("ticket %s has asked %d question(s), the most policy.consultant.max_questions_per_ticket (%d) allows; "
                          "work from what the answers and the context pack say" % (ticket, asked, limit))


def record_exchange(project_or_ledger, slug, question, answer, by, session_id=None, ticket=None, limit=None):
    """Append one validated exchange to `qa_log.md`, journal `consulted`, and act on a promotion request.

    Returns the promotion outcome of `dossier.promote`, or None when none was requested. Raises
    ConsultError for an answer code does not accept, and ConsultRefused when `ticket` already has
    `limit` questions recorded, both before anything is written. The count, the records, and the
    promotion share one hold of the lock, so two consults that finish together cannot both record a
    sixth question, nor both spend the phase's last level-2 slot.
    """
    problems = check_answer(answer)
    if problems:
        raise ConsultError("the consultant's answer about %s was not usable: %s" % (slug, "; ".join(problems)))
    ledger = ledger_for(project_or_ledger)
    relpath = "%s/%s/%s" % (REFS, slug, QA_LOG)
    digest = hashlib.sha256(question.encode("utf-8")).hexdigest()
    with ledger.lock():
        if ticket is not None and limit is not None:
            asked = questions_asked(ledger, ticket)
            if asked >= limit:
                raise _refusal(ticket, asked, limit)
        if not ledger.path(relpath).exists():
            ledger.write_markdown(relpath, QA_HEADER % slug)
        ledger.append_line(relpath, _log_line(now_ts(), by, session_id, question, answer))
        ledger.append_event(CONSULTED, {
            "slug": slug, "by": by, "question_sha256": digest,
            "promote_requested": bool(answer["promote_requested"]), "session_id": session_id,
        }, ticket=ticket, session_id=session_id)
        if not answer["promote_requested"]:
            return None
        return promote(ledger, slug, CONSULTANT_QUESTION, ticket=ticket, detail="question %s" % digest[:12])


def _read_level(dossier):
    """The level the dossier has been read to: a promotion to level 2 counts once the read has written `l2`."""
    level = dossier.get("level", 0)
    return level if level < LEVEL_2 or dossier.get("l2") else LEVEL_1


def ask(project, slug, question, ticket=None, launcher=None, resumer=None, harness_root=None, ledger=None):
    """Ask the consultant one question about `slug`; returns `{answer, session_id, promotion, asked, limit}`.

    `ticket` is the asking ticket's id, whose questions are counted; None asks from outside a
    ticket, uncounted. `launcher` and `resumer` default to the seam's; a caller passing its own
    launcher passes its resumer with it, or an unusable answer is not resumed.
    """
    project = Path(project).resolve()
    ledger = ledger_for(ledger if ledger is not None else project)
    if not isinstance(question, str) or not question.strip():
        raise ConsultError("a consultant question is a non-empty string")
    try:
        dossier = read_dossier(ledger, slug)
    except DossierError as failure:
        raise ConsultError(str(failure)) from None
    policy = policy_for(project, harness_root)
    limit = question_limit(policy)
    asked = questions_asked(ledger, ticket) if ticket is not None else None
    if ticket is not None and asked >= limit:
        raise _refusal(ticket, asked, limit)
    request = consult_request(project, slug, question, _read_level(dossier), harness_root=harness_root, policy=policy)
    launcher = launcher or worker.launch
    resumer = resumer if resumer is not None else (worker.resume if launcher is worker.launch else None)
    try:
        envelope = launcher(request)
    except worker.LaunchError as failure:
        raise ConsultError("the consultant could not be launched: %s" % failure) from None
    problems = check_answer(envelope.structured_output) if envelope.valid else (envelope.errors or ["no structured output"])
    if problems:
        _raise_on_limit(envelope, request)  # a refused session is never resumed
        resumed = _resume_once(request, envelope, problems, resumer)
        if isinstance(resumed, worker.Envelope):
            envelope, problems = resumed, []
        else:
            problems = resumed
    if problems:
        raise ConsultError("the consultant returned no usable answer about %s: %s" % (slug, "; ".join(problems)))
    by = "worker:%s" % ticket if ticket is not None else CLI_BY
    promotion = record_exchange(ledger, slug, question, envelope.structured_output, by, envelope.session_id, ticket,
                                limit=limit if ticket is not None else None)
    return {"slug": slug, "answer": envelope.structured_output, "session_id": envelope.session_id,
            "promotion": promotion, "asked": None if ticket is None else asked + 1, "limit": limit, "ticket": ticket}


def _raise_on_limit(envelope, request):
    """Say so plainly when a usage window refused the consultant, so the asker waits rather than rephrases."""
    limit = pacing.hit_limit(envelope, worker.stderr_of(envelope), model=request.model)
    if limit is not None:
        window = "Fable's weekly window" if limit.model == pacing.FABLE else "the %s window" % limit.window
        raise ConsultError("the usage limit refused the consultant (%s); ask again once the window allows" % window)


def _resume_once(request, envelope, problems, resumer):
    """One resume with the reason; the resumed envelope when its answer is usable, else the problems."""
    if resumer is None or not envelope.session_id:
        return problems
    try:
        resumed = resumer(request, envelope.session_id, RESUME % "; ".join(problems))
    except worker.LaunchError as failure:
        return problems + ["the resume could not run: %s" % failure]
    again = check_answer(resumed.structured_output) if resumed.valid else (resumed.errors or ["no structured output"])
    return resumed if not again else problems + ["and after one resume: %s" % "; ".join(again)]


# --- the verb ------------------------------------------------------------------------------------


def consult_command(args):
    """`wayline consult <slug> "<question>" [--json] [--project <path>]`."""
    parser = argparse.ArgumentParser(prog="wayline consult", description="ask the consultant one question about one dossier")
    parser.add_argument("slug", help="the reference whose dossier answers the question")
    parser.add_argument("question", help="the one question, quoted")
    parser.add_argument("--project", help="the project; WAYLINE_PROJECT or the active one by default")
    parser.add_argument("--json", action="store_true", help="print the answer object as JSON")
    options, code = parse_args(parser, args)
    if options is None:
        return code
    raw_ticket = os.environ.get("WAYLINE_TICKET", "").strip()
    if raw_ticket and not raw_ticket.isdigit():
        print("wayline consult: WAYLINE_TICKET is %r, not a ticket id" % raw_ticket, file=sys.stderr)
        return 2
    ticket = int(raw_ticket) if raw_ticket else None
    try:
        project = find_project(options.project or os.environ.get("WAYLINE_PROJECT") or None)
        report = ask(project, options.slug, options.question, ticket=ticket)
    except (ConsultError, ProjectError, DossierError, ValidationError, LedgerError, worker.RoleError, OSError) as failure:
        print("wayline consult: %s" % failure, file=sys.stderr)
        return 1
    if options.json:
        print(json.dumps(report["answer"], ensure_ascii=False, indent=2))
    else:
        print(_render(report))
    return 0


def _render(report):
    answer = report["answer"]
    lines = [
        "answer      %s" % answer["answer"],
        "locators    %s" % ("; ".join(answer["locators"]) or "none"),
        "confidence  %s%s" % (answer["confidence"], ", not in source" if answer["not_in_source"] else ""),
    ]
    promotion = report["promotion"]
    if promotion is not None:
        if promotion.get("promoted"):
            lines.append("promotion   %s promoted to level 2 (phase %s, %s of %s)" % (report["slug"], promotion["phase"], promotion["used"], promotion["limit"]))
        elif promotion.get("decision_ticket"):
            lines.append("promotion   beyond the phase's budget: decision ticket %s opened" % promotion["decision_ticket"])
        else:
            lines.append("promotion   not needed: %s" % promotion.get("reason", "no reason given"))
    if report["ticket"] is not None:
        lines.append("questions   %d of %d asked by ticket %s" % (report["asked"], report["limit"], report["ticket"]))
    return "\n".join(lines)
