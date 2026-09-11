"""The journal vocabulary in the ledger module and in the schema agrees with the spec's table."""

import unittest

from tests.paths import SPEC_PATH
from tests.spec_table import spec_journal_vocabulary
from wayline import ledger
from wayline.jsonschema import load_schema


class VocabularyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.events, cls.enums = spec_journal_vocabulary(SPEC_PATH)

    def test_the_spec_table_was_read(self):
        self.assertGreater(len(self.events), 40)
        self.assertEqual(self.events["run_started"], ("resume", "harness_tag", "autonomy", "radius", "pid"))
        self.assertEqual(self.events["unpaused"], ())
        self.assertEqual(self.events["tagged"], ("tag",))
        self.assertEqual(self.events["pinned"], ("tag", "previous"))
        self.assertEqual(self.enums[("run_ended", "reason")], ("frontier_empty", "goal_reached", "stopped", "stall_strict", "switched"))
        self.assertEqual(self.enums[("notified", "channel")], ("notify-send", "hermes", "none"))

    def test_every_event_name_is_a_constant(self):
        for event in self.events:
            with self.subTest(event=event):
                self.assertEqual(getattr(ledger, event.upper()), event)

    def test_every_payload_key_is_a_constant(self):
        keys = sorted({key for payload in self.events.values() for key in payload})
        for key in keys:
            with self.subTest(key=key):
                self.assertEqual(getattr(ledger, "K_" + key.upper()), key)

    def test_the_events_table_matches_the_spec(self):
        self.assertEqual(set(ledger.EVENTS), set(self.events))
        for event, keys in self.events.items():
            with self.subTest(event=event):
                self.assertEqual(ledger.EVENTS[event], keys)

    def test_the_enumerated_values_match_the_spec(self):
        self.assertEqual(ledger.PAYLOAD_ENUMS, self.enums)

    def test_the_schema_enum_matches_the_ledger(self):
        schema = load_schema("journal_event")
        self.assertEqual(schema["properties"]["event"]["enum"], list(ledger.EVENTS))

    def test_no_stray_constants(self):
        """A constant that is not in the spec is drift in the other direction."""
        spec_events = set(self.events)
        spec_keys = {key for payload in self.events.values() for key in payload}
        for name in dir(ledger):
            if name.startswith("K_"):
                self.assertIn(getattr(ledger, name), spec_keys, name)
            elif name.isupper() and isinstance(getattr(ledger, name), str) and name not in ("JOURNAL", "LOCK"):
                self.assertIn(getattr(ledger, name), spec_events, name)


if __name__ == "__main__":
    unittest.main()
