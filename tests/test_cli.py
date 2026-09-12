"""The command: version, the verb list, and the exit code of a verb that is not built yet."""

import io
import re
import subprocess
import sys
import unittest
from contextlib import redirect_stderr

from tests.paths import HARNESS_ROOT, SPEC_PATH
from tests.spec_table import spec_verbs
from wayline import TAG, __version__, cli


def run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "wayline", *args],
        cwd=HARNESS_ROOT, capture_output=True, text=True, timeout=60,
    )


def run_bin(*args):
    return subprocess.run(
        [str(HARNESS_ROOT / "bin" / "wayline"), *args],
        cwd="/", capture_output=True, text=True, timeout=60,
    )


class VersionTest(unittest.TestCase):
    def test_module_prints_the_tag(self):
        done = run_cli("--version")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn(TAG, done.stdout)

    def test_bin_prints_the_tag_from_any_cwd(self):
        done = run_bin("--version")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn(TAG, done.stdout)

    def test_tag_is_v_plus_version(self):
        self.assertEqual(TAG, "v" + __version__)

    def test_changelog_has_an_entry_for_the_tag(self):
        changelog = (HARNESS_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertRegex(changelog, r"(?m)^## %s\b" % re.escape(TAG))


class VerbListTest(unittest.TestCase):
    def test_help_lists_every_verb_of_the_spec(self):
        done = run_cli("--help")
        self.assertEqual(done.returncode, 0, done.stderr)
        for verb in spec_verbs(SPEC_PATH):
            self.assertRegex(done.stdout, r"(?m)^\s+%s\b" % verb, "verb %r missing from --help" % verb)

    def test_verb_table_covers_the_spec(self):
        table = {verb.name for verb in cli.VERBS}
        missing = set(spec_verbs(SPEC_PATH)) - table
        self.assertEqual(missing, set())

    def test_verb_names_are_unique(self):
        names = [verb.name for verb in cli.VERBS]
        self.assertEqual(len(names), len(set(names)))

    def test_no_arguments_prints_version_and_verbs(self):
        done = run_cli()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn(TAG, done.stdout)
        for verb in cli.VERBS:
            self.assertIn(verb.name, done.stdout)


class NotYetImplementedTest(unittest.TestCase):
    def test_unbuilt_verb_exits_2(self):
        unbuilt = [verb for verb in cli.VERBS if verb.handler is None]
        self.assertTrue(unbuilt, "every verb is built; drop this test")
        done = run_cli(unbuilt[0].name, "--whatever", "arg")
        self.assertEqual(done.returncode, 2)
        self.assertIn("not yet implemented", done.stderr)
        self.assertEqual(done.stdout, "")

    def test_unknown_verb_exits_2(self):
        done = run_cli("frobnicate")
        self.assertEqual(done.returncode, 2)
        self.assertIn("frobnicate", done.stderr)

    def test_main_returns_the_exit_code_in_process(self):
        buffer = io.StringIO()
        with redirect_stderr(buffer):
            code = cli.main(["run"])
        self.assertEqual(code, 2)
        self.assertIn("not yet implemented", buffer.getvalue())

    def test_a_handler_receives_the_remaining_arguments(self):
        seen = []
        verb = cli.Verb("probe", "probe [args]", "a test verb", "tools", handler=lambda args: seen.append(args) or 7)
        with cli.temporary_verb(verb):
            code = cli.main(["probe", "--x", "1"])
        self.assertEqual(code, 7)
        self.assertEqual(seen, [["--x", "1"]])

    def test_exit_codes_from_what_a_handler_returns(self):
        for result, code in [(None, 0), (True, 0), (False, 1), (0, 0), (3, 3), (255, 255)]:
            with self.subTest(result=result):
                self.assertEqual(cli.exit_code("probe", result), code)
        for result in [256, -1, "done", 1.5, [0]]:
            with self.subTest(result=result):
                with self.assertRaises(TypeError):
                    cli.exit_code("probe", result)

    def test_every_verb_belongs_to_a_printed_group(self):
        for verb in cli.VERBS:
            self.assertIn(verb.group, cli.GROUP_TITLES, verb.name)
        with cli.temporary_verb(cli.Verb("stray", "stray", "misfiled", "nowhere")):
            with self.assertRaises(ValueError):
                cli.overview()


if __name__ == "__main__":
    unittest.main()
