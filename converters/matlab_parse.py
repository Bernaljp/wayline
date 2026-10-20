"""One MATLAB file read by tree-sitter-matlab, as JSON. Runs inside the tools venv.

The harness imports no third-party package, so it never imports tree-sitter: it runs this script
with the tools venv's Python (`wayline tools run tree-sitter-matlab -- matlab_parse.py <file.m>`) and
reads the JSON it prints. Usage:

    <tools venv>/bin/python matlab_parse.py <file.m>

What it prints is the parse and nothing judged: the functions with their arguments and line spans;
every call-shaped node (`f(...)`, which MATLAB also writes for indexing, so the reader tells the
two apart by what is a variable), with its arguments as text and node type; every assignment with
its value; and the `if nargin < k, name = value; end` defaults. Lines are 1-based. The rules of
the code-to-Methods check (`wayline/methods.py`) are applied by the harness, not here.
"""

import json
import sys

import tree_sitter
import tree_sitter_matlab


def _text(source, node):
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _named(node, kind):
    return [child for child in node.children if child.type == kind]


def _enclosing(node):
    while node is not None and node.type != "function_definition":
        node = node.parent
    return node


def _function_name(source, node):
    names = _named(node, "identifier")
    return _text(source, names[0]) if names else None


def _arguments(source, call):
    found = _named(call, "arguments")
    if not found:
        return []
    return [{"text": _text(source, child), "kind": child.type} for child in found[0].named_children
            if child.type not in ("comment", "line_continuation")]


def _nargin_default(source, node, function):
    """`if nargin < k, name = value; end`: the default an argument takes when the caller leaves it out."""
    condition = node.child_by_field_name("condition") or next(
        (child for child in node.named_children if child.type == "comparison_operator"), None)
    if condition is None or condition.type != "comparison_operator" or "nargin" not in _text(source, condition):
        return []
    defaults = []
    for block in _named(node, "block"):
        for assignment in _named(block, "assignment"):
            left = assignment.named_children[0] if assignment.named_children else None
            right = assignment.named_children[-1] if len(assignment.named_children) > 1 else None
            if left is not None and left.type == "identifier" and right is not None:
                defaults.append({"function": function, "name": _text(source, left), "value": _text(source, right),
                                 "kind": right.type, "line": assignment.start_point[0] + 1})
    return defaults


def parse(path):
    source = open(path, "rb").read()
    parser = tree_sitter.Parser(tree_sitter.Language(tree_sitter_matlab.language()))
    tree = parser.parse(source)
    functions, calls, assignments, defaults = [], [], [], []
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        stack.extend(reversed(node.children))
        enclosing = _enclosing(node.parent)
        where = _function_name(source, enclosing) if enclosing is not None else None
        if node.type == "function_definition":
            arguments = _named(node, "function_arguments")
            params = [_text(source, child) for child in arguments[0].named_children if child.type == "identifier"] if arguments else []
            outputs = _named(node, "function_output")
            functions.append({"name": _function_name(source, node), "params": params,
                              "outputs": _text(source, outputs[0]).rstrip("= ").strip() if outputs else "",
                              "start": node.start_point[0] + 1, "end": node.end_point[0] + 1, "parent": where})
        elif node.type == "function_call":
            names = _named(node, "identifier")
            if names:
                calls.append({"name": _text(source, names[0]), "line": node.start_point[0] + 1, "end": node.end_point[0] + 1,
                              "function": where, "args": _arguments(source, node), "text": _text(source, node)})
        elif node.type == "assignment":
            left = node.named_children[0] if node.named_children else None
            right = node.named_children[-1] if len(node.named_children) > 1 else None
            if left is not None and right is not None:
                targets = [_text(source, left)] if left.type == "identifier" else \
                    [_text(source, child) for child in left.named_children if child.type == "identifier"]
                for target in targets:
                    assignments.append({"name": target, "value": _text(source, right), "kind": right.type,
                                        "line": node.start_point[0] + 1, "function": where})
        elif node.type == "if_statement":
            defaults.extend(_nargin_default(source, node, where))
    errors = tree.root_node.has_error
    return {"functions": functions, "calls": calls, "assignments": assignments, "nargin_defaults": defaults,
            "has_error": bool(errors)}


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: matlab_parse.py <file.m>", file=sys.stderr)
        sys.exit(2)
    print(json.dumps(parse(sys.argv[1]), indent=1, sort_keys=True))
