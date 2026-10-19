"""The code repository (Implementation Decision 17, ticket 85): `code/`, its absorption, its split, its remote.

Plain `git` runs for real against temporary repositories, `git subtree` included; `gh` never does. Every
program goes through the tool runner (seam 6), and the runner here is the recorded one: it keeps every argv
it was handed, answers `gh` from the recordings under `fixtures/code/recorded/`, and hands `git` on to the
real runner. No test creates a GitHub repository: the push goes to a local bare repository in the GitHub
URL's place. The `gh repo view --json` answers keep the shape `gh` 2.95.0 printed on this workstation on
2026-10-18 for a repository of the owner's, and `gh repo create` answers with the URL it prints.
"""

import copy
import io
import json
import shutil
import subprocess
import sys
from pathlib import Path
from unittest import mock

from tests import machine
from tests.paths import FIXTURES_DIR
from tests.projects import ProjectTestCase
from tests.test_conductor import done, drive
from tests.test_jobs import _spec as job_spec
from wayline import code_repository, intake, resources, worker
from wayline.code_repository import CodeRepositoryError
from wayline.conductor import Conductor
from wayline.jsonschema import load_schema
from wayline.ledger import Ledger
from wayline.project import init_project, read_harness
from wayline.tickets import tickets_dir
from wayline.tools import ToolOutput, Tools, run_tool
from wayline.worker import Patch

MIDWAY = FIXTURES_DIR / "midway"
ONE_TICKET = FIXTURES_DIR / "projects" / "one-ticket"
RECORDED = FIXTURES_DIR / "code" / "recorded"


def git(cwd, *args):
    done = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    if done.returncode != 0:
        raise AssertionError("git %s: %s" % (" ".join(args), done.stderr))
    return done.stdout.strip()


class Runner:
    """The tool runner's recordings: `git` runs for real, `gh` answers from `fixtures/code/recorded/`."""

    def __init__(self, gh=None):
        self.calls = []
        self.gh = gh or {}

    def __call__(self, argv, cwd=None, timeout=None, env=None):
        argv = [str(part) for part in argv]
        self.calls.append(argv)
        if Path(argv[0]).name == "gh":
            for prefix, answer in self.gh.items():
                if argv[1:1 + len(prefix)] == list(prefix):
                    return answer
            return ToolOutput(1, b"", ("gh %s: nothing recorded" % " ".join(argv[1:])).encode())
        return run_tool(argv, cwd=cwd, timeout=timeout, env=env)

    def ran(self, *words):
        """The calls whose argv holds `words` in order, one after another."""
        found = []
        for argv in self.calls:
            for start in range(len(argv)):
                if argv[start:start + len(words)] == list(words):
                    found.append(argv)
                    break
        return found


def recorded(name):
    return ToolOutput(0, (RECORDED / name).read_bytes(), b"")


class CodeRepositoryCase(ProjectTestCase):
    def setUp(self):
        super().setUp()
        self.project = self.temp / "lantern"
        self.project.mkdir()
        init_project(self.project)
        self.clone = self.temp / "owner" / "phaselock"
        subprocess.run([sys.executable, str(MIDWAY / "build_code.py"), str(self.clone)], check=True)
        self.clone_head = git(self.clone, "rev-parse", "HEAD")
        self.run = Runner()

    def absorb(self, clone=None):
        return code_repository.absorb_clone(self.project, clone or self.clone, run=self.run)


class AbsorbTheSyntheticRepositoryTest(CodeRepositoryCase):
    """The start-midway project's repository arrives in `code/` with its history and no gitlink."""

    def test_the_clone_arrives_under_code_with_its_history(self):
        self.absorb()
        self.assertTrue(self.run.ran("subtree", "add", "--prefix=code", str(self.clone.resolve()), self.clone_head))
        self.assertIn("window=512", (self.project / "code" / "phaselock.py").read_text())
        subjects = git(self.project, "log", "--format=%s", "main").splitlines()
        for subject in ("Add the order parameter", "Port the order parameter to MATLAB",
                        "Use a 512-sample window for colony synchrony"):
            self.assertIn(subject, subjects)
        # Only the record in harness.json is left to commit, as every setting intake writes is.
        self.assertEqual(git(self.project, "status", "--porcelain"), "M harness.json")

    def test_no_gitlink_and_no_nested_git(self):
        self.absorb()
        modes = {line.split()[0] for line in git(self.project, "ls-files", "--stage", "--", "code").splitlines()}
        self.assertNotIn("160000", modes)
        self.assertEqual(git(self.project, "ls-files", "code"), "code/phaselock.m\ncode/phaselock.py")
        self.assertFalse((self.project / "code" / ".git").exists())
        self.assertTrue((self.clone / ".git").is_dir(), "the clone itself is left where it is")

    def test_the_upstream_commit_and_license_are_recorded(self):
        git(self.clone, "remote", "add", "origin", "https://github.com/ines-varga/phaselock.git")
        upstream = self.absorb()
        self.assertEqual(upstream, read_harness(self.project)["code_repository"]["upstream"])
        self.assertEqual(upstream["commit"], self.clone_head)
        self.assertEqual(upstream["url"], "https://github.com/ines-varga/phaselock.git")
        self.assertIsNone(upstream["uncommitted"])
        self.assertIsNone(upstream["license"], "the synthetic repository ships no license")

    def test_absorbing_the_same_clone_again_changes_nothing(self):
        self.absorb()
        before = git(self.project, "rev-parse", "main")
        self.absorb()
        self.assertEqual(git(self.project, "rev-parse", "main"), before)

    def test_a_second_clone_is_refused(self):
        self.absorb()
        other = self.temp / "owner" / "other"
        subprocess.run([sys.executable, str(MIDWAY / "build_code.py"), str(other)], check=True)
        with self.assertRaises(CodeRepositoryError) as caught:
            self.absorb(other)
        self.assertIn("absorb --code", str(caught.exception))

    def test_the_project_itself_is_refused(self):
        with self.assertRaises(CodeRepositoryError) as caught:
            self.absorb(self.project)
        self.assertIn("the project itself", str(caught.exception))
        self.assertFalse((self.project / ".clones").exists())

    def test_a_repository_enclosing_the_project_is_refused(self):
        outer = self.temp / "outer"
        outer.mkdir()
        git(outer, "init", "-q", "-b", "main")
        (outer / "README.md").write_text("outer\n")
        git(outer, "add", "README.md")
        git(outer, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "outer")
        inner = outer / "lantern"
        inner.mkdir()
        init_project(inner)
        with self.assertRaises(CodeRepositoryError) as caught:
            code_repository.absorb_clone(inner, outer, run=self.run)
        self.assertIn("encloses the project", str(caught.exception))
        self.assertFalse((inner / "code").exists())

    def test_a_submodule_of_the_clone_stays_a_gitlink(self):
        sub = self.temp / "owner" / "sub"
        subprocess.run([sys.executable, str(MIDWAY / "build_code.py"), str(sub)], check=True)
        pinned = git(sub, "rev-parse", "HEAD")
        git(self.clone, "update-index", "--add", "--cacheinfo", "160000,%s,vendor/sub" % pinned)
        git(self.clone, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "vendor the submodule")
        (self.clone / "phaselock.py").write_text("# an uncommitted edit\n")
        upstream = self.absorb()
        self.assertIsNotNone(upstream["uncommitted"])
        self.assertEqual(git(self.project, "ls-files", "--stage", "--", "code/vendor/sub").split()[:2], ["160000", pinned])

    def test_a_sha256_repository_is_recorded(self):
        project = self.temp / "sha256-project"
        project.mkdir()
        git(project, "init", "-q", "-b", "main", "--object-format=sha256")
        (project / "harness.json").write_text((self.project / "harness.json").read_text())
        git(project, "add", "harness.json")
        git(project, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init")
        clone = self.temp / "sha256-clone"
        clone.mkdir()
        git(clone, "init", "-q", "-b", "main", "--object-format=sha256")
        (clone / "m.py").write_text("x = 1\n")
        git(clone, "add", "m.py")
        git(clone, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "m")
        upstream = code_repository.absorb_clone(project, clone, run=self.run)
        self.assertEqual(len(upstream["commit"]), 64)
        self.assertTrue((project / "code" / "m.py").is_file())

    def test_a_record_harness_json_would_refuse_stops_the_absorption_before_main_moves(self):
        schema = copy.deepcopy(load_schema("harness"))  # the loaded schema is shared: never change it in place
        upstream = schema["properties"]["code_repository"]["properties"]["upstream"]
        upstream["properties"]["commit"]["pattern"] = "^never$"  # a commit the schema refuses, as a SHA-256 one was
        before = git(self.project, "rev-parse", "main")
        with mock.patch.object(code_repository, "load_schema", lambda name: schema), \
                self.assertRaises(CodeRepositoryError):
            self.absorb()
        self.assertEqual(git(self.project, "rev-parse", "main"), before)
        self.assertFalse((self.project / "code").exists())

    def test_a_directory_with_no_history_is_refused(self):
        plain = self.temp / "plain"
        plain.mkdir()
        with self.assertRaises(CodeRepositoryError):
            self.absorb(plain)


class IntakeAbsorbsTest(CodeRepositoryCase):
    """`wayline intake` absorbs the one clone the spec names as the project's own, and its Code section says so."""

    def intake(self, **spec):
        spec.setdefault("intent", "Find whether lantern moth colonies synchronize with size.")
        return intake.take_intake(self.project, spec, base=self.temp, run=self.run)

    def code_section(self):
        text = (self.project / "research" / "INTAKE.md").read_text(encoding="utf-8")
        return text.split("## Code", 1)[1].split("\n## ", 1)[0]

    def test_the_projects_own_clone_arrives_in_code(self):
        (self.clone / "notes.txt").write_text("an untracked note\n")
        report = self.intake(clone=str(self.clone))
        self.assertTrue((self.project / "code" / "phaselock.py").is_file())
        upstream = report["harness"]["code_repository"]["upstream"]
        self.assertEqual(upstream, read_harness(self.project)["code_repository"]["upstream"])
        self.assertEqual(upstream["commit"], self.clone_head)
        section = self.code_section()
        self.assertIn(self.clone_head, section)
        self.assertIn("absorbed into `code/` with its history", section)
        self.assertIn("1 uncommitted change, absorbed as the next commit `%s`" % upstream["uncommitted"][:12], section)
        self.assertEqual(report["counts"]["code"], 1)

    def test_repositories_the_work_builds_on_are_listed_pinned_and_never_absorbed(self):
        other = self.temp / "owner" / "other"
        subprocess.run([sys.executable, str(MIDWAY / "build_code.py"), str(other)], check=True)
        report = self.intake(code=[str(self.clone)], materials=[str(other)])
        self.assertFalse((self.project / "code").exists())
        self.assertNotIn("code_repository", read_harness(self.project))
        self.assertIn(self.clone_head, self.code_section())
        self.assertNotIn("absorbed", self.code_section())
        self.assertEqual(report["counts"]["code"], 2)

    def test_the_clone_and_a_repository_it_builds_on_together(self):
        other = self.temp / "owner" / "other"
        subprocess.run([sys.executable, str(MIDWAY / "build_code.py"), str(other)], check=True)
        self.intake(clone=str(self.clone), code=[str(other)])
        self.assertTrue((self.project / "code" / "phaselock.py").is_file())
        self.assertEqual(read_harness(self.project)["code_repository"]["upstream"]["clone"], str(self.clone.resolve()))
        self.assertEqual(self.code_section().count("absorbed into `code/`"), 1)

    def test_intake_again_after_the_clone_moved_on_keeps_code_as_it_is(self):
        self.intake(clone=str(self.clone))
        before = git(self.project, "rev-parse", "main")
        (self.clone / "later.py").write_text("x = 1\n")
        git(self.clone, "add", "later.py")
        git(self.clone, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "later work")
        self.intake(clone=str(self.clone))
        self.assertEqual(git(self.project, "rev-parse", "main"), before)
        self.assertFalse((self.project / "code" / "later.py").exists())
        self.assertIn("absorbed at `%s`" % self.clone_head[:12], self.code_section())

    def test_intake_again_names_a_nested_clone_by_where_the_owner_put_it(self):
        shutil.move(str(self.clone), str(self.project / "analysis"))
        self.intake(clone="lantern/analysis")
        self.assertTrue((self.project / ".clones" / "analysis" / ".git").is_dir())
        before = git(self.project, "rev-parse", "main")
        self.intake(clone="lantern/analysis")
        self.assertEqual(git(self.project, "rev-parse", "main"), before)
        self.assertIn(".clones/analysis", self.code_section())

    def test_the_setup_answer_rides_in_the_spec(self):
        self.run.gh[("repo", "create")] = recorded("gh-repo-create.txt")
        remote = self.temp / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
        report = intake.take_intake(self.project, {"intent": "x", "clone": str(self.clone),
                                                   "code_repository": {"shape": "package", "license": "MIT"}},
                                    base=self.temp, run=self.run, tools=gh_record(self.temp / "tools"),
                                    push_url=lambda record: str(remote))
        record = read_harness(self.project)["code_repository"]
        self.assertEqual(report["harness"]["code_repository"], record)
        self.assertEqual((record["shape"], record["license"], record["remote"]["how"]), ("package", "MIT", "copy"))
        self.assertEqual(record["upstream"]["commit"], self.clone_head)
        self.assertEqual(git(remote, "rev-parse", "main"), self.clone_head)

    def test_a_bad_setup_answer_is_refused_before_anything_is_written(self):
        with self.assertRaises(intake.IntakeError):
            self.intake(clone=str(self.clone), code_repository={"shape": "monorepo"})
        self.assertFalse((self.project / "code").exists())


class UncommittedChangesTest(CodeRepositoryCase):
    """The clone's uncommitted changes become the next commit, named as such."""

    def setUp(self):
        super().setUp()
        (self.clone / "phaselock.py").write_text((self.clone / "phaselock.py").read_text() + "\n# dusk sweep\n")
        (self.clone / "phaselock.m").unlink()
        (self.clone / "notes.txt").write_text("an untracked note\n")
        (self.clone / ".gitignore").write_text("*.log\n")
        (self.clone / "run.log").write_text("ignored\n")
        (self.clone / "LICENSE").write_text("MIT License\n\nCopyright (c) 2022 Ines Varga\n\nPermission is hereby "
                                            "granted, free of charge, to any person obtaining a copy\n")
        self.upstream = self.absorb()

    def test_the_next_commit_carries_them_and_says_so(self):
        subject = git(self.project, "log", "-1", "--format=%s", self.upstream["uncommitted"])
        self.assertIn("uncommitted changes of phaselock", subject)
        self.assertIn("dusk sweep", (self.project / "code" / "phaselock.py").read_text())
        self.assertFalse((self.project / "code" / "phaselock.m").exists())
        self.assertTrue((self.project / "code" / "notes.txt").exists())
        self.assertFalse((self.project / "code" / "run.log").exists(), "what the clone ignores stays out")

    def test_the_absorbed_commit_is_still_the_clones_head(self):
        self.assertEqual(self.upstream["commit"], self.clone_head)
        files = git(self.project, "ls-tree", "-r", "--name-only", "%s^" % self.upstream["uncommitted"], "--", "code")
        self.assertIn("code/phaselock.m", files.splitlines())

    def test_the_inherited_license_is_named(self):
        self.assertEqual(self.upstream["license"], {"file": "LICENSE", "spdx": "MIT"})

    def test_the_clone_is_not_changed(self):
        self.assertIn("notes.txt", git(self.clone, "status", "--porcelain"))
        self.assertEqual(git(self.clone, "rev-parse", "HEAD"), self.clone_head)


class NestedCloneTest(CodeRepositoryCase):
    """A clone the owner put inside the project, recorded by an earlier commit as an empty gitlink."""

    def setUp(self):
        super().setUp()
        self.nested = self.project / "code"
        shutil.move(str(self.clone), str(self.nested))
        git(self.project, "add", "code")
        git(self.project, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "a wave commit")
        self.assertTrue(git(self.project, "ls-files", "--stage", "code").startswith("160000"))
        self.upstream = code_repository.absorb_clone(self.project, self.nested, run=self.run)

    def test_the_gitlink_is_gone_and_the_files_are_tracked(self):
        stage = git(self.project, "ls-files", "--stage", "--", "code").splitlines()
        self.assertEqual(len(stage), 2)
        self.assertTrue(all(line.startswith("100644") for line in stage))
        self.assertIn("empty gitlink", git(self.project, "log", "--format=%s", "main"))

    def test_the_clone_moved_out_of_the_tree(self):
        moved = self.project / ".clones" / "code"
        self.assertTrue((moved / ".git").is_dir())
        self.assertEqual(self.upstream["clone"], str(moved))
        self.assertFalse((self.project / "code" / ".git").exists())
        self.assertEqual(git(self.project, "status", "--porcelain", "--untracked-files=all", "--", ".clones", "code"), "")
        self.assertIn(".clones/", git(self.project, "show", "main:.gitignore").splitlines())
        self.assertEqual(git(self.project, "status", "--porcelain"), "M harness.json", "the .gitignore entry is committed")

    def test_a_failed_absorption_puts_the_clone_back(self):
        again = self.temp / "again"
        again.mkdir()
        init_project(again)
        nested = again / "analysis"
        shutil.copytree(self.project / ".clones" / "code", nested)
        before = git(again, "rev-parse", "main")

        def failing(argv, **kwargs):
            if "subtree" in [str(part) for part in argv]:
                return ToolOutput(1, b"", b"fatal: the recorded failure")
            return self.run(argv, **kwargs)

        with self.assertRaises(CodeRepositoryError) as caught:
            code_repository.absorb_clone(again, nested, run=failing)
        self.assertIn("the recorded failure", str(caught.exception))
        self.assertTrue((nested / ".git").is_dir(), "the clone is back where the owner put it")
        self.assertFalse((again / ".clones" / "analysis").exists())
        self.assertEqual(git(again, "rev-parse", "main"), before, "nothing reached main")
        self.assertEqual(git(again, "worktree", "list").count("\n"), 0, "the temporary worktree is gone")


class SplitTest(CodeRepositoryCase):
    """`git subtree split --prefix=code` cuts the code repository, which never holds the project's own files."""

    def setUp(self):
        super().setUp()
        self.absorb()
        for name in ("research/notes.md", "jobs/j1.json", "results/r.csv"):
            (self.project / name).parent.mkdir(parents=True, exist_ok=True)
            (self.project / name).write_text("project only\n")
        git(self.project, "add", "-A")
        git(self.project, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "the project's own files")

    def test_the_split_holds_code_alone(self):
        cut = code_repository.split(self.project, run=self.run)
        self.assertTrue(self.run.ran("subtree", "split", "--prefix=code", "main"))
        self.assertEqual(git(self.project, "ls-tree", "-r", "--name-only", cut).splitlines(), ["phaselock.m", "phaselock.py"])
        for name in ("research", "harness.json", "jobs", "results", "code"):
            self.assertNotIn(name, git(self.project, "ls-tree", "--name-only", cut).splitlines())

    def test_the_split_carries_the_upstream_history_unchanged(self):
        cut = code_repository.split(self.project, run=self.run)
        self.assertEqual(cut, self.clone_head, "an absorbed history splits back to the very commits it came with")

    def test_a_split_after_a_push_walks_only_what_main_gained_since(self):
        """The split cut since the last push equals the whole split, and git subtree is not handed `main` to walk."""
        last = {"commit": code_repository.split(self.project, run=self.run), "main": git(self.project, "rev-parse", "main")}
        for wave in range(12):
            (self.project / "research" / "notes.md").write_text("wave %d\n" % wave)
            git(self.project, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-am", "wayline: wave %d" % wave)
        (self.project / "code" / "phaselock.py").write_text("# changed by a ticket\n")
        git(self.project, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-am", "ticket 4: change it")
        self.run.calls.clear()
        cut = code_repository.split(self.project, run=self.run, since=last)
        split_calls = self.run.ran("subtree", "split", "--prefix=code")
        self.assertEqual(len(split_calls), 1)
        self.assertNotEqual(split_calls[0][-1], "main", "the walk starts at a join on the last push, not at the root")
        self.assertEqual(cut, code_repository.split(self.project, run=self.run), "the same split as the whole history gives")
        self.assertEqual(git(self.project, "rev-parse", "%s^" % cut), last["commit"])

    def test_a_last_push_main_no_longer_holds_falls_back_to_the_whole_split(self):
        cut = code_repository.split(self.project, run=self.run, since={"commit": self.clone_head, "main": "0" * 40})
        self.assertEqual(cut, self.clone_head)

    def test_a_project_without_code_has_no_split(self):
        bare = self.temp / "bare-project"
        bare.mkdir()
        init_project(bare)
        self.assertIsNone(code_repository.split(bare, run=self.run))


def gh_record(root):
    """A `tools.json` naming a `gh` at an absolute path that exists; nothing ever runs it."""
    executable = Path(root) / "bin" / "gh"
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_text("#!/bin/sh\nexit 99\n")
    return Tools(root, record={"tools": {"gh": {"executable": str(executable), "version": "2.95.0"}}})


class SettleTest(CodeRepositoryCase):
    """One setup question settles the shape, the remote, the visibility, and the license."""

    def setUp(self):
        super().setUp()
        self.remote = self.temp / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.remote)], check=True)
        self.tools = gh_record(self.temp / "tools")
        self.run = Runner({("repo", "create"): recorded("gh-repo-create.txt"),
                           ("repo", "edit"): ToolOutput(0, b"", b"")})

    def settle(self, answer, **kwargs):
        # The created repository's URL is GitHub's; the push goes to a local bare repository in its place.
        return code_repository.settle(self.project, answer, run=self.run, tools=self.tools,
                                      push_url=lambda remote: str(self.remote), **kwargs)

    def test_a_new_private_repository_is_created_with_gh_and_recorded(self):
        self.absorb()
        settled = self.settle({"shape": "package", "license": "MIT"})
        created = self.run.ran("repo", "create")
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0][0], str(self.temp / "tools" / "bin" / "gh"), "gh runs by its recorded executable")
        self.assertIn("--private", created[0])
        self.assertNotIn("--public", created[0])
        self.assertNotIn("fork", " ".join(created[0]))
        record = read_harness(self.project)["code_repository"]
        self.assertEqual(record, settled)
        self.assertEqual((record["shape"], record["visibility"], record["license"]), ("package", "private", "MIT"))
        self.assertEqual(record["remote"], {"repository": "jpbernal/lantern", "url": "https://github.com/jpbernal/lantern",
                                            "how": "copy", "branch": "main"})

    def test_the_first_push_carries_the_split_and_its_upstream_history(self):
        self.absorb()
        self.settle({"shape": "reproducibility"})
        self.assertTrue(self.run.ran("push", str(self.remote), "%s:refs/heads/main" % self.clone_head))
        self.assertEqual(git(self.remote, "rev-parse", "main"), self.clone_head)
        self.assertEqual(len(git(self.remote, "log", "--format=%s", "main").splitlines()), 3)

    def test_without_a_clone_the_repository_is_new_and_named_after_the_project(self):
        (self.project / "code").mkdir()
        (self.project / "code" / "README.md").write_text("# lantern\n")
        git(self.project, "add", "code")
        git(self.project, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "code: start")
        record = self.settle({"shape": "package"})
        self.assertEqual(self.run.ran("repo", "create")[0][3], "lantern")
        self.assertEqual(record["remote"]["how"], "new")
        self.assertIsNone(record["license"])

    def test_the_license_defaults_to_the_inherited_one(self):
        (self.clone / "LICENSE").write_text("Apache License\nVersion 2.0, January 2004\n")
        git(self.clone, "add", "LICENSE")
        git(self.clone, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "license")
        self.absorb()
        self.assertEqual(self.settle({"shape": "package"})["license"], "Apache-2.0")

    def test_a_shape_outside_the_two_is_refused(self):
        with self.assertRaises(CodeRepositoryError):
            self.settle({"shape": "monorepo"})

    def test_a_second_answer_keeps_the_remote_and_creates_nothing(self):
        self.absorb()
        self.settle({"shape": "package"})
        record = self.settle({"shape": "reproducibility"})
        self.assertEqual(len(self.run.ran("repo", "create")), 1)
        self.assertEqual(record["shape"], "reproducibility")

    def test_a_taken_over_repository_not_the_owners_gets_a_new_private_copy_with_its_history(self):
        git(self.clone, "remote", "add", "origin", "https://github.com/ines-varga/phaselock.git")
        self.absorb()
        self.run.gh[("repo", "view")] = recorded("gh-repo-view-theirs.json")
        record = self.settle({"shape": "package", "remote": "ines-varga/phaselock"})
        self.assertEqual(self.run.ran("repo", "create")[0][3:5], ["phaselock", "--private"])
        self.assertEqual(record["remote"]["how"], "copy")
        self.assertEqual(record["remote"]["repository"], "jpbernal/lantern")
        self.assertFalse(self.run.ran("repo", "fork"))
        self.assertEqual(git(self.remote, "log", "--format=%H", "main").splitlines()[-3:],
                         git(self.clone, "log", "--format=%H", "main").splitlines(), "the copy carries the upstream's commits")

    def test_a_repository_not_the_owners_and_not_absorbed_is_refused(self):
        self.absorb()  # the synthetic clone has no remote, so it is not ines-varga/phaselock
        self.run.gh[("repo", "view")] = recorded("gh-repo-view-theirs.json")
        with self.assertRaises(CodeRepositoryError) as caught:
            self.settle({"shape": "package", "remote": "ines-varga/phaselock"})
        self.assertIn("absorb", str(caught.exception))
        self.assertFalse(self.run.ran("repo", "create"))
        self.assertNotIn("remote", read_harness(self.project)["code_repository"])

    def test_the_owners_own_private_repository_is_taken_over_on_their_word(self):
        self.absorb()
        self.run.gh[("repo", "view")] = recorded("gh-repo-view-own-private.json")
        record = self.settle({"shape": "package", "remote": "jpbernal/phaselock"})
        self.assertFalse(self.run.ran("repo", "create"))
        self.assertEqual(record["remote"], {"repository": "jpbernal/phaselock", "url": "https://github.com/jpbernal/phaselock",
                                            "how": "owners_own", "branch": "master"})
        self.assertEqual(record["visibility"], "private")
        self.assertTrue(self.run.ran("push", str(self.remote), "%s:refs/heads/master" % self.clone_head),
                        "the push goes to the repository's default branch")
        self.assertEqual(git(self.remote, "branch", "--format=%(refname:short)"), "master")

    def test_the_owners_own_repository_holding_other_history_is_refused_before_anything_is_recorded(self):
        self.absorb()
        stray = self.temp / "stray"
        subprocess.run(["git", "init", "-q", "-b", "master", str(stray)], check=True)
        (stray / "x.txt").write_text("not the absorbed history\n")
        git(stray, "add", "x.txt")
        git(stray, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "other history")
        git(stray, "push", "-q", str(self.remote), "master")
        self.run.gh[("repo", "view")] = recorded("gh-repo-view-own-private.json")
        with self.assertRaises(CodeRepositoryError) as caught:
            self.settle({"shape": "package", "remote": "jpbernal/phaselock"})
        self.assertIn("master", str(caught.exception))
        self.assertNotIn("remote", read_harness(self.project)["code_repository"])
        self.assertFalse(self.run.ran("push"))

    def test_the_owners_own_public_repository_is_confirmed_once(self):
        self.absorb()
        self.run.gh[("repo", "view")] = recorded("gh-repo-view-own-public.json")
        with self.assertRaises(CodeRepositoryError) as caught:
            self.settle({"shape": "package", "remote": "jpbernal/phaselock"})
        self.assertIn("public", str(caught.exception))
        self.assertNotIn("remote", read_harness(self.project)["code_repository"])
        record = self.settle({"shape": "package", "remote": "jpbernal/phaselock", "confirm_public": True})
        self.assertEqual((record["remote"]["how"], record["remote"]["confirmed_public"], record["visibility"]),
                         ("owners_own", True, "public"))

    def test_public_at_setup_is_the_owners_word_and_runs_after_the_private_push(self):
        self.absorb()
        record = self.settle({"shape": "package", "visibility": "public"})
        create, = self.run.ran("repo", "create")
        edit, = self.run.ran("repo", "edit")
        self.assertIn("--private", create)
        self.assertEqual(edit[3:6], ["jpbernal/lantern", "--visibility", "public"])
        self.assertLess(self.run.calls.index(create), self.run.calls.index(edit))
        self.assertEqual(record["visibility"], "public")

    def test_making_it_public_later_is_the_owners_word_only(self):
        self.absorb()
        self.settle({"shape": "package"})
        for who in ("decider", "code", "worker"):
            with self.subTest(by=who), self.assertRaises(CodeRepositoryError) as caught:
                code_repository.make_public(self.project, by=who, run=self.run, tools=self.tools)
            self.assertIn("irreversible", str(caught.exception))
        self.assertFalse(self.run.ran("repo", "edit"))
        self.assertEqual(read_harness(self.project)["code_repository"]["visibility"], "private")
        code_repository.make_public(self.project, by="owner", run=self.run, tools=self.tools)
        self.assertEqual(len(self.run.ran("repo", "edit", "jpbernal/lantern", "--visibility", "public")), 1)
        self.assertEqual(read_harness(self.project)["code_repository"]["visibility"], "public")

    def test_gh_failing_records_no_remote(self):
        self.absorb()
        self.run.gh[("repo", "create")] = ToolOutput(1, b"", b"GraphQL: Name already exists on this account (createRepository)")
        with self.assertRaises(CodeRepositoryError) as caught:
            self.settle({"shape": "package"})
        self.assertIn("Name already exists", str(caught.exception))
        self.assertNotIn("remote", read_harness(self.project)["code_repository"])


class PushAfterTheWaveTest(ProjectTestCase):
    """A replayed journal that already pushed `code/`, then a wave that changed it and one that did not."""

    def setUp(self):
        super().setUp()
        self.project = self.temp / "one-ticket"
        shutil.copytree(ONE_TICKET, self.project)
        init_project(self.project)
        (self.project / "code").mkdir()
        (self.project / "code" / "README.md").write_text("# one ticket\n")
        self.remote = self.temp / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.remote)], check=True)
        harness = read_harness(self.project)
        harness["code_repository"] = {"shape": "reproducibility", "visibility": "private", "license": "MIT",
                                      "remote": {"repository": "jpbernal/one-ticket", "url": str(self.remote), "how": "new"}}
        (self.project / "harness.json").write_text(json.dumps(harness, indent=2) + "\n")
        git(self.project, "add", "code", "harness.json")
        git(self.project, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "code: start")
        self.run = Runner()
        # The journal a restart replays: the split was pushed by an earlier run.
        self.first = code_repository.push(self.project, code_repository.split(self.project), str(self.remote),
                                          "jpbernal/one-ticket", run=self.run)
        self.run.calls.clear()

    def pushes(self):
        return [event["payload"] for event in Ledger(self.project).read_events()[0] if event["event"] == "code_pushed"]

    def conduct(self, files):
        with worker.use_fake() as fake:
            fake.script(done(outputs_written=sorted(files)), patch=Patch(files=files, message="ticket 1: write it"))
            self.conductor = Conductor(self.project, out=io.StringIO())
            self.conductor.readings = machine.recorded
            self.conductor.code_run = self.run
            return drive(self.conductor)

    def code_ticket(self):
        path = tickets_dir(self.project) / "01-write-the-hello-file.md"
        path.write_text(path.read_text().replace("hello.txt", "code/hello.txt"))
        git(self.project, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-am", "the ticket writes under code/")

    def test_a_wave_that_did_not_change_code_pushes_nothing(self):
        results = self.conduct({"hello.txt": "hello\n"})
        self.assertTrue(results[-1].ended)
        self.assertIn("ticket 1: write it", git(self.project, "log", "--format=%s", "main"))
        self.assertFalse(self.run.ran("push"))
        self.assertEqual([push["commit"] for push in self.pushes()], [self.first])

    def test_a_wave_that_changed_code_pushes_its_split_once(self):
        self.code_ticket()
        results = self.conduct({"code/hello.txt": "hello\n"})
        self.assertTrue(results[-1].ended)
        self.assertGreater(len(results), 1, "the waves after the one that pushed find nothing to push")
        cut = code_repository.split(self.project)
        self.assertNotEqual(cut, self.first)
        self.assertEqual(len(self.run.ran("push", str(self.remote), "%s:refs/heads/main" % cut)), 1)
        self.assertEqual(len(self.run.ran("push")), 1)
        self.assertEqual([(push["commit"], push["remote"]) for push in self.pushes()],
                         [(self.first, "jpbernal/one-ticket"), (cut, "jpbernal/one-ticket")])
        cut_from = self.pushes()[-1]["main"]  # the main the split was cut from, which the next split starts after
        git(self.project, "merge-base", "--is-ancestor", cut_from, "main")
        self.assertEqual(git(self.project, "rev-parse", cut_from + ":code"), git(self.project, "rev-parse", cut + "^{tree}"))
        self.assertEqual(git(self.remote, "rev-parse", "main"), cut)
        self.assertEqual(git(self.remote, "show", "main:hello.txt"), "hello")
        self.assertNotIn("research", git(self.remote, "ls-tree", "--name-only", "main").splitlines())

    def test_the_ticket_launch_carries_the_commit_of_main_it_ran_at(self):
        at = git(self.project, "rev-parse", "main")
        self.conduct({"hello.txt": "hello\n"})
        launched, = [event["payload"] for event in Ledger(self.project).read_events()[0] if event["event"] == "ticket_launched"]
        self.assertEqual(launched["commit"], at)
        self.assertNotEqual(git(self.project, "rev-parse", "main"), at, "main moved on after the launch")

    def test_a_launch_on_a_branch_an_earlier_attempt_left_records_that_branch(self):
        """An attempt that reuses `ticket/<id>` runs on its commit, not on main's tip."""
        older = git(self.project, "rev-parse", "main")
        git(self.project, "branch", "ticket/1", older)
        (self.project / "elsewhere.txt").write_text("main moved on\n")
        git(self.project, "add", "elsewhere.txt")
        git(self.project, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "main moves on")
        self.conduct({"hello.txt": "hello\n"})
        launched, = [event["payload"] for event in Ledger(self.project).read_events()[0] if event["event"] == "ticket_launched"]
        self.assertEqual(launched["commit"], older)

    def test_a_rejected_push_is_told_to_the_owner_once_and_not_retried(self):
        stray = self.temp / "stray"
        subprocess.run(["git", "clone", "-q", str(self.remote), str(stray)], check=True)
        (stray / "x.txt").write_text("pushed by someone else\n")
        git(stray, "add", "x.txt")
        git(stray, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "someone else")
        git(stray, "push", "-q", "origin", "main")
        self.code_ticket()
        told = []
        with worker.use_fake() as fake:
            fake.script(done(outputs_written=["code/hello.txt"]), patch=Patch(files={"code/hello.txt": "hello\n"}, message="t"))
            self.conductor = Conductor(self.project, out=io.StringIO())
            self.conductor.readings = machine.recorded
            self.conductor.code_run = self.run
            self.conductor.notify = lambda event, text, *args, **kwargs: told.append((event, text))
            drive(self.conductor)
            self.conductor.wave()
        self.assertEqual(len(self.run.ran("push")), 1, "a rejected split is not pushed again every wave")
        self.assertEqual([event for event, _ in told], ["code_push_rejected"])
        self.assertIn("jpbernal/one-ticket", told[0][1])
        self.assertEqual(len(self.pushes()), 1)

    def test_a_restart_replays_the_last_push_and_pushes_nothing_more(self):
        self.code_ticket()
        self.conduct({"code/hello.txt": "hello\n"})
        self.run.calls.clear()
        with worker.use_fake():
            again = Conductor(self.project, out=io.StringIO())
            again.readings = machine.recorded
            again.code_run = self.run
            again.wave()
        self.assertFalse(self.run.ran("push"))
        self.assertEqual(len(self.pushes()), 2)


class JobLaunchCommitTest(ProjectTestCase):
    """Every job records the commit of `main` it ran at, so a result traces to the code that made it."""

    def launched(self, project):
        with resources.use_fake_jobs() as fake:
            fake.script(["running"])
            resources.JobRunner(project, backend=fake).launch(job_spec(project, cwd=str(project), log=str(project / "t19-1.log")))
        return [event["payload"] for event in Ledger(project).read_events()[0] if event["event"] == "job_launched"][-1]

    def test_job_launched_carries_main(self):
        project = self.temp / "p"
        project.mkdir()
        init_project(project)
        self.assertEqual(self.launched(project)["commit"], git(project, "rev-parse", "main"))

    def test_a_job_in_a_worktree_records_the_worktree_commit(self):
        project = self.temp / "p"
        project.mkdir()
        init_project(project)
        older = git(project, "rev-parse", "main")
        (project / "later.txt").write_text("later\n")
        git(project, "add", "later.txt")
        git(project, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "later")
        worktree = project / ".worktrees" / "7"
        git(project, "worktree", "add", "-q", "--detach", str(worktree), older)
        with resources.use_fake_jobs() as fake:
            fake.script(["running"])
            resources.JobRunner(project, backend=fake).launch(job_spec(project, cwd=str(worktree), log=str(project / "j.log")))
        launched = [event["payload"] for event in Ledger(project).read_events()[0] if event["event"] == "job_launched"][-1]
        self.assertEqual(launched["commit"], older)

    def test_a_project_with_no_repository_records_no_commit(self):
        project = self.temp / "p"
        project.mkdir()
        init_project(project, git=False)
        self.assertNotIn("commit", self.launched(project))
