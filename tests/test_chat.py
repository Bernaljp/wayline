"""The dashboard's chat (Implementation Decision 17, Talking with the project; ticket 114).

Every chat session runs over the fake launcher, which scripts what a session returns: a first message, a resumed one,
one past the hour, a queued second message, and a card. The project is a copy of `fixtures/ledger/`; the seam is
`wayline.chat` (posting a message and answering the queue) and the `LaunchRequest` it hands the launcher.
"""

import contextlib
import io
import json
from unittest import mock

from tests.paths import HARNESS_ROOT
from tests.projects import ProjectTestCase
from wayline import chat, cli, worker
from wayline.worker import Envelope

T0 = 1_800_000_000.0


def reply(text="Here is where it stands.", card=None, session="s-1"):
    return Envelope(session_id=session, structured_output={"reply": text, "card": card}, answered=True)


class ChatCase(ProjectTestCase):
    def setUp(self):
        super().setUp()
        self.project = self.ledger_fixture()
        self.fake = self.enterContext(worker.use_fake())

    def script(self, *envelopes):
        for envelope in envelopes:
            self.fake.script(envelope, role=chat.ROLE)

    def say(self, text, now=T0, view=None, item=None):
        record = chat.post(self.project, text, view=view, item=item, now=now)
        chat.answer_queued(self.project, now=now)
        return chat.read_message(self.project, record["id"])

    def run_verb(self, *argv):
        """`wayline <argv>` as a chat session's command runs it, under `WAYLINE_CHAT`: its exit code and what it printed."""
        out = io.StringIO()
        environment = {chat.CHAT_ENV: "1", "WAYLINE_PROJECT": str(self.project)}
        with mock.patch.dict("os.environ", environment), contextlib.redirect_stderr(out), contextlib.redirect_stdout(out):
            code = cli.main(list(argv))
        return code, out.getvalue()

    def harness(self, **fields):
        path = self.project / "harness.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        value.update(fields)
        path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


class FirstMessageTest(ChatCase):
    def test_a_first_message_starts_one_session_fresh_from_the_digest_on_opus_high(self):
        self.script(reply("Two decisions wait on you."))
        record = self.say("How does it stand?")
        [call] = self.fake.calls
        self.assertEqual(call.kind, "launch")
        self.assertEqual((call.request.role, call.request.model, call.request.effort), (chat.ROLE, "opus", "high"))
        self.assertTrue(call.request.prompt.startswith("/wayline\n"), call.request.prompt)
        self.assertIn("research/ACCOUNT.md", call.request.prompt)
        self.assertTrue(call.request.prompt.rstrip().endswith("How does it stand?"))
        self.assertEqual(call.request.cwd, self.project.resolve())
        self.assertEqual((record["status"], record["reply"], record["session_id"], record["resumed"]),
                         ("answered", "Two decisions wait on you.", "s-1", False))


class ResumeTest(ChatCase):
    def test_a_message_under_an_hour_after_the_last_reply_resumes_its_session(self):
        self.script(reply("First.", session="s-1"), reply("Second.", session="s-1"))
        first = self.say("How does it stand?", now=T0)
        second = self.say("And O2?", now=T0 + chat.RESUME_S - 1)
        launch, resumed = self.fake.calls
        self.assertEqual((resumed.kind, resumed.session_id), ("resume", "s-1"))
        self.assertTrue(resumed.message.rstrip().endswith("And O2?"))
        self.assertNotIn("/wayline", resumed.message)
        self.assertEqual(resumed.run_dir.parent, launch.run_dir, "a resume writes beside the session it resumes")
        self.assertEqual((second["status"], second["reply"], second["resumed"]), ("answered", "Second.", True))
        self.assertEqual(first["run_dir"], second["run_dir"])

    def test_a_message_an_hour_or_more_after_the_last_reply_starts_fresh_from_the_digest_and_the_last_exchanges(self):
        self.script(reply("First.", session="s-1"), reply("Fresh.", session="s-2"))
        self.say("How does it stand?", now=T0)
        later = self.say("What changed?", now=T0 + chat.RESUME_S)
        _first, fresh = self.fake.calls
        self.assertEqual(fresh.kind, "launch")
        self.assertTrue(fresh.request.prompt.startswith("/wayline\n"))
        self.assertIn("How does it stand?", fresh.request.prompt, "the last exchanges travel into a fresh session")
        self.assertIn("First.", fresh.request.prompt)
        self.assertEqual((later["session_id"], later["resumed"]), ("s-2", False))

    def test_a_session_that_cannot_be_resumed_is_started_fresh(self):
        self.script(reply("First.", session="s-1"),
                    Envelope(session_id="s-1", is_error=True, subtype="error_during_execution", errors=["No conversation found"]),
                    reply("Fresh.", session="s-3"))
        self.say("How does it stand?", now=T0)
        second = self.say("And O2?", now=T0 + 60)
        self.assertEqual([call.kind for call in self.fake.calls], ["launch", "resume", "launch"])
        self.assertEqual((second["status"], second["reply"], second["resumed"]), ("answered", "Fresh.", False))

    def test_a_resumed_session_that_took_turns_and_then_failed_is_not_run_again(self):
        # It may have recorded what the owner said before it failed; a fresh session would record it twice.
        self.script(reply("First.", session="s-1"),
                    Envelope(session_id="s-1", is_error=True, subtype="error_max_turns", errors=["max turns"], answered=True))
        self.say("How does it stand?", now=T0)
        second = self.say("Add an objective: does depth help?", now=T0 + 60)
        self.assertEqual([call.kind for call in self.fake.calls], ["launch", "resume"])
        self.assertEqual(second["status"], "failed")

    def test_a_resume_the_launcher_refuses_is_started_fresh_with_no_failure_left_on_the_message(self):
        self.script(reply("First.", session="s-1"), reply("Fresh.", session="s-2"))
        self.say("How does it stand?", now=T0)
        with mock.patch.object(worker, "resume", side_effect=worker.LaunchError("the session's directory is gone")):
            second = self.say("And O2?", now=T0 + 60)
        self.assertEqual((second["status"], second["reply"], second["errors"]), ("answered", "Fresh.", []))


class QueueTest(ChatCase):
    def test_messages_queue_in_order_and_one_session_runs_at_a_time(self):
        self.script(reply("To the first."), reply("To the second."))
        first = chat.post(self.project, "First message.", now=T0)
        second = chat.post(self.project, "Second message.", now=T0)
        self.assertEqual([record["status"] for record in chat.read_messages(self.project)], ["queued", "queued"])
        chat.answer_queued(self.project, now=T0)
        self.assertEqual([call.request.prompt.rstrip().splitlines()[-1] if call.kind == "launch" else call.message.rstrip()
                          for call in self.fake.calls], ["First message.", "Second message."])
        self.assertEqual(self.fake.peak, 1)
        self.assertEqual([chat.read_message(self.project, record["id"])["reply"] for record in (first, second)],
                         ["To the first.", "To the second."])

    def test_a_message_still_running_holds_the_queue(self):
        chat.post(self.project, "First.", now=T0)
        chat.post(self.project, "Second.", now=T0)
        [held] = [record for record in chat.read_messages(self.project) if record["id"] == 1]
        held["status"] = "running"
        (self.project / "research" / "chat" / "1.json").write_text(json.dumps(held), encoding="utf-8")
        self.assertEqual(chat.answer_queued(self.project, now=T0), [])
        self.assertEqual(self.fake.calls, [])

    def test_the_conversation_is_kept_under_the_project_and_gitignored(self):
        from wayline.project import GITIGNORE_ENTRIES
        self.script(reply())
        record = self.say("Hello.")
        self.assertTrue((self.project / "research" / "chat" / ("%d.json" % record["id"])).is_file())
        self.assertIn("research/chat/", GITIGNORE_ENTRIES)
        self.assertTrue(record["run_dir"].startswith("research/chat/sessions/"))


class HiddenViewTest(ChatCase):
    def test_the_view_and_item_travel_with_the_message_into_the_session_and_not_into_its_text(self):
        self.script(reply("Dropped R1.2 from its report."))
        record = self.say("drop this one", view="research", item="R1.2")
        [call] = self.fake.calls
        self.assertIn("[In the dashboard the owner is looking at the Research view, with R1.2 open.]\ndrop this one", call.request.prompt)
        self.assertEqual((record["text"], record["view"], record["item"]), ("drop this one", "research", "R1.2"))

    def test_a_view_or_item_the_dashboard_has_not_is_refused(self):
        with self.assertRaises(chat.ChatError):
            chat.post(self.project, "hi", view="settings")
        with self.assertRaises(chat.ChatError):
            chat.post(self.project, "hi", item="../../etc")
        with self.assertRaises(chat.ChatError):
            chat.post(self.project, "   ")


class LaunchRequestTest(ChatCase):
    def request(self):
        self.script(reply())
        self.say("How does it stand?")
        [call] = self.fake.calls
        return call.request

    def test_a_chat_session_gets_read_tools_and_only_the_routed_verbs_under_dont_ask(self):
        request = self.request()
        bash = [tool for tool in request.allowed_tools if tool.startswith("Bash(")]
        reads = [tool for tool in request.allowed_tools if not tool.startswith("Bash(")]
        self.assertEqual(reads[:3], ["Read(./**)", "Grep(./**)", "Glob(./**)"], "read tools on the project")
        skill = "/%s/**" % (HARNESS_ROOT / "skills" / "wayline").resolve()
        self.assertEqual(reads[3:], ["Read(%s)" % skill, "Grep(%s)" % skill, "Glob(%s)" % skill], "and on the skill's own files")
        self.assertTrue(bash and all(tool.startswith("Bash(wayline ") and tool.endswith(":*)") for tool in bash), bash)
        for verb in ("status", "objective add", "answer", "mark", "passage add --section", "ticket add", "switch --autonomy", "intake"):
            self.assertIn("Bash(wayline %s:*)" % verb, request.allowed_tools)
        for tool in ("Edit", "Write", "NotebookEdit", "WebFetch", "WebSearch", "mcp__*", "Agent"):
            self.assertNotIn(tool, request.allowed_tools)
            self.assertIn(tool, request.disallowed_tools)
        self.assertNotIn("Bash", request.allowed_tools, "no shell beyond the routed verbs")
        self.assertEqual(request.agent_json[chat.ROLE]["permissionMode"], "dontAsk")
        self.assertEqual(request.env[chat.CHAT_ENV], "1")
        self.assertEqual(request.schema_path.name, "chat_reply.json")

    def test_no_confirmed_verb_is_allowed_and_each_is_denied_by_name(self):
        request = self.request()
        for verb in ("paper --venue", "consolidate", "run --detach", "switch --stop-when", "switch --budget", "promote skill"):
            with self.subTest(verb=verb):
                self.assertNotIn("Bash(wayline %s:*)" % verb, request.allowed_tools)
                self.assertIn("Bash(wayline %s:*)" % verb, request.disallowed_tools)

    def test_the_rung_is_harness_jsons_chat_setting(self):
        self.harness(chat={"model": "sonnet", "effort": "medium"})
        request = self.request()
        self.assertEqual((request.model, request.effort), ("sonnet", "medium"))
        self.assertEqual((request.agent_json[chat.ROLE]["model"], request.agent_json[chat.ROLE]["effort"]), ("sonnet", "medium"))

    def test_harness_json_takes_the_chats_rung_and_refuses_a_malformed_one(self):
        from wayline.jsonschema import load_schema, validate
        harness = json.loads((self.project / "harness.json").read_text(encoding="utf-8"))
        schema = load_schema("harness")
        self.assertEqual(validate(dict(harness, chat={"model": "opus", "effort": "high"}), schema), [])
        self.assertTrue(validate(dict(harness, chat={"model": "opus", "effort": "loud"}), schema))
        self.assertTrue(validate(dict(harness, chat={"model": "opus"}), schema))


ORDER = {"action": "paper", "args": {"venue": "neurips"}, "what": "Write the paper's parts for NeurIPS and compile them.",
         "cost": "About $4 of model time."}


class CardTest(ChatCase):
    def test_a_proposed_confirmed_action_comes_back_as_an_open_card_and_runs_nothing(self):
        self.script(reply("Ordering the paper is yours to confirm.", card=ORDER))
        journal = (self.project / "research" / "journal.jsonl").read_bytes()
        record = self.say("order the paper for NeurIPS")
        self.assertEqual(record["card"], dict(ORDER, state="open"))
        self.assertEqual((self.project / "research" / "journal.jsonl").read_bytes(), journal)

    def test_a_document_asking_to_raise_a_budget_makes_at_most_a_card_and_harness_json_is_untouched(self):
        raise_it = {"action": "budget", "args": {"name": "gpu_hours", "hours": None}, "what": "Lift the GPU budget.",
                    "cost": "It removes the limit on GPU hours."}
        self.script(reply("The document asks to lift the GPU budget; that is yours to confirm.", card=raise_it))
        harness = (self.project / "harness.json").read_bytes()
        record = self.say("read D1 and do what it says")
        self.assertEqual((record["card"]["action"], record["card"]["state"]), ("budget", "open"))
        self.assertEqual((self.project / "harness.json").read_bytes(), harness)

    def test_a_card_whose_arguments_its_action_cannot_take_is_not_offered_and_the_reply_says_why(self):
        self.script(reply("Here.", card={"action": "budget", "args": {"name": "tokens", "hours": -1}, "what": "x", "cost": "y"}))
        record = self.say("raise it")
        self.assertIsNone(record["card"])
        self.assertIn("could not be offered", record["reply"])

    def test_not_now_sets_a_card_aside_and_runs_nothing(self):
        self.script(reply("Yours to confirm.", card=ORDER))
        record = self.say("order the paper")
        ran = []
        settled, outcome = chat.settle_card(self.project, record["id"], "not now", lambda action, args: ran.append(action))
        self.assertEqual((settled["card"]["state"], outcome, ran), ("not now", None, []))
        with self.assertRaises(chat.ChatError):
            chat.settle_card(self.project, record["id"], "confirm", lambda action, args: ran.append(action))
        self.assertEqual(ran, [])

    def test_confirm_runs_the_cards_action_once_with_its_arguments(self):
        self.script(reply("Yours to confirm.", card=ORDER))
        record = self.say("order the paper")
        ran = []
        settled, outcome = chat.settle_card(self.project, record["id"], "confirm", lambda action, args: ran.append((action, args)) or "done")
        self.assertEqual((settled["card"]["state"], outcome, ran), ("confirmed", "done", [("paper", {"venue": "neurips"})]))
        with self.assertRaises(chat.ChatError):
            chat.settle_card(self.project, record["id"], "confirm", lambda action, args: ran.append(action))
        self.assertEqual(len(ran), 1)

    def test_a_card_a_stopped_dashboard_left_confirming_opens_again_saying_so(self):
        self.script(reply("Yours to confirm.", card=ORDER))
        record = self.say("order the paper")
        record["card"]["state"] = "confirming"
        (self.project / "research" / "chat" / ("%d.json" % record["id"])).write_text(json.dumps(record), encoding="utf-8")
        chat.start(self.project)
        card = chat.read_message(self.project, record["id"])["card"]
        self.assertEqual(card["state"], "open")
        self.assertIn("check whether it was done", card["error"])

    def test_an_action_that_refuses_leaves_the_card_open_with_why(self):
        self.script(reply("Yours to confirm.", card=ORDER))
        record = self.say("order the paper")

        def refuse(action, args):
            raise ValueError("no venue named neurips")

        with self.assertRaises(ValueError):
            chat.settle_card(self.project, record["id"], "confirm", refuse)
        card = chat.read_message(self.project, record["id"])["card"]
        self.assertEqual((card["state"], card["error"]), ("open", "no venue named neurips"))


class PacingTest(ChatCase):
    def pause(self, resets_at, window="five_hour"):
        from wayline.ledger import Ledger
        Ledger(self.project).append_event("paused", {"resets_at": resets_at, "window": window, "utilization": 1.0})

    def test_while_a_hit_limit_stands_the_chat_says_it_cannot_answer_and_launches_nothing(self):
        from wayline.pacing import iso
        self.pause(iso(T0 + 3600))
        record = self.say("How does it stand?")
        self.assertEqual(self.fake.calls, [])
        self.assertEqual(record["status"], "refused")
        self.assertIn("cannot answer now", record["reply"])
        self.assertIn("five-hour window", record["reply"])

    def test_a_pause_whose_window_has_reset_no_longer_holds_the_chat(self):
        from wayline.pacing import iso
        self.pause(iso(T0 - 60))
        self.script(reply("Here."))
        self.assertEqual(self.say("How does it stand?")["status"], "answered")

    def test_near_stop_the_chat_answers_and_its_reply_says_so(self):
        from wayline.ledger import Ledger
        Ledger(self.project).append_event("pacing", {"five_hour": 0.95, "seven_day": 0.4, "fable": None, "action": "stop",
                                                     "fable_action": "normal"})
        self.script(reply("Two decisions wait on you."))
        record = self.say("How does it stand?")
        self.assertEqual(record["status"], "answered")
        self.assertTrue(record["reply"].startswith("Two decisions wait on you."))
        self.assertIn("stand at stop", record["reply"])

    def test_a_session_the_limit_refuses_is_answered_with_the_same_line(self):
        from wayline.worker import RateLimitEvent
        self.script(Envelope(session_id="s-1", is_error=True, subtype="error_during_execution", api_error_status=429,
                             rate_limit_events=[RateLimitEvent(status="rejected", resets_at=int(T0 + 600), rate_limit_type="five_hour")],
                             errors=["usage limit reached"]))
        record = self.say("How does it stand?")
        self.assertEqual(record["status"], "refused")
        self.assertIn("cannot answer now", record["reply"])


class CommandGuardTest(ChatCase):
    """Under `WAYLINE_CHAT` the command itself refuses what a chat session may not run, whatever its tool list let through."""

    def test_a_confirmed_verb_is_refused_in_any_spelling_and_nothing_changes(self):
        harness = (self.project / "harness.json").read_bytes()
        for argv in (["switch", "--budget", "gpu_hours=none", "--project", str(self.project)],
                     ["switch", "--project", str(self.project), "--budget=gpu_hours=none"],
                     ["switch", "--autonomy", "autonomous", "--stop-when", "frontier", "--project", str(self.project)],
                     ["paper", "--venue", "neurips", "--project", str(self.project)],
                     ["consolidate", "results", "--yes", "--project", str(self.project)],
                     ["run", "--detach", "--project", str(self.project)]):
            with self.subTest(argv=argv):
                code, said = self.run_verb(*argv)
                self.assertEqual(code, 2)
                self.assertIn("card", said)
        self.assertEqual((self.project / "harness.json").read_bytes(), harness)

    def test_a_verb_acts_on_the_chats_own_project_alone(self):
        other = self.ledger_fixture("another-project")
        code, said = self.run_verb("pause", "--project", str(other))
        self.assertEqual(code, 2)
        self.assertIn("its own project alone", said)
        code, said = self.run_verb("pause")
        self.assertEqual(code, 2, "with no --project a verb acts on the active project, which may be another")
        self.assertIn("--project .", said)

    def test_an_intake_from_the_chat_never_sets_a_budget(self):
        harness = (self.project / "harness.json").read_bytes()
        code, said = self.run_verb("intake", "--intent", "a toy", "--gpu-hours", "9999", "--project", str(self.project))
        self.assertNotEqual(code, 0)
        self.assertIn("card", said)
        self.assertEqual((self.project / "harness.json").read_bytes(), harness)

    def test_a_verb_the_routing_table_does_not_name_is_refused(self):
        code, said = self.run_verb("tick", "--project", str(self.project))
        self.assertEqual(code, 2)
        self.assertIn("no verb the dashboard's chat runs", said)

    def test_a_routed_verb_runs(self):
        code, said = self.run_verb("status", "--project", str(self.project))
        self.assertEqual(code, 0, said)

    def test_making_the_code_repository_public_is_refused_under_the_chat_whatever_carried_it(self):
        from unittest import mock
        from wayline import code_repository
        with mock.patch.dict("os.environ", {chat.CHAT_ENV: "1"}):
            with self.assertRaises(code_repository.CodeRepositoryError) as caught:
                code_repository.make_public(self.project, by="owner", run=lambda *args, **kwargs: self.fail("gh was called"))
        self.assertIn("card", str(caught.exception))


class BatchTest(ChatCase):
    """A batch is shown in the chat as `wayline mark <batch>` prints it, which the session relays, and the first answer in
    either place settles an item for both."""

    def review(self, count):
        from wayline import batches
        items = [{"ref": "D%d" % number, "text": "D%d: the decider chose" % number, "default": "stand"} for number in range(1, count + 1)]
        return batches.open_batch(self.project, "account_review", "Decided for you", items)

    def test_five_items_or_fewer_show_as_text_and_more_as_one_line_with_a_link_to_the_marks_view(self):
        small, large = self.review(5), self.review(6)
        code, said = self.run_verb("mark", small["id"], "--project", str(self.project))
        self.assertEqual(code, 0, said)
        self.assertIn("1. D1", said)
        self.assertIn("5. D5", said)
        code, said = self.run_verb("mark", large["id"], "--project", str(self.project))
        self.assertEqual(code, 0, said)
        self.assertEqual(len(said.strip().splitlines()), 1, said)
        self.assertIn("6 items", said)
        self.assertIn("#/%s/%s" % (self.project.name, large["id"]), said)

    def test_an_item_marked_in_the_chat_is_settled_in_the_marks_view_and_one_marked_there_is_settled_in_the_chat(self):
        from wayline import batches, dashboard_views
        batch = self.review(2)
        code, said = self.run_verb("mark", batch["id"], "1", "reverse", "--project", str(self.project))
        self.assertEqual(code, 0, said)
        [shown] = [held for held in dashboard_views.marks_view(self.project)["batches"] if held["id"] == batch["id"]]
        self.assertEqual((shown["items"][0]["mark"], shown["items"][0]["via"]), ("reverse", "conversation"))
        batches.mark(self.project, batch["id"], 2, "stand", via=batches.DASHBOARD)
        code, said = self.run_verb("mark", batch["id"], "--project", str(self.project))
        self.assertIn("settled: stand, by owner in the dashboard", said)
