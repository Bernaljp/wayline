# The decision-branch project

The graph of ticket 35: a decision ticket that pauses one branch while the other branch runs.

```
1 write notes/alpha.md ─────────▶ 4 extend notes/alpha.md
2 decide the beta report's form ─▶ 3 write reports/beta.md ─▶ 5 extend reports/beta.md
```

Ticket 2 is a decision ticket with `blocking: subgraph`: its question, its two options, the
recommended one, and its evidence are in its body, with the machine copy the dashboard's decisions
view reads. While it is open, the frontier holds ticket 3, which waits on it, and ticket 5, which
waits on ticket 3. The project runs under autonomy `checkpoints`, so no session answers the
question: the owner does.

With `max_parallel_workers` at its policy value of 2, the first run is two waves of work and one
that ends it:

| Wave | Launched | Why not the rest |
|---|---|---|
| 1 | 1 | 2 waits for the owner; 3 and 5 are paused by it; 4 waits on 1 |
| 2 | 4 | the same, with 1 done |
| 3 | nothing | the frontier holds only ticket 2, so the run ends with `frontier_empty` and says why |

Then the owner answers ticket 2, from any of the four places an answer is given: `wayline answer 2
"one line"`, the dashboard's answer form, an `## Answer` section written at the end of the ticket
file, or a session running `wayline answer` for them. The tick sees the answer and relaunches the
conductor, whose first wave closes ticket 2 and launches 3, and whose next launches 5.

`fake-worker.json` is the script the fake worker follows, keyed by ticket id. `make.py` writes it,
the five tickets, and the empty ledger files; run it after changing how a decision ticket's body
reads (`wayline.decisions.decision_body`), and `tests/test_decisions.py` fails until you do.

## From a shell

Copy it out first, so no git repository is made inside the harness checkout.

```
cp -r fixtures/projects/decision-branch /tmp/decision-branch
export WAYLINE_HOME=/tmp/decision-branch-home WAYLINE_LAUNCHER=fake WAYLINE_FAKE_SCRIPT=/tmp/decision-branch/fake-worker.json
bin/wayline init /tmp/decision-branch
bin/wayline run --project /tmp/decision-branch
bin/wayline status --project /tmp/decision-branch
bin/wayline answer 2 "one line" --project /tmp/decision-branch
bin/wayline run --project /tmp/decision-branch
```

What to look for: the first run launches 1 and 4 and ends with ticket 2 open and 3 and 5 held
back by it; the `decision` event of the answer carries `decided_by: human`; the second run closes
ticket 2 and launches 3, then 5.
