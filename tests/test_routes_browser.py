"""The routed views (ticket 110) in a real browser over HTTP: the hash routes, back and forward, item links opening in
the viewer, the strip's count in the title, and every view at phone width with no sideways scroll.

What the routes promise is only observable where the page runs, so these tests start the real server over a project
built as a run builds it (`test_dashboard_views.DrawnProjectCase`) and load the page in a headless Chromium
(`tests/browser.py`). A machine without a Chromium skips them; `WAYLINE_CHROMIUM` names one explicitly.
"""

import json
import unittest

from tests.browser import Browser, find_chromium
from tests.test_dashboard_views import DrawnProjectCase

CHROMIUM = find_chromium()

# What the page shows: the route, the view, the viewer, and how wide the page is laid out.
SHOWN = """(() => ({
  hash: location.hash,
  view: document.body.dataset.view,
  open: document.getElementById('viewer').open,
  viewer: document.getElementById('viewer-doc').innerText,
  title: document.getElementById('viewer-title').textContent,
  width: document.documentElement.scrollWidth,
}))()"""


@unittest.skipUnless(CHROMIUM, "no Chromium on this machine (set WAYLINE_CHROMIUM to one)")
class RoutesTestCase(DrawnProjectCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.browser = Browser(CHROMIUM)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        from wayline.decisions import open_decision
        self.decision = open_decision(self.project, "Which split is held out?", options=["a", "b"], proposed_by="conductor")["ticket"]
        self.page = self.browser.page()
        self.addCleanup(self.page.close)

    def open(self, route=""):
        self.page.goto("http://%s:%d/%s" % (self.host, self.port, route))

    def shown(self):
        return self.page.evaluate(SHOWN)

    def route(self, suffix):
        return "#/%s/%s" % (self.project_id, suffix)


class RoutingTest(RoutesTestCase):
    def test_the_page_lands_on_research_and_the_strip_count_is_in_the_title_and_on_the_tab(self):
        self.open()
        self.page.wait_for("document.querySelector('#objectives-body li.row[data-item=\"O1\"]')")
        self.assertEqual(self.shown()["hash"], self.route("research"))
        self.page.wait_for("document.title.startsWith('(1) ')")
        self.assertEqual(self.page.evaluate("document.getElementById('strip-count').textContent"), "1")
        self.page.wait_for("document.querySelector('button.tab .count') && document.querySelector('button.tab .count').textContent === '1'")
        self.assertIn("R1", self.page.evaluate("document.getElementById('beyond-body').innerText"))

    def test_back_and_forward_move_between_views_and_a_reload_keeps_the_view(self):
        self.open(self.route("research"))
        self.page.wait_for("document.body.dataset.view === 'research'")
        self.page.click("document.querySelector('#views a[data-route=\"run\"]')")
        self.page.wait_for("document.body.dataset.view === 'run' && location.hash.endsWith('/run')")
        self.page.evaluate("history.back()")
        self.page.wait_for("document.body.dataset.view === 'research' && location.hash.endsWith('/research')")
        self.page.evaluate("history.forward()")
        self.page.wait_for("document.body.dataset.view === 'run'")
        self.page.evaluate("location.reload()")
        self.page.wait_for("document.readyState === 'complete' && document.body.dataset.view === 'run'")
        self.page.click("document.querySelector('#views a[data-route=\"projects\"]')")
        self.page.wait_for("document.body.dataset.view === 'projects' && document.querySelector('#projects-body li.project-row')")


class ItemLinkTest(RoutesTestCase):
    def test_a_link_from_a_notice_opens_the_plot_over_research_and_closing_it_leaves_the_view(self):
        self.open(self.route("R1.1"))
        self.page.wait_for("document.getElementById('viewer').open && document.querySelector('#viewer-doc img')")
        shown = self.shown()
        self.assertEqual(shown["view"], "research")
        self.assertIn("what it shows", shown["viewer"].lower(), "the plot's explanation is under it")
        self.page.press("Escape")
        self.page.wait_for("!document.getElementById('viewer').open")
        self.assertEqual(self.shown()["hash"], self.route("research"))

    def test_a_result_opened_from_its_row_opens_its_report_and_back_closes_it(self):
        self.open(self.route("research"))
        link = "document.querySelector('#beyond-body li.row[data-item=\"R1\"] a.row-id')"
        self.page.wait_for(link)
        self.page.click(link)
        self.page.wait_for("document.getElementById('viewer').open && document.querySelector('#viewer-doc .markdown')")
        self.assertEqual(self.shown()["hash"], self.route("R1"))
        self.page.evaluate("history.back()")
        self.page.wait_for("!document.getElementById('viewer').open && location.hash.endsWith('/research')")

    def test_a_decision_ticket_opens_over_run_and_an_unknown_id_shows_a_line(self):
        self.open(self.route(str(self.decision)))
        self.page.wait_for("document.getElementById('viewer').open && document.querySelector('#viewer-doc .markdown')")
        self.assertEqual(self.shown()["view"], "run")
        self.open(self.route("R99"))
        self.page.wait_for("document.getElementById('viewer').open && document.querySelector('#viewer-doc .state')")
        self.assertIn("not found", self.shown()["viewer"])


class PhoneWidthTest(RoutesTestCase):
    def test_every_view_keeps_to_the_phones_width(self):
        self.page.screen(390, 844, mobile=True)
        for route, ready in (("research", "document.querySelector('#objectives-body li.row')"),
                             ("run", "document.querySelector('#software-body h3') && document.querySelector('#overview-body .grid')"),
                             ("", "document.querySelector('#projects-body li.project-row')")):
            with self.subTest(view=route or "projects"):
                self.open(self.route(route) if route else "#/")
                self.page.wait_for(ready)
                self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth"), 390,
                                     json.dumps(self.shown()))
