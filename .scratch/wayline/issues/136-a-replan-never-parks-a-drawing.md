# 136 - A replan never parks a drawing

**What to build:** The drawing tickets code opens at a rest point stay code's: no re-cut by the planner parks, rewrites, or replaces them.

On the toy's live run (ticket 122, `docs/verification/m8.md`), the run end opened 18 drawing tickets (134 to 151, one per changed result R1 to R18) at 03:59Z. While they ran, verdict-only waves counted as two settling waves without progress (ticket 129), and at 05:34Z the stall rule had the planner re-cut "the open tickets", drawings included. It parked nine of them (139, 142, 143, 146 to 151: R6, R9, R10, and R13 to R18, among them R14 to R17, the experiments' main results) and wrote four analysis tickets (153 to 156) that re-file findings, and the decider was asked to confirm that graph. The paper order waits on "every changed result drawn", so a parked drawing holds the paper.

- Drawing tickets are outside the planner's re-cut, split, and revise: the plan schema refuses a re-cut that parks or names one, and the open tickets the stall rule hands the planner exclude them.
- A drawing that fails or is left out follows decision 17's rules for drawings (left out and listed), never a planner's re-cut.
- Whatever the planner proposes about a drawing's result (a finding to re-file) is a new ticket beside the drawing, never instead of it.

**Blocked by:** None - can start immediately. It touches the planner's re-cut and the stall step; 129 touches the stall rule too, so the two should not run together.

**Status:** ready-for-agent

**GitHub:** [#343](https://github.com/Bernaljp/wayline/issues/343) (mirror; the local file is the source)

**Milestone:** after M8 (v1.1.x). **Spec:** Implementation Decision 17 (drawings: one drawing ticket per changed result at each rest point; the paper order's readiness), 5 (stalls), 10 (the planner's re-cut); ticket 100; ticket 122's live record.

- [ ] A replayed journal with open drawing tickets and a stall re-cuts the graph without parking any drawing; covered with the fake launcher.
- [ ] The plan schema check refuses a cut that parks a drawing ticket.
- [ ] `python -m unittest` passes.
