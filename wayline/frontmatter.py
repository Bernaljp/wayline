"""The frontmatter of a ticket file: a restricted flat YAML subset, written by code and read here.

The subset (Implementation Decisions 2): `key: scalar` (integer, float, boolean, `null`, bare
or double-quoted string), `key: [a, b]` flow lists of scalars, `key: {k: v}` flow maps of
scalars, and one layer of block nesting whose children are `subkey: scalar`, `subkey: [..]`,
`subkey: {..}`, or `- item` lines. A `#` at the start of a line or preceded by whitespace
starts a comment outside quotes. No anchors, no aliases, no tags, no multi-line scalars, no
single quotes, no deeper nesting: each is rejected with the line it was found on.

`serialize` writes only what `parse` reads, so a document round-trips: after one normalizing
pass (comments dropped, spacing and quoting normalized) the text is a fixed point.
"""

import re

__all__ = ["FrontmatterError", "parse", "serialize", "load_document", "dump_document"]

_KEY = r"[A-Za-z_][A-Za-z0-9_-]*"
_KEY_RE = re.compile(_KEY + r"\Z")
_BLOCK_ENTRY_RE = re.compile(r"(" + _KEY + r"):(?:\s+(.*))?\Z")
_FLOW_ENTRY_RE = re.compile(r"\s*(" + _KEY + r")\s*:(?:\s+(.*))?\Z")
_INT_RE = re.compile(r"-?\d+\Z")
_FLOAT_RE = re.compile(r"-?(?:\d+\.\d*|\.\d+)(?:[eE][-+]?\d+)?\Z|-?\d+[eE][-+]?\d+\Z")
_LOOKALIKES = frozenset(["~", "True", "TRUE", "False", "FALSE", "Null", "NULL", ".inf", "-.inf", ".nan", ".Inf", ".NaN"])
_INDICATORS = frozenset("[]{}\"'&*|>!%@`#,?:")
# Characters some reader treats as a line end (str.splitlines does); written escaped, never raw.
_LINE_BREAKS = frozenset("\r\x0b\x0c\x1c\x1d\x1e\x85  ")
_ESCAPES = {"\\": "\\", '"': '"', "n": "\n", "t": "\t", "r": "\r", "/": "/", "0": "\0"}


class FrontmatterError(ValueError):
    """Text the subset does not accept, or a value it cannot write.

    `line` counts from the opening `---` of a document when parsing; it is None for a
    serializer error, which has no line.
    """

    def __init__(self, message, line=None):
        super().__init__(message if line is None else "line %d: %s" % (line, message))
        self.message = message
        self.line = line


# --- parsing ---------------------------------------------------------------------------------


def parse(text, line_offset=0):
    """Parse frontmatter text into a dict, keeping key order; `line_offset` shifts line numbers.

    Only "\\n" ends a line, as in the files the ledger writes; the other characters
    `str.splitlines` would break on (U+000D, U+0085, U+2028, ...) are data and are quoted on write.
    """
    lines = text.split("\n")
    result = {}
    index = 0
    while index < len(lines):
        lineno = index + 1 + line_offset
        raw = lines[index]
        content = _strip_comment(raw, lineno)
        if not content.strip():
            index += 1
            continue
        if raw[0] in " \t":
            raise FrontmatterError("indented line has no parent key", lineno)
        key, rest = _block_entry(content, lineno)
        if key in result:
            raise FrontmatterError("duplicate key %r" % key, lineno)
        if rest is not None:
            result[key] = _parse_value(rest, lineno)
            index += 1
            continue
        children = []
        cursor = index + 1
        while cursor < len(lines):
            child = lines[cursor]
            if not _strip_comment(child, cursor + 1 + line_offset).strip():
                cursor += 1
                continue
            if child[0] not in " \t":
                break
            children.append((cursor + 1 + line_offset, child))
            cursor += 1
        result[key] = _parse_block(children) if children else None
        index = cursor
    return result


def _strip_comment(raw, lineno):
    """Drop a trailing comment (a `#` at the start or after whitespace, outside quotes)."""
    in_quotes = False
    position = 0
    while position < len(raw):
        char = raw[position]
        if in_quotes:
            if char == "\\":
                position += 1
            elif char == '"':
                in_quotes = False
        elif char == '"':
            in_quotes = True
        elif char == "#" and (position == 0 or raw[position - 1] in " \t"):
            return raw[:position].rstrip()
        position += 1
    if in_quotes:
        raise FrontmatterError("unterminated double quote", lineno)
    return raw.rstrip()


def _block_entry(content, lineno):
    match = _BLOCK_ENTRY_RE.match(content)
    if not match:
        raise FrontmatterError("expected 'key: value' with a key of letters, digits, '_' or '-'", lineno)
    key, rest = match.group(1), match.group(2)
    if rest is not None:
        rest = rest.strip()
        if rest == "":
            rest = None
    return key, rest


def _parse_block(children):
    """Parse one layer of block nesting: all `subkey: ...` lines or all `- item` lines."""
    first_lineno, first_raw = children[0]
    indent = len(first_raw) - len(first_raw.lstrip(" \t"))
    entries = []
    for lineno, raw in children:
        leading = raw[: len(raw) - len(raw.lstrip(" \t"))]
        if "\t" in leading:
            raise FrontmatterError("tabs are not allowed in indentation", lineno)
        if len(leading) > indent:
            raise FrontmatterError("deeper nesting is not allowed (one layer of block nesting)", lineno)
        if len(leading) < indent:
            raise FrontmatterError("inconsistent indentation (block starts at %d spaces)" % indent, lineno)
        entries.append((lineno, _strip_comment(raw, lineno).strip()))
    is_list = entries[0][1] == "-" or entries[0][1].startswith("- ")
    if is_list:
        items = []
        for lineno, content in entries:
            if not (content == "-" or content.startswith("- ")):
                raise FrontmatterError("cannot mix '- item' lines and 'subkey:' lines in one block", lineno)
            item = content[1:].strip()
            if item == "":
                raise FrontmatterError("empty list item", lineno)
            if item[0] in "[{":
                raise FrontmatterError("nested collections are not allowed in a '- item' line", lineno)
            items.append(_parse_scalar(item, lineno, flow=False))
        return items
    mapping = {}
    for lineno, content in entries:
        if content == "-" or content.startswith("- "):
            raise FrontmatterError("cannot mix 'subkey:' lines and '- item' lines in one block", lineno)
        key, rest = _block_entry(content, lineno)
        if key in mapping:
            raise FrontmatterError("duplicate key %r" % key, lineno)
        mapping[key] = None if rest is None else _parse_value(rest, lineno)
    return mapping


def _parse_value(text, lineno):
    if text.startswith("["):
        return _parse_flow_list(text, lineno)
    if text.startswith("{"):
        return _parse_flow_map(text, lineno)
    return _parse_scalar(text, lineno, flow=False)


def _parse_flow_list(text, lineno):
    if not text.endswith("]"):
        raise FrontmatterError("unterminated flow list, or text after it" if "]" in text else "unterminated flow list", lineno)
    items = _split_flow(text[1:-1], lineno)
    result = []
    for position, item in enumerate(items):
        item = item.strip()
        if item == "":
            if position == len(items) - 1 and position > 0:
                continue  # a trailing comma
            raise FrontmatterError("empty item in flow list", lineno)
        if item[0] in "[{":
            raise FrontmatterError("nested collections are not allowed inside a flow list", lineno)
        result.append(_parse_scalar(item, lineno, flow=True))
    return result


def _parse_flow_map(text, lineno):
    if not text.endswith("}"):
        raise FrontmatterError("unterminated flow map, or text after it" if "}" in text else "unterminated flow map", lineno)
    items = _split_flow(text[1:-1], lineno)
    result = {}
    for position, item in enumerate(items):
        if item.strip() == "":
            if position == len(items) - 1 and position > 0:
                continue
            raise FrontmatterError("empty entry in flow map", lineno)
        match = _FLOW_ENTRY_RE.match(item)
        if not match:
            raise FrontmatterError("expected 'key: value' inside the flow map, got %r" % item.strip(), lineno)
        key, value = match.group(1), (match.group(2) or "").strip()
        if key in result:
            raise FrontmatterError("duplicate key %r in flow map" % key, lineno)
        if value == "":
            raise FrontmatterError("missing value for %r in flow map" % key, lineno)
        if value[0] in "[{":
            raise FrontmatterError("nested collections are not allowed inside a flow map", lineno)
        result[key] = _parse_scalar(value, lineno, flow=True)
    return result


def _split_flow(inner, lineno):
    """Split the inside of a flow collection on commas outside double quotes."""
    if inner.strip() == "":
        return []
    items, current, in_quotes, position = [], [], False, 0
    while position < len(inner):
        char = inner[position]
        if in_quotes:
            current.append(char)
            if char == "\\" and position + 1 < len(inner):
                current.append(inner[position + 1])
                position += 1
            elif char == '"':
                in_quotes = False
        elif char == '"':
            in_quotes = True
            current.append(char)
        elif char == ",":
            items.append("".join(current))
            current = []
        else:
            current.append(char)
        position += 1
    items.append("".join(current))
    return items


def _parse_scalar(text, lineno, flow):
    if text.startswith('"'):
        return _parse_quoted(text, lineno)
    first = text[0]
    if first == "'":
        raise FrontmatterError("single quotes are not allowed; use double quotes", lineno)
    if first == "&":
        raise FrontmatterError("anchors are not allowed", lineno)
    if first == "*":
        raise FrontmatterError("aliases are not allowed", lineno)
    if first in "|>":
        raise FrontmatterError("multi-line scalars are not allowed", lineno)
    if first == "!":
        raise FrontmatterError("tags are not allowed", lineno)
    if first in "@`%":
        raise FrontmatterError("a bare string cannot start with %r; double-quote it" % first, lineno)
    if first in "[{":
        raise FrontmatterError("nested collections are not allowed here", lineno)
    if flow and any(char in text for char in "[]{},"):
        raise FrontmatterError("a bare string inside a flow collection cannot contain [ ] { } or ','; double-quote it", lineno)
    if ": " in text or text.endswith(":"):
        raise FrontmatterError("a bare string cannot contain ': ' or end with ':'; double-quote it", lineno)
    if text == "true":
        return True
    if text == "false":
        return False
    if text == "null":
        return None
    if _INT_RE.match(text):
        return int(text)
    if _FLOAT_RE.match(text):
        return float(text)
    return text


def _parse_quoted(text, lineno):
    out = []
    position = 1
    while position < len(text):
        char = text[position]
        if char == "\\":
            position += 1
            if position >= len(text):
                break
            escape = text[position]
            if escape == "u":
                code, position = _unicode_escape(text, position, lineno)
                if 0xD800 <= code <= 0xDBFF:  # a high surrogate must pair with a low one
                    if text[position:position + 2] != "\\u":
                        raise FrontmatterError("a lone surrogate \\u%04x cannot be written back" % code, lineno)
                    low, position = _unicode_escape(text, position + 1, lineno)
                    if not 0xDC00 <= low <= 0xDFFF:
                        raise FrontmatterError("a lone surrogate \\u%04x cannot be written back" % code, lineno)
                    code = 0x10000 + ((code - 0xD800) << 10) + (low - 0xDC00)
                elif 0xDC00 <= code <= 0xDFFF:
                    raise FrontmatterError("a lone surrogate \\u%04x cannot be written back" % code, lineno)
                out.append(chr(code))
                continue
            if escape not in _ESCAPES:
                raise FrontmatterError("unknown escape \\%s in double-quoted string" % escape, lineno)
            out.append(_ESCAPES[escape])
            position += 1
            continue
        if char == '"':
            if text[position + 1:].strip():
                raise FrontmatterError("text after the closing quote", lineno)
            return "".join(out)
        out.append(char)
        position += 1
    raise FrontmatterError("unterminated double quote", lineno)


def _unicode_escape(text, position, lineno):
    """Read the four hex digits after the `u` at `position`; return the code and the position after them."""
    hex_digits = text[position + 1: position + 5]
    if len(hex_digits) != 4 or any(digit not in "0123456789abcdefABCDEF" for digit in hex_digits):
        raise FrontmatterError("a \\u escape needs four hex digits", lineno)
    return int(hex_digits, 16), position + 5


# --- serializing -----------------------------------------------------------------------------


def serialize(mapping):
    """Write a dict in the subset; raises FrontmatterError for a value the parser could not read."""
    lines = []
    for key, value in mapping.items():
        _check_key(key)
        if isinstance(value, dict):
            if all(_is_scalar(item) for item in value.values()):
                lines.append("%s: %s" % (key, _flow_map(value, key)))
            else:
                lines.append("%s:" % key)
                for subkey, item in value.items():
                    _check_key(subkey)
                    if isinstance(item, dict):
                        if not all(_is_scalar(leaf) for leaf in item.values()):
                            raise FrontmatterError("deeper nesting under %r.%r cannot be written" % (key, subkey))
                        lines.append("  %s: %s" % (subkey, _flow_map(item, subkey)))
                    elif isinstance(item, (list, tuple)):
                        lines.append("  %s: %s" % (subkey, _flow_list(item, subkey)))
                    else:
                        lines.append("  %s: %s" % (subkey, _scalar(item, subkey, flow=False)))
        elif isinstance(value, (list, tuple)):
            lines.append("%s: %s" % (key, _flow_list(value, key)))
        else:
            lines.append("%s: %s" % (key, _scalar(value, key, flow=False)))
    return "".join(line + "\n" for line in lines)


def _check_key(key):
    if not isinstance(key, str) or not _KEY_RE.match(key):
        raise FrontmatterError("key %r is not letters, digits, '_' and '-'" % (key,))


def _is_scalar(value):
    return value is None or isinstance(value, (bool, int, float, str))


def _flow_list(items, key):
    parts = []
    for item in items:
        if not _is_scalar(item):
            raise FrontmatterError("list %r holds a non-scalar item; only scalars can be written" % key)
        parts.append(_scalar(item, key, flow=True))
    return "[" + ", ".join(parts) + "]"


def _flow_map(mapping, key):
    parts = []
    for subkey, item in mapping.items():
        _check_key(subkey)
        parts.append("%s: %s" % (subkey, _scalar(item, subkey, flow=True)))
    return "{" + ", ".join(parts) + "}"


def _scalar(value, key, flow):
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise FrontmatterError("%r under %r cannot be written" % (value, key))
        return repr(value)
    if isinstance(value, str):
        return value if _safe_bare(value, flow) else _quote(value)
    raise FrontmatterError("value of type %s under %r cannot be written" % (type(value).__name__, key))


def _safe_bare(text, flow):
    if text == "" or text != text.strip():
        return False
    if text in ("true", "false", "null") or text in _LOOKALIKES:
        return False
    if _INT_RE.match(text) or _FLOAT_RE.match(text):
        return False
    if text[0] in _INDICATORS or text[0] == "-" and (len(text) == 1 or text[1] == " "):
        return False
    if ": " in text or text.endswith(":") or " #" in text or "\t#" in text:
        return False
    if '"' in text or "\\" in text:
        return False
    if any(ord(char) < 32 or ord(char) == 127 or char in _LINE_BREAKS or 0xD800 <= ord(char) <= 0xDFFF for char in text):
        return False
    if flow and any(char in text for char in "[]{},"):
        return False
    return True


def _quote(text):
    out = ['"']
    for char in text:
        if char == "\\":
            out.append("\\\\")
        elif char == '"':
            out.append('\\"')
        elif char == "\n":
            out.append("\\n")
        elif char == "\t":
            out.append("\\t")
        elif char == "\r":
            out.append("\\r")
        elif ord(char) < 32 or ord(char) == 127 or char in _LINE_BREAKS:
            out.append("\\u%04x" % ord(char))
        elif 0xD800 <= ord(char) <= 0xDFFF:
            raise FrontmatterError("a lone surrogate U+%04X cannot be written" % ord(char))
        else:
            out.append(char)
    out.append('"')
    return "".join(out)


# --- documents -------------------------------------------------------------------------------


def load_document(text):
    """Split a ticket file into `(frontmatter dict, body)`; the body is kept verbatim."""
    lines = text.split("\n")
    if lines[0].rstrip() != "---":
        raise FrontmatterError("document must start with a '---' line", 1)
    for index in range(1, len(lines)):
        if lines[index].rstrip() == "---":
            mapping = parse("\n".join(lines[1:index]), line_offset=1)
            return mapping, "\n".join(lines[index + 1:])
    last_line = len(lines) - 1 if text.endswith("\n") else len(lines)
    raise FrontmatterError("closing '---' line not found", last_line)


def dump_document(mapping, body):
    """Write a ticket file: the frontmatter between `---` lines, then the body verbatim."""
    return "---\n" + serialize(mapping) + "---\n" + body
