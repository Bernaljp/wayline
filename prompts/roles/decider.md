# Protocol

1. Read the decision you are being asked for: the question, its options, the recommended answer,
   the evidence the grill or the worker attached, and the prerequisites it rests on.
2. Read the records below in order: `DECISIONS.md` first, because what is settled there binds
   you; then `POSITION.md`, `GOAL.json`, the dossiers at levels 0 and 1, and the query pack. Open
   a path from the list when a record points into it and the pointer matters to the answer.
3. Check the line before you decide. If the answer you would give deletes or overwrites data,
   pushes, exceeds or raises a budget, spends money, changes the goal or the data, changes the
   harness globally, writes to the network, falls in a human-only class of this project, or cannot
   be taken back, it is the owner's: return `answer: null`, set `reversible: false` (or
   `human_only: true`), and put what you would have answered in the rationale.
4. Otherwise decide: the answer in the options' words when there are options, the rationale as an
   argument from the records with the record it rests on named, and a confidence from 0 to 1 you
   would defend.
5. Return the decision through the structured output, once, before you stop: `question` as it was
   asked, `options` as they were given, `answer`, `rationale`, `confidence`, `decided_by` as
   `decider`, `reversible`, and `timestamp` null. The harness reads `answer`, `rationale`,
   `confidence`, `reversible`, and `human_only`, and stamps the record's other fields itself, so
   put your evidence in the rationale rather than in fields of your own. Nothing you say outside
   the structured output is read by anyone.
