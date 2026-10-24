"""The user guide under docs/guide/ (ticket 124): it quotes only verbs and flags the command has, and its pages exist."""

import re
import unittest
from pathlib import Path

from wayline import cli

ROOT = Path(__file__).resolve().parent.parent
GUIDE = ROOT / "docs" / "guide"
PAGES = ["getting-started.md", "talking.md", "objectives.md", "midway.md", "research.md", "paper.md", "run.md",
         "software.md", "upgrading.md"]
VERB = re.compile(r"`wayline ([a-z][a-z-]*)([^`]*)`")
FLAG = re.compile(r"(?<![\w-])(--[a-z][a-z-]*)")
# Glossary _Avoid_ words that have no innocent sense in this guide.
AVOIDED = ["final report", "table of contents", "front door", "KPI", "exploration run", "plotting pass",
           "line-of-work report", "accept-if-improved", "hill climbing", "stop condition", "fallback policy"]


def guide_text():
    return {path.name: path.read_text(encoding="utf-8") for path in sorted(GUIDE.glob("*.md"))}


def verb_usage(name):
    return next((verb.usage for verb in cli.VERBS if verb.name == name), None)


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
                usage = verb_usage(match.group(1)) or ""
                for flag in FLAG.findall(match.group(2)):
                    if flag in ("--project", "--help"):
                        continue
                    self.assertIn(flag, usage, "%s: wayline %s %s" % (page, match.group(1), flag))

    def test_every_repository_path_named_exists(self):
        prefixes = ("wayline/", "skills/", "dashboard/", "schemas/", "templates/", "guidelines/", "methods/",
                    "converters/", "policy.json", "CHANGELOG.md", "CONTEXT.md")
        for page, text in guide_text().items():
            for path in re.findall(r"`([A-Za-z_./-]+)`", text):
                if path.startswith(prefixes) and "<" not in path:
                    self.assertTrue((ROOT / path).exists(), "%s names %s" % (page, path))

    def test_no_avoided_word(self):
        for page, text in guide_text().items():
            for word in AVOIDED:
                self.assertNotIn(word.lower(), text.lower(), "%s uses %r" % (page, word))


if __name__ == "__main__":
    unittest.main()
