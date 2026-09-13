"""Remake `inventory.json` and `figures/fig-1.png` for the absorb fixture from `source/flat.tex`.

Run from the harness root: `python fixtures/absorb/make.py`. The inventory is what the harness's
own LaTeX chain reads out of the flattened source, so its locators are the ones a live absorb
would chunk by; only the figure's image file is filled in by hand, because there is no tarball
to rasterize it from.
"""

import json
import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent.parent))

from wayline.dossier import latex_inventory  # noqa: E402
from wayline.jsonschema import check, load_schema  # noqa: E402

SLUG = "suite-2026-tiny-absorb-paper"
CREATED = "2026-09-13T12:00:00.000Z"
BUCKETS = ("sections", "equations", "figures", "tables", "algorithms", "theorems", "appendices", "references")


def png(width, height):
    """A white RGB image, small enough to commit and real enough for a reader to open."""
    raw = b"".join(b"\x00" + bytes([255, 255, 255] * width) for _ in range(height))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def main():
    text = (ROOT / "source" / "flat.tex").read_text(encoding="utf-8")
    record = latex_inventory(text)
    (ROOT / "figures").mkdir(exist_ok=True)
    (ROOT / "figures" / "fig-1.png").write_bytes(png(8, 8))
    for figure in record["figures"]:
        figure["file"] = "figures/fig-1.png"
    inventory = {
        "schema_version": 1, "slug": SLUG, "source_type": "latex",
        "source": {
            "kind": "tarball", "url": "https://export.arxiv.org/src/2609.00001", "arxiv_id": "2609.00001",
            "version": "v1", "etag": None, "fetched": CREATED, "from_cache": False, "bytes": None, "files": 1,
            "main": "flat.tex", "flattened_by": "wayline", "compiled": False,
        },
        "provenance": {name: "latex" for name in BUCKETS + ("metadata", "raw_images", "text_layer")},
        "counts": record["counts"], "environments": record["environments"], "page_count": None,
        "text_layer": {"path": "source/flat.tex", "chars": len(text), "provenance": "latex"},
        **{name: record[name] for name in BUCKETS},
        "raw_images": [], "metadata": record["metadata"], "notes": [], "created": CREATED,
    }
    check(inventory, load_schema("inventory"), name="fixtures/absorb/inventory.json")
    (ROOT / "inventory.json").write_text(json.dumps(inventory, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for name in BUCKETS[:-1]:
        for item in inventory[name]:
            print("%-10s %-6s %-14s %s" % (name, item["id"], item["locator"], item.get("title") or item.get("caption") or ""))


if __name__ == "__main__":
    main()
