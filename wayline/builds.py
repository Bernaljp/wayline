"""Builds at the order (Implementation Decision 17; ticket 117).

Every **build** of the paper is tested before the owner reads it. A paper order runs its builds while it stays open: the
first is the composition ticket 115 makes (`paper.compose`), and each later one a fresh writer session given the previous
parts and the points still standing, with no ticket (`paper.compose` with `rebuild`).

**The gates** (`gate`), on the paper's parts, in order, each a fresh verifier session through `wayline.gates`:

1. the kill argument (`gates.kill_argument`, both threads), told the general report's last verdict (`told`);
2. the independent read (`gates.PAPER_READ`, `READ_QUESTION`);
3. sampled verdicts on the claims never sampled (`run_end.sample_new`, over the sample cache the general report's gate
   keeps, so a claim the report or an earlier build sampled is not drawn again).

Each gate runs whatever the one before it found, so the next build is given every point at once. No gate files a
ticket: what stands goes to the next build, and `PAPER.md` lists each gate of each build with its points. A gate taken
before a pause is not taken again: its verdict is read back from the journal by its subject (`research/paper#v<n>-b<k>`).

**The journal** (`paper_order`): `composed` with its `build`, then `gated` with the `points` when the next build is owed,
`passed` when every gate passed, or `not_passed` when the last build the order allows (`policy.paper.builds`, three)
failed; the last two close the order, and the conductor then compiles the paper. A gate that cannot be taken fails the
order (`failed`): an ungated paper stands, said in `PAPER.md`.

**Not passed.** The paper is marked not passed in `paper.json` and `PAPER.md`, and the owner chooses (`choose`, `wayline
paper builds more|keep|objectives`, which the conversation runs on the owner's word): three more builds, which reopens
the order (`chosen` with `choice: more`) for as many builds again from the points standing; keeping the paper as it is;
or the points as objectives, each one the owner's open objective. Under `interactive` and `checkpoints` the conductor
tells the owner; under `autonomous` the paper stops under the account's "Waiting on you" (`waiting_lines`), and nothing
is asked.

**What the paper says about inherited work** (rendered or checked by code at each composition):

- an unverifiable claim the batch left out is in no part, neither its `{doc:...}` tag nor its words; one the batch kept
  is stated as not verified, in the sentence carrying its tag (`answer_problems`), and `PAPER.md` lists what was left out;
- a supplementary table renders each inherited result's verdict, route, narrowed wording, and reasons
  (`inherited_table`), appended by code to the supplement, and the writer adds one Methods paragraph naming the routes;
- the concerns kept for the order reach the figure finish (each a change request `from: paper`), the writer (its
  prompt, and its `concerns` answer), and the compilation's checks (`concern_checks`);
- a project with critiques gets one `research/paper/response/<critique>.md` per critique (`write_responses`), each point
  verbatim with its answer. Nothing sends a response.
"""

import argparse
import re
import sys
from pathlib import Path

from wayline import HARNESS_ROOT, gates, provenance
from wayline.cli import parse_args
from wayline.ledger import PAPER_ORDER, LedgerError, conductor_holder, ledger_for
from wayline.project import ProjectError, find_project, policy_for

__all__ = [
    "BuildsError", "DEFAULT_BUILDS", "KILL", "READ", "SAMPLED", "GATES", "PASSED", "NOT_PASSED", "NEXT", "MORE", "KEEP",
    "OBJECTIVES", "CHOICES", "READ_QUESTION", "READ_SCOPE", "RESPONSE_DIR", "allowed", "progress", "take", "gate", "subject",
    "told", "choose", "pending_choice", "waiting_lines", "report_lines", "writer_lines", "answer_problems", "order_concerns",
    "inherited_table", "write_responses", "concern_checks", "change_requests", "builds_command",
]

DEFAULT_BUILDS = 3
KILL, READ, SAMPLED = "kill_argument", "paper_read", "sampled_verdicts"
GATES = (KILL, READ, SAMPLED)
GATE_TITLES = {KILL: "the kill argument", READ: "the independent read", SAMPLED: "the sampled verdicts on claims never sampled"}
PASSED, NOT_PASSED, NEXT = "passed", "not_passed", "next"
COMPOSED, GATED, CHOSEN, ORDERED = "composed", "gated", "chosen", "ordered"
MORE, KEEP, OBJECTIVES = "more", "keep", "objectives"
CHOICES = {MORE: "three more builds", KEEP: "keep it as it is", OBJECTIVES: "the points as objectives"}
PAPER_SUBJECT = "research/paper"
RESPONSE_DIR = "response"                 # research/paper/response/<critique>.md
# How a sentence says an inherited claim is not verified: "not verified", "not been verified", "unverified", "could not
# be verified", "cannot be verified", "unverifiable".
NOT_VERIFIED = re.compile(r"\b(?:not\s+(?:yet\s+)?(?:been\s+)?verified|unverified|unverifiable|(?:could|can)\s*not\s+be\s+verified)\b", re.I)
TABLE_MARK = "<!-- wayline: the inherited results, rendered by code from research/verifications.json -->"
_CRITIQUE = re.compile(r"^D[1-9][0-9]*$")

READ_QUESTION = "Would a reader find the paper's claims carried by the project's evidence, and the paper complete as a paper?"
READ_SCOPE = (
    "Read the paper's parts at the paths below as a reviewer would, against the general report, the findings, the "
    "manifest, the outline, and the verifications. It fails on a claim the findings or the references do not carry, a "
    "result stated past what its artifact says, an inherited claim stated as verified that is not, a limitation or a "
    "negative result the report records and the paper leaves out, or a part the outline holds that says nothing. Whether "
    "the science is interesting, or the prose could be better, is not your question. Every finding is at a path and a "
    "locator you read. You are the one independent verdict on this build; a separate pair of sessions wrote and "
    "adjudicated the case against it."
)

_PARTS_READ = ("title", "abstract", "introduction", "results", "discussion", "methods", "supplement", "front")
_SAMPLED_PARTS = ("abstract", "introduction", "results", "discussion", "methods", "supplement")
_EVIDENCE = ("REPORT.md", "findings.jsonl", "manifest.json", "OUTLINE.md", "VERIFICATIONS.md", "CONCERNS.md")


class BuildsError(ValueError):
    """A choice refused: no paper waits on one, or the choice is none of the three."""


def _one_line(text):
    return " ".join(str(text or "").split())


def _plain(text):
    """A sentence with its tags taken off, read as prose."""
    return re.sub(r"\s+([.,;:!?])", r"\1", _one_line(provenance.strip_tags(text)))


def allowed(policy):
    """The builds one order runs at most, and the owner's three more: `policy.paper.builds`."""
    value = ((policy or {}).get("paper") or {}).get("builds")
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 1 else DEFAULT_BUILDS


def _orders(events):
    return [event.get("payload") or {} for event in events if event.get("event") == PAPER_ORDER]


def subject(version, build):
    """The subject of one build's gates: the paper's version and the build."""
    return "%s#v%d-b%d" % (PAPER_SUBJECT, version, build)


# --- where an order stands --------------------------------------------------------------------------------------------


def progress(project_or_events, order):
    """Where the open order `order` stands: `{step, build, first, points}`.

    `step` is `compose` (its first build), `rebuild` (a later build, given `points`), or `gate` (the gates on `build`,
    composed). `first` is the first build since the order was made or reopened: the order allows `allowed(policy)` builds
    from it.
    """
    events = project_or_events if isinstance(project_or_events, list) else ledger_for(project_or_events).read_events()[0]
    number = order.get("order")
    mine = [payload for payload in _orders(events) if payload.get("order") == number]
    opened = max((index for index, payload in enumerate(mine) if payload.get("action") == ORDERED
                  or (payload.get("action") == CHOSEN and payload.get("choice") == MORE)), default=0)
    before = [payload.get("build") or 0 for payload in mine[:opened] if payload.get("build")]
    last = max(before, default=0)
    points = next((list(payload.get("points") or []) for payload in reversed(mine[:opened]) if payload.get("points")), [])
    found = {"step": "rebuild" if last else "compose", "build": last + 1, "first": last + 1, "points": points}
    for payload in mine[opened + 1:]:
        action = payload.get("action")
        if action == COMPOSED:
            found.update(step="gate", build=payload.get("build") or found["build"], points=[])
        elif action == GATED:
            found.update(step="rebuild", build=(payload.get("build") or found["build"]) + 1, points=list(payload.get("points") or []))
    return found


# --- the gates --------------------------------------------------------------------------------------------------------


def told(events):
    """What the kill argument on the paper is told: the general report's last verdict, with its points still standing."""
    from wayline import run_end
    payload = run_end.last_kill_verdict(events)
    if payload is None:
        return ("The general report's last verdict: no kill argument has run on research/REPORT.md yet. The paper is "
                "composed from the same findings; argue against the paper itself.")
    lines = ["The general report's last verdict: the kill argument on %s (verifier session %s, %s) %s." % (
        payload.get("subject") or provenance.REPORT_PATH, payload.get("session_id") or "unknown", payload.get("model") or "an unnamed model",
        "passed" if payload.get("pass") else "failed")]
    if not payload.get("pass"):
        lines += ["", "These points stood against the general report; where the paper still makes the claim, it stands against "
                      "the paper too, unless the paper scoped it down:", "", gates.findings_text(payload.get("findings") or [])]
    return "\n".join(lines)


def _paths(project):
    paper = Path(project) / "research" / "paper"
    found = ["research/paper/%s.md" % part for part in _PARTS_READ if (paper / ("%s.md" % part)).is_file()]
    for folder in ("tables", "figures"):
        if (paper / folder).is_dir():
            found.append("research/paper/%s/" % folder)
    if (paper / "references.json").is_file():
        found.append("research/paper/references.json")
    found += ["research/%s" % name for name in _EVIDENCE if (Path(project) / "research" / name).is_file()]
    return found


def _points(findings):
    return ["%s%s" % (_one_line(item.get("text")), " (%s)" % item["locator"] if item.get("locator") else "")
            for item in findings or [] if _one_line(item.get("text"))]


def _held(events, subject_text, verdict_type):
    """A verdict this build already took, read back from the journal: a gate taken before a pause is not taken again."""
    for event in reversed(events):
        payload = event.get("payload") or {}
        if event.get("event") == "verdict" and payload.get("subject") == subject_text and payload.get("verdict_type") == verdict_type:
            return payload
    return None


def _entry(name, payload):
    return {"gate": name, "pass": bool(payload.get("pass")), "session_id": payload.get("session_id"), "model": payload.get("model"),
            "fallback_from": payload.get("fallback_from"), "points": [] if payload.get("pass") else _points(payload.get("findings")),
            "note": None}


def _parts_text(book):
    texts = []
    for part in _SAMPLED_PARTS:
        try:
            texts.append(book.path("paper/%s.md" % part).read_text(encoding="utf-8"))
        except OSError:
            continue
    return "\n\n".join(texts)


def gate(project, record, build, *, harness_root=HARNESS_ROOT, policy=None, classifier=None):
    """The three gates on one build of the paper, in order: `[{gate, pass, session_id, model, fallback_from, points, note}]`.

    Raises `gates.UsageLimited` when a usage window refuses a session (the conductor pauses, and the gates already taken
    are read back after it), and `gates.GateError` or `worker.LaunchError` when a gate cannot be taken.
    """
    from wayline import run_end
    project = Path(project).resolve()
    book = ledger_for(project)
    policy = policy_for(project, harness_root) if policy is None else policy
    author = provenance._role_tier(policy, provenance.WRITER)[0]
    named = subject(record["version"], build)
    paths = _paths(project)
    events = book.read_events()[0]
    found = []
    taken = _held(events, named, gates.KILL_ARGUMENT)
    if taken is None:
        taken = gates.kill_argument(paths, project=project, author_model=author, subject_kind="paper", subject=named,
                                    harness_root=harness_root, policy=policy, ledger=book, told=told(events),
                                    file=lambda *arguments: None).payload
    found.append(_entry(KILL, taken))
    taken = _held(book.read_events()[0], named, gates.PAPER_READ)
    if taken is None:
        taken = gates.verdict("paper", named, READ_QUESTION, paths, READ_SCOPE, project=project, author_model=author,
                              verdict_type=gates.PAPER_READ, harness_root=harness_root, policy=policy, ledger=book).payload
    found.append(_entry(READ, taken))
    text = _parts_text(book)
    sampled = run_end.sample_new(project, text, PAPER_SUBJECT, harness_root=harness_root, policy=policy,
                                 classifier=classifier, prose_author=author, scope_down=False)
    if sampled["waiting"]:
        # A drawn claim not judged is no pass: the gate waits for Fable's weekly window, as the run-end gates do, and the
        # verdicts taken so far are read back when it is taken again.
        raise gates.FableHeld("%d claim(s) of the paper's build %d wait on Fable's weekly window" % (len(sampled["waiting"]), build))
    # Every claim the parts make now whose latest verdict failed is a point: one judged in this build or before a pause,
    # and one an earlier build failed that this build left as it was, which is never drawn again.
    latest = {}
    for event in book.read_events()[0]:
        payload = event.get("payload") or {}
        if event.get("event") == "verdict" and payload.get("subject_kind") == provenance.CLAIM:
            latest[payload.get("subject")] = payload
    points = []
    for claim in provenance.tagged_claims(text, provenance.read_claims_cache(book)):
        payload = latest.get(provenance.claim_subject(claim, PAPER_SUBJECT))
        if payload is None or payload.get("pass"):
            continue
        reasons = "; ".join(_points(payload.get("findings"))) or "its cited artifacts do not support it"
        points.append('the claim "%s" is not supported: %s' % (_plain(claim.text), reasons))
    note = "%d claim(s) never sampled, %d drawn, %d judged now" % (
        sampled["new"], sampled["sampled"], len(sampled["passed"]) + len(sampled["failed"]))
    found.append({"gate": SAMPLED, "pass": not points, "session_id": None, "model": None, "fallback_from": None,
                  "points": points, "note": note})
    return found


# --- one step of the order --------------------------------------------------------------------------------------------


def take(project, order, *, harness_root=HARNESS_ROOT, policy=None, say=None, classifier=None):
    """One build of the open order `order`: its composition when it is owed, then its gates. Returns `{build, outcome,
    points, record}`, `outcome` one of `passed`, `next` (the next build is owed), and `not_passed`.

    Journals `composed` (through `paper.compose`), then `passed`, `gated`, or `not_passed`, and writes the build into
    `paper.json` and `PAPER.md`. Raises what `paper.compose` and `gate` raise; nothing after a raise is journaled.
    """
    from wayline import paper
    project = Path(project).resolve()
    book = ledger_for(project)
    policy = policy_for(project, harness_root) if policy is None else policy
    state = progress(book.read_events()[0], order)
    if state["step"] != "gate":
        paper.compose(project, order, harness_root=harness_root, policy=policy, say=say,
                      build=state["build"], rebuild=state["points"] if state["step"] == "rebuild" else None)
        state = progress(book.read_events()[0], order)
    record = paper.read_record(book)
    build = state["build"]
    found = gate(project, record, build, harness_root=harness_root, policy=policy, classifier=classifier)
    points = [point for entry in found for point in entry["points"]]
    passed = all(entry["pass"] for entry in found)
    last = state["first"] + allowed(policy) - 1
    outcome = PASSED if passed else (NOT_PASSED if build >= last else NEXT)
    with book.lock():
        record = paper.read_record(book)
        record["builds"] = [entry for entry in record.get("builds") or [] if entry["build"] != build] + [
            {"build": build, "gates": found, "passed": passed}]
        record["gated"] = True
        record["outcome"] = PASSED if passed else (NOT_PASSED if outcome == NOT_PASSED else None)
        book.write_json("paper/%s" % paper.PAPER_JSON, record, schema=paper.RECORD_SCHEMA)
        _rewrite_report(book, record)
        action = {PASSED: PASSED, NOT_PASSED: NOT_PASSED, NEXT: GATED}[outcome]
        payload = {"order": order["order"], "action": action, "by": order.get("by") or "owner", "version": record["version"],
                   "build": build}
        if not passed:
            payload["points"] = points
        book.append_event(PAPER_ORDER, payload)
    if say is not None:
        say("  paper order %s: build %d %s%s" % (order["order"], build, {PASSED: "passed its gates", NEXT: "failed its gates; the "
                                                                          "next build is owed", NOT_PASSED: "failed its gates: the paper is not passed"}[outcome],
                                               " (%d point(s) standing)" % len(points) if points else ""))
    return {"build": build, "outcome": outcome, "points": points, "record": record}


# --- the build report -------------------------------------------------------------------------------------------------


BUILDS_BEGIN = "<!-- wayline:builds -->"
BUILDS_END = "<!-- /wayline:builds -->"


def report_lines(record, closing=None):
    """`PAPER.md`'s builds section, between its markers: each build's gates with the points still standing, and how the
    paper stands; `closing` in place of that last line when the order ended otherwise (it failed, or the owner chose)."""
    lines = [BUILDS_BEGIN, "## Builds and their gates", ""]
    builds = (record or {}).get("builds") or []
    if not builds:
        lines.append("This build is not yet gated: no kill argument, independent read, or sampled verdict has judged it. "
                     "Nothing was submitted anywhere.")
    for entry in builds:
        lines += ["### Build %d: %s" % (entry["build"], "passed" if entry["passed"] else "failed"), ""]
        for item in entry["gates"]:
            by = " (verifier session %s, %s%s)" % (item["session_id"] or "unknown", item["model"] or "an unnamed model",
                                                   ", on Opus in place of %s" % item["fallback_from"] if item.get("fallback_from") else "") \
                if item["session_id"] else ""
            lines.append("- %s: %s%s%s" % (GATE_TITLES[item["gate"]], "passed" if item["pass"] else "failed", by,
                                          "; %s" % item["note"] if item.get("note") else ""))
            lines += ["  - standing: %s" % point for point in item["points"]]
        lines.append("")
    outcome = (record or {}).get("outcome")
    if closing:
        lines.append(closing)
    elif outcome == PASSED:
        lines.append("The paper passed at build %d. Nothing was submitted anywhere." % builds[-1]["build"])
    elif outcome == NOT_PASSED:
        lines.append("The paper is **not passed**: its last build left the points above standing. Choose %s, %s, or %s "
                     "(say so in the conversation). Nothing was submitted anywhere." % (CHOICES[MORE], CHOICES[KEEP], CHOICES[OBJECTIVES]))
    elif builds:
        lines.append("The next build is owed: a fresh writer session given these parts and the points standing.")
    lines.append(BUILDS_END)
    return lines


def closing_note(project, text):
    """Say in `PAPER.md`'s builds section how the order ended when no build did: it failed (a gate that could not be
    taken, a later build that could not be composed), or the owner chose after a paper not passed. Nothing when no paper
    is composed."""
    from wayline import paper
    book = ledger_for(project)
    try:
        record = paper.read_record(book)
    except paper.PaperError:
        return
    if record is not None:
        try:
            _rewrite_report(book, record, closing=text)
        except (OSError, ValueError, LedgerError):
            pass  # the journal holds how the order ended; the report says it at the next build


def _rewrite_report(book, record, closing=None):
    from wayline import paper
    path = book.path("paper/%s" % paper.PAPER_MD)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    section = "\n".join(report_lines(record, closing))
    if BUILDS_BEGIN in text and BUILDS_END in text:
        head, rest = text.split(BUILDS_BEGIN, 1)
        text = head + section + rest.split(BUILDS_END, 1)[1]
    else:
        text = text.rstrip("\n") + "\n\n" + section + "\n"
    book.write_markdown("paper/%s" % paper.PAPER_MD, text)


# --- the owner's choice after a paper not passed ----------------------------------------------------------------------


def pending_choice(project_or_events):
    """The `not_passed` payload of the last order when the owner has not chosen since and no order is open, else None."""
    from wayline import replay
    events = project_or_events if isinstance(project_or_events, list) else ledger_for(project_or_events).read_events()[0]
    orders = _orders(events)
    if replay.open_paper_order(orders) is not None or not orders:
        return None
    last = orders[-1]
    return last if last.get("action") == NOT_PASSED else None


def waiting_lines(project_or_events):
    """The account's "Waiting on you" line for a paper not passed whose choice is the owner's, empty when none waits."""
    found = pending_choice(project_or_events)
    if found is None:
        return []
    return ["- The paper (version %s, paper order %s) is not passed: build %s left %d point(s) standing (research/paper/PAPER.md). "
            "Choose %s, %s, or %s: say which in the dashboard's chat, or in any conversation with the project." % (
                found.get("version"), found.get("order"), found.get("build"), len(found.get("points") or []),
                CHOICES[MORE], CHOICES[KEEP], CHOICES[OBJECTIVES])]


_STARTS = object()


def choose(project, choice, by="owner", start=_STARTS):
    """The owner's choice after a paper not passed: `more`, `keep`, or `objectives`. Returns `{choice, order, objectives,
    run, started}`.

    `more` reopens the order for `policy.paper.builds` more builds from the points standing, and starts a conductor when
    none runs, as the order does (`run` as `paper.order` sets it); `objectives` records each point as the owner's open
    objective; `keep` keeps the paper as it is. Journals `chosen`. Refused when no paper waits on a choice.
    """
    from wayline import objectives as objectives_module, paper, replay
    if choice not in CHOICES:
        raise BuildsError("the choice is one of %s, got %r" % (", ".join(CHOICES), choice))
    project = Path(project).resolve()
    book = ledger_for(project)
    added = []
    with book.lock():
        events = book.read_events()[0]
        found = pending_choice(events)
        if found is None:
            raise BuildsError("no paper waits on a choice: one is asked only after a paper order's builds left it not passed")
        holder = conductor_holder(project)
        run = None
        if choice == MORE:
            view = replay.replay(events)
            run = None if holder is not None else ("stopped" if view.run is None else view.run.get("ended"))
        if choice == OBJECTIVES:
            # Before the choice is journaled, so a point that cannot be recorded leaves the choice to be made again; a
            # point an earlier try recorded is not recorded twice.
            held = {_one_line(item["text"]) for item in objectives_module.read_objectives(project)}
            for point in found.get("points") or []:
                if _one_line(point) not in held:
                    added.append(objectives_module.add_objective(project, point, by=by)[0]["id"])
        payload = {"order": found["order"], "action": CHOSEN, "by": by, "choice": choice, "version": found.get("version")}
        if choice == MORE:
            payload["run"] = run
        book.append_event(PAPER_ORDER, payload)
    closing_note(project, {MORE: "The paper was not passed, and the owner chose %s: they follow from the points above.",
                           KEEP: "The paper was not passed, and the owner chose to %s, marked not passed.",
                           OBJECTIVES: "The paper was not passed, and the owner chose %s: the points above are open objectives."}[choice]
                 % CHOICES[choice])
    started = None
    if choice == MORE and holder is None and start is not None:
        try:
            started = (paper._start_conductor if start is _STARTS else start)(project) or ""
        except (OSError, ValueError, RuntimeError) as failure:
            started = "not started (%s); the tick starts one, or wayline run --detach" % _one_line(failure)
    return {"choice": choice, "order": found["order"], "objectives": added, "run": run, "conductor": holder is not None,
            "started": started}


def builds_command(args):
    """`wayline paper builds more|keep|objectives [--project <path>]`: the owner's choice after a paper not passed."""
    parser = argparse.ArgumentParser(prog="wayline paper builds", description="the owner's choice after a paper not passed: "
                                     "more (three more builds), keep (the paper as it is), or objectives (the points standing "
                                     "as the owner's objectives)")
    parser.add_argument("choice", choices=list(CHOICES))
    parser.add_argument("--project", help="the project; the active one by default")
    options, code = parse_args(parser, args)
    if options is None:
        return code
    try:
        made = choose(find_project(options.project), options.choice)
    except BuildsError as failure:
        print("wayline paper builds: %s" % failure, file=sys.stderr)
        return 2
    except (ProjectError, LedgerError, OSError, ValueError) as failure:
        print("wayline paper builds: %s" % failure, file=sys.stderr)
        return 1
    if made["choice"] == MORE:
        print("paper order %d reopened for more builds from the points standing%s." % (
            made["order"], "; the running conductor takes it" if made["conductor"] else
            "; a conductor was started for it%s" % (" (%s)" % made["started"] if made["started"] else "")))
    elif made["choice"] == OBJECTIVES:
        print("the points standing are objectives %s." % (", ".join(made["objectives"]) or "none: no point stood"))
    else:
        print("the paper is kept as it is, marked not passed.")
    return 0


# --- the writer's part ------------------------------------------------------------------------------------------------


def order_concerns(project):
    """The concerns kept for the order and still open, `[{id, text}]`, each with its first source's verbatim words."""
    from wayline import concerns
    try:
        held = concerns.read_concerns(project)
    except (OSError, ValueError):
        return []
    return [{"id": item["id"], "text": _one_line(item["sources"][0]["text"])} for item in held
            if item.get("place") == "order" and item.get("status") == "open"]


def _routes(project):
    from wayline import verification
    try:
        held = verification.read_results(project)
    except (OSError, ValueError):
        return []
    found = []
    for result in held:
        for verdict in result.get("verdicts") or []:
            if verdict["route"] not in found:
                found.append(verdict["route"])
    return found


def _table_label(plan):
    supplementary = [table for table in (plan or {}).get("tables") or [] if not table.get("main")]
    return "Supplementary Table S%d" % (len(supplementary) + 1)


def writer_lines(project, rebuild=None, build=1, plan=None):
    """The writer's prompt's part from this ticket: the build, the points standing, the concerns for the order, and the
    inherited results' table and routes."""
    lines = []
    if rebuild is not None:
        lines += ["", "## This build", "",
                  "This is build %d of this order: a fresh writer session given the previous build's parts, which are "
                  "under research/paper/ (read the whole of it). Its gates left the points below standing. Write every "
                  "part you are asked for again, answering each point: the evidence it asks for where the project has it, "
                  "or the claim scoped down to what the artifacts support. Do not answer a point by asserting it away, and "
                  "say in `notes` what only the owner can supply." % build, ""]
        lines += ["- %s" % point for point in rebuild] or ["- none was recorded"]
    found = order_concerns(project)
    lines += ["", "## The concerns kept for the order", ""]
    if found:
        lines.append("Each is a point the paper answers where it bears on it. Say in `concerns` how the paper answers each, "
                     "by its id; one it cannot answer, say so and why.")
        lines += ["- %s: %s" % (item["id"], item["text"]) for item in found]
    else:
        lines.append("- none")
    routes = _routes(project)
    if inherited_table(project, plan) is not None:
        lines += ["", "## The inherited results", "",
                  "%s is code's: it renders each inherited result's verdict, route, narrowed wording, and reasons, after the "
                  "supplement you write. Refer to it where the text discusses the inherited results, and write no table of "
                  "your own for them." % _table_label(plan)]
        if routes:
            lines.append("Add one Methods paragraph naming the routes the verifications took, each by its name: %s." % ", ".join(routes))
    return "\n".join(lines) + "\n"


def _doc_tag(item):
    return "{doc:%s}" % item["doc"] if item.get("doc") else None


def answer_problems(project, answer, written, followed, passages):
    """The Type-A checks of a writer's answer this ticket adds: problems, one line each, empty when it passes.

    An unverifiable claim the order left out is in no part (its `{doc:...}` tag or its words); one it kept is stated as
    not verified in each sentence carrying its tag; the Methods name every route the verifications took; and a concern
    answered is one kept for the order.
    """
    from wayline import paper
    texts = {part: answer.get(part) for part in ("abstract", "introduction", "results", "discussion", "methods", "supplement")
             if part in written and answer.get(part)}
    problems = []
    for item in followed:
        if not str(item["ref"]).startswith("unverifiable:"):
            continue
        identifier = item["ref"].split(":", 1)[1]
        passage = passages.get(identifier) or {}
        tag = _doc_tag(passage)
        words = paper._words(passage.get("text"))
        said = " %s " % " ".join(words)
        for part, text in texts.items():
            sentences = [sentence for sentence in re.split(r"(?<=[.!?])\s+", text) if tag and tag in sentence]
            if item["mark"] == paper.LEAVE_OUT:
                if sentences or (len(words) >= 5 and said in " %s " % " ".join(paper._words(text))):
                    problems.append("%s carries %s, an unverifiable claim the order left out: leave it out of every part" % (part, identifier))
            else:
                problems += ['%s: the sentence carrying %s (%s) does not say it is not verified: say "not verified" and why (%s)' % (
                    part, identifier, tag, _one_line(passage.get("reason")) or "its reason") for sentence in sentences
                    if not NOT_VERIFIED.search(sentence)]
    routes = _routes(project)
    if "methods" in written and routes:
        missing = [route for route in routes if not re.search(r"\b%s\b" % route, str(answer.get("methods") or ""), re.I)]
        if missing:
            problems.append("methods: add one paragraph naming the routes the verifications took; it does not name %s" % ", ".join(missing))
    known = {item["id"] for item in order_concerns(project)}
    for item in answer.get("concerns") or []:
        if item.get("id") not in known:
            problems.append("concerns: %s is no concern kept for the order (%s)" % (item.get("id"), ", ".join(sorted(known)) or "none is"))
    return problems


# --- the inherited results' table -------------------------------------------------------------------------------------


def _cell(text):
    return _one_line(text).replace("|", "\\|") or "none"


def inherited_table(project, plan=None):
    """The supplementary table of every inherited result, rendered by code from `research/verifications.json` and the
    passages: its verdict, its route, the narrowed wording, and the reasons. None when the project inherited none."""
    from wayline import sections, verification
    book = ledger_for(project)
    try:
        record = verification.current_record(book)
        rows = verification.claim_rows(book)
    except (OSError, ValueError, LedgerError):
        return None
    if not record["results"]:
        return None
    texts = {item.get("id"): item.get("text") for item in list(sections.read_passages(book)) + list(sections.read_findings(book))}
    lines = ["**%s.** The inherited results: each one's verdict, the route its verification took, the wording the evidence "
             "narrowed it to, and the reasons. Rendered by code from the verifications." % _table_label(plan), "",
             "| Inherited result | Verdict | Route | Narrowed wording | Reasons |", "|---|---|---|---|---|"]
    for result in record["results"]:
        mine = [row for row in rows if row["heading"] == result["heading"]]
        said = [("%s %s" % (row["claim"], row["verdict"])) for row in mine if row["verdict"]]
        verdict = result["standing"] + (": %s" % ", ".join(said) if said else "")
        routes = sorted({verdict_entry["route"] for verdict_entry in result.get("verdicts") or []})
        narrowed = ["%s: %s" % (row["by"], _plain(texts.get(row["by"]))) for row in mine
                    if row["verdict"] == "narrows" and row["by"]]
        reasons = []
        if result.get("reason"):
            reasons.append(result["reason"])
        reasons += ["%s: %s" % (row["claim"], row["reason"]) for row in mine if row["reason"] and row["reason"] != result.get("reason")]
        reasons += ["on substitute data: %s" % verdict_entry["substitute"] for verdict_entry in result.get("verdicts") or []
                    if verdict_entry.get("substitute")]
        reasons += ["contradicted by the evidence: %s" % row["claim"] for row in mine if row["verdict"] == "contradicts"]
        if result["standing"] == "unchecked" and not reasons:
            reasons.append("not verified before this order")
        lines.append("| %s | %s | %s | %s | %s |" % (_cell(result["heading"]), _cell(verdict), _cell(", ".join(routes)),
                                                    _cell("; ".join(narrowed)), _cell("; ".join(reasons))))
    return "\n".join(lines) + "\n"


def with_table(text, project, plan=None):
    """The supplement as written, with the inherited results' table code appends after it, when there is one."""
    text = str(text or "").split(TABLE_MARK, 1)[0].rstrip()
    table = inherited_table(project, plan)
    if table is None:
        return text + "\n"
    return "%s\n\n%s\n\n%s" % (text, TABLE_MARK, table)


# --- the responses to the critiques -----------------------------------------------------------------------------------


def _critiques(project):
    from wayline import documents
    try:
        held = documents.read_documents(project)
    except (OSError, ValueError):
        return []
    return [document for document in held if document.get("kind") == "critique"]


def _answer(concern, answered):
    status = concern.get("status")
    if status == "answered":
        return _one_line(concern.get("answer")) or "Answered by the work."
    if status == "declined":
        return "Declined: %s" % (_one_line(concern.get("reason")) or "no reason was recorded")
    if concern.get("place") == "order":
        given = answered.get(concern["id"])
        return given or "Kept for the paper order; this version of the paper does not say how it answers it."
    if concern.get("place") == "objectives":
        return "Open: the work on %s answers it, and has not yet." % (", ".join(concern.get("objectives") or []) or "its objectives")
    return "Open: not yet sorted."


def write_responses(book, record):
    """One `response/<critique>.md` per critique of the project, each point verbatim with its answer; returns the names.
    Rewritten at each composition, under the ledger's lock. Nothing sends one."""
    from wayline import concerns
    critiques = _critiques(book.project)
    book.remove_tree("paper/%s" % RESPONSE_DIR)
    if not critiques:
        return []
    try:
        held = concerns.read_concerns(book.project)
    except (OSError, ValueError):
        held = []
    answered = {item["id"]: _one_line(item["answer"]) for item in record.get("concerns") or [] if _one_line(item.get("answer"))}
    names = []
    for critique in critiques:
        name = critique["id"]
        if not _CRITIQUE.match(name):
            continue
        lines = ["# Response to %s, %s" % (name, _one_line(critique.get("title")) or "a critique"), "",
                 "Code writes this response from the concerns at version %d of the paper: each point of the critique as it "
                 "said it, and its answer. It is never sent." % record["version"]]
        points = [(source, concern) for concern in held for source in concern["sources"] if source["critique"] == name]
        if not points:
            lines += ["", "No point of this critique became a concern."]
        for number, (source, concern) in enumerate(points, start=1):
            lines += ["", "## Point %d (%s, %s)" % (number, concern["id"], source["locator"]), ""]
            lines += ["> %s" % line if line else ">" for line in str(source["text"]).strip().splitlines()]
            lines += ["", "**Answer.** %s" % _answer(concern, answered)]
        book.write_markdown("paper/%s/%s.md" % (RESPONSE_DIR, name), "\n".join(lines) + "\n")
        names.append(name)
    return names


# --- the concerns at the figure finish and the compilation ------------------------------------------------------------


def change_requests(project):
    """The concerns kept for the order as the figure finish's change requests (`from: paper`)."""
    return [{"id": item["id"], "text": item["text"], "from": "paper"} for item in order_concerns(project)]


def concern_checks(project, record):
    """The compilation's checks on the concerns kept for the order: one per concern open for it now, `ok` when the paper's
    writer said how the paper answers it, `fail` when the writer was asked and did not, and `warn` for one placed on the
    order after the parts were written, which the next order asks about."""
    answered = {item["id"]: _one_line(item["answer"]) for item in (record or {}).get("concerns") or [] if _one_line(item.get("answer"))}
    asked = set((record or {}).get("concerns_asked") or [])
    found = []
    for item in order_concerns(project):
        if item["id"] in answered:
            level, said = "ok", "the paper answers it: %s" % answered[item["id"]]
        elif item["id"] in asked:
            level, said = "fail", "the paper does not say how it answers it"
        else:
            level, said = "warn", "placed on the order after this version was written; the next paper order asks about it"
        found.append({"check": "concern", "level": level, "message": "%s, kept for the paper order (%s): %s" % (
            item["id"], item["text"][:120], said)})
    return found
