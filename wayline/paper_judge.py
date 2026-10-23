"""The decider orders the paper under `autonomous` (Implementation Decision 17; ticket 120).

An autonomous run can end with a paper the owner never ordered by hand. **The setup answer** (setup question 8,
`harness.json`'s `paper_order`, `{decider, venue}`, recorded by `wayline intake`) decides whether the decider judges the
paper order and for which venue; a project without the key judges for no venue (`setting`).

**When.** Only at the stopping rule's own ends (`objectives_closed`, `goal_reached`, `frontier_empty`), after the run-end
gates and the drawings, never after `budget_spent`, `stall_strict`, `stopped`, or `switched`; once per end, read back
from the journal (`judged`), so a wave replayed after a restart never judges again.

**Code first** (`checks`, no model call): no objective the stopping rule names is open; the general report's last kill
argument passed, or its scope-downs are done; the outline has no main-text gap; every changed result is drawn; and at a
start midway, "Do the inherited results hold?" is answered. A failing check is journaled as `paper_judged` with what
failed, and no session launches.

**The session** (`judge`): one decider session on `policy.roles.decider` (`opus max`) reads `REPORT.md`,
`OBJECTIVES.md`, and `OUTLINE.md` and returns `paper_judgment`: order or not, with its reason. When it orders, it answers
the order's batch in the same session (the figure plan, oversized figures, contradictions, unverifiable claims,
unresolved references, the outline's open proposals): code marks the batch `by: decider`, splitting an oversized figure
it would drop and declining a merge that would move a line the owner placed, and `paper.order` runs with the setup's
venue, its run ending as this end once the paper is made. Each choice is a `decision` (`decided_by: decider`), so the
account lists it under "Decided for you". Once the builds settle, the decider picks among the writer's titles and the
paper's other alternatives (`choose_alternatives`), each pick listed there too. A paper not passed after its builds
stops under "Waiting on you" (ticket 117).
"""

import re
from pathlib import Path

from wayline import HARNESS_ROOT, batches, gates, worker
from wayline.jsonschema import ValidationError, check, load_schema
from wayline.ledger import DECISION, OUTLINE, PAPER_JUDGED, LedgerError, ledger_for
from wayline.project import policy_for, read_harness

__all__ = ["KEY", "setting", "check_answer", "PaperJudgeError", "checks", "CHECKS", "ENDS", "SCHEMA", "PREFIX", "judge",
           "record_held", "owner_placed", "decision_parts", "judged", "reversed_by_owner", "considered", "choose_alternatives"]

KEY = "paper_order"  # harness.json's key: the setup's answer
DEFAULT = {"decider": True, "venue": None}
# Code's checks, in the order they are said: each failing one is `{check, said}`.
CHECKS = ("objectives", "kill", "gaps", "drawn", "inherited")
DONE = ("done", "accepted")
ENDS = ("objectives_closed", "goal_reached", "frontier_empty")  # the stopping rule's own ends: the only ones judged at
SCHEMA = "paper_judgment"
SLUG = "paper-order"  # research/sessions/decider/paper-order/<n>
DECIDER = "decider"
# The `decision` each choice is journaled as, which the account lists under "Decided for you": the judgment
# (`paper order: order it, ...` or `paper order: not now`), and each answer of the order's batch and each alternative
# picked (`paper order 1 (<ref>): <mark>`).
PREFIX = "paper order"
ORDER_IT, NOT_NOW = "order it", "not now"
_DECISION = re.compile(r"^paper order(?: ([1-9][0-9]*) \(([^()]+)\))?: (.*)$", re.S)
RESUME = ("The judgment you returned could not be used: %s. Return it again through the structured output, as the "
          "paper_judgment schema asks, and change nothing else about it.")


class PaperJudgeError(ValueError):
    """A setup answer of the wrong shape, or a venue `guidelines/` does not hold."""


def setting(harness):
    """`{decider, venue}`: the setup's answer, or yes with no venue for a project that holds none."""
    found = (harness or {}).get(KEY)
    if not isinstance(found, dict):
        return dict(DEFAULT)
    return {"decider": found.get("decider") is not False, "venue": found.get("venue") or None}


def check_answer(value, harness_root=HARNESS_ROOT):
    """The setup's answer as `harness.json` holds it, or PaperJudgeError: `{decider: bool, venue: <slug> | null}`, the
    venue one `guidelines/` holds."""
    from wayline import guidelines
    from wayline.jsonschema import ValidationError
    if not isinstance(value, dict) or set(value) - {"decider", "venue"} or not isinstance(value.get("decider"), bool) \
            or not isinstance(value.get("venue"), (str, type(None))):
        raise PaperJudgeError("paper_order is {\"decider\": true|false, \"venue\": \"<slug>\"|null}, got %r" % (value,))
    venue = (value.get("venue") or "").strip() or None
    if venue is not None:
        try:
            guidelines.read_guidelines(harness_root, venue)
        except (guidelines.GuidelinesError, ValidationError, OSError) as failure:
            raise PaperJudgeError("paper_order names the venue %s, which guidelines/ does not hold: %s" % (venue, failure)) from None
    return {"decider": value["decider"], "venue": venue}


# --- code's checks --------------------------------------------------------------------------------------------------


def _one_line(text):
    return " ".join(str(text or "").split())


def _objectives(book):
    from wayline import objectives, stopping
    rule = stopping.rule_of(read_harness(book.project))
    waiting = stopping.waited(rule, objectives.read_objectives(book.project))
    if waiting:
        return "the stopping rule still waits on %s, open" % ", ".join(record["id"] for record in waiting)
    return None


def _kill(book, events):
    from wayline import run_end
    last = run_end.last_kill_verdict(events)
    if last is None:
        return "no kill argument has run on the general report"
    if last.get("pass"):
        return None
    filed = [fields for fields in run_end.scope_downs(book.project) if fields.get("origin") == run_end.KILL_ORIGIN]
    if not filed:
        return "the general report's last kill argument failed and filed no scope-down"
    owed = [fields for fields in filed if fields.get("status") not in DONE]
    if owed:
        return "the general report's last kill argument failed, and its scope-down %s not done: %s" % (
            "is" if len(owed) == 1 else "are", ", ".join("ticket %d (%s)" % (fields["id"], fields["status"]) for fields in owed))
    return None


def _gaps(book):
    from wayline import outline
    main = outline.gaps(book)[0]
    if main:
        return "the outline has %d main-text gap(s): %s" % (len(main), "; ".join(
            _one_line(line[2:] if line.startswith("- ") else line) for line in main))
    return None


def _drawn(book):
    from wayline import drawings
    left = drawings.undrawn(book.project)
    if left:
        return "result(s) changed since their last drawing and not drawn: %s" % ", ".join(left)
    return None


def _inherited(book):
    from wayline import objectives, verification
    if not verification.midway(book.project):
        return None
    wanted = verification.OBJECTIVE.casefold()
    found = [record for record in objectives.read_objectives(book.project) if _one_line(record["text"]).casefold() == wanted]
    if not found:
        return 'the project started midway, and "%s" is not recorded as an objective' % verification.OBJECTIVE
    if found[-1]["status"] != "answered":
        return '"%s" (%s) is %s, not answered' % (verification.OBJECTIVE, found[-1]["id"], found[-1]["status"])
    return None


def checks(project, events=None):
    """Code's checks before the decider judges the order, with no model call: `[{check, said}]` for each that fails, in
    `CHECKS` order, empty when all pass. A record that cannot be read fails its check with why."""
    book = ledger_for(project)
    events = book.read_events()[0] if events is None else events
    failed = []
    for name, read in (("objectives", lambda: _objectives(book)), ("kill", lambda: _kill(book, events)),
                       ("gaps", lambda: _gaps(book)), ("drawn", lambda: _drawn(book)), ("inherited", lambda: _inherited(book))):
        try:
            said = read()
        except (OSError, ValueError, LedgerError) as failure:
            said = "could not be checked: %s" % _one_line(failure)
        if said:
            failed.append({"check": name, "said": said})
    return failed


def judged(events):
    """The `paper_judged` payload of the end the run is at now, or None: one journaled since the last `run_ended`, so a wave
    replayed after a restart never judges the same end again."""
    from wayline.ledger import RUN_ENDED
    found = None
    for event in events:
        if event.get("event") == PAPER_JUDGED:
            found = event.get("payload") or {}
        elif event.get("event") == RUN_ENDED:
            found = None
    return found


def reversed_by_owner(events):
    """The `D` id of a decision this module journaled that the owner reversed, or None: the paper order is the owner's
    from then on, and the decider never judges it again (a reversal makes the decision human-only, decision 17)."""
    from wayline.decisions import decision_log
    from wayline.ledger import REVIEWED
    reversed_ids = {(event.get("payload") or {}).get("decision") for event in events
                    if event.get("event") == REVIEWED and (event.get("payload") or {}).get("review") == "reverse"}
    if not reversed_ids:
        return None
    for entry in decision_log(events):
        if entry["decision"] in reversed_ids and entry["decided_by"] == DECIDER and decision_parts(entry["answer"]) is not None:
            return entry["decision"]
    return None


def considered(project, end, events=None):
    """Whether the decider judges the order at `end` now: under `autonomous`, at one of the stopping rule's own ends, the
    setup said yes, the owner reversed none of its paper decisions, and this end was not judged already."""
    harness = read_harness(project)
    if end not in ENDS or harness.get("autonomy") != "autonomous" or not setting(harness)["decider"]:
        return False
    events = ledger_for(project).read_events()[0] if events is None else events
    return judged(events) is None and reversed_by_owner(events) is None


def record_held(project, end, failed):
    """Journal that code's checks held the order at `end`: `paper_judged` with what failed, and no session launched."""
    ledger_for(project).append_event(PAPER_JUDGED, {"end": end, "checks": list(failed), "ordered": None, "reason": (
        "no decider session launched: %s" % "; ".join(item["said"] for item in failed))})


# --- the owner's lines in the outline -------------------------------------------------------------------------------


def owner_placed(project, events=None):
    """The outline's lines the owner placed, in their groups' order: every line `outline.json` holds but those the decider
    placed last. The decider never moves one."""
    from wayline import outline
    book = ledger_for(project)
    events = book.read_events()[0] if events is None else events
    record = outline.read_record(book)
    last = {}
    for event in events:
        payload = event.get("payload") or {}
        if event.get("event") == OUTLINE and payload.get("action") in ("moved", "placed"):
            last[payload.get("item")] = payload.get("by")
    found = []
    for lines in (record.get("groups") or {}).values():
        found += [line for line in lines if last.get(line) != DECIDER and line not in found]
    return found


def _merge_pair(project, ref):
    """The two results an outline merge item of the order's batch (`outline:B3#1`) would merge, or []."""
    match = re.match(r"^outline:(B[1-9][0-9]*)#([1-9][0-9]*)$", str(ref))
    if not match:
        return []
    try:
        item = next(entry for entry in batches.read_batch(project, match.group(1))["items"] if entry["id"] == int(match.group(2)))
    except (batches.BatchError, ValidationError, StopIteration, OSError, ValueError):
        return []
    return str(item["ref"]).split("+")


# --- the session ----------------------------------------------------------------------------------------------------

PROMPT = """\
# The paper order: yours to judge

The run ended `%(end)s` under `autonomous`, and at setup the owner left the paper order to you, %(venue)s. Code's checks
passed: no objective the stopping rule names is open, the general report's last kill argument passed or its scope-downs
are done, the outline has no main-text gap, every changed result is drawn%(midway)s.

Decide one thing from the three records below: order the paper now, or not. Order it when the general report's
findings, the objectives' answers, and the outline make a paper worth the owner's reading in the morning; otherwise say
why not in `reason`, which the owner reads cold. The paper is made from the outline and the sections, never from new
work: ordering it starts no research ticket.

When you order it, answer the order's batch below in the same answer, one entry of `answers` per item by its `ref`, with
one of that item's marks in its words and, where it is not the order's reason, why. An item you leave out takes code's
default. The rules:

- An oversized figure is split, never dropped.
- You settle the outline's open proposals here, and you never move a line the owner placed: a merge that would take one
  of the owner's lines below is declined.
- Nothing you answer may cross the irreversible list: deleting or overwriting data, pushing, raising a budget, spending
  money, changing a goal's measure or the data, changing the harness globally. The human-only classes of this project
  are: %(classes)s.

When you do not order it, `answers` is empty.

# The order's batch
%(items)s
# The lines the owner placed in the outline
%(placed)s
%(records)s
# The paths you may open

The project is `%(project)s`; open with the Read tool what a record points into: `research/sections/<section>.md`, the
results' reports under `research/reports/`, and `research/CONCERNS.md`.
"""


def _items_text(items):
    if not items:
        return "\nNone: the order asks nothing.\n"
    return "\n" + "\n".join("- `%s`: %s (marks: %s; code's default: %s)" % (
        item["ref"], _one_line(item["text"]), " | ".join(item["marks"]), item.get("default") or "none") for item in items) + "\n"


def _prompt(role, project, end, venue, items, placed, records):
    from wayline import decider, verification
    harness = read_harness(project)
    text = PROMPT % {
        "end": end, "venue": "for %s" % venue if venue else "for no venue (the paper is compiled plainly)",
        "midway": ', and "%s" is answered' % verification.OBJECTIVE if verification.midway(project) else "",
        "classes": decider._classes(harness), "items": _items_text(items),
        "placed": "\n" + ("\n".join("- `%s`" % line for line in placed) if placed else "None.") + "\n",
        "records": records, "project": project,
    }
    return "\n\n".join(part.strip("\n") for part in (text, role.protocol, worker.schema_section("# The judgment", SCHEMA, closing=[
        "", "`order` is true to order the paper now; `reason` says why, or why not; `confidence` is from 0 to 1, and honest."]))
        if part and part.strip()) + "\n"


def _request(project, end, venue, items, placed, harness_root, policy, fall_back):
    from wayline import decider, objectives, outline, provenance
    model, effort, fallback_from = decider.decider_tier(policy, fall_back)
    role = worker.read_role(DECIDER, harness_root, project)
    book = ledger_for(project)

    def read(relative):
        try:
            return book.path(relative).read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
    report = provenance.REPORT_PATH[len("research/"):]
    records, _ = decider.inline_records([
        (provenance.REPORT_PATH, read(report), "[wayline: there is no REPORT.md]"),
        ("research/%s" % objectives.OBJECTIVES_MD, read(objectives.OBJECTIVES_MD), "[wayline: no objective is recorded]"),
        ("research/%s" % outline.OUTLINE_MD, read(outline.OUTLINE_MD), "[wayline: there is no OUTLINE.md]"),
    ], decider._context_cap(policy, model), "Read them in this order: the general report, the objectives, the outline.")
    run_dir = decider.session_dir(project, SLUG)
    request = worker.LaunchRequest(
        role=role.name, model=model, effort=effort, prompt=_prompt(role, project, end, venue, items, placed, records),
        agent_json=role.agent_json(model, effort, decider._budget(policy, "max_turns")),
        allowed_tools=list(role.allowed_tools), disallowed_tools=list(role.disallowed_tools),
        settings_path=gates.write_worker_settings(run_dir / "settings.json", harness_root),
        add_dirs=[str(Path(harness_root).resolve()), str(project)], cwd=project, env=gates.verdict_env(project, run_dir),
        schema_path=Path(harness_root).resolve() / "schemas" / (SCHEMA + ".json"),
        max_minutes=decider._budget(policy, "max_minutes"),
    )
    return request, model, fallback_from


def _unusable(envelope, items):
    """Why an envelope is no judgment code can act on, or None."""
    if not envelope.valid:
        return "; ".join(envelope.errors) or "the session returned no structured judgment"
    returned = envelope.structured_output
    try:
        check(returned, load_schema(SCHEMA), name=SCHEMA)
    except ValidationError as failure:
        return str(failure)
    if not returned["order"]:
        return None
    known = {item["ref"]: item for item in items}
    problems, seen = [], set()
    for given in returned["answers"]:
        item = known.get(given["ref"])
        if item is None:
            problems.append("%s is no item of the order's batch" % given["ref"])
        elif given["mark"] not in item["marks"]:
            problems.append("%s takes %s, not %r" % (given["ref"], " | ".join(item["marks"]), given["mark"]))
        elif given["ref"] in seen:
            problems.append("%s is answered twice" % given["ref"])
        seen.add(given["ref"])
    return "; ".join(problems) or None


def _settle(project, items, given, placed):
    """Each item's answer, `[(item, mark, why, note)]`: the decider's, or code's default where it gave none; an oversized
    figure it would drop is split, and a merge that would take a line the owner placed is declined."""
    from wayline import paper, paper_figures
    answered = {entry["ref"]: entry for entry in given}
    settled = []
    for item in items:
        entry = answered.get(item["ref"])
        mark = entry["mark"] if entry else (item.get("default") or item["marks"][0])
        why, note = (entry or {}).get("why"), None if entry else "code's default: the decider gave no answer"
        if item["ref"].startswith(paper_figures.OVERSIZED) and mark == paper_figures.DROP:
            mark, note = paper_figures.SPLIT, "split, never dropped under autonomous; the decider said drop"
        if item["ref"].startswith("outline:") and mark == paper.TAKE:
            touched = [line for line in _merge_pair(project, item["ref"]) if line in placed]
            if touched:
                mark, note = paper.DECLINE, "declined: the merge would move %s, a line the owner placed" % ", ".join(touched)
        settled.append((item, mark, why, note))
    return settled


def _decision(book, answer, rationale, confidence, model, fallback_from, session_id):
    payload = {"ticket": None, "answer": answer, "decided_by": DECIDER, "rationale": _one_line(rationale) or None,
               "confidence": confidence}
    payload.update({key: value for key, value in (("model", model), ("fallback_from", fallback_from)) if value})
    book.append_event(DECISION, payload, session_id=session_id)


def decision_parts(answer):
    """`(order, ref, choice)` of a `decision` this module journaled, or None for another: `order` and `ref` None on the
    judgment itself."""
    match = _DECISION.match(str(answer or ""))
    if not match:
        return None
    return (int(match.group(1)) if match.group(1) else None), match.group(2), match.group(3)


def judge(project, end, *, harness_root=HARNESS_ROOT, policy=None, fall_back=None, say=None):
    """The decider's one session at the run's end `end`, once code's checks passed: order the paper or say why not.

    Returns `{ordered, order, reason}`. An order answers the batch in the same session and runs `paper.order` by the
    decider with the setup's venue, its run ending as `end` once the paper is made; every choice is a `decision`. A
    session that returns no usable judgment is resumed once with why, then recorded as not judged. A usage window that
    refused the launch raises `gates.UsageLimited`, and nothing is journaled: the conductor judges after the pause.
    """
    from wayline import paper
    project = Path(project).resolve()
    say = say or (lambda text: None)
    policy = policy_for(project, harness_root) if policy is None else policy
    book = ledger_for(project)
    venue = setting(read_harness(project))["venue"]
    items = paper.batch_items(project)
    placed = owner_placed(project)
    what = "the decider on the paper order"
    envelope, model, fallback_from = None, None, None
    try:
        request, model, fallback_from = _request(project, end, venue, items, placed, harness_root, policy, fall_back)
        envelope = worker.launch(request)
        gates.raise_if_refused(envelope, model, what)
        problem = _unusable(envelope, items)
        if problem is not None and envelope.session_id:
            envelope = worker.resume(request, envelope.session_id, RESUME % problem)
            gates.raise_if_refused(envelope, model, what)
            problem = _unusable(envelope, items)
    except (worker.LaunchError, worker.RoleError, ValueError, OSError) as failure:
        problem = _one_line(failure)
    if problem is not None:
        reason = "the decider could not judge the paper order: %s" % problem
        book.append_event(PAPER_JUDGED, {"end": end, "checks": [], "ordered": None, "venue": venue, "reason": reason},
                          session_id=getattr(envelope, "session_id", None))
        say("  " + reason)
        return {"ordered": False, "order": None, "reason": reason}
    returned = envelope.structured_output
    model, session = envelope.model or model, envelope.session_id
    reason, confidence = _one_line(returned["reason"]), returned["confidence"]
    if not returned["order"]:
        _decision(book, "%s: %s" % (PREFIX, NOT_NOW), reason, confidence, model, fallback_from, session)
        book.append_event(PAPER_JUDGED, {"end": end, "checks": [], "ordered": False, "venue": venue, "reason": reason},
                          session_id=session)
        say("  the decider did not order the paper: %s" % reason)
        return {"ordered": False, "order": None, "reason": reason}
    settled = _settle(project, items, returned["answers"], placed)
    batch = None
    try:
        if settled:
            batch = batches.open_batch(project, paper.BATCH_KIND, "The paper order: answered by the decider",
                                       [item for item, _, _, _ in settled])["id"]
            numbers = {item["ref"]: item["id"] for item in batches.read_batch(project, batch)["items"]}
            for item, mark, why, note in settled:
                batches.mark(project, batch, numbers[item["ref"]], mark, note=note, by=DECIDER)
        made = paper.order(project, by=DECIDER, start=None, venue=venue, harness_root=harness_root, run=end, batch=batch)
    except (paper.PaperError, batches.BatchError, ValidationError, LedgerError, OSError, ValueError) as failure:
        reason = "the decider ordered the paper, and the order could not be made: %s" % _one_line(failure)
        book.append_event(PAPER_JUDGED, {"end": end, "checks": [], "ordered": None, "venue": venue, "reason": reason},
                          session_id=session)
        say("  " + reason)
        return {"ordered": False, "order": None, "reason": reason}
    number = made["order"]
    _decision(book, "%s: %s, as paper order %d%s" % (PREFIX, ORDER_IT, number, " for %s" % venue if venue else ""), reason,
              confidence, model, fallback_from, session)
    for item, mark, why, note in settled:
        _decision(book, "%s %d (%s): %s" % (PREFIX, number, item["ref"], mark), note or why or reason, confidence, model,
                  fallback_from, session)
    book.append_event(PAPER_JUDGED, {"end": end, "checks": [], "ordered": True, "order": number, "venue": venue,
                                     "reason": reason}, session_id=session)
    say("  the decider ordered the paper as paper order %d%s: %s" % (number, " for %s" % venue if venue else "", reason))
    return {"ordered": True, "order": number, "reason": reason}


# --- the alternatives, once the builds settled -------------------------------------------------------------------------


def choose_alternatives(project, payload, *, harness_root=HARNESS_ROOT, policy=None, fall_back=None, say=None):
    """The decider's pick among the writer's titles and the paper's other alternatives, once the builds of its order
    `payload` settled: one decider session on the `decision` schema, each pick put in its part with `paper.choose` and
    journaled as a `decision`. Returns the alternatives picked. A session that picks nothing usable, or is refused,
    leaves the writer's own choice in each part, said; a usage window that refused the launch raises out."""
    from wayline import decider, paper
    project = Path(project).resolve()
    say = say or (lambda text: None)
    book = ledger_for(project)
    record = paper.read_record(book)
    if record is None or record.get("order") != payload.get("order"):
        return []
    offered = {part: paper.alternatives_of(book, record, part) for part in paper.WRITTEN}
    offered = {part: found for part, found in offered.items() if found}
    if not offered:
        return []
    options = ["%s: %s" % (name, _one_line(text)[:400]) for found in offered.values() for name, text in found]
    question = ("Paper order %d is composed, version %d of the paper. For each part that has alternatives, pick the one the paper "
                "carries, by its name, one per part, separated by semicolons (title-2; results-1). The part holds the "
                "writer's own choice now: its title is title-1." % (payload["order"], record["version"]))
    subject = decider.Subject(kind="paper", key="paper order %d's title and alternatives" % payload["order"], question=question,
                              options=options, recommended="title-1" if "title" in offered else None,
                              evidence=["research/paper/PAPER.md: the build report, with each gate's points",
                                        "research/paper/abstract.md and research/paper/results.md: what the title names"],
                              slug="paper-alternatives")
    outcome, returned, envelope, model, fallback_from = decider._attempt(subject, project=project, harness_root=harness_root,
                                                                         policy=policy, fall_back=fall_back)
    if outcome is not None:
        say("  the decider picked no alternative of paper order %d (%s): the writer's own choices stand" % (
            payload["order"], outcome.why))
        return []
    outcome = decider._decided(subject, returned, envelope, model, fallback_from)
    texts = {name: text for found in offered.values() for name, text in found}
    picked = {}
    for part, number in re.findall(r"\b(%s)-([1-9][0-9]*)\b" % "|".join(map(re.escape, offered)), outcome.answer):
        name = "%s-%s" % (part, number)
        if name in texts and part not in picked:
            picked[part] = name
    if not picked:
        say("  the decider's pick names no alternative of paper order %d (%s): the writer's own choices stand" % (
            payload["order"], _one_line(outcome.answer)))
        return []
    chosen = []
    for part, name in picked.items():
        try:
            paper.choose(project, name)
        except paper.PaperError as failure:
            say("  %s could not be put in the paper: %s" % (name, failure))
            continue
        _decision(book, '%s %d (%s): %s, "%s"' % (PREFIX, payload["order"], part, name, _one_line(texts[name])[:200]),
                  outcome.rationale, outcome.confidence, outcome.model, fallback_from, outcome.session_id)
        chosen.append(name)
    if chosen:
        say("  the decider picked %s for paper order %d" % (", ".join(chosen), payload["order"]))
    return chosen
