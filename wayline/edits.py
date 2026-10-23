"""The owner's edit of a rendered file from outside a terminal: `wayline edit` (decision 17; ticket 113).

The dashboard's editor opens a section or the outline (`opened`): the file's text below its render stamp, and the stamp.
Its save (`save`) writes that text back under the stamp it opened, which is exactly what an edit of the file in a
terminal leaves on disk, so the next render takes it in as it would any edit (`sections.take_in`, ticket 88;
`outline.take_in`, ticket 104): new text becomes the owner's passages, changed text the owner's replacement, removed text
a withdrawal, and the outline's moves, placements, and notes its entries, each by the owner. The text is read against the
render the editor opened, so a passage that arrived since is never read as removed.

When code rendered the file again while the editor was open, the stamp on disk is no longer the one the editor carries:
the save is refused with both versions (`EditConflict`), and goes through only when the owner chooses theirs
(`over_newer`). Nothing is overwritten silently.

Only the sections a render takes an edit from, and the outline, are editable. References is written by code from what
the other sections cite, and the reports, the account, and the paper's parts are never edited here. A reason in Methods'
parameter table is not edited through the file: `reason` writes the owner's passage for its row, as `wayline passage add
--parameter` does (ticket 108).
"""

from wayline import outline, sections
from wayline.ledger import ledger_for

__all__ = ["TARGETS", "EditError", "EditConflict", "opened", "save", "reason", "edit_command"]

OUTLINE = "outline"
# The files an edit is taken in from before the next render, in the Paper view's order.
TARGETS = tuple(name for name in sections.SECTIONS if name != sections.REFERENCES) + (OUTLINE,)


class EditError(ValueError):
    """An edit that cannot be saved: a file that is not editable, not rendered yet, or a stamp that is not one."""


class EditConflict(EditError):
    """The file was rendered again since the editor opened it: `current` is the file as it is now, `yours` the save."""

    def __init__(self, target, current, yours):
        super().__init__("%s was rendered again since you opened it: keep yours over the new render, or take the new one"
                         % _title(target))
        self.target, self.current, self.yours = target, current, yours


def _title(target):
    return "The outline" if target == OUTLINE else sections.TITLES.get(target, target)


def _relative(target):
    """The file's path under `research/`, refusing anything not editable."""
    if target == OUTLINE:
        return outline.OUTLINE_MD
    if target in TARGETS:
        return sections.section_path(target)
    why = sections.REFERENCES_BY_CODE if target == sections.REFERENCES else "only %s are" % ", ".join(TARGETS)
    raise EditError("%r is not editable: %s" % (target, why))


def _read(book, target):
    try:
        whole = (book.research / _relative(target)).read_text(encoding="utf-8")
    except FileNotFoundError:
        raise EditError("%s is not rendered yet: there is nothing to edit" % _title(target)) from None
    stamp, _, text = whole.partition("\n")
    if not sections.STAMP_RE.match(stamp):
        raise EditError("%s carries no render stamp, so an edit of it could not be taken in" % _title(target))
    return {"target": target, "path": "research/%s" % _relative(target), "stamp": stamp, "text": text}


def opened(project_or_ledger, target):
    """What the editor opens: `{target, path, stamp, text}`, the file's first-line render stamp and the text below it."""
    book = ledger_for(project_or_ledger)
    _relative(target)
    return _read(book, target)


def save(project_or_ledger, target, text, stamp=None, over_newer=False):
    """Write `text` below `stamp` (the stamp the editor opened; the file's own when None), as a terminal edit would.

    A stamp other than the file's is refused with both versions (`EditConflict`) unless `over_newer`: then the text is
    written under the stamp it was read against, so the next render reads it against what the owner saw.
    """
    book = ledger_for(project_or_ledger)
    relative = _relative(target)
    if not isinstance(text, str):
        raise EditError("the text is a string")
    with book.lock():
        current = _read(book, target)
        stamp = current["stamp"] if stamp is None else stamp
        if not isinstance(stamp, str) or not sections.STAMP_RE.match(stamp):
            raise EditError("the stamp is the file's first line as the editor opened it, a wayline:render comment")
        if stamp != current["stamp"] and not over_newer:
            raise EditConflict(target, current, {"stamp": stamp, "text": text})
        body = text.replace("\r\n", "\n")
        if body and not body.endswith("\n"):
            body += "\n"
        book.write_markdown(relative, "%s\n%s" % (stamp, body))
    return {"target": target, "path": current["path"], "over_newer": stamp != current["stamp"]}


def reason(project_or_ledger, parameter, text):
    """The owner's reason for one row of Methods' parameter table, as `wayline passage add --parameter` writes it."""
    from wayline import methods_inventory  # the inventory reads the sections it renders into
    book = ledger_for(project_or_ledger)
    rows = methods_inventory.read_record(book).get("parameters") or []
    keys = {methods_inventory.parameter_key(row.get("method"), row.get("name"), row.get("path")) for row in rows}
    if parameter not in keys:
        raise EditError("Methods' parameter table holds no row %r" % parameter)
    if not isinstance(text, str) or not text.strip():
        raise EditError("a reason is some words")
    return sections.add_owners_passage(book, "methods", methods_inventory.PARAMETERS, text.strip(), parameter=parameter)


def edit_command(args):
    """`wayline edit <target> [--from <file>|-] [--stamp "<line>"] [--over-newer] | show <target> [--json]`."""
    import argparse
    import json
    import sys
    from wayline.cli import parse_args
    from wayline.ledger import LedgerError
    from wayline.project import ProjectError, find_project

    if args and args[0] == "show":
        parser = argparse.ArgumentParser(prog="wayline edit show", description="print a rendered file as the editor opens it")
        parser.add_argument("target", help="one of %s" % ", ".join(TARGETS))
        parser.add_argument("--json", action="store_true", help="the stamp and the text as JSON")
        parser.add_argument("--project", help="the project; the active one by default")
        options, code = parse_args(parser, args[1:])
        if options is None:
            return code
        try:
            found = opened(find_project(options.project), options.target)
        except EditError as failure:
            print("wayline edit: %s" % failure, file=sys.stderr)
            return 2
        except (ProjectError, LedgerError, OSError) as failure:
            print("wayline edit: %s" % failure, file=sys.stderr)
            return 1
        print(json.dumps(found, ensure_ascii=False) if options.json else found["text"], end="\n" if options.json else "")
        return 0
    parser = argparse.ArgumentParser(prog="wayline edit", description="save the owner's edit of a section or the outline, "
                                     "taken in by the next render as an edit of the file is")
    parser.add_argument("target", help="one of %s" % ", ".join(TARGETS))
    parser.add_argument("--from", dest="source", default="-", help="the edited text (below the stamp); - for stdin")
    parser.add_argument("--stamp", help="the render stamp the text was read under; the file's own by default")
    parser.add_argument("--over-newer", action="store_true", help="save over a newer render, read against the stamp given")
    parser.add_argument("--project", help="the project; the active one by default")
    options, code = parse_args(parser, args)
    if options is None:
        return code
    try:
        if options.source == "-":
            text = sys.stdin.read()
        else:
            with open(options.source, encoding="utf-8") as handle:
                text = handle.read()
        done = save(find_project(options.project), options.target, text, options.stamp, options.over_newer)
    except EditConflict as failure:
        print("wayline edit: %s; --over-newer keeps yours" % failure, file=sys.stderr)
        return 3
    except EditError as failure:
        print("wayline edit: %s" % failure, file=sys.stderr)
        return 2
    except (ProjectError, LedgerError, OSError) as failure:
        print("wayline edit: %s" % failure, file=sys.stderr)
        return 1
    print("%s saved; the next render takes it in" % done["path"])
    return 0
