"""One PDF through docling, into a directory the harness reads. Runs inside the tools venv.

The harness imports no third-party package, so it never imports docling: it runs this script
with the tools venv's Python and reads what it leaves behind. Usage:

    <tools venv>/bin/python docling_convert.py <pdf> <out dir> [--device auto|cuda|cpu] [--no-formulas]

What lands in `<out dir>`:

- `document.json`, the lossless `DoclingDocument` (typed items with page and bbox provenance);
- `pictures/picture-<n>.png` and `tables/table-<n>.png`, one image per picture and table item, in
  the document's own order, numbered from 1;
- `meta.json`: the docling version, the device that ran, whether formula enrichment ran, the
  seconds the conversion took, and the image files written for each item's `self_ref`.

Formula enrichment runs by default, because an equation without LaTeX is an equation a reader has
to type out; research-notes 06 asks for it on the GPU, and `--device auto` takes the GPU when torch
can see one. The exit code is 0 only when `document.json` was written.
"""

import argparse
import json
import sys
import time
from importlib import metadata
from pathlib import Path


def main(argv):
    parser = argparse.ArgumentParser(prog="docling_convert.py")
    parser.add_argument("pdf")
    parser.add_argument("out")
    parser.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    parser.add_argument("--no-formulas", action="store_true")
    parser.add_argument("--images-scale", type=float, default=2.0)
    options = parser.parse_args(argv)

    from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling_core.types.doc import PictureItem, TableItem

    device = {"auto": AcceleratorDevice.AUTO, "cuda": AcceleratorDevice.CUDA, "cpu": AcceleratorDevice.CPU}[options.device]
    pipeline = PdfPipelineOptions()
    pipeline.do_formula_enrichment = not options.no_formulas
    pipeline.generate_picture_images = True
    pipeline.generate_page_images = True  # what TableItem.get_image() crops a table out of
    pipeline.images_scale = options.images_scale
    pipeline.accelerator_options = AcceleratorOptions(device=device)
    converter = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline)})

    out = Path(options.out)
    (out / "pictures").mkdir(parents=True, exist_ok=True)
    (out / "tables").mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    result = converter.convert(options.pdf)
    document = result.document
    images, counters = {}, {"picture": 0, "table": 0}
    for element, _level in document.iterate_items():
        if isinstance(element, PictureItem):
            kind, folder = "picture", "pictures"
        elif isinstance(element, TableItem):
            kind, folder = "table", "tables"
        else:
            continue
        counters[kind] += 1
        image = element.get_image(document)
        if image is None:
            continue
        name = "%s/%s-%d.png" % (folder, kind, counters[kind])
        image.save(out / name, "PNG")
        images[element.self_ref] = name

    record = _without_embedded_images(document.export_to_dict())
    (out / "document.json").write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    used = _device_used()
    (out / "meta.json").write_text(json.dumps({
        "tool": "docling",
        "version": metadata.version("docling"),
        "docling_core": metadata.version("docling-core"),
        "device": used if options.device == "auto" else options.device,
        "formula_enrichment": pipeline.do_formula_enrichment,
        "seconds": round(time.monotonic() - started, 2),
        "status": str(getattr(result, "status", "")),
        "images": images,
    }, indent=2), encoding="utf-8")
    return 0


def _without_embedded_images(value):
    """The document with every `data:` image URI dropped: the PNGs are files beside it already.

    `export_to_dict` embeds each picture and each page image as base64, which makes a two-page
    paper's JSON a megabyte of pixels the harness never reads out of it.
    """
    if isinstance(value, dict):
        return {key: _without_embedded_images(item) for key, item in value.items()
                if not (key == "uri" and isinstance(item, str) and item.startswith("data:"))}
    if isinstance(value, list):
        return [_without_embedded_images(item) for item in value]
    return value


def _device_used():
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:  # torch is docling's dependency; a broken one still leaves a converted document
        return "unknown"


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
