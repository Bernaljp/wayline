"""A stand-in for `python -m sphinx -b html`, for the docs tests (the suite never has Sphinx installed).

It reads the `.rst` sources the way the checks need them read and no further: a page per source with
a `<section id>` from its title, the toctree entries, `:doc:` roles and `` `text <target>`_ `` links as
anchors, images copied under `_images/`, literal includes as `<pre>` with the file named, and
`automodule` with `:members:` as one `<dt id>` and one `objects.inv` entry per documented top-level
function or class, since autodoc leaves out a member with no docstring unless told otherwise. That
last rule is why a symbol with no docstring is also missing from the reference, as it is under the
real thing.
"""

import ast
import html
import re
import shutil
import zlib
from pathlib import Path

_DIRECTIVE = re.compile(r"^\.\. (\w[\w-]*)::\s*(.*)$")
_DOC_ROLE = re.compile(r":doc:`([^`]+)`")
_LINK = re.compile(r"`([^`<]+?)\s*<([^>]+)>`_")


class FakeSphinx:
    """Callable as the `sphinx` seam of `wayline.docs.build`; records each call it answers."""

    def __init__(self, warnings=(), exit_code=0):
        self.warnings = list(warnings)
        self.exit_code = exit_code
        self.calls = []

    def __call__(self, python, source, out, doctrees, warnings_path, env, timeout_s):
        self.calls.append({"python": python, "source": Path(source), "out": Path(out), "env": dict(env)})
        source, out = Path(source), Path(out)
        out.mkdir(parents=True, exist_ok=True)
        search = [Path(part) for part in env.get("PYTHONPATH", "").split(":") if part]
        objects = []
        for page in sorted(source.rglob("*.rst")):
            relative = page.relative_to(source).with_suffix("")
            body = self._page(page, source, out, relative, search, objects)
            target = out / _html(relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding="utf-8")
        write_objects_inv(out / "objects.inv", objects)
        Path(warnings_path).write_text("".join(line + "\n" for line in self.warnings), encoding="utf-8")
        return self.exit_code, ""

    def _page(self, page, source, out, relative, search, objects):
        lines = page.read_text(encoding="utf-8").splitlines()
        title = lines[0].strip() if lines else relative.name
        depth = len(relative.parts) - 1
        up = "../" * depth
        parts = ['<html><body><section id="%s"><h1>%s</h1>' % (slug(title), html.escape(title))]
        index = 0
        while index < len(lines):
            line = lines[index]
            match = _DIRECTIVE.match(line)
            if not match:
                for target in _DOC_ROLE.findall(line):
                    parts.append('<a href="%s.html">%s</a>' % (target, target))
                for text, target in _LINK.findall(line):
                    parts.append('<a href="%s">%s</a>' % (target, html.escape(text)))
                index += 1
                continue
            name, argument = match.group(1), match.group(2).strip()
            block = []
            index += 1
            while index < len(lines) and (not lines[index].strip() or lines[index].startswith("   ")):
                block.append(lines[index].strip())
                index += 1
            entries = [item for item in block if item and not item.startswith(":")]
            options = [item for item in block if item.startswith(":")]
            if name == "toctree" and ":glob:" in options:
                found = sorted(path.relative_to(page.parent).with_suffix("").as_posix()
                               for pattern in entries for path in page.parent.glob(pattern + ".rst") if path != page)
                parts.extend('<a href="%s.html">%s</a>' % (entry, entry) for entry in found)
            elif name == "toctree":
                parts.extend('<a href="%s.html">%s</a>' % (entry, entry) for entry in entries)
            elif name in ("image", "figure"):
                image = (page.parent / argument).resolve()
                destination = out / "_images" / image.name
                destination.parent.mkdir(parents=True, exist_ok=True)
                if image.is_file():
                    shutil.copyfile(image, destination)
                parts.append('<img src="%s_images/%s">' % (up, image.name))
            elif name == "literalinclude":
                included = page.parent / argument
                text = included.read_text(encoding="utf-8") if included.is_file() else ""
                parts.append('<div><span class="caption">%s</span><pre>%s</pre></div>' % (argument, html.escape(text)))
            elif name == "automodule" and ":members:" in options:
                page_uri = _html(relative).as_posix()
                for member, role in documented_members(argument, search):
                    full = "%s.%s" % (argument, member)
                    parts.append('<dt id="%s">%s</dt>' % (full, full))
                    objects.append((full, "py:" + role, page_uri + "#$"))
        parts.append("</section></body></html>")
        return "\n".join(parts)


def documented_members(module, search):
    """`(name, role)` of each public top-level function and class of `module` that carries a docstring."""
    relative = Path(*module.split("."))
    for root in search:
        for candidate in (root / relative.with_suffix(".py"), root / relative / "__init__.py"):
            if candidate.is_file():
                tree = ast.parse(candidate.read_text(encoding="utf-8"))
                return [(node.name, "class" if isinstance(node, ast.ClassDef) else "function")
                        for node in tree.body
                        if isinstance(node, (ast.FunctionDef, ast.ClassDef))
                        and not node.name.startswith("_") and ast.get_docstring(node)]
    return []


def _html(relative):
    """`reference/pkg.mod` to `reference/pkg.mod.html`: a dotted page name is not a suffix to replace."""
    return relative.parent / (relative.name + ".html")


def slug(title):
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def write_objects_inv(path, objects):
    """A version 2 Sphinx inventory: four plain header lines, then the zlib-compressed entries."""
    header = b"# Sphinx inventory version 2\n# Project: fake\n# Version: \n# The remainder of this file is compressed using zlib.\n"
    lines = "".join("%s %s 1 %s -\n" % (name, role, uri) for name, role, uri in objects)
    Path(path).write_bytes(header + zlib.compress(lines.encode("utf-8")))
