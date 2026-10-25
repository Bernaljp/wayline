"""The showcase (`showcase/build.py`): the dashboard over the M8 toy run as a static site, built from this checkout's
own page and server, so that a change to either is a change to the showcase.

`built_site()` builds it once per process from the committed snapshot (or takes the site `SHOWCASE_SITE` names, which
`.github/workflows/showcase.yml` builds first). These tests read what the build wrote: every GET route of the server
is accounted for, every view answered over the snapshot, the page is the dashboard's own, and nothing the snapshot
leaves out came back. `tests/test_showcase_browser.py` opens the site in a browser.
"""

import atexit
import functools
import json
import os
import re
import shutil
import tarfile
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlsplit

from showcase import build
from wayline.dashboard import STATIC_ROOT, DashboardHandler


@functools.lru_cache(maxsize=None)
def built_site():
    """The site and `showcase.json`'s index, built once for this process."""
    named = os.environ.get("SHOWCASE_SITE")
    if named:
        site = Path(named)
    else:
        scratch = Path(tempfile.mkdtemp(prefix="showcase-test-"))
        atexit.register(shutil.rmtree, scratch, True)
        site = scratch / "site"
        build.build(site)
    return site, json.loads((site / "showcase.json").read_text(encoding="utf-8"))


class CoverageTest(unittest.TestCase):
    def test_every_get_route_of_the_server_is_accounted_for(self):
        routes = {name for _, name in DashboardHandler.ROUTES}
        self.assertEqual(set(build.COVERAGE), routes,
                         "the dashboard's GET routes changed: say in showcase/build.py COVERAGE how the showcase answers each")

    def test_every_route_said_to_be_recorded_has_a_recording(self):
        _, index = built_site()
        recorded = list(index["recordings"])
        for pattern, name in DashboardHandler.ROUTES:
            if build.COVERAGE.get(name) == build.RECORDED:
                with self.subTest(route=name):
                    self.assertTrue(any(pattern.match(urlsplit(path).path) for path in recorded), name)

    def test_every_view_answers_over_the_snapshot(self):
        _, index = built_site()
        # The toy started from a goal, with no documents, so Inherited is not offered (ticket 111).
        expected = {"inherited": 404}
        for view in build.VIEWS:
            with self.subTest(view=view):
                self.assertEqual(index["recordings"]["/api/projects/toy/" + view]["status"], expected.get(view, 200))
        self.assertEqual(index["recordings"]["/api/projects/toy/journal?tail=%d" % build.tail_lines()]["status"], 200)
        broken = sorted(path for path, recording in index["recordings"].items() if recording["status"] >= 500)
        self.assertEqual(broken, [])

    def test_a_ticket_page_is_recorded_for_every_ticket_and_items_for_what_the_views_name(self):
        site, index = built_site()
        tickets = json.loads((site / index["recordings"]["/api/projects/toy/tickets"]["body"]).read_text(encoding="utf-8"))
        for ticket in tickets:
            self.assertEqual(index["recordings"]["/api/projects/toy/tickets/%d" % ticket["id"]]["status"], 200)
        found = {path.rsplit("/", 1)[1] for path, recording in index["recordings"].items()
                 if "/items/" in path and recording["status"] == 200}
        self.assertLessEqual({"report", "account", "outline", "O1", "R1"}, found)


class PageTest(unittest.TestCase):
    def test_the_page_is_the_dashboards_own_with_relative_assets_and_the_replay_first(self):
        site, _ = built_site()
        source = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")
        page = (site / "index.html").read_text(encoding="utf-8")
        self.assertEqual(page.replace('<script src="replay.js"></script>\n', "", 1), re.sub(r'\b(href|src)="/(?!/)', r'\1="', source))
        self.assertLess(page.index('src="replay.js"'), page.index("<script src=\"vendor/"))
        self.assertNotRegex(page, r'\b(?:href|src)="/[^/]')

    def test_the_scripts_styles_and_vendored_files_are_copied_as_they_are(self):
        site, _ = built_site()
        for path in sorted(STATIC_ROOT.rglob("*")):
            relative = path.relative_to(STATIC_ROOT)
            if path.is_file() and relative.name != "index.html":
                with self.subTest(file=str(relative)):
                    self.assertEqual((site / relative).read_bytes(), path.read_bytes())


class LeftOutTest(unittest.TestCase):
    def test_the_snapshot_holds_no_transcript_environment_or_secret(self):
        with tarfile.open(build.ARCHIVE) as archive:
            members = archive.getmembers()
            harness = json.loads(archive.extractfile("toy/harness.json").read())
            for member in members:
                name = member.name.split("/", 1)[1]
                with self.subTest(member=name):
                    self.assertFalse(build._left_out(name) and not name.endswith("stream.jsonl"), name)
                    if name.endswith("stream.jsonl"):
                        self.assertEqual(member.size, 0)
                    elif member.isfile():
                        self.assertIsNone(build.SECRET.search(archive.extractfile(member).read()))
        self.assertIsNone(harness["owner_email"])
        self.assertNotIn("notify", harness)

    def test_the_site_publishes_no_hidden_path_and_no_secret(self):
        site, _ = built_site()
        for path in site.rglob("*"):
            relative = path.relative_to(site)
            self.assertFalse(any(part.startswith(".") for part in relative.parts), relative)
            if path.is_file():
                self.assertIsNone(build.SECRET.search(path.read_bytes()), relative)

    def test_what_the_replay_says_for_a_transcript_counts_what_the_snapshot_left_out(self):
        _, index = built_site()
        about = json.loads(build.ABOUT.read_text(encoding="utf-8"))
        self.assertIn("%d sessions" % about["left_out"]["transcripts"]["count"], index["withheld"]["transcripts"])


if __name__ == "__main__":
    unittest.main()
