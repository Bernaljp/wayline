"""One PDF through marker, into a directory the harness reads. Runs inside the tools venv.

Fallback A of research-notes 06: the harness tries marker only when docling failed on a document.
It runs marker's own command line and leaves the same three things docling's helper leaves:

    <tools venv>/bin/python marker_convert.py <pdf> <out dir>

- `document.json`, marker's JSON rendering (a tree of blocks, each with `block_type`, `html`,
  `bbox` in points from the top left, and an `id` of the form `/page/<n>/<type>/<k>`);
- `pictures/picture-<n>.png`, one per `Figure` or `Picture` block that carried an image;
- `meta.json`: the marker version, the seconds it took, and the image file of each block id.

marker 2.0 reads equations and inline math with a VLM behind a local inference server (vLLM on an
NVIDIA GPU); without one its text-layer mode skips equations. The exit code is 0 only when
`document.json` was written.
"""

import base64
import glob
import json
import shutil
import subprocess
import sys
import tempfile
import time
from importlib import metadata
from pathlib import Path


def main(argv):
    if len(argv) != 2:
        sys.exit("usage: marker_convert.py <pdf> <out dir>")
    pdf, out = Path(argv[0]), Path(argv[1])
    (out / "pictures").mkdir(parents=True, exist_ok=True)
    marker = Path(sys.executable).with_name("marker_single")
    scratch = Path(tempfile.mkdtemp(prefix="marker-"))
    started = time.monotonic()
    try:
        done = subprocess.run([str(marker), str(pdf), "--output_format", "json", "--output_dir", str(scratch)], check=False)
        if done.returncode != 0:
            return done.returncode
        found = sorted(glob.glob(str(scratch / "**" / "*.json"), recursive=True))
        documents = [path for path in found if not path.endswith("_meta.json")]
        if not documents:
            print("marker wrote no JSON document", file=sys.stderr)
            return 1
        document = json.loads(Path(documents[0]).read_text(encoding="utf-8"))
        images = {}
        for block in _blocks(document):
            if block.get("block_type") not in ("Figure", "Picture"):
                continue
            for name, data in (block.get("images") or {}).items():
                target = "pictures/picture-%d.png" % (len(images) + 1)
                (out / target).write_bytes(base64.b64decode(data))
                images[block.get("id") or name] = target
                break
            block.pop("images", None)
        (out / "document.json").write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
        (out / "meta.json").write_text(json.dumps({
            "tool": "marker", "version": metadata.version("marker-pdf"),
            "formula_enrichment": True, "seconds": round(time.monotonic() - started, 2), "images": images,
        }, indent=2), encoding="utf-8")
        return 0
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _blocks(block):
    yield block
    for child in block.get("children") or []:
        yield from _blocks(child)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
