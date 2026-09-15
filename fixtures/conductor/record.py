#!/usr/bin/env python3
"""Record `m1-kill-resume/`: the five-ticket project, its conductor killed with SIGKILL mid-wave.

Run from anywhere with `python3 fixtures/conductor/record.py`. The recording is what
`tests/test_resume.py` replays, so remake it after a change to what the conductor journals.

It copies `fixtures/projects/five-tickets/` to `/tmp/wayline-m1-kill-resume/five-tickets`, lays it
out with `wayline init` under a scratch `WAYLINE_HOME`, and runs `wayline run` with the fake worker
scripted from the fixture's own `fake-worker.json`, except that tickets 3 and 4 sleep. It reads
the conductor's own lines until both of their sessions are journaled, while both workers are still
running, and sends SIGKILL; which wave that is depends on when the workers return, so nothing here
counts waves. What the kill left is copied into `fixtures/conductor/m1-kill-resume/`: the journal,
the ticket files, the graph, the heartbeat, each session's `stream.jsonl` and `pid`, and the files
`main` held (`notes/` and `reports/`), which the suite needs to resume the recording. The prompts, settings, and environments beside the streams
are left out, because they name the harness checkout the recording was made from; the journal
names only the scratch directory, which is the same on every machine.
"""

import json
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
HARNESS = HERE.parent.parent
SOURCE = HARNESS / "fixtures" / "projects" / "five-tickets"
TARGET = HERE / "m1-kill-resume"
SCRATCH = Path("/tmp/wayline-m1-kill-resume")
SLOW = (3, 4)
# The files the done tickets wrote on `main`, which a resume of the recording integrates onto.
OUTPUTS = ("notes", "reports")
LEDGER_FILES = ("journal.jsonl", "graph.json", "conductor.json", "findings.jsonl", "manifest.json", "INTAKE.md")


def main():
    shutil.rmtree(SCRATCH, ignore_errors=True)
    project = SCRATCH / "five-tickets"
    shutil.copytree(SOURCE, project)
    harness = json.loads((project / "harness.json").read_text(encoding="utf-8"))
    harness["policy"] = {"poll_seconds": 1}
    (project / "harness.json").write_text(json.dumps(harness, indent=2) + "\n", encoding="utf-8")
    script = json.loads((SOURCE / "fake-worker.json").read_text(encoding="utf-8"))
    for entry in script:
        if int(entry["ticket"]) in SLOW:
            entry["delay"] = 600
    (SCRATCH / "fake-worker.json").write_text(json.dumps(script, indent=2) + "\n", encoding="utf-8")

    # Unpinned, units off, and no notifications: the fixture pins v0.0.0, and a recording touches nothing of the owner's.
    environment = dict(os.environ, WAYLINE_HOME=str(SCRATCH / "home"), WAYLINE_LAUNCHER="fake",
                       WAYLINE_FAKE_SCRIPT=str(SCRATCH / "fake-worker.json"), WAYLINE_UNPINNED="1",
                       WAYLINE_UNITS="none", WAYLINE_NOTIFY="none")
    subprocess.run([sys.executable, "-m", "wayline", "init", str(project)], cwd=HARNESS, env=environment,
                   check=True, capture_output=True, timeout=120)
    conductor = subprocess.Popen([sys.executable, "-m", "wayline", "run", "--project", str(project)],
                                 cwd=HARNESS, env=environment, stdout=subprocess.PIPE, text=True)
    waiting = {"ticket %d session " % ticket for ticket in SLOW}
    for line in conductor.stdout:
        sys.stdout.write(line)
        waiting = {prefix for prefix in waiting if not line.strip().startswith(prefix)}
        if not waiting:
            break
    else:
        raise SystemExit("the conductor ended before both slow sessions were journaled")
    os.kill(conductor.pid, signal.SIGKILL)
    conductor.wait(60)
    print("killed pid %d" % conductor.pid)

    shutil.rmtree(TARGET, ignore_errors=True)
    (TARGET / "research").mkdir(parents=True)
    shutil.copy(project / "harness.json", TARGET / "harness.json")
    for name in OUTPUTS:
        shutil.copytree(project / name, TARGET / name)
    for name in LEDGER_FILES:
        shutil.copy(project / "research" / name, TARGET / "research" / name)
    shutil.copytree(project / "research" / "tickets", TARGET / "research" / "tickets")
    for stream in sorted((project / "research" / "sessions").glob("*/*/stream.jsonl")):
        relative = stream.parent.relative_to(project / "research")
        (TARGET / "research" / relative).mkdir(parents=True, exist_ok=True)
        for name in ("stream.jsonl", "pid"):
            if (stream.parent / name).exists():
                shutil.copy(stream.parent / name, TARGET / "research" / relative / name)
    print("recorded into %s" % TARGET)


if __name__ == "__main__":
    main()
