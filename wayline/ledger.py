"""The ledger: the only code that writes under a project's `research/` (Implementation Decisions 2).

Every other module returns structured values and the ledger writes them: JSON and markdown by
write-to-temp-then-rename, `journal.jsonl` and the other line files by append. Every write takes
`fcntl.flock` on `research/.lock`, because the conductor, the tick, the dashboard, and the CLI
verbs are separate processes that all write through this module.

The journal is the bus: one JSON object per line with `ts`, `event`, `ticket`, `session_id`,
`job`, `payload`. The event names and the payload keys below are the vocabulary of the spec's
table; `append_event` refuses an event or a key outside it, and a test cross-checks the
constants against the spec so the two cannot drift silently.
"""

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from wayline.jsonschema import check, load_schema

__all__ = ["Ledger", "LedgerError", "make_event", "now_ts", "EVENTS", "PAYLOAD_ENUMS", "JOURNAL", "LOCK"]

JOURNAL = "journal.jsonl"
LOCK = ".lock"

# --- event names -----------------------------------------------------------------------------

RUN_STARTED = "run_started"
RUN_ENDED = "run_ended"
PHASE = "phase"
PACING = "pacing"
PAUSED = "paused"
UNPAUSED = "unpaused"
TICKET_CREATED = "ticket_created"
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
MANIFEST = "manifest"
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
K_ACTION = "action"
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
K_SHA256 = "sha256"
K_SIZE = "size"
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

# --- the vocabulary: event -> payload keys, in the spec table's order ------------------------

EVENTS = {
    RUN_STARTED: (K_RESUME, K_HARNESS_TAG, K_AUTONOMY, K_RADIUS, K_PID),
    RUN_ENDED: (K_REASON,),
    PHASE: (K_FROM, K_TO),
    PACING: (K_FIVE_HOUR, K_SEVEN_DAY, K_ACTION),
    PAUSED: (K_RESETS_AT, K_WINDOW, K_UTILIZATION),
    UNPAUSED: (),
    TICKET_CREATED: (K_TICKET, K_KIND, K_PROPOSED_BY, K_ORIGIN, K_BLOCKED_BY),
    TICKET_LAUNCHED: (K_TICKET, K_ATTEMPT, K_ROLE, K_MODEL, K_EFFORT, K_SKILLS, K_WORKTREE, K_PID, K_CONTEXT_CHARS, K_PROMPT_SHA256),
    TICKET_SESSION: (K_TICKET, K_ATTEMPT, K_SESSION_ID, K_MODEL),
    TICKET_RESULT: (K_TICKET, K_ATTEMPT, K_SESSION_ID, K_STATUS, K_TURNS, K_DURATION_MS, K_USAGE, K_PERMISSION_DENIALS, K_VALID),
    TICKET_RESUMED: (K_TICKET, K_ATTEMPT, K_SESSION_ID, K_REASON),
    ACCEPTANCE: (K_TICKET, K_ATTEMPT, K_WHERE, K_PASS, K_RESULTS),
    INTEGRATED: (K_TICKET, K_COMMIT, K_RESOLVED_BY),
    TICKET_DONE: (K_TICKET,),
    TICKET_ACCEPTED: (K_TICKET,),
    TICKET_FAILED: (K_TICKET, K_ATTEMPT, K_REASON, K_NEXT),
    TICKET_BLOCKED: (K_TICKET, K_PATH),
    TICKET_NEEDS_HUMAN: (K_TICKET, K_QUESTION),
    TICKET_CANCELLED: (K_TICKET, K_BY),
    TICKET_RERUN: (K_TICKET, K_BY),
    DIFFICULTY_RAISED: (K_KIND, K_FROM, K_TO),
    VERDICT: (K_SUBJECT_KIND, K_SUBJECT, K_VERDICT_TYPE, K_PASS, K_SESSION_ID, K_MODEL, K_FINDINGS),
    FINDING: (K_ID, K_TICKET, K_TEXT, K_PROVENANCE, K_NEGATIVE),
    PROGRESS: (K_METRIC, K_VALUE, K_TICKET, K_RUN_ID, K_KEPT),
    DISCARDED: (K_TICKET, K_METRIC, K_BEST, K_SD, K_SEEDS),
    PROPOSAL_ADMITTED: (K_ID, K_FROM, K_KIND, K_TICKET, K_REASON),
    PROPOSAL_PARKED: (K_ID, K_FROM, K_KIND, K_TICKET, K_REASON),
    DECISION_OPENED: (K_TICKET, K_BLOCKING, K_HUMAN_ONLY),
    DECISION: (K_TICKET, K_ANSWER, K_DECIDED_BY, K_RATIONALE, K_CONFIDENCE),
    JOB_LAUNCHED: (K_JOB, K_TICKET, K_UNIT, K_GPU_UUIDS, K_CORES, K_RAM_GB, K_ATTEMPT),
    JOB_FINISHED: (K_JOB, K_EXIT_CODE, K_SECONDS, K_OUTPUTS_OK),
    JOB_RETRIED: (K_JOB, K_ATTEMPT, K_OOM, K_OVERRIDES),
    JOB_FAILED: (K_JOB, K_REASON, K_LOG_TAIL),
    JOB_CANCELLED: (K_JOB, K_REASON, K_LOG_TAIL),
    MANIFEST: (K_PATH, K_SHA256, K_SIZE, K_JOB, K_RUN_ID),
    STALL: (K_WAVES, K_ACTION),
    PROMOTED: (K_SLUG, K_FROM_LEVEL, K_TO_LEVEL, K_TRIGGER),
    DEMOTED: (K_SLUG, K_FROM_LEVEL, K_TO_LEVEL, K_TRIGGER),
    ABSORBED: (K_SLUG, K_LEVEL, K_SESSION_ID, K_CHUNKS, K_ENTRIES, K_COVERAGE_PASS),
    CONSULTED: (K_SLUG, K_BY, K_QUESTION_SHA256, K_PROMOTE_REQUESTED, K_SESSION_ID),
    NOTIFIED: (K_EVENT, K_CHANNEL, K_OK),
    CONTROL: (K_COMMAND, K_ARGS, K_BY),
    SWITCHED: (K_FROM, K_TO),
    FEEDBACK: (K_ID, K_SOURCE),
    CHANGE_RECORD: (K_ID, K_SCOPE_KIND, K_MECHANISM, K_FIXTURE),
    TAGGED: (K_TAG,),
    PINNED: (K_TAG, K_PREVIOUS),
    REPORT_RENDERED: (K_SHA256, K_CLAIMS, K_TAGGED, K_LINTER_PASS),
    PAPER_STARTED: (K_VENUE,),
}

# The values the spec table enumerates for a payload key; checked when the key is present.
PAYLOAD_ENUMS = {
    (RUN_ENDED, K_REASON): ("frontier_empty", "goal_reached", "stopped", "stall_strict", "switched"),
    (PACING, K_ACTION): ("normal", "cheap_only", "stop"),
    (PAUSED, K_WINDOW): ("five_hour", "seven_day", "unknown"),
    (TICKET_RESUMED, K_REASON): ("invalid_result", "acceptance_failed", "worker_died", "timeout"),
    (ACCEPTANCE, K_WHERE): ("worktree", "rebased", "main"),
    (INTEGRATED, K_RESOLVED_BY): ("none", "integrator"),
    (TICKET_FAILED, K_NEXT): ("resume", "tier_up", "split", "needs_human"),
    (VERDICT, K_SUBJECT_KIND): ("ticket", "claim", "figure", "spec", "dossier", "paper"),
    (PROPOSAL_ADMITTED, K_REASON): ("radius", "duplicate", "cap", "blockers"),
    (PROPOSAL_PARKED, K_REASON): ("radius", "duplicate", "cap", "blockers"),
    (DECISION, K_DECIDED_BY): ("human", "decider"),
    (JOB_RETRIED, K_OOM): ("host", "gpu"),
    (STALL, K_ACTION): ("replan", "stop"),
    (NOTIFIED, K_CHANNEL): ("notify-send", "hermes", "none"),
    (CONTROL, K_COMMAND): ("pause", "resume", "stop", "cancel", "rerun", "autonomy", "pacing"),
    (FEEDBACK, K_SOURCE): ("cli", "dashboard", "file"),
    (CHANGE_RECORD, K_SCOPE_KIND): ("local", "global"),
}


class LedgerError(ValueError):
    """A write the ledger refuses: an event outside the vocabulary, a path outside research/, an invalid value."""


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


class Ledger:
    """The writer for one project's `research/`; every method takes the lock."""

    def __init__(self, project):
        self.project = Path(project)
        self.research = self.project / "research"
        self.lock_path = self.research / LOCK
        self.journal_path = self.research / JOURNAL
        self._lock_fd = None
        self._lock_depth = 0

    # --- the lock ---

    @contextmanager
    def lock(self):
        """Hold `flock(research/.lock)`; re-entrant within one Ledger, exclusive across processes."""
        if self._lock_depth == 0:
            self.research.mkdir(parents=True, exist_ok=True)
            fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o644)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
            except BaseException:
                os.close(fd)
                raise
            self._lock_fd = fd
        self._lock_depth += 1
        try:
            yield
        finally:
            self._lock_depth -= 1
            if self._lock_depth == 0:
                fd, self._lock_fd = self._lock_fd, None
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)

    # --- paths ---

    def path(self, relpath):
        """The absolute path of a file under research/; refuses anything outside it."""
        relative = Path(relpath)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise LedgerError("ledger paths are relative to research/ and stay inside it, got %r" % (relpath,))
        return self.research / relative

    # --- writes ---

    def write_json(self, relpath, value, schema=None):
        """Write a JSON file atomically; with `schema` (a shipped schema name) the value is validated first."""
        if schema is not None:
            check(value, load_schema(schema), name="%s (schema %s)" % (relpath, schema))
        text = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
        target = self.path(relpath)
        with self.lock():
            _atomic_write(target, text)
        return target

    def write_markdown(self, relpath, text):
        """Write a markdown (or any text) file atomically."""
        target = self.path(relpath)
        if not text.endswith("\n"):
            text += "\n"
        with self.lock():
            _atomic_write(target, text)
        return target

    def append_line(self, relpath, line):
        """Append one line to a line file (journal.jsonl, findings.jsonl, qa_log.md), durably."""
        if "\n" in line or "\r" in line:
            raise LedgerError("a line file takes one line at a time; the line contains a line break")
        target = self.path(relpath)
        with self.lock():
            target.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(target, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
            try:
                data = (line + "\n").encode("utf-8")
                view = memoryview(data)
                while view:
                    written = os.write(fd, view)
                    view = view[written:]
                os.fsync(fd)
            finally:
                os.close(fd)
        return target

    def append_event(self, event, payload=None, ticket=None, session_id=None, job=None, ts=None):
        """Validate and append one journal event; returns the record written."""
        record = make_event(event, payload, ticket=ticket, session_id=session_id, job=job, ts=ts)
        self.append_line(JOURNAL, json.dumps(record, separators=(",", ":"), ensure_ascii=False))
        return record

    # --- reads (anyone may read; these are conveniences for replay) ---

    def read_events(self, offset=0):
        """The journal events from byte `offset` on, and the offset after the last whole line."""
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
                if raw.strip():
                    events.append(json.loads(raw.decode("utf-8")))
        return events, position

    def read_json(self, relpath):
        with open(self.path(relpath), encoding="utf-8") as handle:
            return json.load(handle)


def _atomic_write(target, text):
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix="." + target.name + ".", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, target)
    except BaseException:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise
    directory = os.open(target.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
