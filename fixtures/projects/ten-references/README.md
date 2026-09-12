# The ten-reference project

A project whose `INTAKE.md` names ten references the way an owner names them: four DOIs (one
bare, one inside a markdown link, one as a `doi.org` URL, one a bioRxiv preprint), three arXiv
ids in three spellings, two titles with no identifier at all, and one reference that does not
exist. It is the smallest thing that exercises the L0 pass end to end, and the suite runs it
offline in `tests/test_dossier.py` against the recorded responses under `fixtures/fetch/`.

Nine of the ten resolve, through four different sources; the tenth is marked
`existence: unresolved`, which is the point of the fixture as much as the nine are.

## From a shell

Copy it out first, so nothing is written inside the harness checkout.

```
cp -r fixtures/projects/ten-references /tmp/ten-references
WAYLINE_HOME=/tmp/ten-references-home bin/wayline init /tmp/ten-references --email you@example.org
WAYLINE_HOME=/tmp/ten-references-home bin/wayline absorb --level 0 --project /tmp/ten-references
```

That second command reaches the real services, paced by the fetch seam, and caches every
response under `research/.cache/scout/`, so a second run costs nothing. To run it with no
network at all, add `--fixtures fixtures/fetch` (an absolute path) and it replays the recordings
instead.

What to look for afterwards: ten directories under `research/refs/` each holding a
`dossier.json`, ten nodes under `research/kb/nodes/`, a `research/kb/query_pack.md` that lists
the ten and carries no abstract, and ten `absorbed` events in the journal.
