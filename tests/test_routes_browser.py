"""The routed views (tickets 110, 111, and 112) in a real browser over HTTP: the hash routes, back and forward, item
links opening in the viewer, the strip's count in the title, Inherited only for a project with documents, every view at
phone width with no sideways scroll, and Marks saving per click with one item to a phone's screen.

What the routes promise is only observable where the page runs, so these tests start the real server over a project
built as a run builds it (`test_dashboard_views.DrawnProjectCase`) and load the page in a headless Chromium
(`tests/browser.py`). A machine without a Chromium skips them; `WAYLINE_CHROMIUM` names one explicitly.
"""

import json
import unittest

from tests.browser import Browser, find_chromium
from tests.test_dashboard_marks import TOKEN, MarksServedCase
from tests.test_dashboard_paper import MidwayServedCase
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


class BrowserCase:
    """A page in a headless Chromium over the served project, and the routes of its views."""

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
        self.page = self.browser.page()
        self.addCleanup(self.page.close)

    def open(self, route=""):
        self.page.goto("http://%s:%d/%s" % (self.host, self.port, route))

    def shown(self):
        return self.page.evaluate(SHOWN)

    def route(self, suffix):
        return "#/%s/%s" % (self.project_id, suffix)

    def fits_the_phone(self, views):
        """Each view, `(route, what shows it is drawn)`, keeps to a phone's 390 pixels with no sideways scroll."""
        self.page.screen(390, 844, mobile=True)
        for route, ready in views:
            with self.subTest(view=route or "projects"):
                self.open(self.route(route) if route else "#/")
                self.page.wait_for(ready)
                self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth"), 390, json.dumps(self.shown()))


@unittest.skipUnless(CHROMIUM, "no Chromium on this machine (set WAYLINE_CHROMIUM to one)")
class RoutesTestCase(BrowserCase, DrawnProjectCase):
    def setUp(self):
        super().setUp()
        from wayline.decisions import open_decision
        self.decision = open_decision(self.project, "Which split is held out?", options=["a", "b"], proposed_by="conductor")["ticket"]


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
        self.fits_the_phone((("research", "document.querySelector('#objectives-body li.row')"),
                             ("paper", "document.querySelector('#paper-sections-body li.row[data-item=\"results\"]')"),
                             ("run", "document.querySelector('#software-body h3') && document.querySelector('#overview-body .grid')"),
                             ("", "document.querySelector('#projects-body li.project-row')")))


class PaperRouteTest(RoutesTestCase):
    """Paper for a start from zero (ticket 111), and no Inherited view: the project has no documents."""

    def test_paper_lists_the_sections_and_a_section_opens_in_the_viewer_over_it(self):
        self.open(self.route("paper"))
        link = "document.querySelector('#paper-sections-body li.row[data-item=\"results\"] a.row-id')"
        self.page.wait_for(link)
        self.assertTrue(self.page.evaluate("document.querySelector('#views a[data-route=\"inherited\"]').hidden"))
        self.page.click(link)
        self.page.wait_for("document.getElementById('viewer').open && document.querySelector('#viewer-doc .markdown')")
        self.assertEqual((self.shown()["view"], self.shown()["hash"]), ("paper", self.route("results")))

    def test_inherited_without_documents_lands_on_research(self):
        self.open(self.route("inherited"))
        self.page.wait_for("document.body.dataset.view === 'research' && location.hash.endsWith('/research')")


@unittest.skipUnless(CHROMIUM, "no Chromium on this machine (set WAYLINE_CHROMIUM to one)")
class InheritedRouteTest(BrowserCase, MidwayServedCase):
    """Inherited and Paper for a start midway (ticket 111), in the browser."""

    def test_inherited_lists_every_record_and_a_pair_opens_side_by_side(self):
        self.open(self.route("inherited"))
        for body, item in (("documents", "D1"), ("concerns", "K1"), ("claims", "P5"), ("pairs", "P5+P11"), ("pairs", "P1+P14"),
                           ("material", "M1")):
            self.page.wait_for("document.querySelector('#inherited-%s-body li.row[data-item=\"%s\"]')" % (body, item))
        self.assertFalse(self.page.evaluate("document.querySelector('#views a[data-route=\"inherited\"]').hidden"))
        self.page.click("document.querySelector('#inherited-pairs-body li.row[data-item=\"P5+P11\"] a.row-id')")
        self.page.wait_for("document.getElementById('viewer').open && document.querySelectorAll('#viewer-doc .side').length === 2")
        self.assertIn("lowest against peaks at dusk", self.shown()["viewer"])
        self.assertEqual(self.shown()["view"], "inherited")

    def test_a_concern_from_a_notice_opens_over_inherited(self):
        self.open(self.route("K1"))
        self.page.wait_for("document.getElementById('viewer').open && document.querySelector('#viewer-doc .markdown')")
        self.assertEqual(self.shown()["view"], "inherited")

    def test_paper_and_inherited_keep_to_the_phones_width(self):
        self.fits_the_phone((("paper", "document.querySelector('#paper-references-body li.row')"),
                             ("inherited", "document.querySelector('#inherited-material-body li.row')")))


@unittest.skipUnless(CHROMIUM, "no Chromium on this machine (set WAYLINE_CHROMIUM to one)")
class MarksRouteTest(BrowserCase, MarksServedCase):
    """Marks (ticket 112), in the browser: a click saves, a second changes, and a phone shows one item at a time."""

    def open(self, route=""):
        self.page.goto("http://%s:%d/?token=%s%s" % (self.host, self.port, TOKEN, route))

    def item(self, key):
        return "document.querySelector('#marks-body li.mark-item[data-item=\"%s\"]')" % key

    def button(self, key, name):
        return "[...%s.querySelectorAll('button.mark')].find((button) => button.textContent === '%s')" % (self.item(key), name)

    def test_a_click_saves_the_mark_and_a_second_click_changes_it(self):
        plots = self.plots["id"]
        self.open(self.route("marks"))
        self.page.wait_for(self.item("%s.1" % plots) + " && " + self.item("%s.1" % plots) + ".querySelector('.mark-plot img')")
        self.page.click(self.button("%s.1" % plots, "keep"))
        self.page.wait_for(self.button("%s.1" % plots, "keep") + ".getAttribute('aria-pressed') === 'true'")
        self.assertEqual(self.on_disk(plots)["items"][0]["mark"], "keep")
        self.page.click(self.button("%s.1" % plots, "drop"))
        self.page.wait_for(self.button("%s.1" % plots, "drop") + ".getAttribute('aria-pressed') === 'true'")
        self.assertEqual((self.on_disk(plots)["items"][0]["mark"], self.on_disk(plots)["items"][0]["via"]), ("drop", "dashboard"))

    def test_a_batch_link_opens_marks_at_it(self):
        self.open(self.route(self.review["id"]))
        self.page.wait_for("document.body.dataset.view === 'marks' && " + self.item("%s.1" % self.review["id"]))
        self.assertFalse(self.shown()["open"], "a batch opens in Marks, not the viewer")

    def test_a_phone_shows_one_item_at_a_time_with_previous_and_next(self):
        self.page.screen(390, 844, mobile=True)
        self.open(self.route("marks"))
        first = "%s.1" % self.plots["id"]
        self.page.wait_for(self.item(first) + " && " + self.item(first) + ".classList.contains('current')")
        shown = "[...document.querySelectorAll('#marks-body li.mark-item')].filter((item) => item.offsetParent !== null).map((item) => item.dataset.item)"
        self.assertEqual(self.page.evaluate(shown), [first])
        self.page.click("[...document.querySelectorAll('#marks-body .pager button')].find((button) => button.textContent === 'next')")
        self.page.wait_for("%s.length === 1 && %s[0] === '%s.2'" % (shown, shown, self.plots["id"]))
        self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth"), 390, json.dumps(self.shown()))
