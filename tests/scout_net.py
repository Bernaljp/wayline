"""The network the scout's tests ask: scripted answers behind the fetch seam, and synthetic recordings.

`Net` answers by URL and counts what it was asked, so a test can say what reached "the network".
`recorded` runs a fetcher over a `Net` into a temporary directory once, which is how
`fixtures/fetch/` was made against the live services, and the directory then replays.
"""

import json
import tempfile
from pathlib import Path

from wayline.fetch import Backend, DirectoryBackend, FetchError, Fetcher, Response

EMAIL = "owner@example.org"
NOW = 1_790_000_000.0  # 2026-09-21T14:13:20Z, a fixed clock
DAY = 86_400.0

DOI = "10.5555/wayline.found"
NOT_FOUND = (404, '{"error": "not found"}')
DOWN = (503, "Service Unavailable")
EMPTY_EUROPEPMC = (200, json.dumps({"resultList": {"result": []}}))


def crossref_work(doi=DOI, title="A work the services know", abstract="What the work found.", year=2021, family="Lovelace"):
    """A Crossref `works/{doi}` answer for one work."""
    return (200, json.dumps({"status": "ok", "message": {
        "DOI": doi, "title": [title], "author": [{"given": "Ada", "family": family}],
        "issued": {"date-parts": [[year]]}, "container-title": ["Journal of Tests"], "type": "journal-article",
        "abstract": "<jats:p>%s</jats:p>" % abstract,
    }}))


TITLE = "Learning the flows of single cells"


def title_search(doi, title=TITLE, family="Lovelace", year=2022):
    """A Crossref `query.bibliographic` answer whose one item is the work under `doi`."""
    return (200, json.dumps({"status": "ok", "message": {"items": [{
        "DOI": doi, "title": [title], "author": [{"given": "Ada", "family": family}],
        "issued": {"date-parts": [[year]]}, "container-title": ["Journal of Tests"], "type": "journal-article",
    }]}}))


def doi_answers(crossref, rest=NOT_FOUND):
    """The DOI chain's four services: Crossref as given, the others answering `rest` (Europe PMC an empty list)."""
    return {"api.crossref.org": crossref, "api.openalex.org": rest, "api.unpaywall.org": rest,
            "www.ebi.ac.uk": EMPTY_EUROPEPMC if rest == NOT_FOUND else rest}


class Net(Backend):
    """The network, scripted: the first key found in a URL picks its answer; a FetchError is raised as a timeout would be."""

    def __init__(self, answers):
        self.answers = dict(answers)
        self.asked = []

    def send(self, request):
        self.asked.append(request.url)
        for key, answer in self.answers.items():
            if key in request.url:
                if isinstance(answer, Exception):
                    raise answer
                status, body = answer
                return Response(request.url, status, {}, body.encode("utf-8") if isinstance(body, str) else body)
        raise FetchError("nobody scripted %s" % request.url)


def net_fetcher(answers):
    """A fetcher straight onto a scripted network, and the network."""
    net = Net(answers)
    return Fetcher(net, email=EMAIL), net


def recorded(answers):
    """Synthetic recordings: a temporary directory a recording fetcher over `answers` fills, and that fetcher."""
    root = Path(tempfile.mkdtemp(prefix="wayline-recorded-"))
    return root, Fetcher(DirectoryBackend(root, inner=Net(answers), record=True), email=EMAIL)


def quiet_search():
    """Position's setup search of its missing prior work (ticket 99), always live, put on a network that answers nothing."""
    from unittest import mock
    from wayline import survey
    return mock.patch.object(survey, "search_fetcher", lambda email=None: net_fetcher({})[0])
