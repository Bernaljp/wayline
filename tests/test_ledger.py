"""The ledger: the lock, atomic writes, appends, the journal record, and two processes appending at once."""

import fcntl
import json
import multiprocessing
import os
import stat
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from wayline import ledger
from wayline.jsonschema import ValidationError
from wayline.ledger import Ledger, LedgerError, make_event

APPENDS_PER_PROCESS = 500
FILLER = "x" * 5000  # longer than a pipe buffer, so interleaving would show without the lock


def append_many(project, label):
    book = Ledger(project)
    for number in range(APPENDS_PER_PROCESS):
        book.append_event(ledger.CONTROL, {"command": "pause", "args": {"n": number, "filler": FILLER}, "by": label})


def try_lock_nonblocking(lock_path, queue):
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        queue.put(False)
        return
    fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)
    queue.put(True)


class LedgerCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name)
        self.book = Ledger(self.project)

    def tearDown(self):
        self.temp.cleanup()


class EventTest(LedgerCase):
    def test_append_event_writes_one_valid_line(self):
        record = self.book.append_event(ledger.RUN_STARTED, {"resume": False, "harness_tag": "v0.0.0", "autonomy": "checkpoints", "radius": "moderate", "pid": 1})
        lines = self.book.journal_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0]), record)
        self.assertEqual(list(record), ["ts", "event", "ticket", "session_id", "job", "payload"])
        self.assertRegex(record["ts"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")

    def test_lock_file_and_research_directory_are_created(self):
        self.book.append_event(ledger.UNPAUSED)
        self.assertTrue(self.book.lock_path.exists())
        self.assertEqual(self.book.lock_path, self.project / "research" / ".lock")

    def test_ticket_session_and_job_fields(self):
        record = self.book.append_event(ledger.TICKET_DONE, {"ticket": 4}, ticket=4, session_id="s-1")
        self.assertEqual((record["ticket"], record["session_id"], record["job"]), (4, "s-1", None))
        record = self.book.append_event(ledger.JOB_FINISHED, {"job": "j1", "exit_code": 0, "seconds": 3.5, "outputs_ok": True}, job="j1")
        self.assertEqual(record["job"], "j1")

    def test_unknown_event_is_refused(self):
        with self.assertRaises(LedgerError) as caught:
            self.book.append_event("ticket_started", {})
        self.assertIn("vocabulary", str(caught.exception))
        self.assertFalse(self.book.journal_path.exists())

    def test_unknown_payload_key_is_refused(self):
        with self.assertRaises(LedgerError) as caught:
            make_event(ledger.TICKET_DONE, {"ticket": 1, "commit": "abc"})
        self.assertIn("commit", str(caught.exception))

    def test_enumerated_value_is_checked(self):
        with self.assertRaises(LedgerError) as caught:
            make_event(ledger.RUN_ENDED, {"reason": "frontier-empty"})
        self.assertIn("frontier_empty", str(caught.exception))
        make_event(ledger.RUN_ENDED, {"reason": "frontier_empty"})
        make_event(ledger.NOTIFIED, {"event": "paused", "channel": "notify-send", "ok": True})
        make_event(ledger.PROPOSAL_PARKED, {"id": "p1", "reason": "cap"})

    def test_envelope_is_validated_against_the_schema(self):
        with self.assertRaises(ValidationError):
            make_event(ledger.TICKET_DONE, {"ticket": 1}, ticket="one")
        with self.assertRaises(ValidationError):
            make_event(ledger.TICKET_DONE, {"ticket": 1}, ts="yesterday")

    def test_explicit_timestamp_is_kept(self):
        record = make_event(ledger.UNPAUSED, ts="2026-09-12T00:00:00Z")
        self.assertEqual(record["ts"], "2026-09-12T00:00:00Z")

    def test_read_events_by_byte_offset(self):
        self.assertEqual(self.book.read_events(), ([], 0))
        first = self.book.append_event(ledger.UNPAUSED)
        events, offset = self.book.read_events()
        self.assertEqual(events, [first])
        self.assertEqual(offset, self.book.journal_path.stat().st_size)
        second = self.book.append_event(ledger.PHASE, {"from": "P0", "to": "P1"})
        events, offset2 = self.book.read_events(offset)
        self.assertEqual(events, [second])
        self.assertEqual(self.book.read_events(offset2), ([], offset2))

    def test_read_events_leaves_a_partial_line_alone(self):
        self.book.append_event(ledger.UNPAUSED)
        with open(self.book.journal_path, "a", encoding="utf-8") as handle:
            handle.write('{"ts": "2026-09-12T00:00:00Z", "event": "unpaused"')
        events, offset = self.book.read_events()
        self.assertEqual(len(events), 1)
        self.assertLess(offset, self.book.journal_path.stat().st_size)


class WriteTest(LedgerCase):
    def test_write_json_is_atomic_and_leaves_no_temp_file(self):
        target = self.book.write_json("conductor.json", {"pid": 1, "started_at": "x"})
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"pid": 1, "started_at": "x"})
        self.assertEqual([p.name for p in self.book.research.iterdir() if p.name.endswith(".tmp")], [])
        self.book.write_json("conductor.json", {"pid": 2})
        self.assertEqual(self.book.read_json("conductor.json"), {"pid": 2})

    def test_write_json_validates_against_a_shipped_schema(self):
        with self.assertRaises(ValidationError):
            self.book.write_json("manifest.json", {"entries": [{"path": "x"}]}, schema="manifest")
        self.assertFalse((self.book.research / "manifest.json").exists())
        self.book.write_json("manifest.json", {"entries": []}, schema="manifest")
        self.assertEqual(self.book.read_json("manifest.json"), {"entries": []})

    def test_write_json_creates_nested_directories(self):
        target = self.book.write_json("jobs/j1.json", {"id": "j1"})
        self.assertEqual(target, self.book.research / "jobs" / "j1.json")
        self.assertTrue(target.exists())

    def test_write_markdown(self):
        target = self.book.write_markdown("REPORT.md", "# Report\n\nText")
        self.assertEqual(target.read_text(encoding="utf-8"), "# Report\n\nText\n")
        self.assertEqual([p.name for p in self.book.research.iterdir() if p.name.endswith(".tmp")], [])

    def test_append_line(self):
        self.book.append_line("findings.jsonl", '{"id": 1}')
        self.book.append_line("findings.jsonl", '{"id": 2}')
        self.assertEqual((self.book.research / "findings.jsonl").read_text(encoding="utf-8"), '{"id": 1}\n{"id": 2}\n')
        with self.assertRaises(LedgerError):
            self.book.append_line("findings.jsonl", "two\nlines")

    def test_paths_stay_under_research(self):
        for bad in ["/etc/passwd", "../CLAUDE.md", "refs/../../x", ""]:
            with self.subTest(path=bad):
                with self.assertRaises(LedgerError):
                    self.book.write_markdown(bad, "x")

    def test_failed_write_leaves_the_old_file_and_no_temp(self):
        self.book.write_json("a.json", {"v": 1})

        def refuse(source, target):
            raise OSError("disk went away")

        with mock.patch.object(ledger.os, "replace", refuse):
            with self.assertRaises(OSError):
                self.book.write_json("a.json", {"v": 2})
        self.assertEqual(self.book.read_json("a.json"), {"v": 1})
        self.assertEqual([p.name for p in self.book.research.iterdir() if p.name.endswith(".tmp")], [])

    def test_values_that_are_not_json_are_refused(self):
        with self.assertRaises(LedgerError):
            self.book.write_json("a.json", {"v": object()})
        for bad in [float("nan"), float("inf"), float("-inf")]:
            with self.subTest(value=bad):
                with self.assertRaises(LedgerError):
                    self.book.write_json("a.json", {"v": bad})
                with self.assertRaises((LedgerError, ValidationError)):
                    self.book.append_event(ledger.PROGRESS, {"metric": "m", "value": bad})
        self.assertFalse((self.book.research / "a.json").exists())
        self.assertFalse(self.book.journal_path.exists())

    def test_rewrite_keeps_the_file_mode_and_a_new_file_gets_the_umask(self):
        old_umask = os.umask(0o022)
        try:
            target = self.book.write_json("wide.json", {"v": 1})
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o644)
            os.chmod(target, 0o600)
            self.book.write_json("wide.json", {"v": 2})
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
            lines = self.book.append_line("lines.jsonl", "{}")
            self.assertEqual(stat.S_IMODE(lines.stat().st_mode), 0o644)
        finally:
            os.umask(old_umask)

    def test_a_symlink_cannot_lead_a_write_outside_research(self):
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        self.book.research.mkdir(parents=True, exist_ok=True)
        os.symlink(outside, self.book.research / "out")
        with self.assertRaises(LedgerError):
            self.book.write_json("out/escaped.json", {"v": 1})
        with self.assertRaises(LedgerError):
            self.book.append_line("out/escaped.jsonl", "{}")
        self.assertEqual(list(outside.iterdir()), [])

    def test_a_relative_project_path_becomes_absolute(self):
        cwd = os.getcwd()
        os.chdir(self.temp.name)
        try:
            book = Ledger("proj")
        finally:
            os.chdir(cwd)
        self.assertTrue(book.research.is_absolute())
        self.assertEqual(book.research, (Path(self.temp.name) / "proj" / "research").resolve())

    def test_the_lock_and_the_journal_are_not_targets_of_a_rename(self):
        with self.assertRaises(LedgerError):
            self.book.write_json(".lock", {})
        with self.assertRaises(LedgerError):
            self.book.append_line(".lock", "x")
        with self.assertRaises(LedgerError):
            self.book.write_markdown("journal.jsonl", "not json")
        with self.assertRaises(LedgerError):
            self.book.write_json("journal.jsonl", [])

    def test_line_breaking_characters_never_reach_a_line_file_raw(self):
        for char in ["\n", "\r", " ", " ", "\x85", "\x0c"]:
            with self.subTest(char="U+%04X" % ord(char)):
                with self.assertRaises(LedgerError):
                    self.book.append_line("findings.jsonl", "a%sb" % char)
        record = self.book.append_event(ledger.TICKET_NEEDS_HUMAN, {"ticket": 1, "question": "line sep\x85nel\r\n?"}, ticket=1)
        raw = self.book.journal_path.read_bytes()
        self.assertEqual(raw.count(b"\n"), 1)
        for char in [" ", "\x85", "\r"]:
            self.assertNotIn(char.encode("utf-8"), raw)
        events, _ = self.book.read_events()
        self.assertEqual(events, [record])

    def test_a_torn_tail_is_closed_and_skipped(self):
        first = self.book.append_event(ledger.UNPAUSED)
        with open(self.book.journal_path, "ab") as handle:
            handle.write(b'{"ts": "2026-09-12T00:00:00Z", "event": "unpau')
        with self.assertLogs("wayline.ledger", level="WARNING"):
            second = self.book.append_event(ledger.PHASE, {"from": "P0", "to": "P1"})
        lines = self.book.journal_path.read_bytes().split(b"\n")
        self.assertEqual(len(lines), 4)  # first, torn, second, and the empty tail
        self.assertEqual(json.loads(lines[2]), second)
        with self.assertLogs("wayline.ledger", level="WARNING"):
            events, offset = self.book.read_events()
        self.assertEqual(events, [first, second])
        self.assertEqual(offset, self.book.journal_path.stat().st_size)


class LockTest(LedgerCase):
    def test_two_ledgers_of_one_project_share_the_lock_in_one_process(self):
        other = Ledger(self.project)
        with self.book.lock():
            other.write_json("shared.json", {"v": 1})  # would deadlock on a second flock descriptor
            with other.lock():
                self.book.append_event(ledger.UNPAUSED)
        self.assertEqual(other.read_json("shared.json"), {"v": 1})

    def test_another_thread_waits_for_the_lock(self):
        held = threading.Event()
        release = threading.Event()
        entered = []

        def holder():
            with self.book.lock():
                held.set()
                release.wait(60)

        def contender():
            with self.book.lock():
                entered.append(True)

        first = threading.Thread(target=holder)
        first.start()
        self.assertTrue(held.wait(60))
        second = threading.Thread(target=contender)
        second.start()
        state = ledger._process_lock(self.book.lock_path)
        self.assertFalse(state.mutex.acquire(blocking=False), "a second thread could enter the critical section")
        self.assertEqual(entered, [])
        release.set()
        first.join(60)
        second.join(60)
        self.assertEqual(entered, [True])

    def test_timestamps_follow_file_order(self):
        for _ in range(50):
            self.book.append_event(ledger.UNPAUSED)
        events, _ = self.book.read_events()
        stamps = [event["ts"] for event in events]
        self.assertEqual(stamps, sorted(stamps))

    def test_lock_is_flock_on_research_lock_and_reentrant(self):
        context = multiprocessing.get_context("fork")
        queue = context.Queue()
        with self.book.lock():
            with self.book.lock():  # re-entrant in one process
                child = context.Process(target=try_lock_nonblocking, args=(str(self.book.lock_path), queue))
                child.start()
                child.join(60)
                self.assertFalse(queue.get(timeout=60), "another process took the lock while the ledger held it")
            child = context.Process(target=try_lock_nonblocking, args=(str(self.book.lock_path), queue))
            child.start()
            child.join(60)
            self.assertFalse(queue.get(timeout=60), "the lock was released by the inner block")
        child = context.Process(target=try_lock_nonblocking, args=(str(self.book.lock_path), queue))
        child.start()
        child.join(60)
        self.assertTrue(queue.get(timeout=60), "the lock was not released")

    def test_two_processes_appending_500_events_each_lose_and_interleave_nothing(self):
        context = multiprocessing.get_context("fork")
        workers = [context.Process(target=append_many, args=(str(self.project), label)) for label in ("a", "b")]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(120)
            self.assertEqual(worker.exitcode, 0)
        raw = self.book.journal_path.read_bytes()
        self.assertTrue(raw.endswith(b"\n"))
        lines = raw.decode("utf-8").split("\n")[:-1]
        self.assertEqual(len(lines), 2 * APPENDS_PER_PROCESS)
        seen = {"a": set(), "b": set()}
        for line in lines:
            record = json.loads(line)  # a torn line would not parse
            self.assertEqual(record["event"], "control")
            self.assertEqual(record["payload"]["args"]["filler"], FILLER)
            seen[record["payload"]["by"]].add(record["payload"]["args"]["n"])
        self.assertEqual(seen["a"], set(range(APPENDS_PER_PROCESS)))
        self.assertEqual(seen["b"], set(range(APPENDS_PER_PROCESS)))
        events, offset = self.book.read_events()
        self.assertEqual(len(events), 2 * APPENDS_PER_PROCESS)
        self.assertEqual(offset, len(raw))


if __name__ == "__main__":
    unittest.main()
