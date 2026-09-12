# A sample Markdown draft for the guidelines checks

This file is a fixture, not a paper. It exists so the seven mechanical checks of Implementation
Decisions 13 have a draft to run on, and it is written to trip some of them on purpose: it names
an animal study, so a venue that requires ARRIVE asks for it, and one of its two figures is a
72 dpi PNG, so a venue that wants 300 dpi TIFF or EPS says so.

## Abstract

We measure how a harness that writes its own checks behaves when the checks are pointed at a
draft of its own making. The result is a sample manuscript that passes some venues and fails
others, which is the point of a fixture.

## Author summary

A short plain-language summary, present so the section check can find it.

## Introduction

Reporting guidelines differ by venue, and a writer cannot hold fifteen of them in mind at once [1]
{ref:plos-guidelines#introduction}. The mechanical half of that burden is a word count, a section
list, a figure specification and a citation style, all of which a machine can check [2].

## Results

The pipeline recovered the expected signal in every held-out split {res:t52-a1/metrics.json#auroc}.
Single-cell RNA-seq of the treated mice showed no change in the two control clusters, which is a
negative result and carries its own tag {res:t52-a1/clusters.csv#row12}.

![A grey square standing in for a real panel](figures/fig1.tif)

Figure 1. The anchor result, drawn at 300 dpi as a TIFF so that a venue asking for either is
satisfied.

![A second grey square](figures/fig2.png)

Figure 2. A deliberately wrong figure: a 72 dpi PNG, which fails a venue that asks for 300 dpi
TIFF or EPS and passes one that asks for nothing.

## Discussion

Nothing here should be read as a finding about anything but the checks themselves.

## Materials and Methods

All animal experiments followed the local protocol. Mice were housed in groups of four and
sequencing libraries were prepared from bulk tissue. Custom code is available in the repository.

## Acknowledgments

No one is thanked for a fixture.

## References

1. Sample A, Sample B. A sample reference that exists only to be counted. J Fixtures. 2026.
2. Sample C. A second sample reference, numbered in citation order. J Fixtures. 2026.

## Supporting Information captions

S1 Table. The counts behind Figure 1.
