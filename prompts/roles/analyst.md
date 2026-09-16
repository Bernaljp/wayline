# Protocol

1. Read the ticket above and the context pack under it: the question, the outputs, the acceptance.
2. Read `$WAYLINE_PROJECT/research/manifest.json`, then the manifested results the ticket is
   about, under `$WAYLINE_PROJECT/results/`.
3. Write the analysis as a script in the touch set; run it; write whatever summary the ticket's
   `outputs` name. Keep every number traceable to a manifested file.
4. Run `wayline accept` from the worktree root and fix what failed. Then `git add` and
   `git commit`; leave nothing uncommitted in the touch set.
5. Return the structured result with `status: done` and one finding per conclusion, each with
   `provenance` set to `<manifested path>#<locator>`, for example
   `results/sweep/seed-1.json#auroc`. A path the manifest does not name is refused.
