# Decisions

The design decisions of this project: the grill's questions, settled by the owner or, once autonomy is raised, by the decider. `wayline grill` writes this file and reads back the record under each question, so a decision changes by answering it again (`wayline grill answer <id> ... --revise`), never by editing here.

## Settled

### Q1. What does the goal become, given that no model can reach 0.85 AUROC on split_b at the generator defaults?

- answer: the +0.02 gain over the no-product logistic regression: at least +0.02 held-out AUROC on split_b, mean over seeds
- rationale: the owner: I care about the gain, not an absolute number I picked before anyone ran the generator
- decided-by: human
- confidence: 0.95
- timestamp: 2026-09-13T06:24:16.685Z
- tier: 1
- recommended: a gain over the no-product logistic regression: at least +0.02 held-out AUROC on split_b, mean over seeds
- options: keep 0.85 absolute (unreachable at defaults); an absolute target under the ceiling, 0.74 AUROC on split_b; a gain over the no-product logistic regression: at least +0.02 held-out AUROC on split_b, mean over seeds; raise the generator's signal or interaction strength so 0.85 becomes reachable
- evidence:
  - the AUROC of the true log-odds on split_b is 0.7445, 0.7492, 0.7447, 0.7511, 0.7447 for seeds 0-4 at signal 1.0, interaction 0.6 (computed from toy/make_synthetic.py with toy/eval.py); the linear-only oracle is 0.699-0.713, so the planted product is worth about 0.03-0.045; the memo's revised 0.83 is also out of reach; intake's 0.7778 came from a 6-row sample file (toy/predictions-sample.csv)
- human-only: yes
- reversible: no

<!-- wayline:decision {"id":"Q1","question":"What does the goal become, given that no model can reach 0.85 AUROC on split_b at the generator defaults?","options":["keep 0.85 absolute (unreachable at defaults)","an absolute target under the ceiling, 0.74 AUROC on split_b","a gain over the no-product logistic regression: at least +0.02 held-out AUROC on split_b, mean over seeds","raise the generator's signal or interaction strength so 0.85 becomes reachable"],"recommended":"a gain over the no-product logistic regression: at least +0.02 held-out AUROC on split_b, mean over seeds","evidence":["the AUROC of the true log-odds on split_b is 0.7445, 0.7492, 0.7447, 0.7511, 0.7447 for seeds 0-4 at signal 1.0, interaction 0.6 (computed from toy/make_synthetic.py with toy/eval.py); the linear-only oracle is 0.699-0.713, so the planted product is worth about 0.03-0.045; the memo's revised 0.83 is also out of reach; intake's 0.7778 came from a 6-row sample file (toy/predictions-sample.csv)"],"requires":[],"human_only":true,"reversible":false,"tier":1,"supersedes":null,"answer":"the +0.02 gain over the no-product logistic regression: at least +0.02 held-out AUROC on split_b, mean over seeds","rationale":"the owner: I care about the gain, not an absolute number I picked before anyone ran the generator","confidence":0.95,"decided_by":"human","timestamp":"2026-09-13T06:24:16.685Z"} -->

### Q2. Which of the position memo's directions does the project take?

- answer: moderate: nearest plus a flexible model without products as a second baseline
- rationale: the owner took the recommendation: the radius is moderate, and only the moderate direction answers objection 2, paper-b's flexible model finding interactions without products
- decided-by: human
- confidence: not stated
- timestamp: 2026-09-13T06:24:17.920Z
- tier: 1
- recommended: moderate: nearest plus a flexible model without products as a second baseline
- options: nearest: logistic regression with and without pairwise products, several seeds, default set; moderate: nearest plus a flexible model without products as a second baseline; exploratory: sweep the generator's interaction strength to find where products stop helping
- evidence:
  - harness.json radius is moderate; the memo's objection 2 cites paper-b (a flexible model finds interactions without explicit products, research/refs/paper-b/dossier.json), and only the moderate direction answers it

<!-- wayline:decision {"id":"Q2","question":"Which of the position memo's directions does the project take?","options":["nearest: logistic regression with and without pairwise products, several seeds, default set","moderate: nearest plus a flexible model without products as a second baseline","exploratory: sweep the generator's interaction strength to find where products stop helping"],"recommended":"moderate: nearest plus a flexible model without products as a second baseline","evidence":["harness.json radius is moderate; the memo's objection 2 cites paper-b (a flexible model finds interactions without explicit products, research/refs/paper-b/dossier.json), and only the moderate direction answers it"],"requires":[],"human_only":false,"reversible":true,"tier":1,"supersedes":null,"answer":"moderate: nearest plus a flexible model without products as a second baseline","rationale":"the owner took the recommendation: the radius is moderate, and only the moderate direction answers objection 2, paper-b's flexible model finding interactions without products","confidence":null,"decided_by":"human","timestamp":"2026-09-13T06:24:17.920Z"} -->

### Q3. scikit-learn is not installed: what fits the models?

- answer: install scikit-learn, but into a virtual environment of the project's own, not the tools venv
- rationale: the owner: the tools venv is for the PDF converters and I want it left alone
- decided-by: human
- confidence: not stated
- timestamp: 2026-09-13T06:24:19.108Z
- tier: 1
- recommended: install scikit-learn into the tools venv (wayline tools install) and use it
- options: install scikit-learn into the tools venv (wayline tools install) and use it; implement the models in numpy, which is installed; pure Python, no third-party packages
- evidence:
  - python3 -c 'import sklearn' fails with ModuleNotFoundError; numpy 1.26.4 imports; wayline tools show reports nothing installed; the intake asks for scikit-learn if present, and it also carries the flexible baselines Q2's moderate direction needs

<!-- wayline:decision {"id":"Q3","question":"scikit-learn is not installed: what fits the models?","options":["install scikit-learn into the tools venv (wayline tools install) and use it","implement the models in numpy, which is installed","pure Python, no third-party packages"],"recommended":"install scikit-learn into the tools venv (wayline tools install) and use it","evidence":["python3 -c 'import sklearn' fails with ModuleNotFoundError; numpy 1.26.4 imports; wayline tools show reports nothing installed; the intake asks for scikit-learn if present, and it also carries the flexible baselines Q2's moderate direction needs"],"requires":[],"human_only":false,"reversible":true,"tier":1,"supersedes":null,"answer":"install scikit-learn, but into a virtual environment of the project's own, not the tools venv","rationale":"the owner: the tools venv is for the PDF converters and I want it left alone","confidence":null,"decided_by":"human","timestamp":"2026-09-13T06:24:19.108Z"} -->

### Q4. Which interaction terms does the with-products model get?

- answer: all 28 pairwise products of x0..x7, with the planted-only model (x2*x3) as an oracle reference, and no coefficient read as a discovery
- rationale: the owner took the recommendation: the method cannot know which product was planted, the planted-only model bounds what a product can add, and reading no coefficient as a discovery meets objection 4
- decided-by: human
- confidence: not stated
- timestamp: 2026-09-13T06:24:20.733Z
- tier: 1
- recommended: all 28 pairwise products of x0..x7, with the planted-only model (x2*x3) as an oracle reference, and no coefficient read as a discovery
- options: all 28 pairwise products of x0..x7, with the planted-only model (x2*x3) as an oracle reference, and no coefficient read as a discovery; all 28 pairwise products, nothing else; only the planted product x2*x3
- evidence:
  - the generator has 8 features and plants exactly one product, x2*x3 (toy/make_synthetic.py); paper-a adds pairwise products (research/refs/paper-a/dossier.json); the memo's objection 4 warns against reading whichever product helps as a discovery

<!-- wayline:decision {"id":"Q4","question":"Which interaction terms does the with-products model get?","options":["all 28 pairwise products of x0..x7, with the planted-only model (x2*x3) as an oracle reference, and no coefficient read as a discovery","all 28 pairwise products, nothing else","only the planted product x2*x3"],"recommended":"all 28 pairwise products of x0..x7, with the planted-only model (x2*x3) as an oracle reference, and no coefficient read as a discovery","evidence":["the generator has 8 features and plants exactly one product, x2*x3 (toy/make_synthetic.py); paper-a adds pairwise products (research/refs/paper-a/dossier.json); the memo's objection 4 warns against reading whichever product helps as a discovery"],"requires":[],"human_only":false,"reversible":true,"tier":1,"supersedes":null,"answer":"all 28 pairwise products of x0..x7, with the planted-only model (x2*x3) as an oracle reference, and no coefficient read as a discovery","rationale":"the owner took the recommendation: the method cannot know which product was planted, the planted-only model bounds what a product can add, and reading no coefficient as a discovery meets objection 4","confidence":null,"decided_by":"human","timestamp":"2026-09-13T06:24:20.733Z"} -->

### Q6. What wall-clock budget does the project run under?

- answer: 4 hours of CPU wall clock in total
- rationale: the owner: a one-hour cap would kill the network's cross-validation grid halfway through
- decided-by: human
- confidence: not stated
- timestamp: 2026-09-13T06:24:21.724Z
- tier: 1
- recommended: 1 hour of CPU wall clock in total
- options: 1 hour of CPU wall clock in total; 4 hours of CPU wall clock in total; no cap
- evidence:
  - harness.json budgets are all null; the intake says CPU only; the position memo says a logistic regression with or without pairwise products fits a set this size in seconds on a CPU; 8 cores and 64 GB are reserved (harness.json)

<!-- wayline:decision {"id":"Q6","question":"What wall-clock budget does the project run under?","options":["1 hour of CPU wall clock in total","4 hours of CPU wall clock in total","no cap"],"recommended":"1 hour of CPU wall clock in total","evidence":["harness.json budgets are all null; the intake says CPU only; the position memo says a logistic regression with or without pairwise products fits a set this size in seconds on a CPU; 8 cores and 64 GB are reserved (harness.json)"],"requires":[],"human_only":false,"reversible":true,"tier":1,"supersedes":null,"answer":"4 hours of CPU wall clock in total","rationale":"the owner: a one-hour cap would kill the network's cross-validation grid halfway through","confidence":null,"decided_by":"human","timestamp":"2026-09-13T06:24:21.724Z"} -->

### Q5. What varies across repeats, and how many repeats are there?

- answer: ten generator seeds (a fresh set each, split_b always its last quarter), comparisons paired within a seed
- rationale: the owner: more would be nicer, but four hours is four hours
- decided-by: human
- confidence: 0.4
- timestamp: 2026-09-13T06:25:44.023Z
- tier: 1
- recommended: 10 generator seeds (a fresh set each, split_b always its last quarter), comparisons paired within a seed
- options: 10 generator seeds (a fresh set each, split_b always its last quarter), comparisons paired within a seed; 5 generator seeds, paired within a seed; one set (seed 0), 10 model seeds
- evidence:
  - split_b is 5000 rows, the last quarter of 20000 (toy/make_synthetic.py); the ceiling alone moves 0.7445-0.7511 over seeds 0-4, a spread about a third of a 0.02 gain; logistic regression is deterministic, so model seeds on one set measure almost nothing; the memo's objection 3 asks for variance
- human-only: yes

<!-- wayline:decision {"id":"Q5","question":"What varies across repeats, and how many repeats are there?","options":["10 generator seeds (a fresh set each, split_b always its last quarter), comparisons paired within a seed","5 generator seeds, paired within a seed","one set (seed 0), 10 model seeds"],"recommended":"10 generator seeds (a fresh set each, split_b always its last quarter), comparisons paired within a seed","evidence":["split_b is 5000 rows, the last quarter of 20000 (toy/make_synthetic.py); the ceiling alone moves 0.7445-0.7511 over seeds 0-4, a spread about a third of a 0.02 gain; logistic regression is deterministic, so model seeds on one set measure almost nothing; the memo's objection 3 asks for variance"],"requires":[],"human_only":true,"reversible":true,"tier":1,"supersedes":null,"answer":"ten generator seeds (a fresh set each, split_b always its last quarter), comparisons paired within a seed","rationale":"the owner: more would be nicer, but four hours is four hours","confidence":0.4,"decided_by":"human","timestamp":"2026-09-13T06:25:44.023Z"} -->

## Open

### Q7. How is the objection that the synthetic set plants the interaction met?

- open: its prerequisites are settled
- tier: 2
- recommended: add a null control set (interaction 0) and state in the anti-claims that the result is synthetic-only
- options: add a null control set (interaction 0) and state in the anti-claims that the result is synthetic-only; state in the anti-claims that the result is synthetic-only, no extra data; add a short sweep of interaction strength (0, 0.3, 0.6, 1.0) as a follow-up
- requires: Q2
- evidence:
  - make_synthetic.py takes --interaction; paper-a reports products change nothing on sets whose labels do not depend on products (research/refs/paper-a/dossier.json), so interaction 0 is the refutation check; the memo's objection 1 says the result means nothing about real data unless settings vary
- human-only: yes

<!-- wayline:decision {"id":"Q7","question":"How is the objection that the synthetic set plants the interaction met?","options":["add a null control set (interaction 0) and state in the anti-claims that the result is synthetic-only","state in the anti-claims that the result is synthetic-only, no extra data","add a short sweep of interaction strength (0, 0.3, 0.6, 1.0) as a follow-up"],"recommended":"add a null control set (interaction 0) and state in the anti-claims that the result is synthetic-only","evidence":["make_synthetic.py takes --interaction; paper-a reports products change nothing on sets whose labels do not depend on products (research/refs/paper-a/dossier.json), so interaction 0 is the refutation check; the memo's objection 1 says the result means nothing about real data unless settings vary"],"requires":["Q2"],"human_only":true,"reversible":true,"tier":2,"supersedes":null,"answer":null,"rationale":null,"confidence":null,"decided_by":null,"timestamp":null} -->

### Q8. Which flexible model without products is the second baseline?

- open: its prerequisites are settled
- tier: 2
- recommended: a small multilayer network (scikit-learn MLPClassifier) on the raw features
- options: a small multilayer network (scikit-learn MLPClassifier) on the raw features; gradient-boosted trees (scikit-learn HistGradientBoostingClassifier) on the raw features; both
- requires: Q2, Q3
- evidence:
  - paper-b reports a deeper network given no products matched a shallow one given them (research/refs/paper-b/dossier.json; POSITION.md), so a network is the competing explanation as that paper states it; trees would test a different claim

<!-- wayline:decision {"id":"Q8","question":"Which flexible model without products is the second baseline?","options":["a small multilayer network (scikit-learn MLPClassifier) on the raw features","gradient-boosted trees (scikit-learn HistGradientBoostingClassifier) on the raw features","both"],"recommended":"a small multilayer network (scikit-learn MLPClassifier) on the raw features","evidence":["paper-b reports a deeper network given no products matched a shallow one given them (research/refs/paper-b/dossier.json; POSITION.md), so a network is the competing explanation as that paper states it; trees would test a different claim"],"requires":["Q2","Q3"],"human_only":false,"reversible":true,"tier":2,"supersedes":null,"answer":null,"rationale":null,"confidence":null,"decided_by":null,"timestamp":null} -->

### Q9. What counts as the products' gain being real?

- open: its prerequisites are settled
- tier: 3
- recommended: the mean paired gain over seeds meets the goal and its 95% interval over seeds excludes 0
- options: the mean paired gain over seeds meets the goal and its 95% interval over seeds excludes 0; the mean paired gain meets the goal, no interval; the gain is positive on every seed
- requires: Q1, Q5
- evidence:
  - the memo's objection 3: a gain of 0.01 on one split and one seed could be noise; the per-seed ceiling spread on split_b is 0.0066 over seeds 0-4 (computed from toy/make_synthetic.py)
- human-only: yes

<!-- wayline:decision {"id":"Q9","question":"What counts as the products' gain being real?","options":["the mean paired gain over seeds meets the goal and its 95% interval over seeds excludes 0","the mean paired gain meets the goal, no interval","the gain is positive on every seed"],"recommended":"the mean paired gain over seeds meets the goal and its 95% interval over seeds excludes 0","evidence":["the memo's objection 3: a gain of 0.01 on one split and one seed could be noise; the per-seed ceiling spread on split_b is 0.0066 over seeds 0-4 (computed from toy/make_synthetic.py)"],"requires":["Q1","Q5"],"human_only":true,"reversible":true,"tier":3,"supersedes":null,"answer":null,"rationale":null,"confidence":null,"decided_by":null,"timestamp":null} -->

### Q10. How are regularization and network settings tuned without touching split_b?

- open: its prerequisites are settled
- tier: 2
- recommended: 5-fold cross-validation inside split_a, the same grid for every model
- options: 5-fold cross-validation inside split_a, the same grid for every model; a fixed 80/20 validation carve of split_a; no tuning: library defaults for every model
- requires: Q3, Q4
- evidence:
  - split_a is 15000 rows and no model trains or tunes on split_b (toy/make_synthetic.py); 28 products on 8 features make regularization strength matter, and one grid for all models keeps the baselines as tuned as the method

<!-- wayline:decision {"id":"Q10","question":"How are regularization and network settings tuned without touching split_b?","options":["5-fold cross-validation inside split_a, the same grid for every model","a fixed 80/20 validation carve of split_a","no tuning: library defaults for every model"],"recommended":"5-fold cross-validation inside split_a, the same grid for every model","evidence":["split_a is 15000 rows and no model trains or tunes on split_b (toy/make_synthetic.py); 28 products on 8 features make regularization strength matter, and one grid for all models keeps the baselines as tuned as the method"],"requires":["Q3","Q4"],"human_only":false,"reversible":true,"tier":2,"supersedes":null,"answer":null,"rationale":null,"confidence":null,"decided_by":null,"timestamp":null} -->
