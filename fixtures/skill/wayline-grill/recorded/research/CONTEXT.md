# Context

The vocabulary this project's spec, tickets, and report use verbatim, settled in the grill. `wayline grill term` adds a term or replaces its definition; everything else in this file is kept as written.

## Language

**Gain**:
The with-products AUROC minus the no-products AUROC on split_b, paired within a generator seed and averaged over seeds.
_Avoid_: improvement, lift

**Project venv**:
The project's own virtual environment, which holds scikit-learn and whatever else the experiments import; distinct from the tools venv.
_Avoid_: tools venv

**Tools venv**:
The harness's virtual environment for the PDF converters; the experiments never install into it or import from it.

**Oracle reference**:
A logistic regression given the raw features plus only the planted product x2*x3; it bounds what a product can add and is not a baseline the method must beat.
_Avoid_: oracle baseline

**No-product baseline**:
The logistic regression on the raw features x0..x7 with no interaction terms; the model the gain is measured against.
_Avoid_: linear baseline

**Generator seed**:
The --seed passed to toy/make_synthetic.py; each of the ten draws a fresh set of 20000 rows whose last quarter is that seed's split_b, and every model is compared within it.
_Avoid_: model seed, random state
