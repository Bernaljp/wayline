# Protocol

You write only under the figure's directory, `figures/<figure_id>/`; the touch-set guard refuses
anything else. You commit nothing and run no `wayline` command: the harness reads what you return,
hashes the files, and records them.

## Drafts

1. Read the claim, the target, and the house style named in the prompt. Open every data file
   listed and look at its real columns before you draw anything.
2. For each candidate, in the order given: read its pitfalls first, then write its draft script at
   the path the prompt gives and run it with the project's Python. The draft reads the real data,
   uses the house palette, and saves one PNG at the target width at its true aspect ratio. Quick
   drafts: no polish, no caption.
3. A draft that fails to run is reported `rendered: false` with the last lines of its error. Do not
   swap in another chart type and do not fake the data to make it render.
4. `pitfalls_consulted` lists, verbatim, the pitfalls listed for that candidate that you read
   before drawing it; list every one you read and none that was not listed for it.
5. A library trap you hit that no listed pitfall named goes into `traps_hit`, with the fix;
   `promote_to_index: true` when the next figure of that chart type should be told about it. Its
   `chart_type` is the candidate's chart type exactly as this prompt names it, because that is how
   the harness finds the index entry the trap belongs to.
6. Return the drafts once, through the structured output, before you stop.

## Finish

1. Start from what the prompt names: the chosen draft, or on a guided revision the figure as it
   stands and the change requests.
2. Write the final generator at the path the prompt gives. It reads only the data files listed,
   writes the figure files at the paths given, and embeds its fonts. Apply the house style in full,
   and the register rules when the register is conceptual.
3. On a guided revision, take each change request in turn. Carry out the ones that keep the figure
   honest and list their ids in `applied`. A request that would make the figure assert something
   the data does not is refused: record it in `refusals` with the reason, and draw the nearest
   honest alternative as a new draft under the path the prompt gives for alternatives. When no
   honest alternative exists, give null paths. When every request is refused, leave the final
   figure as it was and return `drew_final: false`.
4. Write the caption and the notes at the paths given. The caption carries a `(a)`, `(b)` entry for
   every panel and the disclosures the honesty rules ask for, and names no other figure; the notes record the generator, the
   register, the load-bearing choices with their measurements, the schematic elements, and the
   traps hit.
5. Run the generator once more from the project root and look at the PNG before you stop.
6. Return the result once, through the structured output: the data files the figure draws from
   (with their panels), the schematic elements, the selection statistics, the findings for the
   text, the equations with the code that computes each, the traps hit, and on a guided revision
   what you applied and what you refused.
