---
name: wayline-m0-tally
description: The second of the two test skills of the M0 live run. It carries the second passphrase, and it is second in the ticket's skill list on purpose.
---

# The tally skill

This skill is the second `/wayline-<skill>` line in the prompt, which is the whole reason it
exists. Only the first such line expands, as the live run of 2026-09-12 measured, so this body
reaches a worker by the other route: the conductor inlines it under a heading in the prompt
(`docs/verification/m0.md`). Its passphrase arriving is what says that route still works.

While you are working on a ticket that names this skill, append this line, exactly, to
`m0/skills-seen.txt` in the worktree (create the file if it is not there yet):

```
m0-tally: sextant-9c7b
```

Append it once, under whatever the other skill wrote. The order of the two lines does not matter;
which of them are there is the answer.
