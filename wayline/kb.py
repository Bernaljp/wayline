"""The project knowledge base (Implementation Decisions 9): typed nodes, typed edges, one query pack.

The division of labour with the dossiers is the whole design: a dossier holds depth, the
knowledge base holds relations, and no prose is duplicated between them. So a node here is an
identity and a handle, never a summary, and `query_pack.md`, which is what gets injected into
planning and ideation, is a list of nodes and the edges between them under
`policy.kb.query_pack_max_chars`. A test asserts an abstract never reaches it.

Four node kinds (`paper`, `idea`, `experiment`, `claim`) and the seven edge types the spec
names. Everything is written through the ledger, which is the only writer under `research/`.
"""

import json
import re

from wayline.ledger import ledger_for, now_ts

__all__ = [
    "KBError", "KB_DIR", "NODES_DIR", "EDGES", "QUERY_PACK", "NODE_KINDS", "EDGE_TYPES",
    "make_node", "make_edge", "write_node", "add_edge", "read_nodes", "read_edges",
    "render_query_pack", "rebuild_query_pack", "node_id", "slugify", "ID_MAX",
]

KB_DIR = "kb"
NODES_DIR = KB_DIR + "/nodes"
EDGES = KB_DIR + "/edges.jsonl"
QUERY_PACK = KB_DIR + "/query_pack.md"

NODE_KINDS = ("paper", "idea", "experiment", "claim")
EDGE_TYPES = ("extends", "contradicts", "tested_by", "supports", "refutes", "uses", "depends_on")

# The fields a node carries. Nothing here is prose: `title` is an identity, not a summary.
NODE_FIELDS = ("schema_version", "id", "kind", "title", "identifiers", "year", "level", "existence", "source", "ticket", "created")
EDGE_FIELDS = ("from", "to", "type", "note", "created")

# A node id, which is also a dossier's directory name under `refs/`: the two are the same string,
# so they are normalized by the same function and cannot drift into two spellings of one slug.
ID_MAX = 80
_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,%d}$" % (ID_MAX - 1))
_SLUGGABLE = re.compile(r"[^a-z0-9]+")


class KBError(ValueError):
    """A node or an edge the knowledge base refuses: an unknown kind, an unknown edge type, a bad id."""


def slugify(text, limit=ID_MAX):
    """Free text as the lowercase hyphenated form a node id and a dossier directory take.

    Returns the empty string when nothing survives; `node_id` is the spelling that refuses that.
    """
    return _SLUGGABLE.sub("-", str(text or "").lower()).strip("-")[:limit].strip("-")


def node_id(text, prefix=None):
    """A node id out of free text: lowercase, hyphenated, at most 80 characters."""
    slug = slugify("%s-%s" % (prefix, text) if prefix else text)
    if not slug:
        raise KBError("%r leaves nothing that can be a node id" % (text,))
    return slug


def make_node(identifier, kind, title, **fields):
    """One validated node. Unknown fields are refused, because a typed graph is the point."""
    if kind not in NODE_KINDS:
        raise KBError("node kind %r is not one of %s" % (kind, list(NODE_KINDS)))
    if not _ID.match(str(identifier or "")):
        raise KBError("node id %r is not lowercase, hyphenated, and at most 80 characters" % (identifier,))
    if not str(title or "").strip():
        raise KBError("node %s needs a title" % identifier)
    unknown = [key for key in fields if key not in NODE_FIELDS]
    if unknown:
        raise KBError("a node carries %s, not %s" % (list(NODE_FIELDS), ", ".join(map(repr, unknown))))
    node = {"schema_version": 1, "id": identifier, "kind": kind, "title": str(title).strip()}
    node.update({key: value for key, value in fields.items() if value is not None})
    node.setdefault("created", now_ts())
    return node


def make_edge(source, target, edge_type, note=None):
    """One validated edge. Both ends are node ids; the type is one of the seven."""
    if edge_type not in EDGE_TYPES:
        raise KBError("edge type %r is not one of %s" % (edge_type, list(EDGE_TYPES)))
    for end in (source, target):
        if not _ID.match(str(end or "")):
            raise KBError("edge end %r is not a node id" % (end,))
    if source == target:
        raise KBError("an edge from %s to itself says nothing" % source)
    edge = {"from": source, "to": target, "type": edge_type, "created": now_ts()}
    if note:
        edge["note"] = str(note)
    return edge


def write_node(project_or_ledger, node):
    """Write `kb/nodes/<id>.json`, replacing whatever was there. Returns the path."""
    ledger = ledger_for(project_or_ledger)
    return ledger.write_json("%s/%s.json" % (NODES_DIR, node["id"]), node)


def add_edge(project_or_ledger, edge):
    """Append one edge to `kb/edges.jsonl`, unless the same triple is already there."""
    ledger = ledger_for(project_or_ledger)
    triple = (edge["from"], edge["to"], edge["type"])
    for existing in read_edges(ledger):
        if (existing.get("from"), existing.get("to"), existing.get("type")) == triple:
            return existing
    ledger.append_record(EDGES, edge)
    return edge


def read_nodes(project_or_ledger):
    """Every node, by id. A file that is not readable JSON is skipped rather than raising."""
    ledger = ledger_for(project_or_ledger)
    directory = ledger.research / NODES_DIR
    nodes = {}
    if not directory.is_dir():
        return nodes
    for path in sorted(directory.glob("*.json")):
        try:
            node = ledger.read_json("%s/%s" % (NODES_DIR, path.name))
        except (OSError, ValueError):
            continue
        if isinstance(node, dict) and node.get("id"):
            nodes[node["id"]] = node
    return nodes


def read_edges(project_or_ledger):
    """Every edge, in the order they were appended; a torn line is skipped."""
    ledger = ledger_for(project_or_ledger)
    path = ledger.research / EDGES
    if not path.is_file():
        return []
    edges = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            edge = json.loads(line)
        except ValueError:
            continue
        if isinstance(edge, dict) and edge.get("from") and edge.get("to"):
            edges.append(edge)
    return edges


def render_query_pack(nodes, edges, max_chars):
    """The query pack: relations and identities, cut to `max_chars`, never any dossier prose.

    What is dropped first when the cap bites is the node that takes part in no edge, because a
    node with no relation is the least of what this file exists to carry. The cut is announced
    in the text, so a reader of the pack knows it is looking at part of the graph.
    """
    nodes = dict(nodes)
    edges = [edge for edge in edges if edge.get("from") in nodes and edge.get("to") in nodes]
    connected = {end for edge in edges for end in (edge["from"], edge["to"])}
    ordered = sorted(nodes.values(), key=lambda node: (node["id"] not in connected, node.get("kind", ""), node["id"]))

    counts = {}
    for node in ordered:
        counts[node.get("kind", "?")] = counts.get(node.get("kind", "?"), 0) + 1
    spread = ", ".join("%s %d" % (kind, counts[kind]) for kind in sorted(counts))
    header = [
        "# Knowledge base",
        "",
        "Relations only: the dossiers hold what each paper says. %d node(s)%s; %d edge(s)."
        % (len(ordered), " (%s)" % spread if spread else "", len(edges)),
        "",
    ]
    edge_lines = ["## Edges", ""] + ([
        "- `%s` %s `%s`%s" % (edge["from"], edge["type"], edge["to"], "  (%s)" % edge["note"] if edge.get("note") else "")
        for edge in edges
    ] or ["- none yet"]) + [""]
    node_lines = ["## Nodes", ""]

    fixed = "\n".join(header + edge_lines + node_lines) + "\n"
    room = max_chars - len(fixed)
    body, dropped = [], 0
    for node in ordered:
        line = "- `%s` %s" % (node["id"], _facts(node))
        if room - (len(line) + 1) < 0:
            dropped += 1
            continue
        room -= len(line) + 1
        body.append(line)
    if dropped:
        note = "- (%d node(s) left out: the pack is capped at %d characters)" % (dropped, max_chars)
        while body and len(note) + 1 > room:
            room += len(body.pop()) + 1
            dropped += 1
            note = "- (%d node(s) left out: the pack is capped at %d characters)" % (dropped, max_chars)
        body.append(note)
    return "\n".join(header + edge_lines + node_lines + (body or ["- none yet"])) + "\n"


def _facts(node):
    """A node's line: its kind and identity, and not one word of what the paper says."""
    parts = [node.get("kind", "?")]
    if node.get("level") is not None:
        parts.append("L%s" % node["level"])
    if node.get("existence"):
        parts.append(node["existence"])
    if node.get("year"):
        parts.append(str(node["year"]))
    identifiers = node.get("identifiers") or {}
    for key in ("doi", "arxiv_id"):
        if identifiers.get(key):
            parts.append("%s %s" % (key, identifiers[key]))
            break
    return "%s -- %s" % (", ".join(parts), node.get("title", ""))


def rebuild_query_pack(project_or_ledger, max_chars):
    """Regenerate `kb/query_pack.md` from the nodes and edges on disk. Returns the text written."""
    ledger = ledger_for(project_or_ledger)
    text = render_query_pack(read_nodes(ledger), read_edges(ledger), max_chars)
    ledger.write_markdown(QUERY_PACK, text)
    return text
