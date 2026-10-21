"""The dashboard's routed views (Implementation Decision 17; ticket 110), over HTTP against a fixture ledger.

The seam is the server's JSON: each route a view reads (`research`, `run`, `waiting`), the projects page's rows in
`/api/projects`, and `items/<id>`, which resolves an item link `#/<project>/<id>` to what the popup viewer opens. Every
test starts a real `DashboardServer` on a free loopback port over a project built through the ledger as a run builds
it (findings filed, a drawing accepted, the reports rendered), and reads what the page would read.
"""

import http.client
import json
import threading

from tests.projects import open_goal, open_objective
from tests.test_reports import ReportsCase
from tests.test_results import file
from tests.test_drawings import R1
from wayline import TAG, provenance, reports
from wayline.dashboard import LOOPBACK, make_server
from wayline.project import register, set_active


class Answer:
    def __init__(self, raw):
        self.status = raw.status
        self.headers = {name.lower(): value for name, value in raw.getheaders()}
        self.body = raw.read()

    @property
    def json(self):
        return json.loads(self.body.decode("utf-8"))

    @property
    def etag(self):
        return self.headers.get("etag")


class Serving:
    """A dashboard serving `self.project`, registered and active, on a free loopback port."""

    def serve(self):
        register(self.project, TAG)
        set_active(self.project)
        server = make_server(LOOPBACK, 0, static_root=None, memo_ttl=0.0, readings_ttl_s=3600)
        self.addCleanup(server.server_close)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(server.shutdown)
        self.host, self.port = server.server_address[:2]
        self.project_id = self.project.name

    def get(self, path, headers=None):
        connection = http.client.HTTPConnection(self.host, self.port, timeout=10)
        try:
            connection.request("GET", path, headers=headers or {})
            return Answer(connection.getresponse())
        finally:
            connection.close()

    def api(self, suffix, headers=None):
        return self.get("/api/projects/%s%s" % (self.project_id, suffix), headers=headers)


class DrawnProjectCase(Serving, ReportsCase):
    """A project with one goal, one result drawn once, and the reports rendered, served."""

    def setUp(self):
        super().setUp()
        self.goal = open_goal(self.project)
        self.accept_drawing()
        provenance.render_report(self.project, offline=True)
        self.serve()


class ResearchRouteTest(DrawnProjectCase):
    def test_it_lists_the_general_report_and_each_result_with_its_reports_and_plots_by_id(self):
        view = self.api("/research").json
        self.assertEqual(view["report"]["path"], "research/REPORT.md")
        self.assertTrue(view["report"]["exists"])
        [result] = view["results"]
        self.assertEqual(result["id"], "R1")
        self.assertEqual(result["heading"], R1)
        self.assertEqual(result["current"]["name"], "R1-1")
        self.assertEqual(result["current"]["path"], "research/reports/R1-1.md")
        self.assertEqual(result["earlier"], [])
        self.assertEqual([plot["id"] for plot in result["plots"]], ["R1.1", "R1.T1"])
        self.assertEqual(result["plots"][0]["path"], "drawings/R1-1/auroc_box.png")
        self.assertEqual(result["headline"], "The rise holds.")

    def test_each_objective_shows_its_status_measure_kept_values_and_its_results_and_the_rest_stand_beyond(self):
        view = self.api("/research").json
        [goal] = view["objectives"]
        self.assertEqual((goal["id"], goal["status"]), ("O1", "open"))
        self.assertIn("`auroc` up", goal["measure"])
        self.assertEqual((goal["kept"], goal["best"]), ([], None))
        self.assertEqual(goal["results"], [])
        self.assertEqual(view["beyond"], ["R1"], "a result no objective asked for stands beyond the objectives")
        file(self.ledger, "t3-a1-f1", "The rise holds on split 3.", R1, objectives=("O1",), ticket=3)
        self.ledger.append_event("progress", {"metric": "auroc", "value": 0.71, "ticket": 3, "run_id": "t3-a1", "kept": True,
                                              "goal": "O1"}, ticket=3)
        view = self.api("/research").json
        [goal] = view["objectives"]
        self.assertEqual((goal["kept"], goal["best"]), ([0.71], 0.71))
        self.assertEqual(goal["results"], ["R1"])
        self.assertEqual(view["beyond"], [])

    def test_an_objective_reframed_names_its_successor_and_the_successor_names_where_it_came_from(self):
        from wayline.objectives import reframe_objective
        reframe_objective(self.project, "O1", "Do the products raise the AUROC on held-out species?", by="owner")
        objectives = {objective["id"]: objective for objective in self.api("/research").json["objectives"]}
        self.assertEqual(objectives["O1"]["status"], "reframed")
        self.assertEqual(objectives["O1"]["lineage"]["reframed_as"], "O2")
        self.assertEqual(objectives["O2"]["lineage"]["reframed_from"], ["O1"])

    def test_a_closed_objective_lists_its_set_aside_claims_and_the_tickets_parked_for_it(self):
        from tests.test_specify import draft
        from wayline import objective_changes, specify, tickets
        first = self.ticket(self.identifier)
        _, body = tickets.read_ticket(tickets.tickets_dir(self.project) / tickets.filename(first))
        tickets.write_ticket(self.ledger, dict(first, id=9, title="Sweep the products", kind="experiment", status="open",
                                               objectives=["O1"], touches=["t9.txt"], origin=None), body)
        spec = draft()
        spec["claims"][0]["objectives"] = ["O1"]
        specify._write(self.ledger, spec)
        objective_changes.apply_change(self.project, {"kind": "park", "objective": "O1", "reason": "nothing more to learn"}, "owner")
        view = self.api("/research").json
        self.assertEqual([(claim["id"], claim["objectives"]) for claim in view["set_aside"]], [("C1", ["O1"])])
        self.assertEqual(view["set_aside"][0]["text"], spec["claims"][0]["text"])
        self.assertEqual([(ticket["id"], ticket["title"], ticket["reason"]) for ticket in view["parked"]],
                         [(9, "Sweep the products", "it serves only O1, which was parked")])

    def test_a_renewed_current_report_carries_its_new_hash_for_the_dot_and_no_notice_is_sent(self):
        before = self.api("/research")
        sha = before.json["results"][0]["current"]["sha256"]
        self.assertTrue(sha)
        file(self.ledger, "t3-a1-f1", "The rise holds at 0.71 on split 3.", R1, ticket=3)
        provenance.render_report(self.project, offline=True)
        after = self.api("/research", {"If-None-Match": before.etag})
        self.assertEqual(after.status, 200, "a renewed report moves the view's tag")
        current = after.json["results"][0]["current"]
        self.assertEqual(current["name"], "R1-1")
        self.assertNotEqual(current["sha256"], sha, "the page compares this to the hash it saw when the owner last opened it")
        self.assertNotEqual(after.json["report"]["sha256"], before.json["report"]["sha256"])
        self.assertEqual([event for event in self.ledger.read_events()[0] if event["event"] == "notified"], [],
                         "a renewed report notifies nowhere")

    def test_an_unchanged_ledger_answers_304(self):
        first = self.api("/research")
        self.assertEqual(self.api("/research", {"If-None-Match": first.etag}).status, 304)

    def test_it_names_the_plotting_library_in_use(self):
        self.assertEqual(self.api("/research").json["plotting"]["library"], "matplotlib")


    def test_a_second_drawing_makes_the_first_report_an_earlier_one_and_its_left_out_plots_show_in_their_row(self):
        file(self.ledger, "t3-a1-f1", "The rise holds at 0.71 on split 3.", R1, ticket=3)
        self.next_drawing()
        self.accept_drawing(redraws=["R1.1"], left_out=[{"what": "a violin of the seeds", "reason": "three seeds are too few"}])
        provenance.render_report(self.project, offline=True)
        [result] = self.api("/research").json["results"]
        self.assertEqual(result["current"]["name"], "R1-2")
        self.assertEqual([report["path"] for report in result["earlier"]], ["research/reports/R1-1.md"])
        self.assertEqual(result["left_out"], [{"what": "a violin of the seeds", "reason": "three seeds are too few"}])


class RunRouteTest(DrawnProjectCase):
    """What Run adds to today's page: the account, for the viewer, and Software."""

    def write_tools(self, tools):
        from wayline.tools import tools_home
        root = tools_home()
        root.mkdir(parents=True, exist_ok=True)
        (root / "tools.json").write_text(json.dumps({"tools": tools}), encoding="utf-8")

    def test_it_names_the_account_with_its_counts(self):
        account = self.api("/run").json["account"]
        self.assertEqual(account["path"], "research/ACCOUNT.md")
        self.assertTrue(account["exists"])
        self.assertEqual((account["decided"], account["waiting"]), (0, 0))

    def test_software_lists_tools_json_and_the_matlab_checks_outcome(self):
        self.write_tools({
            "pandoc": {"executable": "/opt/tools/bin/pandoc", "version": "3.6", "route": "conda-forge", "installer": "harness"},
            "matlab": {"executable": "/opt/matlab/bin/matlab", "version": "24.2", "release": "R2024b", "route": "owner",
                       "installer": "owner", "toolboxes": {"Statistics and Machine Learning Toolbox": "24.2"}},
        })
        self.ledger.append_event("tool_installed", {"ticket": 5, "name": "matlab", "outcome": "failed", "version": None, "attempt": 1,
                                                    "reason": "the check `matlab -batch \"ver\"` failed (exit 1)"}, ticket=5)
        software = self.api("/run").json["software"]
        self.assertEqual([(tool["name"], tool["version"], tool["installer"]) for tool in software["tools"]],
                         [("matlab", "24.2", "owner"), ("pandoc", "3.6", "harness")])
        matlab = software["matlab"]
        self.assertEqual((matlab["version"], matlab["release"], matlab["toolboxes"]),
                         ("24.2", "R2024b", ["Statistics and Machine Learning Toolbox"]))
        self.assertEqual((matlab["check"]["outcome"], matlab["check"]["reason"]), ("failed", "the check `matlab -batch \"ver\"` failed (exit 1)"))
        self.ledger.append_event("tool_installed", {"ticket": 5, "name": "matlab", "outcome": "recorded", "version": "24.2", "attempt": 2,
                                                    "reason": None}, ticket=5)
        self.assertEqual(self.api("/run").json["software"]["matlab"]["check"]["outcome"], "recorded")

    def test_no_matlab_is_said_as_none(self):
        self.assertIsNone(self.api("/run").json["software"]["matlab"])

    def test_the_environment_and_a_move_in_progress(self):
        import os
        environment = self.api("/run").json["software"]["environment"]
        self.assertEqual((environment["setting"], environment["move"]), ("shared", None))
        marker = self.project / ".wayline" / "env-move.json"
        marker.parent.mkdir(exist_ok=True)
        marker.write_text(json.dumps({"from": "shared", "to": "conda", "started": "2026-10-21T10:00:00Z", "pid": os.getpid()}), encoding="utf-8")
        move = self.api("/run").json["software"]["environment"]["move"]
        self.assertEqual((move["from"], move["to"]), ("shared", "conda"))

    def test_a_changed_tools_json_moves_the_tag(self):
        first = self.api("/run")
        self.assertEqual(self.api("/run", {"If-None-Match": first.etag}).status, 304)
        self.write_tools({"pandoc": {"executable": "/opt/tools/bin/pandoc", "version": "3.6", "route": "conda-forge", "installer": "harness"}})
        self.assertEqual(self.api("/run", {"If-None-Match": first.etag}).status, 200)


class DecisionKindsTest(DrawnProjectCase):
    """Run's cards for the new decision kinds: each open decision ticket names its kind and the fields that kind has."""

    def open(self, origin, question="What now?"):
        from wayline.decisions import open_decision
        return open_decision(self.project, question, options=["a", "b"], proposed_by="conductor", origin=origin)["ticket"]

    def test_each_new_kind_is_named_with_its_own_fields(self):
        cases = {
            "objective changes #1": ("objective_changes", {"round": 1}),
            "software octave": ("software", {"tool": "octave", "gap": False, "licensed": False}),
            "software matlab": ("software", {"tool": "matlab", "gap": False, "licensed": True}),
            "empty frontier: O1 #2": ("empty_frontier", {"objective": "O1", "asked": 2}),
            "concern K3 #1": ("concern", {"concern": "K3", "asked": 1}),
            "material M2 #1": ("verification_gap", {"item": "M2", "asked": 1}),
        }
        opened = {self.open(origin, "Question about %s?" % origin): expected for origin, expected in cases.items()}
        entries = {entry["id"]: entry for entry in self.api("/decisions").json["open"]}
        for identifier, (kind, about) in opened.items():
            with self.subTest(kind=kind, about=about):
                self.assertEqual(entries[identifier]["kind"], kind)
                for key, value in about.items():
                    self.assertEqual(entries[identifier]["about"][key], value)

    def test_any_other_decision_is_a_plain_one(self):
        identifier = self.open("which split")
        [entry] = [entry for entry in self.api("/decisions").json["open"] if entry["id"] == identifier]
        self.assertEqual((entry["kind"], entry["about"]), ("decision", {}))


class WaitingStripTest(DrawnProjectCase):
    """"Waiting on you" on every view, mirroring the account's section, its count in the title and on each project tab."""

    def test_the_strip_mirrors_the_accounts_waiting_items_each_with_its_link(self):
        from wayline.decisions import open_decision
        self.assertEqual(self.api("/waiting").json["count"], 0)
        opened = open_decision(self.project, "Which split is held out?", options=["a", "b"], proposed_by="conductor")["ticket"]
        strip = self.api("/waiting").json
        self.assertEqual(strip["count"], 1)
        [item] = strip["items"]
        self.assertIn("Which split is held out?", item["text"])
        self.assertFalse(item["text"].startswith("- "), "a line of the strip, not of the Markdown list")
        self.assertEqual(item["item"], str(opened))
        self.assertEqual(strip["path"], "research/ACCOUNT.md")

    def test_its_count_is_on_each_project_tab(self):
        from wayline.decisions import open_decision
        open_decision(self.project, "Which split is held out?", options=["a", "b"], proposed_by="conductor")
        [entry] = self.get("/api/projects").json["projects"]
        self.assertEqual(entry["waiting"], self.api("/waiting").json["count"])
        self.assertEqual(entry["waiting"], 1)

    def test_an_unchanged_ledger_answers_304_and_a_new_item_moves_the_tag(self):
        from wayline.decisions import open_decision
        first = self.api("/waiting")
        self.assertEqual(self.api("/waiting", {"If-None-Match": first.etag}).status, 304)
        listed = self.get("/api/projects")
        open_decision(self.project, "Which split is held out?", options=["a", "b"], proposed_by="conductor")
        self.assertEqual(self.api("/waiting", {"If-None-Match": first.etag}).status, 200)
        self.assertEqual(self.get("/api/projects", {"If-None-Match": listed.etag}).status, 200,
                         "the tabs' counts move with the ledger of every project")


class ProjectsPageTest(DrawnProjectCase):
    def test_each_project_has_the_accounts_standing_line_its_run_state_and_its_waiting_count(self):
        [entry] = self.get("/api/projects").json["projects"]
        self.assertIn("No run has started yet.", entry["standing"])
        self.assertEqual(entry["run_state"], {"state": "not started", "since": None, "reason": None, "conductor": False})
        self.assertEqual(entry["waiting"], 0)
        self.ledger.append_event("run_started", {"autonomy": "checkpoints"})
        [entry] = self.get("/api/projects").json["projects"]
        self.assertEqual(entry["run_state"]["state"], "running")
        self.assertTrue(entry["run_state"]["since"])

    def test_an_old_project_is_listed_read_only_with_its_tag_and_no_reading_of_its_account(self):
        from tests.test_research_version import make_old
        make_old(self.project)
        [entry] = self.get("/api/projects").json["projects"]
        self.assertTrue(entry["read_only"])
        self.assertEqual(entry["research_version"], 1)
        self.assertEqual(entry["harness_tag"], TAG)
        self.assertEqual((entry["standing"], entry["waiting"], entry["run_state"]), (None, None, None))
        self.assertEqual(self.api("/outputs").status, 200, "its files still open in the viewer")


class ItemLinkTest(DrawnProjectCase):
    """`#/<project>/<id>` opens the item in the popup viewer over its view: the page asks `items/<id>` what to open."""

    def item(self, identifier):
        return self.api("/items/%s" % identifier)

    def test_an_objective_opens_the_objectives_file_at_its_heading_over_research(self):
        item = self.item("O1").json
        self.assertEqual((item["kind"], item["view"], item["path"], item["focus"]), ("objective", "research", "research/OBJECTIVES.md", "O1"))
        self.assertEqual(item["title"], self.goal["text"])

    def test_a_result_opens_its_current_report(self):
        item = self.item("R1").json
        self.assertEqual((item["kind"], item["view"], item["path"], item["title"]), ("result", "research", "research/reports/R1-1.md", R1))

    def test_a_report_and_the_general_report_open_as_their_files(self):
        self.assertEqual(self.item("R1-1").json["path"], "research/reports/R1-1.md")
        general = self.item("report").json
        self.assertEqual((general["kind"], general["view"], general["path"]), ("report", "research", "research/REPORT.md"))

    def test_a_plot_opens_its_image_with_its_explanation(self):
        item = self.item("R1.1").json
        self.assertEqual((item["kind"], item["view"], item["path"]), ("plot", "research", "drawings/R1-1/auroc_box.png"))
        self.assertEqual(item["caption"], {"purpose": "Does the AUROC hold across seeds?",
                                           "data": "The held-out AUROC of each seed, from results/summary.json.",
                                           "shows": "The AUROC sits at 0.71 across 3 seeds."})

    def test_a_table_opens_its_rows(self):
        item = self.item("R1.T1").json
        self.assertEqual((item["kind"], item["view"], item["path"]), ("table", "research", "drawings/R1-1/auroc_table.csv"))
        self.assertEqual(item["rows"], [["seed", "auroc"], ["1", "0.71"]])

    def test_a_ticket_and_a_decision_ticket_open_their_files_over_run(self):
        from wayline.decisions import open_decision
        ticket = self.item(str(self.identifier)).json
        self.assertEqual((ticket["kind"], ticket["view"]), ("ticket", "run"))
        self.assertTrue(ticket["path"].startswith("research/tickets/%02d-" % self.identifier))
        opened = open_decision(self.project, "Which split is held out?", options=["a", "b"], proposed_by="conductor")
        decision = self.item(str(opened["ticket"])).json
        self.assertEqual((decision["kind"], decision["view"]), ("decision", "run"))

    def test_the_account_opens_over_run(self):
        item = self.item("account").json
        self.assertEqual((item["kind"], item["view"], item["path"]), ("account", "run", "research/ACCOUNT.md"))

    def test_an_unknown_id_answers_404_with_a_line_to_show_not_an_error_page(self):
        for identifier in ("R99", "O7", "R1.9", "R1-4", "77", "nonsense", "..%2Fharness.json"):
            with self.subTest(identifier=identifier):
                missing = self.item(identifier)
                self.assertEqual(missing.status, 404)
                self.assertFalse(missing.json["found"])
                self.assertIn("not found", missing.json["line"])
