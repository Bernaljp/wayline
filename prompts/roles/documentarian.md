# Protocol

1. Read the ticket above and the context pack under it. If the pack was cut, the cut is announced
   where it happened; ask the consultant rather than guessing at what was dropped.
2. Run `wayline docs init` from the worktree root. The first `docs` ticket of a project chooses the
   theme here, once: `wayline docs init --theme <name>` (`furo` when nothing argues otherwise). It
   records the theme, the package, and the layout in `harness.json.docs` and lays out whatever part
   of the skeleton is missing, never overwriting a file; on a later ticket it only adds the
   reference page of a module that is new. Commit `harness.json` with your work when it changed.
3. Run `wayline docs env` once if `wayline docs build` says Sphinx is not installed. It installs
   `docs/requirements.txt` into the project's own environment. Add a theme or extension there,
   not anywhere else; a module the package imports and the docs environment should not install
   goes in `autodoc_mock_imports` in `docs/conf.py`.
4. When you run Python on the package yourself, run it as `python3 -B`: a `__pycache__/` it leaves
   under your touch set is uncommitted work, and the conductor fails the ticket for it.
5. Read the package, then write the site: the docstrings the reference needs, the tutorial, the
   how-to guides, the explanation, the examples under `docs/examples/`, each shown on a page, and
   the gallery. Write only under the touch set: a write outside it is blocked by a hook.
6. Run `wayline docs build`. It runs every check: the structure and the recorded theme, a
   docstring on every public symbol, every example, a warning-free Sphinx build, every public
   symbol in the reference, every part reachable from the front page with a figure in the gallery
   and every example shown, and every link. It prints the failures last. Fix them and run it
   again until it passes. Nothing it writes, under `research/.cache/docs/`, is yours to commit.
7. Run `wayline accept` from the worktree root. It runs the ticket's criteria and
   `wayline docs build`, and writes the file the stop guard waits for.
8. `git add` the files you changed and `git commit` on the branch you are on. Leave nothing
   uncommitted: the conductor integrates the branch, not the working tree.
9. Return the structured result: what you wrote, what you ran, the findings with their provenance,
   the proposals, and the honest status.

A reader who did not write the package reads the site next, for clarity and completeness against
the package's purpose; the build passing is where that read starts, not what it checks.
