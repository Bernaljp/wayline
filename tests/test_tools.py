"""The harness's tools: their routes, `tools.json`, and `wayline tools install|show|run` (ticket 75).

Every install runs against `Machine`, a recorded runner standing in for the tool runner (seam 6,
after `tests/test_pdf_inventory.py`'s): `curl` answers from a table of downloads, micromamba and
uv lay down the files their real counterparts would, and every `--version` answers with what the
program printed on the owner's workstation (`fixtures/tools/recorded/`). Nothing is downloaded
and nothing is written under the owner's `~/.wayline/tools`: each test installs into a temporary
directory.
"""

import contextlib
import hashlib
import io
import json
import os
import tarfile
import threading
import unittest
from pathlib import Path

from tests.paths import FIXTURES_DIR
from tests.projects import ProjectTestCase
from wayline import cli
from wayline import tools as tools_module
from wayline.tools import (
    MODEL, MODEL_FILES, MODEL_REVISION, SYSTEM_TOOLS, TOOLS_JSON, ToolOutput, Tools, ToolsError,
    install_tool, micromamba_url, model_tree_url, model_url, record_entry, run_recorded, uv_url,
)

RECORDED = FIXTURES_DIR / "tools" / "recorded"


def recorded(name):
    return (RECORDED / name).read_bytes()


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def git_blob_sha1(data):
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def uv_tarball():
    """A tarball laid out as uv's release is: one folder holding `uv` and `uvx`."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name in ("uv", "uvx"):
            body = b"#!/bin/sh\necho %s\n" % name.encode()
            info = tarfile.TarInfo("uv-x86_64-unknown-linux-gnu/%s" % name)
            info.size, info.mode = len(body), 0o755
            tar.addfile(info, io.BytesIO(body))
    return buffer.getvalue()


def model_downloads():
    """The model's files at the pinned revision and the tree listing that publishes their digests."""
    files = {path: ("weights of %s" % path).encode() for path in MODEL_FILES}
    tree = []
    for path, body in files.items():
        entry = {"type": "file", "path": path, "size": len(body), "oid": git_blob_sha1(body)}
        if path.endswith(".safetensors"):
            entry["lfs"] = {"oid": sha256(body), "size": len(body)}
        tree.append(entry)
    downloads = {model_url(path): body for path, body in files.items()}
    downloads[model_tree_url()] = json.dumps(tree).encode()
    return downloads


def published_downloads():
    """Every download of the harness's tools, with the digest each publisher publishes beside it."""
    micromamba = b"\x7fELF micromamba"
    uv = uv_tarball()
    downloads = {
        micromamba_url(): micromamba,
        micromamba_url() + ".sha256": (sha256(micromamba) + "\n").encode(),
        uv_url(): uv,
        uv_url() + ".sha256": ("%s  uv-x86_64-unknown-linux-gnu.tar.gz\n" % sha256(uv)).encode(),
    }
    downloads.update(model_downloads())
    return downloads


class Machine:
    """The tool runner's recordings: what each program the install starts answered on the workstation."""

    def __init__(self, downloads=None, fail=None, versions=None):
        self.downloads = published_downloads() if downloads is None else downloads
        self.fail = fail or (lambda argv: False)
        self.calls = []
        self.versions = {"matplotlib": "3.10.7", "seaborn": "0.13.2", "tree-sitter": "0.26.0", "tree-sitter-matlab": "1.3.1"}
        self.versions.update(versions or {})

    def __call__(self, argv, cwd=None, timeout=None, env=None):
        argv = [str(part) for part in argv]
        self.calls.append((argv, dict(env or {})))
        name = Path(argv[0]).name
        if self.fail(argv):
            return ToolOutput(1, b"", b"error: the recorded failure")
        if name == "curl":
            body = self.downloads.get(argv[-1])
            if body is None:
                return ToolOutput(22, b"", b"curl: (22) The requested URL returned error: 404")
            if "-o" in argv:
                Path(argv[argv.index("-o") + 1]).write_bytes(body)
                return ToolOutput(0, b"", b"")
            return ToolOutput(0, body, b"")
        if argv[1:] == ["--version"] and name in ("micromamba", "uv", "pandoc", "pandoc-crossref"):
            return ToolOutput(0, recorded("%s--version.txt" % name), b"")
        if name == "micromamba" and argv[1] in ("create", "install"):
            prefix = Path(argv[argv.index("-p") + 1])
            (prefix / "bin").mkdir(parents=True, exist_ok=True)
            for program in ("pandoc", "pandoc-crossref"):
                (prefix / "bin" / program).write_text("#!/bin/sh\n", encoding="utf-8")
            return ToolOutput(0, b"", b"")
        if name == "micromamba" and argv[1:3] == ["env", "export"]:
            return ToolOutput(0, recorded("micromamba-env-export.txt"), b"")
        if name == "uv" and argv[1] == "venv":
            python = Path(argv[-1]) / "bin" / "python"
            python.parent.mkdir(parents=True, exist_ok=True)
            python.write_text("#!/bin/sh\n", encoding="utf-8")
            return ToolOutput(0, b"", b"")
        if name == "uv" and argv[1:3] == ["pip", "install"]:
            return ToolOutput(0, b"", b"")
        if name == "uv" and argv[1:3] == ["pip", "freeze"]:
            return ToolOutput(0, b"".join(b"%s==%s\n" % (k.encode(), v.encode()) for k, v in sorted(self.versions.items())), b"")
        if name == "python" and len(argv) > 2 and argv[1] == "-c":
            return ToolOutput(0, (json.dumps({"packages": self.versions, "device": None}) + "\n").encode(), b"")
        if name in SYSTEM_TOOLS:
            return ToolOutput(0, recorded("%s--version.txt" % name), b"")
        return ToolOutput(127, b"", ("%s: nothing recorded" % name).encode())

    def ran(self, program):
        return [(argv, env) for argv, env in self.calls if Path(argv[0]).name == program]


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


class HarnessToolsTest(ProjectTestCase):
    def setUp(self):
        super().setUp()
        self.root = self.temp / "tools"
        self.machine = Machine()

    def install(self, name, machine=None, **options):
        return install_tool(name, root=self.root, run=machine or self.machine, **options)

    def entry(self, name):
        return read_json(self.root / TOOLS_JSON)["tools"][name]

    def test_micromamba_is_its_static_binary_with_its_folders_under_the_tools_home(self):
        self.install("micromamba")
        entry = self.entry("micromamba")
        binary = self.root / "bin" / "micromamba"
        self.assertEqual(entry["executable"], str(binary))
        self.assertTrue(os.access(binary, os.X_OK))
        self.assertEqual(entry["version"], "2.9.0")
        self.assertEqual(entry["env"], {"MAMBA_ROOT_PREFIX": str(self.root / "mamba"), "CONDA_PKGS_DIRS": str(self.root / "mamba" / "pkgs")})
        self.assertEqual(entry["route"], "release")
        self.assertEqual(entry["digest"], "sha256:" + sha256(self.machine.downloads[micromamba_url()]))
        self.assertEqual(entry["installer"], "harness")
        self.assertTrue(entry["installed"])

    def test_a_download_whose_digest_does_not_match_is_refused_and_nothing_is_kept(self):
        downloads = published_downloads()
        downloads[micromamba_url() + ".sha256"] = (sha256(b"another build") + "\n").encode()
        with self.assertRaises(ToolsError) as caught:
            self.install("micromamba", Machine(downloads))
        self.assertIn("digest mismatch", str(caught.exception))
        self.assertFalse((self.root / "bin" / "micromamba").exists())
        self.assertEqual(list((self.root / "bin").iterdir()), [], "the partial download is removed")
        self.assertIsNone(Tools(self.root).entry("micromamba"))

    def test_uv_is_its_release_binary_with_its_cache_under_the_tools_home(self):
        self.install("uv")
        entry = self.entry("uv")
        self.assertEqual(entry["executable"], str(self.root / "bin" / "uv"))
        self.assertTrue(os.access(self.root / "bin" / "uvx", os.X_OK))
        self.assertEqual(entry["version"], "0.12.24")
        self.assertEqual(entry["env"]["UV_CACHE_DIR"], str(self.root / "uv" / "cache"))
        self.assertEqual(entry["env"]["UV_PYTHON_INSTALL_DIR"], str(self.root / "uv" / "python"))
        self.assertEqual(entry["digest"], "sha256:" + sha256(self.machine.downloads[uv_url()]))
        self.assertFalse((self.root / "bin" / "uv-x86_64-unknown-linux-gnu").exists())

    def test_a_tool_recorded_from_the_same_source_is_not_downloaded_again(self):
        self.install("uv")
        before = len(self.machine.ran("curl"))
        self.install("uv")
        self.assertEqual(len(self.machine.ran("curl")), before)

    def test_a_python_package_goes_into_the_tools_venv_through_the_harness_uv(self):
        self.install("matplotlib")
        uv = str(self.root / "bin" / "uv")
        python = str(self.root / "venv" / "bin" / "python")
        commands = [argv for argv, _ in self.machine.ran("uv")]
        self.assertIn([uv, "venv", "--python", tools_module.sys.executable, str(self.root / "venv")], commands)
        self.assertIn([uv, "pip", "install", "--python", python, "matplotlib"], commands)
        for argv, env in self.machine.ran("uv"):
            self.assertEqual(env.get("UV_CACHE_DIR"), str(self.root / "uv" / "cache"), argv)
        entry = self.entry("matplotlib")
        self.assertEqual((entry["executable"], entry["version"], entry["route"]), (python, "3.10.7", "uv"))
        self.assertEqual(entry["env"], {"MPLBACKEND": "Agg"})
        lock = Path(entry["lock"]["path"])
        self.assertIn("matplotlib==3.10.7", lock.read_text(encoding="utf-8"))
        self.assertEqual(entry["lock"]["sha256"], sha256(lock.read_bytes()))

    def test_no_python_package_ever_goes_through_python_m_venv_or_pip(self):
        for name in ("matplotlib", "seaborn", "tree-sitter-matlab"):
            self.install(name)
        for argv, _ in self.machine.calls:
            self.assertFalse(argv[1:3] == ["-m", "venv"] or argv[1:3] == ["-m", "pip"], argv)
        self.assertIn(["tree-sitter", "tree-sitter-matlab"], [argv[-2:] for argv, _ in self.machine.ran("uv")])
        self.assertEqual((self.entry("seaborn")["version"], self.entry("tree-sitter-matlab")["version"]), ("0.13.2", "1.3.1"))
        self.assertEqual(self.entry("tree-sitter-matlab")["packages"], {"tree-sitter": "0.26.0", "tree-sitter-matlab": "1.3.1"})

    def test_pandoc_and_pandoc_crossref_come_from_conda_forge_into_their_own_prefix(self):
        self.install("pandoc")
        micromamba = str(self.root / "bin" / "micromamba")
        prefix = self.root / "envs" / "pandoc"
        solves = [(argv, env) for argv, env in self.machine.ran("micromamba") if argv[1] in ("create", "install")]
        common = ["-y", "-p", str(prefix), "-c", "conda-forge", "--override-channels"]
        self.assertEqual([argv for argv, _ in solves], [
            [micromamba, "create"] + common + ["pandoc=3.11"],
            [micromamba, "install"] + common + ["--no-deps", "pandoc-crossref"],
        ])
        for _, env in solves:
            self.assertEqual(env["MAMBA_ROOT_PREFIX"], str(self.root / "mamba"))
            self.assertEqual(env["CONDA_PKGS_DIRS"], str(self.root / "mamba" / "pkgs"))
        pandoc, crossref = self.entry("pandoc"), self.entry("pandoc-crossref")
        self.assertEqual(pandoc["executable"], str(prefix / "bin" / "pandoc"))
        self.assertEqual(crossref["executable"], str(prefix / "bin" / "pandoc-crossref"))
        self.assertEqual((pandoc["route"], pandoc["source"]), ("micromamba", "conda-forge"))
        self.assertEqual((pandoc["version"], crossref["version"], crossref["built_with"]), ("3.11", "0.3.25", "3.11"))
        self.assertNotIn("note", crossref)
        lock = Path(pandoc["lock"]["path"])
        self.assertTrue(lock.read_text(encoding="utf-8").startswith("# This file may be used"))
        self.assertIn("@EXPLICIT", lock.read_text(encoding="utf-8"))
        self.assertEqual(pandoc["lock"], crossref["lock"])

    def test_a_pandoc_crossref_built_for_another_pandoc_says_so_in_its_entry(self):
        machine = Machine()
        answer = machine.__call__

        def run(argv, cwd=None, timeout=None, env=None):
            if Path(str(argv[0])).name == "pandoc-crossref":
                return ToolOutput(0, b"pandoc-crossref v0.3.25 git commit UNKNOWN (UNKNOWN) built with Pandoc v3.9.0.2, pandoc-types v1.23.1\n", b"")
            return answer(argv, cwd, timeout, env)

        install_tool("pandoc", root=self.root, run=run)
        self.assertEqual(self.entry("pandoc-crossref")["note"], "built with pandoc 3.9.0.2, run through pandoc 3.11")

    def test_an_existing_prefix_is_installed_into_rather_than_created(self):
        self.install("pandoc")
        os.remove(self.root / "envs" / "pandoc" / "bin" / "pandoc")
        self.install("pandoc-crossref")
        verbs = [argv[1] for argv, _ in self.machine.ran("micromamba") if argv[1] in ("create", "install")]
        self.assertEqual(verbs, ["create", "install", "install", "install"])

    def test_the_embedding_model_comes_at_its_pinned_revision_each_file_checked(self):
        self.install("embedding-model")
        entry = self.entry("embedding-model")
        folder = self.root / "models" / "BAAI--bge-base-en-v1.5"
        self.assertEqual(entry["path"], str(folder))
        self.assertEqual((entry["model"], entry["revision"], entry["route"]), (MODEL, MODEL_REVISION, "huggingface"))
        self.assertEqual(entry["executable"], str(self.root / "venv" / "bin" / "python"))
        self.assertTrue(Path(entry["executable"]).exists(), "the interpreter the entry names is there")
        self.assertEqual(entry["env"], {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"})
        for path in MODEL_FILES:
            self.assertEqual((folder / path).read_bytes(), self.machine.downloads[model_url(path)])
        self.assertIn(MODEL_REVISION, model_url("config.json"))

    def test_a_model_file_that_differs_from_the_published_digest_fails_the_model(self):
        downloads = published_downloads()
        downloads[model_url("vocab.txt")] = b"a vocabulary someone changed"
        with self.assertRaises(ToolsError) as caught:
            self.install("embedding-model", Machine(downloads))
        self.assertIn("digest mismatch", str(caught.exception))
        self.assertIn("vocab.txt", str(caught.exception))
        self.assertFalse((self.root / "models" / "BAAI--bge-base-en-v1.5" / "vocab.txt").exists())
        self.assertIsNone(Tools(self.root).entry("embedding-model"))

    def test_model_files_already_there_and_matching_are_not_downloaded_again(self):
        self.install("embedding-model")
        before = len(self.machine.ran("curl"))
        self.install("embedding-model")
        self.assertEqual(len(self.machine.ran("curl")), before + 1, "only the listing is fetched again")

    def system_paths(self, absent=()):
        """Stand-ins for the machine's own programs, found where `which` would find them."""
        folder = self.temp / "usr" / "bin"
        folder.mkdir(parents=True, exist_ok=True)
        paths = {}
        for name in SYSTEM_TOOLS:
            if name not in absent:
                (folder / name).write_text("#!/bin/sh\n", encoding="utf-8")
                paths[name] = str(folder / name)
        return paths

    def test_latex_poppler_libreoffice_and_git_are_recorded_as_system_by_absolute_path(self):
        paths = self.system_paths()
        before = {name: Path(path).read_bytes() for name, path in paths.items()}
        for name in SYSTEM_TOOLS:
            install_tool(name, root=self.root, run=self.machine, which=paths.get)
        for name, path in paths.items():
            entry = self.entry(name)
            self.assertEqual((entry["executable"], entry["installer"], entry["route"]), (path, "system", "system"))
            self.assertEqual(Path(path).read_bytes(), before[name], "a system tool is never changed")
        self.assertEqual(self.entry("git")["version"], "2.43.0")
        self.assertEqual(self.entry("pdfinfo")["version"], "24.02.0")
        self.assertEqual(self.entry("latexmk")["version"], "4.83")
        self.assertEqual(self.entry("soffice")["version"], "24.2.7.2")
        self.assertEqual(self.entry("pdflatex")["version"], "3.141592653-2.6-1.40.25")
        self.assertEqual(sorted(argv[1] for argv, _ in self.machine.calls), sorted(SYSTEM_TOOLS.values()), "only each version flag ran")

    def test_a_system_tool_the_machine_lacks_is_an_error_and_records_nothing(self):
        with self.assertRaises(ToolsError) as caught:
            install_tool("soffice", root=self.root, run=self.machine, which=self.system_paths(absent=("soffice",)).get)
        self.assertIn("not on this machine", str(caught.exception))
        self.assertIsNone(Tools(self.root).entry("soffice"))

    def test_an_owner_entry_is_never_replaced_by_a_system_record(self):
        record_entry(self.root, "git", tools_module.tool_entry("/opt/git/bin/git", "2.47.0", "owner", installer="owner"))
        install_tool("git", root=self.root, run=self.machine, which=self.system_paths().get)
        self.assertEqual((self.entry("git")["executable"], self.entry("git")["installer"]), ("/opt/git/bin/git", "owner"))
        self.assertEqual(self.machine.calls, [])


class InstallEverythingTest(ProjectTestCase):
    def setUp(self):
        super().setUp()
        self.root = self.temp / "tools"
        folder = self.temp / "usr" / "bin"
        folder.mkdir(parents=True)
        self.which = {}
        for name in SYSTEM_TOOLS:
            if name != "soffice":
                (folder / name).write_text("#!/bin/sh\n", encoding="utf-8")
                self.which[name] = str(folder / name)

    def install_all(self, machine):
        return tools_module.install_all(root=self.root, run=machine, which=self.which.get)

    def test_the_install_puts_every_harness_tool_in_the_record_and_the_system_ones_beside(self):
        results = self.install_all(Machine())
        record = read_json(self.root / TOOLS_JSON)
        harness = ["micromamba", "uv", "matplotlib", "seaborn", "tree-sitter-matlab", "pandoc", "pandoc-crossref", "embedding-model"]
        for name in harness:
            self.assertEqual(record["tools"][name]["installer"], "harness", name)
        self.assertEqual(record["packages"]["tree-sitter-matlab"], "1.3.1", "the converter venv's own fields are there too")
        self.assertEqual(record["tools"]["git"]["installer"], "system")
        self.assertEqual(results["soffice"][0], "absent")
        self.assertEqual({results[name][0] for name in harness}, {"installed"})

    def test_a_digest_mismatch_fails_that_tool_alone(self):
        downloads = published_downloads()
        downloads[model_url("model.safetensors")] = b"weights from somewhere else"
        results = self.install_all(Machine(downloads))
        self.assertEqual(results["embedding-model"][0], "failed")
        self.assertIn("digest mismatch", results["embedding-model"][1])
        names = Tools(self.root).names()
        self.assertNotIn("embedding-model", names)
        for name in ("micromamba", "uv", "matplotlib", "pandoc", "pandoc-crossref", "git"):
            self.assertIn(name, names)

    def test_a_tool_whose_installer_failed_takes_down_only_what_is_installed_through_it(self):
        downloads = published_downloads()
        downloads[micromamba_url() + ".sha256"] = (sha256(b"a different binary") + "\n").encode()
        results = self.install_all(Machine(downloads))
        self.assertEqual([results[name][0] for name in ("micromamba", "pandoc", "pandoc-crossref")], ["failed"] * 3)
        self.assertEqual([results[name][0] for name in ("uv", "matplotlib", "embedding-model")], ["installed"] * 3)


def cli_run(*args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(["tools"] + list(args))
    return code, out.getvalue(), err.getvalue()


class ToolsVerbsTest(ProjectTestCase):
    def setUp(self):
        super().setUp()
        self.root = Path(os.environ["WAYLINE_HOME"]) / "tools"

    def test_tools_run_calls_the_recorded_executable_with_its_environment(self):
        calls = []

        def run(argv, cwd=None, timeout=None, env=None):
            calls.append(([str(part) for part in argv], env))
            return ToolOutput(0, b"pandoc 3.11\n", b"")

        record_entry(self.root, "pandoc", tools_module.tool_entry("/opt/tools/envs/pandoc/bin/pandoc", "3.11", "micromamba", env={"LANG": "C.UTF-8"}))
        done = run_recorded("pandoc", ["--version"], tools=Tools(self.root), run=run, exists=lambda path: True)
        self.assertEqual(done.returncode, 0)
        self.assertEqual(calls, [(["/opt/tools/envs/pandoc/bin/pandoc", "--version"], {"LANG": "C.UTF-8"})])

    def test_tools_run_refuses_a_tool_not_recorded(self):
        with self.assertRaises(ToolsError) as caught:
            run_recorded("octave", [], tools=Tools(self.root), run=lambda *a, **k: self.fail("nothing runs"))
        self.assertIn("not recorded", str(caught.exception))
        code, _, err = cli_run("run", "octave", "--", "--version")
        self.assertEqual(code, 2)
        self.assertIn("octave is not recorded", err)
        self.assertNotIn("wayline tools install octave", err, "the harness does not install a project's tools")
        code, _, err = cli_run("run", "pandoc", "--", "--version")
        self.assertEqual(code, 2)
        self.assertIn("wayline tools install pandoc", err)

    def test_tools_run_refuses_a_recorded_executable_that_is_gone(self):
        record_entry(self.root, "pandoc", tools_module.tool_entry(self.temp / "gone" / "pandoc", "3.11", "micromamba"))
        code, _, err = cli_run("run", "pandoc", "--", "--version")
        self.assertEqual(code, 2)
        self.assertIn("no longer there", err)

    def test_tools_run_from_the_command_line_runs_by_absolute_path_and_environment(self):
        record_entry(self.root, "probe", tools_module.tool_entry("/bin/sh", "1", "system", env={"WAYLINE_PROBE": "from the record"}, installer="system"))
        code, out, _ = cli_run("run", "probe", "--", "-c", "echo \"$WAYLINE_PROBE\"; exit 3")
        self.assertEqual((code, out), (3, "from the record\n"))

    def test_tools_show_prints_each_entry(self):
        record_entry(self.root, "pandoc", tools_module.tool_entry("/opt/tools/envs/pandoc/bin/pandoc", "3.11", "micromamba"))
        record_entry(self.root, "git", tools_module.tool_entry("/usr/bin/git", "2.43.0", "system", installer="system"))
        code, out, _ = cli_run("show")
        self.assertEqual(code, 0)
        lines = out.splitlines()
        self.assertTrue(any(line.split()[:4] == ["git", "2.43.0", "system", "/usr/bin/git"] for line in lines), out)
        self.assertTrue(any(line.split()[:4] == ["pandoc", "3.11", "harness", "/opt/tools/envs/pandoc/bin/pandoc"] for line in lines), out)
        code, out, _ = cli_run("show", "--json")
        self.assertEqual(json.loads(out)["tools"]["git"]["version"], "2.43.0")

    def test_tools_install_with_a_name_records_that_tool_alone(self):
        code, out, err = cli_run("install", "git")
        self.assertEqual(code, 0, err)
        record = read_json(self.root / TOOLS_JSON)
        self.assertEqual(list(record["tools"]), ["git"])
        self.assertEqual(record["tools"]["git"]["installer"], "system")
        self.assertIn("git", out)

    def test_tools_install_refuses_a_name_it_does_not_know(self):
        code, _, err = cli_run("install", "matlab")
        self.assertEqual(code, 2)
        self.assertIn("no tool is called matlab", err)

    def test_the_dry_run_names_every_harness_tool_and_its_route(self):
        code, out, _ = cli_run("install", "--dry-run")
        self.assertEqual(code, 0)
        for text in (micromamba_url(), uv_url(), "conda-forge", MODEL_REVISION, "matplotlib", "tree-sitter-matlab", "converters"):
            self.assertIn(text, out)
        self.assertFalse(self.root.exists())


class RecordMergeTest(ProjectTestCase):
    def setUp(self):
        super().setUp()
        self.root = self.temp / "tools"

    def test_two_installs_in_a_row_keep_both_entries(self):
        machine = Machine()
        install_tool("micromamba", root=self.root, run=machine)
        install_tool("uv", root=self.root, run=machine)
        self.assertEqual(Tools(self.root).names(), ["micromamba", "uv"])

    def test_entries_merged_at_once_from_many_threads_are_all_kept(self):
        names = ["tool-%02d" % index for index in range(24)]
        threads = [threading.Thread(target=record_entry, args=(self.root, name, {"executable": "/bin/" + name})) for name in names]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(Tools(self.root).names(), names)

    def test_the_converter_venv_install_keeps_every_tool_entry(self):
        machine = Machine()
        install_tool("micromamba", root=self.root, run=machine)
        record = tools_module.install(root=self.root, run=machine, uv=str(self.root / "bin" / "uv"))
        self.assertIn("micromamba", record["tools"])
        self.assertIn("micromamba", read_json(self.root / TOOLS_JSON)["tools"])
        self.assertEqual(read_json(self.root / TOOLS_JSON)["python"], str(self.root / "venv" / "bin" / "python"))

    def test_the_converters_get_entries_of_their_own_in_the_tools_venv(self):
        machine = Machine(versions={"docling": "2.140.0", "pdfplumber": "0.11.10"})
        tools_module.install(root=self.root, run=machine)
        docling = Tools(self.root).entry("docling")
        self.assertEqual((docling["executable"], docling["version"], docling["route"]), (str(self.root / "venv" / "bin" / "python"), "2.140.0", "uv"))
        self.assertEqual(Tools(self.root).entry("pdfplumber")["lock"], docling["lock"])
        self.assertIsNone(Tools(self.root).entry("marker"), "marker only on request")

    def test_recording_the_same_version_again_keeps_when_it_was_installed(self):
        first = record_entry(self.root, "git", dict(tools_module.tool_entry("/usr/bin/git", "2.43.0", "system"), installed="2026-10-01T00:00:00.000Z"))
        record_entry(self.root, "git", tools_module.tool_entry("/usr/bin/git", "2.43.0", "system"))
        self.assertEqual(Tools(self.root).entry("git")["installed"], first["installed"])
        record_entry(self.root, "git", tools_module.tool_entry("/usr/bin/git", "2.44.0", "system"))
        self.assertNotEqual(Tools(self.root).entry("git")["installed"], first["installed"])

    def test_a_record_of_the_first_version_reads_as_one_with_no_tool_entries(self):
        self.root.mkdir(parents=True)
        (self.root / TOOLS_JSON).write_text(json.dumps({"schema_version": 1, "python": "/x/venv/bin/python", "packages": {"docling": "2.126.0"}}), encoding="utf-8")
        record_entry(self.root, "uv", {"executable": "/x/bin/uv"})
        record = read_json(self.root / TOOLS_JSON)
        self.assertEqual((record["schema_version"], record["packages"], sorted(record["tools"])), (2, {"docling": "2.126.0"}, ["uv"]))
