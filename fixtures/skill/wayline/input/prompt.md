/wayline

I'm starting a small project from zero. The question is whether adding feature interaction terms improves held-out
AUROC on a synthetic two-class set. The generator and the training code are in `src/toy/`: `generate.py` makes the
data, `train.py` trains on the GPU and writes a summary, and `eval.py` prints `auroc: <value>` from a summary. My three
references are in `materials/`: two short papers as PDFs and an arXiv-style source tarball, whose paper released a small
code repository.

My goal: held-out AUROC of at least 0.82, measured on the held-out split with `src/toy/eval.py`. Beyond the number I
want the real answer: do the interaction terms help, and by how much.

I want it to run on its own overnight once it is set up, and the decider can order the paper at the end. Keep the
radius moderate, fall back to Opus when Fable is spent, and ask me before changing the ladder. Set it up.
