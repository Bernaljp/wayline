# Protocol

1. Read every numbered sentence below. Each is one sentence of a report with its provenance tags
   taken off; the number in brackets is how you refer to it.
2. Give each sentence exactly one class:
   - `claim`: it asserts something about the world, the data, a model, or a result, and could be
     wrong. A number reported from a run is a claim. A negative result ("X did not improve Y") is
     a claim. A comparison, a trend, a cause, or a "we found" is a claim.
   - `definition`: it says what a term, a quantity, a split, or a metric means, and asserts
     nothing a result could contradict.
   - `transition`: it moves the reader along ("The next section turns to the baselines.") and
     asserts nothing.
   - `method_description`: it says what was done or how it was done ("Each model was trained on
     three seeds.") without asserting what came of it.
3. When a sentence could be two of these and one of them is `claim`, it is a `claim`.
4. Return one entry per number, every number exactly once, through the structured output.
