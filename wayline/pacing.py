"""Pacing and the pause on usage limits (Implementation Decisions 5, wave step 8; decision 3, the stream).

The subscription has two windows, the five-hour session and the week, and every model draws on
both. The conductor reads how full they are from two surfaces: the `rate_limit_event` messages in
every worker's stream (`unifiedWindows.five_hour` and `seven_day`), and `claude -p "/usage"` at
`run` start. From the fuller window it takes an action: `stop` at or above `pacing.stop_at`,
`cheap_only` at or above `pacing.cheap_at`, else `normal`. A limit that was hit anyway, by any of
the signals below, pauses the run until the window resets.

Fable is also counted in a weekly window of its own (decision 15), which the Fable line of `/usage`
prints and which only a Fable request's own `rate_limit_event` carries, as
`seven_day_overage_included`. It never moves the action. A refusal on that window, or a reading of
it at `pacing.stop_at`, holds only the launches on Fable (a `Limit` whose `model` is `fable`) while
everything else keeps launching, and `cheap_at` does not apply to it, since Fable has no cheaper tier.

Like `wayline.schedule`, nothing here reads the ledger or the clock: the time is passed in, so a
test can stand on either side of a reset without sleeping. The one thing read from the machine is
its local time zone, for a reset the CLI printed as wall-clock prose without naming a zone.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from wayline.schedule import CHEAP_ONLY, NORMAL, STOP

__all__ = [
    "FIVE_HOUR", "SEVEN_DAY", "UNKNOWN", "WINDOWS", "FABLE", "FABLE_LIMIT_TYPE", "READINGS", "STOP_AT", "CHEAP_AT",
    "FALLBACK_PAUSE_S", "EVENT_SIGNAL", "API_SIGNAL", "MESSAGE_SIGNAL", "SUBAGENT_SIGNAL", "READING_SIGNAL",
    "SESSION_RE", "WEEK_RE", "FABLE_RE",
    "Reading", "Windows", "Usage", "Limit",
    "action_for", "thresholds", "parse_usage", "parse_reset", "rejected", "hit_limit", "resets_at",
    "paused_payload", "iso", "epoch",
]

# The windows of decision 3, as the `paused` event names them.
FIVE_HOUR, SEVEN_DAY, UNKNOWN = "five_hour", "seven_day", "unknown"
WINDOWS = (FIVE_HOUR, SEVEN_DAY)

# Fable's weekly window (decision 15). `fable` names its reading in the `pacing` event and the model a
# hold's `paused` and `unpaused` carry; the stream names it `seven_day_overage_included`; a hold's
# `paused` journals it as the `seven_day` window, since it is a week.
FABLE = "fable"
FABLE_LIMIT_TYPE = "seven_day_overage_included"
# Every reading a `pacing` event carries: the two windows every model draws on, then Fable's.
READINGS = WINDOWS + (FABLE,)

# `policy.pacing` as decision 14 ships it; a project's `harness.json` and a `control pacing` override them.
STOP_AT, CHEAP_AT = 0.90, 0.80

# How long a pause lasts when neither the signal nor any reading says when the window resets.
FALLBACK_PAUSE_S = 5 * 3600

# How long each window lasts: a reading older than its window has reset at least once since.
WINDOW_S = {FIVE_HOUR: 5 * 3600, SEVEN_DAY: 7 * 24 * 3600, FABLE: 7 * 24 * 3600}

# Where a window's reset is looked for when its own is not known. Either all-models window stands in
# for the other; Fable's week resets with the all-models week on this account (decision 15), and never
# with the five-hour window.
RESETS_WITH = {FIVE_HOUR: WINDOWS, SEVEN_DAY: WINDOWS, FABLE: (SEVEN_DAY,)}

# The signals of a hit limit, as `Limit.signal` names the one that fired: the three of decision 5; a
# subagent's failed task inside a session whose own result stays a success (decision 15); and a
# reading of Fable's weekly window at `pacing.stop_at`, which holds Fable launches before anything is refused.
EVENT_SIGNAL, API_SIGNAL, MESSAGE_SIGNAL = "rate_limit_event", "api_error_status", "message"
SUBAGENT_SIGNAL, READING_SIGNAL = "subagent", "reading"
REJECTED = "rejected"
LIMIT_STATUS = 429

# The two regexes of decision 5, verbatim, over the text `/usage` prints. The week's reset and the
# zone each reset names in parentheses are read beside them, from where those matches end.
SESSION_RE = re.compile(r"Current session: (\d+)% used · resets (.+?) \(")
WEEK_RE = re.compile(r"Current week \(all models\): (\d+)% used")
_WEEK_RESET_RE = re.compile(r"Current week \(all models\): \d+% used · resets (.+?) \(")
# The regex of decision 15, verbatim, over the Fable line the same `/usage` prints.
FABLE_RE = re.compile(r"Current week \(Fable\): (\d+)% used · resets (.+?) \(")
_ZONE_RE = re.compile(r"([^)\n]*)\)")

# "You've hit your session limit · resets 3:45pm", optionally followed by a zone in parentheses.
_MESSAGE_RESET_RE = re.compile(r"resets\s+([^(\n]+?)\s*(?:\(([^)\n]*)\))?\s*$", re.MULTILINE)

# The reset prose the CLI prints: `3:45pm`, `5am`, `Sep 11, 10:10pm`, `Mon 12:00am`.
_CLOCK_RE = re.compile(
    r"(?:(?P<name>[A-Za-z]+)\.?\s+(?:(?P<day>\d{1,2}),?\s+)?(?:at\s+)?)?"
    r"(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<half>am|pm)\Z",
    re.IGNORECASE,
)
_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
_WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def _fraction(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


# --- the action ------------------------------------------------------------------------------


def action_for(five_hour, seven_day, stop_at=STOP_AT, cheap_at=CHEAP_AT):
    """`stop`, `cheap_only`, or `normal` for two utilizations (0..1, None when unknown).

    The same thresholds apply to both windows (spec decision): a fan-out can exhaust the week
    before the session window resets, so a full week is as much a reason to stop as a full session.
    """
    readings = [value for value in (five_hour, seven_day) if value is not None]
    if any(value >= stop_at for value in readings):
        return STOP
    if any(value >= cheap_at for value in readings):
        return CHEAP_ONLY
    return NORMAL


def thresholds(*layers):
    """`(stop_at, cheap_at)`: the defaults, overridden layer by layer, later layers winning.

    The conductor passes `policy.pacing`, then `harness.json`'s `pacing`, then the thresholds a
    `control pacing` event set. A value that is not a fraction between 0 and 1 is passed over, so a
    mistyped override leaves the layer beneath it standing rather than stopping the run.
    """
    chosen = {"stop_at": STOP_AT, "cheap_at": CHEAP_AT}
    for layer in layers:
        if not isinstance(layer, dict):
            continue
        for key in chosen:
            value = _fraction(layer.get(key))
            if value is not None and 0 <= value <= 1:
                chosen[key] = value
    return chosen["stop_at"], chosen["cheap_at"]


# --- the readings ----------------------------------------------------------------------------


@dataclass
class Reading:
    """One window as last read: its utilization, when it resets (epoch seconds), and when it was read."""

    utilization: float
    resets_at: Optional[int] = None
    observed_at: Optional[float] = None


class Windows:
    """The latest reading of each window, whichever surface it came from.

    A reading is replaced only by one read at the same moment or later, so a `pacing` event a
    restart replays cannot undo the `/usage` reading the run took before its first wave. A reading
    whose window has reset since is no reading at all: the CLI drops a window once its reset passes,
    and holding on to a utilization of 1.0 past the reset would keep a run stopped that nothing
    will ever start again. A reading that names no reset (a `pacing` event carries none) has reset
    once it is older than its window, which is the latest it can have.
    """

    def __init__(self):
        self.readings = {}

    def record(self, name, utilization, resets_at=None, observed_at=None):
        """Take one window's reading; returns whether it replaced the one held."""
        utilization = _fraction(utilization)
        if name not in READINGS or utilization is None:
            return False
        held = self.readings.get(name)
        if held is not None and None not in (held.observed_at, observed_at) and observed_at < held.observed_at:
            return False
        self.readings[name] = Reading(utilization, resets_at, observed_at)
        return True

    def observe(self, event, now, names=READINGS):
        """Take the windows of one `rate_limit_event` that are among `names`; one without `unifiedWindows` carries none."""
        for name in names:
            window = getattr(event, FABLE_LIMIT_TYPE if name == FABLE else name, None)
            if window is not None:
                self.record(name, window.utilization, window.resets_at, now)

    def known(self, names=READINGS):
        """Whether any surface has said anything yet about any of `names`, every reading by default."""
        return any(name in self.readings for name in names)

    def utilization(self, name, now):
        """The window's utilization as it stands at `now`, None when unread or reset since."""
        reading = self.readings.get(name)
        if reading is None:
            return None
        if reading.resets_at is not None:
            return None if reading.resets_at <= now else reading.utilization
        if reading.observed_at is not None and now - reading.observed_at >= WINDOW_S[name]:
            return None
        return reading.utilization

    def next_reset(self, now, window=None):
        """The next reset after `now` of the named window, else of the windows it resets with; None when none is known."""
        for names in (([window],) if window in READINGS else ()) + (RESETS_WITH.get(window, WINDOWS),):
            future = [self.readings[name].resets_at for name in names
                      if name in self.readings and self.readings[name].resets_at is not None
                      and self.readings[name].resets_at > now]
            if future:
                return min(future)
        return None


@dataclass
class Usage:
    """What `claude -p "/usage"` said: each utilization as a fraction, and each window's reset when printed."""

    five_hour: Optional[float]
    seven_day: Optional[float]
    resets: dict = field(default_factory=dict)
    fable: Optional[float] = None


def parse_usage(text, now):
    """The windows of the `/usage` text, or None when none of the regexes of decisions 5 and 15 matched.

    The percentages are whole numbers in prose (`Current session: 24% used`), read as fractions.
    """
    text = text or ""
    session, week, fable = SESSION_RE.search(text), WEEK_RE.search(text), FABLE_RE.search(text)
    if session is None and week is None and fable is None:
        return None
    resets = {}
    if session is not None:
        resets[FIVE_HOUR] = parse_reset(session.group(2), _zone_after(text, session), now)
    week_reset = _WEEK_RESET_RE.search(text)
    if week_reset is not None:
        resets[SEVEN_DAY] = parse_reset(week_reset.group(1), _zone_after(text, week_reset), now)
    if fable is not None:
        resets[FABLE] = parse_reset(fable.group(2), _zone_after(text, fable), now)
    return Usage(
        int(session.group(1)) / 100 if session else None,
        int(week.group(1)) / 100 if week else None,
        resets,
        int(fable.group(1)) / 100 if fable else None,
    )


def _zone_after(text, match):
    """The zone named in the parentheses a match stopped in front of, as in `resets 5am (Asia/Riyadh)`."""
    found = _ZONE_RE.match(text, match.end())
    return found.group(1).strip() if found else None


def parse_reset(prose, zone=None, now=0.0):
    """The epoch second a reset in the CLI's prose names, the first such moment after `now`; None when unreadable.

    `zone` is the IANA name the CLI printed beside it, or None for the machine's own zone. A bare
    time (`3:45pm`) is the next one; a weekday (`Mon 12:00am`) is the next such day; a date
    (`Sep 11, 10:10pm`) is this year's, or next year's when this year's is half a year gone.
    """
    match = _CLOCK_RE.match((prose or "").strip())
    if match is None:
        return None
    hour, minute = int(match.group("hour")), int(match.group("minute") or 0)
    if not 1 <= hour <= 12 or minute > 59:
        return None
    hour = hour % 12 + (12 if match.group("half").lower() == "pm" else 0)
    reference = datetime.fromtimestamp(now, _zone(zone))
    name = (match.group("name") or "").lower()[:3]
    at = dict(hour=hour, minute=minute, second=0, microsecond=0)
    try:
        if name and match.group("day"):
            if name not in _MONTHS:
                return None
            candidate = reference.replace(month=_MONTHS.index(name) + 1, day=int(match.group("day")), **at)
            if candidate < reference - timedelta(days=183):
                candidate = candidate.replace(year=candidate.year + 1)
        elif name:
            if name not in _WEEKDAYS:
                return None
            candidate = (reference + timedelta(days=(_WEEKDAYS.index(name) - reference.weekday()) % 7)).replace(**at)
            if candidate <= reference:
                candidate += timedelta(days=7)
        else:
            candidate = reference.replace(**at)
            if candidate <= reference:
                candidate += timedelta(days=1)
    except ValueError:  # a day the month does not have
        return None
    return int(candidate.timestamp())


def _zone(name):
    if name:
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return datetime.now().astimezone().tzinfo


# --- a hit limit -----------------------------------------------------------------------------


@dataclass
class Limit:
    """A hit limit: the signal that said so, when it resets (epoch seconds, None when unsaid), which window, how full.

    `model` is `fable` when it was Fable's weekly window, which holds only the launches on Fable, and
    None for the windows every model draws on, which pause the run.
    """

    signal: str
    resets_at: Optional[int] = None
    window: str = UNKNOWN
    utilization: Optional[float] = None
    model: Optional[str] = None


def rejected(event):
    """The `Limit` a `rate_limit_event` with `status: rejected` reports, or None for any other status.

    A rejection of `seven_day_overage_included` is Fable's weekly window refusing a Fable request: a
    limit on the week whose `model` is `fable`.
    """
    if event.status != REJECTED:
        return None
    fable = event.rate_limit_type == FABLE_LIMIT_TYPE
    window = SEVEN_DAY if fable else event.rate_limit_type if event.rate_limit_type in WINDOWS else UNKNOWN
    block = getattr(event, FABLE_LIMIT_TYPE, None) if fable else getattr(event, window) if window in WINDOWS else None
    return Limit(
        EVENT_SIGNAL,
        event.resets_at if event.resets_at is not None else (block.resets_at if block else None),
        window,
        block.utilization if block else None,
        FABLE if fable else None,
    )


def hit_limit(envelope, stderr="", now=0.0, model=None):
    """Whether this session stopped at a usage limit, and on which window; a `Limit` or None.

    The signals of decision 5: a `rate_limit_event` with `status: rejected`, a `result` with
    `api_error_status: 429`, or a non-zero exit whose stderr or result text says "hit your" or
    "reached your", and "limit". When the event names no reset, the message's `resets <time>` does,
    read against `now` (the moment the message was written), and the message's "session" or
    "weekly" names the window. Only the line that says so is read, not the log around it. Decision
    15 adds a subagent's failed task whose `error` names a rate limit and Fable, which the stream of
    a parent whose own result stays a success still carries.

    Which window refused is the rejected event's own `rateLimitType` when there is one. Otherwise
    the words decide: words naming Fable are Fable's weekly window, words naming a session or a week
    are the windows every model draws on, and a refusal naming neither is Fable's when the session
    was launched on Fable: `model`, the alias it was launched with, else the model its stream reported.
    """
    found = None
    for event in envelope.rate_limit_events:
        found = rejected(event) or found
    message = _limit_message([envelope.result_text, *envelope.errors, stderr])
    if found is None and envelope.api_error_status == LIMIT_STATUS:
        found = Limit(API_SIGNAL)
    if found is None and message is not None and envelope.exit_code not in (None, 0):
        found = Limit(MESSAGE_SIGNAL)
    if found is None:
        message = _refused_task(envelope.failed_tasks)
        found = Limit(SUBAGENT_SIGNAL) if message is not None else None
    if found is None:
        return None
    if message is not None:
        if found.resets_at is None:
            said = _MESSAGE_RESET_RE.search(message)
            found.resets_at = parse_reset(said.group(1), said.group(2), now) if said else None
        if found.window == UNKNOWN:
            lowered = message.lower()
            found.window = SEVEN_DAY if "week" in lowered else FIVE_HOUR if "session" in lowered else UNKNOWN
    if found.signal != EVENT_SIGNAL:
        # A subagent's refusal is its own model's, never the parent's launch.
        launched = None if found.signal == SUBAGENT_SIGNAL else model if model is not None else envelope.model
        found.model = _refused_model(message, launched)
    if found.model == FABLE:
        found.window = SEVEN_DAY
    return found


def _limit_message(texts):
    """The line that says a limit was hit, from the first text that has one: those words, not the log around them."""
    for text in texts:
        for line in (text.splitlines() if isinstance(text, str) else ()):
            lowered = line.lower()
            if "limit" in lowered and ("hit your" in lowered or "reached your" in lowered):
                return line
    return None


def _refused_task(tasks):
    """The `error` of the first failed subagent task Fable's weekly window refused, or None.

    Only Fable's refusal counts (decision 15): a subagent on another model that met a rate limit
    failed its own task, and the session around it goes on under the windows it draws on.
    """
    for task in tasks or ():
        error = task.get("error") if isinstance(task, dict) else None
        lowered = error.lower() if isinstance(error, str) else ""
        if FABLE in lowered and ("rate_limit" in lowered or "rate limit" in lowered):
            return error
    return None


def _refused_model(words, launched):
    """`fable` when the words name Fable, or name no other window and the session was launched on Fable; else None."""
    lowered = (words or "").lower()
    if FABLE in lowered:
        return FABLE
    if "week" in lowered or "session" in lowered:
        return None
    return FABLE if FABLE in (launched or "").lower() else None


def resets_at(limit, windows, now):
    """When a hit limit resets: from the signal, else the next known reset of its window, else now plus five hours."""
    if limit.resets_at is not None:
        return limit.resets_at
    return windows.next_reset(now, FABLE if limit.model == FABLE else limit.window) or int(now + FALLBACK_PAUSE_S)


def paused_payload(limit, resets, windows):
    """The `paused` event's payload: `resets_at` in the journal's ISO form, the window, its utilization, and a hold's `model`."""
    reading = FABLE if limit.model == FABLE else limit.window
    utilization = limit.utilization
    if utilization is None and reading in windows.readings:
        utilization = windows.readings[reading].utilization
    payload = {"resets_at": iso(resets), "window": limit.window, "utilization": utilization}
    if limit.model == FABLE:
        payload["model"] = FABLE
    return payload


def iso(seconds):
    """An epoch second as the `paused` event writes it: `2026-09-11T13:00:00Z`."""
    return datetime.fromtimestamp(int(seconds), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def epoch(text):
    """An ISO timestamp from the journal as epoch seconds, or None when it is not one."""
    try:
        moment = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.timestamp()
