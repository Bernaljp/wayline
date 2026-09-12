# Recorded responses for the fetch seam

One file per request, at `<host>/<request hash>.json`, holding the request that was made and the
response that came back. The suite replays these instead of reaching the network: `test_scout`
and `test_dossier` run the whole resolution chain against this directory, and a request nobody
recorded raises rather than going out.

The request hash covers the method, the URL, and the stable headers, with two things deliberately
left out: the `User-Agent`, and the values of the `mailto` and `email` query parameters that the
polite pools want an address in. So a recording made on one machine replays on every other, and
no recording here carries the address of whoever made it. A test asserts that.

These were recorded against the live services on 2026-09-12 with the chain of
`research-notes/06-pdf-inventory-and-keyless-apis.md` Section 3: Crossref, OpenAlex, Unpaywall,
Europe PMC, the arXiv API, and the bioRxiv API.

## Remaking them

Delete the files to be remade, then, from the harness root, with a real address:

```python
from pathlib import Path
from wayline.fetch import recording_fetcher
from wayline.scout import Scout

scout = Scout(recording_fetcher(Path("fixtures/fetch"), email="you@example.org", live=True), "you@example.org")
for reference in ["10.1038/s41586-020-2649-2", "Attention Is All You Need", "arXiv:1706.03762",
                  "10.1101/2020.03.22.002386",
                  "A comprehensive taxonomy of interpretive marmalade in high-dimensional sponge topology"]:
    print(reference, scout.resolve(reference)["existence"])
```

The seam paces the requests itself, so this takes a few seconds against arXiv and no time at all
against the rest. A service that has since changed its answer will change the test's expected
values with it; that is the point of recording rather than hand-writing them.

`fixtures/projects/ten-references/` is the sample intake the L0 pass runs on, and its ten
references are covered by these same recordings.
