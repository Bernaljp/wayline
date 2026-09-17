# 03 - How older model versions compare in quality to their neighbours

Research ticket: [How older model versions compare in quality to their neighbours](https://github.com/Bernaljp/wayline/issues/132), child of [Map: finer difficulty tiers using more model versions](https://github.com/Bernaljp/wayline/issues/129).
Written 2026-09-17 from published sources only. No model probes were run. A sibling ticket covers which versions the subscription actually serves; this note covers quality.

## Question

Is each older model version reliably weaker than its family's newest version and stronger than the next family down, or only different?

## Short answer

Within a family, yes: every published within-family comparison puts the newer version ahead, and Anthropic's own framing is that one version step is worth about the whole effort range ("At minimum effort, Opus 4.8 matches the peak performance of Opus 4.7 at maximum effort", [Opus 4.8 system card, section 8.2](https://www-cdn.anthropic.com/0f0c97ad20d8005706296bd92aa1c27c6b2f4f61/Claude%20Opus%204.8%20System%20Card.pdf)).

Across families, no. Two candidate rungs do not behave:

- **Opus 4.8 against Sonnet 5** is a clear step up on coding and tool use but a tie or a loss on knowledge work.
- **Fable 5 against Opus 5** is the bad case: Fable 5 loses to Opus 5 on almost every shared benchmark while costing twice as much per token. It is out of order as a rung, not a cheap step below Fable 5.1.

The cheap finer-grained dial is not older versions at all. It is the effort parameter, which Claude Code already exposes as `claude --effort <level>` (from `claude --help`, Claude Code 2.1.274), and which Anthropic reports in five settings (low, medium, high, xhigh, max).

## Sources and how the numbers were taken

Primary sources are Anthropic's system cards (PDF) and launch posts. Every card states its standard configuration as **adaptive thinking at max effort, default sampling, averaged over five trials**, unless a row says otherwise. Announcement charts are published as images, so per-effort curves are described in the cards' prose rather than transcribed here.

- [Claude Fable 5.1 and Mythos 5.1 system card](https://www-cdn.anthropic.com/0339e6a7c5c7b87f5c07798616dc32c215d14235/Claude%20Fable%205.1%20&%20Claude%20Mythos%205.1%20System%20Card.pdf), table 8.1.A and sections 8.2 to 8.16 (September 1, 2026). Announcement: [Introducing Claude Fable 5.1 and Claude Mythos 5.1](https://www.anthropic.com/claude-fable-and-mythos-5-1).
- [Claude Opus 5 system card](https://www-cdn.anthropic.com/ceaf5c7ff2783855203fde8208ec311252dced5b/Claude%20Opus%205%20System%20Card.pdf), table 8.1.A and sections 8.2 to 8.14 (July 24, 2026). Announcement: [Introducing Claude Opus 5](https://www.anthropic.com/news/claude-opus-5).
- [Claude Fable 5 and Mythos 5 system card](https://www-cdn.anthropic.com/57a52ea7d8f0e54e8a542e908266086df425cdf5/Claude%20Fable%205%20&%20Claude%20Mythos%205%20System%20Card.pdf), table 8.1.A (June 9, 2026). Announcement: [Introducing Claude Fable 5 and Claude Mythos 5](https://www.anthropic.com/news/claude-fable-5-mythos-5). Availability history: [Redeploying Claude Fable 5](https://www.anthropic.com/news/redeploying-fable-5).
- [Claude Sonnet 5 system card](https://www-cdn.anthropic.com/283ef97c476cf442c91d9a37d5b214242a55bb92/Claude%20Sonnet%205%20System%20Card.pdf), table 8.1.A and section 8.2 (June 30, 2026). Announcement: [Introducing Claude Sonnet 5](https://www.anthropic.com/news/claude-sonnet-5).
- [Claude Opus 4.8 system card](https://www-cdn.anthropic.com/0f0c97ad20d8005706296bd92aa1c27c6b2f4f61/Claude%20Opus%204.8%20System%20Card.pdf), table 8.1.A and section 8.2 (May 28, 2026). Announcement: [Introducing Claude Opus 4.8](https://www.anthropic.com/news/claude-opus-4-8).
- [Introducing Claude Haiku 4.5](https://www.anthropic.com/news/claude-haiku-4-5) (October 2025).
- [Introducing Claude Sonnet 4.6](https://www.anthropic.com/news/claude-sonnet-4-6) (February 17, 2026) and [Claude Opus 4.6](https://www.anthropic.com/news/claude-opus-4-6) (February 5, 2026).

## Side by side, same benchmark where possible

### A. SWE-bench, the only measure that spans every candidate

| Version | SWE-bench Verified | SWE-bench Pro | Source |
| --- | --- | --- | --- |
| Haiku 4.5 | 73.3% (50 trials, no test-time compute, 128K thinking budget) | not published | [Haiku 4.5 announcement](https://www.anthropic.com/news/claude-haiku-4-5) |
| Sonnet 4.6 | 80.2% with a prompt modification; the plain score is given only in a footnote chart | not published at launch | [Sonnet 4.6 announcement](https://www.anthropic.com/news/claude-sonnet-4-6) |
| Sonnet 5 | 85.2% | 63.2 | [Sonnet 5 card, 8.1 and 8.2](https://www-cdn.anthropic.com/283ef97c476cf442c91d9a37d5b214242a55bb92/Claude%20Sonnet%205%20System%20Card.pdf) |
| Opus 4.7 | 87.6% | 64.3 | [Opus 4.8 card, 8.1](https://www-cdn.anthropic.com/0f0c97ad20d8005706296bd92aa1c27c6b2f4f61/Claude%20Opus%204.8%20System%20Card.pdf) |
| Opus 4.8 | 88.6% | 69.2 | [Opus 4.8 card, 8.1](https://www-cdn.anthropic.com/0f0c97ad20d8005706296bd92aa1c27c6b2f4f61/Claude%20Opus%204.8%20System%20Card.pdf) |
| Fable 5 | 95.0% | 80 (80.3 for Mythos 5) | [Fable 5 card, 8.1](https://www-cdn.anthropic.com/57a52ea7d8f0e54e8a542e908266086df425cdf5/Claude%20Fable%205%20&%20Claude%20Mythos%205%20System%20Card.pdf) |
| Opus 5 | 96.0% | 79.2 | [Opus 5 card, 8.1 and 8.2](https://www-cdn.anthropic.com/ceaf5c7ff2783855203fde8208ec311252dced5b/Claude%20Opus%205%20System%20Card.pdf) |
| Fable 5.1 | **not published** | 81.2 | [Fable 5.1 card, 8.1 and 8.2](https://www-cdn.anthropic.com/0339e6a7c5c7b87f5c07798616dc32c215d14235/Claude%20Fable%205.1%20&%20Claude%20Mythos%205.1%20System%20Card.pdf) |

Missing data, stated plainly: Anthropic dropped SWE-bench Verified from the Fable 5.1 card and reports only Pro, Multilingual, and Multimodal there. Haiku 4.5 and Sonnet 4.6 predate every other benchmark in the 5-series cards, so SWE-bench Verified is the only number they share with the rest, and even that is taken under different harnesses and trial counts.

### B. The three newest versions plus Opus 4.8 and Sonnet 5, on the 5-series benchmark set

All rows below are at max effort unless noted.

| Benchmark | Fable 5.1 | Opus 5 | Fable 5 | Opus 4.8 | Sonnet 5 |
| --- | --- | --- | --- | --- | --- |
| SWE-bench Pro | 81.2 | 79.2 | 80 | 69.2 | 63.2 |
| SWE-bench Multilingual | 89.1 | 89.5 | 86.6 | 84.4 | not published |
| SWE-bench Multimodal | 54.7 | 59.4 | 54.1 | 38.4 | not published |
| Terminal-Bench 4.0 | 55.8% | 52.3% | 42.0% | not published | not published |
| Terminal-Bench-Science 0.1 | 52.6% | 29.0% | 24.7% | not published | not published |
| Terminal-Bench 2.1 | not published | not published | 84.3 | 74.6 in its own card, restated 82.7 twelve days later | 80.4 |
| HLE, no tools | 60.9% | 56.6% (56.3 in the Opus 5 card) | 57.8% (56.5 in the Opus 5 card) | 49.8 | 43.2 |
| HLE, with tools | 65.0% | 63.6% (64.7 in the Opus 5 card) | 63.8% (63.9 in the Opus 5 card) | 57.9 | 57.4 |
| OSWorld 2.0, partial/strict | 77.9 / 41.7 | 75.4 / 39.6 (70.6 under the Opus 5 card's grading) | 72.9 / 36.1 (66.1 under the Opus 5 card's grading) | 55.7 on OSWorld 2.0; 83.4 on the older OSWorld-Verified | 81.2 on OSWorld-Verified |
| GDPval-AA v2 (Elo) | 1853 | 1824 (1861 in the Opus 5 card) | 1723 (1747 in the Opus 5 card) | 1593 in the Opus 5 card; 1890 on GDPval-AA v1 in its own card | 1618 |
| AA-Briefcase (Elo) | 1694 | 1685 (1720 in the Opus 5 card) | 1572 (1574 in the Opus 5 card) | 1346 | not published |
| AutomationBench | 31.4 | 26.9 (26.0 in the Opus 5 card) | 17.1 (17.4 in the Opus 5 card) | 15.5 to 17.0 depending on card | 13.5 |
| Toolathlon Verified, Pass@1 | 77.8 | 80.6 | 79.3 for Mythos 5 | 79.9 | 74.7 |
| ProgramBench (long context) | 87.6% | 85.4% | 86.3% | 80% after the first episode | not published |
| CursorBench 3.2.0 | 73.4% | 70.0% | 70.5% | not published | not published |
| ARC-AGI-1 | 97.5% | 97.5 | 98.5% | 92.5 | not published |
| ARC-AGI-2 | 90.0% | 90.42 | 89.2% | 72.1 | not published |
| ARC-AGI-3 | not available at release | 30.2 (high effort) | not published | 1.5 | not published |
| HealthBench Professional | 62.1% | 59.8% | 63.3% (66.0 for Mythos 5) | 57.4 to 56.9 depending on card | 57.8 |
| FrontierBench v0.1 | not published | 43.3 | 33.8 (33.7 at max effort in section 8.5) | 21.1 | not published |
| FrontierSWE v2 (0 to 1) | 0.57 | 0.52 | 0.48 | not published | not published |
| BrowseComp | not published | 90.8 | 88.0 for Mythos 5 | 84.3 single agent, 88.5 multi agent | 84.7 single agent, 86.6 multi agent |

Rows are read from table 8.1.A of the [Fable 5.1 card](https://www-cdn.anthropic.com/0339e6a7c5c7b87f5c07798616dc32c215d14235/Claude%20Fable%205.1%20&%20Claude%20Mythos%205.1%20System%20Card.pdf), table 8.1.A of the [Opus 5 card](https://www-cdn.anthropic.com/ceaf5c7ff2783855203fde8208ec311252dced5b/Claude%20Opus%205%20System%20Card.pdf), table 8.1.A of the [Fable 5 card](https://www-cdn.anthropic.com/57a52ea7d8f0e54e8a542e908266086df425cdf5/Claude%20Fable%205%20&%20Claude%20Mythos%205%20System%20Card.pdf), table 8.1.A of the [Opus 4.8 card](https://www-cdn.anthropic.com/0f0c97ad20d8005706296bd92aa1c27c6b2f4f61/Claude%20Opus%204.8%20System%20Card.pdf), and table 8.1.A of the [Sonnet 5 card](https://www-cdn.anthropic.com/283ef97c476cf442c91d9a37d5b214242a55bb92/Claude%20Sonnet%205%20System%20Card.pdf). Toolathlon figures are table 8.15.5.A of the Fable 5.1 card; ProgramBench is section 8.11.1 there and section 8.9.1 of the Opus 5 card; Terminal-Bench 4.0 is section 8.6 of the Fable 5.1 card; CursorBench is section 8.8 there; FrontierSWE v2 is section 8.5 there; AA-Briefcase and GDPval-AA v2 are sections 8.15.3 and 8.15.4 there.

**Where a version is measured twice, the two numbers differ.** The same model's OSWorld 2.0, GDPval-AA v2, and Terminal-Bench 2.1 scores move between cards because the grader, the tool stack, or the harness changed. The Fable 5.1 card says outright that its OSWorld 2.0 figures "supersede the OSWorld 2.0 figures in the Claude Opus 5 System Card and are not directly comparable", and the Opus 4.8 card's Terminal-Bench 2.1 score of 74.6 was restated as 82.7 in the Fable 5 card twelve days later. **Cross-card comparisons of a single benchmark are therefore worth about five points of slack, and Terminal-Bench 2.1 numbers should not be compared across cards at all.**

## Effort settings and whether they overlap across versions

Anthropic reports five effort settings (low, medium, high, xhigh, max). Claude Code exposes them as `claude --effort <level>`, and the Fable 5.1 announcement says Claude Code defaults to high effort while Claude.ai and Cowork default to medium ([announcement](https://www.anthropic.com/claude-fable-and-mythos-5-1)).

Published overlaps, all from primary text:

- **A version step is roughly the whole effort range, within a family.** "At minimum effort, Opus 4.8 matches the peak performance of Opus 4.7 at maximum effort" ([Opus 4.8 card, section 8.2](https://www-cdn.anthropic.com/0f0c97ad20d8005706296bd92aa1c27c6b2f4f61/Claude%20Opus%204.8%20System%20Card.pdf)).
- **The same holds for Fable.** Fable 5.1 "achieves similar or better results than Fable 5 at low or medium effort, with much higher performance at higher effort tiers" ([Fable 5.1 announcement](https://www.anthropic.com/claude-fable-and-mythos-5-1)). On FrontierCode 1.1 Extended, Fable 5.1 scores 63.6% at medium effort against Fable 5's 64.9% at xhigh, and on the main set 50.9% at medium against Fable 5's 53.5% at xhigh, at roughly half the cost per task ([Fable 5.1 card, section 8.4](https://www-cdn.anthropic.com/0339e6a7c5c7b87f5c07798616dc32c215d14235/Claude%20Fable%205.1%20&%20Claude%20Mythos%205.1%20System%20Card.pdf)).
- **The newest Opus at max lands between the newest Fable at medium and at max.** On CursorBench 3.2.0, Fable 5.1 max is 73.4%, Opus 5 max is 70.0%, Fable 5 max is 70.5%, and Fable 5.1 medium is 68.0% at $3.53 per task ([Fable 5.1 card, section 8.8](https://www-cdn.anthropic.com/0339e6a7c5c7b87f5c07798616dc32c215d14235/Claude%20Fable%205.1%20&%20Claude%20Mythos%205.1%20System%20Card.pdf)). On AA-Briefcase, Opus 5 at max (1685) sits above Fable 5.1 at high (1611) and below Fable 5.1 at xhigh (1686) and max (1694) ([section 8.15.4](https://www-cdn.anthropic.com/0339e6a7c5c7b87f5c07798616dc32c215d14235/Claude%20Fable%205.1%20&%20Claude%20Mythos%205.1%20System%20Card.pdf)). On GDPval-AA v2, Fable 5.1 holds the top two spots at 1853 (max) and 1835 (xhigh), ahead of Opus 5 at max (1824) ([section 8.15.3](https://www-cdn.anthropic.com/0339e6a7c5c7b87f5c07798616dc32c215d14235/Claude%20Fable%205.1%20&%20Claude%20Mythos%205.1%20System%20Card.pdf)).
- **Effort is often cheaper than it looks.** Fable 5.1 xhigh matches max within the confidence interval on GDPval-AA v2 using about 25% fewer output tokens, and on AA-Briefcase using 19% fewer ([sections 8.15.3 and 8.15.4](https://www-cdn.anthropic.com/0339e6a7c5c7b87f5c07798616dc32c215d14235/Claude%20Fable%205.1%20&%20Claude%20Mythos%205.1%20System%20Card.pdf)). On FrontierBench, Opus 5 at high reaches 39% mean reward for 19% fewer output tokens than its best xhigh result of about 43%, and low reaches 25% for 64% fewer ([Opus 5 card, section 8.5](https://www-cdn.anthropic.com/ceaf5c7ff2783855203fde8208ec311252dced5b/Claude%20Opus%205%20System%20Card.pdf)).

So yes, the ranges overlap, and the overlap is wide enough that an effort step and a version step buy about the same amount of quality. The effort step is the cheaper of the two, because it does not change the model and costs fewer output tokens rather than more.

## Known regressions, where an older version beats a newer one

- **Tool use, and it matters most for the harness.** On Toolathlon Verified, Opus 5 scores 80.6 Pass@1, Opus 4.8 scores 79.9, Mythos 5 scores 79.3, Fable 5.1 scores 77.8, and Sonnet 5 scores 74.7 ([Fable 5.1 card, table 8.15.5.A](https://www-cdn.anthropic.com/0339e6a7c5c7b87f5c07798616dc32c215d14235/Claude%20Fable%205.1%20&%20Claude%20Mythos%205.1%20System%20Card.pdf)). The newest and most expensive model is last of the four. Part of this is safeguards: 11 of 324 Fable 5.1 trials hit a safety refusal and were finished by the Opus 4.8 fallback, and four more were terminated by classifiers and counted as failures.
- **Scope discipline at high effort.** Fable 5.1's FrontierCode score peaks at medium and falls below Fable 5 at high, xhigh, and max, because it "occasionally adds more small, unrequested changes in files outside the task, such as a documentation comment in an adjacent file, an edit to a docs page, or a new CI job where an existing one could have been reused" ([Fable 5.1 card, section 8.4](https://www-cdn.anthropic.com/0339e6a7c5c7b87f5c07798616dc32c215d14235/Claude%20Fable%205.1%20&%20Claude%20Mythos%205.1%20System%20Card.pdf)). Opus 5 shows the same shape: "There is a decline in FrontierCode score above high effort. This reflects a tendency for Opus 5 at these effort levels to make more changes than the task requires", and external pilot users reported "Overthinking, where it performs worse at higher effort levels" along with "Doing less than was asked" ([Opus 5 card, sections 8.4 and 6.2.1](https://www-cdn.anthropic.com/ceaf5c7ff2783855203fde8208ec311252dced5b/Claude%20Opus%205%20System%20Card.pdf)). This is directly relevant to a harness that enforces a touch set.
- **Multimodal and multilingual coding.** Opus 5 beats Fable 5.1 on SWE-bench Multimodal (59.4 against 54.7) and edges it on Multilingual (89.5 against 89.1).
- **Fluid reasoning.** Fable 5 beats Fable 5.1 on ARC-AGI-1 (98.5% against 97.5%), and Opus 5 edges Fable 5.1 on ARC-AGI-2 (90.42 against 90.0).
- **Health knowledge.** Fable 5 beats Fable 5.1 on HealthBench Professional (63.3% against 62.1%), and Mythos 5 (66.0) beats Opus 5 (59.8).
- **Science knowledge.** Opus 4.7 beats Opus 4.8 on GPQA Diamond (94.2 against 93.6) ([Opus 4.8 card, table 8.1.A](https://www-cdn.anthropic.com/0f0c97ad20d8005706296bd92aa1c27c6b2f4f61/Claude%20Opus%204.8%20System%20Card.pdf)).
- **Knowledge work across families.** Sonnet 5 beats Opus 4.8 on GDPval-AA v2 (1618 against 1593), on the older Terminal-Bench 2.1 if the Opus 4.8 card's own 74.6 is used against Sonnet 5's 80.4, and nearly ties it on HLE with tools (57.4 against 57.9). The Fable 5 card's restated Opus 4.8 Terminal-Bench figure of 82.7 reverses that one, which is exactly why cross-card Terminal-Bench comparisons are unsafe.
- **Some risk-relevant capability falls on purpose.** On CyberGym vulnerability discovery, Sonnet 5 "is less capable than Sonnet 4.6", reproducing the target vulnerability in fewer tasks ([Sonnet 5 card, section 3.2.3](https://www-cdn.anthropic.com/283ef97c476cf442c91d9a37d5b214242a55bb92/Claude%20Sonnet%205%20System%20Card.pdf)), and on the VCT multimodal virology evaluation Sonnet 5 scores 0.45 against Opus 4.7's 0.50 and Opus 4.8's 0.47, which the card itself calls a regression ([Sonnet 5 card, section 2.2.4](https://www-cdn.anthropic.com/283ef97c476cf442c91d9a37d5b214242a55bb92/Claude%20Sonnet%205%20System%20Card.pdf)). These are safety-desirable and do not bear on harness quality, but the first is a genuine case of an older version of the same family scoring higher.

## Proposed quality-ordered ladder

Ordered weakest to strongest, for the harness's own work (coding, tool use, long-horizon agentic tasks). Cost per token is included because the map keeps a rung only if it sits between its neighbours on both cost and quality.

| Rung | Verdict | Confidence | Evidence |
| --- | --- | --- | --- |
| Haiku 4.5 | clearly below Sonnet 4.6 | high | 73.3% SWE-bench Verified against Sonnet 4.6's 80.2%, and Anthropic positions it at Sonnet 4 level ([Haiku 4.5 announcement](https://www.anthropic.com/news/claude-haiku-4-5)) |
| Sonnet 4.6 | clearly between Haiku 4.5 and Sonnet 5 | medium-high | 80.2% against 85.2% Verified; SWE-bench Pro 58.1 against 63.2; Terminal-Bench 2.1 67.0 against 80.4; HLE with tools 46.8 against 57.4 ([Sonnet 5 card, table 8.1.A](https://www-cdn.anthropic.com/283ef97c476cf442c91d9a37d5b214242a55bb92/Claude%20Sonnet%205%20System%20Card.pdf)) |
| Sonnet 5 (newest Sonnet) | clearly above Sonnet 4.6, below Opus 4.8 on coding | high | as above, plus SWE-bench Pro 63.2 against Opus 4.8's 69.2 and Toolathlon 74.7 against 79.9 |
| Opus 4.7 | roughly tied with Sonnet 5, and out of order on cost | medium | Opus 4.7 leads on Verified (87.6 against 85.2) and Pro (64.3 against 63.2) but trails on Terminal-Bench 2.1 (66.1 against 80.4) and HLE with tools (54.7 against 57.4), while carrying Opus pricing of $5 and $25 per million tokens against Sonnet 5's $2 and $10 ([Opus 5 announcement](https://www.anthropic.com/news/claude-opus-5), [Sonnet 5 announcement](https://www.anthropic.com/news/claude-sonnet-5)). **Recommend dropping this rung.** |
| Opus 4.8 | clearly between Sonnet 5 and Opus 5 on coding and tool use; roughly tied with Sonnet 5 on knowledge work | medium-high for coding, low for knowledge work | SWE-bench Pro 69.2 against 63.2 and 79.2; Toolathlon 79.9 against 74.7 and 80.6; SWE-bench Multimodal 38.4 against 59.4. Against it: GDPval-AA v2 1593 against Sonnet 5's 1618, and AA-Briefcase 1346 against Opus 5's 1720 |
| Opus 5 (newest Opus) | clearly above Opus 4.8 | high | Verified 96.0 against 88.6; Pro 79.2 against 69.2; OSWorld 2.0 70.6 against 55.7; ARC-AGI-2 90.42 against 72.1; ARC-AGI-3 30.2 against 1.5; FrontierBench 43.3 against 21.1 |
| Fable 5 | **out of order** | high | Fable 5 loses to Opus 5 on Verified (95.0 against 96.0), Multilingual, Multimodal, FrontierBench (33.8 against 43.3), OSWorld 2.0, GDPval-AA v2, AA-Briefcase, AutomationBench, BrowseComp, and HLE with tools, and wins only SWE-bench Pro by 0.8 (80 against 79.2) and HealthBench Professional, while Opus 5 is priced at $5 per million input tokens and $25 per million output tokens, which the announcement calls half the price of Fable 5 ([Opus 5 announcement](https://www.anthropic.com/news/claude-opus-5)). **Do not use it as a rung between Opus 5 and Fable 5.1.** |
| Fable 5.1 (newest Fable) | clearly above Opus 5 on long-horizon coding and science work; roughly tied on tool use and multimodal | medium-high | Terminal-Bench 4.0 55.8 against 52.3; Terminal-Bench-Science 52.6 against 29.0; SWE-bench Pro 81.2 against 79.2; FrontierSWE v2 0.57 against 0.52; CursorBench 73.4 against 70.0; AutomationBench 31.4 against 26.9. Against it: Toolathlon 77.8 against 80.6 and SWE-bench Multimodal 54.7 against 59.4 |

**Recommended ladder, after dropping the two rungs that do not sit between their neighbours:**

`haiku-4.5` < `sonnet-4.6` < `sonnet-5` < `opus-4.8` < `opus-5` < `fable-5.1`

with Opus 4.7 and Fable 5 omitted, and with the caveat that Opus 4.8's place above Sonnet 5 is a coding and tool-use claim, not a knowledge-work one.

**Second recommendation, which the evidence supports more strongly than any version rung.** Because one version step is worth about one full effort range, and because effort is `claude --effort` on the model the harness already launches, the cheapest finer tiers are effort steps on the newest model of each family, for example `sonnet-5 @ medium`, `sonnet-5 @ high`, `opus-5 @ medium`, `opus-5 @ high`, `opus-5 @ max`, `fable-5.1 @ medium`. That gives more rungs than the served older versions do, with no risk that a retired version name breaks a launch, and with per-rung cost that falls rather than rises. Older versions are worth keeping only where a served older version is cheaper than the newer one at equal quality, which the published prices do not show for any Anthropic pair: within a family, price is unchanged across versions ($5/$25 for both Opus 4.8 and Opus 5, per the [Opus 5 announcement](https://www.anthropic.com/news/claude-opus-5)), so the older version is strictly dominated.

## What is missing, stated plainly

- No SWE-bench Verified score is published for Fable 5.1.
- No Terminal-Bench 4.0 or Terminal-Bench-Science score is published for Opus 4.8, Sonnet 5, Sonnet 4.6, or Haiku 4.5.
- No SWE-bench Pro, Terminal-Bench, OSWorld, ARC-AGI, or GPQA score is stated in text for Opus 4.6 or Sonnet 4.6; their launch posts publish those only as chart images ([Opus 4.6](https://www.anthropic.com/news/claude-opus-4-6), [Sonnet 4.6](https://www.anthropic.com/news/claude-sonnet-4-6)).
- No numeric per-effort table is published for any model. Every effort curve appears as a chart image, so the effort overlaps above are the ones Anthropic states in prose.
- Haiku 4.5 shares no benchmark with the 5-series cards other than SWE-bench Verified, and that under a different configuration (50 trials, no test-time compute).
- Nothing here measures the context window cost or the tokens a version consumes per ticket in this harness. That is a live probe, which this ticket does not run.
