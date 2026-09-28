# A results section with math

$$\newcommand{\norm}[1]{\left\lVert #1 \right\rVert}$$

A name KaTeX predefines and LaTeX does not, defined by the document: $\newcommand{\R}{\mathbb{R}}$ and used: $x \in \R^n$.

Inline dollars with underscores and stars: $x_i^* = \arg\min_{x} f(x_1, x_2)$ and $a^*b^*$ and $\{x_i\}_{i=1}^n$.
Parenthesis delimiters: \(\mathbf{W}^\top \boldsymbol{\mu} \in \R^{d}\) and a thin space \(a\,b\;c\!d\).
A user macro from the first block: $\norm{\hat{\theta} - \theta^*}_2 \le \varepsilon$.
A price that is not math: it cost $5 and then $10 more.
Code is not math: `echo $HOME and $PATH` and `$x_1$`.

A display with brackets:

\[
  \mathcal{L}(\theta) = \frac{1}{N}\sum_{n=1}^{N} \ell\big(y_n, f_\theta(x_n)\big) + \lambda \norm{\theta}_2^2
\]

An aligned block whose second line starts with a plus sign:

$$
\begin{align}
  p(z \mid x) &= \frac{p(x \mid z)\,p(z)}{p(x)} \label{eq:bayes} \\
  + \log p(x) &\ge \mathbb{E}_{q}\left[\log p(x, z) - \log q(z)\right] \tag{ELBO}
\end{align}
$$

By Bayes' rule \eqref{eq:bayes}, and \ref{eq:bayes} again.

$$
\begin{equation}
  \mathbf{y} = \mathbf{X}\boldsymbol{\beta} + \boldsymbol{\epsilon}, \quad \boldsymbol{\epsilon} \sim \mathcal{N}(0, \sigma^2 \mathbf{I})
\end{equation}
$$

\begin{gather}
  a = b \\
  c = d
\end{gather}

| quantity | value |
|---|---|
| loss | $\mathcal{L} = 0.31$ |
| norm | $\lvert x \rvert = 2$ |

```python
cost = "$5"  # $x_1$ inside a fence stays code
```

## Injection attempts

Each attempt stands in a block of its own, so marked reads each as it would alone.

<script>window.__pwned = 'script'</script>

<img src="x" onerror="window.__pwned = 'img'">

<a href="javascript:window.__pwned='link'">a raw link</a>

A [markdown link](javascript:window.__pwned='md') in a paragraph.

<iframe src="https://example.com"></iframe>

<svg><script>window.__pwned='svg'</script></svg>

<math><mtext><table><mglyph><style><img src=x onerror="window.__pwned='mxss'"></style></mglyph></table></mtext></math>

Math that tries to escape: $x</span><img src=x onerror="window.__pwned='tex'">$ and $\href{javascript:window.__pwned='href'}{click}$ and $\url{javascript:alert(1)}$.
HTML extension commands: $\htmlClass{evil}{x}$ $\htmlStyle{background:url(https://example.com/x.png)}{y}$ $\htmlData{onclick=alert(1)}{z}$ $\includegraphics{https://example.com/x.png}$.
A color that tries to break out: $\color{red" onmouseover="window.__pwned='color'}{w}$.
An error path: $\frac{<img src=x onerror="window.__pwned='err'">$ and an unknown command $\undefinedcommand{x}$.
A macro loop: $\def\a{\a}\a$ and a huge rule $\rule{9999em}{9999em}$.
