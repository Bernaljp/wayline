"""Roles and prompt assembly (Implementation Decisions 1 and 3; Testing Decisions seam 1).

The two files a role is, the `--agents` object the conductor composes from them, the locators a
context pack is written in, and the prompt itself: asserted on the rendered text, in the order
the spec fixes, because that order is the contract between the conductor and every worker.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tests.paths import HARNESS_ROOT
from wayline import worker
from wayline.worker import LaunchRequest, Prompt, Role, RoleError

TICKET = {
    "id": 7,
    "title": "Add the tokenizer",
    "kind": "code",
    "difficulty": 2,
    "status": "open",
    "blocked_by": [],
    "touches": ["src/tokenizer.py", "tests/"],
    "role": "coder",
    "skills": ["python-package", "profiling"],
    "acceptance": {"machine": ["python -m unittest", "ruff check src"], "quality": ["is it readable?"]},
    "proposed_by": "planner",
    "demo": "`python -m unittest` passes with the tokenizer in place.",
    "context_pack": ["notes.md", "src/tokenizer.py"],
}


def ticket(**changes):
    return dict(TICKET, **changes)


class RoleFileTest(unittest.TestCase):
    """`roles/<role>/agent.md` and `roles/<role>/wayline.json` as the harness ships them."""

    def test_the_coder_role_loads_from_the_harness(self):
        role = worker.read_role("coder")
        self.assertEqual(role.name, "coder")
        self.assertTrue(role.description.strip())
        self.assertIn("worktree", role.system_prompt)
        self.assertEqual(role.output_schema, "result")
        self.assertFalse(role.may_judge)

    def test_the_coder_tool_lists_are_the_ones_decision_4_fixes(self):
        role = worker.read_role("coder")
        for tool in ("Read", "Edit", "Write", "Glob", "Grep", "Agent", "Bash(wayline accept*)", "Bash(git commit *)"):
            self.assertIn(tool, role.allowed_tools)
        for tool in ("WebFetch", "WebSearch", "NotebookEdit"):
            self.assertIn(tool, role.disallowed_tools)
        self.assertFalse([tool for tool in role.allowed_tools if tool.startswith("Bash(git push")])

    def test_the_host_tools_a_worker_inherits_are_disallowed(self):
        """docs/verification/m0.md: --settings adds to the owner's configuration, it does not replace it.

        The live M0 run read the tool list off `system/init` rather than guessing at it, and found
        ten host tools the first denylist did not name. `Monitor` is the one that matters most: it
        runs a shell command, and it is not the `Bash` tool, so neither the role's `Bash(...)`
        allowlist nor the command guard's `Bash` matcher sees what it runs.
        """
        role = worker.read_role("coder")
        for tool in ("mcp__*", "Workflow", "Skill", "Monitor", "PushNotification", "SendMessage",
                     "RemoteTrigger", "ScheduleWakeup", "EnterWorktree", "ExitWorktree"):
            with self.subTest(tool=tool):
                self.assertIn(tool, role.disallowed_tools)

    def test_the_protocol_comes_from_prompts(self):
        role = worker.read_role("coder")
        self.assertIn("wayline accept", role.protocol)
        self.assertEqual(role.protocol, (HARNESS_ROOT / "prompts" / "roles" / "coder.md").read_text(encoding="utf-8"))

    def test_an_unknown_role_names_the_file_it_wanted(self):
        with self.assertRaises(RoleError) as caught:
            worker.read_role("nonesuch")
        self.assertIn("wayline.json", str(caught.exception))

    def test_a_role_name_outside_the_alphabet_is_refused(self):
        for name in ("Coder", "../coder", "coder/agent", ""):
            with self.subTest(name=name):
                with self.assertRaises(RoleError):
                    worker.read_role(name)


class RoleFileRefusalTest(unittest.TestCase):
    """A role the harness will not launch, checked on a copy so the shipped files stay untouched."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        shutil.copytree(HARNESS_ROOT / "roles", self.root / "roles")
        shutil.copytree(HARNESS_ROOT / "prompts", self.root / "prompts")
        self.markdown = self.root / "roles" / "coder" / "agent.md"
        self.settings = self.root / "roles" / "coder" / "wayline.json"

    def role(self):
        return worker.read_role("coder", harness_root=self.root)

    def rewrite(self, path, text):
        path.write_text(text, encoding="utf-8")

    def test_a_tools_field_in_the_agent_markdown_is_refused(self):
        text = self.markdown.read_text(encoding="utf-8").replace("name: coder", "name: coder\ntools: [Read, Write]", 1)
        self.rewrite(self.markdown, text)
        with self.assertRaises(RoleError) as caught:
            self.role()
        self.assertIn("StructuredOutput", str(caught.exception))

    def test_a_skills_field_in_the_agent_markdown_is_refused(self):
        text = self.markdown.read_text(encoding="utf-8").replace("name: coder", "name: coder\nskills: [absorb]", 1)
        self.rewrite(self.markdown, text)
        with self.assertRaises(RoleError):
            self.role()

    def test_an_agent_markdown_without_a_description_is_refused(self):
        body = self.markdown.read_text(encoding="utf-8").split("---", 2)[2]
        self.rewrite(self.markdown, "---\nname: coder\n---\n" + body)
        with self.assertRaises(RoleError) as caught:
            self.role()
        self.assertIn("description", str(caught.exception))

    def test_an_agent_markdown_without_a_body_is_refused(self):
        self.rewrite(self.markdown, "---\nname: coder\ndescription: \"a role\"\n---\n")
        with self.assertRaises(RoleError) as caught:
            self.role()
        self.assertIn("system prompt", str(caught.exception))

    def test_an_unknown_field_in_the_settings_is_refused(self):
        settings = json.loads(self.settings.read_text(encoding="utf-8"))
        settings["allowed_toolz"] = []
        self.rewrite(self.settings, json.dumps(settings))
        with self.assertRaises(RoleError) as caught:
            self.role()
        self.assertIn("allowed_toolz", str(caught.exception))

    def test_a_settings_file_naming_another_role_is_refused(self):
        settings = json.loads(self.settings.read_text(encoding="utf-8"))
        settings["role"] = "verifier"
        self.rewrite(self.settings, json.dumps(settings))
        with self.assertRaises(RoleError):
            self.role()

    def test_a_tool_list_that_is_not_a_list_of_strings_is_refused(self):
        settings = json.loads(self.settings.read_text(encoding="utf-8"))
        settings["allowed_tools"] = ["Read", 7]
        self.rewrite(self.settings, json.dumps(settings))
        with self.assertRaises(RoleError):
            self.role()

    def test_a_project_overrides_the_words_and_not_the_tools(self):
        project = self.root / "project"
        (project / ".claude" / "agents").mkdir(parents=True)
        (project / ".claude" / "agents" / "coder.md").write_text(
            "---\nname: coder\ndescription: \"the project's own coder\"\n---\n\nWrite Fortran.\n", encoding="utf-8")
        role = worker.read_role("coder", harness_root=self.root, project=project)
        self.assertEqual(role.description, "the project's own coder")
        self.assertEqual(role.system_prompt, "Write Fortran.")
        self.assertEqual(role.allowed_tools, worker.read_role("coder", harness_root=self.root).allowed_tools)


class AgentJsonTest(unittest.TestCase):
    """The `--agents` object of decision 3, which the launch line passes verbatim."""

    def setUp(self):
        self.role = worker.read_role("coder")

    def test_the_object_carries_the_fields_the_spec_names_in_its_order(self):
        agents = self.role.agent_json("opus", "high", 100)
        self.assertEqual(list(agents), ["coder"])
        self.assertEqual(list(agents["coder"]), ["description", "prompt", "model", "effort", "maxTurns", "permissionMode"])
        self.assertEqual(agents["coder"]["model"], "opus")
        self.assertEqual(agents["coder"]["effort"], "high")
        self.assertEqual(agents["coder"]["maxTurns"], 100)
        self.assertEqual(agents["coder"]["permissionMode"], "dontAsk")

    def test_the_object_carries_no_tools_and_no_skills(self):
        agents = self.role.agent_json("sonnet", "low", 40)
        self.assertNotIn("tools", agents["coder"])
        self.assertNotIn("skills", agents["coder"])

    def test_a_request_built_from_it_passes_the_launcher_check(self):
        request = LaunchRequest(
            role="coder", model="sonnet", effort="low", prompt="do the thing",
            agent_json=self.role.agent_json("sonnet", "low", 40),
            allowed_tools=self.role.allowed_tools, disallowed_tools=self.role.disallowed_tools,
            env={"WAYLINE_RUN": "/tmp/run"},
        )
        self.assertIs(request.check(), request)

    def test_no_budget_leaves_max_turns_out_rather_than_null(self):
        self.assertNotIn("maxTurns", self.role.agent_json("sonnet", "low", None)["coder"])


class LocatorTest(unittest.TestCase):
    """A context-pack entry: a path, a line range, or a markdown anchor."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.addCleanup(self.temporary.cleanup)
        (self.root / "notes.md").write_text(
            "# Notes\n\nfirst\n\n## Claim 1\n\nthe claim\n\n### Detail\n\nunder it\n\n## Claim 2\n\nthe other\n",
            encoding="utf-8")

    def test_a_plain_path_is_the_whole_file(self):
        text, problem = worker.read_locator("notes.md", [self.root])
        self.assertIsNone(problem)
        self.assertTrue(text.startswith("# Notes"))
        self.assertIn("the other", text)

    def test_a_line_range_is_inclusive_and_one_based(self):
        text, problem = worker.read_locator("notes.md:1-3", [self.root])
        self.assertIsNone(problem)
        self.assertEqual(text, "# Notes\n\nfirst\n")

    def test_one_line_number_is_that_line(self):
        self.assertEqual(worker.read_locator("notes.md:3", [self.root])[0], "first\n")

    def test_a_line_range_past_the_end_says_how_long_the_file_is(self):
        text, problem = worker.read_locator("notes.md:99-100", [self.root])
        self.assertEqual(text, "")
        self.assertIn("line(s)", problem)

    def test_an_anchor_is_the_section_down_to_the_next_heading_at_its_level(self):
        text, problem = worker.read_locator("notes.md#claim-1", [self.root])
        self.assertIsNone(problem)
        self.assertIn("the claim", text)
        self.assertIn("under it", text)  # a deeper heading stays inside the section
        self.assertNotIn("the other", text)

    def test_the_last_section_runs_to_the_end(self):
        self.assertIn("the other", worker.read_locator("notes.md#claim-2", [self.root])[0])

    def test_an_anchor_that_matches_nothing_is_a_problem(self):
        self.assertIn("no heading", worker.read_locator("notes.md#claim-9", [self.root])[1])

    def test_a_missing_file_is_a_problem_and_not_an_exception(self):
        self.assertIn("no file", worker.read_locator("gone.md", [self.root])[1])

    def test_a_path_leaving_the_root_is_refused(self):
        self.assertIn("outside", worker.read_locator("../secret.txt", [self.root])[1])

    def test_the_roots_are_tried_in_order(self):
        second = self.root / "second"
        second.mkdir()
        (second / "only-here.md").write_text("second root\n", encoding="utf-8")
        self.assertEqual(worker.read_locator("only-here.md", [self.root, second])[0], "second root\n")


class PromptTest(unittest.TestCase):
    """The prompt of decision 3, asserted on the rendered text."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.addCleanup(self.temporary.cleanup)
        (self.root / "notes.md").write_text("# Notes\n\nwhat the planner packed\n", encoding="utf-8")
        (self.root / "src").mkdir()
        (self.root / "src" / "tokenizer.py").write_text("def tokenize(text):\n    return text.split()\n", encoding="utf-8")
        self.role = worker.read_role("coder")

    def assemble(self, fields=None, **options):
        options.setdefault("roots", [self.root])
        return worker.assemble_prompt(fields or TICKET, self.role, **options)

    def sections(self, text):
        """The prompt's own top-level headings; a packed file's headings are inside a fence."""
        headings, fence = [], None
        for line in text.split("\n"):
            if fence is None and line.startswith("```"):
                fence = line
            elif fence is not None and line == fence:
                fence = None
            elif fence is None and line.startswith("# "):
                headings.append(line)
        return headings

    def test_the_sections_come_in_the_order_decision_3_fixes(self):
        text = self.assemble().text
        self.assertEqual(self.sections(text), ["# The rest of your skills", "# Ticket 7: Add the tokenizer",
                                               "# Context pack", "# Protocol", "# The result", "# The contract"])
        self.assertTrue(text.startswith("/wayline-python-package\n/wayline-profiling\n"))

    def test_one_skill_line_per_assigned_skill_and_none_without(self):
        self.assertNotIn("/wayline-", self.assemble(ticket(skills=[])).text.split("# Ticket")[0])

    def test_the_ticket_is_restated_with_what_the_spec_lists(self):
        text = self.assemble().text
        for expected in ("Add the tokenizer", "kind: code", "python -m unittest", "`src/tokenizer.py`", "tests/"):
            self.assertIn(expected, text)
        self.assertIn("passes with the tokenizer in place", text)  # the demo

    def test_the_budget_is_restated_when_it_is_given(self):
        self.assertIn("- budget: 40 turns, 30 minutes", self.assemble(budget={"max_turns": 40, "max_minutes": 30}).text)

    def test_the_quality_criteria_stay_with_the_verifier(self):
        self.assertNotIn("is it readable?", self.assemble().text)

    def test_each_pack_entry_sits_under_a_header_with_its_locator(self):
        text = self.assemble().text
        self.assertIn("## notes.md\n", text)
        self.assertIn("## src/tokenizer.py\n", text)
        self.assertIn("what the planner packed", text)
        self.assertIn("def tokenize(text):", text)
        self.assertLess(text.index("## notes.md"), text.index("## src/tokenizer.py"))  # the ticket's order

    def test_an_unreadable_entry_is_announced_and_the_rest_still_render(self):
        prompt = self.assemble(ticket(context_pack=["gone.md", "notes.md"]))
        self.assertIn("could not be read", prompt.text)
        self.assertIn("what the planner packed", prompt.text)
        packing = [problem for problem in prompt.problems if problem.startswith("gone.md")]
        self.assertEqual(len(packing), 1, prompt.problems)

    def test_an_entry_over_the_cap_is_cut_where_it_runs_out(self):
        prompt = self.assemble(max_chars=40)
        self.assertTrue(prompt.cut)
        self.assertEqual(prompt.context_chars, 40)
        self.assertIn("what the planner packed", prompt.text)  # the first entry fits whole
        self.assertIn("def tok", prompt.text)                  # the second is cut mid-file
        self.assertNotIn("return text.split()", prompt.text)
        self.assertIn("cut here at the context cap; 37 character(s) are missing", prompt.text)

    def test_an_entry_the_cap_leaves_no_room_for_is_dropped_and_named(self):
        prompt = self.assemble(max_chars=33)
        self.assertTrue(prompt.cut)
        self.assertEqual(prompt.dropped, ["src/tokenizer.py"])
        self.assertIn("reached its cap of 33 characters", prompt.text)
        self.assertIn("src/tokenizer.py", prompt.text.split("reached its cap")[1])
        self.assertNotIn("def tok", prompt.text)

    def test_a_pack_under_the_cap_is_not_cut(self):
        prompt = self.assemble(max_chars=100000)
        self.assertFalse(prompt.cut)
        self.assertEqual(prompt.dropped, [])
        self.assertNotIn("context cap", prompt.text)

    def test_no_pack_renders_no_pack_section(self):
        text = self.assemble(ticket(context_pack=[])).text
        self.assertNotIn("# Context pack", text)

    def test_file_contents_are_fenced_longer_than_any_fence_inside_them(self):
        (self.root / "notes.md").write_text("```\nnested\n```\n", encoding="utf-8")
        text = self.assemble(ticket(context_pack=["notes.md"])).text
        self.assertIn("````\n```\nnested\n```\n````", text)

    def test_the_result_section_names_the_schema_fields(self):
        text = self.assemble().text
        for expected in ("`ticket_id` (integer, required)", "`summary` (string, required)", "structured output"):
            self.assertIn(expected, text)
        self.assertIn("one of done, running, failed, blocked, needs_human", text)
        self.assertIn("`ticket_id` is 7", text)

    def test_the_contract_lines_are_all_five(self):
        text = self.assemble(consult_max=5).text.split("# The contract")[1]
        self.assertIn("touch set: `src/tokenizer.py`, `tests/`", text)
        self.assertIn("`wayline accept`", text)
        self.assertIn("branch `ticket/7`", text)
        self.assertIn("never edit `research/`", text)
        self.assertIn("at most 5 times", text)

    def test_the_sha256_changes_with_the_prompt(self):
        first = self.assemble()
        second = self.assemble(ticket(title="Add the other tokenizer"))
        self.assertNotEqual(first.sha256, second.sha256)
        self.assertEqual(len(first.sha256), 64)

    def test_the_prompt_ends_with_one_newline(self):
        text = self.assemble().text
        self.assertTrue(text.endswith("\n"))
        self.assertFalse(text.endswith("\n\n"))


class InlinedSkillTest(unittest.TestCase):
    """The skills after the first, inlined under a heading (M0 criterion 8, ticket 06).

    The live run measured which of a ticket's `/wayline-<skill>` lines expand: the first one, and
    only the first (`docs/verification/m0.md`). So the conductor carries the rest itself rather
    than leaving a worker to find them, which it can only do where they happen to be committed in
    its worktree.
    """

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="wayline-skills-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.role = worker.read_role("coder")

    def write_skill(self, name, body, frontmatter=True):
        directory = self.root / ".claude" / "skills" / ("wayline-" + name)
        directory.mkdir(parents=True, exist_ok=True)
        head = "---\nname: wayline-%s\ndescription: the %s skill\n---\n\n" % (name, name) if frontmatter else ""
        (directory / "SKILL.md").write_text(head + body, encoding="utf-8")

    def assemble(self, skills):
        return worker.assemble_prompt(ticket(skills=skills, context_pack=[]), self.role, roots=[self.root])

    def test_the_first_skill_is_left_to_the_line_that_expands(self):
        self.write_skill("alpha", "# Alpha\n\nThe alpha instruction.\n")
        self.write_skill("beta", "# Beta\n\nThe beta instruction.\n")
        text = self.assemble(["alpha", "beta"]).text
        self.assertIn("The beta instruction.", text)
        self.assertNotIn("The alpha instruction.", text)

    def test_the_rest_come_in_the_ticket_s_order_under_their_own_headings(self):
        for name in ("alpha", "beta", "gamma"):
            self.write_skill(name, "# %s\n\nThe %s instruction.\n" % (name.title(), name))
        text = self.assemble(["alpha", "beta", "gamma"]).text
        self.assertLess(text.index("## /wayline-beta"), text.index("## /wayline-gamma"))
        self.assertLess(text.index("# The rest of your skills"), text.index("# Ticket 7"))

    def test_the_frontmatter_is_left_behind(self):
        self.write_skill("alpha", "body\n")
        self.write_skill("beta", "# Beta\n\nThe beta instruction.\n")
        text = self.assemble(["alpha", "beta"]).text
        self.assertNotIn("description: the beta skill", text)
        self.assertIn("The beta instruction.", text)

    def test_a_skill_with_no_frontmatter_survives_whole(self):
        self.write_skill("alpha", "body\n")
        self.write_skill("beta", "# Beta\n\nThe beta instruction.\n", frontmatter=False)
        self.assertIn("The beta instruction.", self.assemble(["alpha", "beta"]).text)

    def test_a_skill_that_is_nowhere_is_announced_rather_than_guessed_at(self):
        self.write_skill("alpha", "body\n")
        prompt = self.assemble(["alpha", "missing"])
        self.assertIn("## /wayline-missing", prompt.text)
        self.assertIn("was not found", prompt.text)
        self.assertEqual(prompt.problems, ["skill missing has no SKILL.md under any of the prompt's roots"])

    def test_a_skill_that_cannot_be_read_is_announced_rather_than_crashing_the_wave(self):
        """A locator the pack cannot read is announced; a skill body is no different."""
        self.write_skill("alpha", "body\n")
        self.write_skill("beta", "the beta instruction\n")
        (self.root / ".claude" / "skills" / "wayline-beta" / "SKILL.md").write_bytes(b"\xff\xfe not utf-8")
        prompt = self.assemble(["alpha", "beta"])
        self.assertIn("could not be read", prompt.text)
        self.assertEqual(len(prompt.problems), 1, prompt.problems)
        self.assertIn("skill beta", prompt.problems[0])

    def test_the_first_skill_is_looked_up_even_though_its_body_is_not_inlined(self):
        """Nothing else checks that a ticket's skills exist, and its line is the one that expands.

        A misspelled first skill would otherwise be a slash-command line expanding into nothing,
        with no problem recorded and a worker that never learns it was missing anything.
        """
        self.write_skill("beta", "the beta instruction\n")
        prompt = self.assemble(["missing", "beta"])
        self.assertEqual(prompt.problems, ["skill missing has no SKILL.md under any of the prompt's roots"])
        self.assertIn("the beta instruction", prompt.text)  # the rest are inlined regardless

    def test_a_lone_skill_that_is_nowhere_is_reported_too(self):
        prompt = self.assemble(["missing"])
        self.assertEqual(prompt.problems, ["skill missing has no SKILL.md under any of the prompt's roots"])
        self.assertNotIn("# The rest of your skills", prompt.text)

    def test_an_inlined_body_is_cut_at_the_cap_and_says_where(self):
        self.write_skill("alpha", "body\n")
        self.write_skill("beta", "B" * 500)
        prompt = worker.assemble_prompt(ticket(skills=["alpha", "beta"], context_pack=[]), self.role,
                                        roots=[self.root], max_chars=40)
        self.assertTrue(prompt.cut)
        self.assertEqual(prompt.skill_chars, 40)
        self.assertIn("cut here at the context cap", prompt.text)
        self.assertNotIn("B" * 41, prompt.text)

    def test_a_skill_past_the_cap_is_named_rather_than_silently_gone(self):
        self.write_skill("alpha", "body\n")
        self.write_skill("beta", "B" * 60)
        self.write_skill("gamma", "the gamma instruction\n")
        prompt = worker.assemble_prompt(ticket(skills=["alpha", "beta", "gamma"], context_pack=[]),
                                        self.role, roots=[self.root], max_chars=40)
        self.assertEqual(prompt.dropped, ["/wayline-gamma"])
        self.assertIn("reached the context cap", prompt.text)
        self.assertNotIn("the gamma instruction", prompt.text)

    def test_the_pack_and_the_skills_are_counted_apart(self):
        """The journal has always recorded the pack's size; the skills are beside it, not inside."""
        self.write_skill("alpha", "body\n")
        self.write_skill("beta", "the beta instruction\n")
        prompt = self.assemble(["alpha", "beta"])
        self.assertEqual(prompt.context_chars, 0)  # this ticket packs nothing
        self.assertEqual(prompt.skill_chars, len("the beta instruction\n"))

    def test_one_skill_or_none_gets_no_section(self):
        self.write_skill("alpha", "body\n")
        for skills in ([], ["alpha"]):
            with self.subTest(skills=skills):
                self.assertNotIn("# The rest of your skills", self.assemble(skills).text)

    def test_the_first_root_that_has_the_skill_wins(self):
        """The worktree's copy stands in for the project's, as it does for a context-pack locator."""
        other = Path(tempfile.mkdtemp(prefix="wayline-skills-other-"))
        self.addCleanup(shutil.rmtree, other, ignore_errors=True)
        self.write_skill("alpha", "body\n")
        self.write_skill("beta", "the worktree copy\n")
        directory = other / ".claude" / "skills" / "wayline-beta"
        directory.mkdir(parents=True)
        (directory / "SKILL.md").write_text("the project copy\n", encoding="utf-8")
        text = worker.assemble_prompt(ticket(skills=["alpha", "beta"], context_pack=[]), self.role,
                                      roots=[self.root, other]).text
        self.assertIn("the worktree copy", text)
        self.assertNotIn("the project copy", text)

    def test_a_body_that_carries_backticks_is_fenced_longer_than_they_are(self):
        self.write_skill("alpha", "body\n")
        self.write_skill("beta", "Run this:\n\n```\nwayline accept\n```\n")
        text = self.assemble(["alpha", "beta"]).text
        self.assertIn("````", text)
        self.assertIn("wayline accept", text)


if __name__ == "__main__":
    unittest.main()
