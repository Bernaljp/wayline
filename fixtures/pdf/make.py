"""Rebuild `tiny-paper.pdf` beside this file: a PDF written for the suite, never a paper someone published.

`python3 fixtures/pdf/make.py` writes the LaTeX source and two PNG figures into a temporary
directory, runs `pdflatex` twice (the second run settles the cross-references), and copies the
PDF here together with the source it came from, so the fixture can be read in a diff even though
the PDF cannot. The preamble switches off the creation date, the trailer id, and the pdfTeX info
line, so a rebuild on the same TeX Live is byte for byte the same.

The paper is two-column on purpose: multi-column confusion is one of the failure modes the M3
criterion asks about, and a one-column fixture would never show it. It carries one of every item
the inventory looks for, and `README.md` lists the by-eye counts the tests hold the chain to.

`python3 fixtures/pdf/make.py --record` also refreshes the recorded tool outputs under
`recorded/` from the tools installed on this machine (poppler always, pdfplumber and docling from
the tools venv of `wayline tools install` when it exists), which is what the suite replays on a
machine that has none of them.
"""

import os
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent

PAPER = r"""\documentclass[twocolumn]{article}
\pdfinfoomitdate=1
\pdftrailerid{}
\pdfsuppressptexinfo=-1
\usepackage{graphicx}
\usepackage{amsmath}
\usepackage{amsthm}
\usepackage{algorithm}
\usepackage{algorithmic}
\newtheorem{theorem}{Theorem}
\newtheorem{lemma}{Lemma}
\title{A tiny two-column paper, written for the PDF inventory}
\author{The Wayline Suite}
\date{}
\begin{document}
\maketitle

\begin{abstract}
This paper exists so that a PDF inventory has something to count. It has two columns,
three numbered equations, two figures, one ruled table, one algorithm, a theorem, a lemma,
an appendix, and two references.
\end{abstract}

\section{Introduction}
A tiny paper needs a tiny introduction. The method of Section~\ref{sec:method} is one
line, and Figure~\ref{fig:signal} shows it doing nothing in particular. Earlier work on
nothing includes Knuth~\cite{knuth1984} and Lamport~\cite{lamport1994}.

\subsection{Scope}
Nothing at all is in scope, which is the point. The two columns of this page are there to
see whether a converter reads the left column to the bottom before it starts on the right.

\section{Method}
\label{sec:method}
The method is one numbered equation,
\begin{equation}
  y = m x + b ,
  \label{eq:line}
\end{equation}
followed by a display that carries no number,
\[
  \int_0^1 x^2 \, dx = \frac{1}{3} ,
\]
and an aligned pair that is numbered twice:
\begin{align}
  a &= \sum_{i=1}^{n} b_i , \label{eq:sum} \\
  c &= \sqrt{a^2 + d^2} . \label{eq:root}
\end{align}

\begin{theorem}[Tininess]
\label{thm:tiny}
Every tiny paper is tiny.
\end{theorem}

\begin{proof}
By inspection of this page.
\end{proof}

\begin{lemma}
\label{lem:tinier}
Some tiny papers are tinier than others.
\end{lemma}

\begin{algorithm}
\caption{Do nothing, carefully}
\label{alg:nothing}
\begin{algorithmic}
\STATE $x \gets 0$
\FOR{$i = 1$ to $n$}
  \STATE $x \gets x + 0$
\ENDFOR
\RETURN $x$
\end{algorithmic}
\end{algorithm}

\section{Results}
Table~\ref{tab:numbers} lists the numbers the method produced, and
Figure~\ref{fig:panels} puts them side by side.

\begin{figure}
  \centering
  \includegraphics[width=0.9\columnwidth]{signal.png}
  \caption{A signal that rises from left to right and means nothing.}
  \label{fig:signal}
\end{figure}

\begin{table}
  \centering
  \caption{Numbers the method produced.}
  \label{tab:numbers}
  \begin{tabular}{|l|r|r|}
    \hline
    Run & Input & Output \\
    \hline
    first & 1 & 0 \\
    second & 2 & 0 \\
    third & 3 & 0 \\
    \hline
  \end{tabular}
\end{table}

\begin{figure*}
  \centering
  \includegraphics[width=0.8\textwidth]{panels.png}
  \caption{Two panels that span both columns, so the caption sits under the whole page width.}
  \label{fig:panels}
\end{figure*}

\appendix
\section{Proof of the lemma}
\label{app:proof}
The proof of Lemma~\ref{lem:tinier} is left to the reader, who is the point of the inventory.

\begin{thebibliography}{2}
\bibitem{knuth1984} D. E. Knuth. The \TeX book. Addison-Wesley, 1984.
\bibitem{lamport1994} L. Lamport. \LaTeX: A Document Preparation System. Addison-Wesley, 1994.
\end{thebibliography}
\end{document}
"""


def png(width, height, pixel):
    """A valid RGB PNG built without a library; `pixel(x, y)` returns an `(r, g, b)` triple."""
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        for x in range(width):
            raw.extend(pixel(x, y))

    def chunk(kind, payload):
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b"")


def signal(x, y):
    """A rising diagonal band on white, so the picture has structure a layout model can see."""
    height, width = 180, 320
    line = height - 1 - int(x * (height - 1) / (width - 1))
    if abs(y - line) < 6:
        return (0x2A, 0x6F, 0xB0)
    if y == height - 1 or x == 0:
        return (0x20, 0x20, 0x20)
    return (0xFF, 0xFF, 0xFF)


def panels(x, y):
    """Two filled panels with a white gutter between them."""
    if 300 <= x < 340:
        return (0xFF, 0xFF, 0xFF)
    if x < 300:
        return (0xB0, 0x3A, 0x2E) if (x // 30 + y // 30) % 2 == 0 else (0xF2, 0xD7, 0xD0)
    return (0x2E, 0x7D, 0x32) if y > 200 - x // 3 else (0xD8, 0xEE, 0xD9)


def build():
    if not shutil.which("pdflatex"):
        sys.exit("pdflatex is not installed; the fixture cannot be rebuilt on this machine")
    workspace = Path(tempfile.mkdtemp(prefix="wayline-pdf-fixture-"))
    try:
        (workspace / "tiny-paper.tex").write_text(PAPER, encoding="utf-8")
        (workspace / "signal.png").write_bytes(png(320, 180, signal))
        (workspace / "panels.png").write_bytes(png(640, 200, panels))
        env = dict(os.environ, SOURCE_DATE_EPOCH="1700000000", FORCE_SOURCE_DATE="1")
        for _ in range(2):
            done = subprocess.run(
                ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "tiny-paper.tex"],
                cwd=str(workspace), capture_output=True, env=env,
            )
            if done.returncode != 0:
                sys.exit(done.stdout.decode("utf-8", errors="replace")[-2000:])
        shutil.copyfile(workspace / "tiny-paper.pdf", HERE / "tiny-paper.pdf")
        shutil.copyfile(workspace / "tiny-paper.tex", HERE / "tiny-paper.tex")
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
    path = HERE / "tiny-paper.pdf"
    print(path.name, path.stat().st_size, "bytes")


if __name__ == "__main__":
    build()
    if "--record" in sys.argv[1:]:
        sys.path.insert(0, str(HERE.parent.parent))
        from wayline.pdf_inventory import record_tool_outputs

        for line in record_tool_outputs(HERE / "tiny-paper.pdf", HERE / "recorded"):
            print(line)
