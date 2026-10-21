"""Batches and marks (Implementation Decision 17; ticket 79).

Decision 17 puts several kinds of choice before the owner, or the decider at a rule's end, as a
**batch** of items: plots to keep, objective changes and the software ask to approve, decider
decisions to let stand, merges, contradictions, concern placements, and the outline's proposals.
This module is the one record for all of them, so every producer puts its items in one place and
the marks view and the conversation show and settle them the same way.

A batch is `research/batches/<id>.json` (schema `batch`), ids B1 onward, never reused, written
only through the ledger. Each item carries what it is about (`ref`), its text, the marks its kind
allows, code's default where it has one, the owner's note, and its settled mark with who settled
it, where, and when. A mark saves when given, with no submit: the first one settles the item, and a later
one is refused with what settled it, except that a mark the owner gave in the dashboard's marks view
changes on a second click there until its producer acts on it (ticket 112), which the producer says
with `acted_on`. A note alone is kept without settling. `take_defaults`
settles every open item that has a default in one call. A batch whose items are all settled is
closed, and its producer reads the marks back with `marks`. Every mark and every note is
journaled as `marked`.

What a batch is about, and what a producer does with its marks (answering a decision ticket,
redrawing a plot, approving a proposal), is the producer's; this module never acts on a mark.
"""

import argparse
import re
import sys
from collections import namedtuple

from wayline.cli import parse_args
from wayline.jsonschema import ValidationError, check, load_schema
from wayline.ledger import K_BATCH, K_BY, K_ITEM, K_MARK, K_NOTE, MARKED, LedgerError, ledger_for, now_ts
from wayline.project import ProjectError, find_project

__all__ = ["KINDS", "WHOLE_AT", "VIA", "BatchError", "open_batch", "extend", "read_batch", "read_batches", "mark", "take_defaults", "marks",
           "changeable", "acted_on", "link", "render", "mark_command"]

SCHEMA = "batch"
DIRECTORY = "batches"

# The marks view's marks by batch, in its order (decision 17, the dashboard); the schema's `kind` enum names the same kinds.
KINDS = {
    "plots": ("keep", "maybe", "drop"),
    "objective_changes": ("approve", "decline"),
    "software_ask": ("approve", "decline"),
    "account_review": ("stand", "reverse"),
    "merges": ("right", "split"),
    "contradictions": ("real", "not a contradiction"),
    "concern_placements": ("take it", "another place"),
    "outline_proposals": ("take", "decline"),
}

OPEN = "open"
CLOSED = "closed"

# The conversation shows a batch's items whole up to this many, otherwise one line with the count and a link.
WHOLE_AT = 5

# Who gives a mark: the owner, or the decider settling a batch at a rule's end.
OWNER = "owner"
DECIDER = "decider"
WHO = (OWNER, DECIDER)

# Where the owner gave a mark: the dashboard's marks view, or the conversation's `wayline mark` verb (ticket 112). A mark
# code gives on another answer (a decision ticket's, a review's) and the decider's name no place.
DASHBOARD = "dashboard"
CONVERSATION = "conversation"
VIA = (DASHBOARD, CONVERSATION)

_ID_RE = re.compile(r"^B([1-9][0-9]*)$")

# One `marked` event to journal: a mark, a note, or both, given on one item.
_Marked = namedtuple("_Marked", "item given note by ts")


class BatchError(ValueError):
    """A batch the module refuses to open, or a mark it refuses to record."""


def _path(identifier):
    return "%s/%s.json" % (DIRECTORY, identifier)


def _numbers(ledger):
    """The numbers of the batches the project holds, in order."""
    directory = ledger.research / DIRECTORY
    if not directory.is_dir():
        return []
    return sorted(int(match.group(1)) for match in (_ID_RE.match(path.stem) for path in directory.glob("*.json")) if match)


def _next_id(ledger):
    return "B%d" % (max(_numbers(ledger), default=0) + 1)


def _new_item(number, item, allowed):
    return {"id": number, "ref": item["ref"], "text": item["text"], "marks": allowed, "default": item.get("default"),
            "note": None, "mark": None, "by": None, "via": None, "at": None, "acted": None}


def _blank(text):
    return not isinstance(text, str) or not text.strip()


def _check_by(by):
    if by not in WHO:
        raise BatchError("a mark is given by %s, got %r" % (" or ".join(WHO), by))


def _open_count(batch):
    return sum(1 for item in batch["items"] if item["mark"] is None)


def open_batch(project, kind, title, items, decision=None):
    """Open a batch of `items` (each `{ref, text, default?}`) of one `kind`; returns the record written.

    `decision` is the decision ticket the batch answers, when there is one.
    """
    if kind not in KINDS:
        raise BatchError("a batch's kind is one of %s, got %r" % (", ".join(KINDS), kind))
    if _blank(title):
        raise BatchError("a batch has a title, got %r" % (title,))
    if not items:
        raise BatchError("a batch of %s with no items puts nothing before the owner" % kind)
    allowed = list(KINDS[kind])
    built = []
    for number, item in enumerate(items, start=1):
        if _blank(item.get("ref")) or _blank(item.get("text")):
            raise BatchError("item %d: an item names what it is about (`ref`) and says it (`text`)" % number)
        default = item.get("default")
        if default is not None and default not in allowed:
            raise BatchError("item %d (%s): a %s item's default is one of %s, got %r" % (number, item["ref"], kind, ", ".join(allowed), default))
        built.append(_new_item(number, item, allowed))
    ledger = ledger_for(project)
    with ledger.lock():
        record = {"id": _next_id(ledger), "kind": kind, "title": title, "decision": decision, "status": OPEN, "items": built}
        ledger.write_json(_path(record["id"]), record, schema=SCHEMA)
    return record


def extend(project, batch_id, items=(), decision=None):
    """Add `items` (each `{ref, text, default?}`) to an open batch, and with `decision` link it to that decision ticket instead.

    What takes new items until it is answered (the "Objective changes" ticket of ticket 91) adds them here; a batch whose
    ticket was answered with items left open is linked to the ticket that asks about those again. A closed batch takes
    nothing, and an item whose `ref` the batch holds already is not added twice. Returns the batch as written.
    """
    ledger = ledger_for(project)
    with ledger.lock():
        batch = read_batch(ledger, batch_id)
        if batch["status"] != OPEN:
            raise BatchError("%s is closed and takes no new item" % batch["id"])
        allowed = list(KINDS[batch["kind"]])
        held = {item["ref"] for item in batch["items"]}
        for item in items:
            if _blank(item.get("ref")) or _blank(item.get("text")):
                raise BatchError("an item names what it is about (`ref`) and says it (`text`)")
            if item["ref"] in held:
                continue
            default = item.get("default")
            if default is not None and default not in allowed:
                raise BatchError("a %s item's default is one of %s, got %r" % (batch["kind"], ", ".join(allowed), default))
            batch["items"].append(_new_item(len(batch["items"]) + 1, item, allowed))
            held.add(item["ref"])
        if decision is not None:
            batch["decision"] = decision
        ledger.write_json(_path(batch["id"]), batch, schema=SCHEMA)
    return batch


def read_batch(project, identifier):
    """One batch as its file holds it, checked against its schema and its kind's marks; a batch that is not there is a BatchError."""
    ledger = ledger_for(project)
    if not _ID_RE.match(str(identifier)):
        raise BatchError("a batch id is B1 onward, got %r" % (identifier,))
    try:
        record = ledger.read_json(_path(identifier))
    except FileNotFoundError:
        raise BatchError("%s holds no batch %s" % (ledger.project, identifier)) from None
    check(record, load_schema(SCHEMA), name="batch %s" % identifier)
    allowed = list(KINDS[record["kind"]])
    for item in record["items"]:
        if item["marks"] != allowed or any(value is not None and value not in allowed for value in (item["default"], item["mark"])):
            raise BatchError("batch %s, item %d: a %s item's marks are %s, and its default and mark are among them; the file says otherwise"
                             % (identifier, item["id"], record["kind"], ", ".join(allowed)))
    return record


def _item(batch, item_id):
    try:
        number = int(item_id)
    except (TypeError, ValueError):
        raise BatchError("an item is named by its number, 1 onward, got %r" % (item_id,)) from None
    for item in batch["items"]:
        if item["id"] == number:
            return item
    raise BatchError("batch %s has no item %s; its items are 1 to %d" % (batch["id"], item_id, len(batch["items"])))


def _settled_by(batch, item):
    where = " in the %s" % item["via"] if item.get("via") else ""
    acted = "; its producer acted on it at %s" % item["acted"] if item.get("acted") else ""
    return "item %d of %s was settled as %s by %s%s at %s%s" % (item["id"], batch["id"], item["mark"], item["by"], where, item["at"], acted)


def changeable(item):
    """Whether a click in the marks view may still change a settled item: the owner gave its mark there, and its producer
    has not acted on it yet."""
    return item["mark"] is not None and item["by"] == OWNER and item.get("via") == DASHBOARD and not item.get("acted")


def _check_via(via):
    if via is not None and via not in VIA:
        raise BatchError("a mark is given in the %s, got %r" % (" or the ".join(VIA), via))


def _close_if_settled(batch):
    if _open_count(batch) == 0:
        batch["status"] = CLOSED


def _save(ledger, batch, journaled):
    """Write the batch, then journal one `marked` per `_Marked` in `journaled`, under the lock the caller holds.

    The file first, as the ledger's other records are written before the event that tells of them,
    so a journaled mark is always one the file holds.
    """
    ledger.write_json(_path(batch["id"]), batch, schema=SCHEMA)
    for entry in journaled:
        payload = {K_BATCH: batch["id"], K_ITEM: entry.item}
        if entry.given is not None:
            payload[K_MARK] = entry.given
        if entry.note is not None:
            payload[K_NOTE] = entry.note
        payload[K_BY] = entry.by
        ledger.append_event(MARKED, payload, ts=entry.ts)


def mark(project, batch_id, item_id, given, note=None, by=OWNER, via=None):
    """Record the mark `given` on one item of a batch, with an optional `note`; returns the batch as written.

    The function the `mark` verb (`via` the conversation) and the dashboard's marks view (`via` the
    dashboard) call. A mark saves when given: the first one settles the item, and a later one is
    refused with what settled it, unless the owner gave both in the dashboard and the item's producer
    has not acted on it (`changeable`): then the later one replaces it, the same mark again records
    nothing, and a note alone replaces the note. `given` None with a `note` keeps the note on the
    item and leaves it open. A blank note is no note. The last item settled closes the batch.
    """
    _check_by(by)
    _check_via(via)
    note = None if _blank(note) else note
    if given is None and note is None:
        raise BatchError("nothing to record: give a mark or a note")
    ledger = ledger_for(project)
    with ledger.lock():
        batch = read_batch(ledger, batch_id)
        item = _item(batch, item_id)
        if item["mark"] is not None and not (via == DASHBOARD and by == OWNER and changeable(item)):
            raise BatchError("%s; a later mark or note is refused" % _settled_by(batch, item))
        if given is not None and given not in item["marks"]:
            raise BatchError("item %d of %s (%s) takes %s, got %r" % (item["id"], batch["id"], batch["kind"], ", ".join(item["marks"]), given))
        if given is not None and given == item["mark"]:
            given = None  # the same mark clicked again is no new answer
            if note is None or note == item["note"]:
                return batch
        ts = now_ts()
        if note is not None:
            item["note"] = note
        if given is not None:
            item.update(mark=given, by=by, via=via if by == OWNER else None, at=ts)
            _close_if_settled(batch)
        _save(ledger, batch, [_Marked(item["id"], given, note, by, ts)])
    return batch


def take_defaults(project, batch_id, by=OWNER, via=None):
    """"Take all defaults": settle every open item that has a default with it, in one call.

    Returns `(batch, settled)`: the batch as written and the numbers of the items this call settled.
    An item with no default stays open, and a batch with nothing left to default is left as it was.
    """
    _check_by(by)
    _check_via(via)
    ledger = ledger_for(project)
    with ledger.lock():
        batch = read_batch(ledger, batch_id)
        ts = now_ts()
        journaled = []
        for item in batch["items"]:
            if item["mark"] is None and item["default"] is not None:
                item.update(mark=item["default"], by=by, via=via if by == OWNER else None, at=ts)
                journaled.append(_Marked(item["id"], item["mark"], None, by, ts))
        if journaled:
            _close_if_settled(batch)
            _save(ledger, batch, journaled)
    return batch, [entry.item for entry in journaled]


def acted_on(project, batch_id, item_ids):
    """Say that a batch's producer acted on the marks of `item_ids`: a mark acted on is final, even one the dashboard gave.

    The producer calls it once its act on a mark is done (a merge split, a concern placed, a plot retired), so a later
    click in the marks view cannot change what was already done. An open item, or one stamped already, is left as it is.
    Returns the numbers of the items stamped now; it journals nothing, since the act is journaled by its producer.
    """
    wanted = {int(number) for number in item_ids}
    ledger = ledger_for(project)
    with ledger.lock():
        batch = read_batch(ledger, batch_id)
        stamped, ts = [], now_ts()
        for item in batch["items"]:
            if item["id"] in wanted and item["mark"] is not None and not item.get("acted"):
                item["acted"] = ts
                stamped.append(item["id"])
        if stamped:
            ledger.write_json(_path(batch["id"]), batch, schema=SCHEMA)
    return stamped


def marks(project, batch_id):
    """What a producer reads back: each item's ref, mark, note, and who settled it, in item order."""
    batch = read_batch(project, batch_id)
    return [{"item": item["id"], "ref": item["ref"], "mark": item["mark"], "note": item["note"], "by": item["by"]} for item in batch["items"]]


def read_batches(project, status=None):
    """Every batch the project holds in id order, or only those of one `status` (`open`, `closed`)."""
    ledger = ledger_for(project)
    found = [read_batch(ledger, "B%d" % number) for number in _numbers(ledger)]
    return [batch for batch in found if status is None or batch["status"] == status]


# --- the conversation's rendering -----------------------------------------------------------------


def link(project, batch_id):
    """The batch's item link in the dashboard, `#/<project>/<id>`, naming the project as the dashboard's tabs do."""
    from wayline import dashboard  # late: the dashboard's marks view will read this module

    return "#/%s/%s" % (dashboard.project_id(ledger_for(project).project), batch_id)


def render(project, batch_id):
    """The batch as text for the conversation: whole items at `WHOLE_AT` or fewer, otherwise one line with the count and a link.

    The one rendering the `wayline` skill and the dashboard's chat show, so the two never differ.
    """
    batch = read_batch(project, batch_id)
    items = batch["items"]
    head = "%s %s: %s%s, %d item%s, %s" % (
        batch["id"], batch["kind"], batch["title"], " (decision %d)" % batch["decision"] if batch["decision"] else "",
        len(items), "" if len(items) == 1 else "s", "%d open" % _open_count(batch) if batch["status"] == OPEN else "closed")
    where = link(project, batch["id"])
    if len(items) > WHOLE_AT:
        return "%s, in the marks view: %s" % (head, where)
    lines = [head]
    for item in items:
        if item["mark"] is None:
            state = "%s; %s" % (", ".join(item["marks"]), "default %s" % item["default"] if item["default"] else "no default")
        else:
            state = "settled: %s, by %s%s" % (item["mark"], item["by"], " in the %s" % item["via"] if item.get("via") else "")
        line = "  %d. %s: %s [%s]" % (item["id"], item["ref"], item["text"].strip().replace("\n", "\n     "), state)
        if item["note"]:
            line += " note: %s" % item["note"]
        lines.append(line)
    lines.append("Also in the marks view: %s" % where)
    return "\n".join(lines)


# --- the verb --------------------------------------------------------------------------------------


def _standing(batch):
    return "%s is closed" % batch["id"] if batch["status"] == CLOSED else "%d open" % _open_count(batch)


def _via(by):
    """The verb is the conversation's: an owner's mark through it was given there, the decider's names no place."""
    return CONVERSATION if by == OWNER else None


def mark_command(args):
    """`wayline mark <batch> [<item> [<mark>] [--note "<text>"] | --defaults] [--by owner|decider] [--project <path>]`.

    With the batch alone it prints the batch as the conversation shows it. A mark of several words
    (`not a contradiction`, `take it`) needs no quotes. A refused mark exits 2 with what refused it.
    """
    parser = argparse.ArgumentParser(prog="wayline mark", description="show a batch of the marks view, settle one of its items with a mark, keep a note on one, or take all defaults")
    parser.add_argument("batch", help="the batch, B1 onward")
    parser.add_argument("item", nargs="?", help="the item's number in the batch")
    parser.add_argument("mark", nargs="*", help="the mark, one the batch's kind allows")
    parser.add_argument("--note", help="a note kept on the item, with the mark or alone")
    parser.add_argument("--defaults", action="store_true", help="take all defaults: settle every open item that has one")
    parser.add_argument("--by", choices=WHO, default=OWNER, help="who gives the mark (default: owner)")
    parser.add_argument("--project", help="the project the batch is in; the active one by default")
    options, code = parse_args(parser, args)
    if options is None:
        return code
    given = " ".join(options.mark) or None
    if options.defaults and (options.item is not None or given is not None or options.note is not None):
        print("wayline mark: --defaults takes the batch alone, not an item, a mark, or a note", file=sys.stderr)
        return 2
    if options.item is None and options.note is not None:
        print("wayline mark: a note is kept on an item; name the item", file=sys.stderr)
        return 2
    try:
        project = find_project(options.project)
        if options.defaults:
            batch, settled = take_defaults(project, options.batch, by=options.by, via=_via(options.by))
            print("%d item(s) of %s settled by their defaults; %s" % (len(settled), batch["id"], _standing(batch)))
            return 0
        if options.item is None:
            print(render(project, options.batch))
            return 0
        batch = mark(project, options.batch, options.item, given, note=options.note, by=options.by, via=_via(options.by))
    except BatchError as failure:
        print("wayline mark: %s" % failure, file=sys.stderr)
        return 2
    except (ProjectError, LedgerError, ValidationError, OSError) as failure:
        print("wayline mark: %s" % failure, file=sys.stderr)
        return 1
    item = _item(batch, options.item)
    print("item %d of %s (%s) %s; %s" % (item["id"], batch["id"], item["ref"], "marked %s" % given if given is not None else "noted", _standing(batch)))
    return 0
