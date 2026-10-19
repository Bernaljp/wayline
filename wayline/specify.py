"""Specify, phase P3 (Implementation Decisions 10 and 11; BRIEF 6.1). Built by ticket 33.

From the settled decisions, the position memo, the objectives, and the knowledge base, the planner
drafts the research spec; code checks its structure, one independent verdict checks that every claim
has an experiment and every experiment defends a claim, and the owner confirms it before planning.

**The draft.** `wayline specify` drafts once one objective is open (decision 17, ticket 81): that
objective may be the question to answer first, not the project's end. With none open it refuses and
names the question the conversation asks, "what should the project answer first?". It launches the
`planner` role in its specify protocol through the worker launcher (seam 1), on `policy.roles.planner`,
with `spec.json` as its schema and, in its prompt, the open objectives with their measures, the records
the decider reads (`DECISIONS.md`, `POSITION.md`, the L0 and L1 records, and the query pack), the grill's
open questions, and whatever the owner or the gates asked to change. The session writes nothing: code
writes what it returns as `research/spec.json` and renders `research/SPEC.md` from it, and the pair is
the spec. The spec carries `summary`, about 120 words on what the project is, which the general report
opens with, and every claim its `objectives`, the open objectives it answers (none for a claim no
objective asked for).

**The two gates.** The Type-A checks (`check_draft`) are the structure: every section present and
non-empty, every id unique and every reference resolving, every claim with at least one experiment
that names it back, every experiment naming a claim, every metric naming a script, every anti-claim
naming the experiment that would confirm it, every objective a claim names open, every open objective
answered by at least one claim, and every goal's metric among the metrics. A draft that
fails them is returned to the same planner session once with the failures; a second failure ends the
call and writes nothing. The Type-B gate is one verifier session (`gates.verdict`, `spec_coverage`)
on the spec as written; a fail returns the draft to the planner once with the findings, and the
redraft is checked and judged again. A second fail leaves the spec written and unconfirmed, with both
verdicts journaled, and the next `wayline specify` drafts it anew with the last findings. A spec
written and never judged (its verifier stopped by a window) is judged, not redrafted, on the next run.
The phase never moves back.

**The confirmation**, by autonomy. Under `checkpoints` a decision ticket "Confirm the spec" is opened
with `blocking: all` and origin `specify: confirm research/SPEC.md at <sha>`; the phase advances on its
answer, whoever gives it (`wayline answer`, the dashboard, the file). Under `autonomous` the same ticket
is opened and the decider answers it at once (`decider.decide_ticket`); a refusal leaves it to the owner.
Under `interactive` no ticket is opened: the session that ran the verb asks the owner, and records the
answer with `wayline specify confirm` or `wayline specify revise "<what to change>"`, journaled as a
`decision` with no ticket whose answer leads with `spec <sha>:`. An answer that confirms journals
`phase P3 -> P4`; any other answer is what to change, and the next `wayline specify` redrafts with it
(and stops, spending no verdict, when the redraft comes back unchanged). An answer confirms only when it
says nothing else ("ok, but drop C3" is a change), and the last answer given to a version wins, so the
owner can still confirm a version they first sent back.

`spec_state` reads all of this back from the files and the journal, so the verb is safe to run again
at any point: it drafts, asks, waits, or advances, whichever the ledger says is owed.
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from wayline import HARNESS_ROOT, decider, decisions, gates, grill, objectives, pacing, sections, worker
from wayline.cli import parse_args
from wayline.jsonschema import ValidationError, check, load_schema
from wayline.ledger import DECISION, PHASE, Ledger, LedgerError
from wayline.project import ProjectError, find_project, journal_written_answers, policy_for, read_harness
from wayline.project import answer as answer_ticket
from wayline.tickets import DECISION as DECISION_KIND, TicketError, answer_section, filename, read_ticket, read_tickets, tickets_dir
from wayline.worker import protocol_for  # the planner's cut, first written here and kept under its name

__all__ = [
    "PLANNER", "SPEC_SCHEMA", "SPEC_MD", "SPEC_JSON", "SECTIONS", "SpecifyError", "planner_tier", "protocol_for",
    "check_draft", "render_spec", "check_spec", "spec_sha", "spec_state", "specify_prompt", "draft_spec", "judge_spec", "specify",
    "confirm", "advance", "render_report", "specify_command", "confirms", "what_to_change", "move_phase", "context_cap", "current_phase",
    "PlannerSession", "falls_back_now", "session_dir",
]

PLANNER = "planner"
SPEC_SCHEMA = "spec"
SPEC_MD = "SPEC.md"
SPEC_JSON = "spec.json"
GAP_BY = "step:specify"             # who wrote the Introduction's passages on the gap (decision 17)
SUBJECT = "research/" + SPEC_MD
SESSIONS = "sessions/specify"      # research/sessions/specify/<n>
PLANNER_BUDGET = "large"           # policy.budget: the planner is a large-budget role (policy.roles, opus xhigh)
SPECIFY_PHASE, PLAN_PHASE = "P3", "P4"
PHASES = ("P0", "P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8")
ORIGIN = "specify: confirm %s at %%s" % SUBJECT
TITLE = "Confirm the spec"
CONFIRM = "confirm"
REVISE = "revise: <what to change, in a sentence>"
ANSWER_PREFIX = "spec %s: "        # the interactive answer's `decision`, keyed by the spec it answers
# An answer confirms the spec when it holds one of these words and nothing but these and the fillers
# below ("yes, go ahead", "I confirm the spec", "looks good"); any other answer is what to change, so
# "ok, but drop C3" is a change and never a confirmation that loses it.
CONFIRMING = frozenset(("confirm", "confirmed", "confirms", "yes", "ok", "okay", "approve", "approved", "accept", "accepted",
                        "lgtm", "good", "fine"))
FILLERS = frozenset(("i", "it", "the", "this", "spec", "go", "ahead", "looks", "as", "is", "please", "all"))
INTERACTIVE, CHECKPOINTS, AUTONOMOUS = "interactive", "checkpoints", "autonomous"

# The sections of SPEC.md, in order: (the key in spec.json, the heading). The summary leads, then the
# question, because a spec a reader cannot place is not read.
SECTIONS = (
    ("summary", "Summary"),
    ("question", "Question"),
    ("claims", "Claims"),
    ("anti_claims", "Anti-claims"),
    ("methods", "Methods"),
    ("experiments", "Experiments"),
    ("baselines", "Baselines"),
    ("data", "Data"),
    ("metrics", "Metrics"),
    ("success_criteria", "Success criteria"),
    ("budgets", "Budgets"),
    ("out_of_scope", "Out of scope"),
    ("risks", "Risks"),
    ("seams", "Seams"),
)

VERDICT_QUESTION = "Does every claim of the spec have at least one experiment that tests it, and does every experiment defend a claim?"
VERDICT_SCOPE = (
    "Judge only the mapping between the claims (and anti-claims) and the experiments in research/SPEC.md: whether each "
    "claim's experiments would actually test it, whether each experiment actually bears on the claims it names, and "
    "whether each anti-claim's experiment would confirm it. Read DECISIONS.md and OBJECTIVES.md only to see what the "
    "claims must answer. Not the science's merit, the budgets, the prose, or anything a later phase decides. The hex after "
    "`at` in the subject is the first twelve of research/spec.json's sha256, written by the harness beside the file "
    "you read; it needs no checking."
)
VERDICT_PATHS = ("research/SPEC.md", "research/spec.json", "research/DECISIONS.md", "research/OBJECTIVES.md")

# Specify drafts once one objective is open (decision 17); with none, the conversation asks this before anything else.
FIRST_QUESTION = "what should the project answer first?"
NO_OBJECTIVE = ("no objective is open, so there is nothing for the spec to answer: ask the owner \"%s\" and record the "
                "answer with wayline objective add \"<question>\", then run wayline specify again" % FIRST_QUESTION)

RESUME_INVALID = (
    "The spec you returned could not be read: %s. Return the whole spec again through the structured output, as the "
    "spec schema asks."
)
RESUME_CHECKS = (
    "The harness's structural checks failed on the spec you returned:\n\n%s\n\nChange what they name, keep the rest, and "
    "return the whole spec again through the structured output."
)
RESUME_FINDINGS = (
    "An independent verifier read the spec as written (research/SPEC.md) and failed it on whether every claim has an "
    "experiment and every experiment defends a claim. Its findings:\n\n%s\n\nChange what they name, keep the rest, and "
    "return the whole spec again through the structured output."
)


class SpecifyError(ValueError):
    """A spec nobody could draft: no open objective, a role that cannot be read, a draft that failed its gates twice."""

    def __init__(self, message, failures=()):
        super().__init__(message)
        self.failures = list(failures)


# --- the tier and the protocol ------------------------------------------------------------------------


def planner_tier(policy, fall_back=False):
    """The `(model, effort, fallback_from)` the planner runs at: `policy.roles.planner`, Opus in Fable's place when `fall_back`."""
    entry = ((policy or {}).get("roles") or {}).get(PLANNER) or {}
    model, effort = entry.get("model"), entry.get("effort")
    if model not in worker.MODEL_ALIASES or effort not in worker.EFFORTS:
        raise SpecifyError("policy.roles.planner names no model and effort the launcher knows; got %r" % (entry,))
    if model == pacing.FABLE and fall_back:
        return pacing.OPUS, effort, pacing.FABLE
    return model, effort, None


def falls_back_now(project, policy, fall_back, what="the planner's specify session"):
    """Whether this planner launch falls back to Opus now: the caller's word, else the journal's hold, and only for a planner on Fable."""
    if fall_back is not None:
        return bool(fall_back)
    if planner_tier(policy)[0] != pacing.FABLE:
        return False
    return gates.fallback_now(project, what)


# --- the Type-A checks --------------------------------------------------------------------------------


def _one_line(text):
    return " ".join(str(text or "").split())


def _ids(items, key="id"):
    return [item.get(key) for item in items if isinstance(item, dict)]


def _duplicates(values):
    seen, repeated = set(), []
    for value in values:
        if value in seen and value not in repeated:
            repeated.append(value)
        seen.add(value)
    return repeated


def check_draft(draft, objectives=None):
    """The Type-A checks on a spec draft; returns the failures, each one line, empty when it passes.

    The schema is checked first, because the rest reads the fields it promises. `objectives` is the
    project's `objectives.json` records (`objectives.read_objectives`), None when the caller has none to
    hold the draft to: every objective a claim names must be open, every open objective must be
    answered by at least one claim, and every open goal's metric must be among the spec's metrics.
    """
    try:
        check(draft, load_schema(SPEC_SCHEMA), name="the spec")
    except ValidationError as failure:
        return [str(failure)]
    failures = []
    for key, heading in SECTIONS:
        value = draft[key]
        if key == "budgets":
            if all(value.get(name) is None for name in ("gpu_hours", "wallclock_hours", "usage_windows")) and not _one_line(value.get("notes")):
                failures.append("section %s is empty: give at least one budget or a note on why there is none" % heading)
        elif not value or (isinstance(value, str) and not value.strip()):
            failures.append("section %s is empty" % heading)
    for key, label in (("claims", "claim"), ("anti_claims", "anti-claim"), ("experiments", "experiment"),
                       ("baselines", "baseline"), ("data", "data item")):
        for repeated in _duplicates(_ids(draft[key])):
            failures.append("the %s id %s is used more than once" % (label, repeated))
    for repeated in _duplicates(_ids(draft["metrics"], "name")):
        failures.append("the metric %s is defined more than once" % repeated)
    claims = {item["id"]: item for item in draft["claims"]}
    experiments = {item["id"]: item for item in draft["experiments"]}
    baselines, data = set(_ids(draft["baselines"])), set(_ids(draft["data"]))
    metrics = set(_ids(draft["metrics"], "name"))
    for claim in draft["claims"]:
        if not claim["experiments"]:
            failures.append("claim %s names no experiment" % claim["id"])
        for experiment in claim["experiments"]:
            if experiment not in experiments:
                failures.append("claim %s names the experiment %s, which the spec does not define" % (claim["id"], experiment))
            elif claim["id"] not in experiments[experiment]["claims"]:
                failures.append("claim %s names the experiment %s, which does not name %s among its claims"
                                % (claim["id"], experiment, claim["id"]))
    for experiment in draft["experiments"]:
        name = experiment["id"]
        if not experiment["claims"]:
            failures.append("experiment %s names no claim" % name)
        for claim in experiment["claims"]:
            if claim not in claims:
                failures.append("experiment %s names the claim %s, which the spec does not define" % (name, claim))
            elif name not in claims[claim]["experiments"]:
                failures.append("experiment %s names the claim %s, whose experiments do not list %s" % (name, claim, name))
        if not experiment["metrics"]:
            failures.append("experiment %s names no metric" % name)
        for metric in experiment["metrics"]:
            if metric not in metrics:
                failures.append("experiment %s names the metric %s, which the spec does not define" % (name, metric))
        for reference in experiment["baselines"]:
            if reference not in baselines:
                failures.append("experiment %s names the baseline %s, which the spec does not define" % (name, reference))
        for reference in experiment["data"]:
            if reference not in data:
                failures.append("experiment %s names the data %s, which the spec does not define" % (name, reference))
    for metric in draft["metrics"]:
        if not _one_line(metric["script"]):
            failures.append("metric %s names no script" % metric["name"])
    for anti in draft["anti_claims"]:
        if not anti["confirmed_by"]:
            failures.append("anti-claim %s names no experiment that would confirm it" % anti["id"])
        elif anti["confirmed_by"] not in experiments:
            failures.append("anti-claim %s names the experiment %s, which the spec does not define" % (anti["id"], anti["confirmed_by"]))
    for index, criterion in enumerate(draft["success_criteria"], 1):
        for reference in criterion["experiments"]:
            if reference not in experiments:
                failures.append("success criterion %d names the experiment %s, which the spec does not define" % (index, reference))
    if objectives is not None:
        failures += _objective_failures(draft, objectives, metrics)
    return failures


def _objective_failures(draft, records, metrics):
    """Ticket 81's half of the Type-A checks: the claims against the objectives, and the goals against the metrics."""
    failures, answered = [], set()
    for claim in draft["claims"]:
        failures += objectives.check_named("claim %s" % claim["id"], claim["objectives"], records, "claim")
        answered.update(identifier for identifier in claim["objectives"] if objectives.is_open(objectives.named(records, identifier)))
    for item in records:
        if not objectives.is_open(item):
            continue
        if item["id"] not in answered:
            failures.append("the open objective %s is answered by no claim: name it in the objectives of the claim that answers it"
                            % item["id"])
        metric = (item.get("measure") or {}).get("metric")
        if metric and metric not in metrics:
            failures.append("the goal %s's metric %s is not among the spec's metrics" % (item["id"], metric))
    return failures


# --- SPEC.md ------------------------------------------------------------------------------------------


def _list(values):
    return ", ".join(values) if values else "none"


def _number(value, unit):
    return "not set" if value is None else "%g %s" % (value, unit)


def render_spec(draft):
    """`SPEC.md` from a spec record: the sections of decision 10 in order, one line per item."""
    lines = ["# Spec: %s" % _one_line(draft["title"]), "",
             "Rendered by `wayline specify` from `research/spec.json`; change the spec by answering its confirmation "
             "with what to change, never by editing here.", ""]
    body = {
        "summary": [_one_line(draft["summary"])],
        "question": [_one_line(draft["question"])],
        "claims": ["- **%s.** %s (experiments: %s%s)" % (item["id"], _one_line(item["text"]), _list(item["experiments"]),
                                                          "; objectives: %s" % _list(item["objectives"]) if item["objectives"] else "")
                   for item in draft["claims"]],
        "anti_claims": ["- **%s.** %s (confirmed by: %s)" % (item["id"], _one_line(item["text"]), item["confirmed_by"] or "none")
                        for item in draft["anti_claims"]],
        "methods": ["- **%s**: %s" % (_one_line(item["name"]), _one_line(item["text"])) for item in draft["methods"]],
        "baselines": ["- **%s.** %s%s" % (item["id"], _one_line(item["text"]),
                                          " (source: %s)" % _one_line(item["source"]) if item.get("source") else "")
                      for item in draft["baselines"]],
        "data": ["- **%s.** %s%s" % (item["id"], _one_line(item["text"]),
                                     " (source: %s)" % _one_line(item["source"]) if item.get("source") else "")
                 for item in draft["data"]],
        "metrics": ["- **%s**: %s (script: `%s`)" % (item["name"], _one_line(item["definition"]), _one_line(item["script"]) or "none")
                    for item in draft["metrics"]],
        "success_criteria": ["- %s (experiments: %s)" % (_one_line(item["text"]), _list(item["experiments"]))
                             for item in draft["success_criteria"]],
        "budgets": ["- GPU: %s" % _number(draft["budgets"]["gpu_hours"], "hours"),
                    "- wall clock: %s" % _number(draft["budgets"]["wallclock_hours"], "hours"),
                    "- usage windows: %s" % ("not set" if draft["budgets"]["usage_windows"] is None else "%g" % draft["budgets"]["usage_windows"])]
                   + (["- notes: %s" % _one_line(draft["budgets"]["notes"])] if _one_line(draft["budgets"].get("notes")) else []),
        "out_of_scope": ["- %s" % _one_line(item) for item in draft["out_of_scope"]],
        "risks": ["- %s%s" % (_one_line(item["text"]), " Mitigation: %s" % _one_line(item["mitigation"]) if item.get("mitigation") else "")
                  for item in draft["risks"]],
        "seams": ["- **%s**: %s" % (_one_line(item["name"]), _one_line(item["text"])) for item in draft["seams"]],
    }
    experiments = []
    for item in draft["experiments"]:
        experiments += ["### %s (claims: %s)" % (item["id"], _list(item["claims"])), "",
                        "- design: %s" % _one_line(item["design"]),
                        "- baselines: %s" % _list(item["baselines"]),
                        "- data: %s" % _list(item["data"]),
                        "- metrics: %s" % _list(item["metrics"]),
                        "- success: %s" % _one_line(item["success"])]
        if _one_line(item.get("budget")):
            experiments.append("- budget: %s" % _one_line(item["budget"]))
        experiments.append("")
    body["experiments"] = experiments[:-1] if experiments else []
    for key, heading in SECTIONS:
        lines += ["## %s" % heading, ""] + (body[key] or ["none"]) + [""]
    return "\n".join(lines).rstrip("\n") + "\n"


def _read_json(ledger, relative):
    try:
        return json.loads(ledger.path(relative).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def check_spec(project, against_objectives=True):
    """The Type-A checks on the spec as written: `spec.json`'s structure, and `SPEC.md` being what it renders to.

    Returns the failures, empty when both pass. This is what a later phase (the planner cutting tickets)
    runs before it trusts the spec, with `against_objectives` False: the claims were held to the objectives
    when the spec was drafted and confirmed, and an objective opened, answered, or parked since is the spec
    amendment's (ticket 92) and the tickets' own check (`plan`), never a spec that cannot be cut. An
    `objectives.json` that cannot be read is a failure, named.
    """
    ledger = Ledger(project)
    try:
        draft = _read_json(ledger, SPEC_JSON)
    except ValueError as failure:
        return ["research/%s is not JSON: %s" % (SPEC_JSON, failure)]
    if draft is None:
        return ["there is no research/%s; run wayline specify" % SPEC_JSON]
    records = None
    if against_objectives:
        try:
            records = objectives.read_objectives(project)
        except objectives.ObjectivesUnreadable as failure:
            return [str(failure)]
    failures = check_draft(draft, records)
    try:
        text = ledger.path(SPEC_MD).read_text(encoding="utf-8")
    except FileNotFoundError:
        return failures + ["there is no research/%s" % SPEC_MD]
    headings = [line[3:].strip() for line in text.split("\n") if line.startswith("## ")]
    missing = [heading for _, heading in SECTIONS if heading not in headings]
    if missing:
        failures.append("research/%s lacks the section(s) %s" % (SPEC_MD, ", ".join(missing)))
    if not failures and text != render_spec(draft):
        failures.append("research/%s is not what research/%s renders to; it was edited by hand" % (SPEC_MD, SPEC_JSON))
    return failures




def spec_sha(project):
    """The first twelve hex of `spec.json`'s hash: the name of one version of the spec. None when there is none."""
    try:
        data = Ledger(project).path(SPEC_JSON).read_bytes()
    except FileNotFoundError:
        return None
    return hashlib.sha256(data).hexdigest()[:12]


# --- where the spec stands ------------------------------------------------------------------------------


def current_phase(events):
    """The phase the journal last moved to, or None."""
    phase = None
    for event in events:
        if event.get("event") == PHASE and (event.get("payload") or {}).get("to") in PHASES:
            phase = event["payload"]["to"]
    return phase


def _verdicts(events, sha):
    return [event["payload"] for event in events
            if event.get("event") == "verdict" and (event.get("payload") or {}).get("subject_kind") == "spec"
            and (event.get("payload") or {}).get("subject") == _subject(sha)]


def _subject(sha):
    return "%s at %s" % (SUBJECT, sha)


def _confirmation_ticket(project, sha):
    for ticket in read_tickets(project):
        if ticket["kind"] == DECISION_KIND and ticket.get("origin") == ORIGIN % sha:
            return ticket
    return None


def confirms(answer):
    words = re.findall(r"[a-z]+", str(answer or "").lower())
    return any(word in CONFIRMING for word in words) and all(word in CONFIRMING or word in FILLERS for word in words)


def what_to_change(answer):
    text = str(answer or "").strip()
    return re.sub(r"^revise\s*[:,-]?\s*", "", text, flags=re.IGNORECASE).strip() or text


def spec_state(project, events=None):
    """Where the spec stands, read from the files and the journal.

    `state` is one of `none` (no spec), `unverified` (written, no passing verdict), `unasked` (verified,
    no confirmation asked or given), `pending` (a confirmation ticket waits), `confirmed`, or `revise`
    (answered with what to change, which `feedback` holds). `sha`, `ticket`, `answer`, `decided_by`,
    `findings` (the last failing verdict's), and `phase` go with it.
    """
    project = Path(project).resolve()
    ledger = Ledger(project)
    if events is None:
        events, _ = ledger.read_events()
    sha = spec_sha(project)
    state = {"state": "none", "sha": sha, "ticket": None, "answer": None, "decided_by": None, "feedback": None,
             "findings": [], "phase": current_phase(events)}
    if sha is None:
        return state
    verdicts = _verdicts(events, sha)
    if not any(verdict.get("pass") for verdict in verdicts):
        state["state"] = "unverified"
        failed = [verdict for verdict in verdicts if not verdict.get("pass")]
        state["findings"] = list(failed[-1].get("findings") or []) if failed else []
        return state
    ticket = _confirmation_ticket(project, sha)
    state["ticket"] = ticket["id"] if ticket is not None else None
    # The last answer given to this version wins, through its ticket or without one: an owner who asked
    # for a change and then changed their mind confirms it with `wayline specify confirm`.
    answer = None
    prefix = ANSWER_PREFIX % sha
    for event in events:
        payload = event.get("payload") or {}
        if event.get("event") != DECISION:
            continue
        text = str(payload.get("answer") or "")
        if payload.get("ticket") is None and text.startswith(prefix):
            answer = dict(payload, answer=text[len(prefix):])
        elif ticket is not None and payload.get("ticket") == ticket["id"]:
            answer = dict(payload)
    if answer is None and ticket is not None:
        written = answer_section(read_ticket(tickets_dir(project) / filename(ticket))[1])
        if written is not None:
            answer = {"answer": written, "decided_by": "human"}
    if answer is None:
        state["state"] = "pending" if ticket is not None else "unasked"
        return state
    state.update(answer=answer["answer"], decided_by=answer.get("decided_by"))
    if confirms(answer["answer"]):
        state["state"] = "confirmed"
        return state
    change = what_to_change(answer["answer"])
    if change == what_to_change(REVISE):
        change = ""  # the option's placeholder, as the decider may pick it: the change is in the rationale
    rationale = str(answer.get("rationale") or "").strip()
    if rationale:
        change = (change + " (the reason given: %s)" % rationale).strip()
    state["state"], state["feedback"] = "revise", change or "no change was named; read the answer on the ticket"
    return state


def move_phase(ledger, events, to, session_id=None):
    """Journal `phase` to `to` unless the journal is there already; returns whether it moved."""
    now = current_phase(events)
    if now is not None and PHASES.index(now) >= PHASES.index(to):
        return False  # never backwards: a spec redrafted in a later phase leaves the phase where it is
    ledger.append_event(PHASE, {"from": now, "to": to}, session_id=session_id)
    return True


def advance(project, events=None):
    """Journal `phase P3 -> P4` once the spec is confirmed; returns whether it moved.

    A journal already at P4 or past it is left alone: the spec was confirmed before, and a later phase
    is not undone by reading the confirmation again.
    """
    project = Path(project).resolve()
    ledger = Ledger(project)
    if events is None:
        events, _ = ledger.read_events()
    if spec_state(project, events)["state"] != "confirmed":
        return False
    seed_gap(ledger)
    now = current_phase(events)
    if now is not None and PHASES.index(now) >= PHASES.index(PLAN_PHASE):
        return False
    return move_phase(ledger, events, PLAN_PHASE)


def seed_gap(project_or_ledger):
    """Write the confirmed spec's `gap` passages into the Introduction (decision 17), each once, by the specify step.

    Returns the passages written; a spec without `gap`, or one whose passages were written already, writes none.
    """
    ledger = project_or_ledger if isinstance(project_or_ledger, Ledger) else Ledger(project_or_ledger)
    try:
        draft = _read_json(ledger, SPEC_JSON)
    except (OSError, ValueError):
        return []
    items = [(item.get("heading"), item.get("text")) for item in (draft or {}).get("gap") or [] if isinstance(item, dict)]
    return sections.seed_passages(ledger, "introduction", items, by=GAP_BY) if items else []


# --- the prompt -----------------------------------------------------------------------------------------


def specify_prompt(role, records, harness, project, open_questions=(), change=None, cut=False, pursued=()):
    """The planner's specify prompt: what is asked, the objectives, the open questions, what to change, the records, the paths, the protocol, the schema.

    `pursued` is the project's open objectives, which the claims answer.
    """
    lines = ["# What you are asked for", "",
             "The research spec of this project: phase P3, specify. The harness renders what you return as "
             "`research/SPEC.md`, checks its structure, has an independent verifier read whether every claim has an "
             "experiment and every experiment defends a claim, and asks the owner to confirm it before planning.", "",
             "- autonomy: %s; radius: %s" % (harness.get("autonomy"), harness.get("radius"))]
    lines += ["", "# The objectives", "",
              "The questions the project answers now (`research/OBJECTIVES.md`); an objective with a measure is a goal. The "
              "first may be the question to answer first rather than the project's end. Every one of them is answered by at "
              "least one claim that names it in its `objectives`; a claim no objective asked for names none, and a claim never "
              "names an objective that is not listed here. A goal's metric is among the spec's metrics, with its "
              "`eval_command` as the script. Write `summary` too: what the project is, in about 120 words a newcomer reads "
              "cold, since the general report opens with it.", ""]
    for item in pursued:
        lines.append("- %s: %s (%s)" % (item["id"], _one_line(item["text"]),
                                        "a goal: %s" % objectives.describe_measure(item["measure"]) if item.get("measure")
                                        else "an objective: no measure"))
    if open_questions:
        lines += ["", "# The questions the grill left open", "",
                  "The spec takes the recommended answer on each of these where it has to take a side, and names the "
                  "question in a risk. A question marked as the owner's (human-only or irreversible) takes no answer from the spec: "
                  "what depends on it is written as conditional on the owner's answer, and named in a risk, so that the "
                  "graph can pause it behind a decision ticket.", ""]
        for record in open_questions:
            if grill.owners(record):
                lines.append("- %s: %s (the owner's: human-only or irreversible)" % (record["id"], _one_line(record["question"])))
            else:
                lines.append("- %s: %s (recommended: %s)" % (record["id"], _one_line(record["question"]),
                                                              _one_line(record.get("recommended")) or "none given"))
    if change:
        lines += ["", "# What to change", "",
                  "A previous draft of this spec was not accepted. Change what this names, and keep what it does not:", "",
                  change.strip()]
    parts = ["\n".join(lines), records]
    if cut:
        parts.append("[wayline: the records were cut at the context cap; the paths below hold the rest.]")
    parts.append("\n".join([
        "# The paths you may open",
        "",
        "The project is `%s`; open these with the Read tool when a record points into them:" % project,
        "",
        "- `research/INTAKE.md`: the intent, the references, the data, the constraints, the radius",
        "- `research/CONTEXT.md`: the vocabulary the grill settled; the spec uses its terms",
        "- `research/refs/<slug>/dossier.json`, and `dossier.md` for a reference read in full",
        "- `research/SPEC.md` and `research/spec.json`: the previous draft, when there is one",
    ]))
    parts.append(worker.protocol_for(role.protocol, "specify"))
    parts.append(worker.schema_section("# The spec", SPEC_SCHEMA, closing=[
        "",
        "Ids are `C<n>` for claims, `A<n>` for anti-claims, `E<n>` for experiments, `B<n>` for baselines, and `D<n>` for "
        "data; an experiment names metrics by their `name`.",
    ]))
    return "\n\n".join(part.strip("\n") for part in parts if part and part.strip()) + "\n"


# --- the draft ------------------------------------------------------------------------------------------


def session_dir(project, sessions=SESSIONS):
    """`research/<sessions>/<n>`, the first free number: where one planner session's stream and records go."""
    base = Path(project) / "research" / sessions
    number = 1
    while (base / str(number)).exists():
        number += 1
    return base / str(number)


class PlannerSession:
    """One planner session of a phase verb, and the mechanics every such verb shares.

    The launch through the worker launcher (seam 1) on `policy.roles.planner`, Opus in Fable's place
    when the hold says so; the resume of the same session with a gate's message; the record the
    session returned, kept beside its stream as `<prefix>-<n>.json` for the owner to read; and whether
    an envelope holds a record the verb's schema accepts. A verb subclasses it with its own gates:
    specify's draft, checks, and verdict below, and the plan-time checks of `wayline.plan`.
    """

    error = SpecifyError                     # what a session that cannot go on raises
    schema = SPEC_SCHEMA                     # the record the session returns
    sessions = SESSIONS                      # research/<sessions>/<n>
    what = "the planner's specify session"   # named in the hold on Fable's window and in a refusal

    def __init__(self, project, harness_root, policy, fall_back, say):
        self.project, self.harness_root, self.policy, self.say = project, harness_root, policy, say
        self.ledger = Ledger(project)
        self.model, self.effort, self.fallback_from = planner_tier(policy, falls_back_now(project, policy, fall_back, self.what))
        self.role = worker.read_role(PLANNER, harness_root, project)
        self.run_dir = session_dir(project, self.sessions)
        self.request = None
        self.session_id = None
        self.kept = 0

    def budget(self, key):
        return ((self.policy.get("budget") or {}).get(PLANNER_BUDGET) or {}).get(key)

    def start(self, prompt):
        self.request = worker.LaunchRequest(
            role=self.role.name, model=self.model, effort=self.effort, prompt=prompt,
            agent_json=self.role.agent_json(self.model, self.effort, self.budget("max_turns")),
            allowed_tools=list(self.role.allowed_tools), disallowed_tools=list(self.role.disallowed_tools),
            settings_path=gates.write_worker_settings(self.run_dir / "settings.json", self.harness_root),
            add_dirs=[str(Path(self.harness_root).resolve()), str(self.project)],
            cwd=self.project,
            env=gates.verdict_env(self.project, self.run_dir),
            schema_path=Path(self.harness_root).resolve() / "schemas" / (self.schema + ".json"),
            max_minutes=self.budget("max_minutes"),
        )
        return self._taken(worker.launch(self.request))

    def continue_with(self, message):
        if not self.session_id:
            raise self.error("the planner's session has no id to be resumed with")
        return self._taken(worker.resume(self.request, self.session_id, message))

    def _taken(self, envelope):
        gates.raise_if_refused(envelope, self.model, self.what)
        self.session_id = envelope.session_id or self.session_id
        return envelope

    def keep(self, record, prefix):
        """The record as the session returned it, kept beside its stream for the owner to read."""
        self.kept += 1
        relative = "%s/%s-%d.json" % (Path(self.run_dir).relative_to(self.ledger.research), prefix, self.kept)
        self.ledger.write_json(relative, record)

    def unusable(self, envelope):
        """Why this envelope is not a record the verb can act on, or None when it is one."""
        if not envelope.valid:
            return "; ".join(envelope.errors) or "the session returned no structured %s" % self.schema
        try:
            check(envelope.structured_output, load_schema(self.schema), name="the " + self.schema)
        except ValidationError as failure:
            return str(failure)
        return None


class _Session(PlannerSession):
    """The specify session and its one allowance of each return: invalid output, failed checks, failed verdict."""

    objectives = None  # the project's objectives, read once by `draft_spec`, which every draft of the session is checked against

    def draft(self, prompt):
        """A draft that passed the schema and the Type-A checks, with each gate's one return spent as needed."""
        envelope = self.start(prompt)
        problem = self.unusable(envelope)
        if problem is not None:
            self.say("  the draft could not be read (%s); returned to the planner once" % problem)
            envelope = self.continue_with(RESUME_INVALID % problem)
            problem = self.unusable(envelope)
        if problem is not None:
            raise SpecifyError("the planner returned no spec the schema accepts: %s" % problem)
        return self.checked(envelope.structured_output)

    def checked(self, draft, returned=False):
        """`draft` once it passes the Type-A checks; a failing one goes back once, a second failure raises."""
        self.keep(draft, "draft")
        failures = check_draft(draft, self.objectives)
        if failures and not returned:
            self.say("  the draft failed %d structural check(s); returned to the planner once" % len(failures))
            envelope = self.continue_with(RESUME_CHECKS % "\n".join("- " + failure for failure in failures))
            problem = self.unusable(envelope)
            if problem is not None:
                raise SpecifyError("the planner's redraft could not be read: %s" % problem, failures)
            return self.checked(envelope.structured_output, returned=True)
        if failures:
            raise SpecifyError("the spec failed its structural checks twice; nothing was written", failures)
        return draft

    def revise(self, findings):
        """The draft again after a failed verdict, checked; its Type-A allowance is spent already."""
        envelope = self.continue_with(RESUME_FINDINGS % gates.findings_text(findings))
        problem = self.unusable(envelope)
        if problem is not None:
            raise SpecifyError("the planner's redraft after the verdict could not be read: %s" % problem)
        self.keep(envelope.structured_output, "draft")
        failures = check_draft(envelope.structured_output, self.objectives)
        if failures:
            raise SpecifyError("the redraft after the verdict failed its structural checks; the spec as written stands "
                               "unverified", failures)
        return envelope.structured_output


def _write(ledger, draft):
    ledger.write_json(SPEC_JSON, draft, schema=SPEC_SCHEMA)
    ledger.write_markdown(SPEC_MD, render_spec(draft))
    return spec_sha(ledger.project)


def _judge(project, sha, author_model, harness_root, policy, fall_back):
    return gates.verdict("spec", _subject(sha), VERDICT_QUESTION, list(VERDICT_PATHS), VERDICT_SCOPE, project=project,
                         author_model=author_model, verdict_type=gates.SPEC_COVERAGE, harness_root=harness_root,
                         policy=policy, fall_back=fall_back)


def judge_spec(project, *, harness_root=HARNESS_ROOT, policy=None, fall_back=None, say=lambda text: None):
    """The verdict alone, on a spec that was written and passes its checks but was never judged; returns it.

    What a verifier session a usage window or the hold on Fable's window stopped leaves owed: the draft
    stands, so only the verdict is taken. The author is the planner's tier as it stands now.
    """
    project = Path(project).resolve()
    policy = policy_for(project, harness_root) if policy is None else policy
    model = planner_tier(policy, falls_back_now(project, policy, fall_back))[0]
    sha = spec_sha(project)
    say("research/SPEC.md (%s) was written and never judged; asking the verifier" % sha)
    return sha, _judge(project, sha, model, harness_root, policy, fall_back)


def draft_spec(project, *, change=None, unchanged_from=None, harness_root=HARNESS_ROOT, policy=None, fall_back=None,
               say=lambda text: None):
    """Draft, check, write, and judge the spec; returns `(sha, verdict)`, the verdict the last one taken.

    `change` is what the owner or a failed verdict asked to change. `unchanged_from` is the spec the owner
    asked to change: a draft identical to it is refused before a verdict is spent on it. Raises
    `SpecifyError` when the draft fails its gates as the module says, `gates.UsageLimited` when a window
    refused a session, and `gates.FableHeld` when the planner (or its verifier) waits for Fable's weekly window.
    """
    project = Path(project).resolve()
    ledger = Ledger(project)
    policy = policy_for(project, harness_root) if policy is None else policy
    try:
        records = objectives.read_objectives(project)
    except objectives.ObjectivesUnreadable as failure:
        raise SpecifyError("%s; nothing was drafted" % failure) from None
    pursued = [item for item in records if objectives.is_open(item)]
    if not pursued:
        raise SpecifyError(NO_OBJECTIVE)
    events, _ = ledger.read_events()
    session = _Session(project, harness_root, policy, fall_back, say)
    session.objectives = records  # read once: the draft and its redrafts are held to the objectives it was asked for
    records, cut = decider.records_text(project, context_cap(policy, session.model))
    harness = read_harness(project)
    open_questions = [record for record in grill.read_records(project)
                      if record.get("id") and record.get("answer") is None]
    prompt = specify_prompt(session.role, records, harness, project, open_questions, change, cut, pursued)
    move_phase(ledger, events, SPECIFY_PHASE)
    say("drafting the spec: the planner on %s at %s%s" % (session.model, session.effort,
                                                         " in place of fable" if session.fallback_from else ""))
    draft = session.draft(prompt)
    if unchanged_from is not None and draft == unchanged_from:
        raise SpecifyError("the planner returned the spec unchanged, so the change asked for was not made; answer the "
                           "confirmation again (wayline specify confirm, or revise with a clearer change)")
    sha = _write(ledger, draft)
    say("  wrote research/SPEC.md (%s); asking the verifier" % sha)
    verdict = _judge(project, sha, session.model, harness_root, policy, fall_back)
    if verdict.passed:
        return sha, verdict
    say("  the verifier failed it with %d finding(s); returned to the planner once" % len(verdict.findings))
    draft = session.revise(verdict.findings)
    sha = _write(ledger, draft)
    say("  wrote research/SPEC.md again (%s); asking the verifier" % sha)
    return sha, _judge(project, sha, session.model, harness_root, policy, fall_back)


def context_cap(policy, model):
    caps = (policy.get("context_pack") or {}).get("max_chars") or {}
    return caps.get(model, min(caps.values()) if caps else None)


# --- the confirmation -----------------------------------------------------------------------------------


def _ask(project, sha, notify):
    """The confirmation ticket for spec `sha`: `blocking: all`, answerable by the decider under autonomous."""
    return decisions.open_decision(
        project, "Confirm the spec (research/SPEC.md at %s) before the planner cuts the tickets? Answer confirm, or "
                 "revise: and what to change." % sha,
        options=[CONFIRM, REVISE], recommended=CONFIRM,
        evidence=["research/SPEC.md at %s: its structural checks and its verdict passed" % sha,
                  "the verdict: %s" % _subject(sha)],
        blocking="all", human_only=False, reversible=True, proposed_by=PLANNER, origin=ORIGIN % sha, title=TITLE,
        notify=notify)["ticket"]


def _decide(project, identifier, harness_root, policy, fall_back, notify, say):
    """Under autonomous: the decider on the confirmation ticket, now. Returns the outcome's line, or why it waits."""
    for fields, body, record in decisions.for_the_decider(project):
        if fields["id"] != identifier:
            continue
        try:
            outcome = decider.decide_ticket(project, fields, body, record, harness_root=harness_root, policy=policy,
                                            fall_back=fall_back, notify=notify)
        except gates.FableHeld as held:
            return "the decider waits for Fable's weekly window (until %s)" % held.resets_at
        except gates.UsageLimited as refused:
            return "the usage limit refused the decider: %s" % refused
        return outcome.line
    return "decision ticket %d is not the decider's to take now" % identifier


def confirm(project, text, rationale=None, by="cli"):
    """The owner's answer to the spec's confirmation: through its ticket when one is open, else journaled with no ticket.

    Returns the state after the answer (and the phase moved when it confirms). Refused when there is no
    verified spec waiting for an answer.
    """
    project = Path(project).resolve()
    text = str(text or "").strip()
    if not text:
        raise SpecifyError("an answer to the spec's confirmation needs some text")
    state = spec_state(project)
    if state["state"] not in ("unasked", "pending", "revise"):
        raise SpecifyError("the spec is %s, so there is nothing to confirm; %s" % (state["state"], _next(state)))
    if state["state"] == "pending":
        answer_ticket(project, state["ticket"], text, rationale=rationale, by=by)
    else:
        Ledger(project).append_event(DECISION, {"ticket": None, "answer": ANSWER_PREFIX % state["sha"] + text,
                                                "decided_by": "human", "rationale": rationale, "confidence": None})
    advance(project)
    return spec_state(project)


def _next(state):
    return {
        "none": "run wayline specify to draft it",
        "unverified": "run wayline specify to draft it again with the verifier's findings",
        "unasked": "answer with wayline specify confirm, or wayline specify revise \"<what to change>\"",
        "pending": "answer decision ticket %s with wayline answer %s confirm (or revise: ...), or in the dashboard"
                   % (state.get("ticket"), state.get("ticket")),
        "confirmed": "next: wayline plan",
        "revise": "run wayline specify to redraft it with the change asked for",
    }[state["state"]]


# --- the verb -------------------------------------------------------------------------------------------


def specify(project, *, harness_root=HARNESS_ROOT, policy=None, fall_back=None, notify=None, out=None):
    """Do whatever the spec owes next: draft, ask, decide, or advance. Returns the report.

    The report is `{project, did: [...], state, stopped, failures}`; `stopped` names what ended the call
    early (a failed gate, a usage window, the hold on Fable's window) and `failures` the checks behind it.
    """
    project = Path(project).resolve()
    say = (lambda text: print(text, file=out)) if out is not None else (lambda text: None)
    ledger = Ledger(project)
    harness = read_harness(project)
    autonomy = harness.get("autonomy")
    report = {"project": str(project), "autonomy": autonomy, "did": [], "stopped": None, "failures": []}
    journal_written_answers(project, ledger)
    state = spec_state(project)
    if autonomy == AUTONOMOUS and state["state"] in ("none", "revise"):
        # Before a draft, the decider takes whatever the grill left for it: a decide-rest that did not finish
        # (its session killed with the grill's, ticket 36) would otherwise leave the planner to guess.
        decider.settle_grill(project, report, harness_root=harness_root, policy=policy, fall_back=fall_back,
                             notify=notify, say=say)
    if report["stopped"] is not None:
        state = spec_state(project)
    elif state["state"] == "unverified" and not state["findings"] and not check_spec(project):
        try:
            sha, verdict = judge_spec(project, harness_root=harness_root, policy=policy, fall_back=fall_back, say=say)
        except gates.FableHeld as held:
            report["stopped"] = "Fable's weekly window is held until %s and the consent waits: %s" % (held.resets_at, held)
        except gates.UsageLimited as refused:
            report["stopped"] = "the usage limit refused a session: %s" % refused
        except (gates.GateError, worker.LaunchError, worker.RoleError) as failure:
            report["stopped"] = str(failure)
        else:
            report["did"].append("the verifier %s research/SPEC.md at %s (%s)"
                                 % ("passed" if verdict.passed else "failed", sha, verdict.model or "no model named"))
            if not verdict.passed:
                report["stopped"] = "the verifier failed the spec; the next wayline specify redrafts it with the findings"
                report["failures"] = [gates.findings_text(verdict.findings)]
        state = spec_state(project)
    elif state["state"] in ("none", "unverified", "revise"):
        change = None
        if state["state"] == "revise":
            change = "The %s asked: %s" % ("owner" if state["decided_by"] == "human" else state["decided_by"] or "owner",
                                           state["feedback"])
        elif state["findings"]:
            change = "The last verifier failed the spec on these findings:\n\n" + gates.findings_text(state["findings"])
        try:
            previous = _read_json(ledger, SPEC_JSON) if state["state"] == "revise" else None
            sha, verdict = draft_spec(project, change=change, unchanged_from=previous, harness_root=harness_root,
                                      policy=policy, fall_back=fall_back, say=say)
        except SpecifyError as failure:
            report.update(stopped=str(failure), failures=failure.failures)
        except gates.FableHeld as held:
            report["stopped"] = "Fable's weekly window is held until %s and the consent waits: %s" % (held.resets_at, held)
        except gates.UsageLimited as refused:
            report["stopped"] = "the usage limit refused a session: %s" % refused
        except (gates.GateError, worker.LaunchError, worker.RoleError) as failure:
            report["stopped"] = str(failure)
        else:
            report["did"].append("drafted research/SPEC.md at %s; the verifier %s it (%s)"
                                 % (sha, "passed" if verdict.passed else "failed", verdict.model or "no model named"))
            if not verdict.passed:
                report["stopped"] = "the verifier failed the spec twice; it stands unconfirmed"
                report["failures"] = [gates.findings_text(verdict.findings)]
        state = spec_state(project)
    if state["state"] == "unasked" and report["stopped"] is None:
        if autonomy == INTERACTIVE:
            report["did"].append("the spec waits for the owner's word in this session")
        else:
            identifier = _ask(project, state["sha"], notify)
            report["did"].append("opened decision ticket %d, \"%s\", blocking all" % (identifier, TITLE))
        state = spec_state(project)
    if state["state"] == "pending" and autonomy == AUTONOMOUS and report["stopped"] is None:
        report["did"].append("the decider on ticket %d: %s" % (state["ticket"], _decide(
            project, state["ticket"], harness_root, policy, fall_back, notify, say)))
        state = spec_state(project)
    if advance(project):
        report["did"].append("the spec is confirmed; the phase moved to %s" % PLAN_PHASE)
        state = spec_state(project)
    report["state"] = state
    return report


def render_report(report):
    """The text `wayline specify` prints."""
    state = report["state"]
    lines = ["specify  %s  (autonomy %s)" % (report["project"], report["autonomy"])]
    lines += ["  " + line for line in report["did"]] or ["  nothing to do"]
    if report["stopped"]:
        lines.append("  stopped: %s" % report["stopped"])
        lines += ["    " + line for failure in report["failures"] for line in str(failure).split("\n")]
    lines.append("  the spec: %s%s%s" % (state["state"], " at %s" % state["sha"] if state["sha"] else "",
                                         ", answered by the %s: %s" % (state["decided_by"], state["answer"]) if state["answer"] else ""))
    if state["phase"]:
        lines.append("  phase: %s" % state["phase"])
    if state["state"] == "unasked" and report["autonomy"] == INTERACTIVE:
        lines += ["", "Ask the owner to read research/SPEC.md and confirm it. Record the answer with:",
                  "  wayline specify confirm [--rationale \"<why>\"]",
                  "  wayline specify revise \"<what to change>\""]
    else:
        lines.append("  " + _next(state))
    return "\n".join(lines)


def specify_command(args):
    args = list(args)
    if args and args[0] in ("confirm", "revise"):
        return _answer_command(args[0], args[1:])
    parser = argparse.ArgumentParser(
        prog="wayline specify",
        description="phase P3: draft research/SPEC.md with the planner, check it, have the verifier judge it, and ask for "
                    "its confirmation by the project's autonomy; run again, it does whatever the spec owes next. "
                    "`wayline specify confirm` and `wayline specify revise` record the owner's answer.")
    parser.add_argument("--project", help="the project; the active one by default")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    options, code = parse_args(parser, args)
    if options is None:
        return code
    try:
        project = find_project(options.project)
        report = specify(project, out=None if options.json else sys.stdout)
    except (ProjectError, LedgerError, TicketError, SpecifyError, OSError) as failure:
        print("wayline specify: %s" % failure, file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2) if options.json else render_report(report))
    return 1 if report["stopped"] else 0


def _answer_command(verb, args):
    parser = argparse.ArgumentParser(
        prog="wayline specify %s" % verb,
        description="record the owner's %s of the spec: through its confirmation ticket when one is open, else journaled"
                    % ("confirmation" if verb == "confirm" else "request for a change"))
    if verb == "revise":
        parser.add_argument("change", help="what to change, in a sentence")
    parser.add_argument("--rationale", help="the owner's reason, when they gave one")
    parser.add_argument("--project", help="the project; the active one by default")
    options, code = parse_args(parser, args)
    if options is None:
        return code
    text = CONFIRM if verb == "confirm" else "revise: " + options.change
    try:
        project = find_project(options.project)
        state = confirm(project, text, rationale=options.rationale)
    except SpecifyError as failure:
        print("wayline specify %s: %s" % (verb, failure), file=sys.stderr)
        return 2
    except (ProjectError, LedgerError, TicketError, OSError) as failure:
        print("wayline specify %s: %s" % (verb, failure), file=sys.stderr)
        return 1
    print("the spec: %s at %s; %s" % (state["state"], state["sha"], _next(state)))
    return 0
