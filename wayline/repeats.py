"""Repeated claims (Implementation Decision 17; ticket 95).

A claim made in several places of a project's inherited writing is one passage citing every occurrence's `doc` tag and
every work any occurrence cites. Merging never loses content, and contradictions are listed rather than resolved for
the owner.

**At setup** (`check_setup`, `wayline document repeats`), two checks run over the inherited set, the current inherited
claims of every document:

- one **consistency read** (the `consistency-reader` role, `policy.roles`, Opus at high effort, through the launcher)
  reads every claim at once and returns repeat groups and contradictions. A set is read once: it is read again only when
  it holds a claim no read has seen (a newer version's, a new document's); a merged passage is made of claims already read;
- the **embedding net**: the harness's embedding model (BAAI/bge-base-en-v1.5, `wayline tools install embedding-model`,
  ticket 75), run through the tool runner with no tokens, proposes every pair whose cosine is at least
  `policy.repeats.similarity`, the most similar `policy.repeats.max_pairs` of them.

Every pair either proposes and no earlier check labelled goes to the **confirmer** (`confirmer`, Opus), which sees each
sentence with its section and heading and labels the pair `same`, `contradicting`, or `different`; for a pair that is
the same it names the kept text, the fuller occurrence verbatim or one sentence combined from both. A merge stays
automatic, but its kept text must cover every occurrence: a fresh confirmer session, which did not write it, checks that
nothing is lost, and code checks that nothing is added (`additions`: no number, symbol, or citation neither occurrence
has). When either check fails the occurrences stay apart, with no fallback to one of them, and the pair is flagged for
the grill. A merge writes one passage in the place of the first occurrence, `by` its document, naming both in `merges`,
its text the kept text with every `ref` tag of either occurrence and both `doc` tags; the second occurrence is
withdrawn. A pair one of whose claims this check already merged waits for the next check, which sees the merged passage
(a pair the read named is kept in the record's `pending` until then).
Contradicting pairs both stay, listed for the grill (`grill_items`) and for the verification of the result they touch
(`contradictions`). A different pair the confirmer flags is listed for the grill too.

**The record** is `research/repeats.json` (schema `repeats`), written only here through the ledger. The setup's merges
form one `merges` batch of ticket 79 (marks right or split, default right) and its contradictions one `contradictions`
batch (marks real or not a contradiction, default real). `take_marks` acts on them: a split undoes the merge and
restores both passages, which no later check merges again, and a contradiction marked not one leaves the lists and
settles the grill's question on it. The account's render and the setup check take the marks; the grill only reads them.
Each merge standing is listed for the owner in the account under "Changed without asking you" (`account_lines`).

**At each ticket's acceptance** (`check_result`, the conductor's `repeats` result) the embedding net and the same
confirmer run on the ticket's new passages and findings against every current passage: one that repeats a current
passage without naming it in `replaces` sends the worker back with the passage it repeats. Only a ticket's own text is
checked: what the harness writes from inherited passages (a combined merge, a later replacement) is allowed.
"""

import itertools
import json
import re
import sys
import tempfile
from pathlib import Path

from wayline import HARNESS_ROOT, batches, gates, provenance, sections
from wayline.ledger import Ledger, ledger_for, now_ts
from wayline.tools import ToolsError, failure_line, run_recorded, run_tool

__all__ = [
    "RepeatsError", "EMBED_TOOL", "EMBED_SCRIPT", "READER", "CONFIRMER", "RECORD", "REPEATS_CHECK", "plain", "embed",
    "near_pairs", "additions", "read_record", "check_setup", "take_marks", "contradictions", "dismissed", "dismissed_pairs", "grill_items", "account_lines",
    "check_result", "Checked", "repeats_command",
]

EMBED_TOOL = "embedding-model"
EMBED_SCRIPT = HARNESS_ROOT / "converters" / "embed.py"
EMBED_TIMEOUT_S = 600
READER = "consistency-reader"
CONFIRMER = "confirmer"
READ_SCHEMA = "consistency_read"
LABEL_SCHEMA = "repeat_labels"
COVER_SCHEMA = "merge_check"
RECORD_SCHEMA = "repeats"
RECORD = "repeats.json"
REPEATS_CHECK = "repeats"  # the `cmd` of the acceptance result
SIMILARITY = 0.70
MAX_PAIRS = 100

SAME, CONTRADICTING, DIFFERENT = "same", "contradicting", "different"
MERGED, APART, CONTRADICTION, SPLIT, DISMISSED = "merged", "apart", "contradiction", "split", "dismissed"
SPLIT_LATE = "split_late"  # a split marked after a later passage replaced the merged one: nothing restored
FIRST, SECOND, COMBINED = "first", "second", "combined"
RIGHT, SPLIT_MARK = batches.KINDS["merges"]
REAL, NOT_ONE = batches.KINDS["contradictions"]

# What the no-addition check reads in a kept text: numbers, citations, LaTeX commands, and mathematical symbols.
_NUMBER = re.compile(r"(?<![A-Za-z])\d+(?:[.,]\d+)*")
_CITATION = re.compile(r"@[A-Za-z0-9_][A-Za-z0-9_:.#$%&+?<>~/-]*[A-Za-z0-9_]|\{(?:ref|res|code):[^{}]+\}")
_COMMAND = re.compile(r"\\[A-Za-z]+")
_SYMBOLS = set("=<>±×÷≈≠≤≥∝∞∑∏∫√∂∇%°′″‰^_|~") | {chr(code) for code in range(0x391, 0x3CA) if chr(code).isalpha()}


class RepeatsError(ValueError):
    """A check that could not be made: the embedding model is not recorded or failed, or a session answered nothing usable."""


# --- the embedding net ----------------------------------------------------------------------------------


def plain(text):
    """A passage's text as the embedding model and the confirmer read it: its provenance tags taken off, on one line."""
    return " ".join(provenance.ANY_TAG_RE.sub("", str(text or "")).split())


def _tags(text, kind):
    """The provenance tags of one kind a text carries, as written, in order."""
    return ["{%s:%s}" % found for found in provenance.ANY_TAG_RE.findall(str(text or "")) if found[0] == kind]


def embed(texts, run=run_tool, tools=None):
    """One unit vector per text from the harness's embedding model, run once through the tool runner; no tokens."""
    texts = [str(text) for text in texts]
    if not texts:
        return []
    from wayline.tools import Tools

    tools = tools if tools is not None else Tools()
    entry = tools.entry(EMBED_TOOL) or {}
    if not entry.get("path"):
        raise RepeatsError("the embedding model is not recorded in %s (wayline tools install %s)" % (tools.root / "tools.json", EMBED_TOOL))
    with tempfile.TemporaryDirectory(prefix="wayline-embed-") as folder:
        listed = Path(folder) / "texts.json"
        listed.write_text(json.dumps(texts, ensure_ascii=False), encoding="utf-8")
        try:
            done = run_recorded(EMBED_TOOL, [str(EMBED_SCRIPT), entry["path"], str(listed)], tools=tools, run=run, timeout=EMBED_TIMEOUT_S)
        except ToolsError as failure:
            raise RepeatsError(str(failure)) from None
    if done.returncode != 0:
        raise RepeatsError("the embedding model did not run: %s" % failure_line(done))
    try:
        vectors = json.loads(done.stdout.decode("utf-8", errors="replace"))["vectors"]
    except (ValueError, KeyError, TypeError):
        raise RepeatsError("the embedding model printed no vectors") from None
    if not isinstance(vectors, list) or len(vectors) != len(texts):
        raise RepeatsError("the embedding model printed %s vectors for %d texts" % (len(vectors) if isinstance(vectors, list) else "no", len(texts)))
    return vectors


def near_pairs(vectors, threshold, split=None):
    """`[(i, j, similarity)]` for every pair of vectors at or above `threshold`, i < j, the most similar first.

    The vectors are unit length (`embed`), so the cosine is the dot product. With `split`, only the pairs of one vector
    before it and one at or after it are considered: the new texts against the current ones at an acceptance.
    """
    if split is None:
        indices = itertools.combinations(range(len(vectors)), 2)
    else:
        indices = itertools.product(range(split), range(split, len(vectors)))
    found = []
    for first, second in indices:
        similarity = sum(a * b for a, b in zip(vectors[first], vectors[second]))
        if similarity >= threshold:
            found.append((first, second, round(similarity, 4)))
    return sorted(found, key=lambda pair: (-pair[2], pair[0], pair[1]))


def _settings(policy):
    found = (policy or {}).get("repeats") or {}
    return float(found.get("similarity", SIMILARITY)), int(found.get("max_pairs", MAX_PAIRS))


# --- the no-addition check --------------------------------------------------------------------------------


def _marks(text):
    """The numbers, citations, LaTeX commands, and symbols of a text, in order, each once."""
    text = str(text or "")
    found = _CITATION.findall(text) + _NUMBER.findall(_CITATION.sub(" ", text)) + _COMMAND.findall(text)
    found += [char for char in text if char in _SYMBOLS]
    return list(dict.fromkeys(found))


def additions(kept, occurrences):
    """What `kept` has that none of `occurrences` has: a number, a citation, a LaTeX command, or a mathematical symbol."""
    held = set()
    for text in occurrences:
        held.update(_marks(text))
    return [mark for mark in _marks(kept) if mark not in held]


# --- the record -------------------------------------------------------------------------------------------


def read_record(project_or_ledger):
    """`research/repeats.json`, or an empty record when the check never ran."""
    book = ledger_for(project_or_ledger)
    try:
        record = book.read_json(RECORD)
    except FileNotFoundError:
        return {"read": [], "pairs": [], "pending": []}
    except (OSError, ValueError) as failure:
        raise RepeatsError("research/%s cannot be read: %s" % (RECORD, failure)) from None
    from wayline.jsonschema import ValidationError, check, load_schema
    try:
        check(record, load_schema(RECORD_SCHEMA), name="research/%s" % RECORD)
    except ValidationError as failure:
        raise RepeatsError(str(failure)) from None
    record.setdefault("pending", [])
    return record


def _decided(record):
    """The pairs already answered: each labelled pair, and the two passages a split restored, which the owner's mark answers."""
    found = {_key(entry["a"], entry["b"]) for entry in record["pairs"]}
    found |= {_key(*entry["restored"]) for entry in record["pairs"] if len(entry.get("restored") or []) == 2}
    return found


def _save(book, record):
    book.write_json(RECORD, record, schema=RECORD_SCHEMA)


def _key(first, second):
    return frozenset((first, second))


# --- what the check reads -----------------------------------------------------------------------------------


def _number(identifier):
    return int(str(identifier)[1:])


def _current(book):
    """Every current passage of every section and every current finding, by id."""
    found = {}
    for section in sections.SECTIONS:
        for item in sections.arrange(sections.section_items(book, section)).current():
            found[item.get("id")] = dict(item, section=item.get("section") or section)
    return found


def _claims(book):
    """The inherited set: every current inherited claim, in the order the passages were written."""
    current = _current(book)
    claims = [item for item in current.values()
              if sections.is_inherited(item) and item.get("standing") in sections.STANDINGS and not item.get("withdrawn")]
    return sorted(claims, key=lambda item: _number(item["id"]))


def _where(item):
    return 'in %s under the heading "%s"' % (item.get("section"), sections._one_line(item.get("heading")))


# --- the sessions ------------------------------------------------------------------------------------------------


def _session(project, role_name, schema, prompt, policy, harness_root, what, problem=None):
    """One structured session of `role_name`, its answer checked and asked for once more; returns the answer."""
    from wayline import provenance, worker

    role = worker.read_role(role_name, harness_root, project)
    request = provenance.structured_request(project, role, policy, harness_root, prompt, schema, "small",
                                            provenance.session_dir(project, role_name))

    def problem_of(envelope):
        found = provenance.schema_problem(envelope, schema)
        if found is None and problem is not None:
            found = problem(envelope.structured_output)
        return found

    try:
        envelope = provenance._launch_structured(request, problem_of, what)
    except provenance.UsageLimited:
        raise
    except provenance.ProvenanceError as failure:
        raise RepeatsError(str(failure)) from None
    return envelope.structured_output


def _read(project, claims, policy, harness_root):
    """The one consistency read of the inherited set: its groups, each `(kind, ids, why)`, ids it did not list dropped."""
    from wayline import worker

    lines = ["# What you are asked for", "",
             "These are every inherited claim of the project, the sentences of its earlier writing it has not checked yet, by "
             "passage id, each with its section and heading. Return the groups that make the same claim in different places "
             "(`repeat`) and the groups whose claims cannot all hold (`contradiction`), as the schema asks, naming only the ids "
             "listed here.", "", "# The inherited claims", ""]
    lines += ['- %s (%s, under "%s"): %s' % (item["id"], item["section"], sections._one_line(item.get("heading")), plain(item.get("text")))
              for item in claims]
    lines += ["", worker.schema_section("# What you return", READ_SCHEMA)]
    answer = _session(project, READER, READ_SCHEMA, "\n".join(lines) + "\n", policy, harness_root, "consistency read")
    listed = {item["id"] for item in claims}
    groups = []
    for group in answer.get("groups") or []:
        ids = [identifier for identifier in dict.fromkeys(group.get("passages") or []) if identifier in listed]
        if len(ids) >= 2:
            groups.append((group.get("kind"), ids, sections._one_line(group.get("why"))))
    return groups


def _pair_block(heading, number, first, second, kept=None):
    lines = ["## %s %d" % (heading, number), "",
             "First: %s, %s" % (first["id"], _where(first)), "> %s" % plain(first.get("text")), "",
             "Second: %s, %s" % (second["id"], _where(second)), "> %s" % plain(second.get("text"))]
    if kept is not None:
        lines += ["", "Kept:", "> %s" % kept]
    return "\n".join(lines)


def _numbered(answer, key, count):
    """Why an answer's numbers are not each of 1 to `count` once, or None."""
    numbers = [entry.get(key) for entry in (answer or {}).get(key + "s") or []]
    if sorted(numbers) != list(range(1, count + 1)):
        return "answer each of the %d %ss exactly once, numbered as the prompt numbers them; got %s" % (count, key, numbers)
    return None


def _confirm(project, pairs, by_id, policy, harness_root):
    """The confirmer's label for each pair `(a, b)`, as `{key: answer}`."""
    from wayline import worker

    lines = ["# What you are asked for", "",
             "Label each pair of claims below `same`, `contradicting`, or `different`, reading each sentence with the heading "
             "it stands under. For a pair that is the same, name the text one passage would keep: `first` or `second` for "
             "that occurrence verbatim when it says everything the other does, or `combined` with one sentence, in `text`, "
             "that says everything both say and adds no number, symbol, or citation neither has. Set `flag` on a different "
             "pair the owner should see side by side.", ""]
    for number, (first, second) in enumerate(pairs, start=1):
        lines += [_pair_block("Pair", number, by_id[first], by_id[second]), ""]
    lines.append(worker.schema_section("# What you return", LABEL_SCHEMA))
    answer = _session(project, CONFIRMER, LABEL_SCHEMA, "\n".join(lines) + "\n", policy, harness_root, "confirmer",
                      problem=lambda found: _numbered(found, "pair", len(pairs)))
    numbered = {entry["pair"]: entry for entry in answer["pairs"]}
    return {_key(*pair): numbered[number] for number, pair in enumerate(pairs, start=1)}


def _covers(project, merges, by_id, policy, harness_root):
    """The fresh confirmer's no-loss check of each proposed merge `(a, b, kept text)`, as `{key: (covers, lost)}`."""
    from wayline import worker

    lines = ["# What you are asked for", "",
             "Each merge below would replace two occurrences of one claim with the kept text. Say for each whether the kept "
             "text covers everything each occurrence says (`covers`), and if not, what it loses (`lost`), in one sentence. A "
             "merge that loses anything is not made.", ""]
    for number, (first, second, kept) in enumerate(merges, start=1):
        lines += [_pair_block("Merge", number, by_id[first], by_id[second], kept), ""]
    lines.append(worker.schema_section("# What you return", COVER_SCHEMA))
    answer = _session(project, CONFIRMER, COVER_SCHEMA, "\n".join(lines) + "\n", policy, harness_root, "confirmer's no-loss check",
                      problem=lambda found: _numbered(found, "merge", len(merges)))
    numbered = {entry["merge"]: entry for entry in answer["merges"]}
    return {_key(first, second): (bool(numbered[number]["covers"]), numbered[number].get("lost"))
            for number, (first, second, _) in enumerate(merges, start=1)}


# --- the setup check ------------------------------------------------------------------------------------------------


def _entry(first, second, found_by, similarity, answer):
    return {"a": first, "b": second, "found_by": found_by, "similarity": similarity, "label": answer.get("label") or DIFFERENT,
            "outcome": DIFFERENT, "kept": None, "text": None, "passage": None, "why": sections._one_line(answer.get("why")) or None,
            "lost": None, "added": [], "flag": bool(answer.get("flag")), "results": [], "batch": None, "item": None, "at": now_ts()}


def _kept(answer, first, second):
    """The kept text a `same` answer names, without tags, or None when it names none usable."""
    kept = answer.get("kept")
    if kept == FIRST:
        return plain(first.get("text"))
    if kept == SECOND:
        return plain(second.get("text"))
    if kept == COMBINED:
        return plain(answer.get("text")) or None
    return None


def _merged_text(kept, first, second):
    """The kept text with every `ref` tag of either occurrence and every `doc` tag of both, in that order, after it."""
    refs = list(dict.fromkeys(_tags(first.get("text"), "ref") + _tags(second.get("text"), "ref")))
    docs = list(dict.fromkeys(_tags(first.get("text"), "doc") + _tags(second.get("text"), "doc")))
    return kept + "".join(refs) + "".join(docs)


def _write_merge(book, first, second, text):
    """One passage in the place of `first`, by its document, naming both in `merges`; `second` withdrawn. Returns the merge."""
    standings = {first.get("standing"), second.get("standing")}
    standing = sections.UNCHECKED if sections.UNCHECKED in standings else first.get("standing")
    merged = sections.add_passage(book, first["section"], first["heading"], text, by=first["by"], replaces=first["id"],
                                  doc=first.get("doc"), standing=standing,
                                  reason=first.get("reason") if standing == sections.UNVERIFIABLE else None,
                                  merges=[first["id"], second["id"]], render=False)
    sections.add_passage(book, second["section"], second["heading"], str(second.get("text") or ""), by=second["by"],
                         replaces=second["id"], doc=second.get("doc"), withdrawn=True, render=False)
    return merged


def _results(*items):
    return list(dict.fromkeys(sections._one_line(item.get("heading")) for item in items if item.get("section") == sections.RESULTS))


def _item_text(entry, by_id):
    first, second = by_id[entry["a"]], by_id[entry["b"]]
    if entry["outcome"] == MERGED:
        return '%s (%s) and %s (%s) merged into %s, keeping %s: "%s"' % (
            entry["a"], sections.TITLES[first["section"]], entry["b"], sections.TITLES[second["section"]], entry["passage"],
            {FIRST: "the first verbatim", SECOND: "the second verbatim", COMBINED: "a sentence combined from both"}[entry["kept"]],
            entry["text"])
    return '%s (%s): "%s" against %s (%s): "%s"' % (
        entry["a"], sections.TITLES[first["section"]], plain(first.get("text")), entry["b"], sections.TITLES[second["section"]],
        plain(second.get("text")))


def check_setup(project, run=run_tool, tools=None, policy=None, harness_root=None):
    """The setup's repeated-claims check over the inherited set; returns what it did.

    The result is `{read, pairs, merged, apart, contradictions, flagged, waiting, batches, notes}`: whether the consistency
    read ran, how many pairs the confirmer labelled, the merged passages written, and the pairs kept apart, listed as
    contradictions, flagged for the grill, or left for the next check, each as `"Pa+Pb"`; the batches opened; and what
    could not be done (an embedding model that did not run is said, and the read's pairs are still confirmed; a no-loss
    check the usage limit refused leaves its pairs for the next check, and everything else is kept).

    Every pair of a group the read names is proposed. A pair one of whose claims this check merged is kept in the record's
    `pending`, with the merged passage in that claim's place, and proposed by the next check; a pair the owner's split
    restored is answered by the split and never proposed again.
    """
    from wayline.project import policy_for

    project = Path(project).resolve()
    harness_root = Path(harness_root or HARNESS_ROOT)
    policy = policy_for(project, harness_root) if policy is None else policy
    book = Ledger(project)
    report = {"read": False, "pairs": 0, "merged": [], "apart": [], "contradictions": [], "flagged": [], "waiting": [],
              "batches": [], "notes": []}
    report["notes"] += take_marks(project)
    record = read_record(book)
    claims = _claims(book)
    by_id = {item["id"]: item for item in claims}
    if len(claims) < 2:
        return report
    order = {item["id"]: index for index, item in enumerate(claims)}
    decided = _decided(record)
    merged_passages = {entry["passage"] for entry in record["pairs"] if entry.get("passage")}
    candidates = {}

    def propose(first, second, by, similarity=None):
        if first not in by_id or second not in by_id or first == second:
            return
        first, second = sorted((first, second), key=order.get)
        key = _key(first, second)
        if key in decided:
            return
        found = candidates.setdefault(key, {"pair": (first, second), "found_by": [], "similarity": None})
        if by not in found["found_by"]:
            found["found_by"].append(by)
        if similarity is not None:
            found["similarity"] = similarity

    for waiting in record["pending"]:
        for by in waiting["found_by"]:
            propose(waiting["a"], waiting["b"], by)
    read = set()
    if any(item["id"] not in record["read"] and item["id"] not in merged_passages for item in claims):
        for _, ids, _ in _read(project, claims, policy, harness_root):
            for first, second in itertools.combinations(ids, 2):
                propose(first, second, "consistency")
        read = set(by_id)
        report["read"] = True
    threshold, most = _settings(policy)
    try:
        vectors = embed([plain(item.get("text")) for item in claims], run=run, tools=tools)
    except RepeatsError as failure:
        vectors = None
        report["notes"].append("the embedding net proposed nothing: %s" % failure)
    if vectors is not None:
        near = [pair for pair in near_pairs(vectors, threshold) if _key(claims[pair[0]]["id"], claims[pair[1]]["id"]) not in decided]
        if len(near) > most:
            report["notes"].append("the embedding net proposed %d pairs; the %d most similar went to the confirmer" % (len(near), most))
        for first, second, similarity in near[:most]:
            propose(claims[first]["id"], claims[second]["id"], "embedding", similarity)
    pairs = [found["pair"] for found in candidates.values()]
    labels, covers, kept_by = {}, {}, {}
    if pairs:
        labels = _confirm(project, pairs, by_id, policy, harness_root)
        report["pairs"] = len(pairs)
        proposed = []
        for first, second in pairs:
            answer = labels[_key(first, second)]
            if answer.get("label") == SAME:
                kept = _kept(answer, by_id[first], by_id[second])
                if kept is not None:
                    proposed.append((first, second, kept))
        kept_by = {_key(first, second): kept for first, second, kept in proposed}
        try:
            covers = _covers(project, proposed, by_id, policy, harness_root) if proposed else {}
        except (gates.UsageLimited, RepeatsError) as failure:
            covers = None  # the labels are kept; the pairs a merge needs the check for wait for the next check
            report["notes"].append("the no-loss check was not made (%s): the pairs labelled the same wait for the next check" % failure)
    with book.lock():
        record = read_record(book)  # what a mark or another check wrote while this one's sessions ran
        record["read"] = sorted(set(record["read"]) | read, key=_number)
        decided = _decided(record)
        still = _current(book)
        merged_into = {}
        entries = []
        for first, second in pairs:
            key = _key(first, second)
            name = "%s+%s" % (first, second)
            if key in decided:
                continue
            answer = labels[key]
            if first in merged_into or second in merged_into or first not in still or second not in still:
                report["waiting"].append(name)  # a claim of it was merged, or replaced, since: the next check sees what stands
                _pend(record, merged_into.get(first, first), merged_into.get(second, second), candidates[key]["found_by"], still,
                      merged_into)
                continue
            if answer.get("label") == SAME and covers is None and key in kept_by:
                report["waiting"].append(name)
                continue
            found = candidates[key]
            entry = _entry(first, second, found["found_by"], found["similarity"], answer)
            if entry["label"] == SAME:
                _take_same(book, entry, answer, kept_by.get(key), (covers or {}).get(key), by_id)
                if entry["outcome"] == MERGED:
                    merged_into.update({first: entry["passage"], second: entry["passage"]})
                    report["merged"].append(entry["passage"])
                else:
                    report["apart"].append(name)
            elif entry["label"] == CONTRADICTING:
                entry.update(outcome=CONTRADICTION, flag=True, results=_results(by_id[first], by_id[second]))
                report["contradictions"].append(name)
            if entry["flag"]:
                report["flagged"].append(name)
            entries.append(entry)
        record["pairs"].extend(entries)
        answered, standing = _decided(record), _current(book)  # what stands now, the merged passages included
        record["pending"] = [waiting for waiting in record["pending"] if _key(waiting["a"], waiting["b"]) not in answered
                             and waiting["a"] in standing and waiting["b"] in standing]
        report["batches"] = _open_batches(book, entries, by_id)
        _save(book, record)
        touched = {by_id[entry[side]]["section"] for entry in entries if entry["outcome"] == MERGED for side in ("a", "b")}
        if touched:
            sections.render_sections(book, only=sorted(touched))
    return report


def _pend(record, first, second, found_by, still, merged_into):
    """Keep a pair that waits for the merged passage in the record, so the next check proposes it; the read's pairs only.

    The embedding net finds its own pairs again at every check, so only a pair the consistency read named is kept.
    """
    if "consistency" not in found_by or first == second:
        return
    if (first not in still and first not in merged_into.values()) or (second not in still and second not in merged_into.values()):
        return
    first, second = sorted((first, second), key=_number)
    if any(_key(waiting["a"], waiting["b"]) == _key(first, second) for waiting in record["pending"]):
        return
    record["pending"].append({"a": first, "b": second, "found_by": ["consistency"]})


def _take_same(book, entry, answer, kept, covered, by_id):
    """A pair labelled the same: merged when both checks pass, else kept apart and flagged, with why."""
    first, second = by_id[entry["a"]], by_id[entry["b"]]
    entry["kept"] = answer.get("kept")
    if kept is None:
        entry.update(outcome=APART, flag=True, why="kept apart: the confirmer named no kept text it could merge into")
        return
    entry["text"] = kept
    entry["added"] = additions(kept, [plain(first.get("text")), plain(second.get("text"))])
    covers, lost = covered if covered is not None else (False, "the no-loss check did not answer for it")
    reasons = []
    if not covers:
        entry["lost"] = sections._one_line(lost) or "something either occurrence says"
        reasons.append("the confirmer found the kept text loses %s" % entry["lost"].rstrip("."))
    if entry["added"]:
        reasons.append("the kept text adds %s, which neither occurrence has" % ", ".join("`%s`" % mark for mark in entry["added"]))
    if reasons:
        entry.update(outcome=APART, flag=True, why="kept apart: %s" % "; ".join(reasons))
        return
    merged = _write_merge(book, first, second, _merged_text(kept, first, second))
    entry.update(outcome=MERGED, passage=merged["id"])


def _open_batches(book, entries, by_id):
    """The setup's merges and its contradictions, each as one batch; each entry learns its batch and item."""
    opened = []
    for kind, outcome, title, default in (("merges", MERGED, "Merged at setup: right, or split them again", RIGHT),
                                           ("contradictions", CONTRADICTION, "Contradictions in the inherited writing: real, or not one", REAL)):
        chosen = [entry for entry in entries if entry["outcome"] == outcome]
        if not chosen:
            continue
        batch = batches.open_batch(book, kind, title, [{"ref": "%s+%s" % (entry["a"], entry["b"]), "text": _item_text(entry, by_id),
                                                         "default": default} for entry in chosen])
        for number, entry in enumerate(chosen, start=1):
            entry.update(batch=batch["id"], item=number)
        opened.append(batch["id"])
    return opened


# --- the marks ----------------------------------------------------------------------------------------------------


def take_marks(project):
    """Act on the marks given on the merges and contradictions batches; returns a line for each mark that could not be taken.

    A `split` restores both occurrences as they stood and takes the merged passage out; a contradiction marked `not a
    contradiction` leaves the grill's and the verification's lists. `right` and `real` leave things as they are. A split
    marked after a later passage replaced the merged one restores nothing, and is said once.
    """
    book = ledger_for(project)
    problems = []
    with book.lock():
        record = read_record(book)
        changed, touched = False, set()
        for entry, given in _given(book, record, problems):
            if entry["outcome"] == CONTRADICTION and given == NOT_ONE:
                entry.update(outcome=DISMISSED, flag=False)
                changed = True
            elif entry["outcome"] == MERGED and given == SPLIT_MARK:
                changed = True
                problem = _split(book, record, entry, touched)
                if problem is not None:
                    problems.append(problem)
        if changed:
            _save(book, record)
        if touched:
            sections.render_sections(book, only=sorted(touched))
    return problems


def _given(book, record, problems=None):
    """`[(entry, mark)]` for every merge and contradiction still open to a mark, with the mark its item carries, or None."""
    found, marks = [], {}
    for entry in record["pairs"]:
        if not entry.get("batch") or entry["outcome"] not in (MERGED, CONTRADICTION):
            continue
        if entry["batch"] not in marks:
            try:
                marks[entry["batch"]] = {mark["item"]: mark["mark"] for mark in batches.marks(book, entry["batch"])}
            except batches.BatchError as failure:
                marks[entry["batch"]] = {}
                if problems is not None:
                    problems.append("the marks of %s could not be read: %s" % (entry["batch"], failure))
        found.append((entry, marks[entry["batch"]].get(entry["item"])))
    return found


def _split(book, record, entry, touched):
    """Undo one merge: both occurrences written again as they stood, the merged passage replaced by the first.

    The entry is settled first, so a write that fails half-way is never tried again over what it already wrote; the two
    passages restored are recorded as read and as answered by the split, so no later check merges them again.
    """
    passages = {item.get("id"): item for item in sections.read_passages(book)}
    merged = passages.get(entry["passage"])
    if merged is None or merged.get("id") not in sections.current_ids(book, merged["section"]):
        entry.update(outcome=SPLIT_LATE)
        return ("the merge of %s and %s was marked split, but %s was replaced since, so nothing was restored: the later "
                "passage stands" % (entry["a"], entry["b"], entry["passage"]))
    first, second = passages[entry["a"]], passages[entry["b"]]
    withdrawal = next((item for item in passages.values() if item.get("replaces") == second["id"] and item.get("withdrawn")), None)
    entry.update(outcome=SPLIT, restored=[])
    try:
        for original, replaces in ((first, merged["id"]), (second, withdrawal["id"] if withdrawal else None)):
            written = sections.add_passage(book, original["section"], original["heading"], original["text"], by=original["by"],
                                           replaces=replaces, doc=original.get("doc"), standing=original.get("standing"),
                                           reason=original.get("reason"), render=False)
            entry["restored"].append(written["id"])
            touched.add(original["section"])
    except (sections.SectionError, ValueError, OSError) as failure:
        return "the split of %s and %s restored only %s: %s" % (entry["a"], entry["b"], ", ".join(entry["restored"]) or "nothing", failure)
    finally:
        record["read"] = sorted(set(record["read"]) | set(entry["restored"]), key=_number)
    return None


# --- what the grill, the verification, and the account read ---------------------------------------------------------


def contradictions(project, heading=None):
    """The contradictions listed now, each `{a, b, why, results}`; with `heading`, only those touching that Results heading.

    What the verification of an inherited result reads (ticket 97): the contradicting pairs the result's claims are in.
    """
    found = []
    for entry in read_record(project)["pairs"]:
        if entry["outcome"] != CONTRADICTION:
            continue
        if heading is not None and sections._one_line(heading) not in entry["results"]:
            continue
        found.append({"a": entry["a"], "b": entry["b"], "why": entry["why"], "results": list(entry["results"])})
    return found


def _evidence(entry):
    return "research/repeats.json, the pair %s+%s" % (entry["a"], entry["b"])


def dismissed_pairs(project):
    """`{(a, b)}` of every contradiction the owner marked not one, taken or not yet: what the paper order leaves out (ticket 115)."""
    book = ledger_for(project)
    record = read_record(book)
    found = [entry for entry in record["pairs"] if entry["outcome"] == DISMISSED]
    found += [entry for entry, given in _given(book, record) if entry["outcome"] == CONTRADICTION and given == NOT_ONE]
    return {(entry["a"], entry["b"]) for entry in found}


def dismissed(project):
    """The contradictions the owner marked not one, taken or not yet: `[(evidence, why)]`, what settles the grill's question.

    Read only: the marks are read as their batches hold them, and nothing is written.
    """
    book = ledger_for(project)
    record = read_record(book)
    found = [entry for entry in record["pairs"] if entry["outcome"] == DISMISSED]
    found += [entry for entry, given in _given(book, record) if entry["outcome"] == CONTRADICTION and given == NOT_ONE]
    return [(_evidence(entry), "the owner marked it not a contradiction in the marks view (%s, item %s)" % (entry["batch"], entry["item"]))
            for entry in found]


def grill_items(project):
    """What the grill lists: every contradiction standing and every pair flagged, each as one question's spec.

    Each is `{pair, question, options, recommended, evidence}`; a pair the owner already dismissed, by a mark taken or
    not yet taken, is not listed. Read only.
    """
    book = ledger_for(project)
    record = read_record(book)
    passages = {item.get("id"): item for item in sections.read_passages(book)}
    marked = {id(entry) for entry, given in _given(book, record) if given in (NOT_ONE, SPLIT_MARK)}
    items = []
    for entry in record["pairs"]:
        if not entry["flag"] or entry["outcome"] in (DISMISSED, SPLIT, SPLIT_LATE, MERGED) or id(entry) in marked:
            continue
        first, second = passages.get(entry["a"]) or {}, passages.get(entry["b"]) or {}
        said = '%s ("%s") and %s ("%s")' % (entry["a"], plain(first.get("text")), entry["b"], plain(second.get("text")))
        if entry["outcome"] == CONTRADICTION:
            question = "The inherited claims %s contradict each other. Which does the project hold to until verification settles it?" % said
            options = ["the first, %s" % entry["a"], "the second, %s" % entry["b"], "neither until verified"]
            recommended = options[-1]
        else:
            question = "The inherited claims %s were kept apart (%s). Keep them as two passages?" % (
                said, (entry["why"] or "the confirmer flagged them").rstrip("."))
            options = ["keep them apart", "I will rewrite them as one passage"]
            recommended = options[0]
        items.append({"pair": "%s+%s" % (entry["a"], entry["b"]), "question": question, "options": options,
                      "recommended": recommended, "evidence": [_evidence(entry)]})
    return items


# --- at a ticket's acceptance ------------------------------------------------------------------------------------------


class Checked:
    """The acceptance check of one result: the problems that send the worker back, and what was listed, not failed."""

    def __init__(self, problems=(), notes=(), pairs=0, refused=None):
        self.problems, self.notes, self.pairs = list(problems), list(notes), pairs
        self.refused = refused  # the `UsageLimited` a usage window refused the confirmer with: the run pauses on it

    @property
    def passed(self):
        return not self.problems

    def acceptance_result(self):
        """The check as one acceptance result, the shape `gates.run_machine_acceptance` gives a command."""
        lines = list(self.problems) or ["no new passage or finding repeats a current passage without naming it in `replaces`"
                                        + (" (%d pair(s) confirmed different)" % self.pairs if self.pairs else "")]
        lines += ["listed, not failed: %s" % note for note in self.notes]
        return {"cmd": REPEATS_CHECK, "exit_code": 1 if self.problems else 0, "seconds": 0.0, "tail": "\n".join(lines)}


def _new_items(result):
    """A result's own passages and findings, each as an item the confirmer reads: `N1` onward, with section and heading."""
    items = []
    for passage in (result or {}).get("passages") or []:
        if isinstance(passage, dict) and plain(passage.get("text")):
            items.append({"section": passage.get("section"), "heading": passage.get("heading") or sections.TITLES.get(passage.get("section")),
                          "text": passage.get("text"), "replaces": passage.get("replaces"), "what": "passage"})
    for found in (result or {}).get("findings") or []:
        if isinstance(found, dict) and plain(found.get("text")):
            items.append({"section": sections.RESULTS, "heading": found.get("heading") or sections.TITLES[sections.RESULTS],
                          "text": found.get("text"), "replaces": found.get("replaces"), "what": "finding"})
    counted = {}
    for number, item in enumerate(items, start=1):
        counted[item["what"]] = counted.get(item["what"], 0) + 1
        item["id"], item["number"] = "N%d" % number, counted[item["what"]]  # the worker's own count, per passages and findings
    return items


def _lineage(book):
    """`{id: every id it replaced or merged, directly or through what it replaced}` over every passage and finding."""
    parents = {}
    for item in sections.read_passages(book) + sections.read_findings(book):
        parents[item.get("id")] = [item.get("replaces")] + list(item.get("merges") or [])
    lineage = {}

    def walk(identifier, seen):
        for parent in parents.get(identifier) or []:
            if parent and parent not in seen:
                seen.add(parent)
                walk(parent, seen)
        return seen

    for identifier in parents:
        lineage[identifier] = walk(identifier, set())
    return lineage


def check_result(project, result, run=run_tool, tools=None, policy=None, harness_root=None):
    """The repeated-claims check at a ticket's acceptance; a `Checked`, or None for a result with no passage and no finding,
    or a project with no current passage it could repeat.

    The embedding net proposes each pair of a new passage or finding and a current one at `policy.repeats.similarity`
    or above, unless the new one names it (or what it stands in place of) in `replaces`; the confirmer labels them, and
    each pair labelled the same sends the worker back with the passage it repeats. An embedding model that did not run,
    or a confirmer that did not answer, leaves the check listed, not failed: neither is a verdict on the worker's text.
    """
    from wayline import provenance, worker
    from wayline.project import policy_for

    new = _new_items(result)
    if not new:
        return None
    project = Path(project).resolve()
    harness_root = Path(harness_root or HARNESS_ROOT)
    policy = policy_for(project, harness_root) if policy is None else policy
    book = ledger_for(project)
    current = [item for item in _current(book).values() if plain(item.get("text"))]
    if not current:
        return None  # nothing stands that it could repeat
    lineage = _lineage(book)
    threshold, most = _settings(policy)

    def named(item, other):
        replaces = item.get("replaces")
        return bool(replaces) and (other["id"] == replaces or replaces in lineage.get(other["id"], ()))

    try:
        vectors = embed([plain(item.get("text")) for item in new + current], run=run, tools=tools)
    except RepeatsError as failure:
        return Checked(notes=["repeats not checked: %s" % failure])
    count = len(new)
    near = near_pairs(vectors, threshold, split=count)
    pairs = [(new[first], current[second - count]) for first, second, _ in near if not named(new[first], current[second - count])][:most]
    if not pairs:
        return Checked()
    by_id = {item["id"]: item for pair in pairs for item in pair}
    try:
        labels = _confirm(project, [(first["id"], second["id"]) for first, second in pairs], by_id, policy, harness_root)
    except gates.UsageLimited as refused:
        # A closed window, not a verdict on the text: the check fails so the run pauses, and it runs again on the resume.
        return Checked(problems=["the confirmer was refused by the usage limit (%s); nothing here is wrong with the text, and "
                                 "the check runs again once the window opens" % refused], refused=refused)
    except (RepeatsError, provenance.ProvenanceError, worker.LaunchError, OSError) as failure:
        return Checked(notes=["repeats not checked: the confirmer did not answer (%s)" % failure])
    problems = []
    for first, second in pairs:
        if labels[_key(first["id"], second["id"])].get("label") != SAME:
            continue
        problems.append("%s %s (%s, \"%s\"): \"%s\" repeats %s (%s, \"%s\"): \"%s\", without naming it in `replaces`: name %s in "
                        "`replaces` when it says the same thing better, or leave the repeat out" % (
                            first["what"], first["number"], sections.TITLES.get(first["section"], first["section"]),
                            sections._one_line(first["heading"]), plain(first["text"]), second["id"],
                            sections.TITLES.get(second["section"], second["section"]), sections._one_line(second.get("heading")),
                            plain(second.get("text")), second["id"]))
    return Checked(problems, pairs=len(pairs) - len(problems))


def account_lines(project):
    """The account's lines under "Changed without asking you": every merge made at setup that still stands.

    A merge whose item is marked split is left out even before the mark is taken. Read only.
    """
    try:
        book = ledger_for(project)
        record = read_record(book)
        passages = {item.get("id"): item for item in sections.read_passages(book)}
        split = {id(entry) for entry, given in _given(book, record) if given == SPLIT_MARK}
    except (RepeatsError, OSError, ValueError):
        return []
    lines = []
    for entry in record["pairs"]:
        if entry["outcome"] != MERGED or id(entry) in split:
            continue
        first, second = passages.get(entry["a"]) or {}, passages.get(entry["b"]) or {}
        lines.append("- The inherited claims %s (%s) and %s (%s) were merged at setup into %s, keeping %s: \"%s\"%s." % (
            entry["a"], sections.TITLES.get(first.get("section"), first.get("section")), entry["b"],
            sections.TITLES.get(second.get("section"), second.get("section")), entry["passage"],
            {FIRST: "the first verbatim", SECOND: "the second verbatim", COMBINED: "a sentence combined from both"}.get(entry["kept"], "one"),
            entry["text"], "; mark item %d of %s split to undo it" % (entry["item"], entry["batch"]) if entry.get("batch") else ""))
    return lines


# --- the verb ---------------------------------------------------------------------------------------------------------


def _said(report):
    parts = ["%d pair(s) labelled%s" % (report["pairs"], ", after one consistency read" if report["read"] else "")]
    for key, words in (("merged", "merged into"), ("apart", "kept apart"), ("contradictions", "contradicting"),
                       ("flagged", "listed for the grill"), ("waiting", "left for the next check")):
        if report[key]:
            parts.append("%s %s" % (words, ", ".join(report[key])))
    if report["batches"]:
        parts.append("for your marks: %s" % ", ".join(report["batches"]))
    return "; ".join(parts) + "".join("\nnote: %s" % note for note in report["notes"])


def repeats_command(options):
    """`wayline document repeats [--json] [--project <path>]`: the setup's repeated-claims check, run once over the set."""
    from wayline import provenance, worker
    from wayline.project import ProjectError, find_project

    try:
        report = check_setup(find_project(options.project))
    except (RepeatsError, provenance.ProvenanceError, worker.LaunchError, ProjectError, OSError, ValueError) as failure:
        print("wayline document: %s" % failure, file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2) if options.json else _said(report))
    return 0

