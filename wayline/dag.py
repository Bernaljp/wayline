"""The graph SVG of Implementation Decisions 8: a layered layout in a few dozen lines.

Ported from `research-notes/08-dashboard-transport.md` Section 5's throwaway `dag.py`, which
measured it against `@dagrejs/dagre` (48,956 bytes, a dependency) and found longest-path layering
plus two barycenter sweeps enough for a ticket graph: a 14-node, 18-edge layout came to 4258 bytes
of well-formed SVG. The algorithm is carried over unchanged; only the longest-path pass is written
iteratively rather than as memoized recursion, since a project's ticket count is not bounded the
way the prototype's fixture was and Python's recursion limit is not a graph-size limit wayline
should inherit by accident.

Long edges that skip layers are drawn straight through the layers between: the note flags this and
gives the fix (a dummy node per skipped layer before the barycenter sweeps) as an optional Sugiyama
refinement, not something this ticket's acceptance criteria ask for.
"""

__all__ = ["DagError", "STATUS_COLOR", "layout", "svg"]

# Node box and grid spacing, exactly as measured.
NODE_W, NODE_H, GAP_X, GAP_Y = 120, 36, 40, 70

# The prototype's four; wayline's real ticket statuses (wayline.tickets.STATUSES) need the rest.
# "frontier" overrides whatever status a node carries, and always wins the fill.
STATUS_COLOR = {
    "open": "#dddddd",
    "running": "#ffd966",
    "done": "#9be49b",
    "accepted": "#6fbf73",
    "failed": "#f2a6a6",
    "blocked": "#c9c9c9",
    "needs_human": "#f2994a",
    "parked": "#b0b0b0",
    "frontier": "#8ecae6",
}


class DagError(ValueError):
    """A graph `layout` or `svg` cannot draw: a node in an edge that is not in `nodes`."""


def _layers(nodes, parents):
    """Longest path from any source, per node: layer 0 for a node with no parents.

    Iterative post-order over `parents` rather than the prototype's memoized recursion, so a large
    graph cannot exhaust the call stack; the layer numbers it produces are the same ones the
    recursive `L(n)` would.
    """
    layer = {}
    for start in nodes:
        if start in layer:
            continue
        stack, on_stack = [start], {start}
        while stack:
            node = stack[-1]
            pending = [parent for parent in parents[node] if parent not in layer]
            if pending:
                for parent in pending:
                    if parent in on_stack:
                        raise DagError("the edges form a cycle through node %r" % (parent,))
                    on_stack.add(parent)
                    stack.append(parent)
            else:
                layer[node] = 1 + max((layer[parent] for parent in parents[node]), default=-1)
                on_stack.discard(node)
                stack.pop()
    return layer


def layout(nodes, edges, w=NODE_W, h=NODE_H, gx=GAP_X, gy=GAP_Y):
    """Node positions and the canvas size: layering by longest path, then two barycenter sweeps.

    Returns `(pos, (width, height))`, `pos[node] = (x, y)` the top-left corner of its box. Row
    order starts as the order `nodes` were given in, then two down-sweeps (by mean parent order)
    alternate with two up-sweeps (by mean child order) exactly as the measured prototype ran them,
    so two ticket graphs with the same nodes and edges always draw identically.
    """
    nodes = list(nodes)
    present = set(nodes)
    parents = {node: [] for node in nodes}
    kids = {node: [] for node in nodes}
    for a, b in edges:
        if a not in present or b not in present:
            raise DagError("edge %r references a node not in nodes" % ((a, b),))
        kids[a].append(b)
        parents[b].append(a)
    layer = _layers(nodes, parents)
    rows = {}
    for node in nodes:
        rows.setdefault(layer[node], []).append(node)
    order = {node: index for row in rows.values() for index, node in enumerate(row)}
    for _ in range(2):  # barycenter sweeps down then up, as the prototype ran them
        for r in sorted(rows):
            key = (lambda n: (sum(order[p] for p in parents[n]) / len(parents[n])) if parents[n] else order[n])
            rows[r].sort(key=key)
            order.update({n: i for i, n in enumerate(rows[r])})
        for r in sorted(rows, reverse=True):
            key = (lambda n: (sum(order[k] for k in kids[n]) / len(kids[n])) if kids[n] else order[n])
            rows[r].sort(key=key)
            order.update({n: i for i, n in enumerate(rows[r])})
    width = max(len(row) for row in rows.values())
    pos = {}
    for r, row in rows.items():
        x0 = (width - len(row)) * (w + gx) / 2
        for i, node in enumerate(row):
            pos[node] = (x0 + i * (w + gx), r * (h + gy))
    return pos, (width * (w + gx), len(rows) * (h + gy))


def svg(nodes, edges, status, color=None, link="#ticket/%s", w=NODE_W, h=NODE_H, gx=GAP_X, gy=GAP_Y):
    """The graph as inline SVG: one link-wrapped, status-filled rect per node, one arrow per edge.

    `status[node]` must be a key of `color` (`STATUS_COLOR` by default); a node whose caller has
    already decided is in the frontier should carry `"frontier"` rather than its raw ticket status,
    since that fill always wins over the others. `link` is a `%`-format string taking the node id,
    so the caller decides what a click resolves to (the dashboard's front end intercepts it rather
    than navigating, since the page is a single-page app).
    """
    color = STATUS_COLOR if color is None else color
    pos, (W, H) = layout(nodes, edges, w=w, h=h, gx=gx, gy=gy)
    out = ['<svg viewBox="0 0 %d %d" xmlns="http://www.w3.org/2000/svg">' % (W, H)]
    out.append(
        '<defs><marker id="a" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="6" markerHeight="6" '
        'orient="auto"><path d="M0,0L10,5L0,10z"/></marker></defs>'
    )
    for a, b in edges:
        (x1, y1), (x2, y2) = pos[a], pos[b]
        out.append(
            '<line x1="%g" y1="%g" x2="%g" y2="%g" stroke="#666" marker-end="url(#a)"/>'
            % (x1 + w / 2, y1 + h, x2 + w / 2, y2)
        )
    for node in nodes:
        x, y = pos[node]
        fill = color[status[node]]
        out.append(
            '<a href="%s"><rect x="%g" y="%g" width="%d" height="%d" rx="6" fill="%s" stroke="#333"/>'
            '<text x="%g" y="%g" text-anchor="middle" font-size="12">%s</text></a>'
            % (link % node, x, y, w, h, fill, x + w / 2, y + h / 2 + 5, node)
        )
    return "\n".join(out) + "\n</svg>\n"
