"""Sentence embeddings from the harness's embedding model, as JSON. Runs inside the tools venv.

The harness imports no third-party package, so it never imports torch or transformers: it runs
this script with the interpreter the `embedding-model` entry of `tools.json` names
(`wayline tools run embedding-model -- embed.py <model folder> <texts.json>`) and reads the JSON it
prints. Usage:

    <tools venv>/bin/python embed.py <model folder> <texts.json>

`texts.json` is a JSON list of strings. What it prints is `{"model": <folder name>, "vectors":
[[...], ...]}`, one unit-length vector per text, in order, each component rounded to five places:
BAAI/bge-base-en-v1.5's CLS pooling, normalized, as its sentence-transformers config gives it, so
the cosine of two texts is the dot product of their vectors. Nothing is judged here: which pairs
are near enough to be a repeat is the harness's (`wayline/repeats.py`).
"""

import json
import sys
from pathlib import Path

import torch
from transformers import AutoModel, AutoTokenizer

BATCH = 32
MAX_TOKENS = 512


def main(folder, texts_path):
    texts = json.loads(Path(texts_path).read_text(encoding="utf-8"))
    if not isinstance(texts, list) or not all(isinstance(text, str) for text in texts):
        print("embed.py: %s is not a JSON list of strings" % texts_path, file=sys.stderr)
        return 2
    tokenizer = AutoTokenizer.from_pretrained(folder, local_files_only=True)
    model = AutoModel.from_pretrained(folder, local_files_only=True)
    model.eval()
    vectors = []
    with torch.no_grad():
        for start in range(0, len(texts), BATCH):
            encoded = tokenizer(texts[start:start + BATCH], padding=True, truncation=True, max_length=MAX_TOKENS,
                                return_tensors="pt")
            cls = model(**encoded).last_hidden_state[:, 0]
            cls = torch.nn.functional.normalize(cls, p=2, dim=1)
            vectors.extend([round(float(value), 5) for value in row] for row in cls.tolist())
    print(json.dumps({"model": Path(folder).name, "vectors": vectors}))
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv[1], sys.argv[2]))
