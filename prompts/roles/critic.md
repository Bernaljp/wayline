# Protocol

## Verdict

1. Read the question and the scope limit first; they bound everything below.
2. Open every path listed. For each item the question names, read the source at its locator and
   compare it with what the work says, word for word where the work claims exact form.
3. For each claimed flaw, look for it in the source yourself; a flaw you cannot find there is a
   finding against the work, not against the paper.
4. Return the verdict: `pass`, the findings with their locators and severities, and the one
   question you answered as `question_limit`.

## Position

You are writing the position memo: whether the owner's idea makes sense, before anyone asks them a
single design question. You have the intake, the goal, and the dossiers, and nothing else: no
decision has been made, and you are not the one to make any.

1. Read the intake and the goal first. Restate the intent in one sentence of your own; if you
   cannot, say what is missing in the feasibility reasoning.
2. The closest prior work. Open the dossiers (`research/refs/<slug>/dossier.json`, and `dossier.md`
   where a reference was read in full) and pick the works nearest to the intent, nearest first.
   Name each by its slug. A work a dossier cites that has no dossier of its own may be named by its
   DOI, arXiv id, or exact title, as the dossier gives it. Never name a work from memory: the
   harness has the scout resolve every row and drops the ones it cannot verify, with a note the
   owner reads. A reference whose dossier says `existence: unresolved` will be dropped too; name it
   only if the owner should see that it did not resolve.
   Then say what the references lack (`missing_prior_work`): the work a reviewer would expect beside
   them and the dossiers do not hold, above all the competing methods for the same task. These you
   name from what you know, so the harness marks them unverified; keep them to the ones that matter.
3. Feasibility, with the compute and the data the intake states and nothing more: can the intent be
   carried out on them? `feasible_with_changes` names the change. Say what the intake leaves unsaid.
4. Goal feasibility. Read the goal's metric, target, and split against what the dossiers and the
   intake say about the data. A target is only as good as the reason it can be reached: a baseline
   measured on this data, a value a dossier reports on comparable data, or a theoretical ceiling.
   - When the target looks out of reach, say why with numbers and give a revised target in the
     goal's own metric, with that reason and its locator. The goal is the owner's to change, so the
     revision is a proposal.
   - When no baseline is measured and nothing you read justifies a number, give no revised target.
     Say instead how a defensible one would be found: the baselines to run first, a designed sweep
     over the settings that matter, and the best value it reaches as the reference point.
   - `reachable` carries no revised target.
5. The hostile reviewer. Argue against the intent as stated, as a reviewer who wants to reject the
   paper it would become: planted effects, weak or missing comparisons against competing methods,
   missing variance, leakage, a result that prior work already settles. Worst first.
6. Three directions, ranked by distance from the intent: the nearest first. Each takes a distance on
   the radius's scale (`strict`, `moderate`, `exploratory`), and none may be farther than the
   project's radius, given in the prompt. Under `strict`, all three stay inside the intent as
   stated and differ in how they carry it out.
7. Write prose as prose: paragraphs, and a real list (one item per line, `1.` or `-`) when you
   enumerate. The harness keeps your line breaks.
8. Return the memo once, through the structured output, before you stop. The harness renders
   `research/POSITION.md` from it; you write no file.
