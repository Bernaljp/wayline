"""The user guide under docs/guide/ (ticket 124): it quotes only verbs and flags the command has, and its pages exist."""

import re
import unittest
from pathlib import Path

from wayline import cli

ROOT = Path(__file__).resolve().parent.parent
GUIDE = ROOT / "docs" / "guide"
PAGES = ["getting-started.md", "talking.md", "objectives.md", "midway.md", "research.md", "paper.md", "run.md",
         "software.md", "upgrading.md"]
VERB = re.compile(r"(?:`|^)wayline ([a-z][a-z-]*)([^`\n]*)", re.MULTILINE)
WORD = re.compile(r"^ ([a-z][a-z-]*)(?![\w<|])")
FLAG = re.compile(r"(?<![\w-])(--[a-z][a-z-]*)")
# Glossary _Avoid_ words that have no innocent sense in this guide.
AVOIDED = ["final report", "table of contents", "front door", "KPI", "exploration run", "plotting pass",
           "line-of-work report", "accept-if-improved", "hill climbing", "stop condition", "fallback policy"]


def guide_text():
    return {path.name: path.read_text(encoding="utf-8") for path in sorted(GUIDE.glob("*.md"))}


def verb_usage(name):
    return next((verb.usage for verb in cli.VERBS if verb.name == name), None)


def usage_flags(name):
    return set(FLAG.findall(verb_usage(name) or ""))


def source_flags():
    """Every option the package's parsers declare, as a whole token."""
    text = "".join(path.read_text(encoding="utf-8") for path in (ROOT / "wayline").glob("*.py"))
    return set(re.findall(r"[\"'](--[a-z][a-z-]*)[\"'=]", text))


class GuidePages(unittest.TestCase):
    def test_index_links_every_page_and_the_readme_links_the_index(self):
        index = (GUIDE / "index.md").read_text(encoding="utf-8")
        for page in PAGES:
            self.assertTrue((GUIDE / page).is_file(), page)
            self.assertIn("(%s)" % page, index, page)
        self.assertIn("docs/guide/index.md", (ROOT / "README.md").read_text(encoding="utf-8"))

    def test_every_quoted_verb_is_a_verb_of_the_command(self):
        names = {verb.name for verb in cli.VERBS}
        quoted = [(page, m.group(1)) for page, text in guide_text().items() for m in VERB.finditer(text)]
        self.assertGreater(len(quoted), 50)
        for page, name in quoted:
            self.assertIn(name, names, "%s quotes wayline %s" % (page, name))

    def test_every_flag_of_a_quoted_verb_is_in_its_usage(self):
        for page, text in guide_text().items():
            for match in VERB.finditer(text):
                flags = usage_flags(match.group(1))
                for flag in FLAG.findall(match.group(2)):
                    if flag in ("--project", "--help"):  # every writing verb takes --project; --help every verb
                        continue
                    self.assertIn(flag, flags, "%s: wayline %s %s" % (page, match.group(1), flag))

    def test_every_quoted_subcommand_is_in_its_verbs_usage(self):
        for page, text in guide_text().items():
            for match in VERB.finditer(text):
                word = WORD.match(match.group(2))
                if word:
                    usage = set(re.findall(r"[a-z][a-z-]*", verb_usage(match.group(1)) or ""))
                    self.assertIn(word.group(1), usage, "%s: wayline %s %s" % (page, match.group(1), word.group(1)))

    def test_every_flag_named_anywhere_is_declared_by_a_parser(self):
        declared = source_flags()
        for page, text in guide_text().items():
            for flag in FLAG.findall(text):
                self.assertIn(flag, declared, "%s names %s" % (page, flag))

    def test_every_setting_named_is_a_key_of_harness_json_or_policy(self):
        harness = (ROOT / "schemas" / "harness.json").read_text(encoding="utf-8")
        policy = (ROOT / "policy.json").read_text(encoding="utf-8")
        for key in ("research_version", "stop_when", "wallclock_hours", "gpu_hours", "plotting", "environment", "chat",
                    "dashboard", "paper_order", "code_repository", "model_fallback", "ladder_changes", "human_only"):
            self.assertIn('"%s"' % key, harness, key)
        for key in ("give_up_days", "min_seeds", "port"):
            self.assertIn('"%s"' % key, policy, key)

    def test_every_repository_path_named_exists(self):
        prefixes = ("wayline/", "skills/", "dashboard/", "schemas/", "templates/", "guidelines/", "methods/",
                    "converters/", "policy.json", "CHANGELOG.md", "CONTEXT.md")
        for page, text in guide_text().items():
            for path in re.findall(r"`([A-Za-z0-9_./-]+)`", text):
                if path.startswith(prefixes):
                    self.assertTrue((ROOT / path).exists(), "%s names %s" % (page, path))

    def test_no_avoided_word(self):
        for page, text in guide_text().items():
            for word in AVOIDED:
                self.assertNotIn(word.lower(), text.lower(), "%s uses %r" % (page, word))


if __name__ == "__main__":
    unittest.main()
