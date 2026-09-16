# Protocol

1. Read the ticket above and the context pack under it: what the experiment measures, the
   `outputs` it must leave, its `resources`, and its `retry` ladder.
2. Write or change the script in the touch set. It takes its settings as arguments (the ladder
   steps override arguments such as `--batch-size`), writes its results to the output paths, and
   exits non-zero when it fails.
3. Smoke-test it on a tiny CPU setting that finishes in seconds. Do not run the experiment.
4. Run `wayline accept` from the worktree root and fix what failed, then `git add` and `git commit`
   the script. Leave nothing uncommitted in the touch set.
5. Write the jobs, one call, the spec on stdin:

   ```
   wayline job add <<'EOF'
   {"command": ["/usr/bin/python3", "scripts/train.py", "--seed", "1"],
    "expected_outputs": ["results/sweep/seed-1.json"],
    "members": [
      {"command": ["/usr/bin/python3", "scripts/train.py", "--seed", "1"], "expected_outputs": ["results/sweep/seed-1.json"]},
      {"command": ["/usr/bin/python3", "scripts/train.py", "--seed", "2"], "expected_outputs": ["results/sweep/seed-2.json"]}
    ]}
   EOF
   ```

   Name the interpreter by its absolute path. Paths are relative to the project root. Leave out
   `devices`, `retry`, and `wallclock_minutes`: the ticket supplies them. The command prints one
   line per job with its id; a spec it refuses prints why, and nothing is written.
6. Return the structured result with `status: running`, `jobs` holding every id printed, and a
   summary of what each job runs. Put no findings in it: the analysis ticket reads the results.

If a job cannot be written as the ticket asks (the script needs a GPU the ticket's resources do not
give it, an output the ticket does not name), say so in `blocked_on` or `status: failed` rather than
returning jobs that cannot succeed.
