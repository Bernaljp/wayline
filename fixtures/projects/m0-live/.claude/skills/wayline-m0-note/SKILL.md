---
name: wayline-m0-note
description: The first of the two test skills of the M0 live run. It carries one passphrase, and the only way to learn that passphrase is to have this skill's body in front of you.
---

# The note skill

This skill is the first `/wayline-<skill>` line in the prompt, which is the one that expands. It
carries a passphrase for that, and nothing else. The passphrase is written here and nowhere else
in the project, and the prompt itself never carries it, so a worker that reports it had this body
in front of it and a worker that cannot report it did not.

While you are working on a ticket that names this skill, append this line, exactly, to
`m0/skills-seen.txt` in the worktree (create the file if it is not there yet):

```
m0-note: plumbline-4f2a
```

Append it once. Leave whatever other lines the file already holds alone: the other skill writes
its own, and the two lines together are the record.
