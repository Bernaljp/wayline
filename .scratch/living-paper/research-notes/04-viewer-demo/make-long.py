"""Write long.md beside this file: 150 results, each a paragraph with five inline formulas and a
numbered two-row align, for the scrolling and timing checks (1,051 formulas, about 60 KB)."""
from pathlib import Path

parts = ["$$\\newcommand{\\norm}[1]{\\left\\lVert #1 \\right\\rVert}$$\n", "# A long report\n"]
for i in range(1, 151):
    parts.append(f"## Result {i}\n")
    parts.append(
        f"The estimate $\\hat{{\\theta}}_{{{i}}}$ of $\\theta^*$ satisfies $\\norm{{\\hat{{\\theta}}_{{{i}}} - \\theta^*}}_2 \\le C/\\sqrt{{n}}$, "
        f"with $n = {i * 100}$ samples and $\\sigma^2 = {i / 10:.1f}$; the loss is $\\mathcal{{L}}_{{{i}}}(\\theta) = \\mathbb{{E}}[\\ell(y, f_\\theta(x))]$.\n"
    )
    parts.append(
        "$$\n\\begin{align}\n  a_{%d} &= \\sum_{k=1}^{K} w_k \\, x_k^{(%d)} \\\\\n  b_{%d} &= \\frac{1}{K} \\sum_{k=1}^{K} \\left( x_k - \\bar{x} \\right)^2\n\\end{align}\n$$\n"
        % (i, i, i)
    )
(Path(__file__).resolve().parent / "long.md").write_text("\n".join(parts))
