# Installing software without root on this workstation

Research ticket "Installing software without root on this workstation" ([#179](https://github.com/Bernaljp/wayline/issues/179)) on the map "Map: from any starting point to a paper that grows with the work" ([#173](https://github.com/Bernaljp/wayline/issues/173)). It feeds the grilling ticket "Asking for and installing software a project needs" ([#188](https://github.com/Bernaljp/wayline/issues/188)). Measured on 2026-09-28 on the owner's workstation, in a scratch directory outside the repository and outside PINF_Project; every prefix and download was removed afterwards (see "Cleanup").

## Answer

- **Everything the ticket names installs without root in under a minute each, except MATLAB.** micromamba with the conda-forge channel covers Octave, R, and pandoc; Julia comes as the official tarball. Measured here, wall time including the download:

  | What | Route | Version | Download | On disk | Time |
  |---|---|---|---|---|---|
  | micromamba | official static binary | 2.9.0 | 7 MB | 18 MB | 5 s |
  | GNU Octave | conda-forge `octave` | 10.3.0 | 460 MB | 1.8 GB | 16 s |
  | Octave's `optim` | Octave Forge (`struct`, `optim`) and conda-forge (`octave-statistics`) | 1.6.3 | 2.5 MB | 16 MB | 53 s |
  | pandoc | conda-forge `pandoc` | 3.11 | 23 MB | 157 MB | 1.6 s |
  | pandoc | release tarball | 3.11 | 35 MB | 157 MB | 2.6 s |
  | pandoc | `pypandoc_binary` wheel, with uv | bundles pandoc 3.9 | 34 MB | 155 MB | 2.6 s |
  | R | conda-forge `r-base` | 4.6.1 | 259 MB | 1.4 GB | 8 s |
  | Julia | official tarball | 1.13.1 | 302 MB | 1.1 GB | 11 s |
  | MATLAB | the owner's license, then MathWorks' `mpm` | R2026b | not measured | 4.5 GB for MATLAB alone, 5 to 7 GB typical (published) | not measured |

- **Octave does not run PINF's fits as they are written.** conda-forge has no `optim`. It installs from Octave Forge once the compiler is pointed at the system's GCC and `statistics` comes from conda-forge (Forge's newest `statistics` needs Octave 11.1), and it brings `lsqcurvefit`. The copied `vanderpol_V4.m` then stops, in order, at:
  1. three `addpath` folders spelled in a case the repository does not have (`utils` for `Utils`), which do not exist on Linux's case-sensitive file system, whichever program runs the script;
  2. `xline` ("not yet implemented in Octave"), with `yline`, `sgtitle`, and `exportgraphics` behind it;
  3. MATLAB's dot syntax for setting a property of a graphics handle, here a legend's ("scalar cannot be indexed with ."), 70 such lines in the script and its two plotting helpers;
  4. `optimoptions`, which no Octave package has;
  5. `lsqcurvefit` returning a column where MATLAB returns the shape of `x0` ("vertical dimensions mismatch (1x4 vs 4x1)");
  6. an `arguments` block, which Octave ignores ("INCORRECT RESULTS ARE POSSIBLE"), so a default it sets never exists ("'resolution' undefined").

  With a scratch-only stand-in for each, the script ran through both fits and the reconstruction. The fits converge: optim's `lsqcurvefit` reaches the same minimum as a direct least-squares solve of the same data. Yet under Octave both fits land far from the coefficients the script generates its data with, which the solver does not explain. The first `ode45` integration alone took 290 s. So Octave means porting PINF's scripts, not running them, and a port still has to be checked against numbers MATLAB produced, which was not possible here.
- **Recommendation: one installer, one shared place, and a record per tool beside the docling venv's.**
  - The harness keeps its own micromamba at `~/.wayline/tools/bin/micromamba`, with `MAMBA_ROOT_PREFIX=~/.wayline/tools/mamba` and `CONDA_PKGS_DIRS=~/.wayline/tools/mamba/pkgs`; without the second, micromamba 2.9.0 created `~/.mamba/pkgs` in the home. One prefix per tool: `~/.wayline/tools/envs/octave`, `envs/r`, `envs/pandoc`.
  - Julia from the official tarball into `~/.wayline/tools/julia-1.13.1/`, not juliaup, which by default edits shell startup files and checks for its own updates once a day.
  - Pandoc from conda-forge: it is the release tarball's binary (the same build ID), current, and one more package through the same installer. `pypandoc_binary` bundles an older pandoc (3.9) and only helps Python code that imports pypandoc, which the standard-library harness never does.
  - Each tool gets an entry in `tools.json`, as the docling venv has: the absolute executable, the version, the environment it needs (`OCTAVE_HOME` for Octave), and the prefix's explicit lock (`micromamba env export --explicit`, package URLs with hashes), so a later run knows what is there and can build it again.
  - Shared rather than per project, because a runtime is 1 to 2 GB and belongs to the machine, like the 7 GB docling venv. What varies by project is the package set: an R library, a Julia project environment, and Octave Forge packages only if two projects need different versions (otherwise `pkg install -global` puts them in the shared prefix, measured).
- **A job names the absolute path and carries the environment.** Under the user manager a job's `PATH` is the manager's: no `~/.local/bin`, no tool prefix, and a bare `Rscript` finds the system's R 4.4.3 at `/usr/bin/Rscript` (measured). `systemd-run` resolves a bare program name against the conductor's `PATH`, which differs between `wayline run --detach` from a shell and a relaunch by the tick. The job file already has `command` and `env`, and `systemd_run_argv` passes every `env` entry with `-E`, so a job needs no new field: argv[0] comes from `tools.json`, and `env` carries `OCTAVE_HOME` for Octave and `JULIA_DEPOT_PATH` for Julia. No role's `allowed_tools` admits these programs today (`roles/*/wayline.json`), so a worker reaches them through a job.
- **MATLAB stays the owner's.** PINF's fits need a license for MATLAB, Optimization Toolbox (`lsqcurvefit`, `optimoptions`), and, for the noise helper's `boxplot`, Statistics and Machine Learning Toolbox. The owner installs it without root with `mpm` into a folder in the home and activates it by signing in (or points it at a license server, for a Concurrent license); a job then calls `<matlabroot>/bin/matlab -batch "..."`, which exits nonzero on an error. The free MATLAB Runtime runs only applications built with MATLAB Compiler, itself licensed, so it cannot run PINF's `.m` scripts as they are.
- **What an install asks of the owner** (for "Asking for and installing software a project needs"). Apart from MATLAB, each install is one command that needs the network and no root, takes seconds to a minute, writes only under `~/.wayline/tools/` once the variables above are set (and Octave packages go in with `-global`), and is undone by deleting one folder and its `tools.json` entry. MATLAB alone needs the owner's hands: the license, the sign-in, and the choice of toolboxes.
- **Not verified:** anything that needs a MATLAB license (installing, activating, a `-batch` run under the user manager); Octave 11.3 (conda-forge is at 10.3.0; the official container image is 1.5 GB compressed); a headless PDF export from Octave; conda-forge's compilers in place of the system's GCC for Octave packages; installing R or Julia packages; the numbers MATLAB gives for the same fit; juliaup, which was not installed; and the route that "Converting documents both ways with the tools on this machine" ([#177](https://github.com/Bernaljp/wayline/issues/177)) will recommend, whose note was not published yet, so both pandoc routes that ticket names are measured here.

## Evidence

### 1. How this was measured

- **Scratch.** Everything was installed under `/home/bernaljp/.claude/jobs/2a81684c/tmp/research-installing/`, outside the repository and outside `~/Documents/PINF_Project`. `MAMBA_ROOT_PREFIX` (and, after the first probe, `CONDA_PKGS_DIRS`) pointed there; Octave ran with `HOME` and `TMPDIR` there, R and Julia with `HOME` there, and Julia with `JULIA_DEPOT_PATH` there.
- **As a job would run it.** Each program was started by its absolute path in an empty environment, `env -i HOME=<scratch home> PATH=/usr/bin:/bin <program>`, plus only the variables named below.
- **Times.** Wall clock, from `/usr/bin/time -f %e` or differences of `date +%s.%N`, on this workstation's network, measured once each (the Octave integration twice). Read them as orders of magnitude.
- **Sizes.** `du -sh`, which counts a hardlinked file once per call.
- **The main commands**, with `S` the scratch directory and `<probe>` a small script of this session's own:

```sh
export MAMBA_ROOT_PREFIX=$S/mamba CONDA_PKGS_DIRS=$S/mamba/pkgs
curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest -o $S/micromamba.tar.bz2
tar -xvjf $S/micromamba.tar.bz2 -C $S bin/micromamba
$S/bin/micromamba create --dry-run -y -p $S/envs/octave -c conda-forge octave   # then without --dry-run
$S/bin/micromamba install -y -p $S/envs/octave -c conda-forge octave-statistics
env -i HOME=$S/home TMPDIR=$S/tmp PATH=/usr/bin:/bin OCTAVE_HOME=$S/envs/octave \
    CC=/usr/bin/gcc CXX=/usr/bin/g++ F77=/usr/bin/gfortran \
    $S/envs/octave/bin/octave-cli --no-init-file <probe>.m   # pkg install -forge struct, then optim
$S/bin/micromamba create -y -p $S/envs/pandoc -c conda-forge pandoc
curl -sSL -O https://github.com/jgm/pandoc/releases/download/3.11/pandoc-3.11-linux-amd64.tar.gz
UV_CACHE_DIR=$S/uv-cache uv venv --python /usr/bin/python3 $S/venv-uv
UV_CACHE_DIR=$S/uv-cache uv pip install --python $S/venv-uv/bin/python pypandoc_binary
$S/bin/micromamba create -y -p $S/envs/r -c conda-forge r-base
env -i HOME=$S/home PATH=/usr/bin:/bin $S/envs/r/bin/Rscript <probe>.R
curl -sSL -O https://julialang-s3.julialang.org/bin/linux/x64/1.13/julia-1.13.1-linux-x86_64.tar.gz
tar -xzf julia-1.13.1-linux-x86_64.tar.gz -C $S
env -i HOME=$S/home PATH=/usr/bin:/bin JULIA_DEPOT_PATH=$S/julia-depot \
    $S/julia-1.13.1/bin/julia --startup-file=no <probe>.jl
env PATH=<caller's PATH> systemd-run --user --quiet --wait --collect --unit=research-179-probe-<case> \
    --expand-environment=no -p StandardOutput=file:<out> -p StandardError=file:<out> [-E PATH=...] <argv>
SINGULARITY_CACHEDIR=$S/sing-cache SINGULARITY_TMPDIR=$S/sing-tmp \
    /opt/singularity-3.8.1/bin/singularity pull $S/alpine.sif docker://alpine:3.20
```

### 2. The machine

- Ubuntu 24.04.4 LTS, glibc 2.39, systemd 255, x86_64, 128 cores, 1 TB of RAM; `/home` has 9.8 TB free.
- **Present:**
  - GCC, G++, and GFortran 13.3.0, and `make`, in `/usr/bin`;
  - R 4.4.3 at `/usr/bin/R` (package `r-base-core 4.4.3-1.2004.0`), with a user library at `~/R/x86_64-pc-linux-gnu-library/4.4`;
  - uv 0.11.29 and an older micromamba 2.8.1 in `~/.local/bin`;
  - `xelatex`, `pdflatex`, and `latexmk`;
  - SingularityCE 3.8.1 in `/opt/singularity-3.8.1/bin`, with a setuid starter;
  - Docker, which the owner's user cannot reach (`permission denied while trying to connect to the docker API`; the user is not in the `docker` group).
- **Absent:** Octave, MATLAB, pandoc, Julia, juliaup, conda, and mamba.
- **No `python3 -m venv`.** It fails with "ensurepip is not available ... apt install python3.12-venv". That is why the tools venv was built with uv (`tools.json` records `"installer": "uv"`). `install_steps` uses `python -m venv` whenever uv is not on the `PATH` (`wayline/tools.py:179-185`), and that branch fails on this machine.

### 3. Prior art: `wayline tools install` and `tools.json`

- **What it installs.** `wayline tools install` creates the tools venv at `~/.wayline/tools/venv` with uv when uv is on the `PATH` and with `python -m venv` otherwise, installs torch from the index that matches the NVIDIA driver, then docling and pdfplumber (marker and MinerU on request), and pulls the GROBID image with `--grobid` (`wayline/tools.py:165-189`, `212-269`).
- **How it records it.** `~/.wayline/tools/tools.json`, written through a temporary file and a rename (`wayline/tools.py:272-280`) and rewritten from what the venv holds after every install, never merged (`wayline/tools.py:215-218`). The fields are `schema_version`, `created`, `python` (the venv's interpreter, absolute), `packages` (versions read inside the venv with `importlib.metadata`), `device`, `driver_cuda`, `torch_index`, `installer`, `docker_images`, and `notes` (`wayline/tools.py:244-255`). On this machine it records docling 2.126.0, pdfplumber 0.11.10, torch 2.14.0+cu126, `device: cuda`, and `installer: uv`; the venv is 7.0 GB.
- **How the harness finds it.** `tools_home()` is `~/.wayline/tools`, moved with `WAYLINE_HOME` (`wayline/tools.py:106-110`). `Tools` reads the record and gives the venv's interpreter only when the record exists and the file is there (`wayline/tools.py:113-137`). The PDF chain starts each converter as `[tools.python, converters/<name>.py, ...]` through `run_tool` (`wayline/pdf_inventory.py:184`, `378`, `385`, `1248`): always an absolute path, never a lookup on the `PATH`.
- **How a job would call it.** No job does today. A job file carries `command` (an argv), `cwd`, and `env` (`schemas/job.json:14-16`); `wayline job add` writes it (`wayline/resources.py:1676-1711`), and `systemd_run_argv` launches it with one `-E NAME=VALUE` per `env` entry (`wayline/resources.py:671-701`, the loop at `699-700`). A job could name `/home/bernaljp/.wayline/tools/venv/bin/python` as its argv[0].
- **Neighboring precedents.**
  - The worker looks for `claude` on the `PATH` and then in `~/.local/bin`, because the user manager's `PATH` lacks that folder (`wayline/worker.py:1605-1622`).
  - The detached conductor copies the caller's `PATH` and every `WAYLINE_*` variable into its unit (`wayline/tick.py:313-333`).
  - Acceptance commands get the harness's `bin/` put first on the `PATH` (`wayline/gates.py:234-236`).
  - The figure checks find poppler and ruff on the `PATH` (`wayline/figure_checks.py:14-17`).
  - `wayline docs env` uses the interpreter `harness.json.docs.python` names, or a venv at `research/.cache/docs/venv`: the one per-project environment the harness already has (`wayline/docs.py:15-16`).
- **Who may run what.** In a session, the `experimenter`, `analyst`, and `coder` roles may run Python, git, `ls`, `cat`, wayline verbs, and a few named tools (`pytest`, `ruff`, `nvidia-smi`), and nothing else (`roles/*/wayline.json`, `allowed_tools`; spec, Implementation Decisions, "Tool restriction per role"). An Octave, R, Julia, or pandoc call from a worker is therefore a job, unless a role's `allowed_tools` names the program.

### 4. How a job finds a program (measured)

Four transient units under the user manager, started as the job runner starts a job (`systemd-run --user --expand-environment=no`, plus `--wait --collect` so the probe could read the result), each running a small shell script from a scratch folder that prints its `PATH` and looks up `probe-inner` (a second script in the same folder), `Rscript`, and `micromamba`:

| Case | argv[0] | The caller's `PATH` | Result |
|---|---|---|---|
| A | absolute | `/usr/bin:/bin` | ran; the job's `PATH` was `/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/games:/usr/local/games:/snap/bin:/snap/bin`; `probe-inner` not found; `Rscript` was `/usr/bin/Rscript`; `micromamba` not found |
| B | bare `probe-tool` | includes the scratch folder | ran; `systemd-run` had rewritten argv[0] to the absolute path; the job's own `PATH` was still the manager's |
| C | bare `probe-tool` | lacks the folder | refused: `Failed to find executable probe-tool: No such file or directory`, exit 1 |
| D | absolute, with `-E PATH=<folder>:/usr/local/bin:/usr/bin:/bin` | `/usr/bin:/bin` | ran; `probe-inner` was found |

- The job's `PATH` is the manager's (`systemctl --user show-environment` shows the same one), as research-notes 05 (R7) found for any unit.
- A bare argv[0] is looked up on the `PATH` of whoever calls `systemd-run`, which for a job is the conductor. The tick's unit sets no `PATH` (`wayline/tick.py:100-111`), so a conductor the tick relaunches carries the manager's `PATH` (`wayline/tick.py:327-330`), while one started with `wayline run --detach` from a shell carries the owner's. The same job file can therefore start in one and be refused in the other.
- Inside a job, a bare `Rscript` or `python3` silently finds the system's, not a prefix's.

### 5. micromamba

- **Download.** The documented route, `curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest | tar -xvj bin/micromamba`, run as a download and then an extract: a 7.0 MB archive, an 18 MB binary, 5.0 s, version 2.9.0.
- **Dependencies.** The documentation calls it "a fully statically-linked, self-contained, executable"; `ldd` shows it links only glibc's own libraries (`libc`, `libm`, `libpthread`, `libdl`, `librt`, `libresolv`), which every glibc system has.
- **Keeping it in its folder.** `MAMBA_ROOT_PREFIX` sets where "all environments and cache will be created by default". Even so, `micromamba info` listed `/home/bernaljp/.mamba/pkgs` as a second package cache, and micromamba created `~/.mamba/pkgs/urls.txt` (born at the first `micromamba info`). With `CONDA_PKGS_DIRS` set to the scratch cache, `info` listed one cache and `~/.mamba` was not created again.
- **Installs.** Every one went through `micromamba create -y -p <prefix> -c conda-forge <package>`, after a `--dry-run` for the package list and the download size.
- **Locks.** `micromamba env export -p <prefix> --explicit` writes one package URL with its MD5 per line: 1 line for the pandoc prefix, 183 for the Octave prefix.
- **Activation for one command.** `micromamba run -p <prefix> <program>` took 0.08 s to start Octave, against 0.05 s for a direct start.

### 6. GNU Octave

**Install.**

- `micromamba create --dry-run -p <scratch>/envs/octave -c conda-forge octave`: 181 packages, "Total download: 460MB"; `octave 10.3.0` (build `pl5321hd0fbda6_4`, 23 MB). The largest are ghostscript (62 MB), qt-main (53 MB), two LLVMs (44 MB each), and Python 3.14 (26 MB).
- The create itself: 15.6 s. The prefix is 1.8 GB. The package cache is 2.3 GB: 440 MB of downloaded archives and the extracted packages, most of whose files are hardlinked into the prefix; the prefix and the cache together are 2.6 GB.
- conda-forge's newest Octave is 10.3.0 (api.anaconda.org, `latest_version`); "GNU Octave 11.3.0 is the latest stable release" (octave.org).

**Running it without activation.**

- By absolute path, with an empty environment or with the caller's, Octave loads none of its own functions: `error: 'version' undefined near line 2, column 24`.
- The package's activation script exports `OCTAVE_HOME=$CONDA_PREFIX` (conda-forge `octave-feedstock`, `recipe/scripts/activate.sh`). With only `OCTAVE_HOME=<prefix>` added to the empty environment the probe ran, in 0.15 s, as it did under `micromamba run -p`.
- `octave-cli` offers only the gnuplot graphics toolkit (`available_graphics_toolkits()`), warns that "using the gnuplot graphics toolkit is discouraged", and with no display draws each figure as text into the job's log.
- Octave writes `~/.local/share/octave/history` on exit unless given `--no-history`. The first probes kept the real `HOME` and created that folder in the home (removed; see "Cleanup").
- A bare Octave 10.3.0 answers `exist` 0 for `lsqcurvefit`, `lsqnonlin`, `optimoptions`, `fmincon`, and `nlinfit`, and 2 for `optimset`, `fminunc`, and `lsqnonneg`; `fminsearch` ran.

**The `optim` package.**

- **Not on conda-forge.** `micromamba search -c conda-forge octave-optim` finds nothing, api.anaconda.org answers `"octave-optim" could not be found` (404), and there is no `conda-forge/octave-optim-feedstock` (404). conda-forge carries twelve Octave packages: control, datatypes, fuzzy-logic-toolkit, image, instrument-control, netcdf, onsas, signal, sockets, splines, statistics, and stk.
- **On Octave Forge.** optim 1.6.3 (2026-03-08) needs Octave 4.0.0 or later, statistics 1.4.0 or later, and struct 1.0.12 or later (gnu-octave.github.io/packages/optim). `pkg install -forge` downloads from packages.octave.org (`scripts/pkg/private/get_forge_pkg.m:46` and `:61` in Octave 10.3.0) and compiles the package's C++.
- **The compiler.** A first `pkg install -forge struct` failed with `configure: error: C++ compiler cannot create executables`, because `mkoctfile -p CXX` names a compiler that exists only on conda-forge's build machine: `/home/conda/feedstock_root/build_artifacts/bld/rattler-build_octave_1774013224/build_env/bin/x86_64-conda-linux-gnu-c++`. With `CC=/usr/bin/gcc CXX=/usr/bin/g++ F77=/usr/bin/gfortran` in the environment, struct 1.0.18 built and installed in 16.1 s. conda-forge's own compilers (`c-compiler`, `cxx-compiler`, `fortran-compiler`, GCC 15.3) would add 16 packages and 153 MB (dry run; not tried).
- **statistics.** `pkg install -forge statistics` refused: `statistics needs octave >= 11.1.0` and `statistics needs datatypes >= 1.4.2`, since Forge serves only the newest release. conda-forge's `octave-statistics` 1.8.2, with `octave-datatypes` 1.2.1, fits Octave 10.3.0: 2 MB and 2.8 s.
- **optim itself.** `pkg install -forge optim`: optim 1.6.3 in 34.5 s. After `pkg load optim`, `lsqcurvefit` and `lsqnonlin` exist and `optimoptions` still does not. Its help text says optim's `lsqcurvefit` "is a compatibility wrapper" around `nonlin_curvefit`, with the algorithm "lm_svd_feasible", where MATLAB's default is trust-region-reflective.
- **Where the packages go.** By default into the user's `~/.local/share/octave/api-v60/packages`, listed in `~/.config/octave/api-v60/octave_packages` (both inside the scratch `HOME` here). `pkg install -global -forge struct` put struct into `<prefix>/share/octave/packages` in 16.7 s without root, because the prefix belongs to the user; conda-forge's Octave packages land there too.

**One PINF fit script under Octave.**

- **What was run.** Copies of `code/PINF_Code/Scripts_Models/vanderpol_V4.m` and the six helpers it calls (`vanderpol_normalized`, `xNormalization`, `add_Noise_Max`, `noise_5_Boxplots`, `plotState_Beta_time_Pred`, `plotNoisyStateFig_5`), in scratch with the repository's folder layout, run as a job would run them: `octave-cli --no-init-file`, an empty environment plus `OCTAVE_HOME`, `HOME` and `TMPDIR` in scratch, and no display.
- **How.** Octave was moved past each failure with a scratch-only change, to find the next one:

| Step | What the copy had | First failure (error lines only) |
|---|---|---|
| 0 | as copied, no Forge packages | `warning: addpath: ../Functions/utils: No such file or directory` (and the same for `../Functions/violin/` and `../Functions/plottingfunctions/`); then `error: 'xline' undefined near line 59, column 1` and `The 'xline' function is not yet implemented in Octave.` |
| 1 | `pkg load optim` and `statistics`; lowercase links for the three folders | the same `xline` error |
| 2 | do-nothing stand-ins for `xline`, `yline`, `sgtitle`, and `exportgraphics` | `error: scalar cannot be indexed with .` (script line 62, a property set on a legend handle with dot syntax) |
| 3 | dot syntax on handles rewritten as `set` calls | after 302 s: `error: 'optimoptions' undefined near line 91, column 8` and `The 'optimoptions' function belongs to the optim package from Octave Forge but has not yet been implemented.` |
| 4 | `optimoptions` mapped onto `optimset` | both fits ran (exit flag 3, "Change in the residual was less than the specified tolerance"); then `error: vertical dimensions mismatch (1x4 vs 4x1)` (script line 114, where the fitted weights meet a row vector) |
| 5 | the fitted weights transposed on that line | ran through the reconstruction and saved its `.mat`; `warning: function arguments validation blocks are not supported; INCORRECT RESULTS ARE POSSIBLE` (`noise_5_Boxplots` line 9); then `error: 'resolution' undefined near line 120, column 16`, an argument whose default only the ignored block would have set |

- **Other warnings.** `legend: 'best' not yet implemented for location specifier, using 'northeast' instead`, `latex markup not supported for text objects`, and 13 times `legend: ignoring extra labels`.
- **The folder case.** The repository's folders are `Utils`, `plottingFunctions`, and `Violinplot-Matlab-master`, and the script adds `utils`, `plottingfunctions`, and `violin`. That works on a case-insensitive file system (the repository carries `.DS_Store` files) and not on this machine's, whichever program runs the script.
- **A static check** of the same seven files (45 names called like functions, minus variables and the files' own functions) against `exist`: a bare Octave 10.3.0 lacks `boxplot`, `exportgraphics`, `lsqcurvefit`, `optimoptions`, `sgtitle`, `xline`, and `yline`. With optim and statistics loaded it still lacks `optimoptions`, `xline`, `yline`, `sgtitle`, and `exportgraphics`. The dot syntax on handles is 70 property settings (2 in the script, 32 and 36 in the two plotting helpers), plus one property read.
- **Time.** The first `ode45`, with the script's own tight tolerances and dense output, took 290 s, and 291 s in a second run; the reconstruction's `ode45` about 120 s; each `lsqcurvefit` under 5 s. There is no MATLAB time to compare with.
- **The fitted weights.** The fitted model is linear in its weights, so its least-squares minimum is unique. A second scratch variant saved the first fit's data and stopped; on that data, optim's result agreed with a direct least-squares solve (`A \ y`) to three significant digits or better in every weight and to six in the sum of squared residuals, and tightening `TolFun` and `TolX` to 1e-15 changed nothing (exit flag 3 after 8 iterations). In both fits the weights came out far from the coefficients the script generates its data with. Since the solver reaches the minimum, that distance lies in the data the script builds from its `ode45` solution. Octave's and MATLAB's `ode45` are different implementations, and whether MATLAB builds the same data was not checked.

**Octave 11 in a container.** The Octave wiki lists `singularity pull docker://gnuoctave/octave:11.1.0` among the routes that need no root. SingularityCE 3.8.1 pulled and ran `docker://alpine:3.20` here without root (9.5 s to pull, 0.13 s to run, the cache in scratch), though it still created an empty `~/.singularity` (removed). The official `gnuoctave/octave:11.3.0` image is 1,543 MB compressed for amd64 (Docker Hub API); it was not pulled.

### 7. Pandoc

- **The release.** 3.11, published 2026-08-29 (GitHub API, `repos/jgm/pandoc/releases/latest`), with the Linux assets `pandoc-3.11-linux-amd64.tar.gz` and `pandoc-3.11-linux-arm64.tar.gz`.
- **The release tarball.** 34,940,580 bytes; 2.0 s to download and 0.7 s to extract; 157 MB unpacked: `bin/pandoc` (163,653,648 bytes; `file` says "statically linked" and `ldd` "not a dynamic executable") and three man pages. pandoc.org: "The executable is statically linked and has no dynamic dependencies or dependencies on external data files"; install with `tar xvzf $TGZ --strip-components 1 -C $DEST`, where `$DEST` can be `$HOME/.local`. `pandoc --version` ran in an empty environment.
- **conda-forge.** `pandoc 3.11 ha770c72_0`: 23 MB to download, 1.6 s, a 157 MB prefix holding `pandoc`, `pandoc-lua`, and `pandoc-server`. Its binary carries the tarball binary's build ID, `1e051ed3412e1ec08f57ca4dbc2c6a2861c92c76`: it is the same program. It ran in an empty environment.
- **`pypandoc_binary`.** 1.17 (2026-03-14); its manylinux x86_64 wheel is 34,460,960 bytes (PyPI JSON API). With `python3 -m venv` unavailable, it went through uv with the cache in scratch: `uv venv` 0.07 s, `uv pip install pypandoc_binary` 2.6 s, a 155 MB venv. It bundles pandoc 3.9 at `site-packages/pypandoc/files/pandoc` (162 MB, static), and `pypandoc.get_pandoc_version()` answers 3.9.
- **Where each would live.**
  - The tarball: `~/.wayline/tools/pandoc-3.11/bin/pandoc`.
  - conda-forge: `~/.wayline/tools/envs/pandoc/bin/pandoc`.
  - The wheel: inside the tools venv, at `~/.wayline/tools/venv/lib/python3.12/site-packages/pypandoc/files/pandoc`, tied to the 7 GB docling venv and to whichever pandoc the wheel bundles.
- **PDF output.** Pandoc "creates PDFs using LaTeX" by default (pandoc.org), and `xelatex`, `pdflatex`, and `latexmk` are installed.

### 8. R

- **The system's R** is 4.4.3 at `/usr/bin/R`.
- **conda-forge `r-base` 4.6.1.** Dry run: 86 packages, 259 MB. The create: 8.2 s. The prefix is 1.4 GB, most of it the GCC 16.2 toolchain that conda-forge's R depends on so that `install.packages()` can compile: `gcc_impl_linux-64` (86 MB), `sysroot_linux-64` (42 MB), `libstdcxx-devel_linux-64` (23 MB), `gfortran_impl_linux-64` (21 MB), and `gxx_impl_linux-64` (17 MB) to download; on disk `x86_64-conda-linux-gnu/` is 484 MB and `libexec/` 281 MB.
- **No activation needed.** `<prefix>/bin/Rscript` in an empty environment ran a small `nls` fit in 0.21 s; `R.home()` was the prefix's `lib/R`, and `.libPaths()` held only the prefix's library.
- **In a job,** a bare `Rscript` is the system's 4.4.3 (section 4).
- **A project's packages** would be conda-forge `r-*` packages in the prefix, or `install.packages()` into a project library named by `R_LIBS_USER`, compiled by the prefix's GCC. Not measured.

### 9. Julia

- **The official tarball.** The official versions index (`julialang-s3.julialang.org/bin/versions.json`) names 1.13.1 as the newest stable release; `julia-1.13.1-linux-x86_64.tar.gz` is 302,180,186 bytes. 6.4 s to download, 5.0 s to extract, 1.1 GB. `bin/julia --startup-file=no` in an empty environment, with `JULIA_DEPOT_PATH` in scratch, ran in 0.36 s, and the depot stayed at 4 KB.
- **What julialang.org says.** The downloads page recommends juliaup (`curl -fsSL https://install.julialang.org | sh`). The platform page's manual route is to run `<Julia directory>/bin/julia`, and uninstalling is deleting that directory (and `~/.julia` for packages).
- **juliaup, not installed.** v1.22.7 (2026-09-11); its Linux asset `juliaup-1.22.7-x86_64-unknown-linux-musl-portable.tar.gz` is 16,185,564 bytes. Its installer takes `--path`, `--add-to-path` (default yes, which edits `.bashrc`, `.profile`, or `.zshrc`), `--startup-selfupdate` (default 1440 minutes), and `--background-selfupdate`, and `JULIAUP_DEPOT_PATH` moves its store from `~/.julia` (the juliaup README). Channels and self-updates buy a harness nothing, and a job would still need juliaup's launcher by absolute path.
- **conda-forge** has `julia` 1.13.0 (dry run, 227 MB).
- **Packages** go into `JULIA_DEPOT_PATH` (by default `~/.julia`); a project environment (`--project=<dir>`, with `Project.toml` and `Manifest.toml`) pins them per project. Not measured.

### 10. MATLAB

- **The license.** PINF's fits call `lsqcurvefit` and `optimoptions`, which are Optimization Toolbox (MathWorks' `lsqcurvefit` page), and the noise helper calls `boxplot`, which is Statistics and Machine Learning Toolbox (MathWorks' `boxplot` page, which points to base MATLAB's `boxchart` as the alternative). MathWorks' license kinds:
  - an Individual License "is assigned to a named user";
  - a Designated Computer License "restricts use to a host ID that identifies a particular computer, but not a particular user";
  - Concurrent licensing needs license manager software on a server;
  - a university's Campus-Wide License offers these kinds.
- **Installing without root.** `mpm`, the MATLAB Package Manager, from `https://www.mathworks.com/mpm/glnxa64/mpm`, then `mpm install --release=R2026b --destination=<folder> --products=<names>`, with underscores in product names (`Optimization_Toolbox`, `Statistics_and_Machine_Learning_Toolbox`). The page's own Linux example installs into `/home/<USER>/matlab`.
- **Activation.** mpm's page says nothing about it. MathWorks' activation page: run `bin/glnxa64/MathWorksProductAuthorizer.sh` (or start MATLAB), sign in, and select the license; an offline machine uses a license file instead.
- **Size.** R2026b supports Ubuntu 24.04 LTS and needs "4.5 GB for just MATLAB", "5-7 GB for a typical installation", "26 GB for an all products installation", and 8 GB of RAM at least.
- **A job.** `matlab -batch "statement"` starts without the desktop, logs to stdout and stderr, raises an error instead of showing a dialog, and "Exits automatically with exit code 0 if statement executes successfully. Otherwise, MATLAB terminates with a non-zero exit code" (MathWorks' `matlab (Linux)` page).
- **Unattended licensing, not verified.** Whether a license activated at the desktop also serves a `-batch` run started by the user manager was not tested. MathWorks' route for non-interactive use is the `matlab-batch` executable with a batch licensing token, "still in the pilot phase", with an eligibility form (`mathworks-ref-arch/matlab-dockerfile`, `alternates/non-interactive/MATLAB-BATCH.md`).
- **The MATLAB Runtime.** It is "a standalone set of shared libraries that enables the execution of compiled MATLAB applications, Simulink applications, or libraries on computers without an installed version of MATLAB" and "freely available" (the product page). Applications "that use artifacts built with MATLAB Compiler or MATLAB Compiler SDK require a matching version of MATLAB Runtime", and the Runtime's files are "Encrypted and immutable", with "Fixed paths that cannot be changed" (MathWorks' "About the MATLAB Runtime"). Neither page says in one sentence that it cannot run an uncompiled `.m` file; that follows from both. To use the Runtime, someone with MATLAB Compiler would first compile PINF's scripts.

### 11. Where each would live, and how a job would call it

| Tool | Where (recommended) | The job's `command` | The job's `env` | What is per project |
|---|---|---|---|---|
| Octave | `~/.wayline/tools/envs/octave` | `<prefix>/bin/octave-cli --no-history` | `OCTAVE_HOME=<prefix>` | Forge packages, installed `-global` into the shared prefix; a project prefix only when versions must differ |
| R | `~/.wayline/tools/envs/r` | `<prefix>/bin/Rscript` | none; `R_LIBS_USER` for a project library | the project's library |
| Julia | `~/.wayline/tools/julia-1.13.1` | `<dir>/bin/julia --project=<project env>` | `JULIA_DEPOT_PATH=<depot>` | the project environment |
| pandoc | `~/.wayline/tools/envs/pandoc` | `<prefix>/bin/pandoc` | none | nothing |
| MATLAB | where the owner installed it, for example `~/matlab/R2026b` | `<matlabroot>/bin/matlab -batch "..."` | `MLM_LICENSE_FILE` for a network license | nothing |

- **Per project instead.** Any of these prefixes can live in a project, for example beside `research/.cache/docs/venv`; the costs are the size (1 to 2 GB each, though micromamba hardlinks from one package cache on the same file system) and one install per project.
- **Removal.** Each is removed by deleting its folder and its `tools.json` entry.
- **The network.** Every install needs it: `conda.anaconda.org`, `micro.mamba.pm`, `packages.octave.org`, `github.com`, and `julialang-s3.julialang.org`.

### 12. Cleanup

- **The scratch directory** (6.8 GB) was deleted whole with `rm -rf`: every prefix (Octave, R, pandoc), the micromamba binary and its package cache, the pandoc and Julia tarballs and their unpacked trees, the uv venv and its cache, the Singularity image and cache, and the copied PINF files with everything the Octave runs wrote beside them.
- **Three folders the first probes created in the home** were removed, each born during this session (by `stat`) and absent before it:
  - `~/.mamba` (micromamba's second package cache, holding an empty `pkgs/urls.txt`);
  - `~/.local/share/octave` (Octave's `history`, from the probes that kept the real `HOME`);
  - `~/.singularity` (empty).
- **The four probe units** were started with `--collect`; `systemctl --user list-units --all 'research-179*'` lists none.
- **PINF_Project was only read.** `find ~/Documents/PINF_Project -newermt "2026-09-28 16:45"` lists nothing.
- **Nothing else in the home changed.** `~/.julia`, `~/.juliaup`, `~/.config/octave`, `~/.octave_hist`, and `~/.cache/rattler` do not exist, and `~/.cache/uv` and `~/.cache/pip` were last written before this session.

## Sources

**Primary sources on the web** (read on 2026-09-28):

- micromamba installation: <https://mamba.readthedocs.io/en/latest/installation/micromamba-installation.html>; releases: <https://github.com/mamba-org/micromamba-releases/releases>
- conda-forge Octave recipe, activation script: <https://github.com/conda-forge/octave-feedstock/blob/main/recipe/scripts/activate.sh>
- conda-forge package metadata: <https://api.anaconda.org/package/conda-forge/octave>, <https://api.anaconda.org/package/conda-forge/octave-optim> (404), <https://api.anaconda.org/package/conda-forge/octave-statistics>
- GNU Octave download page: <https://octave.org/download>
- Octave wiki, "Octave for GNU/Linux": <https://wiki.octave.org/Octave_for_GNU/Linux>
- Octave packages index, optim: <https://gnu-octave.github.io/packages/optim/>
- Octave's missing-functions page: <https://www.octave.org/missing.html>
- Official Octave images: <https://hub.docker.com/r/gnuoctave/octave> (tags API: <https://hub.docker.com/v2/repositories/gnuoctave/octave/tags>)
- pandoc installation: <https://pandoc.org/installing.html>; releases: <https://github.com/jgm/pandoc/releases/tag/3.11>
- pypandoc_binary: <https://pypi.org/project/pypandoc-binary/> (JSON API: <https://pypi.org/pypi/pypandoc_binary/json>)
- Julia downloads: <https://julialang.org/downloads/>; manual installation: <https://julialang.org/downloads/platform/>; versions index: <https://julialang-s3.julialang.org/bin/versions.json>
- juliaup: <https://github.com/JuliaLang/juliaup> (README; release v1.22.7)
- MATLAB Runtime: <https://www.mathworks.com/products/compiler/matlab-runtime.html>, <https://www.mathworks.com/help/compiler/about-the-matlab-runtime.html>
- MATLAB Package Manager: <https://www.mathworks.com/help/install/ug/get-mpm-os-command-line.html>, <https://www.mathworks.com/help/install/ug/mpminstall.html>
- MATLAB activation: <https://www.mathworks.com/help/install/ug/activate-matlab-installation-manually.html>
- MATLAB license kinds: <https://www.mathworks.com/help/install/administer-individual-and-designated-computer-licenses.html>, <https://www.mathworks.com/help/install/license/plan-your-campus-wide-license-deployment.html>
- MATLAB on Linux, R2026b requirements: <https://www.mathworks.com/support/requirements/matlab-linux.html>
- `matlab -batch`: <https://www.mathworks.com/help/matlab/ref/matlablinux.html>
- `lsqcurvefit` (Optimization Toolbox): <https://www.mathworks.com/help/optim/ug/lsqcurvefit.html>; `boxplot` (Statistics and Machine Learning Toolbox): <https://www.mathworks.com/help/stats/boxplot.html>
- matlab-batch and batch licensing tokens: <https://github.com/mathworks-ref-arch/matlab-dockerfile/blob/main/alternates/non-interactive/MATLAB-BATCH.md>
- MATLAB Answers on running `.m` files without MATLAB, a secondary source: <https://www.mathworks.com/matlabcentral/answers/43114-execute-uncompiled-m-scripts-from-within-deployed-matlab-code>

**In this repository:**

- `wayline/tools.py:106-110`, `113-137`, `165-189`, `212-269`, `272-280`: the tools venv, `tools.json`, and `Tools`
- `wayline/pdf_inventory.py:184`, `378`, `385`, `1248`: converters started by the venv's absolute interpreter
- `schemas/job.json:14-16`; `wayline/resources.py:671-701`, `1676-1711`: the job file and its launch
- `wayline/tick.py:100-111`, `313-333`: the tick's unit and the detached conductor's `PATH`
- `wayline/worker.py:1605-1622`: `claude` looked for in `~/.local/bin`
- `wayline/gates.py:234-236`; `wayline/figure_checks.py:14-17`; `wayline/docs.py:15-16`: other `PATH` and environment precedents
- `roles/experimenter/wayline.json`, `roles/analyst/wayline.json`, `roles/coder/wayline.json`: `allowed_tools`
- `research-notes/05-detached-jobs-tick-notifications.md`, R7: the environment inside a unit

**Measured here:** every number above not attributed to a page, from the commands named in each section, run on 2026-09-28 in the scratch directory and since removed.
