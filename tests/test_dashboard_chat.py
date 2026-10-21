"""The dashboard's chat over HTTP (Implementation Decision 17; ticket 114), against a fixture ledger and the fake launcher.

The seam is the server: posting a message (`POST .../chat`, the token in its header), polling the conversation
(`GET .../chat`, which the panel reads every few seconds and which carries what a running session has said so far),
the queue, and a card's Confirm and Not now (`POST .../chat/<n>/card`), which runs the card's action through the
dashboard's `ACTIONS` whitelist. Nothing sleeps: a test waits on the server's own answer with a deadline.
"""

import http.client
import json
import time

from tests.projects import ProjectTestCase
from tests.test_dashboard_views import Answer, Serving
from wayline import chat, worker
from wayline.dashboard import ACTIONS, TOKEN_HEADER
from wayline.worker import Envelope

TOKEN = "a-token-the-chat-acts-with"
DEADLINE_S = 10


def reply(text="Here is where it stands.", card=None, session="s-1"):
    return Envelope(session_id=session, structured_output={"reply": text, "card": card}, answered=True)


class ChatServedCase(Serving, ProjectTestCase):
    def setUp(self):
        super().setUp()
        self.project = self.ledger_fixture()
        self.fake = self.enterContext(worker.use_fake())
        self.serve(token=TOKEN)
        self.addCleanup(self.drain)

    def drain(self):
        """Let a chat thread this test started end before the fake is reset under it."""
        self.fake.release()
        deadline = time.monotonic() + DEADLINE_S
        while chat.busy(self.project) and time.monotonic() < deadline:
            time.sleep(0.01)

    def post(self, path, body, token=TOKEN):
        connection = http.client.HTTPConnection(self.host, self.port, timeout=10)
        headers = {"Content-Type": "application/json"}
        if token is not None:
            headers[TOKEN_HEADER] = token
        try:
            connection.request("POST", "/api/projects/%s%s" % (self.project_id, path), body=json.dumps(body).encode("utf-8"), headers=headers)
            return Answer(connection.getresponse())
        finally:
            connection.close()

    def send(self, text, **fields):
        answer = self.post("/chat", dict(fields, text=text))
        self.assertEqual(answer.status, 202, answer.body)
        return answer.json["message"]

    def thread(self):
        answer = self.api("/chat")
        self.assertEqual(answer.status, 200, answer.body)
        return answer.json

    def until(self, check, what):
        deadline = time.monotonic() + DEADLINE_S
        while time.monotonic() < deadline:
            view = self.thread()
            if check(view):
                return view
            time.sleep(0.01)
        self.fail("the chat never showed %s: %s" % (what, self.thread()))

    def held(self):
        """Wait until the fake holds a session open, so a release ends it rather than arriving before it."""
        deadline = time.monotonic() + DEADLINE_S
        while self.fake.live() < 1:
            if time.monotonic() > deadline:
                self.fail("no session was held")
            time.sleep(0.01)

    def answered(self, number):
        view = self.until(lambda view: any(message["id"] == number and message["status"] not in ("queued", "running")
                                           for message in view["messages"]), "message %d answered" % number)
        return next(message for message in view["messages"] if message["id"] == number)


class PostAndPollTest(ChatServedCase):
    def test_a_message_posted_is_answered_and_its_reply_is_read_by_polling(self):
        self.fake.script(reply("Two decisions wait on you."), role=chat.ROLE)
        sent = self.send("How does it stand?")
        self.assertEqual((sent["text"], sent["status"]), ("How does it stand?", "queued"))
        message = self.answered(sent["id"])
        self.assertEqual((message["status"], message["reply"]), ("answered", "Two decisions wait on you."))
        self.assertEqual(self.thread()["rung"], "opus high")

    def test_the_reply_streams_while_the_session_runs(self):
        self.fake.script(reply("Done."), role=chat.ROLE, delay=DEADLINE_S)
        sent = self.send("How does it stand?")
        view = self.until(lambda view: view["messages"][0]["status"] == "running" and view["messages"][0].get("partial"),
                          "a running message with what it said so far")
        self.assertEqual(view["messages"][0]["partial"], ["Working on it."])
        self.assertTrue(view["busy"])
        self.held()
        self.fake.release()
        self.assertEqual(self.answered(sent["id"])["reply"], "Done.")
        self.assertFalse(self.thread()["busy"])

    def test_a_second_message_queues_behind_the_first_and_is_answered_after_it(self):
        self.fake.script(reply("To the first."), role=chat.ROLE, delay=DEADLINE_S)
        self.fake.script(reply("To the second."), role=chat.ROLE)
        first = self.send("First.")
        self.until(lambda view: view["messages"][0]["status"] == "running", "the first running")
        second = self.send("Second.")
        self.assertEqual([message["status"] for message in self.thread()["messages"]], ["running", "queued"])
        self.held()
        self.fake.release()
        self.assertEqual(self.answered(second["id"])["reply"], "To the second.")
        self.assertEqual(self.answered(first["id"])["reply"], "To the first.")
        self.assertEqual(self.fake.peak, 1)

    def test_the_hidden_view_travels_into_the_session_and_not_into_the_text_shown(self):
        self.fake.script(reply("Dropped it."), role=chat.ROLE)
        sent = self.send("drop this one", view="research", item="R1.2")
        message = self.answered(sent["id"])
        self.assertEqual(message["text"], "drop this one")
        [call] = self.fake.calls
        self.assertIn("the Research view, with R1.2 open", call.request.prompt)

    def test_a_queue_left_by_a_dashboard_that_stopped_is_taken_up_by_the_next_poll(self):
        self.fake.script(reply("Answered after the restart."), role=chat.ROLE)
        left = chat.post(self.project, "Sent before the restart.")
        orphan = chat.post(self.project, "Running when it stopped.")
        record = chat.read_message(self.project, orphan["id"])
        record.update(status="running", pid=999999)
        (self.project / "research" / "chat" / ("%d.json" % orphan["id"])).write_text(json.dumps(record), encoding="utf-8")
        self.fake.alive[999999] = False
        self.assertEqual(self.answered(orphan["id"])["status"], "failed", "a session that ended with no reply is said to have")
        self.assertEqual(self.answered(left["id"])["reply"], "Answered after the restart.")

    def test_an_unchanged_conversation_answers_304(self):
        first = self.api("/chat")
        self.assertEqual(self.api("/chat", {"If-None-Match": first.etag}).status, 304)
        harness = json.loads((self.project / "harness.json").read_text(encoding="utf-8"))
        (self.project / "harness.json").write_text(json.dumps(dict(harness, chat={"model": "sonnet", "effort": "medium"})), encoding="utf-8")
        moved = self.api("/chat", {"If-None-Match": first.etag})
        self.assertEqual((moved.status, moved.json["rung"]), (200, "sonnet medium"), "a changed rung is shown")

    def test_posting_needs_the_token_and_records_nothing_without_it(self):
        answer = self.post("/chat", {"text": "How does it stand?"}, token=None)
        self.assertEqual(answer.status, 403)
        self.assertEqual(self.thread()["messages"], [])

    def test_a_body_the_chat_cannot_take_is_refused_saying_why(self):
        for body in ({}, {"text": "hi", "view": "settings"}, {"text": "hi", "colour": "red"}):
            with self.subTest(body=body):
                answer = self.post("/chat", body)
                self.assertEqual(answer.status, 400, answer.body)
                self.assertFalse(answer.json["ok"])


class CardTest(ChatServedCase):
    CARD = {"action": "stop_when", "args": {"stop_when": "frontier"}, "what": "End the run when no work is left.",
            "cost": "The run may go on longer than the objectives need."}

    def card(self):
        self.fake.script(reply("That is yours to confirm.", card=self.CARD), role=chat.ROLE)
        sent = self.send("stop when the frontier is empty")
        message = self.answered(sent["id"])
        self.assertEqual(message["card"]["state"], "open")
        return message["id"]

    def harness(self):
        return json.loads((self.project / "harness.json").read_text(encoding="utf-8"))

    def test_the_cards_actions_are_dashboard_actions(self):
        for action in chat.CARD_ACTIONS:
            self.assertIn(action, ACTIONS)

    def test_confirm_without_the_token_is_refused_and_runs_nothing(self):
        number = self.card()
        answer = self.post("/chat/%d/card" % number, {"choice": "confirm"}, token=None)
        self.assertEqual(answer.status, 403)
        self.assertNotIn("stop_when", self.harness())
        self.assertEqual(self.thread()["messages"][0]["card"]["state"], "open")

    def test_confirm_with_the_token_runs_the_cards_action_from_the_dashboard(self):
        number = self.card()
        answer = self.post("/chat/%d/card" % number, {"choice": "confirm"})
        self.assertEqual(answer.status, 200, answer.body)
        self.assertEqual(self.harness()["stop_when"], "frontier")
        self.assertEqual(answer.json["message"]["card"]["state"], "confirmed")
        self.assertEqual(answer.json["outcome"]["report"]["to"], "frontier")
        again = self.post("/chat/%d/card" % number, {"choice": "confirm"})
        self.assertEqual(again.status, 400, "a card is confirmed once")

    def test_not_now_sets_the_card_aside_and_runs_nothing(self):
        number = self.card()
        answer = self.post("/chat/%d/card" % number, {"choice": "not now"})
        self.assertEqual(answer.status, 200, answer.body)
        self.assertEqual(answer.json["message"]["card"]["state"], "not now")
        self.assertNotIn("stop_when", self.harness())

    def test_a_consolidation_that_refuses_at_once_says_so_and_leaves_the_card_open(self):
        self.fake.script(reply("Yours to confirm.", card={"action": "consolidate", "args": {"section": "discussion"},
                                                          "what": "Rewrite Discussion's passages into fewer.", "cost": "One writer session."}),
                         role=chat.ROLE)
        sent = self.send("compile the discussion")
        self.answered(sent["id"])
        answer = self.post("/chat/%d/card" % sent["id"], {"choice": "confirm"})
        self.assertEqual(answer.status, 400, answer.body)
        self.assertIn("nothing to consolidate", answer.json["error"])
        card = self.thread()["messages"][0]["card"]
        self.assertEqual(card["state"], "open")
        self.assertIn("nothing to consolidate", card["error"])

    def test_a_message_with_no_card_has_nothing_to_confirm(self):
        self.fake.script(reply("Recorded O3."), role=chat.ROLE)
        sent = self.send("add an objective")
        self.answered(sent["id"])
        self.assertEqual(self.post("/chat/%d/card" % sent["id"], {"choice": "confirm"}).status, 400)
