---
name: wayline-interval-claims
description: "Keeps a sentence about a result or a figure inside the interval its cited artifact holds: no verdict word over a difference whose interval includes zero, no number that is not, unaltered, at its tagged leaf field. Local to this project's writing tickets (feedback 009-captions-overclaim-the-caption-of)."
---

# Interval claims

A sentence that describes a result or a figure may say only what the artifact at its cited
locator holds. This is the procedure for every claim sentence you write, in a caption, a report
paragraph, or a negative result.

1. Open the artifact at the cited locator and list its exact leaf fields: the estimate, the
   interval, and any verdict field the key itself carries. A leaf holds one number (or one array
   of one kind of value); a parent object nesting several such fields is not a leaf, and is never
   the tag.
2. A difference whose interval includes zero is written as its estimate with the interval, or as
   "not distinguishable from zero." It is never written as "does not," "no effect," "matches,"
   "as much as," or "the same": those are verdicts the interval does not give when it includes
   zero.
3. A verdict word ("holds," "fails," "credited," "supported," "confirmed") appears only when the
   artifact carries a verdict field with that value at that key. A comparison between two arms
   appears only when the artifact holds that difference and its interval, not because two
   separate numbers looked close.
4. A tag names the leaf the number actually lives at, never a parent that nests more than one
   leaf. A raw value and a difference derived from it are two facts, even printed side by side in
   a finding's own sentence or nested under one parent key; a value at one arm or one signal and
   a value at another arm or signal are also two facts. Two facts never share one tag: give each
   its own leaf tag and sentence, or, if a finding hands you one tag for several facts, keep only
   the one fact that tag's leaf most narrowly names and drop or move the rest.
5. Never write a number you computed yourself: no unit conversion (a rate turned into "points," a
   fraction into a percent), no subtracting or averaging two stored values by hand, no re-rounding
   past a field's own precision. If the number wanted isn't itself sitting at a leaf, don't write
   it: report the literal value, in the file's own unit, at its own leaf, or drop the sentence.
6. A number that varies by signal or arm is one fact per signal or arm. A sentence stating a value
   at signals 1, 2, 4, and 8 needs four tags, one to each signal's own file, never the one tag of a
   sweep file that prints all four together. When a finding names only one signal's tag, write
   only that signal's number under it and give the rest their own sentences and tags, or leave
   them out.
7. A claim label, an experiment name, or a cross-reference the artifact itself does not carry
   (e.g. "A4," "confirms C3") goes in an untagged sentence citing `research/SPEC.md`, where the
   label is defined.
8. Before returning, reread the sentence fact by fact against the key(s) cited: is each number
   sitting, unaltered, at the leaf its tag names? Cut what a key doesn't hold, or split off what
   needs a leaf of its own. If nothing needs cutting, the sentence stays as written.

## Worked examples from this project

**The caption that overclaimed.** `figures/e1-signal4/caption.md` said adding x3·x4 "lifts
held-out AUROC ... as much as adding all pairs; the wrong pair x1·x2 does not." The cited keys,
`signal-4.json#allpairs_cost.mean` (-0.0002, ci95 [-0.0008, 0.0003]) and
`signal-4.json#wrong_pair_vs_raw.mean` (ci95 [-0.0007, 0.0011]), both include zero, so neither
verdict is available; the fix reports each difference's mean and interval as not distinguishable
from zero.

**The per-signal tag that named four facts.** A sentence gave sixteen per-arm seed counts under
one tag, `signal-8.json#goal_check.seeds_at_or_above_target`, which under step 6 holds only the
signal-8 counts. The fix keeps signal 8's counts there and gives signals 1, 2, and 4 their own
sentences and tags.

**The unit conversion that invented a number.** An A5 sentence reported "the mean paired gain in
points is ... 8.6 at signal 4." `signal-4.json#paired_gain.mean` holds 0.0864, in AUROC; no field
holds "points," and 8.6 exists only because 0.0864 was multiplied by 100 by hand. Under step 5
that multiplication is never written: the sentence keeps 0.0864 in AUROC, or drops "points."

**The parent key that nested two facts.** "At signal 8 the Bayes ceiling's mean is 0.947 and the
ceiling minus raw_x3x4 is 0.0003" was tagged to `signal-8.json#ceiling.means`, the parent object
`{"ceiling": 0.9474, "minus_raw_x3x4": 0.0003}`. That parent nests two facts, so under steps 1 and
4 it is never the tag. The ceiling's own mean gets its own sentence at the leaf
`signal-8.json#ceiling.means.ceiling`; the derived difference gets its own sentence at the leaf
`signal-8.json#ceiling.means.minus_raw_x3x4` (or, for a per-seed spread,
`signal-8.json#ceiling.minus_raw_x3x4`, which has no ci95, so no verdict word rides on it either).
