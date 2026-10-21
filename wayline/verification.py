"""Verifying inherited results (Implementation Decision 17; ticket 97).

A project that starts midway inherits results: its earlier manuscript's Results, deconstructed by ticket 93 into
inherited claims that stand unchecked. Every **inherited result** (one inherited Results heading, all its claims
judged together, a large one split by the planner) is verified before anything is built on it: re-run, then its
wording judged, so an overstated claim is narrowed to what the evidence shows. A gap that needs new experiments is a
proposed `add`, not the verification's to close.

**The record.** `research/verifications.json` (schema `verification`), written only by this module through the
ledger, rendered as `research/VERIFICATIONS.md`, and journaled as `verification` whenever a result is found or its
standing changes. A result stands `unchecked` until every claim has a verdict (`verified`) or it is found
`unverifiable`, a standing with its reason, kept apart from unchecked.

**The objective.** At every start midway (`midway`) the critic proposes the objective "Do the inherited results
hold?" (`OBJECTIVE`), open by default and human-only: the grill's first tier asks the owner, who may park it.
Specify drafts one claim per inherited result under it (`claim_failures`), and code answers it once every inherited
result has a verdict or is unverifiable (`follow`).

**The routes.** Each verdict names its route (`ROUTES`): `reproduced` (the project's own code at the commit intake
recorded, changed only to run here), `ported` (the same logic in another language or runtime), `reimplemented`
(written from the inherited Methods), or `read` (a cited claim checked against its reference by the consultant,
batched per reference, from the L0 abstract first; `read`). A claim the abstract cannot settle stays unchecked
until its dossier is promoted under the budget, and is read again then. A verdict reached on substitute data covers
only the claim narrowed to that data (`check_result`). Contradictions attached to a result (ticket 95,
`attach_contradiction`) go into its verification: the worker's pack and the verifier's question. So do what the setup
found (ticket 108, `attach_inventory`): each disagreement between the inherited Methods and the code, from the parser
inventory, and each lead the Sonnet reading of the inherited code raised, in the pack and `VERIFICATIONS.md`.

**The ties.** A verification ticket (`verifies`: the result's heading) blocks every ticket built on its result: the
planner's code wires the edge from the objectives' and concerns' ties (`wire`), and an unverifiable result
releases what it blocked (`release`).

**The missing material.** The critic's memo carries a table (`material` rows): per inherited result, the code, data,
and software it needs, each present, missing, or fetchable (fetchable data is never missing). The grill asks about
every missing item in one setup question (`material_question`), each with the replies "I'll provide it", "rebuild
it" (recommended wherever a rebuild can work), or "leave it unverified"; licensed software gets provide, port to
Octave, or port to Python. After setup, a pending or newly found gap is a decision ticket of class `material`
(`settle`) offering provide, rebuild, or leave unverified, pausing only that verification: the owner's under
`interactive` and `checkpoints`, the decider's under `autonomous` (rebuild or leave unverified, never provide), and a
verification that ends `needs_human` under `autonomous` makes its result unverifiable.

**The verdict.** The fresh verifier at acceptance checks each verdict on an inherited claim explicitly
(`verdict_items`, which `gates.ticket_asks` lists in its question and `gates` holds the verdict to).
"""

import re

from wayline.jsonschema import load_schema, validate
from wayline.ledger import K_BY, K_HEADING, K_RELEASED, K_ROUTE, K_STANDING, VERIFICATION, ledger_for

__all__ = [
    "OBJECTIVE", "ROUTES", "VERIFICATIONS_JSON", "VERIFICATIONS_MD", "SCHEMA", "VerificationError", "VerificationUnreadable",
    "midway", "inherited_results", "read_record", "read_results", "current_record", "claim_rows", "follow", "render", "prompt_line",
    "material_failures", "memo_lines", "take_memo", "REPLIES", "LICENSED_REPLIES", "AS_RECOMMENDED", "recommended",
    "parse_replies", "material_question", "check_replies", "take_replies", "leave_unverifiable", "spec_inherited",
    "claim_failures", "spec_lines", "ties", "wire", "intake_commit", "check_result", "take_result", "attach_contradiction",
    "verdict_items", "verdict_text", "pack_text", "reading", "read", "CLASS", "material_of", "gap_of", "decider_refusal",
    "open_gap", "release", "settle", "attach_inventory",
]

OBJECTIVE = "Do the inherited results hold?"
ROUTES = ("reproduced", "ported", "reimplemented", "read")
REPRODUCED, PORTED, REIMPLEMENTED, READ = ROUTES
UNCHECKED, VERIFIED, UNVERIFIABLE = "unchecked", "verified", "unverifiable"
VERIFICATIONS_JSON = "verifications.json"
VERIFICATIONS_MD = "VERIFICATIONS.md"
SCHEMA = "verification"


class VerificationError(ValueError):
    """A change to the verifications this module refuses: an unknown result or item, a reply outside the set."""


class VerificationUnreadable(ValueError):
    """`research/verifications.json` is there and is not the record code writes."""


def _one_line(text):
    return " ".join(str(text or "").split())


# --- the inherited results -------------------------------------------------------------------------------


def _inherited_claims(book):
    """Every inherited Results claim ever written, current or not, in arrival order."""
    from wayline import sections  # the sections module reads the documents

    return [item for item in sections.read_passages(book)
            if item.get("section") == sections.RESULTS and sections.is_inherited(item) and item.get("standing") in sections.STANDINGS]


def midway(project_or_ledger):
    """Whether the project started midway: it inherited at least one Results claim from its own documents."""
    return bool(_inherited_claims(ledger_for(project_or_ledger)))


def inherited_results(project_or_ledger):
    """The inherited results that stand now: `[{heading, claims}]`, one per Results heading holding a current inherited
    claim, unchecked or unverifiable, in the order the section holds them."""
    from wayline import sections

    book = ledger_for(project_or_ledger)
    current = sections.current_ids(book, sections.RESULTS)
    found = {}
    for item in _inherited_claims(book):
        if item["id"] in current and not item.get("withdrawn"):
            found.setdefault(item["heading"], []).append(item["id"])
    return [{"heading": heading, "claims": claims} for heading, claims in found.items()]


# --- the record ------------------------------------------------------------------------------------------


def _empty():
    return {"results": [], "material": [], "reads": []}


def read_record(project_or_ledger):
    """The whole record, `{results, material, reads}`; empty when the project has none yet. Raises `VerificationUnreadable`."""
    ledger = ledger_for(project_or_ledger)
    if not ledger.path(VERIFICATIONS_JSON).is_file():
        return _empty()
    try:
        record = ledger.read_json(VERIFICATIONS_JSON)
    except (OSError, ValueError) as failure:
        raise VerificationUnreadable("research/%s cannot be read: %s" % (VERIFICATIONS_JSON, failure)) from None
    problems = validate(record, load_schema(SCHEMA))
    if problems:
        raise VerificationUnreadable("research/%s cannot be read: %s" % (
            VERIFICATIONS_JSON, "; ".join("%s: %s" % (error.path, error.message) for error in problems[:3])))
    return record


def read_results(project_or_ledger):
    """The inherited results the record holds, in the order they were found."""
    return list(read_record(project_or_ledger)["results"])


def _find(record, heading):
    found = next((item for item in record["results"] if item["heading"] == heading), None)
    if found is None:
        raise VerificationError("no inherited result is headed %r; research/VERIFICATIONS.md lists them" % heading)
    return found


def _save(ledger, record, changed, by, route=None, released=None):
    """Write the record, journal one `verification` per changed result, and render VERIFICATIONS.md; the caller holds the lock."""
    ledger.write_json(VERIFICATIONS_JSON, record, schema=SCHEMA)
    for result in changed:
        payload = {K_HEADING: result["heading"], K_STANDING: result["standing"], K_ROUTE: route, K_BY: by}
        if released:
            payload[K_RELEASED] = sorted(released)
        ledger.append_event(VERIFICATION, payload)
    ledger.write_markdown(VERIFICATIONS_MD, render(record))


# --- following the passages ------------------------------------------------------------------------------


SETTLED, WITHDRAWN = "settled", "withdrawn"


class _View:
    """The passages and findings read once: each id's record, what replaced it, and where a move took it."""

    def __init__(self, ledger):
        from wayline import sections

        passages = sections.read_passages(ledger)
        self.by_id = {item["id"]: item for item in passages}
        self.replaced, self.moved = {}, {}
        for item in list(passages) + list(sections.read_findings(ledger)):
            if item.get("replaces"):
                self.replaced.setdefault(item["replaces"], []).append(item)
            if item.get("moved_from"):
                self.moved[item["moved_from"]] = item

    def follow(self, claim):
        """`(ids, current, state)`: every id the claim held through its document's rewrites and moves, the one that holds it
        now, and its state: `settled` once the work replaced it, `withdrawn` once its document withdrew it, `unverifiable`
        while it stands so, `unchecked` otherwise."""
        from wayline import sections

        ids, current = [], claim
        while current not in ids:
            ids.append(current)
            if current in self.moved:
                current = self.moved[current]["id"]
                continue
            later = self.replaced.get(current) or []
            if any(not sections.is_inherited(item) for item in later):
                return ids, current, SETTLED  # a ticket's finding, a read's, or a passage replaced it: a verdict
            if any(item.get("withdrawn") for item in later):
                return ids, current, WITHDRAWN  # a newer version of its document no longer makes it
            if not later:
                break
            current = later[-1]["id"]  # its document said it again, newer or marked unverifiable
        standing = (self.by_id.get(current) or {}).get("standing")
        return ids, current, UNVERIFIABLE if standing == sections.UNVERIFIABLE else UNCHECKED


def _claim_states(ledger, claims, view=None):
    """`{claim: (current id, state)}` for each claim followed through its document's rewrites and moves (`_View.follow`)."""
    view = view or _View(ledger)
    return {claim: view.follow(claim)[1:] for claim in claims}


def _standing(ledger, result, view=None):
    """`(standing, reason)` of one result from where its claims stand now; `(None, None)` when its document withdrew them all.

    Unchecked while any claim is; once every claim has a verdict or stands unverifiable, unverifiable when any does (with
    the reasons), else verified.
    """
    view = view or _View(ledger)
    states = [state for state in _claim_states(ledger, result["claims"], view).values() if state[1] != WITHDRAWN]
    if not states:
        return None, None
    if any(state == UNCHECKED for _, state in states):
        return UNCHECKED, None
    if any(state == UNVERIFIABLE for _, state in states):
        reasons = list(dict.fromkeys(_one_line(view.by_id[current].get("reason")) for current, state in states
                                     if state == UNVERIFIABLE and current in view.by_id))
        return UNVERIFIABLE, result.get("reason") or "; ".join(reason for reason in reasons if reason) or "no reason given"
    return VERIFIED, None


def _refresh(ledger, record, view=None):
    """Take in the results the passages hold now and each one's standing; returns the results changed.

    A result whose document withdrew every claim (a newer version without it) is no longer an inherited result, and leaves
    the record. `view` is the passages as the caller read them, read here when None.
    """
    view = view or _View(ledger)
    changed = []
    known = {}
    for result in record["results"]:
        for current, _ in _claim_states(ledger, result["claims"], view).values():
            known[current] = result["heading"]
    for found in inherited_results(ledger):
        new = [claim for claim in found["claims"] if claim not in known]
        if not new:
            continue
        try:
            result = _find(record, found["heading"])
        except VerificationError:
            result = {"heading": found["heading"], "claims": [], "standing": UNCHECKED, "reason": None, "verdicts": [],
                      "contradictions": []}
            record["results"].append(result)
        result["claims"] = result["claims"] + new
        changed.append(result)
    for result in list(record["results"]):
        standing, reason = _standing(ledger, result, view)
        if standing is None:
            record["results"].remove(result)
            continue
        if (standing, reason) != (result["standing"], result["reason"]):
            result.update(standing=standing, reason=reason)
            if result not in changed:
                changed.append(result)
    return changed


def current_record(project_or_ledger):
    """The record as it stands with the passages taken in, read only: what `follow` would write, nothing written."""
    ledger = ledger_for(project_or_ledger)
    record = read_record(ledger)
    _refresh(ledger, record)
    return record


def claim_rows(project_or_ledger):
    """Each inherited Results claim of each inherited result, followed to where it stands now, read only: `[{claim,
    current, heading, standing, reason, verdict, route, ticket, by}]` in the record's order (ticket 111).

    `current` is the passage holding the claim now. `standing` is `verified` once this project's evidence replaced it,
    with `verdict` the evidence (supports, narrows, or contradicts), `by` the finding that replaced it, and the route and
    ticket of the verification that recorded it, when one did; else the standing of its passage, unchecked or
    unverifiable with its `reason`. A claim its document withdrew is left out.
    """
    from wayline import sections

    ledger = ledger_for(project_or_ledger)
    record = read_record(ledger)
    view = _View(ledger)
    _refresh(ledger, record, view)
    rows = []
    for result in record["results"]:
        recorded = {entry["claim"]: verdict for verdict in result["verdicts"] for entry in verdict["claims"]}
        for claim in result["claims"]:
            ids, current, state = view.follow(claim)
            if state == WITHDRAWN:
                continue
            row = {"claim": claim, "current": current, "heading": result["heading"], "standing": state, "reason": None,
                   "verdict": None, "route": None, "ticket": None, "by": None}
            if state == SETTLED:
                replacing = next((item for item in view.replaced.get(current) or [] if not sections.is_inherited(item)), {})
                verdict = next((recorded[identifier] for identifier in ids if identifier in recorded), None) or {}
                row.update(standing=VERIFIED, verdict=replacing.get("evidence"), by=replacing.get("id"), route=verdict.get("route"),
                           ticket=verdict.get("ticket"))
            elif state == UNVERIFIABLE:
                row["reason"] = _one_line((view.by_id.get(current) or {}).get("reason")) or result.get("reason")
            rows.append(row)
    return rows


def follow(project):
    """Code's part, after any change to the passages: the results changed, journaled `by: code`.

    New inherited results are recorded unchecked; a result whose claims all have a verdict is verified, and one whose
    claims stand unverifiable once the rest have one is unverifiable, with their reasons; one its document withdrew leaves.
    The objective "Do the inherited results hold?", while open, is answered by code once every inherited result has a
    verdict or is unverifiable.
    """
    ledger = ledger_for(project)
    with ledger.lock():
        record = read_record(ledger)
        before = len(record["results"])
        changed = _refresh(ledger, record)
        if changed or len(record["results"]) != before:
            _save(ledger, record, changed, "code")
        _answer_objective(ledger.project, record)
    return changed


def _answer_objective(project, record):
    """Answer the objective by code once every result is verified or unverifiable; returns the objective answered, or None."""
    from wayline.objectives import change_objective

    objective = _objective(project)
    if objective is None or objective["status"] != "open" or not record["results"]:
        return None
    if any(result["standing"] == UNCHECKED for result in record["results"]):
        return None
    said = "; ".join("%s: %s%s" % (result["heading"], result["standing"], " (%s)" % result["reason"] if result["reason"] else "")
                     for result in record["results"])
    return change_objective(project, objective["id"], "answered", "code", answer="every inherited result has a verdict or is "
                                                                                  "unverifiable: %s" % said)


# --- the critic's table --------------------------------------------------------------------------------------


KINDS = ("code", "data", "software")
PRESENT, MISSING, FETCHABLE = "present", "missing", "fetchable"


def prompt_line(results):
    """The critic's prompt line on the inherited results: one `material` row each, or none at a project that inherited none."""
    headings = [result["heading"] for result in results or ()]
    if not headings:
        return "- the inherited results: the project inherited none, so `material` is empty"
    return ("- the inherited results: this project starts midway, so the harness proposes the objective \"%s\", and the memo holds "
            "one row in `material` for each of %s: the code, the data, and the software each needs to be verified (re-run, then its "
            "wording judged), each `present`, `missing`, or `fetchable` (data a public source serves is fetchable, never missing), "
            "whether it is licensed software, and whether a rebuild (a port, a reimplementation from the inherited Methods, open "
            "software in its place) can work when it is missing; the owner answers for every missing item at the grill"
            % (OBJECTIVE, ", ".join(headings)))


def material_failures(rows, results):
    """Why the memo's `material` rows are not one per inherited result, each naming one, and none else."""
    headings = [result["heading"] for result in results or ()]
    failures, seen = [], {}
    for row in rows or ():
        if row["result"] not in headings:
            failures.append("a row of material names %s, which is no inherited result" % row["result"])
        seen[row["result"]] = seen.get(row["result"], 0) + 1
    for heading in headings:
        if not seen.get(heading):
            failures.append("the inherited result %s has no row in material" % heading)
        elif seen[heading] > 1:
            failures.append("the inherited result %s has more than one row in material" % heading)
    return failures


def memo_lines(rows):
    """`POSITION.md`'s table of what each inherited result needs, with the objective the critic proposes; none without rows."""
    if not rows:
        return []
    lines = ["", "## What each inherited result needs", "",
             "At this start midway the critic proposes the objective \"%s\", open: the grill's first tier asks the owner. A "
             "missing item is asked about once at setup; fetchable data is never missing." % OBJECTIVE, "",
             "| Result | Kind | Item | State | Licensed | A rebuild can work |", "|---|---|---|---|---|---|"]
    for row in rows:
        for need in row["needs"]:
            lines.append("| %s | %s | %s | %s | %s | %s |" % (row["result"], need["kind"], _one_line(need["item"]).replace("|", "\\|"),
                                                           need["state"], "yes" if need["licensed"] else "no",
                                                           "yes" if need["rebuild"] else "no"))
    return lines


def _number(identifier, letter="M"):
    found = re.match(r"^%s([1-9][0-9]*)\Z" % letter, str(identifier))
    return int(found.group(1)) if found else 0


def _add_item(record, heading, kind, item, licensed, rebuild, found_by):
    """The missing item, added with the next M id unless one for the same result, kind, and item is held; returns it."""
    key = (heading, kind, _one_line(item).casefold())
    held = next((entry for entry in record["material"] if (entry["heading"], entry["kind"], entry["item"].casefold()) == key), None)
    if held is not None:
        return held, False
    entry = {"id": "M%d" % (max((_number(entry["id"]) for entry in record["material"]), default=0) + 1), "heading": heading,
             "kind": kind, "item": _one_line(item), "licensed": bool(licensed), "rebuild": bool(rebuild), "reply": None, "by": None,
             "found_by": found_by}
    record["material"].append(entry)
    return entry, True


def take_memo(project, memo):
    """The memo's missing items, recorded (`found_by: critic`) once each; present and fetchable ones are not. Returns those added."""
    rows = (memo or {}).get("material") or []
    ledger = ledger_for(project)
    with ledger.lock():
        record = read_record(ledger)
        changed = _refresh(ledger, record)
        added = []
        for row in rows:
            for need in row["needs"]:
                if need["state"] != MISSING:
                    continue
                entry, new = _add_item(record, row["result"], need["kind"], need["item"], need["licensed"], need["rebuild"], "critic")
                if new:
                    added.append(entry)
        if added or changed:
            _save(ledger, record, changed, "code")
    return added


# --- the replies: the setup's one question, and after it a decision per gap ----------------------------------


PROVIDE, REBUILD, LEAVE, OCTAVE, PYTHON = "I'll provide it", "rebuild it", "leave it unverified", "port to Octave", "port to Python"
REPLIES = (PROVIDE, REBUILD, LEAVE)
LICENSED_REPLIES = (PROVIDE, OCTAVE, PYTHON)
AS_RECOMMENDED = "as recommended"
_ITEM_REPLY = re.compile(r"\b(M[1-9][0-9]*)\s*[:=-]\s*([^;,\n]+)")


def replies_for(item):
    """The replies an item takes: provide, rebuild, or leave it unverified; licensed software provide or a port."""
    return LICENSED_REPLIES if item["licensed"] else REPLIES


def reply_for(item, reply):
    """`reply` as `item` takes it, or None when it takes none such: a licensed item's `rebuild it` is its recommended port
    (Octave), a port named for an item that is not licensed is a rebuild, and `leave it unverified` is every item's."""
    if reply is None:
        return None
    if item["licensed"] and reply == REBUILD:
        return OCTAVE
    if not item["licensed"] and reply in (OCTAVE, PYTHON):
        return REBUILD
    return reply if reply in replies_for(item) or reply == LEAVE else None


def recommended(item):
    """An item's recommended reply: a rebuild (a port, for licensed software) wherever a rebuild can work."""
    if item["licensed"]:
        return OCTAVE if item["rebuild"] else PROVIDE
    return REBUILD if item["rebuild"] else LEAVE


def _reply(text):
    """The reply `text` names, read off its words, or None."""
    words = _one_line(text).casefold().rstrip(".")
    for reply in (PROVIDE, REBUILD, LEAVE, OCTAVE, PYTHON):
        if words == reply.casefold() or words.startswith(reply.casefold()):
            return reply
    if words.startswith(("provide", "i will provide", "i'll provide")):
        return PROVIDE
    if words.startswith(("leave", "leave unverified")):
        return LEAVE
    if words.startswith("rebuild"):
        return REBUILD
    if "octave" in words:
        return OCTAVE
    if "python" in words:
        return PYTHON
    return None


def parse_replies(text, items):
    """`{item id: reply}` for every one of `items` from one answer, or raises `VerificationError` with why.

    `as recommended` takes each item's recommendation; one reply alone is every item's; `M1: <reply>; M2: <reply>` names
    items, and an item it does not name takes its recommendation. Each reply is read as the item takes it (`reply_for`).
    """
    items = list(items)
    by_id = {item["id"]: item for item in items}
    words = _one_line(text)
    if not words:
        raise VerificationError("the answer names no reply")
    if words.casefold().rstrip(".") == AS_RECOMMENDED:
        return {item["id"]: recommended(item) for item in items}
    named = _ITEM_REPLY.findall(words)
    if named:
        replies = {item["id"]: recommended(item) for item in items}
        for identifier, said in named:
            if identifier not in by_id:
                raise VerificationError("%s is no missing item this question asks about" % identifier)
            item = by_id[identifier]
            reply = reply_for(item, _reply(said))
            if reply is None:
                raise VerificationError("%s takes %s; got %r" % (identifier, _choices(item), _one_line(said)))
            replies[identifier] = reply
        return replies
    reply = _reply(words)
    if reply is None:
        raise VerificationError("answer %s, one reply for every item, or name each item (M1: <reply>; M2: <reply>); got %r"
                                % (AS_RECOMMENDED, words))
    return {item["id"]: reply_for(item, reply) for item in items}


def _choices(item):
    replies = replies_for(item)
    if item["licensed"]:
        return "licensed software: %s, or %s (port to Octave or port to Python is its rebuild)" % (", ".join(replies[:-1]), replies[-1])
    return "%s, or %s" % (", ".join(replies[:-1]), replies[-1])


def _item_line(item):
    return "%s (%s, %s%s): %s" % (item["id"], item["heading"], item["kind"], ", licensed" if item["licensed"] else "", item["item"])


def _evidence_line(item):
    if item["licensed"]:
        return "%s: licensed software, so %s, %s, or %s; recommended %s" % (item["id"], PROVIDE, OCTAVE, PYTHON, recommended(item))
    return "%s: recommended %s%s" % (item["id"], recommended(item),
                                     " (a rebuild can work)" if item["rebuild"] else " (no rebuild can work)")


def waiting_items(project_or_ledger):
    """The missing items no reply has settled yet, in id order."""
    return [item for item in read_record(project_or_ledger)["material"] if item["reply"] is None]


def _objective(project):
    from wayline.objectives import read_objectives

    return next((item for item in read_objectives(project) if _one_line(item["text"]).casefold() == OBJECTIVE.casefold()), None)


def material_question(project, only=None):
    """The setup's one question on the missing material, as `{question, material, options, recommended, evidence}`, or None.

    Asked while the objective "Do the inherited results hold?" is open and an item waits for its reply: every missing item
    in one question, each with its replies and its recommendation.
    """
    objective = _objective(project)
    if objective is None or objective["status"] != "open":
        return None
    items = [item for item in waiting_items(project) if only is None or item["id"] in only]
    if not items:
        return None
    options = [AS_RECOMMENDED] + list(REPLIES) + ([OCTAVE, PYTHON] if any(item["licensed"] for item in items) else [])
    question = ("To verify the inherited results, what about the material they need and the project lacks? Answer %s, one reply "
                "for every item, or each item by its id (M1: <reply>; M2: <reply>):\n%s"
                % (AS_RECOMMENDED, "\n".join("- " + _item_line(item) for item in items)))
    return {"question": question, "material": {"ids": [item["id"] for item in items]}, "options": options,
            "recommended": AS_RECOMMENDED, "evidence": [_evidence_line(item) for item in items]}


def check_replies(project, ids, text):
    """Why an answer to the question on `ids` cannot be recorded, or None, with nothing written."""
    try:
        record = read_record(project)
        items = [entry for entry in record["material"] if entry["id"] in ids]
        parse_replies(text, items)
    except (VerificationError, VerificationUnreadable) as failure:
        return str(failure)
    return None


def take_replies(project, ids, text, by):
    """Record one answer's replies on the items `ids`, `by` the owner or the decider; returns the items changed.

    A `leave it unverified` makes its result unverifiable, with the item as the reason, and releases what it blocked.
    """
    ledger = ledger_for(project)
    with ledger.lock():
        record = read_record(ledger)
        items = [entry for entry in record["material"] if entry["id"] in ids]
        replies = parse_replies(text, items)
        changed = []
        for item in items:
            if item["reply"] != replies[item["id"]]:
                item.update(reply=replies[item["id"]], by=by)
                changed.append(item)
        if changed:
            _save(ledger, record, [], by)
        for heading in dict.fromkeys(item["heading"] for item in changed if item["reply"] == LEAVE):
            reasons = ["%s is missing and the %s left it unverified" % (item["item"], by) for item in items
                       if item["heading"] == heading and item["reply"] == LEAVE]
            leave_unverifiable(ledger.project, heading, "; ".join(reasons), by)
    return changed


def leave_unverifiable(project, heading, reason, by):
    """Make one inherited result unverifiable, with `reason`: each of its claims still unchecked is marked so, the record
    says why, and the tickets its verification blocked are released. Returns the result."""
    from wayline import inherited

    ledger = ledger_for(project)
    with ledger.lock():
        record = read_record(ledger)
        _refresh(ledger, record)
        result = _find(record, heading)
        for _, (current, state) in _claim_states(ledger, result["claims"]).items():
            if state == UNCHECKED:
                inherited.mark_unverifiable(ledger.project, current, reason)
        result["reason"] = _one_line(reason)
        before = result["standing"]
        _refresh(ledger, record)
        released = release(ledger.project, heading, by)
        _save(ledger, record, [result] if result["standing"] != before or released else [], by, released=released)
    return result


# --- specify: one claim per inherited result -----------------------------------------------------------------


def spec_inherited(project):
    """What specify holds the claims to: `{objective, headings}` while the objective is open and results wait for a verdict,
    else None. Code takes in the passages first, so a result found since the memo is asked for too."""
    try:
        objective = _objective(project)
    except ValueError:
        return None
    if objective is None or objective["status"] != "open":
        return None
    headings = [result["heading"] for result in current_record(project)["results"] if result["standing"] == UNCHECKED]
    return {"objective": objective["id"], "headings": headings} if headings else None


def claim_failures(draft, inherited):
    """Why a spec draft's claims are not one per inherited result waiting for its verdict, each under the objective."""
    if not inherited:
        return []
    failures, seen = [], {}
    for claim in draft.get("claims") or ():
        heading = claim.get("inherited")
        if heading is None:
            continue
        if heading not in inherited["headings"]:
            failures.append("claim %s verifies %s, which is no inherited result waiting for its verdict" % (claim["id"], heading))
            continue
        seen.setdefault(heading, []).append(claim["id"])
        if inherited["objective"] not in claim.get("objectives") or ():
            failures.append("claim %s verifies the inherited result %s and does not name %s"
                            % (claim["id"], heading, inherited["objective"]))
    for heading in inherited["headings"]:
        if heading not in seen:
            failures.append("the inherited result %s has no claim: draft one claim with `inherited` naming it, under %s"
                            % (heading, inherited["objective"]))
        elif len(seen[heading]) > 1:
            failures.append("the inherited result %s has more than one claim (%s): one claim judges all its claims together"
                            % (heading, ", ".join(seen[heading])))
    return failures


def spec_lines(project, inherited):
    """The specify prompt's part on the inherited results, or none."""
    if not inherited:
        return []
    results = {result["heading"]: result for result in current_record(project)["results"]}
    lines = ["", "# The inherited results", "",
             "The project starts midway, and %s asks \"%s\". Draft exactly one claim per inherited result below, naming its "
             "heading in `inherited` and %s in `objectives`: the claim is that the result holds as worded, and its experiment "
             "re-runs it (the project's own code at the commit intake recorded, a port, a reimplementation from the inherited "
             "Methods, or a read of a cited claim's reference) and judges its wording, narrowing an overstated claim to what the "
             "evidence shows. A gap that needs new experiments is a claim of its own, not the verification's." % (
                 inherited["objective"], OBJECTIVE, inherited["objective"]), ""]
    for heading in inherited["headings"]:
        lines.append("- %s: %s" % (heading, ", ".join(results.get(heading, {}).get("claims") or [])))
    return lines


# --- the plan: the verification tickets and the edges they hold ----------------------------------------------


CLOSED = ("done", "accepted", "parked")


def ties(project):
    """`{heading: objectives}`: the objectives each inherited result is tied to, through the concerns placed on objectives that
    target its claims and the objectives its passages name; what a ticket built on the result serves."""
    from wayline import concerns, sections

    ledger = ledger_for(project)
    record = current_record(ledger)
    try:
        held = concerns.read_concerns(ledger)
    except concerns.ConcernsUnreadable:
        held = []
    by_id = {item["id"]: item for item in sections.read_passages(ledger)}
    index = _claim_index(ledger, record)
    found = {}
    for result in record["results"]:
        ids = _claim_ids(ledger, result["heading"], index)
        tied = set()
        for concern in held:
            if concern.get("place") == concerns.OBJECTIVES and ids & set(concern.get("targets") or []):
                tied |= set(concern.get("objectives") or [])
        for identifier in ids:
            tied |= set((by_id.get(identifier) or {}).get("objectives") or [])
        found[result["heading"]] = tied
    return found


def waiting_headings(project):
    """The inherited results a plan verifies: unchecked, while the objective is open; empty otherwise."""
    objective = _objective(project)
    if objective is None or objective["status"] != "open":
        return [], None
    return [result["heading"] for result in current_record(project)["results"] if result["standing"] == UNCHECKED], objective["id"]


def wire(project, prepared, existing, kind):
    """The plan's verification tickets checked and their edges wired, in `prepared.tickets`; returns the failures.

    Every ticket's `verifies` names an inherited result waiting for its verdict; a first plan, a re-cut, or a revise leaves
    none waiting without a verification ticket (a split and a drafted ticket ask nothing). Each verification ticket, new or kept, blocks every
    ticket that serves an objective its result is tied to (`ties`), never another verification or a decision: each new
    one, and each kept one not yet run or stopped short (re-pointed in `prepared.repointed`).
    """
    waiting, objective = waiting_headings(project)
    failures = []
    verifying = {}
    for identifier, (fields, _) in existing.items():
        if fields.get("verifies") and fields["status"] not in CLOSED and identifier not in prepared.superseded:
            verifying.setdefault(fields["verifies"], set()).add(identifier)
    for key, fields, _, _ in prepared.tickets:
        heading = fields.get("verifies")
        if heading is None:
            continue
        if heading not in waiting:
            failures.append("%s verifies %s, which is no inherited result waiting for its verdict"
                            % (prepared.labels.get(fields["id"], key), heading))
            continue
        verifying.setdefault(heading, set()).add(fields["id"])
    if kind not in ("split", "draft"):  # a split and a drafted ticket add work and leave the rest of the graph as it is
        for heading in waiting:
            if not verifying.get(heading):
                failures.append("the inherited result %s waits for its verdict and no ticket verifies it: add one with `verifies` "
                                "naming it, under %s" % (heading, objective))
    tied = ties(project) if verifying else {}

    def wired(fields):
        served = set(fields.get("objectives") or [])
        blockers = set(fields["blocked_by"])
        for heading, ids in verifying.items():
            if served & tied.get(heading, set()):
                blockers |= ids - {fields["id"]}
        return sorted(blockers)

    for _, fields, _, _ in prepared.tickets:
        if not fields.get("verifies") and fields.get("kind") != "decision":
            fields["blocked_by"] = wired(fields)
    for identifier, (fields, _) in existing.items():
        kept = prepared.repointed.get(identifier, fields)
        if (identifier in prepared.superseded or kept.get("verifies") or kept.get("kind") == "decision"
                or kept["status"] not in PAUSABLE):
            continue
        blockers = wired(kept)
        if blockers != sorted(kept["blocked_by"]):
            prepared.repointed[identifier] = dict(kept, blocked_by=blockers)
    return failures


# --- a verification ticket's result ----------------------------------------------------------------------------


def intake_commit(project):
    """The commit of the project's own code intake recorded (`harness.json`'s `code_repository.upstream`), or None."""
    from wayline import code_repository

    try:
        return (code_repository.record(project).get("upstream") or {}).get("commit")
    except (ValueError, OSError):
        return None


def _same_commit(given, recorded):
    given, recorded = str(given or "").strip().lower(), str(recorded or "").strip().lower()
    return len(given) >= 7 and recorded.startswith(given)


def _claim_index(ledger, record=None, view=None):
    """`{id: (heading, ids)}`: every id an inherited claim has held (as first deconstructed, and as its document rewrote or
    moved it), with its result's heading and the claim's whole chain of ids; built once for a caller's every lookup."""
    view = view or _View(ledger)
    record = record if record is not None else current_record(ledger)
    index = {}
    for result in record["results"]:
        for claim in result["claims"]:
            chain = set(view.follow(claim)[0])
            for identifier in chain:
                index[identifier] = (result["heading"], chain)
    return index


def _claim_ids(ledger, heading, index=None):
    """Every id an inherited claim of `heading` has held."""
    index = index if index is not None else _claim_index(ledger)
    return {identifier for identifier, (found, _) in index.items() if found == heading}


def check_result(project, fields, result):
    """The verification's Type-A check over one ticket result: the problems, each one line, empty when it passes.

    A ticket that `verifies` a result names its route in `verification`; `reproduced` runs at the commit intake recorded,
    `read` is the consultant's alone, and a verdict on substitute data narrows each claim it replaces to that data. A
    `running` result (its jobs re-run the result) is held to the same, since its route is chosen when the jobs launch; a
    ticket that verifies nothing, and a result neither done nor running, are held to none of it.
    """
    heading = (fields or {}).get("verifies")
    result = result if isinstance(result, dict) else {}
    if not heading or result.get("status") not in ("done", "running"):
        return []
    ticket = fields.get("id")
    said = result.get("verification")
    if not isinstance(said, dict) or not said.get("route"):
        return ["ticket %s verifies the inherited result %s and its result names no route: say in `verification` whether it "
                "reproduced, ported, or reimplemented it, with the commit and any substitute data" % (ticket, heading)]
    problems = []
    route = said["route"]
    if route == READ:
        problems.append("ticket %s names the route read, and read is the consultant's route, which code takes batched per "
                        "reference: a ticket reproduces, ports, or reimplements" % ticket)
    elif route == REPRODUCED:
        recorded = intake_commit(project)
        if recorded is None:
            problems.append("ticket %s names the route reproduced, which runs the project's own code at the commit intake "
                            "recorded, and intake recorded none: the route is ported or reimplemented" % ticket)
        elif not _same_commit(said.get("commit"), recorded):
            problems.append("ticket %s: reproduced runs the project's own code at the commit intake recorded, %s, changed only to "
                            "run here; the result names %s (code changed in its logic is a port)"
                            % (ticket, recorded[:12], said.get("commit") or "no commit"))
    substitute = _one_line(said.get("substitute"))
    if substitute:
        ours = _claim_ids(ledger_for(project), heading)
        for index, item in enumerate(result.get("findings") or [], start=1):
            if isinstance(item, dict) and item.get("replaces") in ours and item.get("evidence") != "narrows":
                problems.append("finding %d replaces %s on substitute data (%s) and says %s: a verdict on substitute data covers "
                                "only the claim narrowed to that data, so its evidence is narrows"
                                % (index, item["replaces"], substitute, item.get("evidence") or "nothing"))
    return problems


def take_result(project, fields, result):
    """Record a done verification ticket's verdict, once its findings are filed: its route, its commit, any substitute data,
    and each inherited claim of its result a finding of the ticket replaced, with the evidence. Returns the result, or None
    for a ticket that verifies nothing."""
    from wayline import sections

    heading = (fields or {}).get("verifies")
    said = (result or {}).get("verification") if isinstance(result, dict) else None
    if not heading or not isinstance(said, dict) or not said.get("route"):
        return None
    ledger = ledger_for(project)
    with ledger.lock():
        record = read_record(ledger)
        before = {result["heading"]: result["standing"] for result in record["results"]}
        _refresh(ledger, record)
        try:
            found = _find(record, heading)
        except VerificationError:
            return None  # a result the record does not hold, such as one a newer version of its document withdrew
        ours = _claim_ids(ledger, heading)
        settled = [{"claim": item["replaces"], "evidence": item["evidence"], "by": item["id"]}
                   for item in sections.read_findings(ledger)
                   if item.get("ticket") == fields["id"] and item.get("replaces") in ours and item.get("evidence")]
        verdict = {"ticket": fields["id"], "route": said["route"], "commit": said.get("commit"),
                   "substitute": _one_line(said.get("substitute")) or None, "claims": settled}
        if verdict in found["verdicts"]:
            return found
        found["verdicts"].append(verdict)
        _refresh(ledger, record)
        _save(ledger, record, [result for result in record["results"] if result["standing"] != before.get(result["heading"])],
              "code", route=said["route"])
    return found


# --- the contradictions and the verifier ------------------------------------------------------------------------


def _heading_of(ledger, claim, index=None):
    """The inherited result an inherited claim belongs to, by any id it held, or None."""
    index = index if index is not None else _claim_index(ledger)
    return index[claim][0] if claim in index else None


def attach_contradiction(project, claims, text):
    """Attach a contradiction to the result of the inherited claims it touches, for its verification to answer: the worker's
    pack and the verifier's question carry it. Returns the headings it was attached to.

    The repeated-claims check's own contradictions (ticket 95) are not attached: `_contradictions` reads them where they
    are listed each time, so one the owner marked not a contradiction leaves the verification with it.
    """
    ledger = ledger_for(project)
    text = _one_line(text)
    if not text:
        raise VerificationError("a contradiction says what contradicts what")
    attached = []
    with ledger.lock():
        record = read_record(ledger)
        _refresh(ledger, record)
        index = _claim_index(ledger, record)
        for claim in claims:
            heading = _heading_of(ledger, claim, index)
            if heading is None:
                continue
            result = _find(record, heading)
            entry = next((item for item in result["contradictions"] if item["text"] == text), None)
            if entry is None:
                entry = {"text": text, "claims": []}
                result["contradictions"].append(entry)
            if claim not in entry["claims"]:
                entry["claims"].append(claim)
            if heading not in attached:
                attached.append(heading)
        if not attached:
            raise VerificationError("%s names no inherited Results claim" % ", ".join(claims))
        _save(ledger, record, [], "code")
    return attached


def attach_inventory(project, heading, disagreements=(), leads=()):
    """File what the setup at a start midway found into the verification of one inherited result (ticket 108): each
    disagreement between the inherited Methods and the code, and each lead the reading of the inherited code raised,
    `{text, path, line}`, once each. Returns how many were new."""
    ledger = ledger_for(project)
    added = 0
    with ledger.lock():
        record = read_record(ledger)
        changed = _refresh(ledger, record)
        result = _find(record, heading)
        for field, entries in (("disagreements", disagreements), ("leads", leads)):
            held = result.setdefault(field, [])
            for entry in entries:
                note = {"text": _one_line(entry.get("text")), "path": entry.get("path"), "line": entry.get("line")}
                if note["text"] and not any(item["text"] == note["text"] for item in held):
                    held.append(note)
                    added += 1
            if not held:
                del result[field]
        if added or changed:
            _save(ledger, record, changed, "code")
    return added


def _contradictions(ledger, result):
    """The contradictions a result's verification answers, each `{text, claims}`: those attached to it, then those the
    repeated-claims check lists now on its heading (`repeats.contradictions`, ticket 95)."""
    from wayline import repeats  # the repeated-claims check reads the sections and the batches

    found = [dict(entry) for entry in result["contradictions"]]
    try:
        listed = repeats.contradictions(ledger, heading=result["heading"])
    except repeats.RepeatsError:
        listed = []
    for entry in listed:
        text = _one_line(entry.get("why")) or "%s contradicts %s" % (entry["a"], entry["b"])
        if not any(item["text"] == text for item in found):
            found.append({"text": text, "claims": [entry["a"], entry["b"]]})
    return found


def verdict_items(project, fields, result):
    """Each verdict on an inherited claim a ticket's result gives, for the fresh verifier to check one by one: the claim,
    its inherited words, the evidence and the finding that replaces it, the route, and the contradictions it carries."""
    from wayline import sections

    result = result if isinstance(result, dict) else {}
    ledger = ledger_for(project)
    by_id = {item["id"]: item for item in sections.read_passages(ledger)}
    said = result.get("verification") if isinstance(result.get("verification"), dict) else {}
    record = current_record(ledger)
    index = _claim_index(ledger, record)
    items = []
    for finding in result.get("findings") or []:
        if not isinstance(finding, dict) or not finding.get("evidence") or finding.get("replaces") not in by_id:
            continue
        claim = by_id[finding["replaces"]]
        if not sections.is_inherited(claim) or claim.get("standing") not in sections.STANDINGS:
            continue
        heading, chain = index.get(claim["id"], (None, set()))
        contradictions = []
        if heading is not None:
            contradictions = [entry["text"] for entry in _contradictions(ledger, _find(record, heading)) if chain & set(entry["claims"])]
        items.append({"claim": claim["id"], "said": _plain_claim(claim["text"]), "evidence": finding["evidence"],
                      "finding": _one_line(finding.get("text")), "route": said.get("route"), "commit": said.get("commit"),
                      "substitute": _one_line(said.get("substitute")) or None, "contradictions": contradictions})
    return items


INHERITED_QUESTION = (
    "Besides, this ticket gave a verdict on inherited claims, which the project's earlier writing made and this project's "
    "evidence now replaces (decision 17). For each one below, does the finding's evidence bear out the verdict it gives "
    "(supports, narrows, or contradicts), by the route it names, at the commit it names, covering only the substitute data it "
    "names, and answering the contradictions attached? Give your judgment of every item in `inherited`; an item that does "
    "not hold fails this verdict, with a finding that says why."
)


def verdict_text(items):
    """The lines a verdict's question lists for the inherited claims of one ticket."""
    lines = [INHERITED_QUESTION]
    for item in items or ():
        route = item.get("route") or "no route named (a ticket that does not verify the result)"
        if item.get("route") == REPRODUCED and item.get("commit"):
            route = "reproduced at %s" % str(item["commit"])[:12]
        if item.get("substitute"):
            route += ", on substitute data: %s" % item["substitute"]
        lines.append("- %s \"%s\": %s, %s; the finding: %s" % (item["claim"], item["said"], item["evidence"], route, item["finding"]))
        lines.extend("  - contradiction attached: %s" % text for text in item.get("contradictions") or ())
    return "\n".join(lines)


# --- a verification ticket's context pack ---------------------------------------------------------------------


def pack_text(project_or_ledger, fields, max_chars=None):
    """The context pack's part on the inherited result a verification ticket verifies; empty for any other ticket.

    Its claims in the manuscript's words, the commit intake recorded, the contradictions attached, the missing material
    with the replies, and what the result must carry. `max_chars` is what the tier's context cap leaves this part: what
    does not fit is cut with the cut announced, and the rest is in `research/VERIFICATIONS.md`.
    """
    from wayline import sections

    heading = (fields or {}).get("verifies")
    if not heading:
        return ""
    ledger = ledger_for(project_or_ledger)
    try:
        record = current_record(ledger)
        result = _find(record, heading)
    except (VerificationError, VerificationUnreadable):
        return ""
    by_id = {item["id"]: item for item in sections.read_passages(ledger)}
    commit = intake_commit(ledger.project)
    lines = ["# The inherited result this ticket verifies: %s" % heading, "",
             "Re-run it, then judge its wording, so an overstated claim is narrowed to what the evidence shows (decision 17). "
             "Return a finding replacing each claim below (`replaces` its P id) that says in `evidence` whether this project's "
             "evidence supports, narrows, or contradicts it, and name your route in `verification`: `reproduced` (the project's "
             "own code at %s, changed only to run here), `ported` (the same logic in another language or runtime), or "
             "`reimplemented` (written from the inherited Methods). On substitute data, give it in `verification.substitute`: "
             "the verdict covers only each claim narrowed to that data, so each finding narrows. Missing code, data, or software "
             "ends the ticket blocked with `blocked_on: \"material <code|data|software>: <the item>\"`; a gap that needs new "
             "experiments is a proposal (`add`), not this verification's to close."
             % ("the commit intake recorded, %s" % commit if commit else "the commit intake recorded (none was: the route is ported "
                                                                           "or reimplemented)"), "", "## Its claims"]
    for claim, (current, state) in _claim_states(ledger, result["claims"]).items():
        item = by_id.get(current) or {}
        lines.append("- %s (%s): %s" % (current, state, _plain_claim(item.get("text"))))
    contradictions = _contradictions(ledger, result)
    if contradictions:
        lines += ["", "## Contradictions attached, which the verification answers"]
        lines += ["- %s (%s)" % (entry["text"], ", ".join(entry["claims"])) for entry in contradictions]
    if result.get("disagreements"):
        lines += ["", "## Where the inherited Methods and the code disagree, found at setup, which the verification answers"]
        lines += ["- %s" % entry["text"] for entry in result["disagreements"]]
    if result.get("leads"):
        lines += ["", "## Leads from the reading of the inherited code at setup, to look into"]
        lines += ["- %s%s" % (entry["text"], " (%s:%s)" % (entry["path"], entry["line"]) if entry.get("path") and entry.get("line") else "")
                  for entry in result["leads"]]
    items = [item for item in record["material"] if item["heading"] == heading]
    if items:
        lines += ["", "## Material it needs that the project lacked"]
        lines += ["- %s %s %s: %s" % (item["id"], item["kind"], item["item"], item["reply"] or "no reply yet") for item in items]
    text = "\n".join(lines)
    if max_chars is not None and len(text) > max(0, int(max_chars)):
        cut = text[:max(0, int(max_chars))].rsplit("\n", 1)[0]
        text = cut + ("\n\n" if cut else "") + ("[wayline: the inherited result reached the context cap; the rest is in "
                                                "research/VERIFICATIONS.md.]")
    return text


def reading(project):
    """Whether the read route runs now: past setup, while the objective "Do the inherited results hold?" is open."""
    from wayline import stopping

    try:
        objective = _objective(project)
    except ValueError:
        return False
    return objective is not None and objective["status"] == "open" and stopping.after_setup(ledger_for(project).read_events()[0])


# --- the read route: a cited claim against its reference, by the consultant ---------------------------------------


_REF = re.compile(r"\{ref:([^{}]+)\}")
_READ_LINE = re.compile(r"^\s*(\d+)\s*[:.)]\s*(supports|narrows|contradicts|cannot settle)\b\s*[-:,]*\s*(.*)$", re.IGNORECASE | re.MULTILINE)
READ_QUESTION = (
    "Each numbered sentence below is a claim the project's earlier manuscript makes, citing this work. Judge each against what "
    "the dossier holds at its level, the abstract first: answer one line per claim, `<n>: supports`, `<n>: narrows`, `<n>: "
    "contradicts`, or `<n>: cannot settle`, then a dash and what the work says that decides it. Say `cannot settle` whenever "
    "what you read does not decide the claim, and ask for the promotion when a full read of the work would."
)


def _cited_slugs(text, index):
    from wayline import provenance

    slugs = []
    for body in _REF.findall(str(text or "")):
        _, parts = provenance.parse_tag("ref:" + body)
        slug = provenance.ref_slug(parts, index)
        if slug and slug not in slugs:
            slugs.append(slug)
    return slugs


def _plain_claim(text):
    return _one_line(re.sub(r"\{(?:doc|ref|res|code):[^{}]+\}", "", str(text or "")))


def read(project, ticket=None):
    """The read route over every inherited claim still unchecked that cites a reference the project holds: one consultant
    question per reference, every claim citing it batched in it, read at the dossier's level (L0's abstract first).

    A claim the answer settles is replaced by a finding saying whether the reference supports, narrows, or contradicts it,
    with the reference as its tag; one it cannot settle stays unchecked, and is read again only once the dossier was
    promoted (the consultant asks for the promotion, which the budget allows or a decision ticket asks about). Returns
    `{asked, settled}`: the references asked about, and the claims settled. A claim citing two references is settled by
    the first read that settles it, and not asked about again. A question the consultant could not answer usably is
    recorded as a failed read at that level and not asked again until a promotion; one a usage window refused is asked
    again at a later wave.
    """
    from wayline import consult
    from wayline.dossier import DossierError, read_dossier
    from wayline.provenance import identifier_index

    ledger = ledger_for(project)
    report = {"asked": [], "settled": []}
    record = current_record(ledger)
    view = _View(ledger)
    by_id = view.by_id
    index = identifier_index(ledger.project)
    batches = {}
    for result in record["results"]:
        if result["standing"] != UNCHECKED:
            continue
        for claim, (current, state) in _claim_states(ledger, result["claims"], view).items():
            if state != UNCHECKED:
                continue
            for slug in _cited_slugs((by_id.get(current) or {}).get("text"), index):
                batches.setdefault(slug, []).append((result["heading"], current))
    settled_now = set()
    for slug, claims in batches.items():
        try:
            level = read_dossier(ledger, slug).get("level", 0)
        except DossierError:
            continue
        claims = [(heading, current) for heading, current in claims if current not in settled_now]
        if not claims:
            continue
        ids = [current for _, current in claims]
        done = [entry for entry in record["reads"] if entry["slug"] == slug and entry["level"] >= level]
        if any(set(ids) <= set(entry["claims"]) for entry in done):
            continue
        question = READ_QUESTION + "\n\n" + "\n".join("%d. %s" % (number, _plain_claim(by_id[current]["text"]))
                                                       for number, current in enumerate(ids, 1))
        try:
            asked = consult.ask(ledger.project, slug, question, ticket=ticket)
        except consult.ConsultError as failure:
            if "usage limit" not in str(failure):
                _take_reads(ledger, slug, level, claims, {}, None, failed=_one_line(failure))
            continue
        report["asked"].append(slug)
        answer = asked["answer"]
        verdicts = {}
        if not answer.get("not_in_source"):
            for number, said, why in _READ_LINE.findall(answer.get("answer") or ""):
                said = said.lower()
                if said != "cannot settle" and 1 <= int(number) <= len(ids):
                    verdicts[ids[int(number) - 1]] = (said, _one_line(why))
        locator = next((str(found).split(":", 1)[1] for found in answer.get("locators") or [] if ":" in str(found)), None) or "abstract"
        settled = _take_reads(ledger, slug, level, claims, verdicts, locator)
        settled_now.update(settled)
        report["settled"] += settled
    return report


def _take_reads(ledger, slug, level, claims, verdicts, locator, failed=None):
    """File a finding for each claim a read settled, record the read and its verdicts (or why it failed); returns the claims
    settled. A claim the work replaced while the consultant read is left as it stands."""
    from wayline import sections

    with ledger.lock():
        record = read_record(ledger)
        found = _refresh(ledger, record)  # a result read before code recorded it is recorded first, unchecked
        if found:
            _save(ledger, record, found, "code")
        before = {result["heading"]: result["standing"] for result in record["results"]}
        view = _View(ledger)
        by_id = view.by_id
        settled = {}
        for heading, current in claims:
            if current not in verdicts or view.follow(current)[1:] != (current, UNCHECKED):
                continue
            evidence, why = verdicts[current]
            text = _plain_claim(by_id[current]["text"]) if evidence == "supports" else (why or _plain_claim(by_id[current]["text"]))
            text = text.rstrip() + "{ref:%s#%s}" % (slug, locator)
            sections.file_finding(ledger, {"id": "read-%s" % current, "ticket": None, "text": text,
                                           "provenance": "research/refs/%s/qa_log.md" % slug, "negative": False, "heading": heading,
                                           "replaces": current, "evidence": evidence, "objectives": []})
            settled.setdefault(heading, []).append({"claim": current, "evidence": evidence, "by": "read-%s" % current})
        _refresh(ledger, record)
        for heading, entries in settled.items():
            _find(record, heading)["verdicts"].append({"ticket": None, "route": READ, "commit": None, "substitute": None,
                                                       "claims": entries})
        entry = {"slug": slug, "level": level, "claims": [current for _, current in claims],
                 "settled": [entry["claim"] for entries in settled.values() for entry in entries]}
        if failed:
            entry["failed"] = failed
        record["reads"].append(entry)
        _save(ledger, record, [result for result in record["results"] if result["standing"] != before.get(result["heading"])],
              "code", route=READ)
    return [entry["claim"] for entries in settled.values() for entry in entries]


# --- after setup: a gap is a decision pausing only its verification ----------------------------------------------


CLASS = "material"                      # the decision class of a gap after setup, which the owner may name human-only
ORIGIN = "material %s #%d"              # the origin of the n-th decision ticket asking about one missing item
_ORIGIN = re.compile(r"^material (M[1-9][0-9]*) #([1-9][0-9]*)\Z")
_GAP = re.compile(r"^\s*material\s+(code|data|software)\s*:\s*(\S.*)$", re.IGNORECASE)
PAUSABLE = ("open", "failed", "blocked", "needs_human")


def material_of(origin):
    """The missing item a decision ticket's origin asks about, or None for a ticket of another kind."""
    found = _ORIGIN.match(str(origin or ""))
    return found.group(1) if found else None


def gap_of(blocked_on):
    """`(kind, item)` when a worker's `blocked_on` reads `material <code|data|software>: <the item>`; None otherwise."""
    found = _GAP.match(str(blocked_on or ""))
    return (found.group(1).lower(), _one_line(found.group(2))) if found else None


def decider_refusal(answer):
    """Why the decider may not give `answer` to a gap's decision ticket, or None: it rebuilds or leaves it unverified."""
    reply = _reply(answer)
    if reply is None:
        return "its answer names no reply (rebuild it, a port, or leave it unverified): %s" % _one_line(answer)
    if reply == PROVIDE:
        return "the decider rebuilds or leaves a result unverified and never provides: only the owner can hand material over"
    return None


def _licensed(kind, item):
    return kind == "software" and "matlab" in item.casefold()


def _verifiers(project, heading):
    from wayline import tickets

    return [fields for fields in tickets.read_tickets(project) if fields.get("verifies") == heading]


def _ask(project, item, number, why=None, notify=None):
    """Open the n-th decision ticket on one missing item, pausing the verification tickets of its result."""
    from wayline import decisions

    pauses = [fields["id"] for fields in _verifiers(project, item["heading"]) if fields["status"] in PAUSABLE]
    options = list(LICENSED_REPLIES) + [LEAVE] if item["licensed"] else list(REPLIES)
    evidence = [_evidence_line(item), "found by %s" % item["found_by"],
                "pauses only the verification of %s (%s); every other ticket goes on"
                % (item["heading"], ", ".join("ticket %d" % identifier for identifier in pauses) or "no ticket yet")]
    if why:
        evidence.append(why)
    question = ("The verification of the inherited result %s lacks %s %s: provide it, rebuild it, or leave the result unverified?"
                % (item["heading"], item["kind"], item["item"]))
    return decisions.open_decision(project, question, options=options, recommended=recommended(item), evidence=evidence,
                                   blocking="subgraph", pauses=pauses, proposed_by="conductor", origin=ORIGIN % (item["id"], number),
                                   title="What about %s?" % item["item"], notify=notify, decision_class=CLASS)


def open_gap(project, ticket, blocked_on, notify=None):
    """The decision a verification's newly found gap opens, pausing only that verification; the report, or None when
    `blocked_on` names no gap or `ticket` verifies nothing.

    The item is recorded (`found_by: ticket <n>`); one already recorded is asked about again, its earlier reply set aside,
    since the verification still lacks it.
    """
    from wayline import tickets

    gap = gap_of(blocked_on)
    fields = {item["id"]: item for item in tickets.read_tickets(project)}.get(ticket)
    if gap is None or fields is None or not fields.get("verifies"):
        return None
    kind, name = gap
    ledger = ledger_for(project)
    with ledger.lock():
        record = read_record(ledger)
        _refresh(ledger, record)
        _find(record, fields["verifies"])
        item, new = _add_item(record, fields["verifies"], kind, name, _licensed(kind, name), kind != "data", "ticket %d" % ticket)
        if not new and item["reply"] is not None:
            item.update(reply=None, by=None)
        _save(ledger, record, [], "code")
        mine = _asked(project).get(item["id"], [])
        answered = _answers(ledger.read_events()[0])
        if mine and mine[-1]["status"] == "open" and mine[-1]["id"] not in answered:
            return _ask(project, item, len(mine), notify=notify)  # the same ask, which now pauses this verification too
    return _ask(project, item, len(mine) + 1, why="ticket %d reported: %s" % (ticket, _one_line(blocked_on)), notify=notify)


def _asked(project):
    """`{item: [ticket fields]}`: every decision ticket asking about each missing item, in the order they were asked."""
    from wayline import tickets

    found = {}
    for fields in tickets.read_tickets(project):
        identifier = material_of(fields.get("origin"))
        if identifier is not None:
            found.setdefault(identifier, []).append(fields)
    for listed in found.values():
        listed.sort(key=lambda fields: int(_ORIGIN.match(fields["origin"]).group(2)))
    return found


def _answers(events):
    """The last `decision` journaled for each ticket, and when, after the last time it was asked again."""
    from wayline.ledger import DECISION, TICKET_RERUN

    answered = {}
    for index, event in enumerate(events):
        payload = event.get("payload") or {}
        if event.get("event") == DECISION and payload.get("ticket") is not None:
            answered[payload["ticket"]] = (index, payload)
        elif event.get("event") == TICKET_RERUN and payload.get("ticket") in answered:
            answered.pop(payload["ticket"])
    return answered


def release(project, heading, by):
    """An unverifiable result releases what its verification blocked: every open verification ticket of it is parked, its
    open gap decisions with it, and each ticket that waited on them no longer does. Returns the tickets released."""
    from wayline import tickets
    from wayline.ledger import TICKET_CANCELLED

    ledger = ledger_for(project)
    with ledger.lock():
        record = read_record(ledger)
        held = tickets.read_tickets(ledger.project)
        ours = {fields["id"] for fields in held if fields.get("verifies") == heading}
        items = {item["id"] for item in record["material"] if item["heading"] == heading}
        asks = {fields["id"] for fields in held if material_of(fields.get("origin")) in items and fields["status"] == "open"}
        released = []
        for fields in held:
            path = tickets.tickets_dir(ledger.project) / tickets.filename(fields)
            if fields["id"] in ours | asks:
                if fields["status"] in PAUSABLE:
                    current, body = tickets.read_ticket(path)
                    tickets.write_ticket(ledger, dict(current, status="parked"), body)
                    ledger.append_event(TICKET_CANCELLED, {"ticket": fields["id"], "by": "code"}, ticket=fields["id"])
                continue
            if fields["status"] not in CLOSED and set(fields["blocked_by"]) & (ours | asks):
                current, body = tickets.read_ticket(path)
                tickets.write_ticket(ledger, dict(current, blocked_by=sorted(set(current["blocked_by"]) - ours - asks)), body)
                released.append(fields["id"])
    return released


def _reopen_blocked(project, item, say):
    """The verification tickets this item's gap blocked go back to open, once its reply lets the work go on."""
    from wayline import tickets
    from wayline.ledger import TICKET_BLOCKED, TICKET_RERUN

    ledger = ledger_for(project)
    events, _ = ledger.read_events()
    last = {}
    for event in events:
        if event.get("event") == TICKET_BLOCKED:
            last[(event.get("payload") or {}).get("ticket")] = (event.get("payload") or {}).get("path")
    with ledger.lock():
        for fields in _verifiers(ledger.project, item["heading"]):
            gap = gap_of(last.get(fields["id"]))
            if fields["status"] != "blocked" or gap is None or (gap[0], gap[1].casefold()) != (item["kind"], item["item"].casefold()):
                continue
            current, body = tickets.read_ticket(tickets.tickets_dir(ledger.project) / tickets.filename(fields))
            ledger.append_event(TICKET_RERUN, {"ticket": current["id"], "by": "code"}, ticket=current["id"])
            tickets.write_ticket(ledger, dict(current, status="open"), body)
            say("  ticket %d is open again: the reply on %s lets its verification go on" % (current["id"], item["id"]))


def _take_reply(project, item, reply, by, say):
    """Record one gap's reply: `leave it unverified` makes its result unverifiable; any other reply lets the work go on."""
    ledger = ledger_for(project)
    with ledger.lock():
        record = read_record(ledger)
        held = next(entry for entry in record["material"] if entry["id"] == item["id"])
        held.update(reply=reply, by=by)
        _save(ledger, record, [], by)
    if reply == LEAVE:
        leave_unverifiable(project, item["heading"], "%s is missing and the %s left it unverified" % (item["item"], by), by)
    else:
        _reopen_blocked(project, held, say)


def settle(project, notify=None, say=None):
    """The conductor's verification step of one wave: results followed, and, past setup, a decision per gap and the
    unverifiable results of verifications that ended `needs_human` under `autonomous`. Returns
    `{opened, applied, waiting, unverifiable}`.

    Nothing is asked while the objective "Do the inherited results hold?" is not open. Everything is read back from the
    journal and the files, so a second call, or a restarted conductor, asks nothing twice.
    """
    from wayline import decider, decisions, stopping, tickets
    from wayline.ledger import TICKET_NEEDS_HUMAN
    from wayline.project import read_harness

    say = say or (lambda line: None)
    report = {"opened": [], "applied": [], "waiting": [], "unverifiable": []}
    follow(project)
    ledger = ledger_for(project)
    events, _ = ledger.read_events()
    if not stopping.after_setup(events):
        return report
    record = read_record(ledger)
    standing = {result["heading"]: result["standing"] for result in record["results"]}
    objective = _objective(ledger.project)
    if objective is None or objective["status"] != "open":
        return report  # the owner parked or dropped the verification, or never took it: nothing to verify, nothing to ask
    if read_harness(ledger.project).get("autonomy") == "autonomous":
        questions = {}
        for event in events:
            if event.get("event") == TICKET_NEEDS_HUMAN:
                questions[(event.get("payload") or {}).get("ticket")] = (event.get("payload") or {}).get("question")
        for fields in tickets.read_tickets(ledger.project):
            heading = fields.get("verifies")
            if not heading or fields["status"] != "needs_human" or standing.get(heading) != UNCHECKED:
                continue
            leave_unverifiable(ledger.project, heading, "verification ticket %d ended needs_human under autonomous: %s"
                               % (fields["id"], _one_line(questions.get(fields["id"])) or "no question given"), "code")
            standing[heading] = UNVERIFIABLE
            report["unverifiable"].append(heading)
            say("  the inherited result %s is unverifiable: ticket %d ended needs_human under autonomous" % (heading, fields["id"]))
    answered = _answers(events)
    asked = _asked(ledger.project)
    for item in waiting_items(ledger):
        if standing.get(item["heading"]) != UNCHECKED:
            continue
        mine = asked.get(item["id"], [])
        why = None
        if mine:
            latest = mine[-1]
            given = answered.get(latest["id"])
            if given is None and latest["status"] == "open":
                report["waiting"].append(latest["id"])
                continue
            if given is None:
                why = "ticket %d was closed with no answer" % latest["id"]
            else:
                payload = given[1]
                by = "decider" if payload.get("decided_by") == "decider" else "owner"
                body = tickets.read_ticket(tickets.tickets_dir(ledger.project) / tickets.filename(latest))[1]
                try:
                    options = (decisions.decision_record(body) or {}).get("options") or []
                except ValueError:
                    options = []
                reply = reply_for(item, _reply(decider.chosen_option(payload.get("answer"), options)))
                refused = decider_refusal(reply or payload.get("answer")) if by == "decider" else None
                if reply is not None and refused is None:
                    _take_reply(ledger.project, item, reply, by, say)
                    report["applied"].append(item["id"])
                    say("  %s: the %s's answer to ticket %d: %s" % (item["id"], by, latest["id"], reply))
                    continue
                why = "the answer to ticket %d, \"%s\", %s" % (latest["id"], _one_line(payload.get("answer")),
                                                              refused or "names no reply %s takes" % item["id"])
        opened = _ask(ledger.project, item, len(mine) + 1, why=why, notify=notify)
        if opened["opened"]:
            report["opened"].append(opened["ticket"])
            say("  %s waits for a reply: decision ticket %d" % (item["id"], opened["ticket"]))
    return report


# --- VERIFICATIONS.md --------------------------------------------------------------------------------------


def render(record):
    """`research/VERIFICATIONS.md`: each inherited result with its standing, its claims, its verdicts, and the missing material."""
    lines = ["# Verifications", "",
             "Every inherited result, one inherited Results heading with all its claims, verified before anything is built on "
             "it: code writes this file from `research/verifications.json`. \"%s\"" % OBJECTIVE]
    if not record["results"]:
        lines += ["", "No inherited result: the project did not start midway."]
    for result in record["results"]:
        lines += ["", "## %s" % result["heading"], "",
                  "- standing: %s%s" % (result["standing"], ": %s" % result["reason"] if result["reason"] else ""),
                  "- claims: %s" % ", ".join(result["claims"])]
        for verdict in result["verdicts"]:
            said = ", ".join("%s %s" % (entry["claim"], entry["evidence"]) for entry in verdict["claims"]) or "no claim settled"
            lines.append("- verdict%s, %s%s%s: %s" % (
                " of ticket %d" % verdict["ticket"] if verdict["ticket"] else "", verdict["route"],
                " at %s" % verdict["commit"][:12] if verdict.get("commit") else "",
                " on substitute data (%s)" % verdict["substitute"] if verdict.get("substitute") else "", said))
        for contradiction in result["contradictions"]:
            lines.append("- contradiction (%s): %s" % (", ".join(contradiction["claims"]), contradiction["text"]))
        for entry in result.get("disagreements") or []:
            lines.append("- the inherited Methods and the code disagree: %s" % entry["text"])
        for entry in result.get("leads") or []:
            lines.append("- lead from the reading of the inherited code: %s" % entry["text"])
    if record["material"]:
        lines += ["", "## Missing material", "", "| Item | Result | Kind | Reply |", "|---|---|---|---|"]
        for item in record["material"]:
            lines.append("| %s %s | %s | %s%s | %s |" % (item["id"], item["item"].replace("|", "\\|"), item["heading"], item["kind"],
                                                       ", licensed" if item["licensed"] else "",
                                                       "%s (%s)" % (item["reply"], item["by"]) if item["reply"] else "waiting"))
    return "\n".join(lines) + "\n"
