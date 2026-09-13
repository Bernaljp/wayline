"""Word boxes, character boxes, and ruled tables of one PDF, as JSON. Runs inside the tools venv.

The harness imports no third-party package, so it never imports pdfplumber: it runs this script
with the tools venv's Python and reads the JSON it writes. Usage:

    <tools venv>/bin/python pdfplumber_dump.py <pdf> <out.json>

Coordinates are pdfplumber's: points, origin at the top left of the page, `x0, top, x1, bottom`.
A table is what the default `lines` strategy finds, which is a table drawn with rules; a table set
without rules is a converter's job, not this layer's.
"""

import json
import sys

import pdfplumber


def dump(pdf_path):
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            words = [
                [word["text"], round(word["x0"], 2), round(word["top"], 2), round(word["x1"], 2), round(word["bottom"], 2)]
                for word in page.extract_words()
            ]
            chars = [
                [char["text"], round(char["x0"], 2), round(char["top"], 2), round(char["x1"], 2), round(char["bottom"], 2)]
                for char in page.chars
            ]
            tables = []
            for table in page.find_tables():
                tables.append({"bbox": [round(value, 2) for value in table.bbox], "cells": table.extract()})
            pages.append({
                "page": page.page_number,
                "width": round(page.width, 2),
                "height": round(page.height, 2),
                "words": words,
                "chars": chars,
                "tables": tables,
            })
    return {"tool": "pdfplumber", "version": pdfplumber.__version__, "pages": pages}


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: pdfplumber_dump.py <pdf> <out.json>")
    with open(sys.argv[2], "w", encoding="utf-8") as handle:
        json.dump(dump(sys.argv[1]), handle, ensure_ascii=False, separators=(",", ":"))
