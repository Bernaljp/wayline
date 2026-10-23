# Noise bends a polynomial fit

Ada Lovelace (Analytical Engine Institute)

## Abstract

We measure how noise bends a polynomial fit, and find that its error grows as the square of the noise.

# Introduction

## State of the art

Polynomial fits are standard ([Smith and Li 2020](#ref-smith-2020-fits); [Jones 2019](#ref-jones-2019-least)). Noise is known to bias them ([Lee and Hall 2018](#ref-lee-2018-noise)). An earlier draft said so.

# Results

## How does noise change the fit?

### The error grows with the noise

The error of the fit follows

$$ e(\sigma) = 0.8\,\sigma^2 + 0.02 \qquad{(1)}$$

and Eq. 1 holds at every noise level we ran, as Fig. 1 shows. Table 1 lists the errors. The fit follows Smith's method ([Smith and Li 2020](#ref-smith-2020-fits)).

  noise   rmse
  ------- ------
  0.1     0.03
  0.2     0.05
  0.4     0.15

  : Table 1: The error of the fit at each noise level. {#tbl:T1}

![Figure 1: The error of the fit grows with the noise.](figures/F1.png)

# Discussion

## Limits

The noise model is Gaussian, as Lee assumed ([Lee and Hall 2018](#ref-lee-2018-noise)).

# Methods

## Fitting

We fit by least squares, as Jones did ([Jones 2019](#ref-jones-2019-least)).

# Acknowledgments

\[TO BE GIVEN: acknowledgments\]

# Funding

\[TO BE GIVEN: funding\]

# Competing interests

The authors declare none.

# Data availability

The data are synthetic and the project's runs made them.

# Code availability

\[TO BE GIVEN: the code repository, which setup has not settled\]

# References

Jones, Cy. 2019. "Least Squares for Curves." *Numerical Notes*, ahead of print. <https://doi.org/10.5555/jones>.

Late, Ada. 2024. "A Late Agreement." *Journal of Tests*, ahead of print. <https://doi.org/10.5555/late>.

Lee, Di, and Ed Hall. 2018. "Noise and Bias in Fits." In *arXiv*. Preprint. <https://arxiv.org/abs/1801.00001>.

Smith, Ann, and Bo Li. 2020. "Polynomial Fits in Practice." *Journal of Fits*, ahead of print. <https://doi.org/10.5555/smith>.

# Supplementary information

## Earlier claims

A lost work claimed it first \[to be resolved\], and a late one agreed ([Late 2024](#ref-late-work)). A third said it again. A heavier tail would bend the fit further, and the next runs should try one.
