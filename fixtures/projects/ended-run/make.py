"""Rebuild `fixtures/projects/ended-run/`: a toy project whose run ended, for the report of ticket 40.

Run it from anywhere: `python3 fixtures/projects/ended-run/make.py`. It removes `research/` and
`results/` and writes them again through the ledger with fixed timestamps, so the committed files
are exactly what this script writes. Change the script and rerun it; do not edit the files.

The run holds one of everything `wayline report` has a section for: a decision by the decider and
one by the owner, an open decision ticket and a `needs_human` ticket, kept goal readings and a
discarded change, four findings over manifested results (one of them negative), tickets `done`
and `accepted`, a difficulty-5 ticket, parked proposals, a paper read in full, a paper promoted and
not read, a promotion waiting on a decision, a reference that did not resolve, a global change
record under `autonomous`, GPU jobs, a closed window, and `run_ended`. Fable's weekly window was spent
when the run began, under the fallback consent `auto`, so the decider's answer and ticket 2's diff verdict
ran on Opus in Fable's place (decision 15) until the window reset.
"""

import json
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))

from wayline.dossier import CONSULTANT_QUESTION, PRIMARY_AT_INTAKE  # noqa: E402
from wayline.kb import make_node, write_node  # noqa: E402
from wayline.ledger import Ledger  # noqa: E402
from wayline.provenance import sha256_of  # noqa: E402
from wayline.tickets import write_ticket  # noqa: E402

CLAIM = "SPEC.md#c1-interaction-terms"
ANTI_CLAIM = "SPEC.md#a1-depth-alone"
GPU = "GPU-2f9c1b7e-0000-0000-0000-000000000001"
START = datetime(2026, 9, 11, 20, 0, tzinfo=timezone.utc)

RESULTS = {
    "results/features/summary.json": {"rows": 20000, "label_disagreement": 0.031},
    "results/baseline/seed-1/summary.json": {"seed": 1, "auroc": 0.808},
    "results/baseline/seed-2/summary.json": {"seed": 2, "auroc": 0.816},
    "results/baseline/seed-3/summary.json": {"seed": 3, "auroc": 0.812},
    "results/baseline/summary.json": {"seeds": 3, "auroc_mean": 0.812, "auroc_sd": 0.004},
    "results/interactions/summary.json": {"seeds": 3, "auroc_mean": 0.861, "auroc_sd": 0.005},
    "results/depth/summary.json": {"seeds": 3, "auroc_mean": 0.815, "auroc_sd": 0.011},
}

# path -> (run id, job, ticket)
PRODUCED_BY = {
    "results/features/summary.json": ("t1-a1", None, 1),
    "results/baseline/seed-1/summary.json": ("t2-a1", "j-0001", 2),
    "results/baseline/seed-2/summary.json": ("t2-a1", "j-0001", 2),
    "results/baseline/seed-3/summary.json": ("t2-a1", "j-0001", 2),
    "results/baseline/summary.json": ("t2-a1", "j-0001", 2),
    "results/interactions/summary.json": ("t3-a1", "j-0002", 3),
    "results/depth/summary.json": ("t4-a1", "j-0003", 4),
}

# Each finding stands under its Results heading, which names the question it answers (decision 17): the results
# cluster by heading, so the general report has three, one of them negative.
FINDINGS = [
    ("f-0001", 1, "The two label sources disagree on 3.1 percent of the held-out rows.",
     ["results/features/summary.json#label_disagreement"], False, "Do the two label sources agree?"),
    ("f-0002", 2, "The baseline reaches a held-out AUROC of 0.812, with a standard deviation of 0.004 over three seeds.",
     ["results/baseline/summary.json#auroc_mean", "results/baseline/summary.json#auroc_sd"], False,
     "Do interaction terms raise the held-out AUROC?"),
    ("f-0003", 3, "Pairwise interaction terms raise the held-out AUROC to 0.861. That is more than ten baseline standard deviations above the baseline.",
     ["results/interactions/summary.json#auroc_mean", "results/baseline/summary.json#auroc_sd"], False,
     "Do interaction terms raise the held-out AUROC?"),
    ("f-0004", 4, "Doubling the model depth without interaction terms leaves the held-out AUROC at 0.815, within one standard deviation of the baseline.",
     ["results/depth/summary.json#auroc_mean", "results/depth/summary.json#auroc_sd"], True, "Does depth alone do it?"),
]


def ticket(identifier, title, kind, difficulty, status, role, origin, blocked_by=(), touches=(), outputs=(),
           proposed_by="planner", demo=None, **extra):
    fields = {
        "id": identifier, "title": title, "kind": kind, "difficulty": difficulty, "status": status,
        "blocked_by": list(blocked_by), "touches": list(touches), "role": role, "skills": [],
        "outputs": list(outputs), "acceptance": {"machine": ["python -m unittest"] if kind != "decision" else [], "quality": []},
        "origin": origin, "proposed_by": proposed_by, "demo": demo,
    }
    fields.update(extra)
    return fields


TICKETS = [
    ticket(1, "Build the feature table", "analysis", 2, "accepted", "analyst", CLAIM,
           touches=["src/toy/features.py", "results/features/"], outputs=["results/features/summary.json"],
           demo="The feature table and the label-disagreement summary."),
    ticket(2, "Train the baseline model", "experiment", 3, "accepted", "experimenter", CLAIM, blocked_by=[1],
           touches=["src/toy/train.py", "results/baseline/"], outputs=["results/baseline/summary.json"],
           demo="Three seeds of the baseline with held-out AUROC."),
    ticket(3, "Add pairwise interaction terms", "experiment", 5, "accepted", "experimenter", CLAIM, blocked_by=[2],
           touches=["src/toy/interactions.py", "results/interactions/"], outputs=["results/interactions/summary.json"],
           demo="Three seeds with interaction terms, compared with the baseline."),
    ticket(4, "Try a deeper model without interactions", "experiment", 3, "done", "experimenter", ANTI_CLAIM, blocked_by=[2],
           touches=["src/toy/depth.py", "results/depth/"], outputs=["results/depth/summary.json"],
           demo="Three seeds of a model twice as deep, without interaction terms."),
    ticket(5, "Plot the goal trajectory", "figure", 2, "done", "figure-designer", CLAIM, blocked_by=[3],
           touches=["figures/trajectory/"], proposed_by="worker:3", demo="One trajectory figure."),
    ticket(6, "Which label source wins where the two disagree?", "decision", 1, "open", "decider",
           "research/findings.jsonl#f-0001", blocking="subgraph", human_only=True),
    ticket(7, "Convert the second reference's PDF", "dossier", 2, "needs_human", "reader", "research/INTAKE.md#references",
           touches=["research/refs/paper-b/"]),
    ticket(8, "Which held-out split does the goal read?", "decision", 1, "done", "decider", "research/objectives.json",
           blocking="subgraph", human_only=False),
    ticket(9, "Probe the calibration of the interaction model", "analysis", 2, "parked", "analyst", CLAIM, blocked_by=[3],
           touches=["results/calibration/"], proposed_by="worker:3"),
    ticket(10, "How many rows does the generator write?", "decision", 1, "done", "decider", "research/INTAKE.md#data",
           blocking="subgraph", human_only=False),
    ticket(11, "Promote paper-c to level 2?", "decision", 1, "open", "decider",
           "consultant_question: beyond the P5 budget of 2 level-2 reads", blocking="subgraph", human_only=False),
]

REFS = [
    # slug, level, existence, title, year
    ("paper-a", 2, "verified", "Interaction features for tabular classification", 2021),
    ("paper-b", 2, "verified", "Depth versus width in small tabular networks", 2023),
    ("paper-c", 1, "verified", "Label noise between annotation sources", 2019),
    ("paper-d", 0, "unresolved", "A tabular benchmark someone mentioned", None),
]


class Clock:
    def __init__(self):
        self.now = START

    def tick(self, minutes=1):
        self.now += timedelta(minutes=minutes)
        return self.now.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def main():
    for name in ("research", "results"):
        shutil.rmtree(HERE / name, ignore_errors=True)
    book = Ledger(HERE)
    clock = Clock()
    created = clock.tick(0)

    def event(name, payload, ticket=None, session_id=None, job=None, minutes=1):
        book.append_event(name, payload, ticket=ticket, session_id=session_id, job=job, ts=clock.tick(minutes))

    # The goal is an objective with a measure (decision 17; ticket 87), which code wrote reached from the kept 0.861.
    book.write_json("objectives.json", {"objectives": [{
        "id": "O1", "text": "Do feature interaction terms raise the held-out AUROC on the synthetic set?",
        "measure": {"metric": "auroc", "direction": "up", "target": 0.85, "held_out_split": "split_b",
                    "eval_command": "python -m toy.eval --split held_out", "baseline": {"value": None, "source": None},
                    "dataset_or_split": None, "min_seeds": None},
        "status": "answered", "answer": "reached: the best kept auroc is 0.861 against the target 0.85 (up), measured by code on t3-a1",
        "evidence": [], "reframed_as": None}]}, schema="objectives")
    book.write_markdown("INTAKE.md", "# Intake\n\nFind whether adding feature interaction terms improves held-out AUROC on the synthetic set.\n")
    for fields in TICKETS:
        body = "## Demo\n\n%s\n" % (fields["demo"] or fields["title"])
        write_ticket(book, fields, body)

    for relative, value in RESULTS.items():
        path = HERE / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    for slug, level, existence, title, year in REFS:
        record = {
            "schema_version": 1, "slug": slug, "level": level, "existence": existence,
            "resolved_by": "crossref" if existence == "verified" else None,
            "query": {"kind": "title", "value": title},
            "identifiers": {"doi": "10.5555/wayline.fixture.%s" % slug} if existence == "verified" else {},
            "metadata": {"title": title, "year": year} if existence == "verified" else {},
            "created": created,
        }
        if level >= 1:
            record["relation_to_intent"] = "Bears on whether interaction terms help on tabular data."
            record["deserves_l2_if"] = "A spec claim rests on its method."
        book.write_json("refs/%s/dossier.json" % slug, record, schema="dossier")
        write_node(book, make_node(slug, "paper", title, level=level, existence=existence, year=year, created=created))

    session = lambda n: "%08d-0000-4000-8000-0000000000%02d" % (n, n)  # noqa: E731

    event("run_started", {"resume": False, "harness_tag": "v0.0.0", "autonomy": "autonomous", "radius": "moderate", "pid": 40401})
    event("pacing", {"five_hour": 0.18, "seven_day": 0.34, "action": "normal"})
    event("paused", {"resets_at": "2026-09-11T23:27:00Z", "window": "seven_day", "utilization": 1.0, "model": "fable"})
    event("decision", {"ticket": 10, "answer": "20000 rows", "decided_by": "human",
                       "rationale": "Enough rows for three seeds to separate by more than one standard deviation.", "confidence": 1.0}, ticket=10)
    event("decision", {"ticket": 8, "answer": "split_b", "decided_by": "decider",
                       "rationale": "split_b holds out whole annotation sources, so a gain on it cannot come from leakage between the two label sources.",
                       "confidence": 0.8, "model": "claude-opus-5", "fallback_from": "fable"}, ticket=8)
    for slug, level, _, _, _ in REFS:
        event("absorbed", {"slug": slug, "level": 0})
    event("promoted", {"slug": "paper-a", "from_level": 1, "to_level": 2, "trigger": PRIMARY_AT_INTAKE})
    event("absorbed", {"slug": "paper-a", "level": 2, "session_id": session(20), "chunks": 6, "entries": 48, "coverage_pass": True}, session_id=session(20), minutes=40)

    def worked(identifier, role, model, effort, turns, minutes, status="done", attempt=1):
        event("ticket_launched", {"ticket": identifier, "attempt": attempt, "role": role, "model": model, "effort": effort,
                                  "skills": [], "worktree": ".worktrees/%d" % identifier, "pid": 41000 + identifier,
                                  "context_chars": 12000, "prompt_sha256": "%064x" % identifier}, ticket=identifier)
        event("ticket_session", {"ticket": identifier, "attempt": attempt, "session_id": session(identifier),
                                 "model": "claude-%s-5" % model}, ticket=identifier, session_id=session(identifier))
        event("ticket_result", {"ticket": identifier, "attempt": attempt, "session_id": session(identifier), "status": status,
                                "turns": turns, "duration_ms": minutes * 60000, "usage": {"input_tokens": 30000, "output_tokens": 4000},
                                "permission_denials": 0, "valid": True}, ticket=identifier, session_id=session(identifier), minutes=minutes)

    def job(identifier, name, seconds):
        event("job_launched", {"job": name, "ticket": identifier, "unit": "wayline-job-%s.service" % name, "gpu_uuids": [GPU],
                               "cores": 8, "ram_gb": 32, "attempt": 1}, ticket=identifier, job=name)
        event("job_finished", {"job": name, "exit_code": 0, "seconds": seconds, "outputs_ok": True}, ticket=identifier, job=name,
              minutes=seconds // 60)

    def manifest(prefix):
        for relative in RESULTS:
            if relative.startswith(prefix):
                run_id, job_id, owner = PRODUCED_BY[relative]
                path = HERE / relative
                entry = {"path": relative, "size": path.stat().st_size, "sha256": sha256_of(path), "job": job_id,
                         "run_id": run_id, "ticket": owner, "ts": clock.tick()}
                entries.append(entry)
                book.write_json("manifest.json", {"entries": entries}, schema="manifest")
                event("manifest", {"path": relative, "sha256": entry["sha256"], "size": entry["size"], "job": job_id, "run_id": run_id},
                      ticket=owner, minutes=0)

    def finding(identifier):
        for number, owner, text, provenance, negative, heading in FINDINGS:
            if owner == identifier:
                record = {"id": number, "ticket": owner, "text": text, "provenance": provenance, "negative": negative,
                          "heading": heading, "ts": clock.tick()}
                book.append_record("findings.jsonl", record)
                event("finding", {"id": number, "ticket": owner, "text": text, "provenance": provenance, "negative": negative,
                                  "heading": heading}, ticket=owner, minutes=0)

    def closed(identifier, verdict_model=None, verdict_type="result", fallback_from=None):
        event("acceptance", {"ticket": identifier, "attempt": 1, "where": "main", "pass": True,
                             "results": [{"command": "python -m unittest", "exit_code": 0}]}, ticket=identifier)
        event("integrated", {"ticket": identifier, "commit": "%07x" % (0x4c2f9a0 + identifier), "resolved_by": "none"}, ticket=identifier)
        event("ticket_done", {"ticket": identifier}, ticket=identifier)
        finding(identifier)
        if verdict_model:
            payload = {"subject_kind": "ticket", "subject": "research/tickets/%02d" % identifier, "verdict_type": verdict_type,
                       "pass": True, "session_id": session(60 + identifier), "model": verdict_model, "findings": []}
            if fallback_from:
                payload["fallback_from"] = fallback_from
            event("verdict", payload, ticket=identifier, session_id=session(60 + identifier))
            event("ticket_accepted", {"ticket": identifier}, ticket=identifier)

    entries = []
    worked(1, "analyst", "sonnet", "medium", 14, 10)
    manifest("results/features/")
    closed(1, "claude-opus-5", "quality")

    worked(2, "experimenter", "opus", "high", 22, 12, status="running")
    job(2, "j-0001", 2700)
    manifest("results/baseline/")
    event("progress", {"metric": "auroc", "value": 0.812, "ticket": 2, "run_id": "t2-a1", "kept": True, "goal": "O1"}, ticket=2)
    closed(2, "claude-opus-5", "diff", fallback_from="fable")

    event("paused", {"resets_at": "2026-09-12T02:00:00Z", "window": "five_hour", "utilization": 0.92})
    event("unpaused", {}, minutes=65)
    event("unpaused", {"model": "fable"})
    event("pacing", {"five_hour": 0.05, "seven_day": 0.51, "action": "normal"})

    worked(3, "experimenter", "fable", "max", 41, 25, status="running")
    job(3, "j-0002", 3000)
    manifest("results/interactions/")
    event("progress", {"metric": "auroc", "value": 0.861, "ticket": 3, "run_id": "t3-a1", "kept": True, "goal": "O1"}, ticket=3)
    event("proposal_admitted", {"id": "p-0001", "from": 3, "kind": "figure", "ticket": 5}, ticket=3)
    event("proposal_parked", {"id": "p-0002", "from": 3, "kind": "analysis", "reason": "cap"}, ticket=3)
    event("proposal_parked", {"id": "p-0003", "from": 4, "kind": "experiment", "reason": "radius"}, ticket=4)
    closed(3, "claude-opus-5", "result")

    worked(4, "experimenter", "opus", "high", 19, 10, status="running")
    job(4, "j-0003", 2400)
    manifest("results/depth/")
    event("progress", {"metric": "auroc", "value": 0.815, "ticket": 4, "run_id": "t4-a1", "kept": False, "goal": "O1"}, ticket=4)
    event("discarded", {"ticket": 4, "metric": "auroc", "best": 0.861, "sd": 0.011, "seeds": 3, "goal": "O1"}, ticket=4)
    closed(4)

    worked(5, "figure-designer", "sonnet", "medium", 9, 6)
    closed(5)

    event("promoted", {"slug": "paper-b", "from_level": 1, "to_level": 2, "trigger": CONSULTANT_QUESTION}, ticket=4)
    event("ticket_created", {"ticket": 11, "kind": "decision", "proposed_by": "planner", "origin": TICKETS[10]["origin"], "blocked_by": []}, ticket=11)
    event("decision_opened", {"ticket": 11, "blocking": "subgraph", "human_only": False}, ticket=11)

    worked(7, "reader", "sonnet", "medium", 30, 20, status="failed")
    event("ticket_failed", {"ticket": 7, "attempt": 1, "reason": "the converter venv is missing", "next": "needs_human"}, ticket=7)
    event("ticket_needs_human", {"ticket": 7, "question": "Install the converter venv, or accept paper-b at level 1?"}, ticket=7)
    event("decision_opened", {"ticket": 6, "blocking": "subgraph", "human_only": True}, ticket=6)
    event("change_record", {"id": "c-0001", "scope_kind": "global", "mechanism": "prompt", "fixture": "fixtures/prompt/captions-overclaim"})
    event("change_record", {"id": "c-0002", "scope_kind": "local", "mechanism": "skill", "fixture": "fixtures/skill/toy-plotting"})
    event("run_ended", {"reason": "frontier_empty"})
    event("notified", {"event": "run_ended", "channel": "hermes", "ok": True}, minutes=0)

    (book.research / ".lock").unlink(missing_ok=True)


if __name__ == "__main__":
    main()
