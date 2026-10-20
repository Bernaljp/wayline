"""The decider (Implementation Decisions 10, 4, and 5; BRIEF 6.2). Built by ticket 31.

After the autonomy switch, a max-effort session on the `decider` role resolves what the owner left
open: every open question of the grill's design tree, every decision ticket not marked human-only,
and, at the end of each wave, every parked proposal. One session per decision, launched through the
worker launcher (seam 1) on `policy.roles.decider` (`opus`, `max`), with `decision.json` as its
schema and, in its prompt, `DECISIONS.md`, `POSITION.md`, `OBJECTIVES.md`, the L0 and L1 records, and
the query pack, with the project's radius, which bounds the objectives it may add (decision 17; ticket 80:
`proposals.apply_admitted` already trusted it to have weighed the radius). Every decision it makes is written with rationale, confidence, and
`decided-by: decider`, the model it ran on, and its session, so the owner can audit and reverse any
of them in the morning: a grill question through `wayline grill answer <id> ... --revise`, a decision
ticket through `wayline rerun <id>`.

**The line it never crosses.** Nothing on the irreversible list of decision 4 is the decider's:
deleting or overwriting data, pushing, exceeding or raising a budget, spending money, changing a
goal's measure or the data, changing the harness globally, and any network write; nor a question the grill
marked human-only or irreversible, which `grill.with_answer` refuses it outright. The session is
told the line and hands such a decision back with `answer: null`; and code checks every answer it
does give against the list (`irreversible_class`), because the session's own reading is not the
guard, and reads the option's words when the answer only points at one (`chosen_option`). A refused
answer turns the decision into a human-only one: a grill question is marked `human_only` in
`DECISIONS.md` and a human-only decision ticket is opened for it (origin `grill <id>`), so the owner
sees it in the dashboard and the report and answers it there or in the grill, either of which
settles the question and the ticket; a decision ticket becomes human-only in its own file; a parked
proposal becomes a human-only decision ticket asking whether it is admitted (origin `proposal <id>`).
A decision ticket the decider did answer lands in its `## Answer`, in the journal, and as a record
appended to `DECISIONS.md`, so that file holds every decision the decider made about the design.

**The paper's venue.** `wayline paper` without `--venue` asks it once for the venue that fits best
(`decide_venue`, ticket 53): the options are the slugs of `guidelines/`, the evidence a line of each
venue's limits, and the pick is journaled as a `decision` with no ticket, `paper venue: <slug>`. The
owner asked for the paper and is at the command, so a refusal opens no decision ticket: it stops
the command, which says so.

**Where it is launched from.** `wayline grill --decide-rest` (`decide_rest`) resolves the design
tree's frontier one question at a time until only the owner's questions are left; the conductor
(`decide_ticket`, `decide_proposal`) launches it for open decision tickets in wave step 5 and for
parked proposals at the end of the wave, under the pacing and the hold on Fable's weekly window
like any model work. While Fable's window is spent the decider falls back to Opus at the same effort
as decision 15 says (`decider_tier`), and the decision records `fallback_from: fable`.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from wayline import HARNESS_ROOT, decisions, gates, grill, pacing, worker
from wayline.jsonschema import ValidationError, check, load_schema
from wayline.ledger import DECISION, Ledger
from wayline.provenance import VENUE_PREFIX
from wayline.objectives import OBJECTIVES_MD
from wayline.project import DEFAULT_HUMAN_ONLY, OBJECTIVE_CLASS, ProjectError, human_only_classes_now, policy_for, read_harness
from wayline.tickets import DECISION as DECISION_KIND, TicketError, read_tickets

__all__ = [
    "DECIDER", "DECISION_SCHEMA", "IRREVERSIBLE", "DeciderError", "Subject", "Outcome", "decider_tier", "decides_on_fable",
    "irreversible_class", "chosen_option", "refusal", "records_text", "decider_prompt", "take_decision", "decide_question",
    "decide_ticket", "decide_proposal", "proposal_origin", "VENUE_ANSWER", "venue_of", "decide_venue", "reconsidered", "decide_rest", "render_decided",
    "FRONTIER_SUBJECT", "frontier_answers", "decide_frontier",
]

DECIDER = "decider"
DECISION_SCHEMA = "decision"
SESSIONS = "decider"            # <project>/research/sessions/decider/<subject>/<n>
DECIDER_BUDGET = "medium"       # policy.budget: the turns and minutes one decision may take; a read-only session needs no more
PROPOSAL_ANSWER = "proposal %s: %s"  # the `decision` a parked proposal gets, its id leading the answer, as a grill question's id does
VENUE_ANSWER = VENUE_PREFIX + "%s"  # the `decision` the paper's venue gets (ticket 53): the prefix the report reads, then the slug
ADMIT, KEEP_PARKED = "admit", "keep parked"
RESUME_DECISION = (
    "The decision you returned could not be recorded: %s. Return it again through the structured output, "
    "as the decision schema asks, and change nothing else about it."
)
# The room the prompt keeps under the context cap for everything that is not a record: the question, the protocol, the schema.
PROMPT_ROOM = 20000
# The least the records get however small the cap: DECISIONS.md whole, at the very least, since it binds the answer.
RECORDS_MIN = 20000
# What each radius lets the decider add (decision 17): the objectives it adds or reframes, once the owner took the
# class `objective` off the human-only list, and the follow-up work it admits (intake.RADIUS says the latter for
# INTAKE.md; this is the decider's reading of both). Reopening a parked objective is allowed at every radius.
RADIUS_BOUNDS = {
    "strict": "`strict`: no objective added, and only work that traces to a spec claim",
    "moderate": "`moderate`: a prerequisite, or a narrowing reframe, that an open objective's own work raises, and "
                "follow-ups that directly probe a claim's failure",
    "exploratory": "`exploratory`: also one new question within the intent per wave, and new directions gated on a novelty check",
}

# The irreversible list of decision 4, as classes a code check reads off an answer's words. Each pattern
# names a change verb with its object, so an answer that keeps the goal, reads the data, or fetches a source
# is not caught by the noun alone; the session is told the list too, and the two readings are both refusals.
IRREVERSIBLE = (
    ("delete or overwrite data",
     r"\b(delet(?:e|es|ing)|eras(?:e|es|ing)|wip(?:e|es|ing)|purg(?:e|es|ing)|overwrit(?:e|es|ing|ten)|truncat(?:e|es|ing)"
     r"|rm -r\w*|git clean|drop(?:s|ping)? (?:the |every |all )?(?:table|column|row|data|result|file|checkpoint)s?"
     r"|discard(?:s|ing)? (?:the |every |all )?(?:result|data|file|checkpoint|run)s?)\b"),
    ("push",
     r"\b(force[- ]push(?:es|ed|ing)?|git push|push(?:es|ed|ing)? (?:it |them |the \w+ )?(?:to |onto )?(?:main|master|origin|upstream|the remote|a shared branch)"
     r"|publish(?:es|ed|ing)? (?:the |a )?(?:branch|release|package|tag))\b"),
    # Decision 17: code pushes the code repository's split to its private remote, but making it public, or any other
    # change to its visibility, is the owner's word only (ticket 85).
    ("make the code repository public",
     r"\b((?:mak(?:e|es|ing)|turn(?:s|ing)?|set(?:s|ting)?|flip(?:s|ping)?) (?:the |our |its )?(?:github |code |project's )?"
     r"(?:repositor(?:y|ies)|repos?|code/?|package)(?:'s)? public"
     r"|(?:mak(?:e|es|ing)|turn(?:s|ing)?|set(?:s|ting)?) (?:it|them) public"
     r"|publish(?:es|ed|ing)? (?:the |our |its )?code repositor(?:y|ies)"
     r"|open[- ]sourc(?:e|es|ed|ing) (?:the |our |its )?(?:code|repositor(?:y|ies)|repos?|package|method)"
     r"|gh repo edit\b[^\n]*--visibility"
     r"|(?:chang(?:e|es|ing)|set(?:s|ting)?|flip(?:s|ping)?|switch(?:es|ing)?) (?:the |our |its )?(?:github |code )?(?:repositor(?:y|ies)|repos?)(?:'s)? visibility)"),
    ("budgets",
     r"\b(exceed(?:s|ed|ing)? (?:the |its |our )?(?:[\w-]+ )?(?:budget|allowance|quota|cap)"
     r"|(?:rais(?:e|es|ing)|increas(?:e|es|ing)|doubl(?:e|es|ing)|extend(?:s|ing)?|lift(?:s|ing)?|remov(?:e|es|ing)) (?:the |its |our )?(?:[\w-]+ )?(?:budget|cap|allowance|quota|usage window)"
     r"|more (?:gpu|cpu|compute|wall[- ]?clock) (?:hours|time) than|over (?:the |its |our )?budget|beyond (?:the |its |our )?budget)\b"),
    # Decision 17 (ticket 87): after setup, the stopping rule is the owner's to change, as a budget is theirs to raise.
    ("stopping rule",
     r"\b(switch --stop-when|stop_when"
     r"|(?:chang(?:e|es|ing)|replac(?:e|es|ing)|relax(?:es|ing)?|loosen(?:s|ing)?|redefin(?:e|es|ing)|rewrit(?:e|es|ing)|set(?:s|ting)?"
     r"|mov(?:e|es|ing)|switch(?:es|ing)?|extend(?:s|ing)?|drop(?:s|ping)?|remov(?:e|es|ing)|lift(?:s|ing)?)"
     r" (?:the |its |our |a |an )?(?:new )?stop(?:ping)? (?:rule|condition|criteri(?:on|a)))\b"),
    ("spending",
     r"\b(spend(?:s|ing)? (?:money|dollars|credits)|pay(?:s|ing)? for|purchas(?:e|es|ing)"
     r"|buy(?:s|ing)? (?:a |an |the |more )?(?:credits?|licen[cs]es?|subscriptions?|gpus?|instances?|api keys?|compute|time)"
     r"|paid (?:tier|plan|api|account)|credit card|rent(?:s|ing)? (?:a |an |the |more )?(?:gpus?|instances?|servers?|machines?)"
     r"|cloud (?:instances?|credits))\b"),
    ("goal",
     r"\b((?:chang(?:e|es|ing)|replac(?:e|es|ing)|redefin(?:e|es|ing)|relax(?:es|ing)?|lower(?:s|ing)?|rais(?:e|es|ing)|drop(?:s|ping)?"
     r"|swap(?:s|ping)?|revis(?:e|es|ing)|rewrit(?:e|es|ing)|switch(?:es|ing)?|set(?:s|ting)?|mov(?:e|es|ing)|loosen(?:s|ing)?|tighten(?:s|ing)?)"
     r" (?:the |our |its |a |an )?(?:new )?(?:goal|target|success criteri(?:on|a)|primary metric|goal metric|eval(?:uation)? command)"
     r"|the goal becomes|a new goal|a new target)\b"),
    ("data",
     r"\b((?:chang(?:e|es|ing)|replac(?:e|es|ing)|swap(?:s|ping)?|drop(?:s|ping)?|re-?split(?:s|ting)?|redefin(?:e|es|ing)|regenerat(?:e|es|ing)"
     r"|augment(?:s|ing)?|relabel(?:s|l?ing)?|mov(?:e|es|ing)|switch(?:es|ing)?|shrink(?:s|ing)?|subsampl(?:e|es|ing)|filter(?:s|ing)?|clean(?:s|ing)?)"
     r" (?:the |our |its |to (?:a |an )?)?(?:new |different |another )?(?:data(?:set)?|training (?:set|data)|test (?:set|data)|held[- ]out (?:set|split|data)|hold[- ]out (?:set|split)|split_[a-z0-9]+|splits?)"
     r"|hold(?:s|ing)? out (?:a |the |another )?(?:different|new)|leav(?:e|es|ing) the machine|off the machine"
     r"|export(?:s|ing)? (?:the |any |our )?data|shar(?:e|es|ing) (?:the |any |our )?data|upload(?:s|ing)? (?:the |any |our )?data)\b"),
    ("global harness change",
     r"\b((?:edit(?:s|ing)?|chang(?:e|es|ing)|modif(?:y|ies|ying)|patch(?:es|ing)?|rewrit(?:e|es|ing)|updat(?:e|es|ing)|bump(?:s|ing)?|promot(?:e|es|ing))"
     r" (?:the |a |an )?(?:global |harness |shipped )?(?:harness|policy\.json|global policy|~/\.wayline|wayline itself|wayline's (?:code|policy|roles?|skills?|hooks?)|shipped (?:roles?|skills?|policy))"
     r"|harness[- ]wide|in the harness itself|for every project)\b"),
    # Decision 17: moving a project between the shared tools, a conda prefix, a venv, and a container is the owner's word
    # alone; no decision class names it, and an answer that would move it is refused (ticket 83).
    ("environment",
     r"\b(switch --environment"
     r"|(?:mov(?:e|es|ing)|switch(?:es|ing)?|chang(?:e|es|ing)|set(?:s|ting)?|migrat(?:e|es|ing)|rebuild(?:s|ing)?|run(?:s|ning)?|put(?:s|ting)?)"
     r" (?:the |our |its |this )?(?:project(?:'s)? |it |everything |(?:the )?jobs? |(?:project's |run's )?environment )?"
     r"(?:to|into|in|inside|as) (?:a |an |the )?"
     r"(?:conda\b|venv|virtual ?env(?:ironment)?|container|singularity|docker (?:image|container)|shared(?: tools| environment)?\b))"),
    ("network write",
     r"\b(upload(?:s|ed|ing)?|post(?:s|ed|ing)? (?:it |them |the \w+ )?to|submit(?:s|ted|ting)? (?:it |them |the \w+ )?to"
     r"|send(?:s|ing)? (?:it |them |the \w+ )?to (?:a |the |an )?(?:server|api|service|endpoint|slack|telegram|e-?mail|webhook|channel)"
     r"|curl -x post|curl -d|curl --data|wget --post|webhook"
     r"|publish(?:es|ed|ing)? (?:to|on) (?:the )?(?:web|internet|github|pypi|hugging ?face|zenodo|arxiv|osf)"
     r"|push(?:es|ed|ing)? to (?:hugging ?face|pypi|docker ?hub|a registry))\b"),
)
_PATTERNS = tuple((name, re.compile(pattern, re.IGNORECASE)) for name, pattern in IRREVERSIBLE)


class DeciderError(ValueError):
    """A decision nobody could take: a role that cannot be read, a session that returned no usable record."""


@dataclass
class Subject:
    """One decision the decider is asked for: a grill question, a decision ticket, a parked proposal, or the paper's venue."""

    kind: str                      # question | ticket | proposal | venue | frontier
    key: str                       # Q8 | 2 | the proposal's id
    question: str
    options: list = field(default_factory=list)
    recommended: Optional[str] = None
    evidence: list = field(default_factory=list)
    requires: list = field(default_factory=list)   # (id, question, answer) of the settled prerequisites
    reversible: bool = True
    slug: str = ""                 # the session directory's name under research/sessions/decider/

    @property
    def name(self):
        return {"question": "the grill's %s", "ticket": "decision ticket %s", "proposal": "parked proposal %s",
                "venue": "the venue of the %s", "frontier": "%s"}[self.kind] % self.key

    @classmethod
    def from_record(cls, record, records=()):
        """A grill question from its `DECISIONS.md` record, with its prerequisites' answers pulled from `records`."""
        questions = {other["id"]: other for other in records if other.get("id")}
        requires = [(need, questions[need]["question"], questions[need].get("answer"))
                    for need in record.get("requires") or [] if need in questions]
        return cls(kind="question", key=record["id"], question=record["question"], options=list(record.get("options") or []),
                   recommended=record.get("recommended"), evidence=list(record.get("evidence") or []), requires=requires,
                   reversible=record.get("reversible", True) is not False, slug=record["id"].lower())

    @classmethod
    def from_ticket(cls, fields, body, record=None):
        """A decision ticket from its file: the record when the body carries one, else its `## Decision` text."""
        record = record or {}
        return cls(kind="ticket", key=str(fields["id"]), question=decisions.decision_question(fields, body),
                   options=list(record.get("options") or []), recommended=record.get("recommended"),
                   evidence=list(record.get("evidence") or []) + (["asked by: %s" % fields["origin"]] if fields.get("origin") else []),
                   reversible=record.get("reversible", True) is not False, slug="ticket-%d" % fields["id"])

    @classmethod
    def from_proposal(cls, proposal):
        """A parked proposal, asked as the admission question the rules could not answer (decision 5)."""
        identifier = str(proposal.get("id"))
        evidence = ["parked because: %s" % proposal.get("reason", "no reason recorded")]
        for key in ("kind", "proposed_by", "origin", "blocked_by", "touches", "demo"):
            if proposal.get(key):
                evidence.append("%s: %s" % (key, proposal[key] if isinstance(proposal[key], str) else json.dumps(proposal[key])))
        if proposal.get("path"):
            evidence.append("the proposal as parked: %s" % proposal["path"])
        return cls(kind="proposal", key=identifier,
                   question="Is the parked proposal %s, \"%s\", admitted to the run?" % (identifier, proposal.get("title")),
                   options=[ADMIT, KEEP_PARKED], recommended=KEEP_PARKED, evidence=evidence,
                   slug="proposal-" + re.sub(r"[^a-z0-9]+", "-", identifier.lower()).strip("-"))


@dataclass
class Outcome:
    """What one launch of the decider came to, for the caller's report and the wave's count."""

    subject: Subject
    status: str                    # decided | refused | failed
    answer: Optional[str] = None
    rationale: Optional[str] = None
    confidence: Optional[float] = None
    model: Optional[str] = None
    fallback_from: Optional[str] = None
    session_id: Optional[str] = None
    why: Optional[str] = None      # the refusal, or the failure
    ticket: Optional[int] = None   # the human-only decision ticket a refusal opened or turned over

    @property
    def line(self):
        """One line for the console and the report of `--decide-rest`."""
        if self.status == "decided":
            return "%s  decided: %s (confidence %s, on %s%s)" % (
                self.subject.name, self.answer, "not stated" if self.confidence is None else "%g" % self.confidence,
                self.model or "an unnamed model", " in place of %s" % self.fallback_from if self.fallback_from else "")
        if self.status == "refused":
            return "%s  refused, and turned over to the owner%s: %s" % (
                self.subject.name, " as decision ticket %d" % self.ticket if self.ticket else "", self.why)
        return "%s  not decided: %s" % (self.subject.name, self.why)


# --- the tier and the line ------------------------------------------------------------------------


def decider_tier(policy, fall_back=False):
    """The `(model, effort, fallback_from)` the decider runs at: `policy.roles.decider`, Opus in Fable's place when `fall_back`."""
    entry = ((policy or {}).get("roles") or {}).get(DECIDER) or {}
    model, effort = entry.get("model"), entry.get("effort")
    if model not in worker.MODEL_ALIASES or effort not in worker.EFFORTS:
        raise DeciderError("policy.roles.decider names no model and effort the launcher knows; got %r" % (entry,))
    if model == pacing.FABLE and fall_back:
        return pacing.OPUS, effort, pacing.FABLE
    return model, effort, None


def decides_on_fable(policy):
    """Whether the decider's tier is Fable, so the hold on Fable's weekly window holds it (decision 15)."""
    try:
        return decider_tier(policy)[0] == pacing.FABLE
    except DeciderError:
        return False


def _falls_back_now(project, policy, fall_back, what):
    """Whether this launch falls back now: the caller's word, else the journal's, and only for a decider on Fable."""
    if fall_back is not None:
        return bool(fall_back)
    if not decides_on_fable(policy):
        return False
    return gates.fallback_now(project, what)


def irreversible_class(answer, question=""):
    """The class of the irreversible list an answer falls in, or None: the code check of decision 4.

    The answer's own words are read first; the question's are read with them only for the goal and the
    data, whose change is often named in the question and taken with a bare option in the answer.
    """
    text = " ".join(str(answer or "").split())
    if not text:
        return None
    for name, pattern in _PATTERNS:
        if pattern.search(text):
            return name
    both = " ".join(str(question or "").split()) + " " + text
    for name, pattern in _PATTERNS:
        if name in ("goal", "data") and pattern.search(both) and _bare_choice(text):
            return name
    return None


def _bare_choice(text):
    """An answer that only picks (`yes`, `the second`, `raise it`) and so means what the question says."""
    return len(text.split()) <= 3


_ORDINALS = ("first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth")
_INDEXICAL = re.compile(r"^(?:the )?(?:option |choice |number |no\. ?)?(?:(\d+)|(%s))(?: option| one| choice)?\.?$"
                        % "|".join(_ORDINALS), re.IGNORECASE)


def chosen_option(answer, options):
    """The option an indexical answer picks (`option 2`, `the second`, `2`), or the answer as given.

    The code check reads the words of what was decided: an answer that only points at an option
    means that option's words, and those are what the check has to see.
    """
    text = " ".join(str(answer or "").split())
    found = _INDEXICAL.match(text)
    if found is None or not options:
        return text
    index = int(found.group(1)) if found.group(1) else _ORDINALS.index(found.group(2).lower()) + 1
    return " ".join(str(options[index - 1]).split()) if 1 <= index <= len(options) else text


def refusal(subject, returned):
    """Why a returned decision is not the decider's to make, or None when it is.

    Three readings refuse it: the session's own (`answer` null, `reversible` false, or `human_only` true),
    the code check on the answer's class (on the option's words when the answer only points at one), and a
    subject the grill marked irreversible, which never reaches a launch but is refused here too in case a
    record was edited by hand.
    """
    answer = returned.get("answer")
    rationale = (returned.get("rationale") or "").strip()
    if not subject.reversible:
        return "the question is irreversible, so it is the owner's"
    if returned.get("human_only") is True:
        return "the decider read it as a human-only class%s" % (": " + rationale if rationale else "")
    if returned.get("reversible") is False:
        return "the decider read its answer as one that cannot be taken back%s" % (": " + rationale if rationale else "")
    if answer is None or not str(answer).strip():
        return "the decider gave no answer%s" % (": " + rationale if rationale else "")
    decided = chosen_option(answer, subject.options)
    found = irreversible_class(decided, subject.question)
    if found is not None:
        return "its answer falls in a class on the irreversible list (%s): %s" % (found, decided)
    return None


# --- the prompt -----------------------------------------------------------------------------------


def _fence(text):
    fence = "```"
    while fence in text:
        fence += "`"
    return fence


def _read(ledger, relative):
    try:
        return ledger.path(relative).read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def _dossier_lines(ledger):
    """One line per reference at level 0 or 1 (and the path of a level-2 one): the L0 and L1 records."""
    from wayline.dossier import REFS, LEVEL_2, all_slugs, read_dossier  # the dossier module imports the launcher and the fetcher
    lines = []
    for slug in all_slugs(ledger):
        try:
            dossier = read_dossier(ledger, slug)
        except ValueError as failure:
            lines.append("- `%s`: [wayline: its dossier could not be read: %s]" % (slug, failure))
            continue
        metadata = dossier.get("metadata") or {}
        level = dossier.get("level", 0)
        parts = ["- `%s` (level %s): %s" % (slug, level, metadata.get("title") or "untitled")]
        if metadata.get("year"):
            parts.append("(%s)" % metadata["year"])
        facts = []
        if dossier.get("existence"):
            facts.append("existence: %s" % (dossier["existence"] if isinstance(dossier["existence"], str) else json.dumps(dossier["existence"])))
        if dossier.get("relation_to_intent"):
            facts.append("relation to the intent: %s" % dossier["relation_to_intent"])
        if dossier.get("deserves_l2_if"):
            facts.append("worth a full read if: %s" % dossier["deserves_l2_if"])
        if dossier.get("abstract"):
            facts.append("abstract: %s" % dossier["abstract"])
        lines.append(" ".join(parts) + (". " + "; ".join(facts) if facts else ""))
        lines.append("  path: research/%s/%s/dossier.json%s" % (REFS, slug, ", and dossier.md with the full read" if level >= LEVEL_2 else ""))
    return lines or ["[wayline: no reference has a dossier yet; the answer rests on the intake and the position memo alone]"]


def records_text(project, max_chars=None):
    """The records the decider reads, inlined in order and cut at `max_chars` with every cut announced.

    `DECISIONS.md` first, whole when it fits, because the settled decisions bind the answer; then the
    position memo, the objectives (`OBJECTIVES.md`, decision 17, in place of `GOAL.json`), the L0 and L1
    records, and the query pack. Returns `(text, cut)`.
    """
    ledger = Ledger(project)
    entries = [
        ("research/DECISIONS.md", _read(ledger, grill.DECISIONS_MD), "[wayline: there is no DECISIONS.md; nothing is settled yet]"),
        ("research/POSITION.md", _read(ledger, grill.POSITION_MD),
         "[wayline: there is no position memo; the tree rests on INTAKE.md alone]"),
        ("research/%s" % OBJECTIVES_MD, _read(ledger, OBJECTIVES_MD), "[wayline: no objective is recorded yet]"),
        ("the L0 and L1 records (research/refs/<slug>/dossier.json)", "\n".join(_dossier_lines(ledger)), None),
        ("research/kb/query_pack.md", _read(ledger, "kb/query_pack.md"), "[wayline: there is no query pack; no reference was absorbed]"),
    ]
    return inline_records(entries, max_chars, "Read them in this order; what DECISIONS.md settles binds the answer.")


def inline_records(entries, max_chars=None, lead=None, heading="# The records"):
    """`entries` inlined in order under `heading`, cut at the context cap with every cut announced.

    Each entry is `(heading, text, absent)`: the text is fenced under its heading, or `absent` stands
    in for one that is missing. The cap keeps `PROMPT_ROOM` under `max_chars` for what is not a record,
    and never goes under `RECORDS_MIN`. Returns `(text, cut)`. The planner's plan prompt inlines its
    own records (the spec, the goal, the query pack) through this, so the two prompts cut alike.
    """
    cap = None if max_chars is None else max(RECORDS_MIN, int(max_chars) - PROMPT_ROOM)
    rendered, used, cut = [heading, ""] + ([lead] if lead else []), 0, False
    for heading, text, absent in entries:
        rendered.extend(["", "## %s" % heading, ""])
        if text is None or not text.strip():
            rendered.append(absent)
            continue
        text = text.rstrip("\n")
        if cap is not None and used >= cap:
            rendered.append("[wayline: left out at the context cap; open the path yourself if the answer needs it.]")
            cut = True
            continue
        note = None
        if cap is not None and used + len(text) > cap:
            left_out = len(text) - (cap - used)
            text, cut = text[: cap - used], True
            note = "[wayline: cut here at the context cap; %d character(s) are missing. Open the path for the rest.]" % left_out
        used += len(text)
        fence = _fence(text)
        rendered.extend([fence, text, fence])
        if note:
            rendered.extend(["", note])
    return "\n".join(rendered) + "\n", cut


def decider_prompt(role, subject, records, harness, project, cut=False):
    """The decider's prompt: the decision, the line, the records, the paths it may open, the protocol, the schema."""
    lines = ["# The decision you are being asked for", "", "- subject: %s" % subject.name,
             "- the question: %s" % subject.question.strip().replace("\n", "\n  ")]
    if subject.options:
        lines.append("- options: %s" % " | ".join(" ".join(option.split()) for option in subject.options))
    lines.append("- recommended: %s" % (" ".join(subject.recommended.split()) if subject.recommended else "none was given"))
    for item in subject.evidence:
        lines.append("- evidence: %s" % " ".join(str(item).split()))
    for identifier, question, answer in subject.requires:
        lines.append("- rests on %s, %s: settled as %s" % (identifier, " ".join(question.split()),
                                                           " ".join(str(answer).split()) if answer else "open"))
    lines += [
        "",
        "Decide this one thing, from the records below, and answer nothing wider. The owner raised autonomy to "
        "`autonomous` and reads your decision in the morning; write the rationale for them.",
        "",
        "# The line",
        "",
        "The irreversible list is not yours to decide: deleting or overwriting data; pushing or force-pushing; making the "
        "code repository public or changing its visibility; exceeding or raising a budget (wall-clock or GPU hours: "
        "never extend one); changing the stopping rule; spending money; changing a goal's measure or the data; changing "
        "the harness globally; any network write. The human-only classes of this project are: %s. An answer that falls in any of "
        "these, or that cannot be taken back, is the owner's: return `answer: null` with `reversible: false` (or "
        "`human_only: true`), and put what you would have answered in the rationale. The harness checks every answer "
        "against the list as well." % _classes(harness),
        "",
        "A `software` decision (a project's tool a ticket needs, decision 17) is yours to answer with Install, Not now, or "
        "Go without: installing free software through the harness's routes is neither irreversible nor a global harness "
        "change. Changing a tool already installed, the tools venv, and licensed software (MATLAB) are the owner's alone, "
        "and their decisions never reach you.",
        "",
        "Moving the project's environment (`wayline switch --environment`: the shared tools, a conda prefix, a venv, or a "
        "container) is the owner's word alone, and no decision class names it: never answer with a move, and never set it.",
        "",
        "# The radius",
        "",
        "The project's radius is `%s`. It bounds what you may add: %s." % (harness.get("radius"), _radius_bound(harness.get("radius"))),
        "",
        _objective_line(harness),
        "",
    ]
    parts = ["\n".join(lines), records]
    if cut:
        parts.append("[wayline: the records were cut at the context cap; the paths below hold the rest.]")
    parts.append("\n".join([
        "# The paths you may open",
        "",
        "The project is `%s`; open these with the Read tool when a record points into them:" % project,
        "",
        "- `research/INTAKE.md`: the intent, the constraints, the human-only classes as the owner stated them",
        "- `research/CONTEXT.md`: the vocabulary the grill settled",
        "- `research/refs/<slug>/dossier.json`, and `dossier.md` for a reference read in full",
        "- `research/tickets/<n>-<slug>.md`: the ticket a decision request came from",
    ]))
    parts.append(role.protocol)
    parts.append(worker.schema_section("# The decision", role.output_schema or DECISION_SCHEMA, closing=[
        "",
        "`decided_by` is `decider`, `timestamp` is null (the harness stamps it), and `reversible` is true unless the "
        "answer cannot be taken back.",
    ]))
    return "\n\n".join(part.strip("\n") for part in parts if part and part.strip()) + "\n"


def _classes(harness):
    """The human-only classes the decider is told, `harness.json`'s plus `ladder` while the ladder consent is not `auto` (decision 16).

    An old `goal` entry is told as `objective`, which covers goals (decision 17).
    """
    stated = [name for name in (harness.get("human_only") or []) if isinstance(name, str)]
    classes = human_only_classes_now(dict(harness, human_only=stated or list(DEFAULT_HUMAN_ONLY)))
    return ", ".join("`%s`" % name for name in classes)


def _objective_line(harness):
    """What the decider may do to an objective: nothing that adds, reframes, or reopens one while `objective` is human-only."""
    if OBJECTIVE_CLASS in human_only_classes_now(dict(harness, human_only=harness.get("human_only") or list(DEFAULT_HUMAN_ONLY))):
        return ("`objective` is a human-only class of this project, so adding, reframing, or reopening an objective, and "
                "changing a goal's measure, is the owner's: hand such a decision back with `answer: null` and "
                "`human_only: true`. The radius above bounds only the work you admit.")
    return ("The owner took `objective` off the human-only classes, so you may add or reframe an objective within the "
            "radius above, and reopen a parked one at any radius; changing a goal's measure stays the owner's.")


def _radius_bound(radius):
    """What the radius lets the decider add, every bound named so the session reads its own against the others."""
    if radius not in RADIUS_BOUNDS:
        return "the radius is not one the harness knows, so add nothing (%s)" % RADIUS_BOUNDS["strict"]
    return "; ".join(RADIUS_BOUNDS.values()) + " (yours: `%s`)" % radius


# --- one launch -----------------------------------------------------------------------------------


def session_dir(project, slug):
    """`research/sessions/decider/<subject>/<n>`, the first free number, so a subject decided twice keeps both streams."""
    base = Path(project) / "research" / "sessions" / SESSIONS / (slug or "subject")
    number = 1
    while (base / str(number)).exists():
        number += 1
    return base / str(number)


def _budget(policy, key):
    return ((policy.get("budget") or {}).get(DECIDER_BUDGET) or {}).get(key)


def _context_cap(policy, model):
    caps = (policy.get("context_pack") or {}).get("max_chars") or {}
    return caps.get(model, min(caps.values()) if caps else None)


def _unusable(envelope):
    """Why this envelope is not a decision the harness can record, or None when it is one."""
    if not envelope.valid:
        return "; ".join(envelope.errors) or "the session returned no structured decision"
    try:
        check(envelope.structured_output, load_schema(DECISION_SCHEMA), name="decision")
    except ValidationError as failure:
        return str(failure)
    returned = envelope.structured_output
    if not (returned.get("rationale") or "").strip():
        return "the decision carries no rationale, and a decision nobody can audit is a guess"
    if returned.get("answer") is not None and not str(returned["answer"]).strip():
        return "the decision's answer is empty; give one, or null with the reason it is the owner's"
    return None


def take_decision(subject, *, project, harness_root=HARNESS_ROOT, policy=None, fall_back=None):
    """One decider session on `subject`, validated but not written: `(record, envelope, model, fallback_from)`.

    A session that returns something the `decision` schema refuses, or a decision with no rationale, is
    resumed once with the reason; a second unusable answer raises `DeciderError`. A session a usage window
    refused raises `gates.UsageLimited` and is launched again later, fresh, never resumed. `fall_back` is
    the conductor's word for its wave; None reads the hold from the journal and raises `gates.FableHeld`
    before a session is spent when the decider waits (decision 15). Every launch goes through the worker
    launcher (seam 1), so a test scripts the fake there.
    """
    project = Path(project).resolve()
    policy = policy_for(project, harness_root) if policy is None else policy
    what = "the decider on %s" % subject.name
    model, effort, fallback_from = decider_tier(policy, _falls_back_now(project, policy, fall_back, what))
    role = worker.read_role(DECIDER, harness_root, project)
    records, cut = records_text(project, _context_cap(policy, model))
    prompt = decider_prompt(role, subject, records, read_harness(project), project, cut)
    run_dir = session_dir(project, subject.slug)
    request = worker.LaunchRequest(
        role=role.name, model=model, effort=effort, prompt=prompt,
        agent_json=role.agent_json(model, effort, _budget(policy, "max_turns")),
        allowed_tools=list(role.allowed_tools), disallowed_tools=list(role.disallowed_tools),
        settings_path=gates.write_worker_settings(run_dir / "settings.json", harness_root),
        add_dirs=[str(Path(harness_root).resolve()), str(project)],
        cwd=project,
        env=gates.verdict_env(project, run_dir),
        schema_path=Path(harness_root).resolve() / "schemas" / (DECISION_SCHEMA + ".json"),
        max_minutes=_budget(policy, "max_minutes"),
    )
    envelope = worker.launch(request)
    gates.raise_if_refused(envelope, model, what)
    problem = _unusable(envelope)
    if problem is not None and envelope.session_id:
        envelope = worker.resume(request, envelope.session_id, RESUME_DECISION % problem)
        gates.raise_if_refused(envelope, model, what)
        problem = _unusable(envelope)
    if problem is not None:
        raise DeciderError("%s could not decide: %s" % (what, problem))
    return envelope.structured_output, envelope, model, fallback_from


def _attempt(subject, **context):
    """One launch on `subject`, read for the caller: `(outcome, returned, envelope, model, fallback_from)`.

    `outcome` is the `Outcome` the launch already settled, or None when there is a record to act on: a
    launch nobody could take (a role or a file that cannot be read, a session with no usable record) is a
    `failed` outcome, and a refused record (`refusal`) a `refused` one with the session's model and id on it.
    A usage window that refused the launch, or the hold on Fable's window, raises out to the caller.
    """
    try:
        returned, envelope, model, fallback_from = take_decision(subject, **context)
    except (DeciderError, worker.LaunchError, worker.RoleError, ProjectError, OSError) as failure:
        return Outcome(subject, "failed", why=str(failure)), None, None, None, None
    why = refusal(subject, returned)
    if why is not None:
        return (Outcome(subject, "refused", why=why, session_id=envelope.session_id, model=envelope.model or model,
                        fallback_from=fallback_from), returned, envelope, model, fallback_from)
    return None, returned, envelope, model, fallback_from


def _decided(subject, returned, envelope, model, fallback_from):
    return Outcome(subject, "decided", answer=str(returned["answer"]).strip(), rationale=returned["rationale"].strip(),
                   confidence=returned.get("confidence"), model=envelope.model or model, fallback_from=fallback_from,
                   session_id=envelope.session_id)


def _open_for_owner(project, subject, why, origin, title, notify):
    """The human-only decision ticket a refused decision becomes: the question, the options, and the refusal as evidence.

    It pauses nothing (`blocking` null): a grill question holds no subgraph, and a parked proposal is parked
    already. Returns the ticket's id, or None with the reason folded into `why` when none could be opened.
    """
    try:
        opened = decisions.open_decision(
            project, subject.question, options=subject.options, recommended=subject.recommended,
            evidence=subject.evidence + ["the decider was refused it: %s" % why], blocking=None, human_only=True,
            reversible=subject.reversible, proposed_by=DECIDER, origin=origin, title=title, notify=notify)
    except (TicketError, ProjectError, OSError) as failure:
        return None, "%s (no decision ticket could be opened for it: %s)" % (why, failure)
    return opened["ticket"], why


# --- the four subjects ----------------------------------------------------------------------------


def decide_question(project, record, records=(), *, harness_root=HARNESS_ROOT, policy=None, fall_back=None, notify=None):
    """Resolve one open question of the design tree; returns the `Outcome`.

    A decision is written through `grill.answer` with `decided_by: decider`, the model, and the session. A
    refusal marks the question human-only in `DECISIONS.md` and opens a human-only decision ticket for it,
    pausing nothing, with the decider's reading as evidence. A launch nobody could take is a failed outcome
    and the question stays as it was; a usage window that refused it, or the hold on Fable's window, raises
    out to the caller.
    """
    project = Path(project).resolve()
    subject = Subject.from_record(record, records)
    outcome, returned, envelope, model, fallback_from = _attempt(subject, project=project, harness_root=harness_root,
                                                                 policy=policy, fall_back=fall_back)
    if outcome is not None and outcome.status == "refused":
        grill.turn_over(project, record["id"], "the decider was refused it: %s" % outcome.why)
        outcome.ticket, outcome.why = _open_for_owner(project, subject, outcome.why, grill.TICKET_ORIGIN + record["id"],
                                                      "%s: %s" % (record["id"], record["question"]), notify)
    if outcome is not None:
        return outcome
    outcome = _decided(subject, returned, envelope, model, fallback_from)
    try:
        grill.answer(project, record["id"], outcome.answer, outcome.rationale, confidence=outcome.confidence, decided_by=DECIDER,
                     model=outcome.model, fallback_from=fallback_from, session_id=outcome.session_id)
    except (grill.GrillError, ProjectError, OSError) as failure:
        return Outcome(subject, "failed", why="the answer could not be recorded: %s" % failure, session_id=outcome.session_id)
    return outcome


def decide_ticket(project, fields, body, record=None, *, harness_root=HARNESS_ROOT, policy=None, fall_back=None, notify=None):
    """Resolve one open decision ticket; returns the `Outcome`.

    A decision is written through `decisions.decide`: `## Answer` in the ticket's file, a `decision` with
    `decided_by: decider`, which the conductor closes as it closes the owner's, and the record appended to
    `DECISIONS.md`. A refusal turns the ticket human-only (`decisions.turn_over`) and notifies the owner.
    """
    from wayline.stopping import DECIDER_CHOICES, frontier_choice, frontier_objective  # the stopping module imports the goal module
    project = Path(project).resolve()
    subject = Subject.from_ticket(fields, body, record)
    identifier = fields["id"]
    outcome, returned, envelope, model, fallback_from = _attempt(subject, project=project, harness_root=harness_root,
                                                                 policy=policy, fall_back=fall_back)
    if outcome is None and frontier_objective(fields.get("origin")) is not None \
            and frontier_choice(returned.get("answer")) not in DECIDER_CHOICES:
        # An empty-frontier ticket (ticket 87): the decider replans or answers; parking or dropping is the owner's.
        outcome = Outcome(subject, "refused", why="the decider only replans for an objective the stopping rule names or answers "
                          "it as it stands, and it answered %s" % returned.get("answer"), session_id=envelope.session_id,
                          model=envelope.model or model, fallback_from=fallback_from)
    if outcome is not None and outcome.status == "refused":
        decisions.turn_over(project, identifier, outcome.why, notify=notify)
        outcome.ticket = identifier
    if outcome is not None:
        return outcome
    outcome = _decided(subject, returned, envelope, model, fallback_from)
    try:
        decisions.decide(project, identifier, outcome.answer, outcome.rationale, confidence=outcome.confidence, model=outcome.model,
                         fallback_from=fallback_from, session_id=outcome.session_id)
    except (ProjectError, OSError) as failure:
        return Outcome(subject, "failed", why="the answer could not be recorded: %s" % failure, session_id=outcome.session_id)
    outcome.ticket = identifier
    return outcome


def proposal_origin(identifier):
    """The origin of the decision ticket a refused parked proposal becomes: `proposal <id>`."""
    return "proposal %s" % identifier


def decide_proposal(project, proposal, *, harness_root=HARNESS_ROOT, policy=None, fall_back=None, notify=None):
    """Reconsider one parked proposal at the end of a wave; returns the `Outcome`.

    The decision is journaled as a `decision` with no ticket, its answer `proposal <id>: admit` or `keep
    parked`, which is what ticket 37's admission reads to admit it within the cap. A refusal (an admission
    that would cross the line) opens a human-only decision ticket asking the owner instead, with the
    decider's reading as evidence, and journals no decision: the admission is the owner's then.
    """
    project = Path(project).resolve()
    subject = Subject.from_proposal(proposal)
    outcome, returned, envelope, model, fallback_from = _attempt(subject, project=project, harness_root=harness_root,
                                                                 policy=policy, fall_back=fall_back)
    if outcome is not None and outcome.status == "refused":
        outcome.ticket, outcome.why = _open_for_owner(project, subject, outcome.why, proposal_origin(subject.key),
                                                      "Admit the parked proposal %s?" % subject.key, notify)
    if outcome is not None:
        return outcome
    outcome = _decided(subject, returned, envelope, model, fallback_from)
    if outcome.answer.strip().lower() != ADMIT:
        outcome.answer = KEEP_PARKED
    payload = {"ticket": None, "answer": PROPOSAL_ANSWER % (subject.key, outcome.answer), "decided_by": DECIDER,
               "rationale": outcome.rationale, "confidence": outcome.confidence}
    payload.update({key: value for key, value in (("model", outcome.model), ("fallback_from", outcome.fallback_from)) if value})
    Ledger(project).append_event(DECISION, payload, session_id=outcome.session_id)
    return outcome


def venue_of(answer, venues):
    """The slug of `venues` (`{slug: display name}`) a decider's answer names, or None when it names none or several.

    The answer may be the slug, an option it points at (`option 3`), or a sentence naming one venue by its slug or
    its display name. A name is matched as whole words, and one found only inside another venue's longer name does
    not count, so "Nature Methods fits" names `nature-methods` and not `nature`.
    """
    text = " ".join(chosen_option(answer, sorted(venues)).split())  # the order `decide_venue` lists the options in
    folded = text.strip("`'\". ").lower()
    if folded in venues:
        return folded
    lowered, spans = text.lower(), {}
    for slug, display in venues.items():
        for name in {slug, str(display).lower()}:
            words = [re.escape(word) for word in re.split(r"[-\s]+", name) if word]
            if words:
                pattern = r"(?<![a-z0-9])%s(?![a-z0-9])" % r"[-\s]+".join(words)
                spans.setdefault(slug, []).extend(found.span() for found in re.finditer(pattern, lowered))

    def inside(span, slug):
        return any(other != span and other[0] <= span[0] and span[1] <= other[1]
                   for elsewhere, found in spans.items() if elsewhere != slug for other in found)

    named = {slug for slug, found in spans.items() if any(not inside(span, slug) for span in found)}
    return named.pop() if len(named) == 1 else None


def decide_venue(project, venues, evidence=(), *, subject="paper", harness_root=HARNESS_ROOT, policy=None, fall_back=None):
    """Pick the best-fitting venue for the paper among `venues` (`{slug: display name}`); returns the `Outcome`.

    `wayline paper` without `--venue` asks this (Implementation Decisions 13): one decider session, the slugs as the
    options and a line per venue as `evidence`. A decision is journaled as a `decision` with no ticket, its answer
    `paper venue: <slug>`, so the report lists it first with the rest of the decider's, and the outcome's `answer` is
    the slug. The owner asked for the paper and is at the command, so a refusal opens no decision ticket: it comes
    back as a `refused` outcome for the command to print, and so does an answer that names no venue, as `failed`.
    """
    project = Path(project).resolve()
    venues = dict(venues)
    question = ("Which venue does the paper fit best, given the run's findings, its report, and each venue's "
                "guidelines? Answer with the venue's slug.")
    subject = Subject(kind="venue", key=subject, question=question, options=sorted(venues), recommended=None,
                      evidence=list(evidence), slug="paper-venue")
    outcome, returned, envelope, model, fallback_from = _attempt(subject, project=project, harness_root=harness_root,
                                                                 policy=policy, fall_back=fall_back)
    if outcome is not None:
        return outcome
    outcome = _decided(subject, returned, envelope, model, fallback_from)
    slug = venue_of(outcome.answer, venues)
    if slug is None:
        return Outcome(subject, "failed", why="its answer names no one venue of %d: %s" % (len(venues), outcome.answer),
                       model=outcome.model, fallback_from=fallback_from, session_id=outcome.session_id)
    outcome.answer = slug
    payload = {"ticket": None, "answer": VENUE_ANSWER % slug, "decided_by": DECIDER,
               "rationale": outcome.rationale, "confidence": outcome.confidence}
    payload.update({key: value for key, value in (("model", outcome.model), ("fallback_from", outcome.fallback_from)) if value})
    Ledger(project).append_event(DECISION, payload, session_id=outcome.session_id)
    return outcome


def reconsidered(project, events):
    """The ids of the parked proposals the decider has taken already: answered in the journal, or turned over to the owner.

    Read off the journal's `decision` events (`proposal <id>: ...`) and the decision tickets whose origin names a
    proposal, so a proposal is put to one session, not one per wave.
    """
    found = set()
    prefix = PROPOSAL_ANSWER.split("%s")[0]
    for event in events:
        payload = event.get("payload") or {}
        answer = payload.get("answer") or ""
        if event.get("event") == DECISION and payload.get("decided_by") in (DECIDER, "human") and payload.get("ticket") is None \
                and answer.startswith(prefix):
            found.add(answer[len(prefix):].split(":", 1)[0])  # the owner's own answer (ticket 89) is never put to the decider
    try:
        for ticket in read_tickets(project):
            origin = str(ticket.get("origin") or "")
            if ticket["kind"] == DECISION_KIND and origin.startswith(prefix):
                found.add(origin[len(prefix):].strip())
    except (ValueError, OSError):
        pass
    return found


# --- the verb: wayline grill --decide-rest ---------------------------------------------------------


def settle_grill(project, report, *, harness_root=HARNESS_ROOT, policy=None, fall_back=None, notify=None, say=None):
    """`decide_rest` for a phase verb under autonomous: each outcome's line into `report["did"]`, what stopped it into `report["stopped"]`.

    `wayline position` calls it once the memo is there, and `wayline specify` before a draft, so a
    decide-rest that did not finish (its session killed with the grill's, ticket 36) is taken up again.
    """
    if not grill.decider_share(grill.read_records(project)):
        return
    try:
        decided = decide_rest(project, harness_root=harness_root, policy=policy, fall_back=fall_back, notify=notify, out=None)
    except (grill.GrillError, ProjectError) as failure:
        report["stopped"] = "the decider could not take the grill's questions: %s" % failure
        return
    for name in ("decided", "refused", "failed"):
        report["did"] += ["the decider on " + outcome.line for outcome in decided[name]]
    if decided["stopped"]:
        report["stopped"] = decided["stopped"]
    if say is not None:
        say("  the decider took %d of the grill's question(s)" % sum(len(decided[name]) for name in ("decided", "refused", "failed")))


def decide_rest(project, *, harness_root=HARNESS_ROOT, policy=None, fall_back=None, notify=None, out=None):
    """Resolve the design tree's frontier until only the owner's questions are left; returns the report.

    Under autonomy `autonomous` only: under any other the verb refuses, naming the switch. Each decision
    is one session, and the frontier is read again after each, because an answer settles the prerequisites
    of questions behind it. A question the decider could not take (`failed`) is left as it was and not tried
    again in this call; a usage window that refused a launch, or the hold on Fable's window while the consent
    waits, ends the call with what it decided so far and the reason in `stopped`.
    """
    project = Path(project).resolve()
    harness = read_harness(project)
    if harness.get("autonomy") != grill.AUTONOMOUS:
        raise grill.GrillError("autonomy is %s: the decider resolves the rest only under autonomous; raise it with "
                               "wayline switch --autonomy autonomous --project %s" % (harness.get("autonomy"), project))
    say = (lambda text: print(text, file=out)) if out is not None else (lambda text: None)
    report = {"project": str(project), "decided": [], "refused": [], "failed": [], "stopped": None, "left": []}
    tried = set()
    while True:
        records = grill.read_records(project)
        share = [record for record in grill.decider_share(records) if record["id"] not in tried]
        if not share:
            break
        record = share[0]
        tried.add(record["id"])
        say("deciding %s: %s" % (record["id"], " ".join(record["question"].split())))
        try:
            outcome = decide_question(project, record, records, harness_root=harness_root, policy=policy, fall_back=fall_back,
                                      notify=notify)
        except gates.FableHeld as held:
            report["stopped"] = "Fable's weekly window is held until %s and the consent waits: %s" % (held.resets_at, held)
            break
        except gates.UsageLimited as refused:
            report["stopped"] = "the usage limit refused the launch: %s" % refused
            break
        say("  " + outcome.line)
        report[outcome.status].append(outcome)
    records = grill.read_records(project)
    report["left"] = [record["id"] for record in grill.decider_share(records)]
    return report


def render_decided(report):
    """The text `wayline grill --decide-rest` prints before the tier."""
    lines = ["decider  %s" % report["project"]]
    for name in ("decided", "refused", "failed"):
        lines += ["  " + outcome.line for outcome in report[name]]
    if not (report["decided"] or report["refused"] or report["failed"]):
        lines.append("  nothing was open for the decider")
    if report["stopped"]:
        lines.append("  stopped: %s" % report["stopped"])
    if report["left"]:
        lines.append("  still open for the decider: %s" % ", ".join(report["left"]))
    lines.append("  every decision is in research/DECISIONS.md as decided-by: decider, and journaled; reverse one with "
                 "wayline grill answer <id> \"<answer>\" --rationale \"<why>\" --revise")
    return "\n".join(lines)


# --- the empty frontier (decision 17; ticket 87) --------------------------------------------------------------


FRONTIER_SUBJECT = "the empty frontier"
_FRONTIER_LINE = re.compile(r"\b(O[1-9][0-9]*)\b\s*[:=\-–—]*\s*([^;,\n]*)")


def frontier_answers(answer, identifiers):
    """`{objective: choice}` from one answer naming each objective (`O1: replan for it; O2: answer it as it stands`).

    The choice is `stopping.frontier_choice` of the words after the id, None when they pick no option.
    """
    from wayline.stopping import frontier_choice  # the stopping module imports the goal and objectives modules
    found = {}
    for match in _FRONTIER_LINE.finditer(str(answer or "")):
        if match.group(1) in identifiers and match.group(1) not in found:
            found[match.group(1)] = frontier_choice(match.group(2))
    return found


def decide_frontier(project, entries, *, harness_root=HARNESS_ROOT, policy=None, fall_back=None, notify=None):
    """One decider session on every open empty-frontier ticket of this empty frontier; returns `(outcome, decided)`.

    `entries` are `(fields, body, record, objective)` for each ticket. The session answers each objective with
    `replan for it` or `answer it as it stands`, all in one answer; each such choice is written to its ticket through
    `decisions.decide`, the answer naming the option. Parking or dropping an objective the stopping rule names is never
    the decider's, so a choice of either, a choice of nothing, or a refused session turns the ticket over to the owner.
    `decided` lists the tickets answered.
    """
    from wayline.stopping import DECIDER_CHOICES, FRONTIER_OPTIONS
    project = Path(project).resolve()
    identifiers = [objective for _, _, _, objective in entries]
    lines, options, recommended, evidence = [], [], [], []
    for fields, body, record, objective in entries:
        record = record or {}
        lines.append("ticket %d about %s: %s" % (fields["id"], objective, decisions.decision_question(fields, body)))
        options.extend("%s: %s" % (objective, choice) for choice in DECIDER_CHOICES)
        if record.get("recommended"):
            recommended.append("%s: %s" % (objective, record["recommended"]))
        evidence.extend("%s: %s" % (objective, item) for item in record.get("evidence") or [])
    question = ("The frontier is empty, and the stopping rule still waits on %s. For each, answer one line `<id>: replan for it` "
                "or `<id>: answer it as it stands`, separated by semicolons; parking or dropping one is the owner's. %s"
                % (", ".join(identifiers), " ".join(lines)))
    subject = Subject(kind="frontier", key=FRONTIER_SUBJECT, question=question, options=options,
                      recommended="; ".join(recommended) or None, evidence=evidence, slug="frontier")
    outcome, returned, envelope, model, fallback_from = _attempt(subject, project=project, harness_root=harness_root,
                                                                 policy=policy, fall_back=fall_back)
    if outcome is not None:
        if outcome.status == "refused":
            for fields, _, _, _ in entries:
                decisions.turn_over(project, fields["id"], outcome.why, notify=notify)
        return outcome, []
    outcome = _decided(subject, returned, envelope, model, fallback_from)
    chosen = frontier_answers(outcome.answer, identifiers)
    decided = []
    for fields, _, _, objective in entries:
        choice = chosen.get(objective)
        if choice not in DECIDER_CHOICES:
            why = ("the decider only replans for an objective the stopping rule names or answers it as it stands, and its answer "
                   "for %s was %s" % (objective, "%r, which is the owner's" % choice if choice in FRONTIER_OPTIONS else "none of those"))
            decisions.turn_over(project, fields["id"], why, notify=notify)
            continue
        try:
            decisions.decide(project, fields["id"], choice, outcome.rationale, confidence=outcome.confidence, model=outcome.model,
                             fallback_from=fallback_from, session_id=outcome.session_id)
        except (ProjectError, OSError) as failure:
            decisions.turn_over(project, fields["id"], "the decider's answer could not be recorded: %s" % failure, notify=notify)
            continue
        decided.append(fields["id"])
    return outcome, decided
