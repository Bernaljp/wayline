"""The numbers check: a Type-A check at acceptance (Implementation Decision 17; ticket 90).

Every number in a finding must match a value at one of its sentence's `res` locators: the `res` tags the sentence ends
with, or, for a finding with no tag of its own, its provenance, which tags every sentence of it. A number matches a
value when it is the value as rounded to the places it is written with, or the value times 100 (a percent, written
with a percent sign or without) or 1000 (seconds as milliseconds); the sign is not read, since "a drop of 0.3" reports
-0.3. A value is never scaled down to meet a number: at the places a small number is written with, nearly any value
would round to it.

What a number is: digits standing alone, with a decimal point, thousands separators, or an exponent. Counts in words
("three seeds") are words, so they are exempt; so are digits glued to letters or underscores (`R2`, `t3-a1`,
`split_2`, `CIFAR-10`, `2nd`), which name things rather than measure them; and so are the parameters the spec names
(`spec_parameters`: every number in its methods, experiments, baselines, and data).

What a locator holds (`values_at`): in JSON, the value at the key (a dotted or slashed path into nested objects, or a
key holding dots), every number under it; in JSON lines, that key's values across the lines; in CSV or TSV, the
column it names, else the rows holding a cell equal to it; in any other text, the lines `L<a>` or `L<a>-L<b>`, else the
lines that contain it. A locator code cannot resolve holds nothing, so its numbers are unmatched.

Each sentence code cannot match goes to a fresh verifier (`judge`), every such sentence, as a `numbers_match` verdict on
the claim; a failing verdict fails the check and the ticket is sent back with the sentence and the verifier's findings.
A verifier that could not be taken (a usage window, a held Fable window under the consent `wait`, a launch that
failed) lists the sentence in the tail and fails nothing: a closed window is no verdict on the worker's numbers. A verdict
the gate refuses outright fails it, so the refusal is seen; a sentence a verifier already passed is not judged again.

A `res` tag names a run: its file is read only while the manifest still holds that run's file at its path (or it is the
attempt's own run, whose files are in its worktree), and a sentence ending with only `ref`, `code`, or `doc` tags names
no run artifact, so its numbers are not read here.
"""

import csv
import hashlib
import io
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "NUMBERS_CHECK", "SCALES", "Number", "Sentence", "NumbersCheck", "Judged", "numbers_in", "matches", "values_at", "reader",
    "spec_parameters", "check", "judge", "acceptance_result",
]

NUMBERS_CHECK = "wayline numbers check"  # the acceptance result's `cmd`
SCALES = (1, 100, 1000)  # the value as written, as a percent, or in thousandths (seconds as milliseconds)

# Digits that stand alone: not after a letter, digit, underscore, or point, nor after a letter and a hyphen (`CIFAR-10`),
# and not before a letter, digit, or underscore. A thousands-separated form, a decimal, and an exponent are one number.
_NUMBER = re.compile(r"(?<![\w.])(?<![A-Za-z]-)(?P<number>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?(?:[eE][-+]?\d+)?|\.\d+)(?![\w])")
_RES = re.compile(r"\{res:(t[0-9]+-a[0-9]+)/([^{}#]+)#([^{}]+)\}")
_LINES = re.compile(r"^L([1-9][0-9]*)(?:-L?([1-9][0-9]*))?$")


@dataclass(frozen=True)
class Number:
    """One number as a sentence writes it: the text, its value, and the half-unit of its last written place."""

    raw: str
    value: float
    tolerance: float


def numbers_in(text, exempt=()):
    """The numbers of `text` the check reads, its tags taken off; a number equal to one in `exempt` is left out."""
    from wayline.provenance import ANY_TAG_RE  # what a tag is, the linter's own pattern
    found = []
    for match in _NUMBER.finditer(ANY_TAG_RE.sub(" ", str(text or ""))):
        raw = match.group("number")
        plain = raw.replace(",", "")
        try:
            value = float(plain)
        except ValueError:
            continue
        mantissa, _, exponent = plain.lower().partition("e")
        places = len(mantissa.partition(".")[2])
        tolerance = 0.5 * 10 ** (int(exponent or 0) - places)
        if any(math.isclose(value, float(other), rel_tol=1e-12, abs_tol=1e-15) for other in exempt):
            continue
        found.append(Number(raw, value, tolerance))
    return found


def matches(number, values):
    """Whether `number` is one of `values` as rounded, as a percent, or at the scales 100 and 1000 (the module's docstring)."""
    for value in values:
        for scale in SCALES:
            scaled = abs(value * scale)
            if abs(abs(number.value) - scaled) <= number.tolerance + 1e-9 * max(1.0, scaled):
                return True
    return False


# --- what a locator holds ------------------------------------------------------------------------------------------


def _numbers_under(node):
    if isinstance(node, bool) or node is None:
        return []
    if isinstance(node, (int, float)):
        return [float(node)]
    if isinstance(node, str):
        return [number.value for number in numbers_in(node)]
    if isinstance(node, dict):
        return [value for child in node.values() for value in _numbers_under(child)]
    if isinstance(node, list):
        return [value for child in node for value in _numbers_under(child)]
    return []


def _json_at(data, locator):
    """The node at `locator` in parsed JSON: the key itself, else a path through `.` or `/`; None when it is not there."""
    if isinstance(data, dict) and locator in data:
        return data[locator]
    node = data
    for part in [part for part in re.split(r"[./]", locator) if part]:
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        else:
            return None
    return node


def values_at(text, path, locator):
    """Every number `locator` names in the file `path` whose text is `text`; None when the locator names nothing there."""
    suffix = Path(path).suffix.lower()
    locator = str(locator or "").strip()
    if suffix == ".json":
        try:
            node = _json_at(json.loads(text), locator)
        except ValueError:
            return None
        return None if node is None else _numbers_under(node)
    if suffix == ".jsonl":
        found, seen = [], False
        for line in text.splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            node = _json_at(record, locator)
            if node is not None:
                seen = True
                found.extend(_numbers_under(node))
        return found if seen else None
    lines = text.splitlines()
    span = _LINES.match(locator)
    if span:
        start, end = int(span.group(1)), int(span.group(2) or span.group(1))
        if end < start or end > len(lines):
            return None
        return [number.value for line in lines[start - 1:end] for number in numbers_in(line)]
    if suffix in (".csv", ".tsv"):
        rows = list(csv.reader(io.StringIO(text), delimiter="\t" if suffix == ".tsv" else ","))
        if rows and locator in rows[0]:
            column = rows[0].index(locator)
            return [number.value for row in rows[1:] if column < len(row) for number in numbers_in(row[column])]
        held = [row for row in rows if locator in row]
        return [number.value for row in held for cell in row for number in numbers_in(cell)] if held else None
    held = [line for line in lines if locator and locator in line]
    return [number.value for line in held for number in numbers_in(line.replace(locator, " "))] if held else None


def reader(*roots):
    """`path -> text or None`: the file at `path` under the first of `roots` that holds it (a worktree, then the project).

    `read.locate(path)` is that file's absolute path, or None: what the verifier is given, so it opens the file code read.
    """
    def locate(path):
        relative = Path(path)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            return None
        for root in roots:
            if (Path(root) / relative).is_file():
                return Path(root) / relative
        return None

    def read(path):
        found = locate(path)
        try:
            return found.read_text(encoding="utf-8", errors="replace") if found is not None else None
        except OSError:
            return None

    read.locate = locate
    return read


def spec_parameters(project):
    """The numbers the spec names as parameters: every number in `research/spec.json`'s methods, experiments, baselines,
    and data; empty when the project has no spec."""
    try:
        spec = json.loads((Path(project) / "research" / "spec.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    if not isinstance(spec, dict):
        return set()
    return {value for key in ("methods", "experiments", "baselines", "data") for value in _numbers_under(spec.get(key))}


# --- the check ---------------------------------------------------------------------------------------------------------


@dataclass
class Sentence:
    """One sentence of a finding that holds a number: its finding (by its place in the result), its numbers, the ones no
    locator holds, and its locators as `<path>#<locator>`."""

    finding: int
    text: str
    numbers: list
    unmatched: list
    locators: list


@dataclass
class NumbersCheck:
    sentences: list = field(default_factory=list)

    @property
    def unmatched(self):
        return [sentence for sentence in self.sentences if sentence.unmatched]


def _locators(sentence_text, finding, own_tags):
    """A sentence's `res` locators as `(run, path, locator)`: the `res` tags it ends with; for a finding with no tag of its
    own, its provenance (no run named), which tags every sentence of it; none for any other sentence."""
    from wayline.provenance import _cited  # a finding's provenance as a list, however it was written
    tagged = _RES.findall(sentence_text)
    if tagged or own_tags:
        return tagged
    return [(None,) + tuple(str(item).partition("#")[::2]) for item in _cited(finding) if "#" in str(item)]


def check(findings, read, exempt=(), runs=None, own_run=None):
    """The Type-A numbers check over a result's findings: every sentence holding a number, and which numbers match.

    `runs` maps a manifested path to the run whose file it holds now; a `res` tag naming another run (not `own_run`, the
    attempt's own, whose files are in its worktree) is not read, since the file at its path is no longer that run's.
    A sentence of a finding that carries tags of its own and ends with no `res` tag (a reference's number, `ref` tagged)
    names no run artifact, so the check does not read it.
    """
    from wayline.provenance import ANY_TAG_RE, prose_sentences  # the provenance module pulls in the gates
    runs = runs or {}
    locate = getattr(read, "locate", lambda path: None)
    outcome = NumbersCheck()
    for index, finding in enumerate(findings or [], start=1):
        if not isinstance(finding, dict):
            continue
        own_tags = bool(ANY_TAG_RE.search(str(finding.get("text") or "")))
        for sentence in prose_sentences(str(finding.get("text") or "")):
            written = numbers_in(sentence.text, exempt)
            locators = _locators(sentence.text, finding, own_tags)
            if not written or not locators:
                continue
            values, shown = [], []
            for run, path, locator in locators:
                found = locate(path)
                shown.append("%s#%s" % (found if found is not None else path, locator))
                if run is not None and run != own_run and runs.get(path) not in (None, run):
                    continue  # the file at that path is another run's now
                text = read(path)
                held = values_at(text, path, locator) if text is not None else None
                values.extend(held or [])
            outcome.sentences.append(Sentence(index, sentence.text, [number.raw for number in written],
                                              [number.raw for number in written if not matches(number, values)], shown))
    return outcome


# --- the verifier for what code cannot match ----------------------------------------------------------------------------


QUESTION = ("Does every number in this sentence match a value at its cited locators, allowing for rounding, percents, "
            "and the scales 100 and 1000?\n\n> %s\n\nCode could not match: %s.")
SCOPE = ("Only the numbers of this one sentence, and only the locators listed. Open each one and find the value each "
         "number reports, as written or derived plainly from what is there (a difference, a ratio, a count of rows). The "
         "sentence passes when every number is there or follows plainly from what is there; a number nothing there "
         "supports fails it, with a finding at the locator you read. Whether the sentence matters, or is well written, is "
         "not your question.")


@dataclass
class Judged:
    """The verifier's word on each sentence code could not match: `(sentence, passed or None, detail)`."""

    check: NumbersCheck
    judged: list = field(default_factory=list)


def _passed_before(project, ledger):
    """The subjects of every passing `numbers_match` verdict the journal holds."""
    from wayline.gates import NUMBERS_MATCH
    from wayline.ledger import VERDICT, ledger_for
    events, _ = ledger_for(ledger or project).read_events()
    return {(event.get("payload") or {}).get("subject") for event in events if event.get("event") == VERDICT
            and (event.get("payload") or {}).get("verdict_type") == NUMBERS_MATCH and (event.get("payload") or {}).get("pass")}


def judge(project, outcome, *, ticket, author_model, fall_back=None, policy=None, harness_root=None, ledger=None, cwd=None):
    """One fresh verifier per sentence code could not match, each journaled as a `numbers_match` verdict on the claim.

    A sentence of this ticket a verifier already passed, word for word, is not judged again when the acceptance runs
    again. A verdict a usage window, a held Fable window, or a failed launch kept from being taken lists the sentence;
    one the gate refuses outright (a verifier table it cannot read) fails it, so the refusal is seen.
    """
    from wayline import gates, worker
    from wayline.provenance import ProvenanceError, one_line
    options = {"policy": policy, "ledger": ledger, "cwd": cwd}
    if harness_root is not None:
        options["harness_root"] = harness_root
    judged = Judged(outcome)
    passed = _passed_before(project, ledger) if outcome.unmatched else set()
    for sentence in outcome.unmatched:
        digest = hashlib.sha256(sentence.text.encode("utf-8")).hexdigest()[:16]
        subject = "ticket %s#numbers-%s" % (ticket, digest)
        if subject in passed:
            judged.judged.append((sentence, True, "a verifier passed it at an earlier acceptance"))
            continue
        try:
            taken = gates.verdict("claim", subject, QUESTION % (one_line(sentence.text), ", ".join(sentence.unmatched)),
                                  sentence.locators or ["the finding's provenance"], SCOPE, project=project, author_model=author_model,
                                  verdict_type=gates.NUMBERS_MATCH, ticket=ticket, fall_back=fall_back, **options)
        except (gates.FableHeld, gates.UsageLimited, worker.LaunchError, OSError) as failure:
            judged.judged.append((sentence, None, "no verdict could be taken: %s" % failure))
            continue
        except (gates.GateError, ProvenanceError) as failure:
            judged.judged.append((sentence, False, "the verdict was refused: %s" % failure))
            continue
        detail = "; ".join(one_line(item.get("text")) for item in taken.findings or [] if isinstance(item, dict))
        judged.judged.append((sentence, bool(taken.passed), detail))
    return judged


def acceptance_result(judged):
    """The check as one acceptance result: it fails when a verifier failed a sentence, and the tail names each one."""
    failed = [(sentence, detail) for sentence, passed, detail in judged.judged if passed is False]
    lines = ["the numbers of %s sentence(s) did not match their locators and the verifier did not support them:" % len(failed)] if failed else []
    lines += ["- finding %d: %s (unmatched: %s)%s" % (sentence.finding, sentence.text, ", ".join(sentence.unmatched),
                                                     "; the verifier: %s" % detail if detail else "")
              for sentence, detail in failed]
    matched = [sentence for sentence, passed, _ in judged.judged if passed]
    if matched:
        lines.append("matched by the verifier: %s" % "; ".join(sentence.text for sentence in matched))
    waiting = [(sentence, detail) for sentence, passed, detail in judged.judged if passed is None]
    lines += ["listed, not failed: finding %d: %s (%s)" % (sentence.finding, sentence.text, detail) for sentence, detail in waiting]
    if not lines:
        lines.append("every number in a finding matches a value at its res locators" if judged.check.sentences
                     else "no finding holds a number")
    return {"cmd": NUMBERS_CHECK, "exit_code": 1 if failed else 0, "seconds": 0.0, "tail": "\n".join(lines)}
