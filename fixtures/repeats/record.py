"""Record the embedding model's vectors for the sentences `tests/test_repeats.py` embeds.

Run from the repository root on a machine where `wayline tools install embedding-model` has run:

    python3 fixtures/repeats/record.py [<texts.json>]

It embeds every text of `recorded/texts.json` (or the JSON list named) that `recorded/embeddings.json` does not hold yet,
through the tool runner exactly as `wayline.repeats.embed` runs it live, and adds the vectors to the table. Nothing of
any real project is in either file: the texts are the synthetic start-midway project's and this ticket's supplement's.
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

from wayline import repeats  # noqa: E402

TABLE = HERE / "recorded" / "embeddings.json"
TEXTS = HERE / "recorded" / "texts.json"


def main(source=TEXTS):
    texts = json.loads(Path(source).read_text(encoding="utf-8"))
    table = json.loads(TABLE.read_text(encoding="utf-8")) if TABLE.exists() else {}
    wanted = [text for text in dict.fromkeys(texts) if text not in table]
    if wanted:
        table.update(zip(wanted, repeats.embed(wanted)))
    TABLE.write_text(json.dumps(dict(sorted(table.items())), ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print("%d recorded now, %d in the table" % (len(wanted), len(table)))


if __name__ == "__main__":
    main(*sys.argv[1:])
