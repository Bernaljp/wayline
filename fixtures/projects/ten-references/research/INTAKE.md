# Intake

## The intent

Exercise the L0 pass end to end: ten references the owner names in prose, each resolved through
the keyless chain into a dossier, a knowledge-base node, and a line of the query pack. The answer
is ten records under `research/refs/` whose identifiers came off a response, and one reference
that resolves nowhere and says so.

## What exists already

Nothing but this file. The project is a fixture: it is copied out of the harness, laid out by
`wayline init`, and absorbed with the recorded responses under `fixtures/fetch/`.

## References

The list is written the way an owner writes one: DOIs bare and inside links, arXiv ids in two
spellings, titles with no identifier at all, and one reference that does not exist.

- 10.1038/s41586-020-2649-2
- [SciPy 1.0: fundamental algorithms for scientific computing in Python](https://doi.org/10.1038/s41592-019-0686-2)
- https://doi.org/10.1371/journal.pcbi.1008074
- 10.1101/2020.03.22.002386
- arXiv:1706.03762
- arxiv.org/abs/1802.03426
- arXiv:1912.01703
- Highly accurate protein structure prediction with AlphaFold
- Integrating single-cell transcriptomic data across different conditions, technologies, and species
- A comprehensive taxonomy of interpretive marmalade in high-dimensional sponge topology

## Constraints

No model is launched and no GPU is touched: the L0 pass is code and requests only.

## Success

Ten dossiers under `research/refs/`, ten nodes under `research/kb/nodes/`, a `query_pack.md` that
holds relations and no abstract, and the last reference marked `existence: unresolved`.
