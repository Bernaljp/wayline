"""Rebuild the tarball fixtures beside this file: papers written for the suite, never e-prints.

`python3 fixtures/arxiv/make.py` writes `tiny-paper.tar.gz` and `no-latex.tar.gz` byte for byte
the same on every machine (fixed mtimes, fixed ownership, no gzip timestamp), so a rebuild that
changes nothing shows as no diff. A tarball cannot be edited in place and read in a diff, so the
fixtures are generated from the sources here rather than committed as an opaque blob alone.
"""

import gzip
import io
import struct
import tarfile
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent

MS = r"""\documentclass{article}
\usepackage{graphicx}
\usepackage{amsmath}
\usepackage{float}
\newfloat{algorithm}{tbp}{loa}
\floatname{algorithm}{Algorithm}
\newtheorem{theorem}{Theorem}
\newtheorem{lemma}{Lemma}
\graphicspath{{figures/}}
\title{A tiny paper, written for the inventory}
\author{The Wayline Suite}
\begin{document}
\maketitle
% the sections live in their own files, which is what the flattening is for
\input{sections/intro}
\input{sections/method}
\appendix
\section{Proof of the lemma}
\label{app:proof}
The proof is left as an exercise for the reader. % and this comment is not in flat.tex
\begin{thebibliography}{1}
\bibitem{knuth1984} D. E. Knuth. The \TeX book. Addison-Wesley, 1984.
\end{thebibliography}
\end{document}
"""

INTRO = r"""\section{Introduction}
\label{sec:intro}
A tiny paper needs a tiny introduction, and this is one. See Figure~\ref{fig:plot}.

\begin{figure}
  \includegraphics[width=0.4\textwidth]{plot}
  \caption{A plot of nothing against nothing.}
  \label{fig:plot}
\end{figure}

\subsection{What is not in this paper}
Nothing at all, which is the point.
"""

METHOD = r"""\section{Method}
\label{sec:method}
The method is one numbered equation,
\begin{equation}
  y = m x + b
  \label{eq:line}
\end{equation}
one that is not numbered,
\begin{align*}
  y &= m x + b \\
  0 &= 0
\end{align*}
and one aligned pair that is numbered twice:
\begin{align}
  a &= b \label{eq:first} \\
  c &= d \label{eq:second}
\end{align}
Equation~\eqref{eq:line} is the one that matters.

\begin{table}
  \caption{One column of numbers and one of letters.}
  \label{tab:numbers}
  \begin{tabular}{ll}
    a & 1 \\
    b & 2 \\
  \end{tabular}
\end{table}

\begin{figure*}
  \includegraphics[width=\textwidth]{diagram.pdf}
  \caption{A diagram that ships as a PDF, so an inventory has to rasterize it.}
  \label{fig:diagram}
\end{figure*}

\begin{algorithm}
  \caption{Do nothing, carefully.}
  \label{alg:nothing}
  Do nothing, and then stop.
\end{algorithm}

\begin{theorem}[Tininess]
  \label{thm:tiny}
  Every tiny paper is tiny.
\end{theorem}

\begin{lemma}
  \label{lem:tinier}
  Some tiny papers are tinier.
\end{lemma}
"""

README = """{
  "process": {"compiler": "pdflatex"},
  "sources": [
    {"filename": "ms.tex", "usage": "toplevelfile"},
    {"filename": "sections/intro.tex", "usage": "include"},
    {"filename": "sections/method.tex", "usage": "include"}
  ]
}
"""


def png(width=8, height=8, colour=(0x2a, 0x6f, 0xb0)):
    """A small valid PNG: one solid colour, no library."""
    raw = b""
    for _ in range(height):
        raw += b"\x00" + bytes(colour) * width

    def chunk(kind, payload):
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def pdf():
    """A one-page PDF with a drawn rectangle, with a correct cross-reference table."""
    content = b"1 0 0 RG 0.15 0.42 0.69 rg 20 20 160 100 re f\n"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 140] /Contents 4 0 R /Resources << >> >>",
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"endstream",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for index, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % index + body + b"\nendobj\n")
    start = out.tell()
    out.write(b"xref\n0 %d\n" % (len(objects) + 1))
    out.write(b"0000000000 65535 f \n")
    for offset in offsets:
        out.write(b"%010d 00000 n \n" % offset)
    out.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, start))
    return out.getvalue()


FILES = {
    "00README.json": README.encode("utf-8"),
    "ms.tex": MS.encode("utf-8"),
    "sections/intro.tex": INTRO.encode("utf-8"),
    "sections/method.tex": METHOD.encode("utf-8"),
    "figures/plot.png": png(),
    "figures/diagram.pdf": pdf(),
}

NO_TEX = {
    "00README.XXX": b"notes.txt toplevelfile\n",
    "notes.txt": b"This submission carries no LaTeX at all.\n",
    "figures/plot.png": png(6, 6, (0x88, 0x22, 0x22)),
}


def write_tarball(target, files):
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as archive:
        for name, payload in sorted(files.items()):
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            info.mtime = 1700000000
            info.mode = 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            archive.addfile(info, io.BytesIO(payload))
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "wb") as handle:
        with gzip.GzipFile(fileobj=handle, mode="wb", mtime=0) as zipped:
            zipped.write(raw.getvalue())
    return target


for name, files in (("tiny-paper.tar.gz", FILES), ("no-latex.tar.gz", NO_TEX)):
    path = write_tarball(HERE / name, files)
    print(path.name, path.stat().st_size, "bytes")
