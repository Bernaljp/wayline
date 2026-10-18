# 102 - The plotting library switch

**What to build:** The owner can switch plotting to Altair, or to R with ggplot2, at any time and back to matplotlib and seaborn. `harness.json.plotting` holds the choice, written by `wayline switch --plotting <library>` and journaled as a `control` event. It applies at each result's next drawing. The drawing script, the clean room, and the checks then run in that library, and the checks read the SVG it writes.

The owner's word is the yes to install what the library needs, through the project's tools and the `software` routes that "82 - Project tools and the software decision" built: R and its packages from conda-forge, Altair into the tools venv through uv. The decider never changes the setting under any autonomy. A drawing already accepted keeps the library it was drawn in, and so does a figure finished at the order.

Not part of this ticket:

- the dashboard's select in Run's controls, which is "121 - Dashboard: cards and new actions".

**Blocked by:** 82 - Project tools and the software decision; 100 - Drawings on the plotter. It blocks 121.

**Status:** ready-for-agent

**GitHub:** [#249](https://github.com/Bernaljp/wayline/issues/249) (mirror; the local file is the source)

**Milestone:** M8 A paper that grows with the work (v1.1.0). **Spec:** Implementation Decision 17 (Drawings and plots: `harness.json.plotting`; Tools, packages, and environments: a project's tools after a yes); Implementation Decision 1 (`harness.json`, the verb table: `switch --plotting`); Implementation Decision 2 (the event table: the `control` command); M8 criterion 6; user story 130.

- [ ] `harness.json.plotting` (matplotlib with seaborn by default, Altair, or R with ggplot2) is in the schema, and a project without the key uses the default.
- [ ] `wayline switch --plotting <library>` writes `harness.json` first and then journals `control`, accepted with a conductor running or not. A `project` function is what the dashboard will call.
- [ ] Switching to a library whose tools are not recorded installs them through `wayline tools install` as the owner's yes, synchronously in a conversation. A failed install leaves the setting unchanged and says why.
- [ ] The next drawing of each result runs in the chosen library, and the clean-room rerun and the checks read its SVG. Accepted drawings keep their library.
- [ ] The decider has no path to change `plotting` under any autonomy.
- [ ] Tests as plain functions over a temporary project: the schema with each value and without the key; `switch --plotting` writing and journaling in that order; an install through the tool runner's recordings; a drawing prompt naming the library; the decider refused.
- [ ] Decision 1's verb table gains `switch --plotting` and `harness.json`'s `plotting` key, and decision 2's `control` enumeration the command, in the same commit.
- [ ] `python -m unittest` passes.
