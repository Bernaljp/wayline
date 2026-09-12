---
name: wayline-m0-note
description: The first of the two test skills of the M0 live run. It carries one passphrase, and the only way to learn that passphrase is to have this skill's body in front of you.
---

# The note skill

This skill exists to answer one question: does a `/wayline-<skill>` line at the top of a worker's
prompt expand into the skill's body? It carries a passphrase for that, and nothing else. The
passphrase is written here and nowhere else in the project, so a worker that reports it read this
file, and a worker that cannot report it did not.

While you are working on a ticket that names this skill, append this line, exactly, to
`m0/skills-seen.txt` in the worktree (create the file if it is not there yet):

```
m0-note: plumbline-4f2a
```

Append it once. Leave whatever other lines the file already holds alone: the other skill writes
its own, and the two lines together are the record.
