# Interval claims: the one question

You are shown a writer session's returned prose (`groups` and `negative_results`, each a
paragraph whose claim sentences end with `{res:<run-id>/<artifact>#<locator>}` tags) and the
evidence items the session was given (each with its tags and the fields it holds: mean,
`ci95`, and any verdict field). You are not shown anything else, and you have no tools.

Answer yes or no: does every tagged sentence stay inside what its cited key holds, on both of
these counts?

(a) No sentence states a verdict ("does not," "matches," "as much as," "no effect," "holds,"
"fails," "credited," "supported," "confirmed") over a quantity whose cited interval includes
zero, or whose cited key carries no verdict field at all. A sentence about such a quantity may
report only the estimate and the interval, or say the difference is not distinguishable from
zero.

(b) Every number in a tagged sentence is at the tagged key of the tagged file. A sentence that
gives figures for more than one signal, more than one arm, or more than one file may only do so
if it carries a tag for each figure's own file; a sentence with one tag covering numbers from
several signals' files fails this count, whichever numbers are not at the tagged key.

Say no if either count fails anywhere in the prose, and name the sentence and the key it
disagrees with.
