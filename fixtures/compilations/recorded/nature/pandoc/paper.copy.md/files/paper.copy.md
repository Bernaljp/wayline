# Noise bends a polynomial fit

Ada Lovelace (Analytical Engine Institute)

## Abstract

We measure how noise bends a polynomial fit, and find that its error grows as the square of the noise.

# Introduction

## State of the art

Polynomial fits are standard^[1](#ref-smith-2020-fits)--[3](#ref-kim-2017-survey)^. Noise is known to bias them^[4](#ref-lee-2018-noise)^. An earlier draft said so. A lost work claimed it first \[to be resolved\], and a late one agreed^[5](#ref-late-work)^. A third said it again.

# Results

## How does noise change the fit?

### The error grows with the noise

The error of the fit follows

$$ e(\sigma) = 0.8\,\sigma^2 + 0.02 \qquad{(1)}$$

and Eq. 1 holds at every noise level we ran, as Fig. 1 shows. Table 1 lists the errors. The fit follows Smith's method^[1](#ref-smith-2020-fits)^.

  noise   rmse
  ------- ------
  0.1     0.03
  0.2     0.05
  0.4     0.15

  : Table 1: The error of the fit at each noise level. {#tbl:T1}

![Figure 1: The error of the fit grows with the noise.](figures/F1.png)

# Discussion

## Limits

The noise model is Gaussian, as Lee assumed^[4](#ref-lee-2018-noise)^. A heavier tail would bend the fit further, and the next runs should try one.

# Methods

## Fitting

We fit by least squares, as Jones did^[2](#ref-jones-2019-least)^.

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

1. Smith, A. & Li, B. Polynomial fits in practice. *Journal of Fits* <https://doi.org/10.5555/smith> (2020) doi:[10.5555/smith](https://doi.org/10.5555/smith).

2. Jones, C. Least squares for curves. *Numerical Notes* <https://doi.org/10.5555/jones> (2019) doi:[10.5555/jones](https://doi.org/10.5555/jones).

3. Kim, F. A survey of fitting. *Fitting Reviews* <https://doi.org/10.5555/kim> (2017) doi:[10.5555/kim](https://doi.org/10.5555/kim).

4. Lee, D. & Hall, E. Noise and bias in fits. *arXiv* Preprint at <https://arxiv.org/abs/1801.00001> (2018).

5. Late, A. A late agreement. *Journal of Tests* <https://doi.org/10.5555/late> (2024) doi:[10.5555/late](https://doi.org/10.5555/late).
