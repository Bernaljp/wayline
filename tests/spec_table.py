"""Read the tables of `.scratch/wayline/spec.md` that the code must agree with.

Three tables are read: the verb table of Implementation Decisions 1, the journal event
vocabulary of Implementation Decisions 2, and the policy table of Implementation Decisions 14.
The tests compare the code's constants against them so the two cannot drift silently.
"""

import re

_BACKTICKED = re.compile(r"`([^`]+)`")
_PARENTHETICAL = re.compile(r"\([^)]*\)")


def _split_row(line):
    """Split a markdown table row on pipes that are not inside backticks."""
    cells, current, in_code = [], [], False
    for char in line:
        if char == "`":
            in_code = not in_code
            current.append(char)
        elif char == "|" and not in_code:
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    cells.append("".join(current).strip())
    if cells and cells[0] == "":
        cells = cells[1:]
    if cells and cells[-1] == "":
        cells = cells[:-1]
    return cells


def table_rows(text, header):
    """The body rows of the first table whose header line is `header`, as lists of cells."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if _split_row(line) == header:
            rows = []
            for row in lines[index + 2:]:
                if not row.strip().startswith("|"):
                    break
                rows.append(_split_row(row))
            return rows
    raise LookupError("table with header %r not found in the spec" % (header,))


def spec_verbs(spec_path):
    """The verb names of the Implementation Decisions 1 command table, in table order."""
    text = spec_path.read_text(encoding="utf-8")
    verbs = []
    for cells in table_rows(text, ["Verb", "Does"]):
        for token in _BACKTICKED.findall(cells[0]):
            verbs.append(token.split()[0])
    return verbs


_LAUNCH_REQUEST = re.compile(r"`LaunchRequest` with `([^`]+)`")
_ENVELOPE = re.compile(r"`Envelope` carries `([^`]+)`")


def spec_seam_fields(spec_path):
    """The `LaunchRequest` and `Envelope` field lists of Implementation Decisions 3, in the spec's order."""
    text = spec_path.read_text(encoding="utf-8")

    def names(pattern):
        match = pattern.search(text)
        if match is None:
            raise LookupError("field list %r not found in the spec" % pattern.pattern)
        return [part.strip() for part in _PARENTHETICAL.sub("", match.group(1)).split(",")]

    return names(_LAUNCH_REQUEST), names(_ENVELOPE)


def spec_journal_vocabulary(spec_path):
    """The journal event vocabulary of Implementation Decisions 2.

    Returns `(events, enums)`: `events` maps every event name to its payload keys in table
    order; `enums` maps `(event, key)` to the values the table enumerates for that key.
    """
    text = spec_path.read_text(encoding="utf-8")
    events, enums = {}, {}
    for cells in table_rows(text, ["Event", "Payload keys"]):
        names = _BACKTICKED.findall(cells[0])
        keys, key_enums, only_for, alternatives = _parse_payload_cell(cells[1])
        if alternatives:
            # "`ticket` or `reason`" in a row naming two events: the first key is the first event's.
            if len(alternatives) != len(names):
                raise ValueError("row %r: %d alternatives for %d events" % (cells[0], len(alternatives), len(names)))
            for name, key in zip(names, alternatives):
                only_for[key] = name
        for name in names:
            events[name] = tuple(key for key in keys if only_for.get(key, name) == name)
            for key, values in key_enums.items():
                if key in events[name]:
                    enums[(name, key)] = tuple(values)
    return events, enums


def _parse_payload_cell(cell):
    cell = _PARENTHETICAL.sub("", cell)
    if cell.strip() == "none":
        return [], {}, {}, []
    keys, key_enums, only_for, alternatives = [], {}, {}, []
    for segment in cell.split(";"):
        adds = re.match(r"\s*`(\w+)` adds `(\w+)`\s*$", segment)
        if adds:
            only_for[adds.group(2)] = adds.group(1)
            keys.append(adds.group(2))
            continue
        head, colon, tail = segment.partition(":")
        either = re.search(r"`(\w+)` or `(\w+)`", head)
        if either:
            alternatives.extend(either.groups())
        head_keys = _BACKTICKED.findall(head)
        keys.extend(head_keys)
        if colon:
            key_enums[head_keys[-1]] = _BACKTICKED.findall(tail)
    return keys, key_enums, only_for, alternatives


def spec_policy_keys(spec_path):
    """The dotted keys of the Implementation Decisions 14 policy table, in table order."""
    text = spec_path.read_text(encoding="utf-8")
    keys = []
    for cells in table_rows(text, ["Key", "Initial value", "Source"]):
        keys.extend(_BACKTICKED.findall(cells[0]))
    return keys
