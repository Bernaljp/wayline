"""The `python` structural checks of the wayline-intake fixture (research-notes 07 vocabulary).

Each function takes the root a session ran in (the project, or `recorded/` for the recording) and
returns the problems it found; an empty list passes. The section list is pinned here rather than
imported from `wayline.intake`, so a change to the code that drops a section fails the fixture.
"""

import json
from pathlib import Path

from wayline.dossier import intake_references
from wayline.jsonschema import load_schema, validate

SECTIONS = ["Intent", "References", "Data", "Code", "Constraints", "Autonomy", "Radius", "Budgets",
            "Decisions that stay human-only"]


def _sections(root):
    found, current = [], None
    for line in (Path(root) / "research" / "INTAKE.md").read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            current = [line[3:].strip(), []]
            found.append(current)
        elif current is not None:
            current[1].append(line)
    return [(name, "\n".join(body).strip()) for name, body in found]


def intake_has_every_section(root):
    found = _sections(root)
    problems = []
    if [name for name, _ in found] != SECTIONS:
        problems.append("INTAKE.md sections are %s, not %s" % ([name for name, _ in found], SECTIONS))
    problems += ["INTAKE.md section %s is empty" % name for name, body in found if not body]
    return problems


def references_reach_absorb(root):
    """The three references the owner gave, read the way `wayline absorb` reads them, and nothing invented."""
    text = (Path(root) / "research" / "INTAKE.md").read_text(encoding="utf-8")
    found = {(reference.kind, reference.value.lower()) for reference in intake_references(text)}
    wanted = {("arxiv", "1706.03762"), ("doi", "10.1038/s41592-019-0686-2")}
    problems = ["reference %s:%s is missing" % pair for pair in sorted(wanted - found)]
    if not any(kind == "title" and "alphafold" in value for kind, value in found):
        problems.append("the AlphaFold title is missing")
    if len(found) != 3:
        problems.append("INTAKE.md names %d references; the owner gave 3" % len(found))
    return problems


def data_pointer_is_listed(root):
    data = dict(_sections(root)).get("Data", "")
    return [] if "expression.csv" in data else ["the Data section does not point at data/expression.csv"]


def harness_records_the_intake(root):
    harness = json.loads((Path(root) / "harness.json").read_text(encoding="utf-8"))
    problems = ["harness.json %s: %s" % (error.path, error.message) for error in validate(harness, load_schema("harness"))]
    if harness.get("human_only", [])[:2] != ["objective", "data"]:
        problems.append("harness.json human_only is %r; objective and data come first and always" % harness.get("human_only"))
    return problems
