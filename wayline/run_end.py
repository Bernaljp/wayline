"""The run-end gates (Implementation Decision 17; ticket 103).

The general report's claims are tested at every run end without the owner asking. The gates run in a fixed order:

1. the drawings (`wayline.drawings`, ticket 100), for every result changed since its last accepted drawing;
2. **sampled claim verdicts** on `research/REPORT.md` (`sampled_verdicts`): only the claims never sampled, cached by
   sentence hash in `research/.cache/sampled.json`, 10 percent of them and at least ten, plus every difficulty-5 claim
   (`provenance.sample_claims` over the new claims alone), so a pass over a report with no new claim samples nothing;
3. **the kill argument** on the general report (`kill_argument`), when the report changed since the last one: its
   verdict's subject names the report's text as it stood (`kill_subject`, a hash of the report without its records),
   so an unchanged report is not argued again.

Both verdict gates file **scope-downs**: `writing` tickets the verifier proposes, declaring Results, whose findings name
in `replaces` the finding they narrow (`check_scope_down`, run at the ticket's acceptance). A claim's scope-down names
the findings its sentence was rendered from; the kill argument's names every current finding it may narrow.

What follows depends on how the run ended (the conductor's `_gates_before_the_end`):

- at the stopping rule's own ends (`RULE_ENDS`: `objectives_closed`, `goal_reached`, `frontier_empty`) the gates run
  first, and their scope-downs continue the run until an end holds with no gate owed;
- after `budget_spent` or `stall_strict` (`ONCE_ENDS`) they run once, their scope-downs wait for the next run, and the
  failed claims are marked in the report's records (`failed_marks`);
- after `stopped` or `switched` none run.

The one end notice is sent after the gates. Everything here is code over the ledger except the sessions the gates take:
the classifier, for a sentence the claims cache does not hold, and the verifier's.
"""

import hashlib
from pathlib import Path

from wayline import HARNESS_ROOT, gates, provenance, sections, tickets
from wayline.ledger import RUN_ENDED, RUN_STARTED, TICKET_CREATED, VERDICT, Ledger, ledger_for
from wayline.project import policy_for
from wayline.stopping import BUDGET_SPENT, FRONTIER_EMPTY, GOAL_REACHED, OBJECTIVES_CLOSED

__all__ = [
    "RULE_ENDS", "ONCE_ENDS", "NO_GATE_ENDS", "STALL_STRICT", "SAMPLED_CACHE", "REPORT_SUBJECT", "KILL_ORIGIN",
    "runs_gates", "continues", "report_text", "report_digest", "kill_subject", "last_kill", "read_sampled",
    "candidate_sentences", "sampled_verdicts", "kill_owed", "kill_argument", "is_scope_down", "scope_downs", "targets",
    "check_scope_down", "pending", "owed", "failed_marks", "MAX_ROUNDS", "rounds", "is_gate_event",
]

STALL_STRICT = "stall_strict"
RULE_ENDS = (OBJECTIVES_CLOSED, GOAL_REACHED, FRONTIER_EMPTY)
ONCE_ENDS = (BUDGET_SPENT, STALL_STRICT)
NO_GATE_ENDS = ("stopped", "switched")

SAMPLED_CACHE = ".cache/sampled.json"  # under research/: every claim a pass considered, by sentence hash
REPORT_SUBJECT = "report"              # the verdict's `subject_kind` for the kill argument on the general report
KILL_ORIGIN = provenance.REPORT_PATH + "#kill-argument"  # the origin of the kill argument's scope-down: one open at a time
_KILL_PREFIX = provenance.REPORT_PATH + "#kill-"
_SCOPE_PREFIX = provenance.REPORT_PATH + "#"
_FINDINGS_INPUT = "research/" + provenance.FINDINGS + "#"

KILL_TITLE = "Scope down the general report's claims the kill argument left standing"
SCOPE_CHECK = "wayline: a scope-down's findings name in replaces the finding they narrow"
# The kill arguments one run takes at most: each scope-down that lands changes the report and owes another, so a memo that
# always finds a point would keep a run at its end forever. After the last, the scope-down waits for the next run.
MAX_ROUNDS = 3


def runs_gates(reason):
    """Whether the gates run at an end of this kind: every end but the owner's stop and a switch."""
    return reason in RULE_ENDS or reason in ONCE_ENDS


def continues(reason):
    """Whether the gates' scope-downs continue the run (the stopping rule's own ends) or wait for the next run."""
    return reason in RULE_ENDS


def rounds(events):
    """The kill arguments on the general report taken in the current run: since the last `run_ended`, or the last run
    the owner started afresh (a relaunch by the tick resumes the run, and counts on)."""
    count = 0
    for event in events:
        name, payload = event.get("event"), event.get("payload") or {}
        if name == RUN_ENDED or (name == RUN_STARTED and not payload.get("resume")):
            count = 0
        elif name == VERDICT and payload.get("subject_kind") == REPORT_SUBJECT and payload.get("verdict_type") == gates.KILL_ARGUMENT:
            count += 1
    return count


def is_gate_event(event):
    """Whether a journal event is a run-end gate's: a verdict on the general report's claims or its kill argument, or the
    `ticket_created` of a scope-down the verifier filed on it."""
    payload = event.get("payload") or {}
    if event.get("event") == VERDICT:
        return str(payload.get("subject") or "").startswith(_SCOPE_PREFIX)
    return (event.get("event") == TICKET_CREATED and payload.get("proposed_by") == gates.VERIFIER
            and str(payload.get("origin") or "").startswith(_SCOPE_PREFIX))


# --- the report ---------------------------------------------------------------------------------------------


def report_text(project):
    """`research/REPORT.md` with its tags restored, or None when it was never rendered."""
    try:
        text = (Path(project) / provenance.REPORT_PATH).read_text(encoding="utf-8")
    except OSError:
        return None
    return provenance.restore_tags(text)


def report_digest(text):
    """The hash of a report's text without its records: what code says of the render (the journal's size, the linter's
    count) changes at every render, while the report the kill argument reads is the rest."""
    kept, inside = [], False
    for line in str(text or "").splitlines():
        stripped = line.strip()
        if stripped == provenance.RECORDS_BEGIN:
            inside = True
        elif stripped == provenance.RECORDS_END:
            inside = False
        elif not inside:
            kept.append(line.rstrip())
    return hashlib.sha256("\n".join(kept).strip().encode("utf-8")).hexdigest()


def kill_subject(digest):
    """The kill argument's subject for one version of the general report."""
    return "%s%s" % (_KILL_PREFIX, digest[:16])


def last_kill(events):
    """The subject of the last kill argument on the general report, or None."""
    for event in reversed(events):
        payload = event.get("payload") or {}
        if event.get("event") == VERDICT and payload.get("subject_kind") == REPORT_SUBJECT \
                and payload.get("verdict_type") == gates.KILL_ARGUMENT:
            return payload.get("subject")
    return None


def candidate_sentences(text):
    """The report's sentences that end with a tag other than `doc`: a claim when the classifier says so."""
    return [sentence for sentence in provenance.prose_sentences(text)
            if any(kind != "doc" for kind in provenance.end_kinds(sentence.text))]


# --- the sample cache ---------------------------------------------------------------------------------------


def read_sampled(project_or_ledger):
    """`research/.cache/sampled.json` as `{sentence hash: {"drawn": [subjects]}}`, every claim a pass considered by its
    sentence hash with the subjects it drew under that hash (the same words twice, tagged apart, are two subjects); empty
    when absent or unreadable."""
    book = ledger_for(project_or_ledger)
    try:
        data = book.read_json(SAMPLED_CACHE)
    except (OSError, ValueError):
        return {}
    claims = data.get("claims") if isinstance(data, dict) else None
    return {digest: entry for digest, entry in (claims or {}).items() if isinstance(entry, dict)} if isinstance(claims, dict) else {}


def _drawn(entry):
    drawn = (entry or {}).get("drawn")
    return drawn if isinstance(drawn, list) else []


def _judged(events):
    """The subjects of every claim verdict the journal holds."""
    return {(event.get("payload") or {}).get("subject") for event in events
            if event.get("event") == VERDICT and (event.get("payload") or {}).get("subject_kind") == provenance.CLAIM}


def _difficulties(project):
    return {fields["id"]: fields.get("pinned_difficulty") or fields.get("difficulty") for fields in tickets.read_tickets(project)}


def sampled_verdicts(project, *, harness_root=HARNESS_ROOT, policy=None, classifier=None):
    """The second gate: verdicts on a sample of the general report's claims never sampled. Returns what happened.

    The report's tagged sentences the claims cache does not hold are classified first (`classifier(texts)`, else
    `provenance.classify`). The claims whose sentence hash the sample cache does not hold are new: `sample_claims` draws
    from them alone, and every new claim is written to the cache, drawn or not, before any verdict, so a pass that died
    half way takes the drawn claims still owed their verdict next time and draws nothing again. The verdicts are
    `provenance.verify_claims`'s, which skips a claim already judged and files a failing one's scope-down.
    """
    project = Path(project).resolve()
    book = Ledger(project)
    policy = policy_for(project, harness_root) if policy is None else policy
    outcome = {"new": 0, "sampled": 0, "passed": [], "failed": [], "tickets": [], "waiting": [], "fell_back": []}
    text = report_text(project)
    if text is None:
        return outcome
    classes = provenance.read_claims_cache(book)
    pending = [sentence.text for sentence in candidate_sentences(text) if provenance.sentence_hash(sentence.text) not in classes]
    if pending:
        classes = (classifier(pending) if classifier is not None
                   else provenance.classify(project, pending, harness_root=harness_root, policy=policy))
    claims = provenance.tagged_claims(text, classes)
    with book.lock():
        cache = read_sampled(book)
        new = [claim for claim in claims if claim.digest not in cache]
        drawn = provenance.sample_claims(new, policy, _difficulties(project)) if new else []
        for claim in new:
            entry = cache.setdefault(claim.digest, {"drawn": []})
            if claim in drawn:
                entry["drawn"].append(provenance.claim_subject(claim))
        if new:
            book.write_json(SAMPLED_CACHE, {"schema_version": 1, "claims": dict(sorted(cache.items()))})
    outcome["new"], outcome["sampled"] = len(new), len(drawn)
    events, _ = book.read_events()
    judged = _judged(events)
    owed = [claim for claim in claims if provenance.claim_subject(claim) in _drawn(cache.get(claim.digest))
            and provenance.claim_subject(claim) not in judged]
    if not owed:
        return outcome
    judged = provenance.verify_claims(project, harness_root=harness_root, policy=policy, chosen=owed)
    for key in ("passed", "failed", "tickets", "waiting", "fell_back"):
        outcome[key] = judged[key]
    return outcome


# --- the scope-downs ----------------------------------------------------------------------------------------


def failed_marks(events, by_id, body):
    """The lines the general report's records mark the failed claims with: each claim of `body` whose sampled verdict
    failed, with the scope-down that narrows it, and the kill argument's standing points while their scope-down is open.
    Empty when nothing is marked. A claim stays marked until a finding narrowing it replaces its sentence.
    """
    latest, kill = {}, None
    for event in events:
        payload = event.get("payload") or {}
        if event.get("event") != VERDICT:
            continue
        if payload.get("subject_kind") == provenance.CLAIM and str(payload.get("subject") or "").startswith(_SCOPE_PREFIX):
            latest[payload["subject"]] = bool(payload.get("pass"))
        elif payload.get("subject_kind") == REPORT_SUBJECT and payload.get("verdict_type") == gates.KILL_ARGUMENT:
            kill = payload
    open_by_origin = {fields.get("origin"): fields for _, fields in sorted((by_id or {}).items())
                      if is_scope_down(fields) and fields.get("status") not in tickets.SATISFIED + ("parked",)}
    lines = []
    for sentence in candidate_sentences(body):
        subject = provenance.claim_subject(provenance.Claim(sentence.text, sentence.tags, provenance.sentence_hash(sentence.text)))
        if latest.get(subject) is not False:
            continue
        ticket = open_by_origin.get(subject)
        lines.append("- %s (its sampled verdict failed; %s)" % (
            provenance.one_line(provenance.strip_tags(sentence.text)),
            "scope-down ticket %d narrows it" % ticket["id"] if ticket else "no scope-down is open for it"))
    ticket = open_by_origin.get(KILL_ORIGIN)
    if kill is not None and not kill.get("pass") and ticket is not None:
        lines.append("- the kill argument left %d point(s) standing; scope-down ticket %d narrows the findings they name"
                     % (len(kill.get("findings") or []), ticket["id"]))
    if not lines:
        return []
    return ["The run-end gates failed these claims; each stays marked until its scope-down narrows it:", ""] + lines


def is_scope_down(fields):
    """Whether a ticket is a scope-down a run-end gate filed on the general report: a `writing` ticket the verifier
    proposed, whose origin is one of the report's claims or its kill argument."""
    fields = fields or {}
    return (fields.get("kind") == "writing" and fields.get("proposed_by") == gates.VERIFIER
            and str(fields.get("origin") or "").startswith(_SCOPE_PREFIX))


def scope_downs(project):
    """Every scope-down the run-end gates filed, as ticket fields, in id order."""
    return [fields for fields in tickets.read_tickets(project) if is_scope_down(fields)]


def targets(fields):
    """The findings a claim's scope-down narrows, by id, from its inputs; empty for the kill argument's, which may
    narrow any current finding."""
    return [str(item)[len(_FINDINGS_INPUT):] for item in (fields or {}).get("inputs") or []
            if str(item).startswith(_FINDINGS_INPUT) and len(str(item)) > len(_FINDINGS_INPUT)]


def check_scope_down(fields, result):
    """The problems of a scope-down's result, each one line, empty when it passes: it returns findings, and each names
    in `replaces` a finding it narrows, one of its targets when it has them. A claim's scope-down that names no finding
    (a sentence the report rendered from none) returns what the artifacts support with nothing to replace. Whether a
    finding named is in Results now is the declared-sections check's (`sections.check_result`)."""
    result = result if isinstance(result, dict) else {}
    if result.get("status") == "running":
        return []
    findings = [item for item in result.get("findings") or [] if isinstance(item, dict)]
    wanted = targets(fields)
    if not wanted and (fields or {}).get("origin") != KILL_ORIGIN:
        return [] if findings else ["a scope-down returns, as findings with their provenance, what the artifacts support"]
    if not findings:
        return ["a scope-down returns the narrowed finding(s), each naming in `replaces` the finding it narrows%s"
                % (" (%s)" % ", ".join(wanted) if wanted else "")]
    problems = []
    for index, finding in enumerate(findings, start=1):
        replaces = finding.get("replaces")
        if not replaces:
            problems.append("finding %d names nothing in `replaces`: a scope-down narrows a finding, so it names the one "
                            "it narrows%s" % (index, " (%s)" % ", ".join(wanted) if wanted else ""))
        elif wanted and replaces not in wanted:
            problems.append("finding %d replaces %s, which this scope-down does not narrow; it narrows %s"
                            % (index, replaces, ", ".join(wanted)))
    return problems


# --- what is owed -------------------------------------------------------------------------------------------


def pending(project, events=None):
    """What of the two verdict gates the general report is owed now, as phrases; empty when nothing is. Code alone.

    A tagged sentence the classifier has not read may be a claim, so it counts until it is read: the gates read it
    first. A claim never sampled is owed a draw, a drawn one with no verdict yet its verdict, and a report holding a
    claim that changed since the last kill argument the kill argument.
    """
    text = report_text(project)
    if text is None:
        return []
    if events is None:
        events, _ = Ledger(project).read_events()
    classes, cache = provenance.read_claims_cache(project), read_sampled(project)
    verdicted = _judged(events)
    unread = new = owed = claims = 0
    for sentence in candidate_sentences(text):
        digest = provenance.sentence_hash(sentence.text)
        kind, entry = classes.get(digest), cache.get(digest)
        if kind is None:
            unread += 1
            continue
        if kind != provenance.CLAIM:
            continue
        claims += 1
        if entry is None:
            new += 1
        else:
            subject = provenance.claim_subject(provenance.Claim(sentence.text, sentence.tags, digest))
            if subject in _drawn(entry) and subject not in verdicted:
                owed += 1
    found = []
    if unread:
        found.append("%d tagged sentence(s) of REPORT.md not yet classified" % unread)
    if new:
        found.append("%d claim(s) never sampled" % new)
    if owed:
        found.append("%d sampled claim(s) owed their verdict" % owed)
    if (unread or claims) and last_kill(events) != kill_subject(report_digest(text)):
        found.append("the kill argument on a changed REPORT.md")
    return found


def owed(project, events=None):
    """What a run resting at its end still owes before it ends, as phrases, by code alone: the gates' scope-downs and the
    drawings open, running, or failed and waiting on a step, and the verdict gates `pending` finds. What the tick
    relaunches a run for that did not end."""
    from wayline import replay  # the journal's view, for a failed ticket's step
    if events is None:
        events, _ = Ledger(project).read_events()
    steps = {identifier: known.step for identifier, known in replay.replay(events).tickets.items()}

    def under_way(fields):
        return fields["status"] in ("open", "running") or (
            fields["status"] == "failed" and steps.get(fields["id"]) in ("resume", "split", "tier_up"))

    found = []
    every = tickets.read_tickets(project)
    downs = [fields for fields in every if is_scope_down(fields) and under_way(fields)]
    if downs:
        found.append("%d scope-down(s) of the run-end gates" % len(downs))
    drawn = [fields for fields in every if fields.get("kind") == "drawing" and under_way(fields)]
    if drawn:
        found.append("%d drawing(s)" % len(drawn))
    return found + pending(project, events)


# --- the kill argument --------------------------------------------------------------------------------------


def kill_owed(project, events=None):
    """The kill argument's subject when the general report is owed one, else None: it holds a claim (a tagged sentence
    the classifier called one) and it changed since the last kill argument."""
    text = report_text(project)
    if text is None or not provenance.tagged_claims(text, provenance.read_claims_cache(project)):
        return None
    subject = kill_subject(report_digest(text))
    if events is None:
        events, _ = Ledger(project).read_events()
    return None if last_kill(events) == subject else subject


def _kill_paths(project):
    found = [provenance.REPORT_PATH]
    for name in (provenance.FINDINGS, provenance.MANIFEST, "results.json", "objectives.json"):
        if (Path(project) / "research" / name).is_file():
            found.append("research/" + name)
    return found


def kill_argument(project, *, harness_root=HARNESS_ROOT, policy=None, fall_back=None, events=None):
    """The third gate: the two-thread kill argument on the general report, when it changed since the last one.

    Returns the adjudication's verdict, or None when none is owed. Both threads are the verifier for the report's
    writer, as for its prose claims; a fail files the one scope-down `_file_kill_scope_down` writes, unless one is open.
    """
    project = Path(project).resolve()
    subject = kill_owed(project, events)
    if subject is None:
        return None
    policy = policy_for(project, harness_root) if policy is None else policy
    author = provenance._role_tier(policy, provenance.WRITER)[0]
    return gates.kill_argument(_kill_paths(project), project=project, author_model=author, subject_kind=REPORT_SUBJECT,
                               subject=subject, harness_root=harness_root, policy=policy, fall_back=fall_back,
                               file=_file_kill_scope_down)


def _file_kill_scope_down(project, ledger, adjudication, paths, memo):
    """The scope-down of a failed kill argument on the general report: Results declared, every current finding listed
    as one it may narrow, each finding it returns naming the one it narrows in `replaces`. One is open at a time."""
    standing = gates.open_writing_ticket(project, KILL_ORIGIN)
    if standing is not None:
        return standing
    current = provenance.current_findings(project)
    lines = ["- `%s` %s" % (finding.get("id"), provenance.one_line(finding.get("text"))) for finding in current
             if not finding.get("negative")]
    body = "\n".join([
        "## What the kill argument left standing",
        "",
        "The rejection memo was written by verifier session `%s` (%s) and adjudicated by verifier session `%s` (%s), which "
        "read the general report and the ledger beneath it and found that these points still stand:"
        % (memo.session_id, memo.model, adjudication.session_id, adjudication.model),
        "",
        gates.findings_text(adjudication.findings),
        "",
        "The report renders the findings as their tickets recorded them. Return in the result each finding a point "
        "narrows, narrowed to what its artifacts support, with its provenance, naming the finding it narrows in its "
        "`replaces`; the ledger records it in that finding's place and the next render reads it. Do not answer a point by "
        "asserting it away.",
        "",
        provenance.PROVENANCE_FORM,
        "",
        "## The current findings it may narrow",
        "",
    ] + (lines or ["- none"]) + ["", "## The paths both threads read", ""] + ["- `%s`" % item for item in paths])
    return gates.file_writing_ticket(
        project, ledger, title=KILL_TITLE, touches=[], inputs=list(paths),
        quality=["Does every point the kill argument left standing now meet a finding narrowed to what its artifacts support?"],
        origin=KILL_ORIGIN, sections=[sections.RESULTS],
        demo="The general report renders the narrowed findings, and the kill argument at the next run end leaves no point standing.",
        body=body,
    )
