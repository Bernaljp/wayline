"""One PDF through MinerU's pipeline backend, into a directory the harness reads. Runs inside the tools venv.

Fallback B of research-notes 06: the harness tries MinerU only when docling and marker both failed
on a document (or are not installed). It runs MinerU's own command line and leaves:

    <tools venv>/bin/python mineru_convert.py <pdf> <out dir>

- `document.json`, MinerU's `content_list` (one entry per block in reading order: `type` of
  `text`, `image`, `table`, or `equation`, with `text`, `text_level` for a heading, `page_idx`
  from 0, `bbox`, and the captions of an image or a table);
- `pictures/picture-<n>.png` and `tables/table-<n>.png`, copied from the images MinerU cropped;
- `meta.json`: the MinerU version, the seconds it took, and the image file of each entry's index.

The exit code is 0 only when `document.json` was written.
"""

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
        sys.exit("usage: mineru_convert.py <pdf> <out dir>")
    pdf, out = Path(argv[0]), Path(argv[1])
    for folder in ("pictures", "tables"):
        (out / folder).mkdir(parents=True, exist_ok=True)
    mineru = Path(sys.executable).with_name("mineru")
    scratch = Path(tempfile.mkdtemp(prefix="mineru-"))
    started = time.monotonic()
    try:
        done = subprocess.run([str(mineru), "-p", str(pdf), "-o", str(scratch), "-b", "pipeline"], check=False)
        if done.returncode != 0:
            return done.returncode
        lists = sorted(glob.glob(str(scratch / "**" / "*_content_list.json"), recursive=True))
        if not lists:
            print("MinerU wrote no content_list.json", file=sys.stderr)
            return 1
        content_path = Path(lists[0])
        content = json.loads(content_path.read_text(encoding="utf-8"))
        images, counters = {}, {"image": 0, "table": 0}
        for index, entry in enumerate(content):
            kind = entry.get("type")
            if kind not in counters or not entry.get("img_path"):
                continue
            source = content_path.parent / entry["img_path"]
            if not source.is_file():
                continue
            counters[kind] += 1
            target = "%s/%s-%d%s" % ("pictures" if kind == "image" else "tables", "picture" if kind == "image" else "table",
                                     counters[kind], source.suffix.lower() or ".png")
            shutil.copyfile(source, out / target)
            images[str(index)] = target
        (out / "document.json").write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
        (out / "meta.json").write_text(json.dumps({
            "tool": "mineru", "version": metadata.version("mineru"),
            "formula_enrichment": True, "seconds": round(time.monotonic() - started, 2), "images": images,
        }, indent=2), encoding="utf-8")
        return 0
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
