"""Type-B verdicts: the verifier role and the two gates (Implementation Decisions 11).

The gate is driven with the fake launcher over a real project, and what is asserted is what the
next component and the owner can see: the journal's `verdict` and `ticket_accepted` events, the
ticket statuses in the files, the prompt the session was handed, and the launch line's model.

The one rule that holds under every other assertion: a verdict is a fresh launch carrying none of the
author's context, whichever model the table gives it.
"""

import io
import json
import shutil
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from tests.paths import HARNESS_ROOT
from tests.projects import ProjectTestCase
from tests.test_conductor import ConductorCase, done, patch, combined, drive
from wayline import conductor, gates, project, replay, schedule, tickets, worker
from wayline.gates import GateError
from wayline.ledger import Ledger
from wayline.worker import Envelope

ONE_TICKET = HARNESS_ROOT / "fixtures" / "projects" / "one-ticket"
TICKET_FILE = "research/tickets/01-write-the-hello-file.md"

CRITERION = "Does hello.txt hold exactly the one line the ticket asked for?"


def passing(question_limit="Only the criteria the ticket set.", **extra):
    """An envelope carrying the verdict a verifier returns when the subject answers the question."""
    record = {"pass": True, "findings": [], "question_limit": question_limit}
    record.update(extra)
    return Envelope(structured_output=record, num_turns=4, duration_ms=9000)


def failing(text="hello.txt holds two lines where the ticket asked for one.",
            locator="hello.txt#L2", severity="blocker", **extra):
    """An envelope carrying a verdict that fails, with one finding at a locator."""
    record = {
        "pass": False,
        "findings": [{"text": text, "locator": locator, "severity": severity}],
        "question_limit": "Only the criteria the ticket set.",
    }
    record.update(extra)
    return Envelope(structured_output=record, num_turns=6, duration_ms=12000)


class VerifierRoleTest(unittest.TestCase):
    """`roles/verifier/` as the harness ships it: read-only, judging, its own schema and prompt."""

    def setUp(self):
        self.role = worker.read_role(gates.VERIFIER)

    def test_the_role_judges_and_returns_a_verdict(self):
        self.assertEqual(self.role.name, "verifier")
        self.assertTrue(self.role.may_judge)
        self.assertEqual(self.role.output_schema, "verdict")
        self.assertEqual(self.role.kinds, [], "the verifier is launched by the gate, not assigned to tickets")

    def test_the_role_can_read_and_cannot_write(self):
        for tool in ("Read", "Glob", "Grep", "Bash(git show*)", "Bash(git diff*)"):
            with self.subTest(tool=tool):
                self.assertIn(tool, self.role.allowed_tools)
        for tool in ("Edit", "Write", "NotebookEdit"):
            with self.subTest(tool=tool):
                self.assertIn(tool, self.role.disallowed_tools)
                self.assertNotIn(tool, self.role.allowed_tools)

    def test_the_role_carries_none_of_the_authors_skills_or_the_host_tools(self):
        for tool in ("Skill", "Workflow", "mcp__*", "Agent", "WebFetch", "WebSearch", "Monitor",
                     "ToolSearch"):
            with self.subTest(tool=tool):
                self.assertIn(tool, self.role.disallowed_tools)

    def test_no_bash_rule_names_a_command_that_writes(self):
        """docs/verification/m4.md: the allowlist is not what makes the verifier read-only.

        A read-only command runs under `dontAsk` whether a rule names it or not, and a command
        that writes is refused whether one does or not. The list is the harness saying what it
        means to permit, so a write in it would be the harness meaning the wrong thing.
        """
        writes = ("git commit", "git add", "git push", "git checkout", "git rebase", "git merge",
                  "rm ", "mv ", "cp ", "tee", "truncate", "mkdir", "printf", "echo", "sed -i")
        for rule in self.role.allowed_tools:
            for command in writes:
                with self.subTest(rule=rule, command=command.strip()):
                    self.assertNotIn(command, rule)

    def test_the_protocol_comes_from_prompts(self):
        self.assertEqual(self.role.protocol,
                         (HARNESS_ROOT / "prompts" / "roles" / "verifier.md").read_text(encoding="utf-8"))
        self.assertIn("question_limit", self.role.protocol)


class VerifierTableTest(unittest.TestCase):
    """`policy.verifier`: the model table of decision 11, and the rule under it."""

    def setUp(self):
        self.policy = json.loads((HARNESS_ROOT / "policy.json").read_text(encoding="utf-8"))

    def test_the_shipped_table_is_the_spec_table(self):
        self.assertEqual(gates.verifier_tier(self.policy, "sonnet"), ("opus", "high"))
        self.assertEqual(gates.verifier_tier(self.policy, "opus"), ("opus", "max"))
        self.assertEqual(gates.verifier_tier(self.policy, "fable"), ("opus", "max"))

    def test_the_shipped_table_puts_no_verifier_on_fable(self):
        """Ticket 65: Opus 5.5 reads Opus's work in a fresh session, so no verdict draws on Fable's weekly window."""
        for author in ("sonnet", "opus", "fable"):
            with self.subTest(author=author):
                self.assertEqual(gates.verifier_tier(self.policy, author)[0], "opus")
                self.assertFalse(gates.verifies_on_fable(self.policy, author))

    def test_an_override_that_names_the_authors_model_is_taken(self):
        """The table is the default choice, not the rule: a fresh session on the author's model is a verdict (ticket 56)."""
        overridden = dict(self.policy, verifier=dict(self.policy["verifier"],
                                                     sonnet={"model": "sonnet", "effort": "high"}))
        self.assertEqual(gates.verifier_tier(overridden, "sonnet"), ("sonnet", "high"))

    def test_an_author_the_table_does_not_name_is_refused_by_name(self):
        with self.assertRaises(GateError) as caught:
            gates.verifier_tier(self.policy, "haiku")
        self.assertIn("haiku", str(caught.exception))
        self.assertIn("fable, opus, sonnet", str(caught.exception))

    def test_an_effort_outside_the_launchers_list_is_refused(self):
        overridden = dict(self.policy, verifier=dict(self.policy["verifier"],
                                                     sonnet={"model": "opus", "effort": "thorough"}))
        with self.assertRaises(GateError) as caught:
            gates.verifier_tier(overridden, "sonnet")
        self.assertIn("thorough", str(caught.exception))


class TicketAsksTest(unittest.TestCase):
    """What a done ticket earns (decision 11, "what gets a verdict"), as a function of the ticket."""

    def ticket(self, **changes):
        base = {"id": 4, "title": "Train the baseline", "acceptance": {"machine": ["true"], "quality": []}}
        base.update(changes)
        return base

    def asks(self, difficulty, quality=(), **changes):
        ticket = self.ticket(acceptance={"machine": [], "quality": list(quality)}, **changes)
        return gates.ticket_asks(ticket, difficulty, "sonnet", TICKET_FILE, commit="abc123def456")

    def test_an_easy_ticket_with_no_quality_criteria_earns_nothing(self):
        for difficulty in (1, 2):
            with self.subTest(difficulty=difficulty):
                self.assertEqual(self.asks(difficulty), [])

    def test_quality_criteria_earn_a_verdict_at_every_difficulty(self):
        for difficulty in (1, 2, 3, 4, 5):
            with self.subTest(difficulty=difficulty):
                types = [ask.verdict_type for ask in self.asks(difficulty, [CRITERION])]
                self.assertIn(gates.QUALITY, types)

    def test_a_blank_quality_entry_is_not_a_criterion(self):
        self.assertEqual(self.asks(1, ["   "]), [])

    def test_difficulty_three_is_read_as_its_diff_and_four_and_five_as_their_result(self):
        self.assertEqual([ask.verdict_type for ask in self.asks(3)], [gates.DIFF])
        self.assertEqual([ask.verdict_type for ask in self.asks(4)], [gates.RESULT])
        self.assertEqual([ask.verdict_type for ask in self.asks(5)], [gates.RESULT])

    def test_a_difficulty_three_ticket_with_no_diff_of_its_own_is_read_as_its_result(self):
        """The M5 run's scope-down writing tickets filed findings and committed nothing; their diff was the ledger's."""
        ticket = self.ticket(acceptance={"machine": [], "quality": []})
        asks = gates.ticket_asks(ticket, 3, "sonnet", TICKET_FILE, commit="abc123def456", no_diff=True)
        self.assertEqual([ask.verdict_type for ask in asks], [gates.RESULT])
        self.assertNotIn("abc123def456", " ".join(ask.question + ask.scope_limit for ask in asks))

    def test_a_hard_ticket_with_criteria_earns_both(self):
        self.assertEqual([ask.verdict_type for ask in self.asks(4, [CRITERION])],
                         [gates.QUALITY, gates.RESULT])

    def test_the_diff_verdict_names_the_commit_to_read(self):
        ask = self.asks(3)[0]
        self.assertIn("abc123def456", ask.scope_limit)
        self.assertIn("abc123def456"[:12], ask.question)

    def test_every_ask_carries_the_ticket_file_as_its_subject(self):
        for ask in self.asks(4, [CRITERION]):
            with self.subTest(kind=ask.verdict_type):
                self.assertEqual(ask.subject_kind, "ticket")
                self.assertEqual(ask.subject, TICKET_FILE)
                self.assertEqual(ask.ticket, 4)
                self.assertIn(TICKET_FILE, ask.paths)
                self.assertEqual(ask.author_model, "sonnet")


class VerdictPromptTest(unittest.TestCase):
    """The prompt one verifier session is handed: the question, the scope, the paths, the schema."""

    def setUp(self):
        self.role = worker.read_role(gates.VERIFIER)

    def prompt(self, paths=("research/INTAKE.md",), cwd=None, memo=None):
        return gates.verdict_prompt(self.role, "ticket", TICKET_FILE, "Is it right?",
                                    list(paths), "Only that.", cwd=cwd, memo=memo)

    def test_the_question_the_scope_and_the_paths_are_in_it(self):
        text = self.prompt()
        self.assertIn("Is it right?", text)
        self.assertIn("Only that.", text)
        self.assertIn("`research/INTAKE.md`", text)
        self.assertIn(TICKET_FILE, text)

    def test_the_protocol_and_the_schema_fields_are_in_it(self):
        text = self.prompt()
        self.assertIn("Protocol", text)
        for field in ("`pass`", "`findings`", "`question_limit`"):
            self.assertIn(field, text)

    def test_no_skill_line_reaches_the_verifier(self):
        self.assertNotIn("/wayline-", self.prompt())

    def test_a_path_that_is_not_there_is_said_to_be_missing_where_it_is_listed(self):
        text = self.prompt(paths=["research/INTAKE.md", "nowhere/at/all.md"], cwd=ONE_TICKET)
        self.assertIn("nowhere/at/all.md`  [wayline: this path is not there", text)
        self.assertNotIn("research/INTAKE.md`  [wayline", text)

    def test_a_question_with_no_path_says_so_rather_than_asking_it_anyway(self):
        self.assertIn("no path was given", self.prompt(paths=[]))

    def test_the_memo_reaches_the_adjudicating_thread_with_its_locators(self):
        text = self.prompt(memo=[{"text": "The baseline is not the one the field uses.",
                                  "locator": "research/REPORT.md#L40", "severity": "major"}])
        self.assertIn("[major] The baseline is not the one the field uses.", text)
        self.assertIn("research/REPORT.md#L40", text)
        self.assertIn("point by point", text)

    def test_a_memo_with_no_case_is_said_to_have_none_rather_than_left_out(self):
        """An empty memo is an answer; an adjudicator told nothing would invent something."""
        text = self.prompt(memo=[])
        self.assertIn("found no case to make", text)
        self.assertNotIn("rejection memo to adjudicate", self.prompt(memo=None))


class GateCase(ProjectTestCase):
    """A laid-out one-ticket project and the fake launcher, for the gate on its own."""

    def setUp(self):
        super().setUp()
        self.project = self.temp / "one-ticket"
        shutil.copytree(ONE_TICKET, self.project)
        project.init_project(self.project)
        self.ledger = Ledger(self.project)

    def take(self, *scripted, **kwargs):
        """Script the fake, take one verdict, and keep the requests the fake was handed.

        The calls are kept whether the gate returned or raised, because what a refused verdict
        did not spend is half of what the refusal is worth.
        """
        self.calls = []
        asked = dict(subject_kind="ticket", subject=TICKET_FILE, question="Is it right?",
                     paths=[TICKET_FILE], scope_limit="Only that.")
        options = dict(project=self.project, author_model="sonnet",
                       verdict_type=gates.QUALITY, ticket=1)
        for key, value in kwargs.items():
            (asked if key in asked else options)[key] = value
        with worker.use_fake() as fake:
            for envelope in scripted:
                fake.script(envelope)
            try:
                return gates.verdict(asked["subject_kind"], asked["subject"], asked["question"],
                                     asked["paths"], asked["scope_limit"], **options)
            finally:
                self.calls = list(fake.calls)

    def events(self, name=None):
        events, _ = self.ledger.read_events()
        return [event for event in events if name is None or event["event"] == name]

    def payload(self, name):
        found = self.events(name)
        self.assertTrue(found, "no %s event in the journal" % name)
        return found[-1]["payload"]


class VerdictGateTest(GateCase):
    """`gates.verdict`: the launch, the validation, the journal record."""

    def test_a_passing_verdict_comes_back_and_is_journaled(self):
        taken = self.take(passing())
        self.assertTrue(taken.passed)
        self.assertEqual(taken.findings, [])
        payload = self.events("verdict")[0]["payload"]
        self.assertEqual(payload["subject_kind"], "ticket")
        self.assertEqual(payload["subject"], TICKET_FILE)
        self.assertEqual(payload["verdict_type"], gates.QUALITY)
        self.assertTrue(payload["pass"])
        self.assertEqual(payload["findings"], [])
        self.assertEqual(payload["model"], "claude-opus-5")
        self.assertTrue(payload["session_id"])

    def test_the_journal_carries_the_session_id_and_the_ticket(self):
        taken = self.take(passing())
        event = self.events("verdict")[0]
        self.assertEqual(event["ticket"], 1)
        self.assertEqual(event["session_id"], taken.session_id)

    def test_a_failing_verdict_carries_its_findings_to_the_journal(self):
        taken = self.take(failing())
        self.assertFalse(taken.passed)
        payload = self.events("verdict")[0]["payload"]
        self.assertFalse(payload["pass"])
        self.assertEqual(payload["findings"], [{
            "text": "hello.txt holds two lines where the ticket asked for one.",
            "locator": "hello.txt#L2", "severity": "blocker",
        }])

    def test_the_launch_is_on_the_model_the_table_gives_for_the_author(self):
        self.take(passing(), author_model="sonnet")
        request = self.calls[0].request
        self.assertEqual((request.model, request.effort), ("opus", "high"))
        self.assertEqual(request.role, "verifier")

    def test_under_the_shipped_table_each_author_is_read_by_a_fresh_opus_session(self):
        for author in ("sonnet", "opus", "fable"):
            with self.subTest(author=author):
                self.take(passing(), author_model=author)
                self.assertEqual((self.calls[0].kind, self.calls[0].session_id, self.calls[0].request.model), ("launch", None, "opus"))

    def test_the_session_can_write_nothing_and_can_stop(self):
        """The two variables `verdict_env` leaves out are what read-only and stoppable mean."""
        self.take(passing())
        env = self.calls[0].request.env
        self.assertNotIn("TICKET_TOUCHES", env)
        self.assertNotIn("TICKET_ACCEPTANCE_FILE", env)
        self.assertEqual(env["WAYLINE_PROJECT"], str(self.project))

    def test_the_launch_carries_the_verdict_schema_and_the_rendered_guards(self):
        self.take(passing())
        request = self.calls[0].request
        self.assertEqual(Path(request.schema_path).name, "verdict.json")
        settings = json.loads(Path(request.settings_path).read_text(encoding="utf-8"))
        self.assertIn("PreToolUse", settings["hooks"])

    def test_the_session_runs_in_the_project_and_writes_under_verdicts(self):
        self.take(passing())
        call = self.calls[0]
        self.assertEqual(Path(call.request.cwd), self.project)
        self.assertIn("research/sessions/verdicts", str(call.run_dir).replace("\\", "/"))
        self.assertTrue((call.run_dir / "prompt.md").is_file())

    def test_a_second_verdict_on_one_subject_keeps_both_streams(self):
        first = gates.verdict_dir(self.project, "ticket", TICKET_FILE)
        first.mkdir(parents=True)
        second = gates.verdict_dir(self.project, "ticket", TICKET_FILE)
        self.assertEqual((first.name, second.name), ("1", "2"))
        self.assertEqual(first.parent, second.parent)

    def test_an_unusable_answer_is_resumed_once_and_then_raises(self):
        with self.assertRaises(GateError) as caught:
            self.take(Envelope(subtype="error_max_structured_output_retries", is_error=True),
                      Envelope(subtype="error_max_structured_output_retries", is_error=True))
        self.assertIn("could not be taken", str(caught.exception))
        self.assertEqual([call.kind for call in self.calls], ["launch", "resume"])
        self.assertEqual(self.events("verdict"), [], "a verdict nobody could take is not journaled")

    def test_a_resumed_session_that_answers_is_the_verdict(self):
        taken = self.take(Envelope(subtype="error_max_structured_output_retries", is_error=True), passing())
        self.assertTrue(taken.passed)
        self.assertIn("Return the verdict now", self.calls[1].message)

    def test_a_pass_carrying_a_blocker_is_not_an_answer(self):
        blocking = {"text": "This is broken.", "locator": "hello.txt#L1", "severity": "blocker"}
        with self.assertRaises(GateError) as caught:
            self.take(passing(findings=[blocking]), passing(findings=[blocking]))
        self.assertIn("blocking finding", str(caught.exception))

    def test_a_fail_that_names_no_finding_is_not_an_answer(self):
        empty = Envelope(structured_output={"pass": False, "findings": [], "question_limit": "That."})
        with self.assertRaises(GateError) as caught:
            self.take(empty, empty)
        self.assertIn("named no finding", str(caught.exception))

    def test_a_verdict_type_outside_the_list_is_refused_before_a_session_is_spent(self):
        with self.assertRaises(GateError) as caught:
            self.take(passing(), verdict_type="vibes")
        self.assertIn("vibes", str(caught.exception))
        self.assertEqual(self.calls, [])

    def test_a_subject_kind_the_journal_could_not_carry_is_refused_before_a_session_is_spent(self):
        """The gate must not spend a session on a verdict it would then be unable to journal."""
        with self.assertRaises(GateError) as caught:
            self.take(passing(), subject_kind="notebook")
        self.assertIn("notebook", str(caught.exception))
        self.assertEqual(self.calls, [])
        self.assertEqual(gates.SUBJECT_KINDS,
                         ("ticket", "claim", "figure", "spec", "dossier", "paper"))

    def test_a_verdict_with_no_question_is_refused_before_a_session_is_spent(self):
        for empty in ({"question": "  "}, {"scope_limit": ""}, {"subject": ""}):
            with self.subTest(**empty):
                options = {"question": "Is it right?", "scope_limit": "Only that.",
                           "subject": TICKET_FILE}
                options.update(empty)
                with self.assertRaises(GateError):
                    self.take(passing(), **options)
                self.assertEqual(self.calls, [])


class KillArgumentTest(GateCase):
    """`gates.kill_argument`: two threads, one verdict, and the `writing` ticket a fail files."""

    def run_gate(self, *scripted, **kwargs):
        with worker.use_fake() as fake:
            for envelope in scripted:
                fake.script(envelope)
            options = dict(project=self.project, author_model="fable", subject_kind="paper")
            options.update(kwargs)
            taken = gates.kill_argument(["research/REPORT.md"], **options)
            self.calls = list(fake.calls)
        return taken

    def memo(self):
        return failing(text="The headline claim rests on one seed.",
                       locator="research/REPORT.md#L12", severity="major")

    def test_two_sessions_run_and_the_adjudication_is_the_verdict(self):
        taken = self.run_gate(self.memo(), passing())
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(taken.verdict_type, gates.KILL_ARGUMENT)
        self.assertTrue(taken.passed)

    def test_only_the_adjudication_is_journaled_as_a_verdict(self):
        """The memo is the case against the work, not a judgment of it.

        Journaling it would leave a failing Type-B verdict in the ledger against a paper the
        second thread went on to clear, and the report renders the ledger.
        """
        taken = self.run_gate(self.memo(), passing())
        payloads = [event["payload"] for event in self.events("verdict")]
        self.assertEqual([item["verdict_type"] for item in payloads], [gates.KILL_ARGUMENT])
        self.assertTrue(payloads[0]["pass"])
        self.assertEqual(payloads[0]["session_id"], taken.session_id)

    def test_the_memos_session_is_on_disk_beside_the_adjudications(self):
        self.run_gate(self.memo(), passing())
        memo, adjudication = (call.run_dir for call in self.calls)
        self.assertTrue((memo / "stream.jsonl").is_file())
        self.assertTrue((adjudication / "stream.jsonl").is_file())
        self.assertNotEqual(memo, adjudication)

    def test_a_memo_that_finds_no_case_passes_the_gate_rather_than_raising(self):
        """`pass` means one thing in both threads, so an empty memo is an answer, not a failure."""
        taken = self.run_gate(passing(question_limit="I can make no case against these paths."),
                              passing())
        self.assertTrue(taken.passed)
        self.assertEqual(len(self.calls), 2)
        self.assertIn("found no case to make", self.calls[1].request.prompt)
        self.assertEqual([item["id"] for item in tickets.read_tickets(self.project)], [1])

    def test_both_threads_run_on_the_verifier_the_table_gives_the_author(self):
        self.run_gate(self.memo(), passing(), author_model="fable")
        for call in self.calls:
            self.assertEqual(call.request.model, "opus")
            self.assertEqual(call.request.effort, "max")

    def test_the_memos_points_reach_the_adjudicating_session_and_not_the_memos_own(self):
        self.run_gate(self.memo(), passing())
        first, second = (call.request.prompt for call in self.calls)
        self.assertNotIn("rejection memo to adjudicate", first)
        self.assertIn("The headline claim rests on one seed.", second)
        self.assertIn("research/REPORT.md#L12", second)

    def test_the_two_threads_of_one_gate_share_a_run_directory(self):
        self.run_gate(self.memo(), passing())
        memo, adjudication = (call.run_dir for call in self.calls)
        self.assertEqual((memo.name, adjudication.name), ("memo", "adjudication"))
        self.assertEqual(memo.parent, adjudication.parent)

    def test_a_pass_files_no_ticket(self):
        self.run_gate(self.memo(), passing())
        self.assertEqual([item["id"] for item in tickets.read_tickets(self.project)], [1])

    def test_a_fail_scopes_the_claims_down_with_a_writing_ticket(self):
        taken = self.run_gate(self.memo(), failing(text="One seed is one seed.",
                                                   locator="research/REPORT.md#L12",
                                                   severity="blocker"))
        self.assertFalse(taken.passed)
        filed = {item["id"]: item for item in tickets.read_tickets(self.project)}[2]
        self.assertEqual(filed["kind"], "writing")
        self.assertEqual(filed["status"], "open")
        self.assertEqual(filed["proposed_by"], "verifier")
        self.assertEqual(filed["touches"], ["research/REPORT.md"])
        self.assertTrue(filed["acceptance"]["quality"])
        payload = self.events("ticket_created")[0]["payload"]
        self.assertEqual(payload, {"ticket": 2, "kind": "writing", "proposed_by": "verifier",
                                   "origin": "research/REPORT.md", "blocked_by": []})

    def test_the_filed_ticket_carries_the_points_that_still_stand(self):
        self.run_gate(self.memo(), failing(text="One seed is one seed.",
                                           locator="research/REPORT.md#L12", severity="blocker"))
        filed = {item["id"]: item for item in tickets.read_tickets(self.project)}[2]
        body = (tickets.tickets_dir(self.project) / tickets.filename(filed)).read_text(encoding="utf-8")
        self.assertIn("One seed is one seed.", body)
        self.assertIn("research/REPORT.md#L12", body)
        self.assertIn("[blocker]", body)
        self.assertIn(self.payload("verdict")["session_id"], body)
        memo_session = [call for call in self.calls][0]
        self.assertIn("rejection memo was written by verifier session", body)
        self.assertTrue(memo_session.run_dir.name == "memo")

    def test_a_gate_with_no_paths_is_refused_before_a_session_is_spent(self):
        with worker.use_fake() as fake:
            fake.script(passing())
            with self.assertRaises(GateError):
                gates.kill_argument([], project=self.project, author_model="fable")
            self.assertEqual(fake.calls, [])


class ConductorVerdictTest(ConductorCase):
    """The conductor's queue (decision 11): a done ticket earns a verdict and is accepted or failed."""

    def quality(self, criteria=(CRITERION,), difficulty=1):
        """Rewrite the fixture's ticket so its done attempt earns a verdict."""
        path = tickets.tickets_dir(self.project) / "01-write-the-hello-file.md"
        fields, body = tickets.read_ticket(path)
        fields["acceptance"] = dict(fields["acceptance"], quality=list(criteria))
        fields["difficulty"] = difficulty
        tickets.write_ticket(self.ledger, fields, body)
        self.git("add", "--", "research")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "ticket: add a quality criterion")

    def conduct_with(self, verdicts, worker_envelope=None, waves=None):
        """Waves with the worker's call scripted by ticket and the verdicts by role, settled between waves."""
        with worker.use_fake() as fake:
            fake.script(worker_envelope or done(), patch=patch(), ticket=1)
            for envelope in verdicts:
                fake.script(envelope, role=gates.VERIFIER)
            self.conductor = conductor.Conductor(self.project, out=io.StringIO())
            results = drive(self.conductor, waves)
            self.calls = list(fake.calls)
        return results

    def test_a_ticket_with_no_quality_criteria_at_difficulty_one_earns_no_verdict(self):
        self.conduct((done(), patch()))
        self.assertEqual(self.events("verdict"), [])
        self.assertEqual(self.ticket()["status"], "done")

    def test_a_ticket_that_committed_nothing_earns_a_read_of_its_result_not_of_a_diff(self):
        """The M5 run: a difficulty-3 ticket whose work is findings integrates no commit, and `main`'s head is not its diff."""
        path = tickets.tickets_dir(self.project) / "01-write-the-hello-file.md"
        fields, body = tickets.read_ticket(path)
        tickets.write_ticket(self.ledger, dict(fields, difficulty=3, acceptance=dict(fields["acceptance"], machine=["true"])), body)
        self.git("add", "--", "research")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "ticket: its work commits nothing")
        with worker.use_fake() as fake:
            fake.script(done(outputs_written=[]), ticket=1)
            fake.script(passing(), role=gates.VERIFIER)
            made = conductor.Conductor(self.project, out=io.StringIO())
            drive(made)
        self.assertTrue(self.payload("integrated").get("empty"))
        self.assertEqual([item["payload"]["verdict_type"] for item in self.events("verdict")], [gates.RESULT])
        self.assertEqual(self.ticket()["status"], "accepted")
        self.assertIn(1, replay.replay(self.ledger.read_events()[0]).integrated_empty)

    def test_a_passing_verdict_accepts_the_ticket(self):
        self.quality()
        result = combined(self.conduct_with([passing()]))
        self.assertEqual(self.ticket()["status"], "accepted")
        self.assertEqual([event["payload"]["ticket"] for event in self.events("ticket_accepted")], [1])
        self.assertEqual(result.accepted, [1])
        self.assertEqual(result.done, [1])

    def test_the_verdict_is_journaled_after_the_ticket_was_done(self):
        self.quality()
        self.conduct_with([passing()])
        sequence = self.sequence()
        self.assertLess(sequence.index("ticket_done"), sequence.index("verdict"))
        self.assertLess(sequence.index("verdict"), sequence.index("ticket_accepted"))

    def test_the_verdict_runs_on_the_verifier_of_the_authors_model(self):
        self.quality(difficulty=1)
        self.conduct_with([passing()])
        launches = [call.request for call in self.calls]
        self.assertEqual([request.role for request in launches], ["coder", "verifier"])
        self.assertEqual((launches[0].model, launches[1].model), ("sonnet", "opus"))
        self.assertEqual(self.payload("verdict")["model"], "claude-opus-5")

    def test_a_failing_verdict_fails_the_ticket_with_the_findings_as_its_output(self):
        self.quality()
        result = combined(self.conduct_with([failing()]))
        self.assertEqual(self.ticket()["status"], "failed")
        payload = self.payload("ticket_failed")
        self.assertEqual(payload["next"], "resume")
        self.assertEqual(payload["attempt"], 1)
        self.assertIn("hello.txt holds two lines", payload["reason"])
        self.assertIn("hello.txt#L2", payload["reason"])
        self.assertEqual(result.rejected, [1])

    def test_the_findings_reach_the_ticket_file_the_next_attempt_is_assembled_from(self):
        self.quality()
        self.conduct_with([failing()])
        body = self.body()
        self.assertIn("**Verdict (quality): failed**", body)
        self.assertIn("hello.txt holds two lines", body)
        self.assertIn("hello.txt#L2", body)
        self.assertIn(self.payload("verdict")["session_id"], body)

    def test_an_accepted_ticket_says_who_acquitted_it_and_on_what(self):
        self.quality()
        self.conduct_with([passing()])
        body = self.body()
        self.assertIn("**Verdict (quality): passed**", body)
        self.assertIn("claude-opus-5", body)
        self.assertEqual(body.count("## Result"), 1, "the verdict goes under the attempt's own section")

    def test_a_hard_ticket_earns_two_verdicts_and_both_have_to_pass(self):
        self.quality(difficulty=4)
        self.conduct_with([passing(), passing()])
        self.assertEqual([event["payload"]["verdict_type"] for event in self.events("verdict")],
                         [gates.QUALITY, gates.RESULT])
        self.assertEqual(self.ticket()["status"], "accepted")

    def test_the_second_verdict_is_not_spent_once_the_first_has_failed(self):
        self.quality(difficulty=4)
        self.conduct_with([failing(), passing()])
        self.assertEqual([event["payload"]["verdict_type"] for event in self.events("verdict")],
                         [gates.QUALITY])
        self.assertEqual(self.ticket()["status"], "failed")

    def test_the_diff_verdict_of_a_difficulty_three_ticket_names_the_integrated_commit(self):
        self.quality(criteria=[], difficulty=3)
        self.conduct_with([passing()])
        commit = self.payload("integrated")["commit"]
        prompt = [call.request.prompt for call in self.calls if call.request.role == "verifier"][0]
        self.assertIn(commit[:12], prompt)
        self.assertEqual(self.payload("verdict")["verdict_type"], gates.DIFF)

    def test_pacing_holds_the_queue_rather_than_taking_half_of_it(self):
        self.quality(difficulty=4)
        with worker.use_fake() as fake:
            fake.script(done(), patch=patch(), ticket=1)
            self.conductor = conductor.Conductor(self.project, out=io.StringIO())
            self.conductor.wave()
            self.conductor.settle()
            self.conductor.action = schedule.STOP
            first = self.conductor.wave()
            self.assertEqual(self.events("verdict"), [])
            self.assertEqual(self.ticket()["status"], "done")
            self.assertEqual(len(self.conductor.verdicts), 1)
            fake.script(passing(), role=gates.VERIFIER)
            fake.script(passing(), role=gates.VERIFIER)
            self.conductor.action = schedule.NORMAL
            second = self.conductor.wave()
        self.assertEqual(self.ticket()["status"], "accepted")
        self.assertEqual((first.accepted, second.accepted), ([], [1]))
        self.assertTrue(first.touched and second.touched)

    def test_the_verb_exits_nonzero_and_names_the_ticket_its_verdict_failed(self):
        """A rejected ticket is in neither the frontier nor the running set, so the verb says it."""
        harness = json.loads((self.project / "harness.json").read_text(encoding="utf-8"))
        harness["policy"] = {"poll_seconds": 1}  # the verb waits this long between waves, and the shipped 60 s is a minute
        (self.project / "harness.json").write_text(json.dumps(harness, indent=2) + "\n", encoding="utf-8")
        self.git("add", "--", "harness.json")
        self.quality()
        out, err = io.StringIO(), io.StringIO()
        with worker.use_fake() as fake:
            fake.script(done(), patch=patch(), ticket=1)
            fake.script(failing(), role=gates.VERIFIER)
            with redirect_stdout(out), redirect_stderr(err):
                code = conductor.run_command(["--project", str(self.project)])
        self.assertEqual(code, 1, out.getvalue() + err.getvalue())
        self.assertIn("failed their quality verdict", out.getvalue())
        self.assertEqual(self.ticket()["status"], "needs_human", "its resume had nothing scripted")

    def test_a_verdict_nobody_could_take_leaves_the_ticket_done_and_unaccepted(self):
        self.quality()
        unusable = Envelope(subtype="error_max_structured_output_retries", is_error=True)
        result = combined(self.conduct_with([unusable, unusable]))
        self.assertEqual(self.ticket()["status"], "done")
        self.assertEqual(self.events("verdict"), [])
        self.assertEqual(self.events("ticket_accepted"), [])
        self.assertEqual((result.accepted, result.rejected), ([], []))


if __name__ == "__main__":
    unittest.main()
