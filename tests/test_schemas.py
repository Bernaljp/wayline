"""The shipped schemas and policy.json: the subset, the examples, and the spec's policy table."""

import json
import re
import unittest

from tests.paths import EXAMPLES_DIR, SCHEMAS_DIR, SPEC_PATH
from tests.spec_table import spec_policy_keys
from wayline import POLICY_PATH
from wayline.jsonschema import ValidationError, check, check_schema, load_schema, validate
from wayline.pacing import family
from wayline.project import check_policy, policy_problems

# The schemas this ticket ships; later tickets add the rest of Implementation Decisions 2's list.
SHIPPED = ["journal_event", "ticket", "result", "harness", "policy", "job", "manifest", "decision",
           "dossier", "registry_entry", "l1_record", "code_dossier", "verdict", "guidelines", "inventory", "goal",
           "claim_classes", "report_prose", "figure_request", "figure_result",
           "dossier_entry", "dossier_entry_list", "dossier_sections", "absorb_result", "fixture", "fixture_verdict",
           "dedup_verdict", "spec", "consultant_answer", "plan", "position", "change", "change_list",
           "figure_drafts", "figure_ranking", "figure_finish", "paper_draft", "objectives"]


def load(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


class SchemaFilesTest(unittest.TestCase):
    def test_every_shipped_schema_exists_and_is_in_the_subset(self):
        for name in SHIPPED:
            with self.subTest(schema=name):
                schema = load(SCHEMAS_DIR / (name + ".json"))
                check_schema(schema)
                self.assertEqual(schema["title"], name)
                self.assertIn("description", schema)
                self.assertIs(load_schema(name) is not None, True)

    def test_every_schema_file_is_in_the_subset(self):
        for path in sorted(SCHEMAS_DIR.glob("*.json")):
            with self.subTest(schema=path.name):
                check_schema(load(path))

    def test_every_schema_has_a_valid_and_an_invalid_example(self):
        for name in SHIPPED:
            with self.subTest(schema=name):
                folder = EXAMPLES_DIR / name
                valid = sorted(folder.glob("valid-*.json"))
                invalid = sorted(folder.glob("invalid-*.json"))
                self.assertTrue(valid, "no valid example for %s" % name)
                self.assertTrue(invalid, "no invalid example for %s" % name)

    def test_valid_examples_validate(self):
        for name in SHIPPED:
            schema = load_schema(name)
            for path in sorted((EXAMPLES_DIR / name).glob("valid-*.json")):
                with self.subTest(example=path.name):
                    self.assertEqual(validate(load(path), schema), [])

    def test_invalid_examples_fail_and_name_a_path(self):
        for name in SHIPPED:
            schema = load_schema(name)
            for path in sorted((EXAMPLES_DIR / name).glob("invalid-*.json")):
                with self.subTest(example=path.name):
                    errors = validate(load(path), schema)
                    self.assertTrue(errors, "%s validated but should not" % path.name)
                    self.assertTrue(all(error.path.startswith("$") for error in errors))


class PolicyTest(unittest.TestCase):
    def setUp(self):
        self.policy = load(POLICY_PATH)

    def test_policy_validates_against_its_schema(self):
        check(self.policy, load_schema("policy"), name="policy.json")

    def test_policy_carries_every_key_of_the_spec_table(self):
        keys = spec_policy_keys(SPEC_PATH)
        self.assertGreater(len(keys), 20)
        for dotted in keys:
            with self.subTest(key=dotted):
                node = self.policy
                for part in dotted.split("."):
                    self.assertIn(part, node, "policy.json lacks %s" % dotted)
                    node = node[part]

    def test_initial_values_of_the_spec_table(self):
        policy = self.policy
        self.assertEqual(policy["tiers"], [
            {"model": "haiku", "effort": "medium", "budget": "small"},
            {"model": "sonnet", "effort": "low", "budget": "small"},
            {"model": "sonnet", "effort": "high", "budget": "small"},
            {"model": "opus", "effort": "low", "budget": "medium"},
            {"model": "opus", "effort": "medium", "budget": "medium"},
            {"model": "opus", "effort": "high", "budget": "large"},
        ])
        self.assertEqual(policy["difficulty"], {"1": 2, "2": 3, "3": 5, "4": 6, "5": 6})
        self.assertEqual(policy["budget"]["large"], {"max_turns": 200, "max_minutes": 180})
        self.assertEqual(policy["roles"]["decider"], {"model": "opus", "effort": "max"})
        self.assertEqual(policy["verifier"], {"sonnet": {"model": "opus", "effort": "high"}, "opus": {"model": "opus", "effort": "max"},
                                              "fable": {"model": "opus", "effort": "max"}})
        self.assertEqual(policy["max_parallel_workers"], 2)
        self.assertEqual((policy["poll_seconds"], policy["heartbeat_stale_s"], policy["acceptance_timeout_s"]), (60, 300, 600))
        self.assertEqual(policy["pacing"], {"stop_at": 0.90, "cheap_at": 0.80})
        self.assertEqual(policy["context_pack"]["max_chars"], {"sonnet": 120000, "opus": 200000, "fable": 300000})
        self.assertEqual(policy["escalation"]["raise_after_failures"], 2)
        self.assertEqual(policy["stall"]["waves"], 2)
        self.assertEqual(policy["proposals"]["cap"], {"strict": 0, "moderate": 3, "exploratory": 6})
        self.assertEqual(policy["goal"], {"min_seeds": 3, "margin_sd": 1})
        self.assertEqual(policy["absorb"]["l2_per_phase"], {"P1": 3, "P3": 2, "P5": 2})
        self.assertEqual(policy["consultant"]["max_questions_per_ticket"], 5)
        self.assertEqual(policy["kb"]["query_pack_max_chars"], 20000)
        self.assertEqual(policy["provenance"], {"sample": 0.10, "min": 10, "all_difficulty_5": True})
        self.assertEqual(policy["artifacts"]["commit_threshold_bytes"], 1000000)
        self.assertEqual(policy["reservations"], {"gpu": [], "cores": 8, "ram_gb": 64, "processes": []})
        self.assertEqual(policy["jobs"]["oom_log_tail_bytes"], 65536)
        self.assertEqual(policy["tick"], {"on_calendar": "*:0/15", "login_warning_days": 3})
        self.assertEqual(policy["dashboard"], {"port": 8765, "poll_journal_s": 2, "poll_views_s": 5, "bind": "127.0.0.1"})
        self.assertEqual(policy["fixtures"]["judge"], {"model": "haiku", "effort": "low"})
        self.assertEqual(policy["figures"], {"candidates": {"max": 5}, "margin_threshold": 2, "ssim_min": 0.99, "crops_dpi": 600})
        self.assertEqual(policy["plot_index"], {"crawl_rate_per_s": 1, "liveness": "monthly", "recrawl": "quarterly"})
        self.assertIsNone(policy["quiet_hours"])
        self.assertIsNone(policy["per_window_worker_budget"])

    def test_every_rung_names_a_shipped_budget_and_every_level_a_rung(self):
        for rung in self.policy["tiers"]:
            self.assertIn(rung["budget"], self.policy["budget"])
        for level, rung in self.policy["difficulty"].items():
            self.assertTrue(1 <= rung <= len(self.policy["tiers"]), "level %s names rung %s" % (level, rung))
        self.assertEqual(check_policy(self.policy), None)

    def test_the_cap_binds_no_role_and_no_verifier(self):
        """Decision 16: ticket work stops at high; the planner, the decider, and the verifiers stay where decision 14 puts them."""
        self.assertTrue(all(rung["effort"] in ("low", "medium", "high") for rung in self.policy["tiers"]))
        self.assertEqual(self.policy["roles"]["planner"], {"model": "opus", "effort": "xhigh"})
        self.assertEqual(self.policy["roles"]["decider"], {"model": "opus", "effort": "max"})
        self.assertEqual(self.policy["roles"]["writer"], {"model": "opus", "effort": "xhigh"})
        self.assertEqual(self.policy["roles"]["evolver"], {"model": "opus", "effort": "xhigh"})
        self.assertEqual(self.policy["verifier"]["opus"], {"model": "opus", "effort": "max"})
        self.assertEqual(self.policy["verifier"]["fable"], {"model": "opus", "effort": "max"})

    def test_a_rung_above_the_cap_is_refused(self):
        policy = json.loads(json.dumps(self.policy))
        policy["tiers"][5]["effort"] = "xhigh"
        with self.assertRaises(ValidationError) as caught:
            check_policy(policy)
        self.assertIn('  $.tiers[5].effort: "xhigh" is not one of ["low", "medium", "high"]', str(caught.exception))
        self.assertNotIn("$: $", str(caught.exception), "the schema's own path, once")

    def test_the_rung_model_grammar_is_the_launchers(self):
        """The schema's pattern and `pacing.family` accept the same names, so a policy the schema takes launches."""
        pattern = re.compile(load_schema("policy")["$defs"]["rung_model"]["pattern"])
        for name in ("haiku", "sonnet", "opus", "fable", "claude-opus-4-8", "claude-sonnet-5", "claude-haiku-4-5-20251001", "claude-fable-5-1",
                     "gpt-5", "claude-opus", "claude-opus-", "opus-5", "claude-gemini-3", ""):
            with self.subTest(name=name):
                self.assertEqual(bool(pattern.match(name)), family(name) is not None)

    def test_a_rung_model_is_an_alias_or_a_full_version_name(self):
        policy = json.loads(json.dumps(self.policy))
        policy["tiers"][4]["model"] = "claude-opus-4-8"
        self.assertEqual(check_policy(policy), None)
        policy["tiers"][4]["model"] = "gpt-5"
        with self.assertRaises(ValidationError) as caught:
            check_policy(policy)
        self.assertIn("$.tiers[4].model", str(caught.exception))

    def test_the_old_difficulty_shape_is_refused_naming_upgrade(self):
        policy = json.loads(json.dumps(self.policy))
        policy["difficulty"] = {"1": {"model": "sonnet", "effort": "low", "budget": "small"}, "2": 3, "3": 5, "4": 6,
                                "5": {"model": "fable", "effort": "max", "budget": "large"}}
        self.assertEqual(policy_problems(policy), [
            ("$.difficulty", "policy", "policy.difficulty maps levels 1, 5 to a model and an effort, the shape before the rung ladder; "
             "run wayline upgrade, which rewrites it to rungs")])
        with self.assertRaises(ValidationError) as caught:
            check_policy(policy, name="harness.json")
        self.assertIn("wayline upgrade", str(caught.exception))
        self.assertTrue(validate(policy, load_schema("policy")), "the schema refuses the old shape too")

    def test_a_level_naming_a_rung_the_ladder_lacks_is_refused(self):
        policy = json.loads(json.dumps(self.policy))
        policy["difficulty"]["5"] = 9
        self.assertEqual(validate(policy, load_schema("policy")), [], "the schema cannot see the ladder's length")
        self.assertEqual(policy_problems(policy), [
            ("$.difficulty.5", "policy", "policy.difficulty maps level 5 to rung 9, which policy.tiers does not have; the rung ladder has 6 rung(s), 1 to 6")])

    def test_every_refused_example_is_refused_by_check_policy(self):
        """The refusals the schema cannot express have their negative examples beside the schema's, under `refused-`."""
        examples = sorted((EXAMPLES_DIR / "policy").glob("refused-*.json")) + sorted((EXAMPLES_DIR / "policy").glob("invalid-*.json"))
        self.assertTrue(examples)
        for path in examples:
            with self.subTest(example=path.name):
                with self.assertRaises(ValidationError):
                    check_policy(load(path), name=path.name)
        for path in sorted((EXAMPLES_DIR / "policy").glob("valid-*.json")):
            with self.subTest(example=path.name):
                self.assertEqual(check_policy(load(path), name=path.name), None)


if __name__ == "__main__":
    unittest.main()
