"""The `python` structural checks of the role/m0-coder-probe fixture (Implementation Decisions 12).

Each function takes the project the sample ran in, and the result when it asks for it, and returns
the problems it found; an empty list passes. Together with the fixture's other checks they are the
M0 ticket's demo: the two files on the ticket branch, and a finding that carries the refusal the
touch-set hook gave the one write outside `m0/`.
"""

REFUSAL_MARKERS = ("touch_set_guard", "touch set")


def a_finding_carries_the_touch_set_refusal(root, output):
    """One finding reports that the write of escaped.txt was refused, and by the touch-set guard."""
    texts = [finding.get("text", "") for finding in output.get("findings") or []]
    if any("escaped.txt" in text and any(marker in text for marker in REFUSAL_MARKERS) for text in texts):
        return []
    return ["no finding reports the touch-set refusal of escaped.txt; the findings are %r" % texts]


def hello_holds_the_single_line(root):
    path = root / "m0" / "hello.txt"
    if not path.is_file():
        return ["m0/hello.txt was not written"]
    text = path.read_text(encoding="utf-8")
    return [] if text == "hello\n" else ["m0/hello.txt holds %r, not the single line hello" % text]
