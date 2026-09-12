"""The worker launcher seam (Implementation Decisions 3; Testing Decisions seam 1).

Every model call in the harness goes through `launch(request)` and `resume(request, session_id,
message)` over a `LaunchRequest`, and comes back as an `Envelope`. Two backends: `claude_cli`,
the only real one, runs the launch line of decision 3 and parses the `stream-json` output; `fake`
returns scripted envelopes for tests and demos. `WAYLINE_LAUNCHER=fake` selects the fake.
Nothing else in the harness starts `claude`: this module is the portability seam, and anything
that must run the executable for another reason (the tick's `auth status`) is added here as a
`ClaudeCli` method, never elsewhere.

The session directory is `request.env["WAYLINE_RUN"]`, spelled as the launch line spells it
(`<project>/research/sessions/<ticket>/<attempt>`); a resume writes into `resume-<k>/` under it so
the launch's own stream survives. This directory is the one place under `research/` written by
something other than the ledger: the launch line itself redirects the worker's stream there,
and the request is written beside it so the run can be reproduced by hand.

Two envelope fields extend the spec's list, each with a reason: `errors` carries the error text
the conductor puts in its one resume (BRIEF 9.1), and `result_text` carries the plain `result`
string a session without a schema returns (the tick reads `claude -p "/usage"` through this seam).

`WAYLINE_CLAUDE` names the executable when it is not the `claude` on PATH; the tests point it at
a recording stand-in, so the real backend is exercised without the network.
"""

import argparse
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

from wayline import HARNESS_ROOT
from wayline.frontmatter import FrontmatterError, load_document
from wayline.jsonschema import SchemaError, check_schema, load_schema, validate
from wayline.ledger import now_ts

__all__ = [
    "LaunchRequest", "Envelope", "RateLimitEvent", "Window", "Started", "Parsed", "Patch", "LaunchError",
    "launch", "resume", "pid_alive", "backend", "build_argv", "spelled_argv", "parse_stream", "read_envelope",
    "session_dir", "session_env", "use_fake", "ClaudeCli", "FakeLauncher", "CLAUDE_CLI", "FAKE",
    "describe_windows", "launch_verb", "MODEL_ALIASES", "EFFORTS",
    "Role", "RoleError", "Prompt", "Pack", "read_role", "assemble_prompt", "read_locator", "CONSULT_MAX",
    "schema_bullets",
]

_log = logging.getLogger("wayline.worker")

TERM_GRACE_SECONDS = 15  # after SIGTERM on a timeout, before SIGKILL
FALLBACK_MODEL = "sonnet"  # `--fallback-model`: overload only, never usage limits (decision 3)
MODEL_ALIASES = ("haiku", "sonnet", "opus", "fable")  # what decision 3 passes as --model; the policy schema's enum
EFFORTS = ("low", "medium", "high", "xhigh", "max")

# The resolved model name `system/init` reports for each alias, used by the fake backend.
RESOLVED_MODELS = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-5",
    "opus": "claude-opus-5",
    "fable": "claude-fable-5-1",
}


class LaunchError(ValueError):
    """A request the launcher refuses, a backend it does not have, or a fake with nothing scripted."""


# --- the request and the envelope -------------------------------------------------------------


@dataclass
class LaunchRequest:
    """One model call: the fields of decision 3, in its order.

    `agent_json` is the `--agents` object (a dict, or its JSON text) and must define `role`
    without a `tools` or `skills` key (decision 3). `settings_path` is copied into the session
    directory as `settings.json`; None writes `{}`. `schema_path` is passed as `--json-schema`
    and re-validated in code; None runs the session without a schema. `env` carries the
    `TICKET_*` and `WAYLINE_*` variables, and `env["WAYLINE_RUN"]` names the session directory.
    `max_minutes` None means no timeout.
    """

    role: str
    model: str
    effort: str
    prompt: str
    agent_json: Union[dict, str]
    allowed_tools: list = field(default_factory=list)
    disallowed_tools: list = field(default_factory=list)
    settings_path: Optional[Union[str, Path]] = None
    add_dirs: list = field(default_factory=list)
    cwd: Union[str, Path] = "."
    env: dict = field(default_factory=dict)
    schema_path: Optional[Union[str, Path]] = None
    max_minutes: Optional[float] = None

    @property
    def run_dir(self):
        """The session directory: `env["WAYLINE_RUN"]`."""
        run = self.env.get("WAYLINE_RUN") if isinstance(self.env, dict) else None
        if not run:
            raise LaunchError("request.env lacks WAYLINE_RUN, the session directory of the launch line")
        return Path(run)

    def agent_text(self):
        """The `--agents` argument: the dict serialized, or the text as given."""
        return self.agent_json if isinstance(self.agent_json, str) else json.dumps(self.agent_json)

    def check(self):
        """Refuse a request the launch line cannot carry, before anything starts or is written."""
        for name in ("role", "model", "effort", "prompt"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise LaunchError("request.%s must be a non-empty string" % name)
        if self.model not in MODEL_ALIASES:
            raise LaunchError("request.model must be one of %s, got %r" % (", ".join(MODEL_ALIASES), self.model))
        if self.effort not in EFFORTS:
            raise LaunchError("request.effort must be one of %s, got %r" % (", ".join(EFFORTS), self.effort))
        if isinstance(self.agent_json, str):
            try:
                agents = json.loads(self.agent_json)
            except ValueError as exc:
                raise LaunchError("request.agent_json is not JSON: %s" % exc)
        else:
            agents = self.agent_json
        if not isinstance(agents, dict) or self.role not in agents or not isinstance(agents[self.role], dict):
            raise LaunchError("request.agent_json must be an object defining the role %r" % self.role)
        for key in ("tools", "skills"):
            if key in agents[self.role]:
                raise LaunchError("request.agent_json[%r] must not carry %r: an agent tools allowlist removes the StructuredOutput tool and skills are not injected that way (decision 3)" % (self.role, key))
        for name in ("allowed_tools", "disallowed_tools", "add_dirs"):
            value = getattr(self, name)
            if not isinstance(value, (list, tuple)) or not all(isinstance(item, (str, Path)) for item in value):
                raise LaunchError("request.%s must be a list of strings" % name)
        if not isinstance(self.env, dict):
            raise LaunchError("request.env must be a dict of environment variables")
        if self.max_minutes is not None and (isinstance(self.max_minutes, bool) or not isinstance(self.max_minutes, (int, float)) or self.max_minutes <= 0):
            raise LaunchError("request.max_minutes must be a positive number or None")
        return self


@dataclass
class Window:
    """One usage window of a `rate_limit_event`: utilization as a 0..1 fraction and the reset epoch."""

    utilization: Optional[float]
    resets_at: Optional[int]

    @classmethod
    def from_dict(cls, data):
        if data is None or isinstance(data, Window):
            return data
        if not isinstance(data, dict):
            raise LaunchError("a window is an object or null, got %r" % (data,))
        unknown = sorted(set(data) - {"utilization", "resets_at"})
        if unknown:
            raise LaunchError("a window has no field(s) %s" % ", ".join(unknown))
        return cls(_number(data.get("utilization")), _integer(data.get("resets_at")))


@dataclass
class RateLimitEvent:
    """One `rate_limit_event` of the stream (decision 3).

    `status`, `resets_at`, and `rate_limit_type` are documented; the `five_hour` and `seven_day`
    windows come from the observed, undocumented `unifiedWindows` block and are None without it.
    """

    status: Optional[str]
    resets_at: Optional[int] = None
    rate_limit_type: Optional[str] = None
    five_hour: Optional[Window] = None
    seven_day: Optional[Window] = None

    @classmethod
    def from_info(cls, info):
        """Build from a stream's `rate_limit_info` object; a missing `unifiedWindows` degrades to status alone."""
        info = info if isinstance(info, dict) else {}
        windows = info.get("unifiedWindows")

        def window(name):
            block = windows.get(name) if isinstance(windows, dict) else None
            if not isinstance(block, dict):
                return None
            return Window(_number(block.get("utilization")), _integer(block.get("resetsAt")))

        return cls(
            status=info.get("status") if isinstance(info.get("status"), str) else None,
            resets_at=_integer(info.get("resetsAt")),
            rate_limit_type=info.get("rateLimitType") if isinstance(info.get("rateLimitType"), str) else None,
            five_hour=window("five_hour"),
            seven_day=window("seven_day"),
        )

    @classmethod
    def from_dict(cls, data):
        """The inverse of `as_dict`, for scripted envelopes; unknown keys (the stream's own spelling) are refused."""
        if isinstance(data, RateLimitEvent):
            return data
        if not isinstance(data, dict):
            raise LaunchError("a rate_limit_event is an object, got %r" % (data,))
        known = {item.name for item in fields(cls)}
        unknown = sorted(set(data) - known)
        if unknown:
            raise LaunchError("a rate_limit_event has no field(s) %s (the fields are %s)" % (", ".join(unknown), ", ".join(sorted(known))))
        status = data.get("status")
        if status is not None and not isinstance(status, str):
            raise LaunchError("rate_limit_event.status is a string or null")
        return cls(status, _integer(data.get("resets_at")), data.get("rate_limit_type"), Window.from_dict(data.get("five_hour")), Window.from_dict(data.get("seven_day")))

    def as_dict(self):
        return asdict(self)


@dataclass
class Envelope:
    """What one model call came back with: the fields of decision 3, in its order, then the two extensions.

    `structured_output` is the object validated in code against the request's schema, or None:
    a `success` result without the key, a `subtype: error_max_structured_output_retries`, or an
    object the schema rejects all leave it None with the reason in `errors`. `is_error` is the
    CLI's flag or the harness's own verdict, whichever is worse. `exit_code` is the process exit
    status with signals folded the shell way (SIGTERM is 143). `stream_path` is the whole stream.
    """

    session_id: Optional[str] = None
    model: Optional[str] = None
    structured_output: Optional[dict] = None
    is_error: Optional[bool] = None
    subtype: Optional[str] = None
    num_turns: Optional[int] = None
    duration_ms: Optional[int] = None
    duration_api_ms: Optional[int] = None
    usage: Optional[dict] = None
    model_usage: Optional[dict] = None
    permission_denials: list = field(default_factory=list)
    api_error_status: Optional[int] = None
    rate_limit_events: list = field(default_factory=list)
    exit_code: Optional[int] = None
    stream_path: Optional[Path] = None
    errors: list = field(default_factory=list)
    result_text: Optional[str] = None

    def __post_init__(self):
        if self.structured_output is not None and not isinstance(self.structured_output, dict):
            raise LaunchError("envelope.structured_output is an object or None, got %s" % type(self.structured_output).__name__)
        for name in ("usage", "model_usage"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, dict):
                raise LaunchError("envelope.%s is an object or None" % name)
        for name in ("permission_denials", "errors", "rate_limit_events"):
            value = getattr(self, name)
            if value is None:
                setattr(self, name, [])
            elif not isinstance(value, list):
                raise LaunchError("envelope.%s is a list, got %s" % (name, type(value).__name__))
        if any(not isinstance(item, str) for item in self.errors):
            raise LaunchError("envelope.errors is a list of strings")
        self.rate_limit_events = [RateLimitEvent.from_dict(item) for item in self.rate_limit_events]
        if self.stream_path is not None and not isinstance(self.stream_path, Path):
            self.stream_path = Path(self.stream_path)

    @property
    def valid(self):
        """True when a structured output passed the schema in code."""
        return self.structured_output is not None

    def last_windows(self):
        """The five-hour and seven-day utilization of the latest `rate_limit_event`, None when absent."""
        if not self.rate_limit_events:
            return (None, None)
        last = self.rate_limit_events[-1]
        return (
            last.five_hour.utilization if last.five_hour else None,
            last.seven_day.utilization if last.seven_day else None,
        )

    def as_dict(self):
        """A JSON-able view (the journal, the smoke verb, the dashboard)."""
        data = asdict(self)
        data["stream_path"] = str(self.stream_path) if self.stream_path is not None else None
        return data

    @classmethod
    def from_dict(cls, data):
        """The inverse of `as_dict`; unknown keys are refused so a scripted typo cannot pass silently."""
        if not isinstance(data, dict):
            raise LaunchError("an envelope is an object, got %r" % (data,))
        known = {item.name for item in fields(cls)}
        unknown = sorted(set(data) - known)
        if unknown:
            raise LaunchError("envelope has no field(s) %s" % ", ".join(unknown))
        return cls(**data)


@dataclass
class Started:
    """What a backend reports the moment the process exists: its pid, the session directory, the stream."""

    pid: int
    run_dir: Path
    stream_path: Path


# --- roles and the prompt (Implementation Decisions 1 and 3) -------------------------------------


ROLES = "roles"                 # <harness>/roles/<role>/agent.md and wayline.json
ROLE_PROMPTS = "prompts/roles"  # <harness>/prompts/roles/<role>.md: the protocol the prompt carries
LOCAL_ROLES = ".claude/agents"  # <project>/.claude/agents/<role>.md: the project's own wording

# `--agents` takes neither key, each for its own reason (decision 3, from map ticket 01).
FORBIDDEN_AGENT_KEYS = {
    "tools": "an agent `tools` allowlist removes the StructuredOutput tool; tool restriction is wayline.json's allowed_tools and disallowed_tools",
    "skills": "`skills` in `--agents` does not inject when the agent runs as the main session; a skill reaches the worker as a /wayline-<skill> line in the prompt",
}

# The fields `roles/<role>/wayline.json` may carry; anything else is a typo, not a setting.
ROLE_SETTINGS = ("role", "summary", "kinds", "may_judge", "output_schema", "allowed_tools", "disallowed_tools")

# `policy.consultant.max_questions_per_ticket`, restated in the contract lines.
CONSULT_MAX = 5

_ROLE_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*\Z")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*\Z")


class RoleError(ValueError):
    """A role the harness cannot launch: a missing file, a forbidden agent key, a broken tool list."""


@dataclass
class Role:
    """One role as its two files define it (decision 1), plus the protocol its prompt carries."""

    name: str
    description: str
    system_prompt: str
    allowed_tools: list = field(default_factory=list)
    disallowed_tools: list = field(default_factory=list)
    output_schema: Optional[str] = None
    may_judge: bool = False
    summary: str = ""
    kinds: list = field(default_factory=list)
    protocol: str = ""
    source: Optional[Path] = None

    def agent_json(self, model, effort, max_turns=None):
        """The `--agents` object of decision 3, in its order, with no `tools` and no `skills`."""
        agent = {
            "description": self.description,
            "prompt": self.system_prompt,
            "model": model,
            "effort": effort,
            "maxTurns": None if max_turns is None else int(max_turns),
            "permissionMode": "dontAsk",
        }
        if agent["maxTurns"] is None:
            del agent["maxTurns"]
        return {self.name: agent}


def read_role(name, harness_root=HARNESS_ROOT, project=None):
    """The role `name` as its files define it; a project's `.claude/agents/<role>.md` wins for the words.

    The tool lists stay the harness's on purpose: a project may say what a role is for in its own
    terms, but what a worker is permitted to run is the harness's decision (decision 4).
    """
    if not isinstance(name, str) or not _ROLE_NAME_RE.match(name):
        raise RoleError("a role name is lowercase letters, digits, and dashes, got %r" % (name,))
    root = Path(harness_root).resolve()
    settings = _role_settings(root / ROLES / name / "wayline.json", name)
    source = root / ROLES / name / "agent.md"
    if project is not None:
        local = Path(project) / LOCAL_ROLES / (name + ".md")
        if local.is_file():
            source = local
    description, system_prompt = _role_markdown(source, name)
    protocol_path = root / ROLE_PROMPTS / (name + ".md")
    protocol = protocol_path.read_text(encoding="utf-8") if protocol_path.is_file() else ""
    return Role(
        name=name, description=description, system_prompt=system_prompt,
        allowed_tools=settings["allowed_tools"], disallowed_tools=settings["disallowed_tools"],
        output_schema=settings["output_schema"], may_judge=settings["may_judge"],
        summary=settings["summary"], kinds=settings["kinds"], protocol=protocol, source=source,
    )


def _role_markdown(path, name):
    """`agent.md`: the description the `--agents` object needs and the body, which is the system prompt."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as failure:
        raise RoleError("the role %r has no readable %s: %s" % (name, path, failure)) from None
    try:
        frontmatter, body = load_document(text)
    except FrontmatterError as failure:
        raise RoleError("%s: %s" % (path, failure)) from None
    for key, why in FORBIDDEN_AGENT_KEYS.items():
        if key in frontmatter:
            raise RoleError("%s must not carry %r: %s" % (path, key, why))
    if frontmatter.get("name", name) != name:
        raise RoleError("%s names the role %r but the harness reads it as %r" % (path, frontmatter.get("name"), name))
    description = frontmatter.get("description")
    if not isinstance(description, str) or not description.strip():
        raise RoleError("%s needs a description in its frontmatter: --agents carries one per agent" % path)
    if not body.strip():
        raise RoleError("%s has no body, and the body is the role's system prompt" % path)
    return description.strip(), body.strip()


def _role_settings(path, name):
    """`wayline.json`: the tool lists and the registry fields, with every value checked."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as failure:
        raise RoleError("the role %r has no readable %s: %s" % (name, path, failure)) from None
    except ValueError as failure:
        raise RoleError("%s is not readable JSON: %s" % (path, failure)) from None
    if not isinstance(value, dict):
        raise RoleError("%s holds an object of role settings, got %s" % (path, type(value).__name__))
    unknown = sorted(set(value) - set(ROLE_SETTINGS))
    if unknown:
        raise RoleError("%s has no field(s) %s (the fields are %s)" % (path, ", ".join(unknown), ", ".join(ROLE_SETTINGS)))
    if value.get("role", name) != name:
        raise RoleError("%s names the role %r but lives under %r" % (path, value.get("role"), name))
    for key in ("allowed_tools", "disallowed_tools", "kinds"):
        items = value.setdefault(key, [])
        if not isinstance(items, list) or not all(isinstance(item, str) and item.strip() for item in items):
            raise RoleError("%s: %s is a list of non-empty strings" % (path, key))
    if not isinstance(value.setdefault("may_judge", False), bool):
        raise RoleError("%s: may_judge is true or false" % path)
    if value.setdefault("output_schema", None) is not None and not isinstance(value["output_schema"], str):
        raise RoleError("%s: output_schema names a shipped schema, or is null" % path)
    if not isinstance(value.setdefault("summary", ""), str):
        raise RoleError("%s: summary is a string" % path)
    return value


# --- context pack locators -----------------------------------------------------------------------


def read_locator(locator, roots):
    """The text one context-pack entry names, and the problem that stopped it being read.

    An entry is a path, optionally with `:<first>-<last>` line numbers (1-based, inclusive) or
    `#<anchor>` naming a markdown heading, whose section runs to the next heading at that level
    or above. The path is resolved against each root in order and must stay inside the root it
    resolved in, so a pack cannot reach out of the project through `..` or a symlink.
    """
    path_part, kind, selector = _split_locator(locator)
    if not path_part:
        return "", "names no file"
    found = None
    for root in roots:
        root = Path(root).resolve()
        candidate = (root / path_part).resolve()
        if not candidate.is_relative_to(root):
            return "", "resolves outside %s" % root
        if candidate.is_file():
            found = candidate
            break
    if found is None:
        return "", "no file at %s" % path_part
    try:
        text = found.read_text(encoding="utf-8", errors="replace")
    except OSError as failure:
        return "", "cannot be read: %s" % failure
    if kind == "lines":
        return _lines(text, selector, path_part)
    if kind == "anchor":
        return _section(text, selector)
    return text, None


def _split_locator(locator):
    """A locator as `(path, kind, selector)`, where kind is `file`, `lines`, or `anchor`."""
    text = str(locator).strip()
    if "#" in text:
        path_part, anchor = text.split("#", 1)
        return path_part.strip(), "anchor", anchor.strip()
    match = re.search(r":(\d+)(?:-(\d+))?\Z", text)
    if match:
        first = int(match.group(1))
        return text[: match.start()].strip(), "lines", (first, int(match.group(2)) if match.group(2) else first)
    return text, "file", None


def _lines(text, selector, path_part):
    first, last = selector
    lines = text.split("\n")
    if text.endswith("\n"):
        lines.pop()
    if first < 1 or first > len(lines):
        return "", "%s has %d line(s), so line %d is outside it" % (path_part, len(lines), first)
    return "\n".join(lines[first - 1: max(first, last)]) + "\n", None


def _section(text, anchor):
    """The markdown section under the heading whose slug is `anchor`, to the next heading at or above it."""
    wanted = _slug(anchor)
    lines = text.split("\n")
    start, level = None, 0
    for index, line in enumerate(lines):
        match = _HEADING_RE.match(line)
        if match is None:
            continue
        if start is None:
            if _slug(match.group(2)) == wanted:
                start, level = index, len(match.group(1))
        elif len(match.group(1)) <= level:
            return "\n".join(lines[start:index]).rstrip("\n") + "\n", None
    if start is None:
        return "", "no heading matches #%s" % anchor
    return "\n".join(lines[start:]).rstrip("\n") + "\n", None


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


# --- prompt assembly -----------------------------------------------------------------------------


@dataclass
class Pack:
    """A rendered context pack: the text, what it spent, and what it had to leave out."""

    text: str = ""
    chars: int = 0
    cut: bool = False
    dropped: list = field(default_factory=list)
    problems: list = field(default_factory=list)


@dataclass
class Prompt:
    """The assembled prompt, its context size, and what assembling it had to leave out.

    `context_chars` is the context pack alone, as the journal has always recorded it;
    `skill_chars` is what the inlined skill bodies spent beside it, under the same cap.
    """

    text: str
    context_chars: int = 0
    cut: bool = False
    dropped: list = field(default_factory=list)
    problems: list = field(default_factory=list)
    skill_chars: int = 0

    @property
    def sha256(self):
        """What the journal records, so two launches of the same ticket can be told apart."""
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


def assemble_prompt(ticket, role, roots=(), max_chars=None, budget=None, consult_max=CONSULT_MAX):
    """The worker's prompt, assembled in the order of decision 3.

    One `/wayline-<skill>` line per assigned skill, the body of every skill after the first
    inlined under a heading, the ticket restated, the context pack under locator headers cut at
    the tier's cap with the cut announced, the role protocol, the result schema, and the contract
    lines. `roots` are the directories a locator resolves against, in order (the worktree and the
    project); `max_chars` is `policy.context_pack.max_chars` for the tier's model, None for no cap.
    """
    pack = _context_section(ticket.get("context_pack") or [], roots, max_chars)
    skills = _skill_section(ticket.get("skills") or [], roots, max_chars)
    parts = [
        "\n".join("/wayline-%s" % skill for skill in (ticket.get("skills") or [])),
        skills.text,
        _ticket_section(ticket, budget),
        pack.text,
        role.protocol,
        _result_section(ticket, role),
        _contract_section(ticket, consult_max),
    ]
    text = "\n\n".join(part.strip("\n") for part in parts if part.strip()) + "\n"
    return Prompt(text, pack.chars, pack.cut or skills.cut, pack.dropped + skills.dropped,
                  pack.problems + skills.problems, skills.chars)


def _skill_path(skill, roots):
    """Where a ticket's skill lives: `.claude/skills/wayline-<skill>/SKILL.md` under the first root that has it.

    One lookup covers both kinds of skill, because `wayline init` symlinks every harness skill
    into the project's `.claude/skills/` beside the project's own.
    """
    for root in roots:
        candidate = Path(root) / ".claude" / "skills" / ("wayline-" + str(skill)) / "SKILL.md"
        if candidate.is_file():
            return candidate
    return None


def _skill_section(skills, roots, max_chars=None):
    """The bodies of every skill after the first, inlined under a heading, capped like the pack.

    Only the first `/wayline-<skill>` line of a prompt expands. The live M0 run measured it: of a
    ticket's two skills, the worker knew the first one's passphrase without ever opening a file
    and had to read the second one's `SKILL.md` itself to learn the other (`docs/verification/m0.md`).
    A worker can only do that where the skills happen to be committed in its worktree, so the
    conductor inlines them instead, which is the path Implementation Decisions 3 names for exactly
    this finding.

    The first skill is looked up too, though its body is not inlined. Nothing else checks that a
    ticket's skills exist, so without this a misspelled first skill is a slash-command line that
    expands into nothing and a worker that never learns it was missing anything.
    """
    pack = Pack()
    if not skills:
        return pack
    if _skill_path(skills[0], roots) is None:
        pack.problems.append("skill %s has no SKILL.md under any of the prompt's roots" % skills[0])
    if len(skills) < 2:
        return pack
    cap = None if max_chars is None else max(0, int(max_chars))
    rendered = [
        "# The rest of your skills",
        "",
        "Only the first `/wayline-<skill>` line above expands into its skill. The others are "
        "inlined here, in the ticket's order, and each is to be followed as if it had expanded.",
    ]
    for index, skill in enumerate(skills[1:], start=1):
        if cap is not None and pack.chars >= cap:
            pack.dropped.extend("/wayline-%s" % name for name in skills[index:])
            break
        path = _skill_path(skill, roots)
        rendered.extend(["", "## /wayline-%s" % skill, ""])
        if path is None:
            pack.problems.append("skill %s has no SKILL.md under any of the prompt's roots" % skill)
            rendered.append("[wayline: this skill's SKILL.md was not found, so its body is missing. "
                            "Say so in your result rather than guessing what it asked for.]")
            continue
        try:
            body = _skill_body(path)
        except (OSError, ValueError) as exc:
            pack.problems.append("skill %s: %s cannot be read: %s" % (skill, path, exc))
            rendered.append("[wayline: this skill's SKILL.md could not be read, so its body is "
                            "missing. Say so in your result rather than guessing what it asked for.]")
            continue
        note = None
        if cap is not None and pack.chars + len(body) > cap:
            left_out = len(body) - (cap - pack.chars)
            body = body[: cap - pack.chars]
            note = "[wayline: this skill was cut here at the context cap; %d character(s) are missing. Read its SKILL.md yourself if you need the rest.]" % left_out
            pack.cut = True
        pack.chars += len(body)
        fence = _fence(body)
        rendered.extend([fence, body.rstrip("\n"), fence])
        if note:
            rendered.extend(["", note])
    if pack.dropped:
        pack.cut = True
        rendered.extend(["", "[wayline: the inlined skills reached the context cap of %d characters; %s left out: %s. Read their SKILL.md yourself if you need them.]"
                         % (cap, "one was" if len(pack.dropped) == 1 else "%d were" % len(pack.dropped), ", ".join(pack.dropped))])
    pack.text = "\n".join(rendered)
    return pack


def _skill_body(path):
    """A `SKILL.md` without its frontmatter: the heading above already names the skill."""
    text = path.read_text(encoding="utf-8")
    if text.startswith("---\n"):
        end = text.find("\n---\n", 3)
        if end != -1:
            text = text[end + len("\n---\n"):]
    return text.lstrip("\n")


def _ticket_section(ticket, budget):
    lines = ["# Ticket %s: %s" % (ticket["id"], ticket["title"]), "", "- kind: %s" % ticket["kind"]]
    if ticket.get("demo"):
        lines.append("- demo: %s" % ticket["demo"])
    lines.append("- touch set: %s" % ", ".join("`%s`" % item for item in ticket["touches"]))
    machine = (ticket.get("acceptance") or {}).get("machine") or []
    if machine:
        lines.append("- acceptance, which the conductor runs again in the worktree, after the rebase, and on `main`:")
        lines.extend("    - `%s`" % command for command in machine)
    else:
        lines.append("- acceptance: this ticket carries no machine acceptance command.")
    if budget:
        lines.append("- budget: %s turns, %s minutes" % (budget.get("max_turns", "?"), budget.get("max_minutes", "?")))
    return "\n".join(lines)


def _context_section(locators, roots, max_chars):
    """The pack rendered under locator headers, cut at `max_chars` with every cut announced."""
    pack = Pack()
    if not locators:
        return pack
    cap = None if max_chars is None else max(0, int(max_chars))
    rendered = ["# Context pack", "", "What the planner packed for this ticket, in the ticket's order."]
    used = 0
    for index, locator in enumerate(locators):
        if cap is not None and used >= cap:
            pack.dropped.extend(str(item) for item in locators[index:])
            break
        text, problem = read_locator(locator, roots)
        rendered.extend(["", "## %s" % locator, ""])
        if problem is not None:
            pack.problems.append("%s %s" % (locator, problem))
            rendered.append("[wayline: this entry could not be read: it %s.]" % problem)
            continue
        note = None
        if cap is not None and used + len(text) > cap:
            left_out = len(text) - (cap - used)
            text = text[: cap - used]
            note = "[wayline: this entry was cut here at the context cap; %d character(s) are missing.]" % left_out
            pack.cut = True
        used += len(text)
        fence = _fence(text)
        rendered.extend([fence, text.rstrip("\n"), fence])
        if note:
            rendered.extend(["", note])
    if pack.dropped:
        pack.cut = True
        rendered.extend(["", "[wayline: the context pack reached its cap of %d characters; %s left out: %s. Ask the consultant for what you need from them.]"
                         % (cap, "one entry was" if len(pack.dropped) == 1 else "%d entries were" % len(pack.dropped), ", ".join(pack.dropped))])
    pack.text = "\n".join(rendered)
    pack.chars = used
    return pack


def _fence(text):
    """A code fence longer than any run of backticks the text itself carries."""
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)


def schema_bullets(schema):
    """One bullet per property of a schema: the name, the type phrase, and the description.

    Every prompt that asks a session for a structured result lists the fields this way, so the
    prompt and the schema cannot drift: the words a session reads are the schema's own.
    """
    required = set(schema.get("required") or ())
    lines = []
    for field_name, definition in (schema.get("properties") or {}).items():
        line = "- `%s` (%s%s)" % (field_name, _type_phrase(definition), ", required" if field_name in required else "")
        if definition.get("description"):
            line += ": " + definition["description"]
        lines.append(line)
    return lines


def _result_section(ticket, role):
    name = role.output_schema or "result"
    schema = load_schema(name)
    lines = [
        "# The result",
        "",
        "Return it through the structured output, once, before you stop. The launch passes the `%s` schema to this session, and the conductor validates what comes back against it again:" % name,
        "",
    ]
    lines.extend(schema_bullets(schema))
    lines.extend([
        "",
        "`ticket_id` is %s. `status` is `done` only when the acceptance commands pass. Give every "
        "finding the path and the locator it came from: a finding a reader cannot follow back to a "
        "file is worth nothing." % ticket["id"],
    ])
    return "\n".join(lines)


def _type_phrase(definition):
    """A schema property as one readable phrase, so the prompt and the schema cannot drift."""
    kind = definition.get("type")
    if isinstance(kind, list):
        return " or ".join(_type_phrase(dict(definition, type=one)) for one in kind)
    if definition.get("enum"):
        return "%s, one of %s" % (kind or "value", ", ".join(str(value) for value in definition["enum"]))
    if kind == "array":
        return "array of " + _type_phrase(definition.get("items") or {})
    if kind == "object":
        keys = list(definition.get("properties") or {})
        if keys:
            required = set(definition.get("required") or ())
            return "object with " + ", ".join(key + " (required)" if key in required else key for key in keys)
        extra = definition.get("additionalProperties")
        return ("object of " + _type_phrase(extra)) if isinstance(extra, dict) else "object"
    return kind or "any"


def _contract_section(ticket, consult_max):
    return "\n".join([
        "# The contract",
        "",
        "- Write only under the touch set: %s. A hook blocks every write outside it." % ", ".join("`%s`" % item for item in ticket["touches"]),
        "- Run `wayline accept` from the worktree root before you stop; the stop is blocked until the file it writes exists.",
        "- Commit your work on the branch `ticket/%s`. The conductor integrates that branch, so anything uncommitted is lost." % ticket["id"],
        "- Never integrate, never close the ticket, never edit `research/`: the conductor does all three.",
        "- Ask the consultant with `wayline consult <slug> \"<question>\"`, at most %s in this ticket." % ("once" if consult_max == 1 else "%d times" % consult_max),
    ])


# --- the session directory ----------------------------------------------------------------------


def session_dir(project, ticket, attempt):
    """`<project>/research/sessions/<ticket>/<attempt>`, the RUN of the launch line."""
    return Path(project) / "research" / "sessions" / str(ticket) / str(attempt)


def session_env(project, ticket, attempt, touches, harness_root=HARNESS_ROOT, path=None):
    """The `TICKET_*`, `WAYLINE_*` and `PATH` variables the launch line exports, as strings.

    The contract line tells the worker to run `wayline accept`, and the stop guard blocks the
    stop until the file that verb writes exists, so the command has to resolve. The harness
    `bin/` goes first on the worker's `PATH` for that reason: a project need not install the
    command, and a worker cannot reach a different checkout's copy of it by accident.
    """
    run = session_dir(project, ticket, attempt)
    if isinstance(touches, (str, Path)):
        touches = [touches]
    return {
        "TICKET_TOUCHES": ":".join(str(item) for item in touches),
        "TICKET_ACCEPTANCE_FILE": str(run / "acceptance.json"),
        "WAYLINE_PROJECT": str(project),
        "WAYLINE_TICKET": str(ticket),
        "WAYLINE_RUN": str(run),
        "PATH": _path_with_harness_bin(harness_root, path),
    }


def _path_with_harness_bin(harness_root, path=None):
    """`<harness>/bin` first on `PATH`, and only once however often a launch is composed.

    Absolute, because the child runs in the worktree rather than here, and a relative entry on a
    `PATH` means something different from every directory.
    """
    binary = os.path.abspath(str(Path(harness_root) / "bin"))
    inherited = os.environ.get("PATH", os.defpath) if path is None else path
    rest = [entry for entry in inherited.split(os.pathsep) if entry and entry != binary]
    return os.pathsep.join([binary] + rest)


def _resume_dir(run_dir):
    """The first free `resume-<k>` under the session directory."""
    number = 1
    while (run_dir / ("resume-%d" % number)).exists():
        number += 1
    return run_dir / ("resume-%d" % number)


def _write_text(path, text):
    """Write a small file durably by write-then-rename, so a reader never sees a torn one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _load_schema(schema_path):
    """The text `--json-schema` is given and the parsed object, refused when the file is unusable.

    The text is not the file byte for byte: the meta-schema reference is dropped first. Every
    schema under `schemas/` opens with `"$schema": "https://json-schema.org/draft/2020-12/schema"`,
    and the CLI's own validator resolves `$schema` against the schemas it holds rather than
    fetching one, so it answers `--json-schema is not a valid JSON Schema: no schema with key or
    ref ...` and exits before the session starts (`docs/verification/m0.md`, ticket 06). Nothing
    downstream wants the key either: the harness re-validates the result with `wayline.jsonschema`,
    whose subset is a 2020-12 subset by construction.
    """
    try:
        text = Path(schema_path).read_text(encoding="utf-8")
        schema = json.loads(text)
    except (OSError, ValueError) as exc:
        raise LaunchError("schema %s cannot be read: %s" % (schema_path, exc))
    try:
        check_schema(schema)
    except SchemaError as exc:
        raise LaunchError("schema %s is outside the validator's subset: %s" % (schema_path, exc))
    return _schema_text(text, schema), schema


def _schema_text(text, schema):
    """The file's own text, or the object without its meta-schema references when it has any.

    A subschema may carry `$schema` too, and the CLI refuses a whole file over one of those as
    readily as over the one at the top, so the strip goes all the way down. A file that names it
    nowhere goes across byte for byte, which is what the session directory's copy then shows.
    """
    if not _names_meta_schema(schema):
        return text
    return json.dumps(_without_meta_schema(schema), indent=2) + "\n"


# Where a schema's keys are names rather than keywords, and where its values are literals rather
# than schemas. A property may legitimately be called `$schema`, and a `const` may carry the word.
NAMED_SUBSCHEMAS = ("properties", "patternProperties", "$defs", "definitions")
LITERALS = ("const", "enum", "default", "examples")


def _names_meta_schema(schema):
    """Whether `$schema` appears as a keyword anywhere in the schema, at any depth."""
    if isinstance(schema, list):
        return any(_names_meta_schema(item) for item in schema)
    if not isinstance(schema, dict):
        return False
    if "$schema" in schema:
        return True
    for key, value in schema.items():
        if key in LITERALS:
            continue
        if key in NAMED_SUBSCHEMAS and isinstance(value, dict):
            if any(_names_meta_schema(item) for item in value.values()):
                return True
        elif _names_meta_schema(value):
            return True
    return False


def _without_meta_schema(schema):
    """`schema` with every `$schema` keyword removed, at any depth, and every name left alone."""
    if isinstance(schema, list):
        return [_without_meta_schema(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    result = {}
    for key, value in schema.items():
        if key == "$schema":
            continue
        if key in LITERALS:
            result[key] = value
        elif key in NAMED_SUBSCHEMAS and isinstance(value, dict):
            result[key] = {name: _without_meta_schema(item) for name, item in value.items()}
        else:
            result[key] = _without_meta_schema(value)
    return result


def _check_paths(request):
    """The filesystem side of `LaunchRequest.check`: the cwd and the files the launch line reads."""
    cwd = Path(request.cwd)
    if not cwd.is_dir():
        raise LaunchError("request.cwd %s is not a directory" % cwd)
    if request.settings_path is not None and not Path(request.settings_path).is_file():
        raise LaunchError("request.settings_path %s is not a file" % request.settings_path)
    return cwd


def _write_session(run_dir, request, prompt_text, executable, command, session_id):
    """Write the request beside where the stream will go: prompt, agent, settings, schema, env.

    A previous run's `result.json` and `pid` are removed first, so a relaunch into a used
    directory never shows the earlier result next to the new stream.
    """
    run_dir.mkdir(parents=True, exist_ok=True)
    for stale in ("result.json", "pid"):
        try:
            (run_dir / stale).unlink()
        except FileNotFoundError:
            pass
    _write_text(run_dir / "prompt.md", prompt_text if prompt_text.endswith("\n") else prompt_text + "\n")
    agents = request.agent_json if isinstance(request.agent_json, dict) else json.loads(request.agent_json)
    _write_text(run_dir / "agent.json", json.dumps(agents, indent=2) + "\n")
    if request.settings_path is None:
        _write_text(run_dir / "settings.json", "{}\n")
    elif Path(request.settings_path).resolve() != (run_dir / "settings.json").resolve():
        _write_text(run_dir / "settings.json", Path(request.settings_path).read_text(encoding="utf-8"))
    if request.schema_path is not None and Path(request.schema_path).resolve() != (run_dir / "schema.json").resolve():
        _write_text(run_dir / "schema.json", _load_schema(request.schema_path)[0])
    record = {
        "executable": executable,
        "command": command,
        "stdin": "/dev/null",
        "cwd": str(request.cwd),
        "env": {key: str(value) for key, value in request.env.items()},
        "resume_of": session_id,
        "started_at": now_ts(),
    }
    _write_text(run_dir / "env.json", json.dumps(record, indent=2) + "\n")


# --- the launch line ----------------------------------------------------------------------------


def build_argv(request, run_dir, session_id=None, message=None):
    """The argv of the launch line of decision 3 (or of the resume, with `session_id` and `message`).

    The request is checked first and the schema is read and checked here, so a request the
    line cannot carry is refused before a session is spent.
    """
    request.check()
    if session_id is not None and (not isinstance(message, str) or not message.strip()):
        raise LaunchError("a resume needs a non-empty message")
    run_dir = Path(run_dir)
    prompt = request.prompt if session_id is None else message
    argv = [ClaudeCli.executable, "-p", prompt]
    if session_id is not None:
        argv += ["--resume", session_id]
    argv += ["--agents", request.agent_text(), "--agent", request.role]
    argv += ["--model", request.model, "--effort", request.effort]
    argv += ["--permission-mode", "dontAsk", "--permission-prompts", "none"]
    if request.allowed_tools:
        argv += ["--allowedTools", *[str(tool) for tool in request.allowed_tools]]
    if request.disallowed_tools:
        argv += ["--disallowedTools", *[str(tool) for tool in request.disallowed_tools]]
    argv += ["--settings", str(run_dir / "settings.json")]
    for directory in request.add_dirs:
        argv += ["--add-dir", str(directory)]
    argv += ["--output-format", "stream-json", "--verbose"]
    if request.schema_path is not None:
        argv += ["--json-schema", _load_schema(request.schema_path)[0]]
    argv += ["--fallback-model", FALLBACK_MODEL]
    return argv


def spelled_argv(argv, run_dir):
    """The launch line as the spec writes it: the prompt, the agents, and the schema as `$(cat <file>)`."""
    run_dir = Path(run_dir)
    spelled = list(argv)
    spelled[2] = "$(cat %s)" % (run_dir / "prompt.md")
    for flag, name in (("--agents", "agent.json"), ("--json-schema", "schema.json")):
        if flag in spelled[3:]:
            spelled[spelled.index(flag, 3) + 1] = "$(cat %s)" % (run_dir / name)
    return spelled


# --- the stream ----------------------------------------------------------------------------------


@dataclass
class Parsed:
    """What `parse_stream` found: the init, every rate limit event, the final result, and the torn lines."""

    session_id: Optional[str] = None
    model: Optional[str] = None
    init: Optional[dict] = None
    rate_limit_events: list = field(default_factory=list)
    result: Optional[dict] = None
    torn_lines: int = 0
    messages: int = 0


def parse_stream(path):
    """Read a `stream.jsonl` whole: `system/init`, every `rate_limit_event`, the final `result`.

    A line that is not a JSON object (the torn tail a killed worker leaves) is counted and skipped.
    A missing file parses as empty.
    """
    parsed = Parsed()
    path = Path(path)
    if not path.exists():
        return parsed
    with open(path, "rb") as handle:
        for raw in handle:
            line = raw.strip()
            if not line:
                continue
            try:
                message = json.loads(line.decode("utf-8"))
            except ValueError:
                parsed.torn_lines += 1
                continue
            if not isinstance(message, dict):
                parsed.torn_lines += 1
                continue
            parsed.messages += 1
            kind = message.get("type")
            if kind == "system" and message.get("subtype") == "init" and parsed.init is None:
                parsed.init = message
                parsed.session_id = message.get("session_id") if isinstance(message.get("session_id"), str) else None
                parsed.model = message.get("model") if isinstance(message.get("model"), str) else None
            elif kind == "rate_limit_event":
                parsed.rate_limit_events.append(RateLimitEvent.from_info(message.get("rate_limit_info")))
            elif kind == "result":
                parsed.result = message
    if parsed.torn_lines:
        _log.warning("%s: skipped %d torn line(s)", path, parsed.torn_lines)
    return parsed


def read_envelope(stream_path, schema_path, exit_code=None, errors=()):
    """The envelope of a stream on disk, with `structured_output` re-validated against `schema_path`.

    Works for a stream another process wrote (the conductor re-adopting a worker by pid and
    stream file); `exit_code` is None when the process is not this caller's.
    """
    return _envelope_from(parse_stream(stream_path), Path(stream_path), schema_path, exit_code, errors)


def _envelope_from(parsed, stream_path, schema_path, exit_code, errors):
    errors = list(errors)
    result = parsed.result
    structured_output = None
    if result is None:
        errors.append("no result message in the stream (the worker did not finish)")
    else:
        reported = result.get("errors")
        for item in (reported if isinstance(reported, list) else [reported] if reported else []):
            errors.append(str(item))
        subtype = result.get("subtype")
        if subtype == "error_max_structured_output_retries":
            errors.append("the result is error_max_structured_output_retries: the worker never returned an output the schema accepts")
        elif schema_path is not None:
            if "structured_output" not in result:
                errors.append("the result carries no structured_output (subtype %s); the worker stopped without returning it" % subtype)
            elif not isinstance(result["structured_output"], dict):
                errors.append("structured_output is not an object (got %s)" % type(result["structured_output"]).__name__)
            else:
                problems = validate(result["structured_output"], _load_schema(schema_path)[1])
                if problems:
                    errors.append("structured_output does not match the schema: " + "; ".join("%s: %s" % (problem.path, problem.message) for problem in problems))
                else:
                    structured_output = result["structured_output"]
    is_error = result is None or bool(result.get("is_error")) or (schema_path is not None and structured_output is None)
    result = result or {}
    return Envelope(
        session_id=parsed.session_id or (result.get("session_id") if isinstance(result.get("session_id"), str) else None),
        model=parsed.model,
        structured_output=structured_output,
        is_error=is_error,
        subtype=result.get("subtype") if isinstance(result.get("subtype"), str) else None,
        num_turns=_integer(result.get("num_turns")),
        duration_ms=_integer(result.get("duration_ms")),
        duration_api_ms=_integer(result.get("duration_api_ms")),
        usage=result.get("usage") if isinstance(result.get("usage"), dict) else None,
        model_usage=result.get("modelUsage") if isinstance(result.get("modelUsage"), dict) else None,
        permission_denials=list(result["permission_denials"]) if isinstance(result.get("permission_denials"), list) else [],
        api_error_status=_integer(result.get("api_error_status")),
        rate_limit_events=list(parsed.rate_limit_events),
        exit_code=exit_code,
        stream_path=stream_path,
        errors=errors,
        result_text=result.get("result") if isinstance(result.get("result"), str) else None,
    )


def _integer(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _number(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _exit_code(returncode):
    """Fold a signal death the shell way: -15 becomes 143."""
    if returncode is None:
        return None
    return 128 - returncode if returncode < 0 else returncode


# --- the claude_cli backend ---------------------------------------------------------------------


class ClaudeCli:
    """The real backend: the launch line of decision 3 as a subprocess, its stream parsed from disk."""

    name = "claude_cli"
    executable = "claude"

    def launch(self, request, on_start=None):
        request.check()
        return self._run(request, request.run_dir, None, None, on_start)

    def resume(self, request, session_id, message, on_start=None):
        request.check()
        if not isinstance(session_id, str) or not session_id:
            raise LaunchError("resume needs the session id of the launch")
        return self._run(request, _resume_dir(request.run_dir), session_id, message, on_start)

    def pid_alive(self, pid):
        """Whether the kernel still knows the pid (a zombie counts until it is reaped)."""
        try:
            os.kill(int(pid), 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def _executable(self):
        override = os.environ.get("WAYLINE_CLAUDE")
        if override:
            if not (os.path.isfile(override) and os.access(override, os.X_OK)):
                raise LaunchError("WAYLINE_CLAUDE=%s is not an executable file" % override)
            return os.path.abspath(override)  # the child runs in another cwd
        found = shutil.which(self.executable)
        if found is None:
            raise LaunchError("%s is not on PATH; install Claude Code or set WAYLINE_CLAUDE to the executable" % self.executable)
        return found

    def _run(self, request, run_dir, session_id, message, on_start):
        executable = self._executable()
        cwd = _check_paths(request)
        argv = build_argv(request, run_dir, session_id, message)
        _write_session(run_dir, request, argv[2], executable, spelled_argv(argv, run_dir), session_id)
        child_env = dict(os.environ)
        child_env.update({key: str(value) for key, value in request.env.items()})
        child_env.pop("CLAUDE_CODE_RETRY_WATCHDOG", None)  # workers fail fast; the conductor owns the wait
        stream_path = run_dir / "stream.jsonl"
        stderr_path = run_dir / "stderr.txt"
        errors = []
        with open(stream_path, "wb") as stream, open(stderr_path, "wb") as stderr:
            try:
                process = subprocess.Popen(
                    [executable] + argv[1:], stdin=subprocess.DEVNULL, stdout=stream, stderr=stderr,
                    cwd=str(cwd), env=child_env,
                )
            except OSError as exc:
                raise LaunchError("could not start %s: %s" % (executable, exc))
            _write_text(run_dir / "pid", "%d\n" % process.pid)
            if on_start is not None:
                try:
                    on_start(Started(process.pid, run_dir, stream_path))
                except BaseException:
                    process.kill()  # a caller that cannot record the pid must not leave an orphan
                    process.wait()
                    raise
            timeout = request.max_minutes * 60 if request.max_minutes else None
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                errors.append("timeout: no result within %s minute(s); SIGTERM sent" % request.max_minutes)
                process.terminate()
                try:
                    process.wait(timeout=TERM_GRACE_SECONDS)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                    errors.append("the worker ignored SIGTERM for %d s; SIGKILL sent" % TERM_GRACE_SECONDS)
        parsed = parse_stream(stream_path)
        if parsed.result is not None:
            _write_text(run_dir / "result.json", json.dumps(parsed.result, indent=2) + "\n")
        return _envelope_from(parsed, stream_path, request.schema_path, _exit_code(process.returncode), errors)


# --- the fake backend ----------------------------------------------------------------------------


@dataclass
class Patch:
    """Files the fake writes in the request's cwd before returning, committed there unless `commit` is False.

    Only the patch's own files are staged; a commit is skipped when they leave the tree unchanged.
    """

    files: dict
    message: str = "fake worker: scripted patch"
    commit: bool = True


@dataclass
class Scripted:
    """One scripted call. `ticket` and `role` restrict which request may take it (parallel launches)."""

    envelope: Envelope
    patch: Optional[Patch] = None
    delay: float = 0.0
    alive: Optional[bool] = None
    died: bool = False
    ticket: Optional[str] = None
    role: Optional[str] = None

    def matches(self, request):
        if self.ticket is not None and str(request.env.get("WAYLINE_TICKET")) != self.ticket:
            return False
        if self.role is not None and request.role != self.role:
            return False
        return True


@dataclass
class Call:
    """One call the fake received, for assertions."""

    kind: str
    request: LaunchRequest
    session_id: Optional[str]
    message: Optional[str]
    run_dir: Path
    pid: int


class FakeLauncher:
    """The fake backend: scripted envelopes, written as a stream the same parser reads.

    Script with `script(envelope, patch=, delay=, alive=, died=, ticket=, role=)` in a test, or
    with the JSON list in `WAYLINE_FAKE_SCRIPT` for a demo (entries `{"envelope": {...}, "patch":
    {"files": {...}, "message": "...", "commit": true}, "delay": 0, "alive": null, "died": false,
    "ticket": null, "role": null}`). A call takes the first entry whose `ticket` and `role`
    match it (an entry with neither matches any call), so parallel launches are keyed by
    `WAYLINE_TICKET` when the script says so and by order otherwise. Fields left None on a
    scripted envelope are filled the way a real session would fill them; the scripted
    `structured_output` is validated against the request's schema exactly as the real backend
    validates it. `died` cuts the stream after `system/init`, as a killed worker leaves it, and
    hands the scripted `errors` over as the harness's own (the timeout text). `alive` seeds the
    pid-alive simulation `pid_alive` answers from; `alive` is a dict a test may edit directly.
    """

    name = "fake"

    def __init__(self):
        self._lock = threading.Lock()
        self.reset()

    def reset(self):
        with self._lock:
            self.queue = []
            self.calls = []
            self.alive = {}
            self._loaded = None
            self._next_pid = 100000

    @staticmethod
    def _scripted(envelope, patch=None, delay=0.0, alive=None, died=False, ticket=None, role=None):
        if not isinstance(envelope, Envelope):
            envelope = Envelope.from_dict(envelope)
        if patch is not None and not isinstance(patch, Patch):
            if not isinstance(patch, dict) or not isinstance(patch.get("files"), dict):
                raise LaunchError("a patch is {files: {path: content}, message?, commit?}, got %r" % (patch,))
            unknown = sorted(set(patch) - {"files", "message", "commit"})
            if unknown:
                raise LaunchError("patch has no field(s) %s" % ", ".join(unknown))
            patch = Patch(**patch)
        if alive is not None and not isinstance(alive, bool):
            raise LaunchError("alive is true, false, or null, got %r" % (alive,))
        if delay is None:
            delay = 0.0
        if isinstance(delay, bool) or not isinstance(delay, (int, float)) or delay < 0:
            raise LaunchError("delay is a number of seconds, got %r" % (delay,))
        if role is not None and not isinstance(role, str):
            raise LaunchError("role is a string or null")
        return Scripted(envelope, patch, float(delay), alive, bool(died), None if ticket is None else str(ticket), role)

    def script(self, envelope, patch=None, delay=0.0, alive=None, died=False, ticket=None, role=None):
        entry = self._scripted(envelope, patch, delay, alive, died, ticket, role)
        with self._lock:
            self.queue.append(entry)
        return entry

    @classmethod
    def _parse_script(cls, path):
        try:
            with open(path, encoding="utf-8") as handle:
                entries = json.load(handle)
        except (OSError, ValueError) as exc:
            raise LaunchError("fake script %s cannot be read: %s" % (path, exc))
        if not isinstance(entries, list):
            raise LaunchError("%s: a fake script is a JSON list of entries" % path)
        parsed = []
        for entry in entries:
            if not isinstance(entry, dict) or "envelope" not in entry:
                raise LaunchError("%s: every entry is an object with an envelope" % path)
            unknown = sorted(set(entry) - {"envelope", "patch", "delay", "alive", "died", "ticket", "role"})
            if unknown:
                raise LaunchError("%s: entry has no field(s) %s" % (path, ", ".join(unknown)))
            parsed.append(cls._scripted(entry["envelope"], entry.get("patch"), entry.get("delay"), entry.get("alive"), entry.get("died", False), entry.get("ticket"), entry.get("role")))
        return parsed

    def load(self, path):
        """Script from a JSON file in-process (the `WAYLINE_FAKE_SCRIPT` of a demo does this on first use)."""
        entries = self._parse_script(path)
        with self._lock:
            self.queue.extend(entries)

    def launch(self, request, on_start=None):
        request.check()
        return self._run("launch", request, request.run_dir, None, None, on_start)

    def resume(self, request, session_id, message, on_start=None):
        request.check()
        if not isinstance(session_id, str) or not session_id:
            raise LaunchError("resume needs the session id of the launch")
        return self._run("resume", request, _resume_dir(request.run_dir), session_id, message, on_start)

    def pid_alive(self, pid):
        return bool(self.alive.get(int(pid), False))

    def _take(self, request):
        with self._lock:
            script_path = os.environ.get("WAYLINE_FAKE_SCRIPT")
            if script_path and self._loaded != script_path:
                self.queue.extend(self._parse_script(script_path))  # a malformed file fails every call, not just the first
                self._loaded = script_path
            for index, entry in enumerate(self.queue):
                if entry.matches(request):
                    del self.queue[index]
                    pid = self._next_pid
                    self._next_pid += 1
                    return entry, pid
        raise LaunchError("the fake launcher has no scripted envelope left for role %r, ticket %s" % (request.role, request.env.get("WAYLINE_TICKET")))

    def _run(self, kind, request, run_dir, session_id, message, on_start):
        _check_paths(request)
        argv = build_argv(request, run_dir, session_id, message)  # refused before an entry is consumed
        scripted, pid = self._take(request)
        _write_session(run_dir, request, request.prompt if session_id is None else message, "fake", spelled_argv(argv, run_dir), session_id)
        stream_path = run_dir / "stream.jsonl"
        _write_text(run_dir / "stderr.txt", "")
        _write_text(run_dir / "pid", "%d\n" % pid)
        given = scripted.envelope
        session = given.session_id or session_id or str(uuid.uuid4())
        model = given.model or RESOLVED_MODELS.get(request.model, request.model)
        head = [{"type": "system", "subtype": "init", "session_id": session, "model": model, "cwd": str(request.cwd),
                 "permissionMode": "dontAsk", "agents": [request.role], "apiKeySource": "none", "fake": True}]
        for event in given.rate_limit_events:
            head.append({"type": "rate_limit_event", "rate_limit_info": _rate_limit_info(event), "session_id": session})
        _write_text(stream_path, "".join(json.dumps(line) + "\n" for line in head))  # visible while the call runs, as the real stream is
        if scripted.alive is not None:
            self.alive[pid] = scripted.alive
        with self._lock:
            self.calls.append(Call(kind, request, session_id, message, run_dir, pid))
        if on_start is not None:
            on_start(Started(pid, run_dir, stream_path))
        if scripted.patch is not None:
            _apply_patch(Path(request.cwd), scripted.patch)
        if scripted.delay:
            time.sleep(scripted.delay)
        exit_code = given.exit_code
        harness_errors = []
        if scripted.died:
            exit_code = 143 if exit_code is None else exit_code
            harness_errors = list(given.errors)
        else:
            subtype = given.subtype or "success"
            result = {
                "type": "result", "subtype": subtype,
                "is_error": bool(given.is_error) if given.is_error is not None else subtype != "success",
                "num_turns": 1 if given.num_turns is None else given.num_turns,
                "duration_ms": 1000 if given.duration_ms is None else given.duration_ms,
                "duration_api_ms": 800 if given.duration_api_ms is None else given.duration_api_ms,
                "usage": {"input_tokens": 0, "output_tokens": 0} if given.usage is None else given.usage,
                "modelUsage": {} if given.model_usage is None else given.model_usage,
                "permission_denials": list(given.permission_denials),
                "api_error_status": given.api_error_status,
                "result": given.result_text if given.result_text is not None else (json.dumps(given.structured_output) if given.structured_output is not None else ""),
                "session_id": session,
                "fake": True,
            }
            if given.structured_output is not None:
                result["structured_output"] = given.structured_output
            if given.errors:
                result["errors"] = list(given.errors)
            with open(stream_path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(result) + "\n")
            if exit_code is None:
                exit_code = 1 if result["is_error"] else 0
        parsed = parse_stream(stream_path)
        if parsed.result is not None:
            _write_text(run_dir / "result.json", json.dumps(parsed.result, indent=2) + "\n")
        return _envelope_from(parsed, stream_path, request.schema_path, exit_code, harness_errors)


def _rate_limit_info(event):
    info = {"status": event.status, "resetsAt": event.resets_at, "rateLimitType": event.rate_limit_type}
    windows = {}
    for name in ("five_hour", "seven_day"):
        window = getattr(event, name)
        if window is not None:
            windows[name] = {"utilization": window.utilization, "resetsAt": window.resets_at}
    if windows:
        info["unifiedWindows"] = windows
    return info


def _apply_patch(cwd, patch):
    root = cwd.resolve()
    written = []
    for relative, content in patch.files.items():
        target = cwd / relative
        if not target.resolve().is_relative_to(root):
            raise LaunchError("patch path %r leaves the request's cwd" % relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        written.append(str(target.resolve().relative_to(root)))
    if patch.commit:
        _git(cwd, "add", "--", *written)
        staged = _git(cwd, "diff", "--cached", "--quiet", ok=(0, 1))
        if staged.returncode == 1:
            _git(cwd, "commit", "-q", "-m", patch.message)


def _git(cwd, *args, ok=(0,)):
    command = ["git", "-C", str(cwd), "-c", "user.name=wayline fake worker", "-c", "user.email=fake@wayline.invalid", *args]
    done = subprocess.run(command, capture_output=True, text=True)
    if done.returncode not in ok:
        raise LaunchError("the fake could not run git %s in %s (exit %d): %s" % (args[0], cwd, done.returncode, (done.stderr or done.stdout).strip()))
    return done


# --- the seam ------------------------------------------------------------------------------------


CLAUDE_CLI = ClaudeCli()
FAKE = FakeLauncher()
BACKENDS = {ClaudeCli.name: CLAUDE_CLI, FakeLauncher.name: FAKE}


def backend():
    """The backend `WAYLINE_LAUNCHER` selects: `claude_cli` (default) or `fake`."""
    name = os.environ.get("WAYLINE_LAUNCHER") or ClaudeCli.name
    try:
        return BACKENDS[name]
    except KeyError:
        raise LaunchError("WAYLINE_LAUNCHER=%s names no backend; the backends are %s" % (name, ", ".join(BACKENDS)))


def launch(request, on_start=None):
    """Run one session and return its envelope; `on_start(Started)` fires when the process exists."""
    return backend().launch(request, on_start)


def resume(request, session_id, message, on_start=None):
    """Continue a session with `message` and return the envelope of the continuation."""
    return backend().resume(request, session_id, message, on_start)


def pid_alive(pid):
    """Whether a worker pid is still running, through the selected backend."""
    return backend().pid_alive(pid)


@contextmanager
def use_fake():
    """Select the fake for a block (tests) and hand it over for scripting, reset before and after.

    `WAYLINE_FAKE_SCRIPT` is unset for the block, so a script file exported for a demo cannot
    leak into a scripted test. Not re-entrant.
    """
    previous = {name: os.environ.get(name) for name in ("WAYLINE_LAUNCHER", "WAYLINE_FAKE_SCRIPT")}
    os.environ["WAYLINE_LAUNCHER"] = FakeLauncher.name
    os.environ.pop("WAYLINE_FAKE_SCRIPT", None)
    FAKE.reset()
    try:
        yield FAKE
    finally:
        FAKE.reset()
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


# --- the smoke verb ------------------------------------------------------------------------------


SMOKE_SCHEMA = {
    "type": "object",
    "properties": {"word": {"type": "string"}, "cwd": {"type": "string"}},
    "required": ["word", "cwd"],
    "additionalProperties": False,
}
SMOKE_PROMPT = (
    "Run exactly one shell command: `pwd`. Then return the structured result: "
    "word is the string \"wayline\" and cwd is the output of pwd. Do not read any files."
)
SMOKE_DISALLOWED = ["Read", "Edit", "Write", "NotebookEdit", "Grep", "Glob", "Agent", "WebFetch", "WebSearch"]


def smoke_request(run_dir, model="sonnet", effort="low"):
    """One cheap session with a two-field schema, through whichever backend is selected."""
    run_dir = Path(run_dir).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    schema_path = run_dir / "schema.json"
    _write_text(schema_path, json.dumps(SMOKE_SCHEMA, indent=2) + "\n")
    agent = {"smoke": {
        "description": "Smoke-test session for the wayline launcher.",
        "prompt": "You are a smoke-test session. Run only the one command you are told to run and return the structured result. Never read, cat, grep, or open any file.",
        "model": model, "effort": effort, "maxTurns": 6, "permissionMode": "dontAsk",
    }}
    return LaunchRequest(
        role="smoke", model=model, effort=effort, prompt=SMOKE_PROMPT, agent_json=agent,
        allowed_tools=["Bash(pwd)"], disallowed_tools=list(SMOKE_DISALLOWED), settings_path=None,
        add_dirs=[str(HARNESS_ROOT)], cwd=str(run_dir), env={"WAYLINE_RUN": str(run_dir)},
        schema_path=str(schema_path), max_minutes=5,
    )


def describe_windows(envelope):
    """The five-hour and seven-day utilization of the latest rate limit event, as printable lines."""
    if not envelope.rate_limit_events:
        return ["usage windows: no rate_limit_event in the stream"]
    last = envelope.rate_limit_events[-1]
    lines = ["usage windows (status %s, type %s):" % (last.status, last.rate_limit_type)]
    for name, window in (("five_hour", last.five_hour), ("seven_day", last.seven_day)):
        if window is None:
            lines.append("  %s: unknown (no unifiedWindows block; read /usage instead)" % name)
        elif window.utilization is None:
            lines.append("  %s: unknown (the window carries no utilization)" % name)
        else:
            lines.append("  %s: %d%% used, resets %s" % (name, round(window.utilization * 100), _epoch(window.resets_at)))
    return lines


def _epoch(value):
    if value is None:
        return "unknown"
    return datetime.fromtimestamp(value, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def launch_verb(args):
    """`wayline launch --smoke [--dir <path>] [--model <alias>] [--effort <effort>]` (hidden)."""
    parser = argparse.ArgumentParser(prog="wayline launch", description="one real cheap session through the launcher")
    parser.add_argument("--smoke", action="store_true", required=True, help="run the smoke session and print the envelope")
    parser.add_argument("--dir", help="the session directory (default: ~/.wayline/smoke/<timestamp>)")
    parser.add_argument("--model", default="sonnet", choices=MODEL_ALIASES)
    parser.add_argument("--effort", default="low", choices=EFFORTS)
    try:
        options = parser.parse_args(args)
    except SystemExit as exc:
        return int(exc.code or 0)
    run_dir = Path(options.dir).resolve() if options.dir else Path.home() / ".wayline" / "smoke" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    try:
        request = smoke_request(run_dir, options.model, options.effort)
        print("launching the smoke session through the %s backend into %s" % (backend().name, run_dir), flush=True)
        envelope = launch(request)
    except (LaunchError, OSError) as exc:
        print("wayline launch: %s" % exc, file=sys.stderr)
        return 1
    print(json.dumps(envelope.as_dict(), indent=2))
    print()
    for line in describe_windows(envelope):
        print(line)
    print("session directory: %s" % run_dir)
    if not envelope.valid:
        print("invalid result: %s" % "; ".join(envelope.errors))
        return 1
    return 0
