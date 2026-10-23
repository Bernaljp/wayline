"""The dashboard's cards and new actions (Implementation Decision 17; ticket 121), over HTTP against a fixture ledger.

The seam is the server: its JSON (`paper`, the cards at `cards/<action>`, `decisions`' controls), its actions under
`actions/<name>`, and its downloads. The project holds a composed paper (`tests/compile_fixture.py`) compiled plainly
and for Nature from the recorded tool runs (seam 6), with the writer's three titles as alternatives. What is asserted is
what the owner sees and what the ledger holds after each click: a card launches nothing and journals nothing, Confirm
calls the function its verb calls, and every new action refuses without the token. Nothing sleeps.
"""

import hashlib
import http.client
import io
import json
import sys
import threading
import time
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from tests import compile_fixture as fixture
from tests import scout_net
from tests.paths import HARNESS_ROOT
from tests.projects import ProjectTestCase
from tests.test_dashboard import Response
from wayline import TAG, cli, compilations, paper, worker
from wayline import dossier as dossiers
from wayline import project as projects
from wayline.dashboard import ACTIONS, FILENAME_HEADER, LOOPBACK, TOKEN_HEADER, make_server
from wayline.ledger import Ledger

TOKEN = "a-token-with-enough-entropy-to-stand-in"
STATIC = HARNESS_ROOT / "dashboard"
TITLES = ("Noise bends a polynomial fit", "How noise bends a polynomial fit", "Fits under noise")
NEW_ACTIONS = ("compile", "plotting", "reference", "choose")


class CardsCase(ProjectTestCase):
    """A composed paper, compiled plainly and for Nature, with the writer's three titles, served with a token."""

    def setUp(self):
        super().setUp()
        self.project = (self.temp / "paper-project").resolve()
        projects.init_project(self.project, harness_root=self.fake_harness(), git=False)
        self.book = fixture.make_paper(self.project)
        self.tools = fixture.fake_tools(self.temp / "tools")
        self.run = compilations.recorded_runner(fixture.RECORDED)
        fetcher, _ = fixture.fetcher()
        compilations.after_order(self.project, {"order": 1, "venue": "nature"}, tools=self.tools, run=self.run, fetcher=fetcher,
                                 clock=lambda: fixture.NOW)
        record = paper.read_record(self.book)
        for number, title in enumerate(TITLES, start=1):
            self.book.write_markdown("paper/alternatives/title-%d.md" % number, title + "\n")
        record["alternatives"] = ["title-1", "title-2", "title-3"]
        self.book.write_json("paper/paper.json", record, schema="paper")
        projects.register(self.project, TAG)
        projects.set_active(self.project)
        self.server = make_server(LOOPBACK, 0, token=TOKEN, static_root=STATIC, memo_ttl=0.0, readings_ttl_s=3600)
        self.addCleanup(self.server.server_close)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.addCleanup(thread.join, 5)
        self.addCleanup(self.server.shutdown)
        thread.start()
        self.host, self.port = self.server.server_address[:2]

    def request(self, method, path, body=b"", headers=None):
        connection = http.client.HTTPConnection(self.host, self.port, timeout=30)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            return Response(connection.getresponse())
        finally:
            connection.close()

    def api(self, suffix, headers=None):
        return self.request("GET", "/api/projects/%s%s" % (self.project.name, suffix), headers=headers)

    def act(self, name, body=None, token=TOKEN, headers=None, raw=None):
        sent = dict(headers or {})
        if token is not None:
            sent[TOKEN_HEADER] = token
        data = raw if raw is not None else json.dumps({} if body is None else body).encode("utf-8")
        return self.request("POST", "/api/projects/%s/actions/%s" % (self.project.name, name), data, sent)

    def journal(self):
        return self.book.journal_path.read_bytes()

    def events(self, name):
        return [event for event in Ledger(self.project).read_events()[0] if event["event"] == name]

    def paper_file(self, relpath):
        return self.project / "research" / "paper" / relpath

    def recorded_compiling(self):
        """`compile_paper` as the server calls it, on the recorded tool runs rather than the machine's own tools."""
        real = compilations.compile_paper
        return mock.patch.object(compilations, "compile_paper",
                                 lambda project, venue=None, **options: real(project, venue, tools=self.tools, run=self.run))


class PaperPartsTest(CardsCase):
    def test_the_paper_view_lists_each_part_with_its_version_and_alternatives(self):
        view = self.api("/paper").json["paper"]
        self.assertEqual(view["version"], 1)
        self.assertEqual([part["part"] for part in view["parts"]], list(paper.PARTS))
        title = view["parts"][0]
        self.assertEqual((title["version"], title["path"], title["edited"]), (1, "research/paper/title.md", False))
        self.assertEqual([(item["name"], item["text"], item["current"]) for item in title["alternatives"]],
                         [("title-1", TITLES[0], True), ("title-2", TITLES[1], False), ("title-3", TITLES[2], False)])
        self.assertEqual(title["alternatives"][1]["path"], "research/paper/alternatives/title-2.md")
        self.assertEqual(view["parts"][1]["alternatives"], [], "the writer offers no other alternative unless asked")
        self.assertEqual(view["report"], "research/paper/PAPER.md")

    def test_earlier_versions_are_listed_each_opening_its_build_report(self):
        self.assertEqual(self.api("/paper").json["paper"]["earlier"], [])
        self.book.write_markdown("paper/earlier/v1/PAPER.md", "# The paper, version 1\n")
        self.book.write_markdown("paper/earlier/v1/title.md", "An older title\n")
        [earlier] = self.api("/paper").json["paper"]["earlier"]
        self.assertEqual((earlier["version"], earlier["report"], earlier["title"]),
                         (1, "research/paper/earlier/v1/PAPER.md", "An older title"))

    def test_before_any_order_the_paper_is_none_and_the_view_still_answers(self):
        self.paper_file("paper.json").unlink()
        view = self.api("/paper").json
        self.assertIsNone(view["paper"])
        self.assertEqual([item["name"] for item in view["compilations"]], ["plain", "nature"], "a compilation on disk is still listed")


class CompilationsTest(CardsCase):
    def compilation(self, name):
        return {item["name"]: item for item in self.api("/paper").json["compilations"]}[name]

    def test_each_compilation_offers_the_pdf_the_docx_the_latex_directory_and_the_markdown_copy(self):
        listed = self.api("/paper").json["compilations"]
        self.assertEqual([item["name"] for item in listed], ["plain", "nature"], "plain first, then the venues by name")
        nature = listed[1]
        self.assertEqual((nature["venue"], nature["display_name"], nature["paper_version"], nature["outcome"]),
                         ("nature", "Nature", 1, "compiled"))
        self.assertEqual(nature["downloads"], {
            "pdf": "research/paper/compilations/nature/paper.pdf", "docx": "research/paper/compilations/nature/paper.docx",
            "latex": "research/paper/compilations/nature/latex", "markdown": "research/paper/compilations/nature/paper.md"})
        self.assertEqual(nature["made_before"], [])

    def download(self, relpath, headers=None):
        return self.api("/download/%s" % relpath, headers=headers)

    def test_the_pdf_downloads_whole_and_by_range_with_its_bytes_intact(self):
        downloads = self.compilation("plain")["downloads"]
        held = (self.project / downloads["pdf"]).read_bytes()
        whole = self.download(downloads["pdf"])
        self.assertEqual((whole.status, whole.headers["content-type"], whole.headers["accept-ranges"]), (200, "application/pdf", "bytes"))
        self.assertEqual(hashlib.sha256(whole.body).hexdigest(), hashlib.sha256(held).hexdigest())
        part = self.download(downloads["pdf"], {"Range": "bytes=0-3"})
        self.assertEqual((part.status, part.body, part.headers["content-range"]), (206, b"%PDF", "bytes 0-3/%d" % len(held)))
        tail = self.download(downloads["pdf"], {"Range": "bytes=-16"})
        self.assertEqual(tail.body, held[-16:])

    def test_the_docx_and_the_markdown_copy_download_intact(self):
        downloads = self.compilation("nature")["downloads"]
        for kind in ("docx", "markdown"):
            with self.subTest(kind=kind):
                answer = self.download(downloads[kind])
                self.assertEqual(answer.status, 200)
                self.assertEqual(answer.body, (self.project / downloads[kind]).read_bytes())
        with zipfile.ZipFile(io.BytesIO(self.download(downloads["docx"]).body)) as archive:
            self.assertIsNone(archive.testzip())

    def test_the_latex_directory_downloads_as_a_zip_that_passes_testzip(self):
        answer = self.download(self.compilation("plain")["downloads"]["latex"])
        self.assertEqual((answer.status, answer.headers["content-type"]), (200, "application/zip"))
        with zipfile.ZipFile(io.BytesIO(answer.body)) as archive:
            self.assertIsNone(archive.testzip())
            self.assertIn("paper.tex", archive.namelist())
            self.assertEqual(archive.read("paper.tex"), self.paper_file("compilations/plain/latex/paper.tex").read_bytes())

    def test_a_compilation_made_from_an_earlier_version_says_so(self):
        record = paper.read_record(self.book)
        record["version"] = 2
        self.book.write_json("paper/paper.json", record, schema="paper")
        self.assertEqual(self.compilation("plain")["paper_version"], 1)
        self.assertTrue(self.compilation("plain")["older"], "made from version 1 while the paper is at version 2")


class ChooseTest(CardsCase):
    def compilations(self):
        return {item["name"]: item["made_before"] for item in self.api("/paper").json["compilations"]}

    def test_choosing_an_alternative_writes_the_part_and_launches_nothing(self):
        before = self.journal()
        with worker.use_fake() as fake:
            answer = self.act("choose", {"alternative": "title-2"})
            self.assertEqual(fake.calls, [], "choosing is free")
        self.assertEqual(answer.status, 200, answer.text)
        self.assertEqual((answer.json["part"], answer.json["alternative"], answer.json["changed"]), ("title", "title-2", True))
        self.assertEqual(self.paper_file("title.md").read_text(encoding="utf-8"), TITLES[1] + "\n")
        self.assertEqual(self.journal(), before)
        title = self.api("/paper").json["paper"]["parts"][0]
        self.assertTrue(title["edited"])
        self.assertEqual([item["current"] for item in title["alternatives"]], [False, True, False])

    def test_it_marks_each_compilation_made_before_the_part_changed_until_the_venue_is_compiled_again(self):
        self.assertEqual(self.compilations(), {"plain": [], "nature": []})
        self.act("choose", {"alternative": "title-3"})
        self.assertEqual(self.compilations(), {"plain": ["title"], "nature": ["title"]})
        with self.recorded_compiling():
            answer = self.act("compile", {"venue": "nature"})
        self.assertEqual(answer.status, 200, answer.text)
        self.assertEqual(self.compilations(), {"plain": ["title"], "nature": []}, "nature was compiled from the chosen title")

    def test_an_alternative_that_replaces_text_no_alternative_holds_keeps_that_text_as_one(self):
        self.paper_file("title.md").write_text("The owner's own title\n", encoding="utf-8")
        self.act("choose", {"alternative": "title-2"})
        [kept] = [item for item in self.api("/paper").json["paper"]["parts"][0]["alternatives"] if item["name"] == "title-4"]
        self.assertEqual((kept["text"], kept["current"]), ("The owner's own title", False))
        self.act("choose", {"alternative": "title-4"})
        self.assertEqual(self.paper_file("title.md").read_text(encoding="utf-8"), "The owner's own title\n")

    def test_an_unknown_alternative_or_one_while_an_order_is_open_is_refused(self):
        for body, words in (({"alternative": "title-9"}, "no alternative title-9"), ({"alternative": "front-1"}, "no alternative"),
                            ({"alternative": "../paper"}, "<part>-<n>"), ({}, "needs alternative")):
            with self.subTest(body=body):
                answer = self.act("choose", body)
                self.assertEqual(answer.status, 400)
                self.assertIn(words, answer.json["error"])
        with mock.patch.object(paper, "_start_conductor", lambda project: "started"):
            paper.order(self.project)
        refused = self.act("choose", {"alternative": "title-2"})
        self.assertEqual(refused.status, 400)
        self.assertIn("paper order 2 is open", refused.json["error"])
        self.assertEqual(self.paper_file("title.md").read_text(encoding="utf-8"), TITLES[0] + "\n")

    def test_the_verb_chooses_as_the_dashboard_does(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(["paper", "choose", "title-2", "--project", str(self.project)])
        self.assertEqual(code, 0, err.getvalue())
        self.assertIn("title-2", out.getvalue())
        self.assertIn("made before", out.getvalue())
        self.assertEqual(self.paper_file("title.md").read_text(encoding="utf-8"), TITLES[1] + "\n")


class CardEndpointTest(CardsCase):
    """Each button opens the card the chat shows, built by code: what will happen and its cost, with no model and no write."""

    def card(self, suffix):
        before = self.journal()
        with worker.use_fake() as fake:
            answer = self.api("/cards/%s" % suffix)
            self.assertEqual(fake.calls, [], "a card launches no model")
        self.assertEqual(self.journal(), before, "a card writes nothing")
        return answer

    def test_the_paper_orders_card_carries_its_readiness_list_and_cost_and_takes_a_venue(self):
        plain = self.card("paper")
        self.assertEqual(plain.status, 200, plain.text)
        self.assertEqual((plain.json["action"], plain.json["args"]), ("paper", {}))
        self.assertEqual(plain.json["readiness"][0]["title"], "Open objectives")
        self.assertIn("$35 to $40", plain.json["cost"])
        self.assertIn("composes the paper", plain.json["what"])
        self.assertEqual(plain.json["confirm"], "wayline paper --yes")
        nature = self.card("paper?venue=nature").json
        self.assertEqual((nature["args"], nature["confirm"]), ({"venue": "nature"}, "wayline paper --yes --for nature"))
        self.assertIn("Nature", nature["what"])
        unknown = self.card("paper?venue=no-such-venue")
        self.assertEqual(unknown.status, 400)
        self.assertIn("no venue no-such-venue", unknown.text)

    def test_the_compile_card_names_the_venue_its_limits_and_the_fitting_sessions_cost(self):
        answer = self.card("compile?venue=nature")
        self.assertEqual(answer.status, 200, answer.text)
        card = answer.json
        self.assertEqual((card["action"], card["args"], card["confirm"]), ("compile", {"venue": "nature"}, "wayline paper compile nature --yes"))
        self.assertIn("Compile the paper for Nature", card["what"])
        self.assertIn("about $3", card["cost"])
        self.assertEqual(self.card("compile").status, 400, "a compilation names its venue")

    def test_the_consolidation_card_says_what_the_session_reads_and_its_tokens(self):
        from wayline import sections
        lonely = self.card("consolidate?section=discussion")
        self.assertEqual(lonely.status, 400, "what Confirm would refuse, the card refuses")
        self.assertIn("nothing to consolidate", lonely.text)
        for heading, text in (("Limits", "The noise model is Gaussian."), ("Next", "A heavier tail would bend the fit further.")):
            sections.add_passage(self.book, "discussion", heading, text, by="owner")
        card = self.card("consolidate?section=discussion").json
        self.assertEqual((card["action"], card["args"], card["confirm"], card["passages"]),
                         ("consolidate", {"section": "discussion"}, "wayline consolidate discussion --yes", 2))
        self.assertIn("Discussion", card["what"])
        self.assertIn("tokens", card["cost"])
        refused = self.card("consolidate?section=results")
        self.assertEqual(refused.status, 400)
        self.assertIn("Results is its findings", refused.text)

    def test_the_public_card_says_it_cannot_be_undone(self):
        harness = projects.read_harness(self.project)
        harness["code_repository"] = {"shape": "reproducibility", "visibility": "private", "license": "MIT", "remote": {
            "repository": "owner/noise-fits", "url": "https://github.com/owner/noise-fits", "how": "new", "branch": "main"}}
        (self.project / "harness.json").write_text(json.dumps(harness, indent=2) + "\n", encoding="utf-8")
        card = self.card("public").json
        self.assertEqual((card["action"], card["args"], card["confirm"]), ("public", {}, "make owner/noise-fits public"))
        self.assertIn("owner/noise-fits", card["what"])
        self.assertIn("cannot be undone", card["cost"])

    def test_a_public_card_with_no_repository_and_an_unknown_card_are_refused(self):
        self.assertEqual(self.card("public").status, 400)
        self.assertEqual(self.card("launch").status, 404)


class ConfirmTest(CardsCase):
    """Confirm on a button's card calls the same action the chat's card calls; Not now sends nothing."""

    def setUp(self):
        super().setUp()
        self.started = []
        patcher = mock.patch.object(paper, "_start_conductor", lambda project: self.started.append(project) or "started")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_paper_order_takes_the_venue_its_card_named(self):
        answer = self.act("paper", {"venue": "nature"})
        self.assertEqual(answer.status, 200, answer.text)
        self.assertEqual((answer.json["order"], answer.json["venue"]), (2, "nature"))
        self.assertEqual(self.events("paper_order")[-1]["payload"]["venue"], "nature")
        self.assertEqual(self.act("paper", {"venue": "nowhere"}).status, 400)

    def test_a_compilation_for_another_venue_is_made_by_the_action_and_refused_while_an_order_is_open(self):
        before = json.loads(self.paper_file("compilations/nature/compilation.json").read_text(encoding="utf-8"))["compiled"]
        with self.recorded_compiling():
            answer = self.act("compile", {"venue": "nature"})
        self.assertEqual(answer.status, 200, answer.text)
        after = json.loads(self.paper_file("compilations/nature/compilation.json").read_text(encoding="utf-8"))
        self.assertNotEqual(after["compiled"], before)
        self.assertEqual(self.act("compile", {"venue": "nowhere"}).status, 400)
        self.act("paper")
        refused = self.act("compile", {"venue": "nature"})
        self.assertEqual(refused.status, 400)
        self.assertIn("paper order 2 is open", refused.json["error"])


class LateTest(CardsCase):
    """A button's action that answered 202 and failed after: the views say so, since no card holds it (the review's
    finding); a choice waits while a compilation is being made."""

    def test_a_compilation_that_fails_after_its_reply_is_shown_in_paper_and_a_choice_waits_for_it(self):
        from wayline import dashboard
        release = threading.Event()

        def slow(project, venue=None, **options):
            release.wait(10)
            raise compilations.CompilationError("pandoc vanished")

        with mock.patch.object(dashboard, "SWITCH_REPLY_S", 0.0), mock.patch.object(compilations, "compile_paper", slow):
            answer = self.act("compile", {"venue": "nature"})
            self.assertEqual((answer.status, answer.json["started"]), (202, "compile"))
            refused = self.act("choose", {"alternative": "title-2"})
            self.assertEqual(refused.status, 409)
            self.assertIn("a compilation is being made", refused.json["error"])
            release.set()
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and "compile" not in self.api("/paper").json["late"]:
                time.sleep(0.1)
        late = self.api("/paper").json["late"]
        self.assertEqual(late["compile"]["error"], "pandoc vanished")
        self.assertEqual(self.api("/decisions").json["late"], late, "Run reads the same, for the plotting select")
        self.assertEqual(self.act("choose", {"alternative": "title-2"}).status, 200, "the compilation has ended")
        with self.recorded_compiling():
            self.act("compile", {"venue": "nature"})
        self.assertNotIn("compile", self.api("/paper").json["late"], "asked again, the old failure goes")


class TokenTest(CardsCase):
    def test_the_whitelist_grows_by_exactly_these_actions_each_refused_without_the_token(self):
        self.assertEqual(ACTIONS[-len(NEW_ACTIONS):], NEW_ACTIONS)
        self.assertEqual(len(ACTIONS), 21 + len(NEW_ACTIONS))
        before, harness = self.journal(), (self.project / "harness.json").read_bytes()
        bodies = {"compile": {"venue": "nature"}, "plotting": {"library": "altair"}, "reference": {"slug": "lost-work", "answer": "leave it"},
                  "choose": {"alternative": "title-2"}}
        for name in NEW_ACTIONS:
            for token in (None, "wrong"):
                with self.subTest(action=name, token=token):
                    answer = self.act(name, bodies[name], token=token)
                    self.assertEqual(answer.status, 403)
                    self.assertIn(TOKEN_HEADER, answer.json["error"])
        self.assertEqual((self.journal(), (self.project / "harness.json").read_bytes()), (before, harness))
        self.assertEqual(self.paper_file("title.md").read_text(encoding="utf-8"), TITLES[0] + "\n")
        self.assertNotIn("handed_over", dossiers.read_dossier(self.book, "lost-work"))


class PlottingTest(CardsCase):
    """Run's select sets `harness.json.plotting` through `switch --plotting`'s function, told the dashboard asked."""

    def test_the_controls_carry_the_library_and_the_select_sets_it(self):
        controls = self.api("/decisions").json["controls"]
        self.assertEqual(controls["plotting"], "matplotlib")
        self.assertEqual([item["library"] for item in controls["plotting_levels"]], ["matplotlib", "altair", "ggplot2"])
        self.assertEqual(controls["plotting_levels"][1]["label"], "Python with Altair")
        fixture.tools_record(self.wayline_home / "tools", {"altair": (sys.executable, "5.4.1")})  # nothing left to install
        answer = self.act("plotting", {"library": "altair"})
        self.assertEqual(answer.status, 200, answer.text)
        self.assertEqual((answer.json["from"], answer.json["to"], answer.json["changed"]), ("matplotlib", "altair", True))
        self.assertEqual(projects.read_harness(self.project)["plotting"], "altair")
        [control] = [event["payload"] for event in self.events("control") if event["payload"]["command"] == "plotting"]
        self.assertEqual((control["args"]["plotting"], control["by"]), ("altair", "dashboard"))
        self.assertEqual(self.api("/decisions").json["controls"]["plotting"], "altair")

    def test_a_library_it_does_not_know_is_refused_and_nothing_changes(self):
        answer = self.act("plotting", {"library": "plotly"})
        self.assertEqual(answer.status, 400)
        self.assertIn("one of matplotlib, altair, ggplot2", answer.json["error"])
        self.assertNotIn("plotting", projects.read_harness(self.project))


class ReferenceTest(CardsCase):
    """The hand-over form: a DOI or title back to the scout, a PDF as the source, "drop it", or the claim kept marked."""

    HANDED = "10.5555/handed"

    def setUp(self):
        super().setUp()
        from wayline import sections
        sections.add_passage(self.book, "introduction", "State of the art", "A lost work claimed it first {ref:lost-work#abstract}.",
                             by="owner")

    def row(self):
        return {row["slug"]: row for row in self.api("/paper").json["references"]["unresolved"]}["lost-work"]

    def test_a_doi_goes_back_to_the_scout_and_the_reference_resolves(self):
        fetcher, net = scout_net.net_fetcher(scout_net.doi_answers(scout_net.crossref_work(doi=self.HANDED, title="Lost, then found")))
        with mock.patch.object(dossiers, "scout_fetcher", lambda project, email=None, fixtures=None: fetcher):
            answer = self.act("reference", {"slug": "lost-work", "answer": self.HANDED})
        self.assertEqual(answer.status, 200, answer.text)
        self.assertEqual((answer.json["slug"], answer.json["answer"]), ("lost-work", "doi"))
        self.assertTrue(net.asked)
        record = dossiers.read_dossier(self.book, "lost-work")
        self.assertEqual((record["existence"], record["handed_over"][-1]["value"]), ("verified", self.HANDED))
        self.assertNotIn("lost-work", [row["slug"] for row in self.api("/paper").json["references"]["unresolved"]])

    def test_keep_the_claim_marked_is_leave_it_and_settles_the_row(self):
        answer = self.act("reference", {"slug": "lost-work", "answer": "leave it"})
        self.assertEqual(answer.status, 200, answer.text)
        self.assertEqual(answer.json["answer"], "leave")
        self.assertEqual(self.row()["state"], "claim kept, to be resolved")

    def test_a_dropped_pdf_becomes_the_references_source(self):
        with mock.patch.object(dossiers, "pdf_details", lambda path: {"title": None}), \
                mock.patch.object(dossiers, "scout_fetcher", lambda project, email=None, fixtures=None: scout_net.net_fetcher({})[0]):
            answer = self.act("reference", raw=b"%PDF-1.4\n% the owner's copy\n", headers={
                "Content-Type": "application/pdf", FILENAME_HEADER: "lost%20copy.pdf", "X-Wayline-Reference": "lost-work"})
        self.assertEqual(answer.status, 200, answer.text)
        self.assertEqual(answer.json["answer"], "pdf")
        source = self.project / "research" / "refs" / "lost-work" / "source" / "lost copy.pdf"
        self.assertEqual(source.read_bytes(), b"%PDF-1.4\n% the owner's copy\n")
        record = dossiers.read_dossier(self.book, "lost-work")
        self.assertEqual((record["existence"], record["resolved_by"]), ("verified", "owner"))

    def test_a_drop_that_is_no_pdf_an_unknown_slug_or_a_url_is_refused(self):
        for raw, headers, words in (
                (b"plain words", {"Content-Type": "application/pdf", FILENAME_HEADER: "notes.txt", "X-Wayline-Reference": "lost-work"}, ".pdf"),
                (b"%PDF-1.4\n", {"Content-Type": "application/pdf", FILENAME_HEADER: "a.pdf"}, "X-Wayline-Reference")):
            with self.subTest(headers=headers):
                answer = self.act("reference", raw=raw, headers=headers)
                self.assertEqual(answer.status, 400)
                self.assertIn(words, answer.json["error"])
        self.assertEqual(self.act("reference", {"slug": "nobody", "answer": "leave it"}).status, 400)
        url = self.act("reference", {"slug": "lost-work", "answer": "https://example.org/lost"})
        self.assertEqual(url.status, 400)
        self.assertIn("URL", url.json["error"])
        elsewhere = self.temp / "private.pdf"
        elsewhere.write_bytes(b"%PDF-1.4\n% not the project's\n")
        typed = self.act("reference", {"slug": "lost-work", "answer": str(elsewhere)})
        self.assertEqual(typed.status, 400, "a typed answer never names a file on the workstation")
        self.assertIn("never named by its path", typed.json["error"])
        self.assertFalse((self.project / "research" / "refs" / "lost-work" / "source").exists())

    def test_with_the_orders_batch_open_the_row_carries_its_item_and_drop_it_is_the_batch_mark(self):
        self.assertIsNone(self.row()["batch"])
        with mock.patch.object(paper, "_start_conductor", lambda project: "started"):
            batch = self.act("paper").json["batch"]
        held = self.row()["batch"]
        self.assertEqual((held["batch"], held["mark"], held["default"]), (batch, None, "to be resolved"))
        self.assertEqual(held["marks"], ["hand over", "drop", "to be resolved"])
        answer = self.act("mark", {"batch": batch, "item": held["item"], "mark": "drop"})
        self.assertEqual(answer.status, 200, answer.text)
        from wayline import batches
        [item] = [item for item in batches.read_batch(self.project, batch)["items"] if item["id"] == held["item"]]
        self.assertEqual((item["mark"], item["by"]), ("drop", "owner"))


class ChatCardFieldsTest(unittest.TestCase):
    """The chat's cards take what the buttons take: the paper order's optional venue and a compilation's venue."""

    def card(self, action, args):
        from wayline import chat
        return chat.card_problems({"action": action, "args": args, "what": "it", "cost": "that"})

    def test_the_paper_card_takes_an_optional_venue_and_the_compile_card_needs_one(self):
        from wayline import chat
        self.assertIn("compile", chat.CARD_ACTIONS)
        self.assertEqual(self.card("paper", {}), [])
        self.assertEqual(self.card("paper", {"venue": "nature"}), [])
        self.assertEqual(self.card("compile", {"venue": "nature"}), [])
        self.assertIn("compile needs venue", self.card("compile", {}))
        self.assertTrue(self.card("paper", {"venue": "../etc"}))
        self.assertTrue(self.card("compile", {"venue": 3}))

    def test_the_schema_and_the_sessions_card_list_name_compile_and_the_venue(self):
        from wayline import chat
        schema = json.loads((HARNESS_ROOT / "schemas" / "chat_reply.json").read_text(encoding="utf-8"))
        self.assertIn("compile", schema["properties"]["card"]["properties"]["action"]["enum"])
        self.assertIn('`compile` {"venue"', chat.SYSTEM_PROMPT)
        self.assertIn('`paper` {} or {"venue"', chat.SYSTEM_PROMPT)
        for action in chat.CARD_ACTIONS:
            self.assertIn(action, ACTIONS)


class OrderEndNoticeTest(unittest.TestCase):
    def test_an_orders_end_notifies_outside_autonomous(self):
        from wayline import notify
        for autonomy, held in (("interactive", False), ("checkpoints", False), ("autonomous", True)):
            with self.subTest(autonomy=autonomy):
                self.assertEqual(notify.holds(notify.PAPER_ENDED, autonomy, setup_ended=True), held)
