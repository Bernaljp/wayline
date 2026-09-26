/wayline-interval-claims

# The report you are writing prose for

Code renders every section of `research/REPORT.md` from the ledger. You write two kinds of paragraph and nothing else: one for each claim group below, saying what its findings establish together, and one on the negative results. The findings themselves are listed under your paragraphs as they were recorded, so do not copy them out one by one.

The run's goal: `auroc`, direction up, target 0.82, on the held-out split `held_out`.

# The evidence

Each finding carries the tags that trace it. A claim sentence of yours ends with the tags of the findings it rests on, copied exactly.

## Group `research/SPEC.md#seams`

- `t5-a1-f1` (ticket 5): toy.analyze's guards exit 2 (missing cell, after a `cells:` stdout line), 3 (a summary at non-default features/epochs/lr/batch_size/rows) and 4 (held_out_labels differing from the regenerated split or between arms), all with no JSON or report written; the experiment tickets can read the code to tell why a run refused. Real summaries must record rows 20000 or pass --expect-rows.
  tags: `{res:t5-a1/src/toy/analyze.py#AnalysisError}`
- `t5-a1-f2` (ticket 5): The per-signal JSON's goal_artifact path is always <results>/signal-4/raw_x3x4/seed-1/summary.json whatever signal is analysed, with auroc and reaches null until it exists; the E2 sweep JSONs for signals 1, 2, 8 will therefore cite the E1 artifact.
  tags: `{res:t5-a1/src/toy/analyze.py#_goal_check}`
- `t5-a1-f3` (ticket 5): The report's 'several points' sentence expresses the mean paired gain in points (one point = 0.01 AUROC) with no floor and no verdict, since paper-a gives no number.
  tags: `{res:t5-a1/src/toy/analyze.py#render_report}`

## Group `research/SPEC.md#e1-claims-c1-c2-c3-c4`

- `t36-a1-f1` (ticket 36): C1 supported at the headline signal (--signal 4.0): the paired gain (held-out AUROC of raw + x3*x4 minus raw, same draw) has mean 0.0864 over ten seeds, 95% bootstrap interval [0.0829, 0.0897] (10000 resamples, random.Random(0)), holds = true, positive_seeds = 10 of 10. The per-seed DeLong triples [diff, lo, hi] for (raw_x3x4, raw), seeds 1..10, are: [0.0831, 0.0717, 0.0944], [0.0779, 0.0668, 0.0891], [0.0770, 0.0660, 0.0881], [0.0880, 0.0773, 0.0987], [0.0841, 0.0729, 0.0952], [0.0881, 0.0771, 0.0992], [0.0890, 0.0778, 0.1003], [0.0935, 0.0828, 0.1043], [0.0890, 0.0783, 0.0996], [0.0941, 0.0818, 0.1065]. Every seed's DeLong interval lies above 0. This is also the signal-4 verdict for C3, which feeds E2's conjunction.
  tags: `{res:t36-a1/analysis/ablation/signal-4.json#paired_gain}`
- `t36-a1-f2` (ticket 36): C2 supported at signal 4.0: credit_margin.credited = true. The credit margin (raw + x3*x4 minus the wrong-pair control raw + x1*x2, same draw, same number of columns) has mean 0.0862, 95% bootstrap interval [0.0827, 0.0897], and 10 of 10 per-seed values positive (min 0.0774, seed 2). The per-seed DeLong triples for (raw_x3x4, raw_x1x2), seeds 1..10, are: [0.0833, 0.0720, 0.0947], [0.0774, 0.0663, 0.0885], [0.0783, 0.0672, 0.0894], [0.0897, 0.0790, 0.1004], [0.0822, 0.0713, 0.0932], [0.0848, 0.0738, 0.0957], [0.0885, 0.0774, 0.0997], [0.0935, 0.0828, 0.1042], [0.0902, 0.0796, 0.1008], [0.0945, 0.0822, 0.1067]. All lie above 0. This is also the signal-4 verdict for C4.
  tags: `{res:t36-a1/analysis/ablation/signal-4.json#credit_margin}`
- `t36-a1-f4` (ticket 36): A4 (reported, no verdict): the all-pairs cost (raw + all six pairwise products minus raw + x3*x4) at signal 4.0 has mean -0.00023, 95% bootstrap interval [-0.00080, 0.00032] (includes 0). Per-seed DeLong intervals for (raw_allpairs, raw_x3x4) include 0 on 9 of 10 seeds; seed 5's is [-0.0036, -0.0003], with diff -0.0019. An interval including 0 says the six-product arm finds the pair on its own at this signal, so the model need not be told which pair matters.
  tags: `{res:t36-a1/analysis/ablation/signal-4.json#allpairs_cost}`
- `t36-a1-f6` (ticket 36): allpairs_vs_raw (descriptive, no verdict): raw + all six pairwise products minus raw at signal 4.0 has mean 0.0862, 95% bootstrap interval [0.0823, 0.0898].
  tags: `{res:t36-a1/analysis/ablation/signal-4.json#allpairs_vs_raw}`
- `t36-a1-f7` (ticket 36): Mean paired gain against paper-a's 'several points' (materials/paper-a.tex:20), in words and with no floor (A5): at signal 4.0 the mean paired gain is 0.0864 AUROC, about 8.6 points (one point = 0.01 AUROC). That is comfortably in the range 'several points' describes at this one signal. It says nothing yet about 'every signal strength tried', which is E2's question.
  tags: `{res:t36-a1/analysis/ablation/signal-4.json#paired_gain.mean}`
- `t36-a1-f8` (ticket 36): Bayes ceiling at signal 4.0 (descriptive, no verdict): the oracle ranking's held-out AUROC per seed ranges 0.8489 to 0.8637 (mean 0.8571). The ceiling minus raw_x3x4 is positive on all ten seeds, from 0.00004 (seed 5) to 0.0023 (seed 4), mean 0.00089. The raw + x3*x4 arm sits within a quarter point of the ceiling on every seed.
  tags: `{res:t36-a1/analysis/ablation/signal-4.json#ceiling}`
- `t36-a1-f9` (ticket 36): Reproduction check of the --features refactor (Q14) passes bitwise. On device cuda (both runs), the flagless seed-1 run's auroc is 0.8502984862625299 and the explicit raw_x3x4 seed-1 cell's is 0.8502984862625299. Difference (flagless minus explicit) = 0.0, bitwise = true, within_1e-6 = true.
  tags: `{res:t36-a1/analysis/ablation/e1-checks.json#reproduction}`
- `t36-a1-f10` (ticket 36): Goal check (Q2; reported, not a stopping rule and not evidence for any claim): the goal artifact results/ablation/signal-4/raw_x3x4/seed-1/summary.json has auroc 0.8502984862625299. GOAL.json's eval_command (PYTHONPATH=src python3 -m toy.eval --split held_out) prints the same value, and reaches_target (>= 0.82) = true. Seeds at or above 0.82 per arm at signal 4.0: raw 0, raw_x3x4 10, raw_x1x2 0, raw_allpairs 10.
  tags: `{res:t36-a1/analysis/ablation/e1-checks.json#goal_artifact}`
- `t36-a1-f11` (ticket 36): Held-out discipline at signal 4.0 (Q5): cells = 10 summaries for each of raw, raw_x3x4, raw_x1x2 and raw_allpairs (40 in all). non_default is empty: every cell records its arm's features, epochs 30, lr 0.1, rows 20000, batch_size 256, signal 4.0, its seed, and 4000 held-out scores and labels. toy.analyze's label-regeneration guard also passed.
  tags: `{res:t36-a1/analysis/ablation/e1-checks.json#non_default}`
- `t36-a1-f12` (ticket 36): GPU seconds (Q11): the forty signal-4 cells sum to 160.5 s and the flagless run to 4.0 s, 164.5 s in total, against the 14400 s cap.
  tags: `{res:t36-a1/analysis/ablation/e1-checks.json#gpu_seconds}`

## Group `research/SPEC.md#e2-claims-c3-c4`

- `t37-a1-f1` (ticket 37): C3 supported. The paired gain holds at all four signals. Mean and 95% bootstrap interval: signal 1: 0.0305 [0.0259, 0.0355]; signal 2: 0.0562 [0.0519, 0.0600]; signal 4: 0.0864 [0.0829, 0.0897]; signal 8: 0.1113 [0.1073, 0.1152]. At every signal all 10 seeds have a positive gain. The omnibus result is true: it is the conjunction of four per-signal verdicts, none corrected for multiple comparisons (Q12). This is a per-signal test with intervals, standing in for paper-a's 'every signal strength tried'.
  tags: `{res:t37-a1/analysis/ablation/report.md#Omnibus}`
- `t37-a1-f2` (ticket 37): Signal 1 paired gain: mean 0.0305, 95% bootstrap interval [0.0259, 0.0355], holds; 10 of 10 seeds positive.
  tags: `{res:t37-a1/analysis/ablation/signal-1.json#paired_gain}`
- `t37-a1-f3` (ticket 37): Signal 2 paired gain: mean 0.0562, 95% bootstrap interval [0.0519, 0.0600], holds; 10 of 10 seeds positive.
  tags: `{res:t37-a1/analysis/ablation/signal-2.json#paired_gain}`
- `t37-a1-f4` (ticket 37): Signal 8 paired gain: mean 0.1113, 95% bootstrap interval [0.1073, 0.1152], holds; 10 of 10 seeds positive.
  tags: `{res:t37-a1/analysis/ablation/signal-8.json#paired_gain}`
- `t37-a1-f5` (ticket 37): C4 at signal 1: credited. Credit margin mean 0.0299, 95% bootstrap interval [0.0243, 0.0349].
  tags: `{res:t37-a1/analysis/ablation/signal-1.json#credit_margin}`
- `t37-a1-f6` (ticket 37): C4 at signal 2: credited. Credit margin mean 0.0553, 95% bootstrap interval [0.0512, 0.0588].
  tags: `{res:t37-a1/analysis/ablation/signal-2.json#credit_margin}`
- `t37-a1-f7` (ticket 37): C4 at signal 4: credited. Credit margin mean 0.0862, 95% bootstrap interval [0.0827, 0.0897].
  tags: `{res:t36-a1/analysis/ablation/signal-4.json#credit_margin}`
- `t37-a1-f8` (ticket 37): C4 at signal 8: credited. Credit margin mean 0.1117, 95% bootstrap interval [0.1080, 0.1155]. C4 is supported at every signal where the gain holds, which is all four; no signal is moot.
  tags: `{res:t37-a1/analysis/ablation/signal-8.json#credit_margin}`
- `t37-a1-f10` (ticket 37): A3 confirmed. Seeds at or above 0.82 per arm (raw / raw_x3x4 / raw_x1x2 / raw_allpairs): 0/0/0/0 at signal 1, 0/0/0/0 at signal 2, 0/10/0/10 at signal 4, 10/10/10/10 at signal 8. The raw arm clears 0.82 on all 10 seeds at signal 8. The raw_x3x4 arm clears it on 0 of 10 seeds at signals 1 and 2, where the gain holds. The goal check is reported only and is not evidence for any claim.
  tags: `{res:t37-a1/analysis/ablation/signal-8.json#goal_check.seeds_at_or_above_target}`
- `t37-a1-f11` (ticket 37): A5. Mean paired gain in points (one point = 0.01 AUROC): 3.1 at signal 1, 5.6 at signal 2, 8.6 at signal 4, 11.1 at signal 8. These are set against paper-a's 'several points'; the paper gives no floor, and no verdict is drawn.
  tags: `{res:t37-a1/analysis/ablation/report.md#Omnibus}`
- `t37-a1-f12` (ticket 37): A4, A6: descriptive, no verdict. All-pairs cost (raw_allpairs minus raw_x3x4), mean and 95% interval: signal 1: -0.0021 [-0.0051, 0.0008]; signal 2: -0.0015 [-0.0030, -0.00001], the only interval just below 0; signal 4: -0.0002 [-0.0008, 0.0003]; signal 8: -0.0002 [-0.0004, 0.00003]. Wrong-pair vs raw: its interval includes 0 at all four signals. All-pairs vs raw: its interval is above 0 at all four and tracks the paired gain.
  tags: `{res:t37-a1/analysis/ablation/signal-2.json#allpairs_cost}`
- `t37-a1-f13` (ticket 37): Budget (Q11): 641.0 GPU seconds over the four signals (160.2 at signal 1, 160.1 at signal 2, 160.5 at signal 4, 160.2 at signal 8), against the 14400 cap. Adding the flagless run's 4.0 s, which lies outside the spec's sum, gives 645.0.
  tags: `{res:t37-a1/analysis/ablation/signal-1.json#gpu_seconds}`
- `t37-a1-f14` (ticket 37): Held-out discipline (Q5): 10 summaries per arm at each signal, 160 in all. toy.analyze accepted every one at the Q5 settings; nothing was re-fitted and no goal artifact was exported.
  tags: `{res:t37-a1/analysis/ablation/signal-1.json#cells}`

## Negative results

- `t5-a1-f4` (ticket 5): The worker prompt for this ticket omitted the ticket's ## Notes and quality criterion, which is where the guards, the JSON shape and the test list (a)-(g) live; attempt 1 failed for that reason. Reading research/tickets/05-*.md directly is what fixed it.
  tags: `{res:t5-a1/research/tickets/05-toy-analyze-per-signal-analysis-json-metric-prin.md#notes}`
- `t36-a1-f3` (ticket 36): A1 not triggered at signal 4.0: the paired gain holds and the credit margin's 95% interval [0.0827, 0.0897] excludes 0. The wrong-pair control does not keep pace, and the gain here is credited to the right interaction rather than to extra capacity.
  tags: `{res:t36-a1/analysis/ablation/signal-4.json#credit_margin.ci95}`
- `t36-a1-f5` (ticket 36): A6 (reported, no verdict): wrong_pair_vs_raw (raw + x1*x2 minus raw) at signal 4.0 has mean 0.00015, 95% bootstrap interval [-0.00068, 0.00111] (includes 0). The product column the label does not use shows no capacity gain over raw here.
  tags: `{res:t36-a1/analysis/ablation/signal-4.json#wrong_pair_vs_raw}`
- `t37-a1-f9` (ticket 37): A2 not confirmed. No signal fails, so the sweep has no failing signal to explain as saturation or noise. The raw_x3x4 arm sits near the Bayes ceiling at every signal. Ceiling minus raw_x3x4, with the ceiling in brackets: 0.0028 (0.622) at signal 1, 0.0015 (0.732) at signal 2, 0.0009 (0.857) at signal 4, 0.0003 (0.947) at signal 8.
  tags: `{res:t37-a1/analysis/ablation/signal-8.json#ceiling.means}`

Return the paragraphs through the structured output; the harness writes them into the report.

# Protocol

1. Read the evidence above: the findings, each with the tags that trace it, grouped the way the
   report groups them. Where paths are listed, open them before you rely on them.
2. Write only what the evidence supports. Every claim sentence ends with the tags of the findings
   it rests on, copied exactly, right after its full stop.
3. Do not introduce a number, a comparison, or a cause that no finding states. A claim you cannot
   tag is a claim you leave out.
4. Definitions, transitions, and method descriptions need no tag. When in doubt whether a
   sentence is a claim, it is one, and it needs its tag.
5. Return the structured result your launch asks for. Nothing under `research/` is yours to
   write: prose meant for the report or the ledger reaches it through that result, and a file a
   writing ticket asks for is written inside the ticket's touch set.

# The prose

Return it through the structured output, once, before you stop. The launch passes the `report_prose` schema to this session, and the harness validates what comes back against it again:

- `groups` (array of object with group (required), text (required), required): one paragraph per claim group, in the prompt's order; a group the prompt did not name is dropped
- `negative_results` (string, required): one paragraph on what did not work, every claim sentence ending with its tags; the empty string when the prompt listed no negative result
