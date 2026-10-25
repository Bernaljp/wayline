"""The showcase in a real browser: each view of the M8 toy run, served from the built site under `/wayline/` as GitHub
Pages serves a project site, drawn by the dashboard's own page with every request answered by `replay.js`.

What `replay.js` promises is only observable where the page runs: nothing the page asks for goes unanswered, nothing
reaches the host under `/api/`, every image a view shows loads from the published files, the banner says what the page
is, and no view scrolls sideways at a phone's width. A machine without a Chromium skips these (`WAYLINE_CHROMIUM` names
one). `SHOWCASE_SHOTS` names a directory for a screenshot of each view, which `.github/workflows/showcase.yml` keeps.
"""

import base64
import functools
import http.server
import json
import os
import re
import threading
import unittest
from pathlib import Path

from tests.browser import Browser, find_chromium
from tests.test_showcase import built_site

CHROMIUM = find_chromium()
PREFIX = "/wayline"
VIEWS = ("research", "paper", "run", "marks")
# A view is settled once it is the one drawn and no request of the page is still being answered.
SETTLED = "document.body.dataset.view === %s && window.showcasePending === 0"
IMAGES_LOADED = """[...document.images].filter((image) => image.offsetParent !== null && image.getAttribute('src'))
  .every((image) => image.complete && image.naturalWidth > 0)"""
# One item of each kind the viewer opens, the first the recordings hold: an objective, a result's current report, one
# of its reports, a plot, a ticket, and the named files.
ITEM_KINDS = (r"O\d+", r"R\d+", r"R\d+-\d+", r"R\d+\.\d+", r"\d+", "report", "account", "outline", "introduction")


class _Site(http.server.SimpleHTTPRequestHandler):
    """The built site under `/wayline/` and nothing else; every path asked for is kept in `asked`."""

    asked = []

    def translate_path(self, path):
        self.asked.append(path)
        if not (path == PREFIX or path.startswith(PREFIX + "/")):
            return "/nonexistent-outside-the-site"
        return super().translate_path(path[len(PREFIX):] or "/")

    def log_message(self, *args):
        """Quiet: the tests read `asked` instead."""


@unittest.skipUnless(CHROMIUM, "no Chromium on this machine (set WAYLINE_CHROMIUM to one)")
class ShowcaseBrowserTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        site, cls.index = built_site()
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_Site, directory=str(site)))
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d%s/" % (cls.server.server_address[1], PREFIX)
        cls.browser = Browser(CHROMIUM)
        cls.shots = Path(os.environ["SHOWCASE_SHOTS"]) if os.environ.get("SHOWCASE_SHOTS") else None

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.page = self.browser.page()
        self.addCleanup(self.page.close)

    def open(self, route):
        self.page.goto(self.base + "#/toy/" + route)

    def settled(self, view):
        self.page.wait_for(SETTLED % json.dumps(view))
        self.page.wait_for(IMAGES_LOADED)

    def shoot(self, name):
        if self.shots:
            self.shots.mkdir(parents=True, exist_ok=True)
            data = self.page.send("Page.captureScreenshot", {"format": "png"})["data"]
            (self.shots / ("%s.png" % name)).write_bytes(base64.b64decode(data))

    def answered(self):
        """Nothing the page asked for went unanswered or threw, and nothing reached the host under `/api/`."""
        self.assertEqual(self.page.evaluate("window.showcaseMisses"), [])
        self.assertEqual(self.page.console_errors(), [])
        self.assertEqual([path for path in _Site.asked if path.startswith("/api/")], [])

    def test_each_view_draws_with_every_request_answered_and_the_banner_above_it(self):
        self.page.screen(1400, 900)
        for view in VIEWS:
            with self.subTest(view=view):
                self.open(view)
                self.settled(view)
                self.assertTrue(self.page.evaluate("Boolean(document.getElementById('showcase-banner'))"))
                self.shoot("view-%s" % view)
        self.answered()

    def test_an_item_of_each_kind_opens_in_the_viewer_with_its_images(self):
        found = [path.rsplit("/", 1)[1] for path, recording in sorted(self.index["recordings"].items())
                 if "/items/" in path and recording["status"] == 200]
        items = [next(item for item in found if re.fullmatch(kind, item)) for kind in ITEM_KINDS]
        self.page.screen(1400, 900)
        for item in items:
            with self.subTest(item=item):
                self.open(item)
                self.page.wait_for("document.getElementById('viewer').open && window.showcasePending === 0")
                self.page.wait_for(IMAGES_LOADED)
                self.assertNotIn("not part of", self.page.evaluate("document.getElementById('viewer-doc').innerText"))
                self.shoot("item-%s" % item.replace(".", "_"))
                self.page.evaluate("document.getElementById('viewer').close()")
        self.answered()

    def test_no_view_scrolls_sideways_at_a_phones_width(self):
        self.page.screen(390, 844, mobile=True)
        for view in VIEWS:
            with self.subTest(view=view):
                self.open(view)
                self.settled(view)
                self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth"), 390)
                self.shoot("phone-%s" % view)

    def test_the_banners_first_link_is_the_published_paper(self):
        self.open("research")
        self.settled("research")
        link = self.page.evaluate("document.querySelector('#showcase-banner a').href")
        answer = self.page.evaluate("fetch(%s).then((response) => [response.status, response.headers.get('Content-Type')])" % json.dumps(link))
        self.assertEqual(answer, [200, "application/pdf"])


if __name__ == "__main__":
    unittest.main()
