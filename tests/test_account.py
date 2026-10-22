"""The account (Implementation Decision 17; ticket 89): `research/ACCOUNT.md`, the reviews, the end notice, and status.

The seam is the ledger over a temporary copy of `fixtures/projects/ended-run/`, a toy run that ended: every test
renders the account from the journal and the ledger and asserts on the file written, the journal's events, and
what the owner is told. Journals are replayed by appending the events a run would have journaled.
"""

import io
import re
import shutil
import subprocess
from contextlib import redirect_stderr, redirect_stdout

from tests import machine
from tests.paths import FIXTURES_DIR
from tests.projects import ProjectTestCase
from tests.test_conductor import ConductorCase, done, drive, patch
from wayline import account, cli, worker
from wayline.conductor import Conductor
from wayline.ledger import Ledger

ENDED_RUN = FIXTURES_DIR / "projects" / "ended-run"
SECTIONS = ("Where the project stands", "Decided for you", "Waiting on you", "Changed without asking you", "Runs",
            "Not pursued", "Library")


class AccountCase(ProjectTestCase):
    """A writable copy of the ended run, made a git repository as `init` makes one."""

    def setUp(self):
        super().setUp()
        self.project = self.temp / "ended-run"
        shutil.copytree(ENDED_RUN, self.project)
        self.book = Ledger(self.project)
        for args in (("init", "-q", "-b", "main"), ("add", "-A"),
                     ("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "fixture")):
            subprocess.run(["git", "-C", str(self.project), *args], check=True, capture_output=True)

    def events(self, name=None):
        found, _ = self.book.read_events()
        return [event for event in found if name is None or event["event"] == name]

    def append(self, name, payload, ticket=None, ts=None):
        return self.book.append_event(name, payload, ticket=ticket, ts=ts)

    def render(self, **kwargs):
        return account.render_account(self.project, **kwargs)

    def text(self):
        return (self.project / "research" / "ACCOUNT.md").read_text(encoding="utf-8")

    def section(self, title):
        text = self.text()
        start = text.index("## %s\n" % title)
        following = re.search(r"^## ", text[start + 3:], re.M)
        return text[start:start + 3 + following.start()] if following else text[start:]

    def headings(self):
        return re.findall(r"^## (.+)$", self.text(), re.M)


class RenderTest(AccountCase):
    def test_the_account_opens_with_its_first_line_and_holds_the_sections_in_order(self):
        self.render()
        lines = self.text().splitlines()
        self.assertIn("code writes this file", lines[0].lower())
        self.assertIn("REPORT.md", lines[0])
        self.assertIn("conversation", lines[0])
        headings = self.headings()
        self.assertEqual(headings, [title for title in SECTIONS if title in headings])
        self.assertEqual(headings[:3], ["Where the project stands", "Decided for you", "Waiting on you"])

    def test_a_render_is_journaled_as_report_rendered_for_the_account_and_once_only(self):
        rendered = self.render()
        (event,) = self.events("report_rendered")
        self.assertEqual(event["payload"]["report"], "account")
        self.assertEqual(event["payload"]["sha256"], rendered.sha256)
        before = self.text()
        again = self.render()
        self.assertFalse(again.changed)
        self.assertEqual(len(self.events("report_rendered")), 1)
        self.assertEqual(self.text(), before)


class DecidedForYouTest(AccountCase):
    def test_each_unreviewed_decision_of_the_decider_is_one_line_with_when_what_answer_confidence_fable_and_link(self):
        self.render()
        (line,) = [line for line in self.section("Decided for you").splitlines() if line.startswith("- ")]
        self.assertIn("D2, 2026-09-11 20:05Z, ticket 8, *Which held-out split does the goal read?*: **split_b**", line)
        self.assertIn("confidence 0.8", line)
        self.assertIn("on Opus while Fable was spent", line)
        self.assertIn("(tickets/08-which-held-out-split-does-the-goal-read.md)", line)

    def test_the_owners_own_decisions_are_not_listed_and_a_conductor_default_is(self):
        self.append("decision", {"ticket": 11, "answer": "superseded", "decided_by": "conductor", "rationale": "the window reset",
                                 "confidence": None}, ticket=11)
        self.render()
        section = self.section("Decided for you")
        self.assertNotIn("20000 rows", section)  # the owner's answer to ticket 10
        self.assertIn("D3, ", section)
        self.assertIn("**superseded** (by the conductor, no confidence given)", section)

    def test_a_superseded_decision_leaves_the_list(self):
        self.append("ticket_rerun", {"ticket": 8, "by": "cli"}, ticket=8)
        self.append("decision", {"ticket": 8, "answer": "split_a", "decided_by": "human", "rationale": None, "confidence": None}, ticket=8)
        self.render()
        self.assertNotIn("Decided for you", self.headings())

    def test_a_grill_question_the_decider_settled_links_to_decisions_md(self):
        self.append("decision", {"ticket": None, "answer": "Q4 Which metric? Answer: auroc", "decided_by": "decider",
                                 "rationale": "the spec names it", "confidence": 0.9})
        self.render()
        self.assertIn("D3, ", self.section("Decided for you"))
        self.assertIn("**auroc**", self.section("Decided for you"))


class ReviewTest(AccountCase):
    def test_every_unreviewed_decision_is_an_item_of_an_open_review_batch(self):
        from wayline import batches
        self.render()
        (batch,) = batches.read_batches(self.project)
        self.assertEqual((batch["kind"], batch["status"]), ("account_review", "open"))
        self.assertEqual([(item["ref"], item["marks"], item["default"]) for item in batch["items"]], [("D2", ["stand", "reverse"], "stand")])
        self.render()
        self.assertEqual(len(batches.read_batches(self.project)), 1)

    def test_letting_a_decision_stand_journals_reviewed_takes_it_off_the_list_and_settles_its_item(self):
        from wayline import batches
        self.render()
        said = account.review(self.project, "D2", "stand")
        self.assertIn("D2 stands", said)
        (event,) = self.events("reviewed")
        self.assertEqual(event["payload"], {"decision": "D2", "review": "stand", "by": "owner"})
        self.assertEqual(batches.marks(self.project, "B1")[0]["mark"], "stand")
        self.render()
        self.assertNotIn("Decided for you", self.headings())
        with self.assertRaises(account.AccountError):
            account.review(self.project, "D2", "reverse")

    def test_a_mark_in_the_marks_view_is_taken_as_the_review_at_the_next_render(self):
        from wayline import batches
        self.render()
        batches.mark(self.project, "B1", 1, "stand")
        self.render()
        (event,) = self.events("reviewed")
        self.assertEqual(event["payload"]["review"], "stand")
        self.assertTrue(batches.read_batch(self.project, "B1")["items"][0]["acted"], "a review taken is final")

    def test_undo_it_reopens_the_decision_ticket_human_only_and_asks_in_one_line(self):
        from wayline import tickets
        self.render()
        said = account.review(self.project, "D2", "reverse")
        self.assertEqual(len(said.splitlines()), 1)
        self.assertIn("human only", said)
        self.assertIn("wayline answer 8", said)
        fields = {ticket["id"]: ticket for ticket in tickets.read_tickets(self.project)}[8]
        self.assertEqual((fields["status"], fields["human_only"]), ("open", True))
        self.assertEqual(self.events("ticket_rerun")[-1]["payload"]["ticket"], 8)
        self.assertTrue(self.events("decision_opened")[-1]["payload"]["human_only"])
        self.assertEqual(self.events("reviewed")[-1]["payload"], {"decision": "D2", "review": "reverse", "by": "owner"})
        self.assertNotIn("run_ended", [event["event"] for event in self.events()[-4:]])

    def test_a_reversal_with_an_answer_is_the_owners_answer_to_the_ticket(self):
        from wayline import tickets
        account.review(self.project, "D2", "reverse", answer="split_a")
        decision = self.events("decision")[-1]
        self.assertEqual((decision["payload"]["answer"], decision["payload"]["decided_by"]), ("split_a", "human"))
        fields = {ticket["id"]: ticket for ticket in tickets.read_tickets(self.project)}[8]
        self.assertTrue(fields["human_only"])
        self.render()
        self.assertNotIn("Decided for you", self.headings())

    def test_a_reviewed_decision_stays_counted_in_its_run(self):
        account.review(self.project, "D2", "stand")
        self.render()
        self.assertIn("Decision by the decider on ticket 8", self.section("Runs"))

    def test_a_decision_not_listed_is_refused(self):
        with self.assertRaises(account.AccountError):
            account.review(self.project, "D1", "stand")  # the owner's own answer to ticket 10
        with self.assertRaises(account.AccountError):
            account.review(self.project, "D9", "stand")

    def test_the_review_verb(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(["review", "D2", "stand", "--project", str(self.project)])
        self.assertEqual(code, 0, err.getvalue())
        self.assertIn("D2 stands", out.getvalue())
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            self.assertEqual(cli.main(["review", "D2", "stand", "--project", str(self.project)]), 2)

    def decided_twice(self):
        """D2 from the fixture, and one more grill question the decider answered: the ids, in order."""
        from wayline import grill
        grill.ask(self.project, "Which metric does the goal read?")
        grill.answer(self.project, "Q1", "auroc", "the spec names it", decided_by="decider", model="claude-opus-5")
        return ["D2", "D%d" % len(self.events("decision"))]

    def review_all(self, *shown):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(["review", "all", "stand", "--shown", ",".join(shown), "--project", str(self.project)])
        return code, out.getvalue(), err.getvalue()

    def test_the_owners_yes_to_the_autonomous_opening_lets_every_decision_shown_stand(self):
        """Ticket 109: "Decided for you" is one numbered item recommending "let them stand"; a yes reviews each one shown."""
        listed = self.decided_twice()
        code, out, err = self.review_all(*listed)
        self.assertEqual(code, 0, err)
        self.assertEqual([event["payload"]["decision"] for event in self.events("reviewed")], listed)
        self.assertEqual({event["payload"]["review"] for event in self.events("reviewed")}, {"stand"})
        self.assertEqual(len(out.splitlines()), 2, "one line read back per decision")

    def test_a_decision_made_after_the_opening_was_shown_is_left_listed(self):
        first, later = self.decided_twice()
        code, out, err = self.review_all(first)
        self.assertEqual(code, 0, err)
        self.assertEqual([event["payload"]["decision"] for event in self.events("reviewed")], [first])
        self.assertIn(later, out, "the owner is told what is still listed")
        self.assertIn(later, "\n".join(account.account_view(self.project, full=False)["sections"][account.TITLES[1]]))

    def test_a_shown_decision_that_cannot_be_reviewed_is_said_and_the_rest_stand(self):
        listed = self.decided_twice()
        account.review(self.project, listed[0], "stand")
        code, out, err = self.review_all(*listed)
        self.assertEqual(code, 1)
        self.assertIn(listed[0], err)
        self.assertIn("%s stands" % listed[1], out)
        self.assertEqual(len(self.events("reviewed")), 2)

    def test_all_takes_only_stand_and_the_decisions_shown(self):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as err:
            self.assertEqual(cli.main(["review", "all", "reverse", "--shown", "D2", "--project", str(self.project)]), 2)
        self.assertIn("one at a time", err.getvalue())
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as err:
            self.assertEqual(cli.main(["review", "all", "stand", "--project", str(self.project)]), 2)
        self.assertIn("--shown", err.getvalue())
        self.assertEqual(self.events("reviewed"), [])

    def test_undo_it_on_a_grill_question_asks_it_again_and_the_owners_answer_revises_it(self):
        from wayline import grill, project, tickets
        grill.ask(self.project, "Which metric does the goal read?")
        grill.answer(self.project, "Q1", "auroc", "the spec names it", decided_by="decider", model="claude-opus-5")
        decision = "D%d" % len(self.events("decision"))
        said = account.review(self.project, decision, "reverse")
        self.assertIn("human only", said)
        opened = [ticket for ticket in tickets.read_tickets(self.project) if ticket.get("origin") == "review %s: grill Q1" % decision]
        self.assertEqual([(ticket["human_only"], ticket["status"]) for ticket in opened], [(True, "open")])
        project.answer(self.project, opened[0]["id"], "auprc")
        self.render()
        revised = grill.read_records(self.project)[-1]
        self.assertEqual((revised["answer"], revised["decided_by"], revised["supersedes"]), ("auprc", "human", "Q1"))
        self.render()
        self.assertEqual(len(grill.read_records(self.project)), 2, "the answer is taken once")

    def test_the_venue_is_the_owners_to_name_with_the_paper_verb(self):
        self.append("decision", {"ticket": None, "answer": "paper venue: nature", "decided_by": "decider",
                                 "rationale": "the claims fit", "confidence": 0.6})
        with self.assertRaises(account.AccountError):
            account.review(self.project, "D3", "reverse", answer="neurips")
        self.assertIn("yours to name when the paper is compiled for a venue", account.review(self.project, "D3", "reverse"))

    def test_a_mark_that_cannot_be_taken_is_said_in_the_banner(self):
        from wayline import batches
        self.append("decision", {"ticket": None, "answer": "proposal p-0002: keep parked", "decided_by": "decider",
                                 "rationale": "outside the claim", "confidence": 0.6})
        self.render()
        (batch,) = batches.read_batches(self.project)
        item = [entry for entry in batch["items"] if entry["ref"] == "D3"][0]
        batches.mark(self.project, batch["id"], item["id"], "reverse", note="please run it")
        self.render()
        self.assertIn("your reverse mark on D3", self.text().split("## ")[0])
        self.assertIn("D3", account.account_view(self.project)["unreviewed"])

    def test_a_grill_reversal_with_an_answer_revises_the_question_by_the_owner(self):
        from wayline import grill
        grill.ask(self.project, "Which metric does the goal read?")
        grill.answer(self.project, "Q1", "auroc", "the spec names it", decided_by="decider", model="claude-opus-5")
        decision = "D%d" % len(self.events("decision"))
        account.review(self.project, decision, "reverse", answer="auprc")
        revised = grill.read_records(self.project)[-1]
        self.assertEqual((revised["answer"], revised["decided_by"], revised["supersedes"]), ("auprc", "human", "Q1"))

    def test_a_parked_proposal_kept_parked_is_admitted_by_a_reversal(self):
        from wayline import proposals
        self.append("decision", {"ticket": None, "answer": "proposal p-0002: keep parked", "decided_by": "decider",
                                 "rationale": "outside the claim", "confidence": 0.6})
        account.review(self.project, "D3", "reverse", answer="admit")
        events = self.events()
        self.assertEqual(proposals._decided_answers(events)["p-0002"], "admit")

    def test_a_reversal_its_verb_would_not_take_is_refused_and_the_decision_stays_listed(self):
        self.append("decision", {"ticket": None, "answer": "proposal p-0002: keep parked", "decided_by": "decider",
                                 "rationale": "outside the claim", "confidence": 0.6})
        with self.assertRaises(account.AccountError):
            account.review(self.project, "D3", "reverse", answer="maybe later")
        self.assertEqual(self.events("reviewed"), [])
        self.assertIn("D3", account.account_view(self.project)["unreviewed"])


class WaitingOnYouTest(AccountCase):
    def proposed_change(self):
        import json
        record = json.loads((FIXTURES_DIR.parent / "tests" / "examples" / "change" / "valid-global-awaiting-owner.json").read_text())
        record.update(id="003-hold-captions", status="proposed", ticket=None, branch=None, worktree=None, commit=None, checks=[],
                      proof=None)
        self.book.write_json("changes/003-hold-captions.json", record)

    def test_every_kind_decision_17_names_is_listed(self):
        self.proposed_change()
        self.render()
        section = self.section("Waiting on you")
        self.assertIn("Decision ticket 6 (human only)", section)
        self.assertIn("Ticket 7, *Convert the second reference's PDF*, needs a person", section)
        self.assertIn("`wayline evolve --apply 003-hold-captions` applies it", section)
        self.assertNotIn("promote", section)

    def test_under_checkpoints_every_open_decision_ticket_waits_on_the_owner(self):
        import json
        harness = json.loads((self.project / "harness.json").read_text())
        (self.project / "harness.json").write_text(json.dumps(dict(harness, autonomy="checkpoints")))
        self.render()
        self.assertIn("Decision ticket 11:", self.section("Waiting on you"))

    def test_an_important_reference_whose_failure_is_final_is_listed(self):
        from wayline import sections
        sections.add_passage(self.project, "introduction", "Background", "Prior work reports the gain.{ref:paper-d#abstract}", by="owner")
        dossier = self.book.read_json("refs/paper-d/dossier.json")
        self.assertNotEqual(dossier.get("existence"), "verified")
        self.render()
        self.assertNotIn("paper-d", self.section("Waiting on you"), "never looked up, it is still to the scout (ticket 105)")
        dossier["attempts"] = [{"source": "crossref", "url": "https://api.crossref.org/works", "status": 200, "outcome": "no match"}]
        self.book.write_json("refs/paper-d/dossier.json", dossier, schema="dossier")
        self.render()
        self.assertIn("Reference `paper-d`", self.section("Waiting on you"))
        self.assertIn("did not resolve (every service asked answered no match), and a standing passage cites it",
                      self.section("Waiting on you"))

    def test_an_edited_report_waits_until_the_owner_writes_a_passage(self):
        self.append("report_rendered", {"sha256": "0" * 64, "report": "general", "edited": "abc123def4567"})
        self.render()
        self.assertIn("REPORT.md was edited by hand", self.section("Waiting on you"))

    def test_the_counts_line(self):
        view = account.account_view(self.project)
        self.assertEqual(account.counts_line(view), "1 decided for you, 2 waiting on you: research/ACCOUNT.md")


class ChangedWithoutAskingTest(AccountCase):
    def test_an_owners_passage_a_later_passage_replaced_is_listed_with_reason_and_evidence(self):
        from wayline import sections
        mine = sections.add_passage(self.project, "discussion", "Scope", "The gain holds on every split.", by="owner")
        sections.add_passage(self.project, "discussion", "Scope", "The gain holds on split_b only.", by="t3-a1",
                             replaces=mine["id"], ticket=3)
        self.render()
        section = self.section("Changed without asking you")
        self.assertIn("Your passage %s in Discussion" % mine["id"], section)
        self.assertIn("The gain holds on every split.", section)

    def test_a_finding_replacing_an_owners_results_passage_is_listed(self):
        from wayline import sections
        mine = sections.add_passage(self.project, "results", "Where the gain holds", "The gain holds on every split.", by="owner")
        sections.file_finding(self.project, {"id": "t9-a1-f1", "ticket": 9, "text": "The gain holds on split_b only.",
                                             "provenance": ["results/interactions/summary.json#auroc_mean"], "negative": False,
                                             "heading": "Where the gain holds", "replaces": mine["id"], "objectives": [],
                                             "reason": "the per-split runs show no gain on split_a"})
        self.render()
        section = self.section("Changed without asking you")
        self.assertIn("Your passage %s in Results" % mine["id"], section)
        self.assertIn("t9-a1-f1", section)
        self.assertIn("the per-split runs show no gain on split_a", section)

    def test_a_finding_naming_what_the_owners_passage_replaced_lists_the_owners_passage(self):
        from wayline import sections
        record = {"provenance": ["results/interactions/summary.json#auroc_mean"], "negative": False, "heading": "Gain",
                  "objectives": [], "ticket": 9}
        sections.file_finding(self.project, dict(record, id="t9-a1-f1", text="The gain holds everywhere.", replaces=None))
        mine = sections.add_passage(self.project, "results", "Gain", "The gain holds on split_b.", by="owner", replaces="t9-a1-f1")
        sections.file_finding(self.project, dict(record, id="t10-a1-f1", text="The gain holds on split_b only.", replaces="t9-a1-f1",
                                                 reason="split_a shows none", ticket=10))
        self.render()
        section = self.section("Changed without asking you")
        self.assertIn("Your passage %s in Results, \"The gain holds on split_b.\", was replaced by t10-a1-f1" % mine["id"], section)

    def test_a_passage_replacing_a_consolidation_of_the_owners_text_is_listed_and_the_consolidation_is_not(self):
        from wayline import sections
        mine = sections.add_passage(self.project, "discussion", "Scope", "The gain holds on every split.", by="owner")
        merged = sections.add_passage(self.project, "discussion", "Scope", "The gain holds on every split we ran.", by="consolidation",
                                      replaces=mine["id"], consolidates=[mine["id"]])
        later = sections.add_passage(self.project, "discussion", "Scope", "The gain holds on split_b only {res:t3-a1/results/"
                                     "interactions/summary.json#auroc_mean}.", by="t3-a1", replaces=merged["id"], ticket=3,
                                     reason="split_a shows none")
        self.render()
        section = self.section("Changed without asking you")
        self.assertIn("by %s" % later["id"], section)
        self.assertNotIn("by %s" % merged["id"], section, "a consolidation the owner asked for changed nothing without asking")
        self.assertEqual(section.count("- "), 1)


class EditRuleTest(AccountCase):
    def test_an_edit_is_committed_as_it_stood_listed_in_the_next_banner_and_never_taken_in(self):
        self.render()
        path = self.project / "research" / "ACCOUNT.md"
        path.write_text(path.read_text() + "\nI think D2 was wrong.\n", encoding="utf-8")
        rendered = self.render()
        self.assertTrue(rendered.edited)
        shown = subprocess.run(["git", "-C", str(self.project), "show", "%s:research/ACCOUNT.md" % rendered.edited],
                               capture_output=True, text=True, check=True).stdout
        self.assertIn("I think D2 was wrong.", shown)
        self.assertNotIn("I think D2 was wrong.", self.text())
        self.assertIn("was edited by hand", self.text().split("## ")[0])
        self.assertEqual(self.events("report_rendered")[-1]["payload"]["edited"], rendered.edited)
        self.assertFalse(self.render().changed)
        self.assertIn(rendered.edited[:12], self.text().split("## ")[0])


class RunsTest(AccountCase):
    def second_run(self, reason):
        self.append("run_started", {"resume": True, "harness_tag": "v0.0.0", "autonomy": "autonomous", "radius": "moderate", "pid": 1},
                    ts="2026-09-13T08:00:00.000Z")
        self.append("wave", {"number": 1, "outcomes": [], "progressed": False}, ts="2026-09-13T08:01:00.000Z")
        self.append("ticket_launched", {"ticket": 9, "attempt": 1, "role": "analyst", "model": "sonnet", "effort": "medium"}, ticket=9,
                    ts="2026-09-13T08:02:00.000Z")
        self.append("ticket_result", {"ticket": 9, "attempt": 1, "status": "done", "turns": 7, "duration_ms": 120000,
                                      "usage": {"input_tokens": 100, "output_tokens": 50, "cache_read_input_tokens": 1000,
                                                "cache_creation_input_tokens": 10}}, ticket=9, ts="2026-09-13T08:04:00.000Z")
        self.append("ticket_done", {"ticket": 9}, ticket=9, ts="2026-09-13T08:05:00.000Z")
        self.append("run_ended", {"reason": reason}, ts="2026-09-13T10:00:00.000Z")

    def test_the_latest_run_in_full_and_earlier_runs_one_row_each(self):
        self.second_run("stopped")
        self.render()
        runs = self.section("Runs")
        self.assertIn("### Run 2, the latest", runs)
        self.assertIn("ended 2026-09-13 10:00Z: the owner stopped it (`stopped`); 1 wave(s). Wall clock 2.0 hours", runs)
        self.assertIn("| 9 | analysis | done | none | sonnet | 7 | 2.0 | 1160 (100 in, 50 out, 1000 cache read, 10 cache written) |", runs)
        rows = [line for line in runs.split("Earlier runs:")[1].splitlines() if line.startswith("| 1 |")]
        self.assertEqual(len(rows), 1)
        self.assertIn("frontier_empty", rows[0])
        self.assertNotIn("$", runs)
        self.assertNotIn("dollar", runs.replace("no dollar figure is journaled", ""))

    def test_a_run_ended_by_each_reason_says_so_where_the_project_stands(self):
        for reason, words in account.REASONS.items():
            with self.subTest(reason=reason):
                self.append("run_started", {"resume": True}, ts="2026-09-14T08:00:00.000Z")
                self.append("run_ended", {"reason": reason}, ts="2026-09-14T09:00:00.000Z")
                self.render()
                self.assertIn(words, self.section("Where the project stands"))
                self.assertIn("(`%s`)" % reason, self.section("Runs"))

    def test_the_run_end_gates_and_their_scope_downs(self):
        self.append("verdict", {"subject_kind": "claim", "subject": "research/REPORT.md#claim-1", "verdict_type": "claim", "pass": False})
        self.append("ticket_created", {"ticket": 12, "kind": "writing", "proposed_by": "verifier", "origin": "research/REPORT.md#claim-1",
                                       "blocked_by": []}, ticket=12)
        self.render()
        runs = self.section("Runs")
        self.assertIn("The run-end gates:", runs)
        self.assertIn("scoped down by ticket 12", runs)

    def test_a_run_that_died_with_no_end_is_counted_to_its_last_event_and_the_account_stays_as_it_is(self):
        self.append("run_started", {"resume": True}, ts="2026-09-13T08:00:00.000Z")
        self.append("wave", {"number": 1, "outcomes": [], "progressed": False}, ts="2026-09-13T09:00:00.000Z")
        self.append("run_started", {"resume": True}, ts="2026-09-14T08:00:00.000Z")
        self.append("run_ended", {"reason": "stopped"}, ts="2026-09-14T09:00:00.000Z")
        self.render()
        (row,) = [line for line in self.section("Runs").splitlines() if line.startswith("| 2 |")]
        self.assertIn("| never journaled | none | 1 | 0 | 0 | 1.0 |", row)
        self.assertFalse(self.render().changed)

    def test_a_live_run_says_running_since(self):
        self.append("run_started", {"resume": True}, ts="2026-09-14T08:00:00.000Z")
        self.render()
        self.assertIn("Running since 2026-09-14 08:00Z (run 2).", self.section("Where the project stands"))


class Channels:
    """The notifier's channel, faked: records every message it is handed and delivers it."""

    def __init__(self):
        self.calls = []

    def __call__(self, argv, timeout):
        self.calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")


class NoticeCase(AccountCase):
    def set_autonomy(self, autonomy):
        import json
        path = self.project / "harness.json"
        path.write_text(json.dumps(dict(json.loads(path.read_text()), autonomy=autonomy)), encoding="utf-8")

    def without_the_end_notice(self):
        """The journal as a conductor that died between `run_ended` and its notice left it."""
        path = self.project / "research" / "journal.jsonl"
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        path.write_text("".join(line for line in lines if '"notified"' not in line), encoding="utf-8")

    def tick_notifications(self):
        from wayline import notify, tick
        channels = Channels()
        machine = tick.Machine(notify=lambda event, text, project, ticket: notify.notify(event, text, project=project, ticket=ticket,
                                                                                         run=channels))
        sent = tick.send_due_notifications(self.project, self.book, machine, 0, lambda line: None)
        return sent, channels


class EndNoticeTest(NoticeCase):
    def test_the_end_notice_opens_with_the_accounts_first_paragraph_and_ends_with_the_counts_and_the_path(self):
        notice = account.end_notice(self.project)
        view = account.account_view(self.project)
        self.assertTrue(notice.startswith("ended-run: The last run (run 1) ended 2026-09-12 02:39Z: no work was left on the frontier."))
        self.assertIn(view["stands"], notice)
        self.assertTrue(notice.endswith("1 decided for you, 2 waiting on you: research/ACCOUNT.md"))

    def test_the_tick_sends_the_end_notice_once_when_the_conductor_died_before_it(self):
        self.without_the_end_notice()
        sent, channels = self.tick_notifications()
        self.assertEqual([entry["event"] for entry in sent], ["run_ended"])
        (call,) = channels.calls
        self.assertEqual(call[-1], account.end_notice(self.project))
        again, channels = self.tick_notifications()
        self.assertEqual((again, channels.calls), ([], []))

    def test_the_tick_sends_nothing_when_the_conductor_sent_it(self):
        sent, channels = self.tick_notifications()
        self.assertEqual(channels.calls, [])


class AutonomyNoticeTest(NoticeCase):
    """The notifier under each autonomy, after setup: what reaches the phone as it arises, and what waits."""

    def sends(self, event, ticket=None):
        from wayline import notify
        channels = Channels()
        outcome = notify.notify(event, "a notice", project=self.project, ticket=ticket, run=channels)
        return bool(channels.calls), outcome

    def test_under_interactive_every_notice_reaches_the_phone(self):
        self.set_autonomy("interactive")
        for event, ticket in (("decision_opened", 6), ("ticket_needs_human", 7), ("paused", None), ("run_ended", None)):
            with self.subTest(event=event):
                self.assertTrue(self.sends(event, ticket)[0])

    def test_under_checkpoints_decision_tickets_notify_and_other_notices_wait(self):
        self.set_autonomy("checkpoints")
        self.assertTrue(self.sends("decision_opened", 6)[0])
        self.assertTrue(self.sends("run_ended")[0])
        held, outcome = self.sends("ticket_needs_human", 7)
        self.assertFalse(held)
        self.assertTrue(outcome["held"])
        self.assertFalse(self.sends("paused")[0])

    def test_under_autonomous_only_the_end_notice_and_the_logins_expiry_notify(self):
        from wayline import decisions, tick
        self.assertFalse(self.sends("decision_opened", 6)[0])
        self.assertFalse(self.sends("ticket_needs_human", 7)[0])
        self.assertTrue(self.sends("run_ended")[0])
        self.assertTrue(self.sends("goal_reached")[0])
        login = decisions.open_decision(self.project, "Log in again: the login expires at 2026-09-20T00:00Z", blocking=None,
                                        human_only=True, proposed_by="tick", origin=tick.LOGIN_ORIGIN, notify=lambda *a: None)
        self.assertTrue(self.sends("decision_opened", login["ticket"])[0])

    def test_before_setup_ends_every_notice_goes_out(self):
        import json
        path = self.project / "research" / "journal.jsonl"
        path.write_text("", encoding="utf-8")
        self.assertTrue(self.sends("ticket_needs_human", 7)[0])
        self.assertEqual(json.loads(path.read_text().splitlines()[-1])["payload"]["channel"], "notify-send")

    def test_the_tick_holds_what_the_autonomy_holds(self):
        self.without_the_end_notice()
        sent, _ = self.tick_notifications()
        self.assertNotIn("ticket_needs_human", [entry["event"] for entry in sent])
        self.set_autonomy("interactive")
        self.book.append_event("run_started", {"resume": True})
        sent, _ = self.tick_notifications()
        self.assertIn("ticket_needs_human", [entry["event"] for entry in sent])


class StatusTest(AccountCase):
    """`wayline status` rendered from the fixture journal: the decisions not yet reviewed, and the account line."""

    def status(self):
        from wayline import project
        view = project.status_view(self.project, refresh=False)
        return view, project.render_status(view)

    def test_status_lists_only_the_decisions_not_yet_reviewed_and_prints_the_account_line(self):
        view, text = self.status()
        self.assertEqual([(entry["decision"], entry["decided_by"]) for entry in view["decided"]], [("D2", "decider")])
        self.assertIn("Account: 1 decided for you, 2 waiting on you: research/ACCOUNT.md", text.splitlines())
        self.assertNotIn("20000 rows", text)  # the owner's own answer is no decision made for them
        account.review(self.project, "D2", "stand")
        view, text = self.status()
        self.assertEqual(view["decided"], [])
        self.assertIn("Account: 0 decided for you, 2 waiting on you: research/ACCOUNT.md", text.splitlines())


class ConductorAccountTest(ConductorCase):
    """The conductor renders the account every wave, its ledger commit carries it, and a run's end sends one notice."""

    def run_to_its_end(self):
        sent = []
        with worker.use_fake() as fake:
            fake.script(done(), patch=patch())
            self.conductor = Conductor(self.project, out=io.StringIO())
            self.conductor.readings = machine.recorded
            self.conductor.notify = lambda event, text, project=None, ticket=None: sent.append((event, text))
            results = drive(self.conductor)
        return results, sent

    def test_each_wave_commits_the_account_and_the_run_end_sends_one_notice_opening_with_its_paragraph(self):
        results, sent = self.run_to_its_end()
        self.assertTrue(results[-1].ended)
        committed = self.git("show", "main:research/ACCOUNT.md")
        self.assertEqual(committed + "\n", (self.project / "research" / "ACCOUNT.md").read_text(encoding="utf-8"))
        self.assertIn("## Where the project stands", committed)
        self.assertEqual([event for event, _ in sent], ["run_ended"])
        self.assertEqual(sent[0][1], account.end_notice(self.project))
        self.assertIn("no work was left on the frontier", sent[0][1])
        names = [event["event"] for event in self.events()]
        self.assertLess(names.index("run_ended"), len(names) - 1 - names[::-1].index("report_rendered"),
                        "the account is rendered after the run's end, before its notice")

    def test_a_conductor_that_sent_the_end_notice_leaves_the_tick_nothing_to_send(self):
        from wayline import tick
        self.run_to_its_end()  # the recorder stands in for the notifier, so its claim is journaled here as the notifier would
        self.ledger.append_event("notified", {"event": "run_ended", "channel": "none", "ok": False, "exit_code": None})
        sent = tick.send_due_notifications(self.project, self.ledger, tick.Machine(notify=lambda *args: {}), 0, lambda line: None)
        self.assertEqual(sent, [])
