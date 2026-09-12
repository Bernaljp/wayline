"""The fetch seam: the request hash, the User-Agent, the rate limits, and the two backends.

The live backend is exercised against a fake `urllib` opener rather than the network, which is
the one place in the suite that stands in for `urllib` at all; everything above it runs on the
recorded responses under `fixtures/fetch/`.
"""

import io
import json
import shutil
import tempfile
import unittest
import urllib.error
from email.message import Message
from pathlib import Path

from tests.paths import FIXTURES_DIR
from wayline import TAG
from wayline.fetch import (
    DEFAULT_RATE, RATE_LIMITS, DirectoryBackend, FetchError, Fetcher, RateLimiter, Request,
    Response, UrllibBackend, canonical_url, recording_fetcher, request_hash, user_agent,
)


class FakeHandle:
    """What `opener.open` returns: enough of `http.client.HTTPResponse` for the backend."""

    def __init__(self, url, status, headers, body):
        self.url, self.status, self.body = url, status, body
        self.headers = Message()
        for key, value in headers.items():
            self.headers[key] = value

    def geturl(self):
        return self.url

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        return False


class FakeOpener:
    """An opener scripted with one answer per URL; records the requests it was given."""

    def __init__(self, answers):
        self.answers = answers
        self.seen = []

    def open(self, request, timeout=None):
        self.seen.append(request)
        answer = self.answers.get(request.full_url)
        if answer is None:
            raise urllib.error.URLError("no route to %s" % request.full_url)
        if isinstance(answer, Exception):
            raise answer
        status, headers, body = answer
        if status >= 400:
            error = urllib.error.HTTPError(request.full_url, status, "error", Message(), io.BytesIO(body))
            for key, value in headers.items():
                error.headers[key] = value
            raise error
        return FakeHandle(request.full_url, status, headers, body)


def fake_limiter():
    """A limiter whose clock only moves when it sleeps, so a test asserts on waits without taking them."""
    state = {"now": 1000.0}

    def clock():
        return state["now"]

    def sleep(seconds):
        state["now"] += seconds

    limiter = RateLimiter(clock=clock, sleep=sleep)
    limiter.advance = lambda seconds: state.__setitem__("now", state["now"] + seconds)
    return limiter


class RequestHashTest(unittest.TestCase):
    def test_the_hash_is_stable_and_covers_the_url(self):
        first = request_hash("https://api.crossref.org/works/10.1/a")
        self.assertEqual(first, request_hash("https://api.crossref.org/works/10.1/a"))
        self.assertNotEqual(first, request_hash("https://api.crossref.org/works/10.1/b"))
        self.assertEqual(len(first), 64)

    def test_the_owners_address_is_outside_the_hash(self):
        """A recording made by one owner replays for the next; that is why the suite can ship them."""
        mine = "https://api.crossref.org/works/10.1/a?mailto=one@example.org"
        yours = "https://api.crossref.org/works/10.1/a?mailto=two@example.net"
        self.assertEqual(request_hash(mine), request_hash(yours))
        self.assertEqual(canonical_url(mine), canonical_url(yours))
        self.assertIn("mailto=%3Cowner%3E", canonical_url(mine))

    def test_unpaywalls_email_parameter_is_masked_too(self):
        self.assertEqual(
            request_hash("https://api.unpaywall.org/v2/10.1/a?email=one@example.org"),
            request_hash("https://api.unpaywall.org/v2/10.1/a?email=two@example.net"),
        )

    def test_the_user_agent_is_outside_the_hash_but_another_header_is_not(self):
        base = "https://api.crossref.org/works/10.1/a"
        self.assertEqual(
            request_hash(base, {"User-Agent": "wayline/v0.0.0 (mailto:one@example.org)"}),
            request_hash(base, {"User-Agent": "wayline/v9.9.9 (mailto:two@example.net)"}),
        )
        self.assertNotEqual(request_hash(base, {"Accept": "application/json"}), request_hash(base))

    def test_a_query_parameter_that_is_not_an_address_still_counts(self):
        self.assertNotEqual(
            request_hash("https://api.crossref.org/works?rows=3"),
            request_hash("https://api.crossref.org/works?rows=5"),
        )


class UserAgentTest(unittest.TestCase):
    def test_the_polite_pool_form(self):
        self.assertEqual(user_agent("v0.1.0", "owner@example.org"), "wayline/v0.1.0 (mailto:owner@example.org)")

    def test_without_an_address_nothing_is_invented(self):
        agent = user_agent("v0.1.0", None)
        self.assertEqual(agent, "wayline/v0.1.0")
        self.assertNotIn("mailto", agent)

    def test_every_request_a_fetcher_makes_carries_it(self):
        opener = FakeOpener({"https://api.crossref.org/x": (200, {"content-type": "application/json"}, b"{}")})
        fetcher = Fetcher(UrllibBackend(limiter=fake_limiter(), opener=opener), email="owner@example.org")
        fetcher.fetch("https://api.crossref.org/x")
        self.assertEqual(opener.seen[0].get_header("User-agent"), "wayline/%s (mailto:owner@example.org)" % TAG)


class RateLimitTest(unittest.TestCase):
    def test_the_documented_intervals(self):
        limiter = RateLimiter()
        self.assertEqual(limiter.interval("api.crossref.org"), 0.1)  # 10 per second, polite pool
        self.assertEqual(limiter.interval("export.arxiv.org"), 3.0)  # one per 3 s
        self.assertEqual(limiter.interval("python-graph-gallery.com"), 1.0)  # the galleries
        self.assertEqual(limiter.interval("example.invalid"), DEFAULT_RATE)

    def test_openalex_is_read_no_faster_than_once_a_second(self):
        self.assertGreaterEqual(RATE_LIMITS["api.openalex.org"], 1.0)

    def test_a_second_request_to_one_host_waits_out_the_interval(self):
        limiter = fake_limiter()
        opener = FakeOpener({
            "https://export.arxiv.org/a": (200, {}, b"a"),
            "https://export.arxiv.org/b": (200, {}, b"b"),
        })
        fetcher = Fetcher(UrllibBackend(limiter=limiter, opener=opener))
        fetcher.fetch("https://export.arxiv.org/a")
        fetcher.fetch("https://export.arxiv.org/b")
        self.assertEqual([host for host, _ in limiter.waits], ["export.arxiv.org"])
        self.assertAlmostEqual(limiter.waits[0][1], 3.0)

    def test_two_hosts_do_not_wait_on_each_other(self):
        limiter = fake_limiter()
        opener = FakeOpener({
            "https://export.arxiv.org/a": (200, {}, b"a"),
            "https://api.crossref.org/b": (200, {}, b"b"),
        })
        fetcher = Fetcher(UrllibBackend(limiter=limiter, opener=opener))
        fetcher.fetch("https://export.arxiv.org/a")
        fetcher.fetch("https://api.crossref.org/b")
        self.assertEqual(limiter.waits, [])

    def test_time_already_spent_counts_against_the_interval(self):
        limiter = fake_limiter()
        opener = FakeOpener({"https://export.arxiv.org/a": (200, {}, b"a"), "https://export.arxiv.org/b": (200, {}, b"b")})
        fetcher = Fetcher(UrllibBackend(limiter=limiter, opener=opener))
        fetcher.fetch("https://export.arxiv.org/a")
        limiter.advance(2.5)
        fetcher.fetch("https://export.arxiv.org/b")
        self.assertAlmostEqual(limiter.waits[0][1], 0.5)

    def test_a_recorded_answer_costs_no_wait(self):
        """Nothing goes out, so nothing is paced: the suite runs the whole chain at full speed."""
        limiter = fake_limiter()
        fetcher = Fetcher(DirectoryBackend(FIXTURES_DIR / "fetch"), email="owner@example.org")
        fetcher.backend.inner = UrllibBackend(limiter=limiter, opener=FakeOpener({}))
        answer = fetcher.fetch("https://api.crossref.org/works/10.1038%2Fs41586-020-2649-2?mailto=owner@example.org")
        self.assertTrue(answer.from_cache)
        self.assertEqual(limiter.waits, [])


class UrllibBackendTest(unittest.TestCase):
    def test_a_404_is_a_response_the_caller_reads(self):
        opener = FakeOpener({"https://api.crossref.org/works/10.0/nope": (404, {"content-type": "text/plain"}, b"Resource not found.")})
        fetcher = Fetcher(UrllibBackend(limiter=fake_limiter(), opener=opener))
        answer = fetcher.fetch("https://api.crossref.org/works/10.0/nope")
        self.assertEqual(answer.status, 404)
        self.assertFalse(answer.ok)
        self.assertIn("not found", answer.text())

    def test_a_refused_connection_is_an_error(self):
        fetcher = Fetcher(UrllibBackend(limiter=fake_limiter(), opener=FakeOpener({})))
        with self.assertRaises(FetchError) as raised:
            fetcher.fetch("https://api.crossref.org/x")
        self.assertIn("api.crossref.org", str(raised.exception))

    def test_json_and_text_come_off_the_body(self):
        opener = FakeOpener({"https://api.crossref.org/x": (200, {"content-type": "application/json"}, b'{"a": 1}')})
        answer = Fetcher(UrllibBackend(limiter=fake_limiter(), opener=opener)).fetch("https://api.crossref.org/x")
        self.assertEqual(answer.json(), {"a": 1})
        self.assertTrue(answer.ok)

    def test_a_body_that_is_not_json_reads_as_none_rather_than_raising(self):
        opener = FakeOpener({"https://api.crossref.org/x": (200, {"content-type": "text/html"}, b"<html>")})
        answer = Fetcher(UrllibBackend(limiter=fake_limiter(), opener=opener)).fetch("https://api.crossref.org/x")
        self.assertIsNone(answer.json())


class DirectoryBackendTest(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp(prefix="wayline-fetch-"))
        self.addCleanup(shutil.rmtree, self.temp, ignore_errors=True)

    def test_a_miss_without_an_inner_backend_names_the_file_it_wanted(self):
        fetcher = recording_fetcher(self.temp, email="owner@example.org")
        with self.assertRaises(FetchError) as raised:
            fetcher.fetch("https://api.crossref.org/works/10.1/x")
        message = str(raised.exception)
        self.assertIn("api.crossref.org", message)
        self.assertIn(".json", message)

    def test_a_miss_with_an_inner_backend_is_recorded_and_replayed(self):
        url = "https://api.crossref.org/works/10.1/x?mailto=owner@example.org"
        opener = FakeOpener({url: (200, {"content-type": "application/json", "set-cookie": "s=1"}, b'{"ok": true}')})
        inner = UrllibBackend(limiter=fake_limiter(), opener=opener)
        fetcher = Fetcher(DirectoryBackend(self.temp, inner=inner, record=True), email="owner@example.org")
        first = fetcher.fetch(url)
        self.assertFalse(first.from_cache)

        replay = Fetcher(DirectoryBackend(self.temp), email="someone-else@example.net")
        second = replay.fetch("https://api.crossref.org/works/10.1/x?mailto=someone-else@example.net")
        self.assertTrue(second.from_cache)
        self.assertEqual(second.json(), {"ok": True})
        self.assertEqual(len(opener.seen), 1, "the replay must not have gone out again")

    def test_a_recording_keeps_no_cookie_and_masks_the_address(self):
        url = "https://api.crossref.org/works/10.1/x?mailto=owner@example.org"
        opener = FakeOpener({url: (200, {"content-type": "application/json", "Set-Cookie": "s=1"}, b"{}")})
        backend = DirectoryBackend(self.temp, inner=UrllibBackend(limiter=fake_limiter(), opener=opener), record=True)
        Fetcher(backend, email="owner@example.org").fetch(url)
        written = json.loads(next(self.temp.rglob("*.json")).read_text(encoding="utf-8"))
        self.assertNotIn("set-cookie", written["response"]["headers"])
        self.assertNotIn("owner@example.org", json.dumps(written))

    def test_a_recording_is_filed_under_its_host_and_hash(self):
        url = "https://api.crossref.org/works/10.1/x"
        opener = FakeOpener({url: (200, {}, b"{}")})
        backend = DirectoryBackend(self.temp, inner=UrllibBackend(limiter=fake_limiter(), opener=opener), record=True)
        Fetcher(backend).fetch(url)
        self.assertTrue((self.temp / "api.crossref.org" / (request_hash(url, {"User-Agent": "x", "Accept": "*/*"}) + ".json")).is_file())

    def test_bytes_that_are_not_text_survive_the_round_trip(self):
        url = "https://export.arxiv.org/src/1706.03762"
        body = bytes(range(256))
        opener = FakeOpener({url: (200, {"content-type": "application/x-eprint-tar"}, body)})
        backend = DirectoryBackend(self.temp, inner=UrllibBackend(limiter=fake_limiter(), opener=opener), record=True)
        Fetcher(backend).fetch(url)
        self.assertEqual(Fetcher(DirectoryBackend(self.temp)).fetch(url).body, body)

    def test_every_request_is_remembered_for_the_test_that_asserts_on_the_chain(self):
        fetcher = recording_fetcher(self.temp)
        for url in ("https://api.crossref.org/a", "https://api.openalex.org/b"):
            with self.assertRaises(FetchError):
                fetcher.fetch(url)
        self.assertEqual(fetcher.hosts, ["api.crossref.org", "api.openalex.org"])
        self.assertEqual(
            [request.url for request in fetcher.backend.misses],
            ["https://api.crossref.org/a", "https://api.openalex.org/b"],
        )


class ResponseTest(unittest.TestCase):
    def test_status_families(self):
        self.assertTrue(Response("u", 200).ok)
        self.assertTrue(Response("u", 204).ok)
        self.assertFalse(Response("u", 429).ok)

    def test_a_request_knows_its_host_and_hash(self):
        request = Request("https://api.biorxiv.org/details/biorxiv/10.1101/x/na/json")
        self.assertEqual(request.host, "api.biorxiv.org")
        self.assertEqual(request.hash, request_hash(request.url))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
