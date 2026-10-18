# Protocol

1. Read the ticket above and the context pack under it: what the experiment measures, the
   `outputs` it must leave, its `resources`, and its `retry` ladder.
2. Write or change the script in the touch set. It takes its settings as arguments (the ladder
   steps override arguments such as `--batch-size`), writes its results to the output paths, and
   exits non-zero when it fails.
3. Smoke-test it on a tiny CPU setting that finishes in seconds, writing its output under
   `results/smoke/`: `results/` is git-ignored, so the smoke output never counts as uncommitted
   work. Do not run the experiment.
4. Write the job spec as a JSON file in the touch set, for example `<touch set>/jobs.json`:

   ```
   {"command": ["/usr/bin/python3", "scripts/train.py", "--seed", "1"],
    "members": [
      {"command": ["/usr/bin/python3", "scripts/train.py", "--seed", "1"], "expected_outputs": ["results/sweep/seed-1.json"]},
      {"command": ["/usr/bin/python3", "scripts/train.py", "--seed", "2"], "expected_outputs": ["results/sweep/seed-2.json"]}
    ]}
   ```

   Name the interpreter by its absolute path. Paths are relative to the project root. Leave out
   `devices`, `retry`, and `wallclock_minutes`: the ticket supplies them. A job that runs one of
   the ticket's tools names it instead, `"tool": "octave"` with the arguments as its `command`
   (`["--eval", "run('scripts/model.m')"]`): `wayline job add` writes the tool's absolute path and
   environment in, and the job record keeps the tool's version and lock.
5. Run `wayline accept` from the worktree root and fix what failed, then `git add` and `git commit`
   the script and the spec. Leave nothing uncommitted in the touch set: the conductor integrates
   the branch, and a stray file there fails the ticket.
6. Write the jobs: `wayline job add <touch set>/jobs.json`. It prints one line per job with its id;
   a spec it refuses prints why, and nothing is written. Run it once.
7. Return the structured result with `status: running`, `jobs` holding every id printed, and a
   summary of what each job runs. Put no findings in it: the analysis ticket reads the results.

Files outside the touch set that you did not mean to write (a `__pycache__` the smoke test made)
are not held against you; leave them. `blocked_on` is only for work you cannot do inside the touch
set, never for a remark: it stops the ticket and cancels its jobs.

If a job cannot be written as the ticket asks (the script needs a GPU the ticket's resources do not
give it, an output the ticket does not name), say so in `blocked_on` or `status: failed` rather than
returning jobs that cannot succeed. When an installed tool lacks what the script needs, stop with
`blocked_on: "software <tool>: <what it lacks>"`, and the harness asks the owner; a package the
script imports goes in with `wayline tools package <python|r|julia|octave> <name>`, with no ask.
