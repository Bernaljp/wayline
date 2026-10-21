"""The owner-facing skill `wayline` (Implementation Decision 17, talking with the project; decision 10; ticket 109).

One skill routes everything the owner says in a session in the project: its body is the routing table, and its
reference files hold the procedures (setup, evolve). The five phase skills retired into it, `wayline-interval-claims`
stays, and no skill names another skill to call. What is checked here is the tree as it ships: its shape, the routing
table against the verb table of decision 1 and the CLI, the rules the session follows, and the setup's ten questions
in their order.
"""

import json
import re
import unittest

from tests.paths import HARNESS_ROOT, SPEC_PATH
from tests.spec_table import spec_verbs
from wayline import cli, conversation, registry
from wayline.frontmatter import load_document

SKILLS = HARNESS_ROOT / "skills"
SKILL = SKILLS / "wayline"
RETIRED = ("wayline-intake", "wayline-grill", "wayline-plan", "wayline-evolve", "wayline-paper")

# The verbs the tickets before this one planned for the conversation, which the routing table uses (ticket 109).
PLANNED = ("objective add", "mark", "document add", "passage add", "consolidate", "review", "result merge",
           "result rename", "specify --amend", "outline", "reference", "ticket add")

# Setup's ten questions, in the order decision 17 settles them.
SETUP_ORDER = ("documents", "objectives", "concerns", "missing material", "stopping rule and budgets", "software",
               "code repository", "paper order", "front matter", "references")


def text(path):
    return path.read_text(encoding="utf-8")


def flat(path):
    return " ".join(text(path).split())


def commands(body):
    """Every `wayline <verb> ...` command a text names in backticks or in a fenced block, as the words after `wayline`."""
    found = re.findall(r"`wayline ([^`]+)`", body)
    for block in re.findall(r"```(?:bash)?\n(.*?)```", body, re.S):
        found += [line.strip()[len("wayline "):] for line in block.splitlines() if line.strip().startswith("wayline ")]
    return found


class TreeTest(unittest.TestCase):
    def test_the_skill_is_a_routing_table_with_reference_files_for_setup_and_evolve(self):
        frontmatter, body = load_document(text(SKILL / "SKILL.md"))
        self.assertEqual(frontmatter["name"], "wayline")
        self.assertIn("talks", frontmatter["description"])
        self.assertIn("## Routing", body)
        for name in ("setup.md", "evolve.md", "paper.md"):
            self.assertTrue((SKILL / name).is_file(), name)
        sidecar = registry.read_sidecar(SKILL / "wayline.json", "skill", expect_id="wayline")
        self.assertEqual(sidecar["applicability_tags"]["kinds"], [], "no ticket kind is assigned the owner's skill")

    def test_the_five_phase_skills_are_retired_and_interval_claims_stays(self):
        for name in RETIRED:
            self.assertFalse((SKILLS / name).exists(), name)
        self.assertTrue((SKILLS / "wayline-interval-claims" / "SKILL.md").is_file())
        self.assertEqual(sorted(path.name for path in SKILLS.iterdir() if path.is_dir()), ["wayline", "wayline-interval-claims"])

    def test_no_skill_names_another_skill_to_call(self):
        names = [path.name for path in SKILLS.iterdir() if path.is_dir()]
        for directory in SKILLS.iterdir():
            if not directory.is_dir():
                continue
            for path in directory.glob("*.md"):
                body = text(path)
                with self.subTest(file=str(path.relative_to(HARNESS_ROOT))):
                    self.assertNotRegex(body, r"(?<![\w.-])/wayline", "a slash command calls a skill")
                    for other in names:
                        if other != directory.name:
                            self.assertNotRegex(body, r"(?<![\w/.-])%s(?![\w-])" % re.escape(other), "names the skill %s" % other)
                    self.assertNotRegex(body, r"(?i)\b(use|load|call|invoke|run) the [`\w-]+ skill\b")

    def test_the_skills_readme_names_only_the_skills_that_ship(self):
        readme = text(SKILLS / "README.md")
        for name in RETIRED:
            self.assertNotIn(name, readme)
        self.assertIn("`wayline`", readme)
        self.assertIn("wayline-interval-claims", readme)

    def test_the_registry_lists_the_owners_skill_and_never_assigns_it(self):
        entries = {entry["id"]: entry for entry in registry.build(None, harness_root=HARNESS_ROOT, pre_check=False)["entries"]
                   if entry["kind"] == "skill"}
        self.assertEqual(sorted(entries), ["interval-claims", "wayline"])
        self.assertFalse(entries["wayline"]["assignable"])
        self.assertIn("owner", " ".join(entries["wayline"]["problems"]))
        self.assertNotIn("no ticket can reach", " ".join(entries["wayline"]["problems"]))
        self.assertTrue(entries["interval-claims"]["assignable"])


class RoutingTest(unittest.TestCase):
    """The routing table names only the verbs the conversation may run, and each is a CLI verb that exists."""

    def setUp(self):
        self.rows = conversation.routing_table()
        self.routed = conversation.routed_commands()

    def test_the_table_has_rows_with_a_rule_each(self):
        self.assertGreater(len(self.rows), 15)
        for row in self.rows:
            with self.subTest(row=row["owner"]):
                self.assertIn(row["rule"], conversation.RULES)
                self.assertTrue(row["commands"], "a row names the verb it routes to")

    def test_every_routed_verb_is_a_built_verb_of_the_spec_table(self):
        table = set(spec_verbs(SPEC_PATH))
        for command in self.routed:
            words = command.split()
            verb = cli.lookup(words[0])
            with self.subTest(command=command):
                self.assertIn(words[0], table, "not in decision 1's verb table")
                self.assertIsNotNone(verb, "no such CLI verb")
                self.assertIsNotNone(verb.handler, "the verb is not built")
                for word in words[1:]:
                    self.assertIn(word.split("=")[0], verb.usage, "%s is not a form of wayline %s" % (word, words[0]))

    def test_the_planned_names_are_routed(self):
        for name in PLANNED:
            with self.subTest(verb=name):
                self.assertTrue(any(command == name or command.startswith(name + " ") for command in self.routed), name)

    def test_every_command_the_skill_and_its_references_run_is_routed(self):
        for path in sorted(SKILL.glob("*.md")):
            for command in commands(text(path)):
                words = [word for word in command.split() if not word.startswith(("<", '"', "'"))]
                with self.subTest(file=path.name, command=command):
                    self.assertTrue(any(" ".join(words).startswith(routed) for routed in self.routed),
                                    "`wayline %s` runs a verb the routing table does not name" % command)

    def test_a_pipe_inside_a_backticked_command_is_no_cell_border(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            skill = Path(folder) / "skills" / "wayline"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text(
                "# x\n\n## Routing\n\n| The owner | Rule | Verbs |\n|---|---|---|\n"
                "| sets the consent | record | `wayline switch --fallback auto|ask`, `wayline status` |\n"
                "| says a\\|b | read | `wayline status` |\n", encoding="utf-8")
            rows = conversation.routing_table(folder)
        self.assertEqual([(row["rule"], row["commands"]) for row in rows],
                         [("record", ["switch --fallback auto|ask", "status"]), ("read", ["status"])])

    def test_the_drafted_ticket_and_the_irreversible_ones_take_their_rules(self):
        rules = {}
        for row in self.rows:
            for command in row["commands"]:
                rules.setdefault(command, set()).add(row["rule"])
        self.assertIn("record", rules["ticket add"])
        self.assertEqual(rules["consolidate"], {"confirm"})
        self.assertIn("confirm", rules["paper --yes"])
        self.assertIn("confirm", rules["paper"])
        self.assertEqual(rules["paper front -"], {"record"})
        self.assertEqual(rules["promote skill"], {"confirm"})


class RulesTest(unittest.TestCase):
    """The rules the session follows, as the SKILL.md body states them."""

    @classmethod
    def setUpClass(cls):
        cls.body = flat(SKILL / "SKILL.md")

    def test_records_without_asking_and_reads_back_one_line_with_the_id(self):
        self.assertIn("## Record without asking", text(SKILL / "SKILL.md"))
        for words in ("materials", "references", "documents", "objectives and goals", "the owner's passages",
                      "answers to waiting decision tickets", "the owner's words as the rationale", "merges and renames of results",
                      "a reference handed over", "harness feedback", "requests for work"):
            self.assertIn(words, self.body)
        self.assertIn("one line with its id", self.body)

    def test_asks_one_line_only_when_unclear(self):
        self.assertIn("## Ask one line", text(SKILL / "SKILL.md"))
        for words in ("objective, goal, or remark", "which section", "which decision ticket", "project or harness",
                      "consolidation or paper order", "a document's kind"):
            self.assertIn(words, self.body)

    def test_confirms_first_with_what_happens_and_what_it_costs(self):
        self.assertIn("## Confirm first", text(SKILL / "SKILL.md"))
        for words in ("what will happen and what it costs", "paper order", "consolidation", "irreversible list",
                      "A human-only class the owner states needs no confirmation"):
            self.assertIn(words, self.body)

    def test_never_does_the_research_and_nothing_lives_only_in_the_conversation(self):
        for words in ("never does the research", "digests code renders", "one ticket", "`wayline ticket add`",
                      "specify --amend", "consultant", "Nothing lives only in the conversation"):
            self.assertIn(words, self.body)

    def test_a_batch_of_more_than_five_is_one_line_with_its_count_and_a_link(self):
        self.assertIn("five items or fewer", self.body)
        self.assertIn("one line with the count and a link to the marks view", self.body)

    def test_under_autonomous_the_conversation_opens_with_decided_for_you(self):
        self.assertIn('"Decided for you" as one numbered item', self.body)
        self.assertIn('"let them stand"', self.body)
        self.assertIn("`wayline review all stand --shown <ids>`", self.body)

    def test_compile_is_read_by_what_it_is_said_of(self):
        self.assertIn('"compile"', self.body)

    def test_no_unit_is_installed_for_remote_control(self):
        for path in (HARNESS_ROOT / "wayline").glob("*.py"):
            with self.subTest(module=path.name):
                self.assertNotIn("remote-control", text(path))
        self.assertIn("claude remote-control", self.body)
        self.assertIn("user guide", self.body)


class SetupTest(unittest.TestCase):
    """The setup reference asks the ten questions in order, each as one question."""

    @classmethod
    def setUpClass(cls):
        cls.text = text(SKILL / "setup.md")
        cls.body = " ".join(cls.text.split())

    def test_the_ten_questions_are_headed_in_order(self):
        headings = re.findall(r"^## Setup (\d+)/10: (.+)$", self.text, re.M)
        self.assertEqual([int(number) for number, _ in headings], list(range(1, 11)))
        for (number, title), expected in zip(headings, SETUP_ORDER):
            self.assertIn(expected, title.lower(), "question %s" % number)

    def test_intakes_settings_come_first_with_objective_and_concern_among_the_human_only_classes(self):
        before = self.text[:self.text.index("## Setup 1/10")]
        for words in ("autonomy", "radius", "model_fallback", "ladder_changes", "human_only"):
            self.assertIn(words, before)
        self.assertRegex(" ".join(before.split()), r"`objective`.*`concern`")

    def test_each_question_is_one_question_and_the_front_matter_alone_may_be_left_for_later(self):
        self.assertIn("one batch", self.body)
        for words in ("one question per proposed objective with its concerns, one for the order, and one for the declines",
                      "in one question"):
            self.assertIn(words, self.body)
        self.assertIn("may be left for later", self.body)
        self.assertIn("setup ends only when every question is answered", self.body)
        self.assertIn("nothing about any of these is asked after setup", self.body)

    def test_the_graphs_confirmation_comes_after_the_last_question(self):
        cut = self.text.index("wayline plan --cut-only")
        self.assertLess(self.text.index("## Setup 5/10"), cut)
        self.assertLess(cut, self.text.index("## Setup 6/10"))
        self.assertLess(self.text.index("## Setup 10/10"), self.text.index("## Ending setup"))

    def test_setup_reads_the_references_105_built_for_it(self):
        self.assertIn("reference --project .", commands(self.text))
        self.assertIn("still retrying", self.body)


class EvolveTest(unittest.TestCase):
    def test_the_evolve_reference_files_feedback_and_runs_the_loop(self):
        ran = [" ".join(command.split()[:2]) for command in commands(text(SKILL / "evolve.md"))]
        for command in ("feedback \"the", "evolve --project", "evolve --apply", "promote skill"):
            self.assertIn(command, ran)


class SidecarTest(unittest.TestCase):
    def test_the_sidecar_names_the_setup_fixture(self):
        sidecar = json.loads(text(SKILL / "wayline.json"))
        self.assertIn("skill/wayline", sidecar["fixtures"])


if __name__ == "__main__":
    unittest.main()
