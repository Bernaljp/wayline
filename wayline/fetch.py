"""The fetch seam (Testing Decisions, seam 5): one `fetch(url, headers)` with a live and a recording backend.

Seven external services are read by the harness: Crossref, OpenAlex, Unpaywall, Europe PMC,
the arXiv API and its source endpoint, the bioRxiv API, and the five plot galleries. They all
come through this module, so their tests replay recorded responses instead of faking `urllib`
in five places, and so the two things every one of them asks of a polite client are enforced
once: the `User-Agent: wayline/<tag> (mailto:<owner email>)` that puts Crossref in the polite
pool, and the per-host rate limit.

A backend answers one question, `send(request) -> Response`. `UrllibBackend` asks the network.
`DirectoryBackend` answers from a directory of recorded responses keyed by request hash, and
either falls through to an inner backend and records what comes back (the plot-gallery crawl's
cache, which keeps only successful answers) or refuses (the suite's `fixtures/fetch/`, where a
request nobody recorded is a test that would otherwise have reached the network, and where a
recorded failure replays like any answer, because a recording is not a cache). `AnswerCache` is
the scout's cache under `research/.cache/scout/` (decision 17): it writes only successful answers
and replays one only when the caller says the work is already found, so a passing outage is
never kept and every lookup about a work not yet found goes to the network.

The request hash leaves out what varies between owners: the `User-Agent` header, and the
`mailto` and `email` query parameters that Crossref and Unpaywall want the owner's address in.
A recording made on one machine therefore replays on another, which is what lets the suite ship
responses recorded against the live services.
"""

import base64
import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from wayline import TAG, real_backend

__all__ = [
    "FetchError", "Response", "Request", "request_hash", "user_agent", "canonical_url",
    "RateLimiter", "Backend", "UrllibBackend", "DirectoryBackend", "Fetcher",
    "RATE_LIMITS", "DEFAULT_RATE", "FIXTURES", "recording_fetcher", "caching_fetcher", "AnswerCache",
]

# The minimum seconds between two requests to one host, from the providers' own documented
# limits (research-notes/06, Section 3). Crossref advertises 10 per second to the polite pool;
# arXiv asks for one request per 3 s on a single connection; OpenAlex keyless is a daily budget
# rather than a rate, so it is read sparingly; the galleries are crawled at 1 per second
# (`policy.plot_index.crawl_rate_per_s`).
RATE_LIMITS = {
    "api.crossref.org": 0.1,
    "api.openalex.org": 1.0,
    "api.unpaywall.org": 1.0,
    "www.ebi.ac.uk": 0.1,
    "api.biorxiv.org": 1.0,
    "export.arxiv.org": 3.0,
    "arxiv.org": 3.0,
    "python-graph-gallery.com": 1.0,
    "r-graph-gallery.com": 1.0,
    "altair-viz.github.io": 1.0,
    "seaborn.pydata.org": 1.0,
    "plotnine.org": 1.0,
}
DEFAULT_RATE = 1.0

# Where the suite's recorded responses live, relative to the harness root.
FIXTURES = Path("fixtures") / "fetch"

# Headers that never enter a recording: a cookie is the one thing a response carries that is
# about the machine that asked rather than about the answer.
_UNRECORDED_HEADERS = ("set-cookie", "set-cookie2")

# Headers left out of the request hash, because they carry the owner's identity rather than the
# question, and the same question recorded by one owner must replay for the next.
_UNHASHED_HEADERS = ("user-agent",)

# Query parameters that carry the owner's address to the polite pools; their values are replaced
# before hashing, for the same reason.
_ADDRESS_PARAMETERS = ("mailto", "email")
_ADDRESS_PLACEHOLDER = "<owner>"

_TIMEOUT_S = 30


class FetchError(RuntimeError):
    """A request that produced no response: the network refused it, or nobody recorded it."""


@dataclass(frozen=True)
class Request:
    """One outbound read. The harness never writes over HTTP, so there is no body."""

    url: str
    headers: dict = field(default_factory=dict)
    method: str = "GET"
    # Whether a cache may answer this request from disk. Only the scout's `AnswerCache` reads it, and
    # only a lookup about a work already found sets it; it is not part of the request's identity.
    replay: bool = field(default=False, compare=False)

    @property
    def host(self):
        return urllib.parse.urlsplit(self.url).hostname or "unknown"

    @property
    def hash(self):
        return request_hash(self.url, self.headers, self.method)


@dataclass
class Response:
    """What a backend returns. A 404 is a response, not an error: the scout reads it and moves on."""

    url: str
    status: int
    headers: dict = field(default_factory=dict)
    body: bytes = b""
    from_cache: bool = False

    @property
    def ok(self):
        return 200 <= self.status < 300

    def text(self, errors="replace"):
        return self.body.decode("utf-8", errors=errors)

    def json(self):
        """The body as JSON, or None when it is not JSON (an HTML error page from a proxy, say)."""
        try:
            return json.loads(self.text(errors="strict"))
        except (ValueError, UnicodeDecodeError):
            return None


def user_agent(tag, email=None):
    """`wayline/<tag> (mailto:<owner email>)`, the string every outbound request carries.

    Without an address the parenthetical is dropped rather than filled with a placeholder: a
    polite pool that is told a fake address is worse served than one that is told nothing.
    """
    return "wayline/%s (mailto:%s)" % (tag, email) if email else "wayline/%s" % tag


def canonical_url(url):
    """`url` with the owner's address masked, which is the form the request hash is taken over."""
    parts = urllib.parse.urlsplit(url)
    if not parts.query:
        return url
    pairs = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    masked = [(key, _ADDRESS_PLACEHOLDER if key.lower() in _ADDRESS_PARAMETERS else value) for key, value in pairs]
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(masked)))


def request_hash(url, headers=None, method="GET"):
    """The sha256 a recording is filed under: the method, the canonical URL, and the stable headers."""
    stable = sorted(
        (key.lower(), str(value))
        for key, value in (headers or {}).items()
        if key.lower() not in _UNHASHED_HEADERS
    )
    material = "\n".join([method.upper(), canonical_url(url)] + ["%s: %s" % pair for pair in stable])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class RateLimiter:
    """The per-host limit, enforced in the seam so no caller can forget it.

    Two things are enforced, both per host: at most one request in flight (what arXiv means by a
    single connection), and a minimum interval between the end of one request and the start of
    the next. Pacing from the end rather than the start is the more conservative of the two
    readings, and it is the one a slow service deserves. The clock and the sleep are arguments so
    a test can assert on the waits without sleeping.
    """

    def __init__(self, limits=None, default=DEFAULT_RATE, clock=time.monotonic, sleep=time.sleep):
        self.limits = dict(RATE_LIMITS if limits is None else limits)
        self.default = default
        self.clock = clock
        self.sleep = sleep
        self.waits = []  # (host, seconds) for every wait taken, in order; the test's assertion
        self._last = {}
        self._guard = threading.Lock()
        self._hosts = {}

    def interval(self, host):
        return self.limits.get(host, self.default)

    def _host_lock(self, host):
        with self._guard:
            return self._hosts.setdefault(host, threading.Lock())

    class _Held:
        def __init__(self, limiter, host, lock):
            self.limiter, self.host, self.lock = limiter, host, lock

        def __enter__(self):
            return self

        def __exit__(self, *unused):
            self.limiter._last[self.host] = self.limiter.clock()
            self.lock.release()
            return False

    def hold(self, host):
        """Take the host's slot, waiting out the interval; release it on the way out of the block."""
        lock = self._host_lock(host)
        lock.acquire()
        try:
            interval = self.interval(host)
            last = self._last.get(host)
            if last is not None:
                wait = interval - (self.clock() - last)
                if wait > 0:
                    self.waits.append((host, wait))
                    self.sleep(wait)
        except BaseException:
            lock.release()
            raise
        return self._Held(self, host, lock)


class Backend:
    """What every backend implements: one request in, one response out."""

    def send(self, request):  # pragma: no cover - the interface
        raise NotImplementedError


class UrllibBackend(Backend):
    """The real backend: `urllib` under the seam's rate limiter."""

    def __init__(self, limiter=None, timeout=_TIMEOUT_S, opener=None):
        self.limiter = limiter if limiter is not None else RateLimiter()
        self.timeout = timeout
        self.real = opener is None  # a test's opener answers from memory; urllib's own asks the network
        self.opener = opener or urllib.request.build_opener()

    def send(self, request):
        if self.real:
            real_backend("the network (%s)" % request.host)
        outbound = urllib.request.Request(request.url, headers=dict(request.headers), method=request.method)
        with self.limiter.hold(request.host):
            try:
                with self.opener.open(outbound, timeout=self.timeout) as handle:
                    return Response(handle.geturl(), handle.status, _headers(handle.headers.items()), handle.read())
            except urllib.error.HTTPError as answer:  # 404 and its kin are answers the scout reads
                with answer:
                    return Response(answer.geturl(), answer.code, _headers(answer.headers.items()), answer.read())
            except (urllib.error.URLError, OSError, ValueError) as failure:
                raise FetchError("%s: %s" % (request.url, failure)) from None


class DirectoryBackend(Backend):
    """Recorded responses under `<root>/<host>/<request hash>.json`.

    With an `inner` backend and `record=True` this is a cache that fills itself: a miss is asked
    of the inner backend and written down. Without one it is the suite's fixture directory, and a
    miss is a `FetchError` naming the file that would have to exist, because the alternative is a
    test that quietly reaches the network.
    """

    def __init__(self, root, inner=None, record=None, keep_failures=True):
        self.root = Path(root)
        self.inner = inner
        self.record = (inner is not None) if record is None else record
        # A cache keeps only successful answers and replays nothing else; a recording keeps everything.
        self.keep_failures = keep_failures
        self.misses = []  # every request this backend could not answer from disk, in order

    def path_for(self, request):
        return self.root / request.host / (request.hash + ".json")

    def send(self, request):
        path = self.path_for(request)
        recorded = _read_recording(path)
        if recorded is not None and (self.keep_failures or recorded.ok):
            recorded.from_cache = True
            return recorded
        self.misses.append(request)
        if self.inner is None:
            raise FetchError(
                "no recorded response for %s; expected %s (record it with a live backend)" % (request.url, path)
            )
        response = self.inner.send(request)
        if self.record and (self.keep_failures or response.ok):
            _write_recording(path, request, response)
        return response


class AnswerCache(Backend):
    """The scout's cache, `research/.cache/scout/<host>/<request hash>.json` (decision 17).

    Two rules, both because a passing outage must not outlive itself. Only a successful (2xx)
    answer is written: an error status, a timeout, and a 404 all go to the network next time. And
    an answer is replayed only for a request marked `replay`, which the scout sets for a work
    already found; every lookup about a work not yet found asks the service, whatever is on disk.
    A failure an older cache kept (v1.0 wrote every answer) is never replayed either.
    """

    def __init__(self, root, inner=None):
        self.root = Path(root)
        self.inner = inner if inner is not None else UrllibBackend()
        self.misses = []  # every request asked of the network, in order
        self.replayed = []  # every request answered from disk, in order

    def path_for(self, request):
        return self.root / request.host / (request.hash + ".json")

    def send(self, request):
        path = self.path_for(request)
        if request.replay:
            recorded = _read_recording(path)
            if recorded is not None and recorded.ok:
                recorded.from_cache = True
                self.replayed.append(request)
                return recorded
        self.misses.append(request)
        response = self.inner.send(request)
        if response.ok:
            _write_recording(path, request, response)
        return response


def _headers(items):
    """Response headers, lower-cased, without the ones a recording must not carry."""
    return {key.lower(): value for key, value in items if key.lower() not in _UNRECORDED_HEADERS}


def _read_recording(path):
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    answer = record.get("response")
    if not isinstance(answer, dict):
        return None
    body = answer.get("body", "")
    raw = base64.b64decode(body) if answer.get("encoding") == "base64" else str(body).encode("utf-8")
    return Response(answer.get("url", ""), int(answer.get("status", 0)), dict(answer.get("headers") or {}), raw)


def _write_recording(path, request, response):
    try:
        body, encoding = response.body.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        body, encoding = base64.b64encode(response.body).decode("ascii"), "base64"
    record = {
        "request": {"method": request.method, "url": canonical_url(request.url), "hash": request.hash},
        "response": {
            "url": canonical_url(response.url),
            "status": response.status,
            "headers": response.headers,
            "encoding": encoding,
            "body": body,
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name("%s.%d.%d.tmp" % (path.name, os.getpid(), threading.get_ident()))  # the tick and absorb may write one hash at once
    temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return path


class Fetcher:
    """The seam itself: `fetch(url, headers) -> Response` over a backend, with the User-Agent attached."""

    def __init__(self, backend=None, tag=None, email=None):
        self.backend = backend if backend is not None else UrllibBackend()
        self.tag = tag or TAG
        self.email = email
        self.requests = []  # every request made, in order; what a test asserts a chain against

    @property
    def user_agent(self):
        return user_agent(self.tag, self.email)

    def fetch(self, url, headers=None, method="GET", replay=False):
        """One request; `replay` lets the scout's cache answer it from disk (a lookup about a work already found)."""
        outbound = {"User-Agent": self.user_agent, "Accept": "*/*"}
        outbound.update(headers or {})
        request = Request(url, outbound, method, replay)
        self.requests.append(request)
        return self.backend.send(request)

    @property
    def hosts(self):
        return [request.host for request in self.requests]


def recording_fetcher(root, email=None, tag=None, live=False, limiter=None):
    """A fetcher over a directory of recordings: the suite's (`live=False`) or a recording run's."""
    inner = UrllibBackend(limiter=limiter) if live else None
    return Fetcher(DirectoryBackend(root, inner=inner, record=live), tag=tag, email=email)


def caching_fetcher(cache_dir, email=None, tag=None, limiter=None):
    """A fetcher that answers from `cache_dir` and asks the network for what is not there yet.

    What the plot-gallery crawl runs on (`research/.cache/figures/`): only successful answers are
    kept, so a gallery page that failed is asked again on the next build. The scout runs on
    `AnswerCache` instead, which also refuses to replay an answer about a work not yet found.
    """
    backend = DirectoryBackend(cache_dir, inner=UrllibBackend(limiter=limiter), record=True, keep_failures=False)
    return Fetcher(backend, tag=tag, email=email)
