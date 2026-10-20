"""A consolidation (Implementation Decision 17; ticket 88): the one rewrite of a section before the paper order.

No model rewrites a section before the order, except a **consolidation**: one read-only writer session the owner asks
for, which replaces a section's current passages with fewer passages that keep their tags. An automated run never
starts one (`wayline consolidate` refuses inside a worker or any other session a run launched), and it is confirmed
first with its cost, since it spends tokens: without `--yes` the verb prints what the session would read and on which
model, and launches nothing.

The session returns the `consolidation` schema: the fewer passages, each naming the current passages it replaces.
Code checks the answer before anything is written: every current passage is replaced by exactly one, there are fewer
of them, each keeps every tag of what it replaces and adds none, and the linter passes it like any passage (a tag that
already failed in the passages it replaces is carried, not held against it, and an untagged claim the owner's own
passage carried is listed, as it was). An answer that fails is sent back once with the problems, and refused if it
still fails. Then each new passage is written `by: consolidation` through the ledger, in the place of the first passage
it replaces, naming in `consolidates` every passage it rewrote (so one made of an owner's passage still steers), the
rest of what it replaces withdrawn, and the whole journaled as `consolidated`. The owner's pending edit of the section
file is taken in before the session reads and again before anything is written; an inherited claim still standing
unchecked or unverifiable is left out, keeping its mark until a passage with this project's evidence replaces it.

Results is not consolidated: it is its findings, which the reports present one result at a time.
"""

import argparse
import json
import os
import sys
from pathlib import Path

from wayline import HARNESS_ROOT, provenance, sections, worker
from wayline.cli import parse_args
from wayline.ledger import CONSOLIDATED, LedgerError, ledger_for
from wayline.project import ProjectError, find_project, policy_for

__all__ = ["SCHEMA", "ROLE", "SECTIONS", "ConsolidationError", "Refused", "estimate", "consolidate", "answer_problems",
           "consolidate_command"]

SCHEMA = "consolidation"
ROLE = "writer"
SECTIONS = sections.WRITTEN  # every section but Results, its findings, and References, which code writes (ticket 105)
# What a session launched by a run carries in its environment: a worker's session directory, or its ticket.
RUN_ENV = ("WAYLINE_RUN", "WAYLINE_TICKET")
CHARS_PER_TOKEN = 4
PROMPT_TOKENS = 1500  # the instructions and the schema, beside the passages
SESSION_DIR = "consolidation"

INSTRUCTIONS = """\
# A consolidation of %(title)s

The owner asked for this section's current passages to be rewritten into fewer, cleaner passages. Return them through
the structured output. The rules:

- Every current passage below is replaced by exactly one of yours: name its id in that passage's `replaces`, the first
  id giving the place your passage takes. Return fewer passages than there are below.
- Keep every provenance tag of the passages yours replaces (`{res:...}`, `{ref:...}`, `{code:...}`, `{doc:...}`), copied
  exactly, each at the end of the claim sentence it supports; add no tag and no claim the passages do not make.
- Keep the owner's passages' meaning: they steer the work. Keep each heading, or merge two under one that names both.
- Markdown with LaTeX math (`$...$`, `$$...$$`), no figures; you read and write nothing else.

# The current passages of %(title)s
"""


class ConsolidationError(ValueError):
    """A consolidation that could not be made: the session's answer failed its checks, or the section changed under it."""


class Refused(ConsolidationError):
    """A consolidation that is not started: inside an automated run, Results, an unknown section, or nothing to consolidate."""


def _current(book, section):
    """The passages a consolidation rewrites: the section's current ones in the outline's order of its headings (ticket
    104), less an inherited claim still standing unchecked or unverifiable, which keeps its mark and waits for a passage
    with this project's evidence."""
    return [item for item in sections.arranged(book, section).current()
            if not (sections.is_inherited(item) and item.get("standing") in sections.STANDINGS)]


def _refusal(section):
    if section == sections.RESULTS:
        return "Results is its findings, which the reports present one result at a time; a consolidation rewrites %s" % (
            ", ".join(sections.TITLES[name] for name in SECTIONS))
    if section not in SECTIONS:
        return "there is no section %r; a consolidation rewrites one of %s" % (section, ", ".join(SECTIONS))
    named = [name for name in RUN_ENV if os.environ.get(name)]
    if named:
        return ("a consolidation is the owner's to ask for, and this process runs inside an automated run (%s is set), which "
                "never starts one" % ", ".join(named))
    return None


def estimate(project, section, harness_root=HARNESS_ROOT, policy=None):
    """What the owner confirms: `{section, passages, chars, tokens, model, effort}` for the one writer session."""
    project = Path(project).resolve()
    book = ledger_for(project)
    current = _current(book, section)
    policy = policy_for(project, harness_root) if policy is None else policy
    entry = ((policy.get("roles") or {}).get(ROLE) or {})
    chars = sum(len(str(item.get("text") or "")) for item in current)
    # It reads the passages once and writes them once, shorter.
    tokens = PROMPT_TOKENS + 2 * chars // CHARS_PER_TOKEN
    return {"section": section, "passages": len(current), "chars": chars, "tokens": tokens,
            "model": entry.get("model"), "effort": entry.get("effort")}


def _prompt(section, current, role, notes=None):
    """The session's prompt: the rules, then the current passages in the outline's order, each heading's note from the
    outline (`notes`, `{heading: note}`) under its first passage, which the consolidation follows as an instruction."""
    lines = [INSTRUCTIONS % {"title": sections.TITLES[section]}]
    noted = set()
    for item in current:
        owner = " (the owner's)" if item.get("by") == sections.OWNER else ""
        lines += ["## %s%s, under %s" % (item.get("id"), owner, item.get("heading")), ""]
        heading = item.get("heading")
        if (notes or {}).get(heading) and heading not in noted:
            noted.add(heading)
            lines += ["The outline's note on this heading: %s" % notes[heading], ""]
        lines += [str(item.get("text") or "").strip(), ""]
    return provenance.joined("\n".join(lines), role.protocol, worker.schema_section("# The answer", SCHEMA))


def _tags(text):
    return ["%s:%s" % found for found in provenance.ANY_TAG_RE.findall(str(text or ""))]


def answer_problems(project, section, current, answer, classify=None):
    """Why the session's `answer` cannot be written, one line each; empty when it can.

    `classify(texts) -> classes` is the sentence classifier the linter reads, the cache's classes when None.
    """
    passages = (answer or {}).get("passages") or []
    by_id = {item.get("id"): item for item in current}
    problems, named = [], []
    for index, passage in enumerate(passages, start=1):
        named.extend(passage.get("replaces") or [])
    unknown = sorted(set(named) - set(by_id), key=named.index)
    if unknown:
        problems.append("`replaces` names %s, which %s does not hold now" % (", ".join(unknown), sections.TITLES[section]))
    twice = sorted({identifier for identifier in named if named.count(identifier) > 1}, key=named.index)
    if twice:
        problems.append("%s replaced by more than one passage: each current passage is replaced by exactly one" % ", ".join(twice))
    missed = [identifier for identifier in by_id if identifier not in named]
    if missed:
        problems.append("%s replaced by none: every current passage is replaced by one of yours" % ", ".join(missed))
    if len(passages) >= len(current):
        problems.append("%d passages for %d current ones: a consolidation returns fewer" % (len(passages), len(current)))
    for index, passage in enumerate(passages, start=1):
        replaced = [by_id[identifier] for identifier in passage.get("replaces") or [] if identifier in by_id]
        kept = set(_tags(passage.get("text")))
        owed = [tag for item in replaced for tag in _tags(item.get("text"))]
        dropped = list(dict.fromkeys(tag for tag in owed if tag not in kept))
        added = [tag for tag in dict.fromkeys(_tags(passage.get("text"))) if tag not in set(owed)]
        if dropped:
            problems.append("passage %d drops the tag(s) %s of what it replaces: keep each, copied exactly"
                            % (index, ", ".join("`{%s}`" % tag for tag in dropped)))
        if added:
            problems.append("passage %d adds the tag(s) %s, which no passage it replaces carries: a consolidation adds no "
                            "provenance" % (index, ", ".join("`{%s}`" % tag for tag in added)))
    if problems:
        return problems
    return _lint_problems(project, current, passages, by_id, classify)


def _lint_problems(project, current, passages, by_id, classify):
    """The linter on the new passages: a failing tag the replaced passages already failed on is carried, not counted."""
    before = provenance.lint_passages(project, current, provenance.read_claims_cache(project))
    carried = {(problem["tag"], problem["problem"]) for problem in before.problems if problem["tag"]}
    # A sentence the passages already said, word for word, is theirs, whatever the linter makes of it now.
    said = {provenance.sentence_hash(sentence.text) for item in current for sentence in provenance.prose_sentences(item.get("text"))}
    items = []
    for index, passage in enumerate(passages, start=1):
        replaced = [by_id[identifier] for identifier in passage["replaces"]]
        # An untagged claim the owner's own passage carried stays listed, as it was: the owner asked for this rewrite.
        owner = any(item.get("by") == sections.OWNER for item in replaced)
        items.append({"id": "passage %d" % index, "by": sections.OWNER if owner else sections.CONSOLIDATION, "text": passage["text"]})
    untagged = [sentence.text for item in items for sentence in provenance.prose_sentences(item["text"])
                if provenance.strip_tags(sentence.text) and not provenance.end_kinds(sentence.text)]
    classes = classify(untagged) if classify is not None and untagged else provenance.read_claims_cache(project)
    linted = provenance.lint_passages(project, items, classes, unclassified_fails=True)
    return ["%s (%s): %s%s; %s" % (problem["problem"], problem["passage"], provenance.one_line(problem["sentence"]),
                                   " tag `%s`" % problem["tag"] if problem["tag"] else "", problem["detail"])
            for problem in linted.problems
            if not ((problem["tag"], problem["problem"]) in carried if problem["tag"] else provenance.sentence_hash(problem["sentence"]) in said)]


def consolidate(project, section, *, harness_root=HARNESS_ROOT, policy=None):
    """Run the one read-only writer session and write what it returns: `{section, replaced, written, model}`.

    Raises Refused before any launch (see `_refusal`, and a section with fewer than two current passages), and
    ConsolidationError when the answer still fails its checks after one resume, or when a passage it replaces was replaced
    while it ran; nothing is written then.
    """
    project = Path(project).resolve()
    refusal = _refusal(section)
    if refusal is not None:
        raise Refused(refusal)
    book = ledger_for(project)
    sections.render_section(book, section)  # the owner's pending edit of the file is taken in before the session reads it
    current = _current(book, section)
    if len(current) < 2:
        raise Refused("%s has %d current passage(s): there is nothing to consolidate" % (sections.TITLES[section], len(current)))
    policy = policy_for(project, harness_root) if policy is None else policy
    role = worker.read_role(ROLE, harness_root, project)
    from wayline import outline  # the outline reads every part of the ledger
    try:
        notes = outline.heading_notes(book, section)
    except (LedgerError, OSError, ValueError):
        notes = {}
    request = provenance.structured_request(project, role, policy, harness_root, _prompt(section, current, role, notes), SCHEMA, "medium",
                                            provenance.session_dir(project, SESSION_DIR), read_only=True)

    def classify(texts):
        return provenance.classify(project, texts, harness_root=harness_root, policy=policy)

    def problem_of(envelope):
        problem = provenance.schema_problem(envelope, SCHEMA)
        if problem is not None:
            return problem
        found = answer_problems(project, section, current, envelope.structured_output, classify)
        return "\n".join("- %s" % line for line in found) if found else None

    try:
        envelope = provenance._launch_structured(request, problem_of, "consolidation")
    except provenance.ProvenanceError as failure:
        raise ConsolidationError(str(failure)) from None
    return _write(book, section, current, envelope.structured_output["passages"], envelope.model or request.model)


def _write(book, section, current, passages, model):
    by_id = {item.get("id"): item for item in current}
    written, replaced = [], []
    with book.lock():
        sections.take_in(book, section)  # an edit the owner made while the session ran is the later word on it
        now = {item.get("id") for item in _current(book, section)}
        gone = [identifier for identifier in by_id if identifier not in now]
        if gone:
            raise ConsolidationError("%s replaced since the consolidation read the section; nothing was written" % ", ".join(gone))
        for passage in passages:
            first, rest = passage["replaces"][0], passage["replaces"][1:]
            written.append(sections.add_passage(book, section, passage["heading"], passage["text"], by=sections.CONSOLIDATION,
                                                replaces=first, consolidates=passage["replaces"], render=False))
            for identifier in rest:
                item = by_id[identifier]
                sections.add_passage(book, section, item.get("heading"), str(item.get("text") or ""), by=sections.CONSOLIDATION,
                                     replaces=identifier, withdrawn=True, render=False)
            replaced.extend(passage["replaces"])
        order = [item.get("id") for item in current]
        outcome = {"section": section, "replaced": sorted(replaced, key=order.index), "written": [item["id"] for item in written],
                   "model": model}
        book.append_event(CONSOLIDATED, outcome)
        sections.render_section(book, section)
    return outcome


def consolidate_command(args):
    """`wayline consolidate <section> [--yes] [--json] [--project <path>]`: the owner's ask, confirmed with its cost."""
    parser = argparse.ArgumentParser(prog="wayline consolidate", description="rewrite one section's current passages into fewer "
                                     "that keep their tags, in one read-only writer session the owner asks for")
    parser.add_argument("section", help="one of %s" % ", ".join(SECTIONS))
    parser.add_argument("--yes", action="store_true", help="the owner's confirmation of the cost; without it nothing is launched")
    parser.add_argument("--project", help="the project; the active one by default")
    parser.add_argument("--json", action="store_true", help="print the outcome as JSON")
    options, code = parse_args(parser, args)
    if options is None:
        return code
    try:
        project = find_project(options.project)
        refusal = _refusal(options.section)
        if refusal is not None:
            raise Refused(refusal)
        if not options.yes:
            cost = estimate(project, options.section)
            if options.json:
                print(json.dumps(dict(cost, confirmed=False), indent=2))
            else:
                print("A consolidation of %s reads its %d current passages (%d characters) in one read-only writer session "
                      "on %s %s: about %s tokens. Nothing was launched; run `wayline consolidate %s --yes` to confirm."
                      % (sections.TITLES[options.section], cost["passages"], cost["chars"], cost["model"], cost["effort"],
                         "{:,}".format(cost["tokens"]), options.section))
            return 0
        outcome = consolidate(project, options.section)
    except Refused as failure:
        print("wayline consolidate: %s" % failure, file=sys.stderr)
        return 2
    except (ConsolidationError, ProjectError, LedgerError, worker.LaunchError, OSError) as failure:
        print("wayline consolidate: %s" % failure, file=sys.stderr)
        return 1
    if options.json:
        print(json.dumps(outcome, indent=2))
    else:
        print("%s consolidated: %s replaced by %s, by: consolidation, on %s" % (
            sections.TITLES[outcome["section"]], ", ".join(outcome["replaced"]), ", ".join(outcome["written"]), outcome["model"]))
    return 0
