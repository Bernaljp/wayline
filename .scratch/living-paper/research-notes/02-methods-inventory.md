## Answer

- **Most of the inventory can be built mechanically, at no token cost.**
  - **Python.** A stdlib `ast` pass lists what each module defines and every library call with its positional and keyword arguments. `inspect.signature`, run inside the project's own pinned environment, then marks each argument as non-default, default, or computed at run time, and lists the defaults left unset.
  - **MATLAB and other languages without a parser here.** A tree-sitter grammar (tree-sitter-matlab) runs as a subprocess. Beside it sit a small table of documented defaults and a backward slice from each method call to the literal assignments that feed it.
  - **On PINF's measured code** these routes find every file-level instance of a written method or parameter that has code there: 103 of 103 in MATLAB and 15 of 15 in Python. Of the facts the Methods omit, they find 29 of 35 in MATLAB and 13 of 13 in Python. Each pass takes under a second.
- **Only a reading finds methods that are inline code rather than calls.** The six MATLAB facts the parsers miss are:
  - a hand-written forward Euler loop where the Methods say ODE45;
  - an RMSE that the Methods call an L2 norm;
  - a fitted coefficient overwritten after the fit;
  - two reconstructions that integrate the true coefficients instead of the fitted ones;
  - a derivative check that calls another system's model.
- **The Sonnet reading.** Under a JSON schema, Sonnet at medium effort read all 19 measured MATLAB files and found:
  - 102 of 103 written facts and 33 of 35 omitted ones, including 5 of the 6 parser misses;
  - no invented call site: every reported item greps at its reported line, once compound names are split into identifiers.

  Of its 48 concerns, 2 were wrong and 15 were housekeeping. It cost $1.42 at list price and 9.3 minutes for 3,244 lines.
- **The Haiku reading.** Haiku at low effort, on the ten fit scripts, cost a third as much ($0.39) and took as long (7.1 minutes). It listed 46 of the 54 method call sites (Sonnet listed 53), and it invented 4 items, among them an `odeset` call with tolerances in a script that has no solver. The grep check catches those.
- **Recommendation.**
  1. **Build the inventory by code.**
     - Extend the code dossier's `python_inventory` (`wayline/code_dossier.py:210-237`) with calls, arguments, and slices.
     - Put tree-sitter and tree-sitter-matlab (2.7 MB, MIT, offline once installed) in the tools venv and run them through `run_tool`, like the PDF converters. That fills the seam the dossier leaves for "universal-ctags or tree-sitter" (`wayline/code_dossier.py:544`).
     - Detect the language per file, not per repository.
  2. **Judge defaults where they are defined.**
     - Python: run the signature pass with the project's interpreter and pinned libraries, never the harness's or the latest. Defaults, and even signatures, change between versions.
     - MATLAB: use a documented-defaults table for the few functions that take options: the ODE solvers and `odeset`, `lsqcurvefit` with `optimoptions` or `optimset`, and `rng`.
  3. **Rank what the Methods must answer.**
     - Keep non-default method parameters.
     - Surface sensitive defaults even when they are unset: an unseeded random state, solver tolerances left at their defaults.
     - Drop cosmetic parameters (`Display`, `verbose`, plotting) and meaningless ones (`numpy.linspace`'s `num`).
  4. **Add a model reading only where the parser sees developed code.** That means function bodies, anonymous functions, and loops that update state.
     - Read per file, on the reader's rung (Sonnet, medium). The classifier's rung (Haiku, low) costs a third as much but missed call sites and invented items here.
     - Check each reported item by grepping its identifiers at its reported line.
     - Treat the reading's concerns as leads for the owner or the decider, never as facts.
  5. **Make the Methods check a Type-A gate.**
     - Every developed method and every non-default parameter in the inventory must map to a Methods entry. Whether the stated reason is adequate is a quality verdict, a Type-B gate.
     - The docx-to-text conversion drops every equation, and every variable name in Table M2. So the Methods' parameter table should be generated from the inventory, not typed. Compared by hand against the code values the slices expose, 10 of Table M2's 39 written cells for the measured systems disagree with the code.
- **Under each autonomy.** The inventory and the gate run the same way under `interactive`, `checkpoints`, and `autonomous`. What differs is who writes the "why" of a non-default parameter:
  - under `interactive` and at `checkpoints`, the owner confirms or writes it;
  - under `autonomous`, the writer drafts it from the ticket's context, and a verifier session (never the writer) judges it.
- **Not verified here.**
  - No MATLAB or Octave is installed, so no run-time value was evaluated; initial conditions computed by formulas stay formulas.
  - PINF's Python loads data files that its repository does not contain, so the run-time check (`get_params` on the fitted estimators) was shown on a synthetic probe only.
  - The doubled model output is inferred from token counts; the `json` envelope does not show the turns.

## 1. Setup

- **Ticket:** [Bernaljp/wayline #178](https://github.com/Bernaljp/wayline/issues/178), a child of the map [From any starting point to a paper that grows with the work](https://github.com/Bernaljp/wayline/issues/173). It serves brief section 1.4: every method developed or used in the code has its written counterpart in the Methods, with its parameters and the reason for any that is not the default.
- **Date:** 2026-09-28. Claude Code 2.1.283.
- **PINF material:** PINF_Project's `code/` and `02_methods/` were copied into a scratch directory outside the repository, and everything ran on the copy. Nothing of PINF appears in this note beyond file, function, and parameter names, and counts.
- **Measured files:**
  - MATLAB: the ten fit scripts `Scripts_Models/*_V4.m` (2,638 lines), the eight files of `Functions/NoiseFunctions`, and `Functions/Utils/ACDC.m`. That is 19 files, 3,244 lines, and 113,144 bytes. The whole MATLAB tree is 54 files and 5,492 lines.
  - Python: `DeepLearningNormalForms/`, with 8 modules (one of them empty) and 559 lines, among them the RF, KNN, and MLP classifiers. The Python elsewhere in the tree (`Scripts_Models/Figbars`, two plotting scripts) was not measured.
- **Environments,** all in scratch and built with uv:
  - `venv-pinned`: a uv-managed CPython 3.8.20 with the pins of the project's `environment.yml`: scikit-learn 1.2.2, numpy 1.24.3, scipy 1.10.1, and matplotlib 3.7.1. The system Python 3.8 lacks `distutils`.
  - `venv-latest`: CPython 3.12.3 with today's releases: scikit-learn 1.9.1, numpy 2.5.3, scipy 1.18.1, and matplotlib 3.11.2.
  - `venv-ts`: tree-sitter 0.26.0, tree-sitter-matlab 1.3.1, and tree-sitter-language-pack 1.20.0.
- **Two writes outside scratch, both undone:**
  - `uv python install 3.8` linked `~/.local/bin/python3.8`.
  - tree-sitter-language-pack fetched its manifest into `~/.cache/tree-sitter-language-pack/`, on the first call made before `configure(PackConfig(cache_dir=...))`.

  A tools-venv install has to guard against both.
- **The prototypes,** each a script in scratch, not in the repository:
  - `py_inventory.py`: the `ast` route.
  - `py_defaults.py`: the signature route, run with each venv's interpreter.
  - `m_regex.py` and `m_treesitter.py`: the two MATLAB parser routes, sharing `m_table.py`, the documented-defaults table.
  - `run_model.py`: the model route.
  - `truth_m.py`, `score_m.py`, `score_py.py`, and `methods_written.py`: the ground truth and the scoring.

The commands, with `$S` standing for the scratch directory (the Bash tool here refuses shell variables, so every command was run with literal paths):

```
soffice --headless --convert-to txt:Text --outdir $S/methods_txt $S/02_methods/PINF_V11_Methods_clean.docx
uv venv --python $S/uv-python/cpython-3.8-linux-x86_64-gnu/bin/python3.8 $S/venv-pinned
uv pip install --python $S/venv-pinned/bin/python scikit-learn==1.2.2 numpy==1.24.3 scipy==1.10.1 matplotlib==3.7.1
python3 $S/tools/py_inventory.py $S/code/PINF_Code/DeepLearningNormalForms $S/out/py_inventory.json
$S/venv-pinned/bin/python $S/tools/py_defaults.py $S/out/py_inventory.json $S/out/py_defaults_pinned.json
$S/venv-latest/bin/python $S/tools/py_defaults.py $S/out/py_inventory.json $S/out/py_defaults_latest.json
python3 $S/tools/m_regex.py $S/code/PINF_Code $S/out/m_regex.json @$S/targets.txt
$S/venv-ts/bin/python $S/tools/m_treesitter.py $S/code/PINF_Code $S/out/m_ts.json @$S/targets.txt
python3 $S/tools/run_model.py sonnet medium $S/model/prompt_v4.md $S/model/schema.json $S/model/out_sonnet_v4.json
python3 $S/tools/run_model.py sonnet medium $S/model/prompt_noise.md $S/model/schema.json $S/model/out_sonnet_noise.json
python3 $S/tools/run_model.py haiku low $S/model/prompt_v4.md $S/model/schema.json $S/model/out_haiku_v4.json
```

## 2. The human reference: what the Methods write

- **The conversion.** LibreOffice converted `PINF_V11_Methods_clean.docx` to 922 lines of text in 2.7 s.
  - Every equation object is dropped. Inline symbols vanish from sentences, and the numbered equations leave only their numbers.
  - Table M2 keeps its numbers but loses the variable each number belongs to: an initial-condition cell arrives as bare values.
  - A check that reads the Methods therefore cannot rely on the converted text for anything written as math.
- **What the Methods write.** Counting one entry per named procedure, and one per named setting (a table column counts once), they write 48 methods and 40 parameters.

  | Where the code is | Methods | Parameters |
  | --- | --- | --- |
  | In the measured files | 21 | 20 |
  | Elsewhere in the repository (the normal-form rescaling of section 2.2) | 1 | 1 |
  | Nowhere in the repository | 26 | 18 |
  | Not code (the MATLAB release) | 0 | 1 |

  The 26 methods with no code are SINDy with STLSQ and its metrics (section 3), the scipy `minimize` fits of section 5, the classifiers' data generation (6.1 and 6.2), the neural encoder with torchdiffeq and Adam (section 7), and three robustness sweeps (1.2.3, 1.2.4, 1.4). Section 8 says the repository reproduces the results, so the inventory also serves the reverse check, from Methods to code.
- **The facts scored below.** They are the written items that have code in the measured files, counted per file:
  - MATLAB, 103: for example `ode45` in eight scripts; `lsqcurvefit`, the cubic model `F1`, the hidden-variable map `mufunc`, and the initial guess `weights0` in ten; the noise grid `VectorOfNoise` in nine; `calculateAvgR2`; `add_Noise_Max`; `xNormalization`; `noise_5_Boxplots` and its `iteration`; and the 39 written cells of Table M2 for the ten measured systems.
  - Python, 15: the three classifiers, their five named hyperparameters, `accuracy_score`, the split proportion, the repetitions, the subsample, the noise model, the noise grid, and the absence of any hyperparameter search.

  Against them stand the code facts the Methods omit, found by reading the code line by line: 35 in MATLAB and 13 in Python (section 8).

## 3. Python: `ast`, then `inspect.signature`

### 3.1 What the `ast` pass lists

`py_inventory.py` (stdlib only, 0.06 s) parses each module and records:

- the imports, resolved to dotted targets;
- `sys.path.append` directories, so local helper modules resolve;
- every `def` and `class`, with the defaults from its own signature;
- every call, with each argument's source, its literal value when `ast.literal_eval` reads it, and a transitive slice of the assignments and loop ranges that feed it.

It never imports or runs project code: these modules are scripts that would run.

On `DeepLearningNormalForms/` the pass gives 8 modules, 5 definitions, and 168 calls, which split as follows.

| Kind of call | Count |
| --- | --- |
| Third-party library calls | 73 |
| Instance calls whose class was inferred (`fit` and `predict` through the dict of estimators) | 4 |
| Calls into the project's own functions (`add_noise`, `get_descriptive_initials`, `process_dataset`, `plot_accuracies`) | 6 |
| Standard library | 26 |
| Builtins | 24 |
| Unresolved | 35 |

The 35 unresolved calls are dict and list methods, `ax[idx].boxplot` (a subscripted receiver), and `pdf.savefig` (bound by a `with` statement).

The slices link each value to the call that uses it:

- the noise level passed to `add_noise` resolves to its `numpy.linspace` grid;
- the `size` of `numpy.random.choice` resolves to the subsample fraction;
- the loop over dataset sizes resolves to the list of fractions.

### 3.2 Which arguments differ from the default

`py_defaults.py` imports only the called libraries. It takes `inspect.signature` of each callee, maps the call's arguments to parameter names with `Signature.bind_partial`, and compares each literal with the parameter's default. For an instance method named through its class, the first parameter is dropped. For a project function, the defaults come from the `ast` reading of its `def`.

- **Under the pinned versions** (0.84 s, 91 call targets):
  - Marked non-default:
    - `MLPClassifier`: `max_iter` (default 200) and `random_state` (default `None`);
    - `RandomForestClassifier`: `max_depth` and `random_state` (both default `None`);
    - `KNeighborsClassifier`: `n_neighbors` (default 5);
    - `train_test_split`: `test_size` (signature default `None`, documented as 0.25 when `train_size` is also `None`);
    - `f1_score`: `average` (default `'binary'`).
  - `shuffle` is marked as the default passed explicitly.
  - `train_test_split` is marked unseeded: `random_state` left at `None`.
  - The effective defaults are listed: 21 unset parameters for the MLP (among them `hidden_layer_sizes`, `solver`, and `learning_rate_init`), 16 for the random forest, and 7 for KNN.
  - A tree rule over the same inventory finds 5 draws from numpy's global random state and no seed anywhere.
- **Where signatures fail.** `numpy.random.choice` and `numpy.random.normal` have no signature under numpy 1.24.3: they are C methods of `RandomState`, with no text signature. The subsample's `replace` argument, set against its default, therefore goes unmarked there.
- **Under the latest versions** the classifier marks are the same, but two things change:
  - `numpy.random.choice` gains a signature under numpy 2.5.3, so `replace` is marked non-default.
  - A `matplotlib.pyplot.boxplot` call passing `labels` no longer binds under matplotlib 3.11.2: the parameter was renamed `tick_labels` in 3.9, and 3.7.1 still accepts `labels`.

  The three classifiers' effective defaults are unchanged between scikit-learn 1.2.2 and 1.9.1, apart from the random forest's added `monotonic_cst`. Defaults do move over time, though: scikit-learn's own source records `n_estimators` changing from 10 to 100 in 0.22 (`sklearn/ensemble/_forest.py:1099-1101` in 1.2.2). The pass has to run with the versions the results were produced with.
- **Scores.**
  - Written facts: all three variants find 15 of 15.
  - Omitted facts: `ast` alone finds 10 of 13. It lists the values but cannot see the unseeded split, the unset defaults, or the library versions. With signatures, both versions find 13 of 13.
  - Noise: 5 marks on `numpy.linspace`'s `num` are true but need no "why".
  - False positives: before a CamelCase guard, the one-step class inference typed a function's return value as an instance and invented `train_test_split.ravel` three times.

### 3.3 What it misses

PINF's Python has no `**kwargs` forwarding, configuration file, command-line argument, or wrapper. So a 30-line synthetic probe in scratch built one estimator from each case. It was then run with `--depth 7` and a JSON configuration, and the estimators' `get_params()` were compared with fresh instances. At run time, 8 parameters differ from the default:

| Case | At run time | The `ast` and signature pass sees |
| --- | --- | --- |
| Command-line argument (`argparse`) | `max_depth` set | `max_depth=args.depth`, computed, value unknown |
| Configuration file through `**kwargs` into a wrapper | `criterion`, `n_estimators` set | `**cfg`: nothing |
| `functools.partial` | `n_estimators`, `random_state` set | a stdlib call; nothing |
| A value computed at run time | `min_samples_leaf` set | computed, with its source expression in the slice |
| A `Pipeline.set_params` override | the SVC's `C` set | nothing |
| A literal inside `make_pipeline` | the SVC's `gamma` set | non-default, exactly |

So the static pass recovers 1 of the 8 values exactly, shows 2 as computed, and misses 5. A tuned value from `GridSearchCV` is known only at run time. The complete answer for Python is a run-time record (each estimator's `get_params()` after `fit`, written by the job). That needs the code to run with its data, which PINF's repository cannot do: `DataSets/` is not in it.

## 4. MATLAB, route (a): a regex and line-grammar pass

`m_regex.py` (stdlib only, 0.18 s for the 19 files) works per file.

1. It removes comments and `%{ %}` blocks and joins `...` continuations, with a scanner that tells a string quote from the transpose quote.
2. It reads `function` lines as definitions and `name = @(...)` as anonymous functions.
3. It treats every `name(` whose name is not a variable of the file as a call. A variable is any name assigned, used as a loop variable, or taken as a parameter.
4. It classifies each call through `m_table.py` or as a project function when the tree defines it.
5. It cuts arguments at top-level commas, pairs name-value options, and marks them against the documented defaults.
6. It slices each call back to its literal assignments.

- **Two scanner bugs in the first version:**
  - a statement splitter that cut `odeset(...)` at commas nested inside parentheses;
  - calls matched inside strings, which produced three phantom calls: a Greek-letter macro in two LaTeX titles, and a distribution's name in a format string.

  A depth-aware splitter and string masking fixed both.
- **What remains.** 100 calls to the builtins `set` and `get` are classified as project functions, because the vendored `Violin.m` classdef defines property accessors (`function set.X`, `function obj = get.X`). The pass also cannot see command syntax (`hold on`).
- **Scores.** On the facts it equals tree-sitter exactly: 103 of 103 written and 29 of 35 omitted.

## 5. MATLAB, route (b): tree-sitter

`m_treesitter.py` runs tree-sitter 0.26.0 with the tree-sitter-matlab 1.3.1 grammar (MIT; the wheel carries the compiled grammar, 648 KB, with tree-sitter's own 2.0 MB). It takes 0.23 s for the 19 files, including an index of every function the whole tree defines.

- **Parse quality.** All 19 files parse without error nodes, except for one MISSING statement terminator at the end of `Saddle_V4.m`, which has no final newline. With a newline appended the tree is clean, and the last call parses whole either way.
- **The grammar in the language pack.** tree-sitter-language-pack's `matlab` parser produced the identical tree on a probe of the hard cases: command syntax, continuations, an `arguments` block, name-value calls, anonymous functions, and transposes. But the pack downloads its grammars at run time (a 23 MB bundle), while tree-sitter-matlab needs no network after install.
- **The grammar's shape.**
  - `f(x)` is a `function_call` whether `f` is a function or an array, so the route needs the same variable table as the regex route.
  - Command syntax is a `command` node.
  - An `arguments` block parses with `default_value`, which gave the one project-function default in the measured files: the `resolution` argument of `noise_5_Boxplots`.
- **Output:**
  - 8 definitions, among them the same function name defined in two files (`noise_5_Boxplots`);
  - 21 anonymous functions: `F1` and `mufunc` in each script, and `polyfunc`;
  - 24 loops;
  - 1,288 calls and function handles: 148 numeric (65 of them carrying a method: the ODE solvers, `odeset`, `lsqcurvefit`, the option builders, `randn`, `diff`, and `norm`), 82 project, 679 plotting, 377 workspace, and 2 handles to project functions.
- **Marks:**
  - `RelTol` and `AbsTol` non-default in the nine scripts that call `odeset`;
  - `Display` non-default in nine option builders;
  - 15 option arguments left at their defaults (14 calls to `lsqcurvefit`, and the generation run of `ode45` in `Transcritical_V4.m`);
  - `randn` flagged as unseeded, since no `rng` exists anywhere in the tree.
- **Slices.** 318 distinct literal-valued bindings feed method or project calls, 21 to 53 per script. Every Table M2 cell's code value is among them, but so is much else.
- **Scores:** 103 of 103 written and 29 of 35 omitted. The six misses are the inline methods listed in the Answer; each is code, not a call.

A generic layer exists too: the language pack ships `tags` queries (definitions and call references) for MATLAB, Python, R, C++, and Fortran, but not Julia. Tags give no arguments, so each language still needs a small adapter for calls, assignments, and keyword or name-value arguments.

## 6. MATLAB, route (c): a model reading under a JSON schema

### 6.1 The three calls and their usage fields

Each call ran `claude -p` with the prompt on stdin, so that 102 KB did not pass as a single argument. The flags were:

- `--model` and `--effort` as in the table below;
- `--output-format json` and `--json-schema` (the schema without a `$schema` key, which the CLI refuses: `wayline/worker.py:1087-1106`);
- `--no-session-persistence` and `--permission-mode dontAsk`;
- `--disallowedTools` with the deny list of `roles/classifier/wayline.json`, which leaves only `StructuredOutput`.

The prompt numbered every line and asked for four lists per file: developed methods, used calls with their parameters and documented defaults, settings, and concerns. The rungs match the policy's reader (Sonnet, medium) and classifier (Haiku, low) (`policy.json:21`, `policy.json:29`). No permission was denied in any call.

| Field | Call 1 | Call 2 | Call 3 |
| --- | --- | --- | --- |
| Model, effort | `claude-sonnet-5`, medium | `claude-sonnet-5`, medium | `claude-haiku-4-5-20251001`, low |
| Files (lines) | 10 fit scripts (2,638) | 8 noise files and `ACDC.m` (606) | 10 fit scripts (2,638) |
| `duration_ms` | 450,578 | 105,996 | 427,549 |
| `num_turns` | 4 | 3 | 3 |
| `input_tokens` | 6 | 4 | 19 |
| `cache_creation_input_tokens` | 115,026 | 23,031 | 54,753 |
| `cache_read_input_tokens` | 152,365 | 33,617 | 49,077 |
| `output_tokens` (thinking) | 68,411 (8,525) | 14,456 (4,642) | 54,790 (5,711) |
| Output of the last message | 20,656 | 4,892 | 22,790 |
| `total_cost_usd` (list price) | 1.174699 | 0.243415 | 0.3883827 |

- **The answer is paid at least twice.** In every call, `result` parses to exactly the `structured_output` object. In call 2, the non-thinking output (9,814 tokens) is twice the last message (4,892 tokens). This matches the two `StructuredOutput` calls recorded in `docs/verification/m0.md:501-504`.
- **Call 1 re-emitted more.** Its non-thinking output (59,886 tokens) is 2.9 times its last message: one more emission, or a partial one, that the envelope does not explain.
- **Call 3 emitted twice.** Its non-thinking output (49,079 tokens) is 2.2 times its last message.
- **What it costs per line.** For Sonnet at medium effort, reading costs about $0.40 to $0.45 per 1,000 lines at list price, so the whole MATLAB tree (5,492 lines) would take about $2.3 per reading. For Haiku at low effort, it costs about $0.15 per 1,000 lines, but Haiku was no faster.

### 6.2 What the readings found

- **Sonnet on the ten fit scripts** returned 27 developed methods, 53 used calls, 91 settings, and 34 concerns.
  - It lists 53 of the 54 method-carrying call sites tree-sitter finds. It described the 54th, `diff` in `Saddle_V4.m`, as an inline finite-difference procedure.
  - Written facts: 96 of 97. It missed the initial conditions of `HH_V4.m`.
  - Omitted facts: 32 of 33. It missed that `Volterra_V4.m` integrates the true coefficients.
  - It found the forward Euler loops of `HH_V4.m` and the overwritten coefficient of `Toggle_V4.m` (and that `F1` there never uses it). It also found the options commented out of one `ode45` call in `Transcritical_V4.m`, the saddle-node model in that script's derivative check, and the true coefficients in `vanderpol_V4.m`.
  - It found one fact the ground truth lacked: `Hopf_V4.m` overwrites a fitted coefficient with its true value before reconstructing.
  - Of its 34 concerns, 21 are true and about the method and 12 are housekeeping (a `tic` without `toc`, a duplicated `clear`, an absolute `addpath`). One is wrong: at `Hopf_V4.m` line 233 it says the derivative check uses the partly fitted `C_predicted`, but the code packs the true `c`.
  - Every default it gave for `odeset` and the option builders agrees with MathWorks.
- **Sonnet on the noise files and `ACDC.m`** returned 14 developed methods, 14 used calls, 4 settings, and 14 concerns. Written facts: 6 of 6. Omitted facts: 1 of 2.
  - It found that the error the plots label an L2 error is an RMSE, that `noise_5_Boxplots` is defined in two files, that `noise_Scale_maximum` computes a true norm instead, that `xNormalization` returns `yzero` unchanged, and that `ACDC` takes the log of its state.
  - It never mentioned that `randn` is unseeded, which the parser routes flag mechanically.
  - Of its 14 concerns, 10 are true, 3 are housekeeping, and 1 is wrong: it calls the derivative R² "silently excluding the first state variable", but column 1 is time in these systems.
- **Haiku on the ten fit scripts** returned 30 developed methods, 103 used calls, 150 settings, and 26 concerns.
  - Written facts: 94 of 97. It missed `F1` in `HH_V4.m` and the initial conditions of `HH_V4.m` and `FitzHugh_V4.m`.
  - Omitted facts: 31 of 33. It missed the default tolerances of one `ode45` call in `Transcritical_V4.m` and the true coefficients in `Volterra_V4.m`.
  - It listed only 46 of the 54 method-carrying call sites, and padded `used` with calls the prompt said to skip (`save`, `addpath`, and nine calls to a plotting function).
  - It invented 4 items: an `odeset` call at line 50 of `HH_V4.m`, with `RelTol` and `AbsTol` settings, in a script that calls no solver; and a call to `plotNoisyStateFig_5` in `Pitchfork_V4.m`, which makes none.
  - Of its 26 concerns, 19 are true (10 of them repeat one observation, that `xMax` is recomputed after integration), 3 are housekeeping, and 4 are wrong. Among the wrong ones: an `xMax` said to be overwritten at a line that does not touch it, and two concerns that treat the reconstruction's use of the fitted coefficients as a defect.

### 6.3 How a model-read inventory is checked

`score_m.py` greps each reported item's identifier on its reported line, allowing one line of slack. A developed inline procedure has only its line range checked.

- **Strict grep** of the reported name: call 1 verified 163 of 171 items. The 8 failures were all naming variants rather than invented facts: `p1..p4`, `cPitch/c`, `cLV/c`, and `xMax_initial` for `xMax`.
- **Tokenized grep,** splitting the name into identifiers: 171 of 171 in call 1 and 32 of 32 in call 2. No call site was absent from the code in either Sonnet call.
- **Call 3 (Haiku):** 279 of 283 items verified. The 4 failures are the invented items of section 6.2: two call sites and two settings that exist nowhere in the files where Haiku placed them.
- **Defaults** are judged against the documented-defaults table: no Sonnet claim was wrong.

What the grep cannot check is a concern's claim. Both of Sonnet's wrong concerns sat at real lines that do hold a problem, but the model's account of it was false. So a harness should verify the items mechanically and route the concerns to a person or a verifier session, as leads.

## 7. The routes side by side

| Route | Needs | Wall time | Tokens | Written facts | Omitted facts | False positives and noise |
| --- | --- | --- | --- | --- | --- | --- |
| Python `ast` | stdlib | 0.06 s | 0 | 15/15 | 10/13 | 3 invented instance calls before the CamelCase guard |
| Python `ast` + `inspect.signature` | the project's environment (286 MB here) | 0.84 s | 0 | 15/15 | 13/13 | 5 meaningless `num` marks; 2 callees without a signature under numpy 1.24.3 |
| MATLAB regex | stdlib | 0.18 s | 0 | 103/103 | 29/35 | 100 `set` and `get` calls taken for project functions |
| MATLAB tree-sitter | 2.7 MB of wheels in the tools venv | 0.23 s | 0 | 103/103 | 29/35 | none misclassified |
| MATLAB, Sonnet medium, 19 files | usage | 557 s | 82,867 output | 102/103 | 33/35 | 2 wrong concerns of 48; 15 housekeeping |
| MATLAB, Haiku low, 10 fit scripts | usage | 428 s | 54,790 output | 94/97 | 31/33 | 4 invented items of 283; 4 wrong concerns of 26 |

Two kinds of noise are shared by both parser routes:

- 9 of their 27 non-default marks are the cosmetic `Display`;
- 83 of their 148 numeric calls are arithmetic helpers (`exp`, `max`, `abs`, `sqrt`) rather than methods.

The model's 91 settings for the fit scripts against the parser's 318 literal bindings show the other difference. A reading selects and names the parameters, while a slice is complete but has to be filtered and labeled.

## 8. What the code has that the Methods omit

These are counts and identifiers, found by reading the code and confirmed by the routes as shown in section 7.

**MATLAB (35 facts):**

- **Solver tolerances.** `RelTol` and `AbsTol` are set far below their defaults in the nine scripts that call `odeset`; the Methods never state tolerances.
- **Other integrators.** `FitzHugh_V4.m` uses the stiff solver `ode23s`, and `HH_V4.m` uses a hand-written forward Euler loop, while the Methods say ODE45 throughout. In `Transcritical_V4.m`, the generation run of `ode45` leaves its tolerances at the defaults.
- **An unseeded draw.** `randn` in `add_Noise_Max` runs with no `rng` anywhere. MATLAB starts each session from the same factory seed (settings can change it since R2023b), so results repeat only from a fresh session.
- **The error metric.** It is an RMSE in `noise_5_Boxplots` (and its twin `noise_5_Boxplots2`), where the Methods say L2 norm. The one function computing a true `norm` (`noise_Scale_maximum`) is never called.
- **Noise settings the Methods do not state.** The noise grid `VectorOfNoise` of `vanderpol_V4.m` sits four orders of magnitude below the stated range. The single-fit `noise_scale` differs by script (`Saddle_V4.m`, `Lorentz_V4.m`, `vanderpol_V4.m`).
- **A derivative check.** Derivative R² from finite differences (`diff`, `function_CalcDerivatives`) runs in `Saddle_V4.m`, `Hopf_V4.m`, and `Transcritical_V4.m`.
- **Post-fit overrides.** `weightdx(1)` and `weightdxNoise(1)` in `Toggle_V4.m` are overwritten with zero.
- **Reconstructions with the true coefficients.** `vanderpol_V4.m` assigns the true `c` to `C_predicted`, and `Volterra_V4.m` passes `c` to the solver directly.
- **Another system's model** in a check: `@saddlenodeNewPoli` in `Transcritical_V4.m`.
- **Parameters absent from Table M2.** The time-scaling factor `reescaleTimeJin` in `Toggle_V4.m`, and a time step `dt` in `FitzHugh_V4.m` where the table leaves the cell blank.
- **Values that disagree with Table M2.** Compared by hand against the code values the slices expose, 10 of the table's 39 written cells for the measured systems disagree with the code: the time step in four scripts, the polynomial coefficients in four, and the initial conditions in two (one of them because the code rescales by a factor the table does not give). Another 4 cells hold initial conditions the code computes by formula after normalizing, so they are left out of the count. The remaining 25 agree.

**Python (13 facts):**

- **Hyperparameter values.** The values of `n_neighbors` and of both `random_state` arguments are unstated; the Methods name KNN's hyperparameter without its value.
- **Subsample fractions.** The fraction behind `reduced_size` in `ClassificationComparisonRF_MLP_KNN.py` is a tenth of the fraction the Methods state. `RForest_Noise.py` and `DownsamplingComparison.py` use other fractions and a list of dataset sizes.
- **Seeds.** The split has no `random_state`, and five draws from numpy's global random state run unseeded.
- **Noise grids.** The grid `noise_levels` includes zero where the Methods start at the first nonzero level, and `RForest_Noise.py` uses a wider grid.
- **An extra metric.** `f1_score` with micro averaging (`average` set against its default) in `RForest_Noise.py` appears nowhere in the Methods.
- **What stays unset.** The MLP's 21 unset defaults (architecture, solver, learning rate), and the library versions of `environment.yml`.

## 9. Where this fits in the harness

- **The existing inventory.** `python_inventory` (`wayline/code_dossier.py:210-237`) reads module-level functions, classes, `__all__`, decorators, and docstrings: no calls and no arguments.
  - `detect_language` (`wayline/code_dossier.py:197-203`) answers `"python"` as soon as any `.py` file exists. PINF's repository, mostly MATLAB, would be inventoried as Python only.
  - Every other language gets the note "universal-ctags or tree-sitter is not yet wired" (`wayline/code_dossier.py:544`).
- **A template for the check.** `docs.public_symbols` (`wayline/docs.py:153-164`) turns that inventory into the documentation site's Type-A gate: every public symbol has a docstring (`wayline/docs.py:602-614`). The Methods check proposed here has the same shape: every developed method and non-default parameter has a Methods entry.
- **Where tree-sitter lives.** The harness imports no third-party package. Its optional tools venv holds packages that run only as subprocesses (`wayline/tools.py:1-19`), declared in `PACKAGES` (`wayline/tools.py:49-55`) and run through `run_tool` (`wayline/tools.py:73`). A `tree-sitter` entry and a helper script beside `converters/` would follow that pattern.
- **Where the signature pass runs.** It needs the project's own environment, which the map lets the harness install outside autonomous runs.
- **Who writes the inventory.** Code, from the diff of a ticket's touch set, into the ledger. No result field carries a method or a parameter today (`schemas/result.json`), and the worker does not need to report one.

## Sources

- The ticket, [Bernaljp/wayline #178](https://github.com/Bernaljp/wayline/issues/178), and the map, [#173](https://github.com/Bernaljp/wayline/issues/173); the owner's brief, section 1.4 (`.scratch/living-paper/owner-brief.md`, untracked).
- Python `ast`, `literal_eval`, and `unparse`: https://docs.python.org/3/library/ast.html
- Python `inspect.signature`, `Signature.bind_partial`, and `Parameter.empty`: https://docs.python.org/3/library/inspect.html
- scikit-learn 1.2 `train_test_split` (the signature and the 0.25 effective default): https://scikit-learn.org/1.2/modules/generated/sklearn.model_selection.train_test_split.html
- scikit-learn 1.2.2 source, `sklearn/ensemble/_forest.py:1099-1101` (`n_estimators` changed from 10 to 100 in 0.22), read in `venv-pinned`.
- Matplotlib 3.9.0 API changes (`boxplot` `labels` renamed `tick_labels`): https://matplotlib.org/stable/api/prev_api_changes/api_changes_3.9.0.html
- MathWorks `odeset` (`RelTol` 1e-3, `AbsTol` 1e-6, `MaxStep`): https://www.mathworks.com/help/matlab/ref/odeset.html
- MathWorks `lsqcurvefit` (the syntaxes, empty bounds, and option defaults: `trust-region-reflective`, `Display` `final`, tolerances 1e-6, 400 iterations): https://www.mathworks.com/help/optim/ug/lsqcurvefit.html
- MathWorks `rng` (the factory default generator and seed at session start): https://www.mathworks.com/help/matlab/ref/rng.html
- MathWorks `ode23s` (a low-order stiff solver): https://www.mathworks.com/help/matlab/ref/ode23s.html
- tree-sitter-matlab grammar (MIT): https://github.com/acristoffers/tree-sitter-matlab; PyPI `tree-sitter-matlab` 1.3.1, whose project URL points there.
- py-tree-sitter 0.26.0: https://github.com/tree-sitter/py-tree-sitter
- tree-sitter-language-pack 1.20.0 (371 grammars, downloaded at run time into a cache): https://github.com/xberg-io/tree-sitter-language-pack
- Claude Code 2.1.283, `claude --help` (`--json-schema`, `--output-format`, `--no-session-persistence`, `--disallowedTools`, `--effort`).
- In this repository:
  - `wayline/code_dossier.py:197-203`, `210-237`, `544`;
  - `wayline/docs.py:153-164`, `602-614`;
  - `wayline/tools.py:1-19`, `49-55`, `73`;
  - `wayline/worker.py:1087-1106`;
  - `roles/classifier/wayline.json`;
  - `policy.json:21`, `29`;
  - `docs/verification/m0.md:501-504`;
  - `schemas/result.json`;
  - `CONTEXT.md` (Type-A gate, ledger, touch set, verifier session, autonomy).
- Measured locally, in a scratch copy of PINF_Project (read-only reference): `code/PINF_Code/Scripts_Models/*_V4.m`, `Functions/NoiseFunctions/*.m`, `Functions/Utils/ACDC.m`, `DeepLearningNormalForms/*.py` and `environment.yml`, and `02_methods/PINF_V11_Methods_clean.docx`, converted with LibreOffice `soffice --headless --convert-to txt:Text`.
