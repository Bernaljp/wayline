# Protocol

1. Read the question and the scope limit above. They are the whole of what you answer.
2. Open every path listed under the subject. A path the harness could not find is announced
   where it is listed; treat that as something you could not check, not as something that passed.
3. Judge the subject against the question from what you read. Where the question asks about a
   diff, read the diff itself with the git commands you have, not the file as it stands now.
4. Write down each problem as you find it, with the path and the line or heading you read it at,
   and the severity you would defend to the person who has to act on it.
5. Decide. `pass` is true when the subject answers the question: no `blocker`, and nothing you
   would be embarrassed to have waved through. Otherwise `pass` is false and at least one
   finding says why, at a locator.
6. Restate the question you answered in `question_limit`, in your own words. It is how a reader
   checks that this verdict is about what was asked and not about something wider you noticed.
7. Return the verdict through the structured output. It is the only thing that reaches the
   ledger: nothing you say outside it is read by anyone.
