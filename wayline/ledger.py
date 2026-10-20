"""The ledger: the only code that writes under a project's `research/` (Implementation Decisions 2).

Every other module returns structured values and the ledger writes them: JSON and markdown by
write-to-temp-then-rename, `journal.jsonl` and the other line files (`findings.jsonl`, `passages.jsonl`) by append. Every write takes
`fcntl.flock` on `research/.lock`, because the conductor, the tick, the dashboard, and the CLI
verbs are separate processes that all write through this module; inside one process the same
lock is shared by every Ledger of the same project and by every thread, so it is re-entrant for
the holder and exclusive for everyone else.

The journal is the bus: one JSON object per line with `ts`, `event`, `ticket`, `session_id`,
`job`, `payload`. The event names and the payload keys below are the vocabulary of the spec's
table; `append_event` refuses an event or a key outside it, and a test cross-checks the
constants against the spec so the two cannot drift silently.
"""

import fcntl
import json
import logging
import math
import os
import shutil
import stat
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from wayline.jsonschema import check, load_schema

__all__ = ["Ledger", "LedgerError", "ledger_for", "make_event", "now_ts", "atomic_write", "atomic_bytes", "EVENTS", "PAYLOAD_ENUMS", "JOURNAL", "LOCK",
           "HEARTBEAT", "Heartbeat", "ConductorBusy", "read_heartbeat", "conductor_holder"]

JOURNAL = "journal.jsonl"
LOCK = ".lock"
# The conductor's heartbeat, whose flock keeps a second conductor off the project (decision 5).
HEARTBEAT = "conductor.json"
# A conductor starting while a reader probes the heartbeat's lock tries this many times, this far
# apart, before it concludes that another conductor holds it; a reader retries a torn read as often.
HEARTBEAT_TRIES = 5
HEARTBEAT_PAUSE_S = 0.01
HEARTBEAT_READS = 3

_log = logging.getLogger("wayline.ledger")

# Characters that end a line for some reader (str.splitlines, JavaScript, editors); a line file
# never contains one raw, and the journal writer escapes them inside JSON strings.
_LINE_BREAKS = "\n\r\x0b\x0c\x1c\x1d\x1e\x85  "

# --- event names -----------------------------------------------------------------------------

RUN_STARTED = "run_started"
RUN_ENDED = "run_ended"
PHASE = "phase"
PACING = "pacing"
PAUSED = "paused"
UNPAUSED = "unpaused"
TICKET_CREATED = "ticket_created"
ASSIGNED = "assigned"
TICKET_LAUNCHED = "ticket_launched"
TICKET_SESSION = "ticket_session"
TICKET_RESULT = "ticket_result"
TICKET_RESUMED = "ticket_resumed"
ACCEPTANCE = "acceptance"
INTEGRATED = "integrated"
TICKET_DONE = "ticket_done"
TICKET_ACCEPTED = "ticket_accepted"
TICKET_FAILED = "ticket_failed"
TICKET_BLOCKED = "ticket_blocked"
TICKET_NEEDS_HUMAN = "ticket_needs_human"
TICKET_CANCELLED = "ticket_cancelled"
TICKET_RERUN = "ticket_rerun"
DIFFICULTY_RAISED = "difficulty_raised"
VERDICT = "verdict"
FINDING = "finding"
PROGRESS = "progress"
DISCARDED = "discarded"
PROPOSAL_ADMITTED = "proposal_admitted"
PROPOSAL_PARKED = "proposal_parked"
DECISION_OPENED = "decision_opened"
DECISION = "decision"
JOB_LAUNCHED = "job_launched"
JOB_FINISHED = "job_finished"
JOB_RETRIED = "job_retried"
JOB_FAILED = "job_failed"
JOB_CANCELLED = "job_cancelled"
JOB_WAITING = "job_waiting"
MANIFEST = "manifest"
WAVE = "wave"
STALL = "stall"
PROMOTED = "promoted"
DEMOTED = "demoted"
ABSORBED = "absorbed"
CONSULTED = "consulted"
NOTIFIED = "notified"
CONTROL = "control"
SWITCHED = "switched"
FEEDBACK = "feedback"
CHANGE_RECORD = "change_record"
TAGGED = "tagged"
PINNED = "pinned"
REPORT_RENDERED = "report_rendered"
PAPER_STARTED = "paper_started"
FIGURE_RESULT = "figure_result"
OBJECTIVE = "objective"  # one change to research/objectives.json (decision 17)
MARKED = "marked"  # one mark or note on one item of a batch (decision 17; ticket 79)
DOCUMENT = "document"  # one document kept, or a newer version of it, in research/documents.json (decision 17; ticket 84)
CODE_PUSHED = "code_pushed"  # code pushed `code/`'s split to the code repository's remote (decision 17; ticket 85)
TOOL_INSTALLED = "tool_installed"  # a project's tool installed, licensed software recorded, or either failing (decision 17; ticket 82)
PASSAGE = "passage"  # one passage of a section written to research/passages.jsonl (decision 17; ticket 86)
SCOUTED = "scouted"  # one `wayline scout <identifier>` a worker ran, counted against its ticket (decision 17; ticket 98)
CONSOLIDATED = "consolidated"  # one consolidation of a section the owner asked for (decision 17; ticket 88)
CONCERN = "concern"  # one concern recorded or changed in research/concerns.json (decision 17; ticket 96)
REVIEWED = "reviewed"  # the owner let a decision made for them stand, or reversed it (decision 17; ticket 89)
RESULT = "result"  # one result created at an acceptance, or merged or renamed on the owner's word (decision 17; ticket 90)
VERIFICATION = "verification"  # one inherited result's standing recorded or changed in research/verifications.json (decision 17; ticket 97)
DRAWING = "drawing"  # one drawing of a result opened at a rest point, accepted, or failed (decision 17; ticket 100)
OBJECTIVE_PROPOSED = "objective_proposed"  # one objective proposal of a result or a verdict, or its judgment (decision 17; ticket 91)

# --- payload keys ----------------------------------------------------------------------------

K_RESUME = "resume"
K_HARNESS_TAG = "harness_tag"
K_AUTONOMY = "autonomy"
K_RADIUS = "radius"
K_PID = "pid"
K_REASON = "reason"
K_FROM = "from"
K_TO = "to"
K_FIVE_HOUR = "five_hour"
K_SEVEN_DAY = "seven_day"
K_FABLE = "fable"
K_ACTION = "action"
K_FABLE_ACTION = "fable_action"  # the action a launch on a Fable rung runs under (decision 16)
K_RESETS_AT = "resets_at"
K_WINDOW = "window"
K_UTILIZATION = "utilization"
K_TICKET = "ticket"
K_KIND = "kind"
K_PROPOSED_BY = "proposed_by"
K_ORIGIN = "origin"
K_BLOCKED_BY = "blocked_by"
K_ATTEMPT = "attempt"
K_ROLE = "role"
K_MODEL = "model"
K_EFFORT = "effort"
K_SKILLS = "skills"
K_WORKTREE = "worktree"
K_CONTEXT_CHARS = "context_chars"
K_PROMPT_SHA256 = "prompt_sha256"
K_DIFFICULTY = "difficulty"
K_RUNG = "rung"  # the index of the rung a ticket attempt ran on (decision 16)
K_MODEL_RAN = "model_ran"  # the model a session actually ran on, when it is not the one it was launched with (decision 16)
K_FALLBACK_FROM = "fallback_from"
K_SESSION_ID = "session_id"
K_STATUS = "status"
K_TURNS = "turns"
K_DURATION_MS = "duration_ms"
K_USAGE = "usage"
K_PERMISSION_DENIALS = "permission_denials"
K_VALID = "valid"
K_WHERE = "where"
K_PASS = "pass"
K_RESULTS = "results"
K_COMMIT = "commit"
K_RESOLVED_BY = "resolved_by"
K_EMPTY = "empty"  # `integrated`: the fast-forward added no commit of the ticket's own (M5)
K_NEXT = "next"
K_PATH = "path"
K_QUESTION = "question"
K_BY = "by"
K_SUBJECT_KIND = "subject_kind"
K_SUBJECT = "subject"
K_VERDICT_TYPE = "verdict_type"
K_FINDINGS = "findings"
K_ID = "id"
K_TEXT = "text"
K_PROVENANCE = "provenance"
K_NEGATIVE = "negative"
K_METRIC = "metric"
K_GOAL = "goal"  # the goal (an objective id) a `progress` or `discarded` judged (decision 17; ticket 87)
K_VALUE = "value"
K_RUN_ID = "run_id"
K_KEPT = "kept"
K_BEST = "best"
K_SD = "sd"
K_SEEDS = "seeds"
K_BLOCKING = "blocking"
K_HUMAN_ONLY = "human_only"
K_ANSWER = "answer"
K_DECIDED_BY = "decided_by"
K_RATIONALE = "rationale"
K_CONFIDENCE = "confidence"
K_JOB = "job"
K_UNIT = "unit"
K_GPU_UUIDS = "gpu_uuids"
K_CORES = "cores"
K_RAM_GB = "ram_gb"
K_EXIT_CODE = "exit_code"
K_SECONDS = "seconds"
K_OUTPUTS_OK = "outputs_ok"
K_OOM = "oom"
K_OVERRIDES = "overrides"
K_LOG_TAIL = "log_tail"
K_JOBS = "jobs"
K_SHA256 = "sha256"
K_SIZE = "size"
K_NUMBER = "number"
K_OUTCOMES = "outcomes"
K_PROGRESSED = "progressed"
K_WAVES = "waves"
K_SLUG = "slug"
K_FROM_LEVEL = "from_level"
K_TO_LEVEL = "to_level"
K_TRIGGER = "trigger"
K_LEVEL = "level"
K_CHUNKS = "chunks"
K_ENTRIES = "entries"
K_COVERAGE_PASS = "coverage_pass"
K_QUESTION_SHA256 = "question_sha256"
K_PROMOTE_REQUESTED = "promote_requested"
K_EVENT = "event"
K_CHANNEL = "channel"
K_OK = "ok"
K_COMMAND = "command"
K_ARGS = "args"
K_SOURCE = "source"
K_SCOPE_KIND = "scope_kind"
K_MECHANISM = "mechanism"
K_FIXTURE = "fixture"
K_TAG = "tag"
K_PREVIOUS = "previous"
K_CLAIMS = "claims"
K_TAGGED = "tagged"
K_LINTER_PASS = "linter_pass"
K_VENUE = "venue"
K_FIGURE_ID = "figure_id"
K_VERSION = "version"
K_MEASURE = "measure"  # `objective`: the goal's metric, or null for an objective without a measure
K_BATCH = "batch"
K_ITEM = "item"
K_MARK = "mark"
K_NOTE = "note"
K_TITLE = "title"  # `document`: the document's title
K_CONVERTER = "converter"  # `document`: the converters and their versions, null for a document kept but not converted
K_REMOTE = "remote"  # `code_pushed`: the code repository's `owner/name` on GitHub
K_MAIN = "main"  # `code_pushed`: the commit of `main` the split was cut from, where the next split's walk starts
K_TOOLS = "tools"  # `job_launched`: the name, version, and lock digest of every tool the job calls (ticket 82)
K_ENVIRONMENT = "environment"  # `job_launched`: the environment the job runs in, shared, conda, venv, or container (ticket 83)
K_NAME = "name"
K_OUTCOME = "outcome"
K_SECTION = "section"  # `passage`: the section it is part of
K_HEADING = "heading"  # `passage`, `finding`: the heading it stands under
K_REPLACES = "replaces"  # `passage`, `finding`: the id of the one it replaces, or null
K_OBJECTIVES = "objectives"  # `passage`, `finding`: the objectives of the ticket that wrote it
K_EVIDENCE = "evidence"  # `passage`, `finding`: what this project's evidence says of the inherited claim it replaces (ticket 93)
K_DOC = "doc"  # `passage`: an inherited passage's locator in its document, `D1#p4.s2` (ticket 93)
K_STANDING = "standing"  # `passage`: an inherited claim's standing, unchecked or unverifiable (ticket 93)
K_WITHDRAWN = "withdrawn"  # `passage`: true on a withdrawal, which takes the passage it replaces out of the section (ticket 93)
K_MOVED_FROM = "moved_from"  # `passage`: the inherited passage this one was moved from, in another section (ticket 93)
K_IDENTIFIER = "identifier"  # `scouted`: the DOI, arXiv id, or exact title the worker asked about
K_REPLACES_OWNER = "replaces_owner"  # `passage`, `finding`: true when it replaces an owner's passage, for the account (ticket 88)
K_REPLACED = "replaced"  # `consolidated`: the ids of the passages the consolidation replaced
K_CONSOLIDATES = "consolidates"  # `passage`: on a consolidation's passage, every passage it rewrote (ticket 88)
K_MERGES = "merges"  # `passage`: on a merged inherited passage, every occurrence of the claim it merges (ticket 95)
K_WRITTEN = "written"  # `consolidated`: the ids of the fewer passages it wrote in their place
K_PLACE = "place"  # `concern`: where the concern was sorted, tied to objectives, for the order, or declined; null while unsorted
K_REPORT = "report"  # `report_rendered`: which rendered file, `account` for research/ACCOUNT.md (ticket 89); absent for REPORT.md
K_EDITED = "edited"  # `report_rendered`: the commit an edit by hand was kept in as it stood, null when it could not be committed
K_DECISION = "decision"  # `reviewed`: the decision reviewed, D1 onward, by its place among the journal's `decision` events
K_REVIEW = "review"  # `reviewed`: stand or reverse
K_RESULT = "result"  # `finding`: the result, R1 onward, the finding joined at its acceptance (ticket 90)
K_INTO = "into"  # `result`: the result a merged one went into
K_ROUTE = "route"  # `verification`: the route of the verdict that changed it, reproduced, ported, reimplemented, or read
K_RELEASED = "released"  # `verification`: the tickets an unverifiable result stopped blocking
K_REST = "rest"  # `drawing`: the rest point it was opened at, run_end, checkpoint, or owner
K_PLOTS = "plots"  # `drawing`: the plot and table ids an accepted drawing drew
K_LEFT_OUT = "left_out"  # `drawing`: what acceptance left out, each with why
K_RETIRED = "retired"  # `drawing`: the plots an accepted drawing retired
K_PROPOSAL = "proposal"  # `objective`: the objective proposal a change applies, absent on the owner's word; `objective_proposed`: the proposal
K_OBJECTIVE = "objective"  # `objective_proposed`: the objective it names, or the new question's text for an add
K_UPHELD = "upheld"  # `objective_proposed`: true or false once judged, null while it waits for its verdict
K_WHY = "why"  # `objective_proposed`: the judgment's reason

# --- the vocabulary: event -> payload keys, in the spec table's order ------------------------

EVENTS = {
    RUN_STARTED: (K_RESUME, K_HARNESS_TAG, K_AUTONOMY, K_RADIUS, K_PID),
    RUN_ENDED: (K_REASON,),
    PHASE: (K_FROM, K_TO),
    PACING: (K_FIVE_HOUR, K_SEVEN_DAY, K_FABLE, K_ACTION, K_FABLE_ACTION),
    PAUSED: (K_RESETS_AT, K_WINDOW, K_UTILIZATION, K_MODEL),
    UNPAUSED: (K_MODEL,),
    TICKET_CREATED: (K_TICKET, K_KIND, K_PROPOSED_BY, K_ORIGIN, K_BLOCKED_BY),
    ASSIGNED: (K_TICKET, K_ROLE, K_SKILLS),
    TICKET_LAUNCHED: (K_TICKET, K_ATTEMPT, K_ROLE, K_MODEL, K_EFFORT, K_SKILLS, K_WORKTREE, K_PID, K_CONTEXT_CHARS, K_PROMPT_SHA256, K_DIFFICULTY, K_RUNG, K_FALLBACK_FROM, K_COMMIT),
    TICKET_SESSION: (K_TICKET, K_ATTEMPT, K_SESSION_ID, K_MODEL),
    TICKET_RESULT: (K_TICKET, K_ATTEMPT, K_SESSION_ID, K_STATUS, K_TURNS, K_DURATION_MS, K_USAGE, K_PERMISSION_DENIALS, K_VALID, K_JOBS, K_MODEL_RAN),
    TICKET_RESUMED: (K_TICKET, K_ATTEMPT, K_SESSION_ID, K_REASON),
    ACCEPTANCE: (K_TICKET, K_ATTEMPT, K_WHERE, K_PASS, K_RESULTS),
    INTEGRATED: (K_TICKET, K_COMMIT, K_RESOLVED_BY, K_EMPTY),
    TICKET_DONE: (K_TICKET,),
    TICKET_ACCEPTED: (K_TICKET,),
    TICKET_FAILED: (K_TICKET, K_ATTEMPT, K_REASON, K_NEXT),
    TICKET_BLOCKED: (K_TICKET, K_PATH),
    TICKET_NEEDS_HUMAN: (K_TICKET, K_QUESTION, K_REASON),
    TICKET_CANCELLED: (K_TICKET, K_BY, K_REASON),
    TICKET_RERUN: (K_TICKET, K_BY),
    DIFFICULTY_RAISED: (K_KIND, K_FROM, K_TO),
    VERDICT: (K_SUBJECT_KIND, K_SUBJECT, K_VERDICT_TYPE, K_PASS, K_SESSION_ID, K_MODEL, K_FINDINGS, K_RUNG, K_FALLBACK_FROM, K_MODEL_RAN),
    FINDING: (K_ID, K_TICKET, K_TEXT, K_PROVENANCE, K_NEGATIVE, K_HEADING, K_REPLACES, K_OBJECTIVES, K_EVIDENCE, K_REASON,
              K_REPLACES_OWNER, K_RESULT),
    PROGRESS: (K_METRIC, K_VALUE, K_TICKET, K_RUN_ID, K_KEPT, K_GOAL),
    DISCARDED: (K_TICKET, K_METRIC, K_BEST, K_SD, K_SEEDS, K_GOAL),
    PROPOSAL_ADMITTED: (K_ID, K_FROM, K_KIND, K_TICKET),
    PROPOSAL_PARKED: (K_ID, K_FROM, K_KIND, K_REASON),
    DECISION_OPENED: (K_TICKET, K_BLOCKING, K_HUMAN_ONLY),
    DECISION: (K_TICKET, K_ANSWER, K_DECIDED_BY, K_RATIONALE, K_CONFIDENCE, K_MODEL, K_FALLBACK_FROM),
    JOB_LAUNCHED: (K_JOB, K_TICKET, K_UNIT, K_GPU_UUIDS, K_CORES, K_RAM_GB, K_ATTEMPT, K_TOOLS, K_ENVIRONMENT, K_COMMIT),
    JOB_FINISHED: (K_JOB, K_EXIT_CODE, K_SECONDS, K_OUTPUTS_OK),
    JOB_RETRIED: (K_JOB, K_ATTEMPT, K_OOM, K_OVERRIDES),
    JOB_FAILED: (K_JOB, K_REASON, K_LOG_TAIL),
    JOB_CANCELLED: (K_JOB, K_REASON, K_LOG_TAIL),
    JOB_WAITING: (K_JOB, K_TICKET, K_REASON),
    MANIFEST: (K_PATH, K_SHA256, K_SIZE, K_JOB, K_RUN_ID),
    WAVE: (K_NUMBER, K_OUTCOMES, K_PROGRESSED),
    STALL: (K_WAVES, K_ACTION),
    PROMOTED: (K_SLUG, K_FROM_LEVEL, K_TO_LEVEL, K_TRIGGER),
    DEMOTED: (K_SLUG, K_FROM_LEVEL, K_TO_LEVEL, K_TRIGGER),
    ABSORBED: (K_SLUG, K_LEVEL, K_SESSION_ID, K_CHUNKS, K_ENTRIES, K_COVERAGE_PASS),
    CONSULTED: (K_SLUG, K_BY, K_QUESTION_SHA256, K_PROMOTE_REQUESTED, K_SESSION_ID),
    NOTIFIED: (K_EVENT, K_CHANNEL, K_OK, K_EXIT_CODE),
    CONTROL: (K_COMMAND, K_ARGS, K_BY),
    SWITCHED: (K_FROM, K_TO),
    FEEDBACK: (K_ID, K_SOURCE),
    CHANGE_RECORD: (K_ID, K_SCOPE_KIND, K_MECHANISM, K_FIXTURE),
    TAGGED: (K_TAG,),
    PINNED: (K_TAG, K_PREVIOUS),
    REPORT_RENDERED: (K_SHA256, K_CLAIMS, K_TAGGED, K_LINTER_PASS, K_REPORT, K_EDITED),
    PAPER_STARTED: (K_VENUE,),
    FIGURE_RESULT: (K_FIGURE_ID, K_VERSION, K_PATH, K_SHA256, K_STATUS, K_REASON),
    OBJECTIVE: (K_ID, K_TEXT, K_STATUS, K_MEASURE, K_BY, K_PROPOSAL),
    MARKED: (K_BATCH, K_ITEM, K_MARK, K_NOTE, K_BY),
    DOCUMENT: (K_ID, K_TITLE, K_KIND, K_VERSION, K_CONVERTER, K_BY),
    CODE_PUSHED: (K_COMMIT, K_REMOTE, K_MAIN),
    TOOL_INSTALLED: (K_TICKET, K_NAME, K_OUTCOME, K_VERSION, K_ATTEMPT, K_REASON),
    PASSAGE: (K_ID, K_SECTION, K_HEADING, K_TEXT, K_REPLACES, K_BY, K_OBJECTIVES, K_EVIDENCE, K_DOC, K_STANDING, K_REASON,
              K_WITHDRAWN, K_MOVED_FROM, K_REPLACES_OWNER, K_CONSOLIDATES, K_MERGES),
    SCOUTED: (K_IDENTIFIER, K_OUTCOME, K_SLUG),
    CONSOLIDATED: (K_SECTION, K_REPLACED, K_WRITTEN, K_MODEL),
    CONCERN: (K_ID, K_STATUS, K_PLACE, K_OBJECTIVES, K_BY),
    REVIEWED: (K_DECISION, K_REVIEW, K_ANSWER, K_BY),
    RESULT: (K_ID, K_HEADING, K_ACTION, K_INTO, K_FROM, K_BY),
    VERIFICATION: (K_HEADING, K_STANDING, K_ROUTE, K_BY, K_RELEASED),
    DRAWING: (K_RESULT, K_VERSION, K_TICKET, K_REST, K_OUTCOME, K_PLOTS, K_LEFT_OUT, K_RETIRED, K_REASON),
    OBJECTIVE_PROPOSED: (K_ID, K_KIND, K_OBJECTIVE, K_TICKET, K_BY, K_UPHELD, K_WHY, K_ANSWER, K_PROPOSAL),
}

# The values the spec table enumerates for a payload key; checked when the key is present.
PAYLOAD_ENUMS = {
    (RUN_ENDED, K_REASON): ("frontier_empty", "goal_reached", "stopped", "stall_strict", "switched", "objectives_closed",
                            "budget_spent"),
    (PACING, K_ACTION): ("normal", "cheap_only", "stop"),
    (PACING, K_FABLE_ACTION): ("normal", "cheap_only", "stop"),
    (PAUSED, K_WINDOW): ("five_hour", "seven_day", "unknown"),
    (PAUSED, K_MODEL): ("fable",),
    (UNPAUSED, K_MODEL): ("fable",),
    (TICKET_RESUMED, K_REASON): ("invalid_result", "acceptance_failed", "worker_died", "timeout", "readopted"),
    (ACCEPTANCE, K_WHERE): ("worktree", "rebased", "main"),
    (INTEGRATED, K_RESOLVED_BY): ("none", "integrator"),
    # `none`: a drawing that still fails takes no step; its result keeps its last accepted drawing (decision 17; ticket 100).
    (TICKET_FAILED, K_NEXT): ("resume", "tier_up", "split", "needs_human", "none"),
    # Why a ticket was handed to a person when the escalation chain named it (decision 16); absent for any other hand-off.
    (TICKET_NEEDS_HUMAN, K_REASON): ("top_rung",),
    (VERDICT, K_SUBJECT_KIND): ("ticket", "claim", "figure", "spec", "dossier", "paper"),
    (PROPOSAL_PARKED, K_REASON): ("radius", "duplicate", "cap", "blockers", "touches"),
    (DECISION, K_DECIDED_BY): ("human", "decider", "conductor"),
    (DECISION, K_FALLBACK_FROM): ("fable",),
    (JOB_RETRIED, K_OOM): ("host", "gpu"),
    (STALL, K_ACTION): ("replan", "stop"),
    (NOTIFIED, K_CHANNEL): ("notify-send", "hermes", "none"),
    (CONTROL, K_COMMAND): ("pause", "resume", "stop", "cancel", "rerun", "autonomy", "pacing", "model_fallback", "ladder_changes", "environment",
                         "stop_when", "budget"),
    # `retrospective` is the one code files after a run ended (ticket 45), read by the evolver like the owner's.
    # `figure` is the figure role's, carrying the traps a figure result would promote into the plot index (ticket 50).
    (FEEDBACK, K_SOURCE): ("cli", "dashboard", "file", "retrospective", "figure"),
    (CHANGE_RECORD, K_SCOPE_KIND): ("local", "global"),
    (OBJECTIVE, K_STATUS): ("open", "parked", "answered", "dropped", "reframed"),
    # Who made the change: the owner's word, the decider's answer, or code (a goal reached from its measured values).
    (OBJECTIVE, K_BY): ("owner", "decider", "code"),
    (FIGURE_RESULT, K_STATUS): ("candidates_ranked", "selected", "verified", "failed_checks", "honesty_failed", "refused", "blocked"),
    (MARKED, K_BY): ("owner", "decider"),
    (DOCUMENT, K_KIND): ("inherited", "critique", "other"),
    # The session's sort (`wayline document add --kind`), or code's cautious guess at a file dropped with no session.
    (DOCUMENT, K_BY): ("session", "code"),
    (TOOL_INSTALLED, K_OUTCOME): ("installed", "recorded", "failed"),
    # Results only for an inherited passage (`by: document:<id>`); a ticket's Results passage is a finding.
    (PASSAGE, K_SECTION): ("introduction", "results", "discussion", "methods", "references"),
    (PASSAGE, K_STANDING): ("unchecked", "unverifiable"),
    (PASSAGE, K_EVIDENCE): ("supports", "narrows", "contradicts"),
    (FINDING, K_EVIDENCE): ("supports", "narrows", "contradicts"),
    (SCOUTED, K_OUTCOME): ("found", "no such work", "failed"),
    (CONCERN, K_STATUS): ("open", "answered", "declined"),
    (CONCERN, K_PLACE): ("objectives", "order", "declined"),
    # The critique splitter's session, code (a comment thread, a reframe or a drop followed, an answer), the critic's
    # proposal, or the owner's or the decider's placement.
    (CONCERN, K_BY): ("session", "code", "critic", "owner", "decider"),
    (REVIEWED, K_REVIEW): ("stand", "reverse"),
    (REVIEWED, K_BY): ("owner",),
    (RESULT, K_ACTION): ("created", "merged", "renamed"),
    # Code clusters a finding into a result at its acceptance; only the owner merges or renames one.
    (RESULT, K_BY): ("code", "owner"),
    (VERIFICATION, K_STANDING): ("unchecked", "verified", "unverifiable"),
    (VERIFICATION, K_ROUTE): ("reproduced", "ported", "reimplemented", "read"),
    # Code (a result found or followed, a verdict taken, a needs_human under autonomous), or the owner's or the decider's
    # reply leaving a result unverified.
    (VERIFICATION, K_BY): ("code", "owner", "decider"),
    (DRAWING, K_REST): ("run_end", "checkpoint", "owner"),
    (DRAWING, K_OUTCOME): ("opened", "accepted", "failed"),
    (OBJECTIVE_PROPOSED, K_KIND): ("add", "answer", "park", "drop", "reframe", "reopen"),
    # A ticket result's proposal, or one a verdict made itself, which goes on without a further judgment.
    (OBJECTIVE_PROPOSED, K_BY): ("worker", "verifier"),
}


class LedgerError(ValueError):
    """A write the ledger refuses: an event outside the vocabulary, a path outside research/, a value it cannot write."""


def now_ts():
    """The journal's timestamp: ISO 8601 in UTC with millisecond precision and a Z suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def make_event(event, payload=None, ticket=None, session_id=None, job=None, ts=None):
    """Build and validate one journal record without writing it."""
    if event not in EVENTS:
        raise LedgerError("event %r is not in the journal vocabulary" % (event,))
    payload = dict(payload or {})
    allowed = EVENTS[event]
    unknown = [key for key in payload if key not in allowed]
    if unknown:
        raise LedgerError("event %r does not carry payload key(s) %s; it carries %s" % (event, ", ".join(map(repr, unknown)), list(allowed)))
    for key, value in payload.items():
        values = PAYLOAD_ENUMS.get((event, key))
        if values is not None and value is not None and value not in values:
            raise LedgerError("event %r: %s must be one of %s, got %r" % (event, key, list(values), value))
    record = {
        "ts": ts or now_ts(),
        "event": event,
        "ticket": ticket,
        "session_id": session_id,
        "job": job,
        "payload": payload,
    }
    check(record, load_schema("journal_event"), name="journal event %r" % event)
    return record


# --- the per-process lock state --------------------------------------------------------------
# flock is per open file description, so one process must hold one descriptor per lock file and
# serialize its own threads in front of it; every Ledger of the same project shares this.


class _ProcessLock:
    def __init__(self):
        self.mutex = threading.RLock()
        self.fd = None
        self.depth = 0


_process_locks = {}
_registry_mutex = threading.Lock()


def _process_lock(lock_path):
    with _registry_mutex:
        return _process_locks.setdefault(str(lock_path), _ProcessLock())


def _forget_locks_in_child():
    # A forked child inherits the descriptors but not the right to the parent's lock.
    _process_locks.clear()


os.register_at_fork(after_in_child=_forget_locks_in_child)


class Ledger:
    """The writer for one project's `research/`; every method takes the lock."""

    def __init__(self, project):
        self.project = Path(project).resolve()
        self.research = self.project / "research"
        self.lock_path = self.research / LOCK
        self.journal_path = self.research / JOURNAL

    # --- the lock ---

    @contextmanager
    def lock(self):
        """Hold `flock(research/.lock)`: re-entrant for the holding thread, exclusive for every other thread and process."""
        state = _process_lock(self.lock_path)
        with state.mutex:
            if state.depth == 0:
                self.research.mkdir(parents=True, exist_ok=True)
                fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o644)
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX)
                except BaseException:
                    os.close(fd)
                    raise
                state.fd = fd
            state.depth += 1
            try:
                yield
            finally:
                state.depth -= 1
                if state.depth == 0:
                    fd, state.fd = state.fd, None
                    fcntl.flock(fd, fcntl.LOCK_UN)
                    os.close(fd)

    # --- paths ---

    def path(self, relpath, replacing=False):
        """The absolute path of a file under research/; refuses anything that would land outside it.

        `replacing` marks a write-then-rename, which the append-only journal never accepts.
        The lock file is never a target.
        """
        relative = Path(relpath)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise LedgerError("ledger paths are relative to research/ and stay inside it, got %r" % (relpath,))
        if relative.name == LOCK:
            raise LedgerError("research/%s is the ledger's lock, not a file to write" % LOCK)
        if replacing and relative == Path(JOURNAL):
            raise LedgerError("research/%s is append-only; use append_event" % JOURNAL)
        target = self.research / relative
        if not target.resolve().is_relative_to(self.research.resolve()):
            raise LedgerError("%r resolves outside research/ (through a symlink); refused" % (relpath,))
        return target

    # --- writes ---

    def write_json(self, relpath, value, schema=None):
        """Write a JSON file atomically; with `schema` (a shipped schema name) the value is validated first."""
        if schema is not None:
            check(value, load_schema(schema), name="%s (schema %s)" % (relpath, schema))
        text = _dumps(value, indent=2) + "\n"
        target = self.path(relpath, replacing=True)
        with self.lock():
            atomic_write(target, text)
        return target

    def write_bytes(self, relpath, data):
        """Write a binary file atomically: the e-print source a dossier keeps, a figure a reader looks at.

        The ledger is the only code that writes under `research/`, and a dossier's `source/` and
        `figures/` are files nobody can spell as text, so binary is a write like any other and
        takes the same lock and the same temp-then-rename.
        """
        target = self.path(relpath, replacing=True)
        with self.lock():
            atomic_bytes(target, data)
        return target

    def remove_tree(self, relpath):
        """Remove a directory under `research/` and everything in it; returns whether it was there.

        A removal is a write, so it takes the lock and the path checks like any other. What needs
        it: the `source/` of a dossier whose e-print was refetched at a new version, where leaving
        the old version's files beside the new ones would leave a tree that is neither.
        """
        target = self.path(relpath)
        with self.lock():
            if not target.is_dir():
                return False
            shutil.rmtree(target)
            return True

    def remove_file(self, relpath):
        """Remove one file under `research/`; returns whether it was there.

        What needs it: the knowledge-base node of a dossier that became a pointer when two dossiers
        of one work were joined (decision 17), which would otherwise list the work twice.
        """
        target = self.path(relpath, replacing=True)
        with self.lock():
            if not target.is_file():
                return False
            target.unlink()
            return True

    def write_markdown(self, relpath, text):
        """Write a markdown (or any text) file atomically."""
        target = self.path(relpath, replacing=True)
        if not text.endswith("\n"):
            text += "\n"
        with self.lock():
            atomic_write(target, text)
        return target

    def touch(self, relpath):
        """Create an empty file under research/ when it is absent, and leave it alone when it is not.

        What `init` needs for the line files a project starts with: an empty `journal.jsonl` and
        `findings.jsonl` exist from the first moment, so a reader never has to tell "no file yet"
        from "nothing happened yet", and a second `init` changes neither.
        """
        target = self.path(relpath)
        with self.lock():
            target.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(target, os.O_WRONLY | os.O_CREAT, 0o644)
            os.close(fd)
        return target

    def append_line(self, relpath, line):
        """Append one line to a line file (journal.jsonl, findings.jsonl, qa_log.md), durably.

        A torn last line left by a crashed writer is closed with a newline first, so the new
        record never glues onto it; readers skip the torn line.
        """
        bad = [char for char in _LINE_BREAKS if char in line]
        if bad:
            raise LedgerError("a line file takes one line at a time; the line contains %s" % ", ".join("U+%04X" % ord(char) for char in bad))
        target = self.path(relpath)
        with self.lock():
            target.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(target, os.O_RDWR | os.O_APPEND | os.O_CREAT, 0o644)
            try:
                data = (line + "\n").encode("utf-8")
                size = os.fstat(fd).st_size
                if size > 0 and os.pread(fd, 1, size - 1) != b"\n":
                    _log.warning("%s ended without a newline (a torn line); closing it before appending", target)
                    data = b"\n" + data
                view = memoryview(data)
                while view:
                    written = os.write(fd, view)
                    view = view[written:]
                os.fsync(fd)
            finally:
                os.close(fd)
        return target

    def append_record(self, relpath, value):
        """Append one JSON object to a line file (`findings.jsonl`), spelled as the journal spells its own.

        The journal is not the only line file of structured records, and a second spelling of
        "one object per line" would be a second set of escaping rules to get wrong.
        """
        self.append_line(relpath, _escape_line_breaks(_dumps(value, separators=(",", ":"))))
        return value

    def append_event(self, event, payload=None, ticket=None, session_id=None, job=None, ts=None):
        """Validate and append one journal event; returns the record written.

        The timestamp is taken under the lock, so the journal's file order and its `ts` order agree.
        """
        with self.lock():
            record = make_event(event, payload, ticket=ticket, session_id=session_id, job=job, ts=ts or now_ts())
            self.append_line(JOURNAL, _escape_line_breaks(_dumps(record, separators=(",", ":"))))
        return record

    # --- reads (anyone may read; these are conveniences for replay) ---

    def count_events(self, event, ticket):
        """How many `event` records the journal holds for `ticket`: what a per-ticket cap counts (the consultant's, the scout's)."""
        events, _ = self.read_events()
        return sum(1 for record in events if record.get("event") == event and record.get("ticket") == ticket)

    def read_events(self, offset=0):
        """The journal events from byte `offset` on, and the offset after the last whole line.

        A line that is not JSON (a torn line closed by a later append) is skipped with a warning.
        """
        if not self.journal_path.exists():
            return [], 0
        events = []
        with open(self.journal_path, "rb") as handle:
            handle.seek(offset)
            position = offset
            for raw in handle:
                if not raw.endswith(b"\n"):
                    break  # a line still being written; read it next time
                position += len(raw)
                if not raw.strip():
                    continue
                try:
                    events.append(json.loads(raw.decode("utf-8")))
                except ValueError:
                    _log.warning("%s: skipping a torn line at byte %d", self.journal_path, position - len(raw))
        return events, position

    def read_json(self, relpath):
        with open(self.path(relpath), encoding="utf-8") as handle:
            return json.load(handle)

    # --- the conductor's heartbeat ---

    def heartbeat(self):
        """The heartbeat of the one conductor this project may run (decision 5); `acquire` it first."""
        return Heartbeat(self)


class ConductorBusy(LedgerError):
    """Another conductor holds this project's heartbeat; `holder` is what its heartbeat says."""

    def __init__(self, project, holder):
        self.project = project
        self.holder = holder
        pid = holder.get("pid") if isinstance(holder, dict) else None
        super().__init__("another conductor%s is running on %s" % (" (pid %s)" % pid if pid else "", project))


class Heartbeat:
    """`research/conductor.json`, and the `flock` on it that keeps a second conductor out.

    The lock is held for the life of one conductor, on one open descriptor, and it dies with the
    process however the process dies, which is what lets a killed conductor be resumed at once.
    The descriptor is not inheritable (PEP 446), so a worker the conductor starts, which outlives
    it by design, never holds the lock on its behalf.

    The file is rewritten in place rather than renamed over, because a rename would move the
    lock's inode out from under every later reader. The new record is written whole before the
    old tail is cut, so a reader that catches the moment in between still reads a whole first
    line, which is all `read_heartbeat` trusts.
    """

    def __init__(self, ledger):
        self.ledger = ledger
        self.path = ledger.path(HEARTBEAT)
        self.fd = None

    def acquire(self, tries=HEARTBEAT_TRIES):
        """Take the lock or raise `ConductorBusy`; returns the heartbeat.

        A reader's probe (`conductor_holder`) holds a shared lock for an instant, so a conductor
        starting in that instant tries `tries` times, `HEARTBEAT_PAUSE_S` apart, before it
        concludes that another conductor is running. The file is created under the ledger's lock,
        like every other write under `research/`.
        """
        with self.ledger.lock():
            fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        for attempt in range(max(1, int(tries))):
            if attempt:
                time.sleep(HEARTBEAT_PAUSE_S)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                continue
            except BaseException:
                os.close(fd)
                raise
            self.fd = fd
            return self
        os.close(fd)
        raise ConductorBusy(self.ledger.project, read_heartbeat(self.ledger.project) or {})

    def write(self, pid, started_at, last_wave_at, harness_tag):
        """Rewrite the heartbeat: the conductor's pid, when its run started, its last wave, its harness tag."""
        if self.fd is None:
            raise LedgerError("the heartbeat is written only by the conductor holding its lock")
        record = {"pid": pid, "started_at": started_at, "last_wave_at": last_wave_at, "harness_tag": harness_tag}
        data = (_dumps(record, separators=(", ", ": ")) + "\n").encode("utf-8")
        with self.ledger.lock():
            os.pwrite(self.fd, data, 0)
            os.ftruncate(self.fd, len(data))
            os.fsync(self.fd)
        return record

    def release(self):
        """Let go of the lock; the file stays, holding the last heartbeat for the tick to read."""
        if self.fd is not None:
            fd, self.fd = self.fd, None
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)


def read_heartbeat(project):
    """The last heartbeat a conductor wrote in this project, or None when there is none to read.

    Only the first line is read, and a read that catches a rewrite halfway is read again, up to
    `HEARTBEAT_READS` times.
    """
    path = ledger_for(project).research / HEARTBEAT
    for _ in range(HEARTBEAT_READS):
        try:
            with open(path, "rb") as handle:
                line = handle.readline()
        except FileNotFoundError:
            return None
        try:
            record = json.loads(line.decode("utf-8"))
        except ValueError:
            continue
        return record if isinstance(record, dict) else None
    return None


def conductor_holder(project):
    """The heartbeat of the conductor running on this project, or None when none is running.

    The lock answers the question, not the pid in the file: a pid can outlive its meaning or be
    reused, and the lock of a dead process is already gone. A conductor that holds the lock and
    has not yet written a heartbeat is named by an empty record.
    """
    path = ledger_for(project).research / HEARTBEAT
    try:
        fd = os.open(path, os.O_RDONLY)
    except FileNotFoundError:
        return None
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            return read_heartbeat(project) or {}
        fcntl.flock(fd, fcntl.LOCK_UN)
        return None
    finally:
        os.close(fd)


def ledger_for(project_or_ledger):
    """A `Ledger`, from one or from the project path of one.

    Every function that writes to the ledger takes either, so a caller with a ledger in hand
    does not open a second one and a caller with only a path does not have to build it.
    """
    return project_or_ledger if isinstance(project_or_ledger, Ledger) else Ledger(project_or_ledger)


def _dumps(value, **options):
    """JSON text, refusing NaN and Infinity (which are not JSON) and unserializable values."""
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False, **options)
    except ValueError as failure:  # NaN or Infinity
        raise LedgerError("the ledger cannot write %s" % failure) from None
    except TypeError as failure:
        raise LedgerError("the ledger cannot write %s" % failure) from None


def _escape_line_breaks(text):
    """Escape the line-breaking characters json.dumps leaves raw, so one record stays one line."""
    for char in "\x85  ":
        if char in text:
            text = text.replace(char, "\\u%04x" % ord(char))
    return text


def atomic_write(target, text):
    """Write `text` to a temp file next to `target`, fsync, and rename it into place."""
    return atomic_bytes(target, text.encode("utf-8"))


def atomic_bytes(target, data):
    """Write `data` to a temp file next to `target`, fsync, and rename it into place.

    The new file gets the mode of the file it replaces, else 0666 under the umask, so a rewrite
    never narrows who can read a ledger file.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        mode = stat.S_IMODE(os.stat(target).st_mode)
    except FileNotFoundError:
        mode = None
    temp = target.parent / (".%s.%s.tmp" % (target.name, uuid.uuid4().hex))
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
    try:
        with os.fdopen(fd, "wb") as handle:
            if mode is not None:
                os.fchmod(handle.fileno(), mode)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, target)
    except BaseException:
        try:
            os.unlink(temp)
        except FileNotFoundError:
            pass
        raise
    directory = os.open(target.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
