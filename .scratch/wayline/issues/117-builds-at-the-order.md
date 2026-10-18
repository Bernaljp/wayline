# 117 - Builds at the order

**What to build:** Every build of the paper is tested before the owner reads it. Each build runs three gates on the paper, in order:

1. the kill argument, told the general report's last verdict;
2. the independent read (`paper_read`);
3. sampled verdicts on claims never sampled before.

A failure sends the standing points to the next build. That build is a fresh writer session given the previous parts, with no ticket. There are at most three builds; after them the paper is marked not passed and the owner chooses three more builds, keeping it as it is, or the points as objectives. Under `autonomous` the paper stops under "Waiting on you". `PAPER.md` records each gate with the points still standing.

What the paper says about inherited work is explicit:

- Unverifiable claims are left out and listed unless the owner keeps one in the batch; a kept one is stated as not verified, with its reason.
- A supplementary table renders each inherited result's verdict, route, narrowed wording, and reasons, and the writer adds one Methods paragraph naming the routes.
- Concerns for the order go to the figure finish, the writer, and the compilation's checks.
- When the project has critiques, one response per critique, `research/paper/response/<critique>.md`, lays out each point verbatim with its answer. A response is never sent.

Not part of this ticket:

- the order, the batch, and the first composition, which are 115's;
- the compilation's own checks and the fitting session, which are 118's;
- the run-end gates on the general report, which are 103's.

**Blocked by:** 96 - Critiques and concerns; 97 - Verifying inherited results; 115 - The paper order and the paper's parts. It blocks 120.

**Status:** ready-for-agent

**GitHub:** PENDING

**Milestone:** M8 A paper that grows with the work (v1.1.0). **Spec:** Implementation Decision 17 (The paper order and what it compiles: per build, unverifiable claims, the inherited verdicts table, responses; Verifying what a project inherited; Documents, critiques, and concerns), 11 (verification, the kill argument), 13 (the paper), 14 (the policy table: the order's three builds); M8 criterion 17; user stories 140, 142, 164.

- [ ] Each build runs the kill argument (its prompt carries the general report's last verdict), then `paper_read`, then sampled verdicts on claims never sampled, and `PAPER.md` lists each gate with its standing points.
- [ ] A failed build launches a fresh writer session given the previous parts and the standing points, with no ticket; after three builds the paper is marked not passed and the owner is offered three more, keep it, or the points as objectives; under `autonomous` it waits under "Waiting on you".
- [ ] The order's three builds are a policy key, and decision 14's policy table gains its row in the same commit.
- [ ] An unverifiable claim is absent from the parts and listed in `PAPER.md` unless the batch kept it, in which case its sentence says it is not verified and why.
- [ ] The supplement carries a table of every inherited result's verdict, route, narrowed wording, and reasons, rendered by code, and Methods carries one writer paragraph naming the routes used.
- [ ] Concerns marked for the order reach the figure finish's, the writer's, and the compilation's inputs; a project with critiques gets one `response/<critique>.md` per critique with each point verbatim and its answer, and nothing sends it.
- [ ] Tests: the fake launcher scripts a build passing, one failing then passing, and three failing; journal replay covers the not-passed state under `autonomous`; the inherited table and the responses are asserted on the files a fixture ledger renders.
- [ ] `python -m unittest` passes.
