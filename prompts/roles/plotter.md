# Protocol

1. Read the drawing's brief in this prompt: the result, its findings and their `res` artifacts,
   the objectives, the project summary, the sorted plot index with its data shapes, the house
   style, the previous drawing with the owner's marks and notes, and any earlier figure to answer.
2. Read the artifacts the findings cite, where they are: `$WAYLINE_PROJECT/<manifest path>`.
   `$WAYLINE_PROJECT/research/manifest.json` names every one. Never the project's own code.
3. Name the result's data views. For each, pick one canonical chart type per matching data shape
   from the plot index, leaving out a near duplicate, a series over an index with no order, a
   plot whose marks are collapsed, and any plot you cannot make readable: at most 20 plots and
   4 tables, at most 4 headline plots, and no minimum.
4. Write one Python script in your drawing directory, `draw.py`, that reads every input as
   `os.path.join(os.environ.get("WAYLINE_PROJECT", "."), "<manifest path>")`, writes every output
   into its own directory (`os.path.dirname(os.path.abspath(__file__))`), and runs with no
   argument, CPU only, with matplotlib and seaborn in the tools venv: each plot as `<name>.png`
   and `<name>.svg`, each table as `<name>.csv`, and every number any explanation quotes into
   `numbers.json`. Seed anything random: acceptance reruns the script in a clean room and
   compares the plots and `numbers.json`. Run it with `wayline tools run matplotlib -- <script>`.
5. Look at every plot. One with rotated text other than the y-axis label, an axis label over 40
   characters, a figure title above titled panels, a labelled heatmap of more than 36 cells, a
   flat summary mark, overlapping text, text under the house style's smallest size, or a color
   outside the house palette fails its checks: fix it or leave it out.
6. Write `drawing.json` in your drawing directory:

   ```json
   {"script": "draw.py", "numbers": "numbers.json", "inputs": ["<manifest path>", "..."],
    "plots": [{"redraws": "R4.3 or null", "chart_type": "...", "index_entries": ["<plot index id>"],
               "data_view": "...", "png": "<name>.png", "svg": "<name>.svg", "inputs": ["<manifest path>"],
               "purpose": "...", "data": "...", "shows": "...", "headline": false}],
    "tables": [{"redraws": "R4.T1 or null", "csv": "<name>.csv", "data_view": "...", "inputs": ["<manifest path>"],
                "purpose": "...", "data": "...", "shows": "..."}],
    "synthesis": "...", "headline": "...", "can_infer": ["..."], "cannot_infer": ["..."],
    "open_questions": ["..."], "left_out": [{"what": "<a view you did not draw>", "reason": "..."}],
    "earlier_figures": [{"figure": "D1#p7", "plot": "<the plot's png or redraws id, or null>",
                         "agrees": "agrees | disagrees | cannot tell", "note": "..."}]}
   ```

   Paths are relative to your drawing directory. `redraws` names the plot of the previous drawing
   you draw again, which keeps its id; null is a new plot. Purpose, Data, and What it shows
   (`shows`) explain every plot; every number in them is a value in `numbers.json`.
7. Run `wayline accept` from the worktree root and fix what failed. Then `git add` and
   `git commit` your drawing directory; leave nothing uncommitted.
8. Return the structured result with `status: done`, `outputs_written` naming your drawing
   directory's files, and, for each inference about the research beyond one plot, a finding under
   the result's heading whose provenance is your `numbers.json` and the key it reads.
