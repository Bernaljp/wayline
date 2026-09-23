"""Proposals admission (Implementation Decisions 5, 14; ticket 37; BRIEF 6.3, 9.5).

Workers, verifiers, and the critic may propose tickets in their structured result's or verdict's
`proposals[]`. Admission is code, not a person: a proposal is admitted when it is inside the
project's configured radius, not a duplicate of a ticket or of another proposal, under the
per-wave cap for its own radius, and every ticket it names in `blocked_by` exists. Admitted, it
becomes a ticket whose `proposed_by` and `origin` name where it came from, and `proposal_admitted`
is journaled. Otherwise it is parked under `research/proposals/` (`wayline.decisions.PROPOSALS`),
one JSON object per file, never deleted, with the reason in `radius`, `duplicate`, `cap`,
`blockers`, and `proposal_parked` is journaled; `decisions.parked_proposals` reads the park back
for the decider (ticket 31) and for the report's "not pursued" section
(`wayline.provenance._not_pursued`).

**The radius.** Each proposal declares the radius it belongs to (BRIEF 9.5): `strict` for a
ticket that traces to a spec claim, `moderate` for a follow-up that probes a claim's failure,
`exploratory` for a new direction. It is inside the project's radius (`harness.json`'s `radius`)
when its own radius is no wider: `strict` is inside every project radius, `moderate` is inside
`moderate` and `exploratory`, `exploratory` is inside `exploratory` alone. A proposal that does not
declare one of the three, or declares one wider than the project's, is parked `radius`. An
`exploratory` proposal's scout novelty check is the duplicate check below: a "new direction" that
is already close to a ticket or a parked proposal's title is not a new one.

**The duplicate check.** Mechanical first: same `kind` and a normalized-title similarity
(`wayline.scout.title_similarity`) above `policy.proposals.dedup.similarity` (0.8), or an
identical, non-empty `touches` and the same `origin`, is a duplicate outright. A similarity within
`policy.proposals.dedup.judged_between` (0.6 to 0.8, inclusive) goes to one session of the
`dedup-judge` role (haiku, low effort, no tools); its `duplicate`/`distinct` answer decides it.
Below the range, the proposal is not a duplicate of that candidate. The corpus is every ticket the
project holds, of any status, and every proposal still parked, so two proposals of the same thing
in the same wave park the second rather than admit both.

**The cap.** `policy.proposals.cap` gives a per-wave admission cap for each radius bucket
(`strict` 0, `moderate` 3, `exploratory` 6 by default): the count already admitted this wave at a
proposal's own radius must be under its bucket's cap. `wave_cap` is the caller's running count,
shared and mutated across every call in one wave (the conductor's); a fresh one is used when none
is given, which caps only within that one call.

**Reconsideration** (ticket 31; `wayline.decider.decide_proposal`) is the decider's opinion, not an
admission: it journals `proposal p: admit` or `proposal p: keep parked` and writes nothing else.
`apply_admitted` reads that opinion back and runs the cap and blockers rules again (not radius or
duplicate, which the decider's reading already weighed) to admit it when the cap allows, or leaves
it parked for a later wave's cap to try again.
"""

import hashlib
import json
import re
from pathlib import Path

from wayline import HARNESS_ROOT, decider, scout, worker
from wayline.decisions import PROPOSALS, parked_proposals
from wayline.ledger import DECISION, PROPOSAL_ADMITTED, PROPOSAL_PARKED, Ledger
from wayline.project import policy_for, read_harness
from wayline.tickets import build_graph, next_id, read_tickets, write_ticket

__all__ = [
    "RADIUS", "RADIUS_RANK", "REASONS", "KIND_ROLE", "DEDUP_ROLE", "DEDUP_SCHEMA",
    "ProposalsError", "parked_path", "admit_proposals", "apply_admitted",
]

RADIUS = ("strict", "moderate", "exploratory")
RADIUS_RANK = {name: index for index, name in enumerate(RADIUS)}
REASONS = ("radius", "duplicate", "cap", "blockers")

DEDUP_ROLE = "dedup-judge"
DEDUP_SCHEMA = "dedup_verdict"
DEDUP_MAX_TURNS = 3
DEDUP_MAX_MINUTES = 5

# A kind's default role, absent anything else to size an auto-admitted ticket by: the planner's own
# convention in the toy fixtures, for a ticket that was never planned by a person.
KIND_ROLE = {
    "dossier": "reader", "lit": "reader", "code": "coder", "docs": "documentarian", "experiment": "experimenter",
    "analysis": "analyst", "figure": "figure-designer", "writing": "writer", "review": "critic",
    "decision": "decider", "harness": "coder",
}


class ProposalsError(ValueError):
    """A proposal admission cannot act on: the dedup judge could not be asked, or answered nothing usable."""


def _proposals_dir(project):
    return Path(project).resolve() / "research" / PROPOSALS


def parked_path(project, identifier):
    """`research/proposals/<identifier>.json`."""
    return _proposals_dir(project) / ("%s.json" % identifier)


def _proposal_id(origin):
    """A short, stable, file-safe id for a proposal: the first twelve hex of its origin's hash.

    The origin already names the source and the proposal's position in it (`_origin`), so the same
    result carried again, or a resumed attempt asking again, computes the same id and finds the
    ticket already admitted or the file already parked, rather than admitting or parking it twice.
    """
    return hashlib.sha256(origin.encode("utf-8")).hexdigest()[:12]


def _origin(prefix, index):
    return "%s: proposal %d" % (prefix, index)


_SOURCE_SUFFIX = re.compile(r": proposal \d+\Z")


def _source_of(origin):
    """The source a ticket's or a parked proposal's `origin` names, with any `: proposal N` suffix `_origin` adds stripped.

    Two proposals of the same source with an identical touch set are a duplicate of each other
    even when their titles read nothing alike (the spec's "identical touch set and origin"); the
    full origin, unique per call, is never equal between two different calls, so the comparison is
    against the source it was cut from, not the whole string.
    """
    return _SOURCE_SUFFIX.sub("", origin or "")


def _title_similarity(a, b):
    return scout.title_similarity(a or "", b or "")


def _radius_reason(proposal, project_radius):
    radius = proposal.get("radius")
    if radius not in RADIUS_RANK or project_radius not in RADIUS_RANK:
        return "radius"
    if RADIUS_RANK[radius] > RADIUS_RANK[project_radius]:
        return "radius"
    return None


def _corpus(project):
    """Every ticket's, and every still-parked proposal's, `(title, kind, touches, source)`, to compare against."""
    corpus = [{"title": ticket.get("title"), "kind": ticket.get("kind"),
              "touches": ticket.get("touches") or [], "source": _source_of(ticket.get("origin"))}
             for ticket in read_tickets(project)]
    corpus.extend({"title": entry.get("title"), "kind": entry.get("kind"),
                   "touches": entry.get("touches") or [], "source": _source_of(entry.get("origin"))}
                  for entry in parked_proposals(project))
    return corpus


def _duplicate_candidate(proposal, corpus, threshold, low, high):
    """`("mechanical" | "judged", candidate)` for the closest match worth acting on, else `(None, None)`."""
    touches = sorted(item for item in (proposal.get("touches") or ()) if item)
    source = proposal.get("source")
    best = None
    for candidate in corpus:
        if touches and source and sorted(candidate["touches"]) == touches and candidate["source"] == source:
            return "mechanical", candidate
        if candidate["kind"] != proposal.get("kind"):
            continue
        similarity = _title_similarity(proposal.get("title"), candidate["title"])
        if best is None or similarity > best[1]:
            best = (candidate, similarity)
    if best is None:
        return None, None
    candidate, similarity = best
    if similarity > threshold:
        return "mechanical", candidate
    if low <= similarity <= high:
        return "judged", candidate
    return None, None


def _dedup_prompt(proposal, candidate, role):
    lines = [
        "- subject: whether two %s proposals are the same admission" % (proposal.get("kind") or "?"),
        "", "## Proposed", "", "Title: %s" % (proposal.get("title") or ""),
        "Why: %s" % (proposal.get("why") or "(no rationale carried)"), "",
        "## Already in the graph", "", "Title: %s" % (candidate.get("title") or ""), "",
        "Are these the same piece of work, close enough that admitting the proposed one would duplicate the other?",
    ]
    parts = ["\n".join(lines).rstrip(), (role.protocol or "").strip(),
            "# Your answer\n\nReturn `verdict` (`duplicate` or `distinct`) and `reason` (one paragraph) "
            "through the structured output."]
    return "\n\n".join(part for part in parts if part) + "\n"


def _session_dir(project, identifier):
    """`research/sessions/dedup-judge/<identifier>/<n>`, the first free number, mirroring the decider's own."""
    base = Path(project).resolve() / "research" / "sessions" / DEDUP_ROLE / identifier
    number = 1
    while (base / str(number)).exists():
        number += 1
    return base / str(number)


def _judge_duplicate(project, proposal, candidate, policy, harness_root):
    root = Path(harness_root or HARNESS_ROOT).resolve()
    role = worker.read_role(DEDUP_ROLE, root, project)
    entry = ((policy or {}).get("roles") or {}).get(DEDUP_ROLE) or {}
    model, effort = entry.get("model") or "haiku", entry.get("effort") or "low"
    run_dir = _session_dir(project, proposal["id"])
    request = worker.LaunchRequest(
        role=DEDUP_ROLE, model=model, effort=effort, prompt=_dedup_prompt(proposal, candidate, role),
        agent_json=role.agent_json(model, effort, DEDUP_MAX_TURNS), allowed_tools=[],
        disallowed_tools=list(role.disallowed_tools), settings_path=None, add_dirs=[], cwd=str(project),
        env={"WAYLINE_PROJECT": str(project), "WAYLINE_RUN": str(run_dir)},
        schema_path=str(root / "schemas" / (DEDUP_SCHEMA + ".json")), max_minutes=DEDUP_MAX_MINUTES,
    )
    envelope = worker.launch(request)
    if not envelope.valid or not envelope.structured_output:
        raise ProposalsError("the dedup judge on %r could not be taken: %s"
                             % (proposal.get("title"), "; ".join(envelope.errors) if envelope.errors else "no usable answer"))
    return envelope.structured_output.get("verdict") == "duplicate"


def _admitted_ticket(project, origin):
    for ticket in read_tickets(project):
        if ticket.get("origin") == origin:
            return ticket["id"]
    return None


def _admit(ledger, project, origin_ticket, proposal, notify=None):
    kind = proposal.get("kind")
    with ledger.lock():
        existing = {ticket["id"]: ticket for ticket in read_tickets(project)}
        found = _admitted_ticket(project, proposal["origin"])
        if found is not None:
            return {"id": proposal["id"], "outcome": "admitted", "ticket": found}
        identifier = next_id(project)
        fields = {
            "id": identifier, "title": (proposal.get("title") or "").strip() or ("proposal %s" % proposal["id"]),
            "kind": kind, "difficulty": 1, "status": "open",
            "blocked_by": sorted(set(proposal.get("blocked_by") or ())), "blocking": None, "human_only": False,
            "touches": sorted(item for item in (proposal.get("touches") or ()) if item),
            "role": KIND_ROLE.get(kind, "coder"), "skills": [], "acceptance": {},
            "origin": proposal["origin"], "proposed_by": proposal["proposed_by"],
            "demo": ((proposal.get("why") or "").strip() or None),
        }
        after = dict(existing)
        after[identifier] = fields
        build_graph(list(after.values()))  # a cycle raises before anything is written
        body = "## Proposed\n\n%s\n" % (proposal.get("why") or "(no rationale carried)")
        write_ticket(ledger, fields, body)
        parked = parked_path(project, proposal["id"])
        if parked.is_file():
            # Never deleted (the ticket's own rule): its status moves off `parked` so a later wave
            # does not keep listing it under "not pursued" or reconsidering it as still waiting.
            record = json.loads(parked.read_text(encoding="utf-8"))
            ledger.write_json("%s/%s.json" % (PROPOSALS, proposal["id"]), dict(record, status="admitted", ticket=identifier))
        ledger.append_event(PROPOSAL_ADMITTED, {"id": proposal["id"], "from": origin_ticket, "kind": kind, "ticket": identifier},
                            ticket=identifier)
    return {"id": proposal["id"], "outcome": "admitted", "ticket": identifier}


def _park(ledger, project, origin_ticket, proposal, reason):
    path = parked_path(project, proposal["id"])
    if path.is_file():
        return {"id": proposal["id"], "outcome": "parked", "reason": reason}
    record = dict(proposal, reason=reason, status="parked", **({"from": origin_ticket} if origin_ticket is not None else {}))
    ledger.write_json("%s/%s.json" % (PROPOSALS, proposal["id"]), record)
    ledger.append_event(PROPOSAL_PARKED, {"id": proposal["id"], "from": origin_ticket, "kind": proposal.get("kind"), "reason": reason},
                        ticket=origin_ticket if isinstance(origin_ticket, int) else None)
    return {"id": proposal["id"], "outcome": "parked", "reason": reason}


def admit_proposals(project, proposals, *, origin_ticket, origin_prefix, proposed_by, policy=None, harness=None,
                    harness_root=None, wave_cap=None, notify=None):
    """Admit or park each of one source's proposals, in order; returns one outcome dict per proposal.

    `origin_ticket` is the ticket the proposals trace to (an int), for `proposal_admitted`'s and
    `proposal_parked`'s `from` and the report's "not pursued" line. `origin_prefix` is a short,
    human-readable name for this source (`"ticket 3 attempt 1"`, `"ticket 5's verifier verdict"`),
    which the proposal's id and the admitted ticket's `origin` are built from: a second call with
    the same prefix and the same proposals (a result carried again after a crash) finds each one
    already admitted or already parked rather than acting on it twice. `proposed_by` is the
    schema's author for the ticket admission writes (`worker:<ticket>` or `verifier`).
    """
    project = Path(project).resolve()
    policy = policy_for(project, harness_root) if policy is None else policy
    harness = read_harness(project) if harness is None else harness
    cap = {} if wave_cap is None else wave_cap
    project_radius = harness.get("radius")
    settings = policy.get("proposals") or {}
    caps = settings.get("cap") or {}
    dedup = settings.get("dedup") or {}
    threshold = dedup.get("similarity", 0.8)
    low, high = (dedup.get("judged_between") or [0.6, 0.8])[:2]
    ledger = Ledger(project)
    outcomes = []
    for index, proposal in enumerate(proposals or (), start=1):
        origin = _origin(origin_prefix, index)
        identifier = _proposal_id(origin)
        entry = dict(proposal, id=identifier, origin=origin, source=origin_prefix, proposed_by=proposed_by)
        found = _admitted_ticket(project, origin)
        if found is not None:
            outcomes.append({"id": identifier, "outcome": "admitted", "ticket": found})
            continue
        if parked_path(project, identifier).is_file():
            outcomes.append({"id": identifier, "outcome": "parked",
                             "reason": json.loads(parked_path(project, identifier).read_text(encoding="utf-8")).get("reason")})
            continue
        reason = _radius_reason(entry, project_radius)
        if reason is None:
            kind, candidate = _duplicate_candidate(entry, _corpus(project), threshold, low, high)
            if kind == "mechanical":
                reason = "duplicate"
            elif kind == "judged":
                if _judge_duplicate(project, entry, candidate, policy, harness_root):
                    reason = "duplicate"
        if reason is None:
            radius = entry.get("radius")
            if cap.get(radius, 0) >= caps.get(radius, 0):
                reason = "cap"
        if reason is None:
            missing = sorted(set(entry.get("blocked_by") or ()) - {ticket["id"] for ticket in read_tickets(project)})
            if missing:
                reason = "blockers"
        if reason is None:
            cap[entry["radius"]] = cap.get(entry["radius"], 0) + 1
            outcomes.append(_admit(ledger, project, origin_ticket, entry, notify=notify))
        else:
            outcomes.append(_park(ledger, project, origin_ticket, entry, reason))
    return outcomes


def _decided_answers(events):
    """`{proposal id: "admit" | "keep parked" | ...}` off the journal's `decision` events (`decider.reconsidered`'s vocabulary)."""
    prefix = decider.PROPOSAL_ANSWER.split("%s")[0]
    answers = {}
    for event in events:
        payload = event.get("payload") or {}
        text = payload.get("answer") or ""
        if event.get("event") == DECISION and payload.get("decided_by") == decider.DECIDER and payload.get("ticket") is None \
                and text.startswith(prefix):
            identifier, _, answer = text[len(prefix):].partition(":")
            answers[identifier.strip()] = answer.strip()
    return answers


def apply_admitted(project, *, policy=None, harness_root=None, wave_cap=None, notify=None):
    """Admit every parked proposal the decider answered `admit`, within the cap; returns the outcomes.

    `wayline.decider.decide_proposal` only journals the decider's opinion; this reads it back and
    runs the cap and blockers rules again (not radius or duplicate, which the decider's reading
    already weighed) so a proposal it recommended is actually admitted once the cap allows, and
    left parked, to be tried again, when it does not.
    """
    project = Path(project).resolve()
    policy = policy_for(project, harness_root) if policy is None else policy
    caps = (policy.get("proposals") or {}).get("cap") or {}
    cap = {} if wave_cap is None else wave_cap
    ledger = Ledger(project)
    events, _ = ledger.read_events()
    decided = _decided_answers(events)
    outcomes = []
    for proposal in parked_proposals(project):
        if decided.get(str(proposal["id"])) != decider.ADMIT:
            continue
        radius = proposal.get("radius")
        if cap.get(radius, 0) >= caps.get(radius, 0):
            outcomes.append({"id": proposal["id"], "outcome": "parked", "reason": "cap"})
            continue
        missing = sorted(set(proposal.get("blocked_by") or ()) - {ticket["id"] for ticket in read_tickets(project)})
        if missing:
            outcomes.append({"id": proposal["id"], "outcome": "parked", "reason": "blockers"})
            continue
        cap[radius] = cap.get(radius, 0) + 1
        origin_ticket = proposal.get("from") if isinstance(proposal.get("from"), int) else None
        outcomes.append(_admit(ledger, project, origin_ticket, proposal, notify=notify))
    return outcomes
