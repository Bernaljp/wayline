# 63 - The model that ran

**What to build:** A retired or unknown model name fails loudly instead of running on another model. The CLI silently runs a retired name such as `claude-opus-4-1` on its family's newest model, and fails a name it does not serve with a 404 that costs nothing. Every launch now sets `CLAUDE_CODE_DISABLE_LEGACY_MODEL_REMAP=1`, and the launcher compares the model named in the result's `modelUsage` with the rung's: a mismatch is journaled as `model_ran` and fails the attempt with `reason: model_mismatch`. A not-served failure (`reason: model_not_served`) is not retried: the conductor holds launches at that rung and opens a `human_only` decision ticket naming the rung and the model, because a policy naming a dead model needs the owner's edit, and the rest of the run continues on other rungs. `wayline status` shows both models when the one that ran differs. No probe runs at `run` start and no retirement date is stored.

**Blocked by:** 60 (The rung ladder)

**Status:** ready-for-agent

**GitHub:** [#146](https://github.com/Bernaljp/wayline/issues/146) (mirror; the local file is the source)

**Milestone:** M5 Overnight and report. **Spec:** milestone M5 criterion 17; Implementation Decisions 16 (the model that ran, what `wayline status` and the dashboard show, the vocabulary the build adds), 3 (the worker launcher, the stream), 5 (failures), 2 (the event table: `model_ran`, the `ticket_failed` reasons); user stories 83, 94, and 95.

- [ ] Every `LaunchRequest` the `claude_cli` backend runs, ticket work, role sessions, and verdicts alike, sets `CLAUDE_CODE_DISABLE_LEGACY_MODEL_REMAP=1` in the session's environment.
- [ ] The launcher reads the model that ran from the result's `modelUsage`. A rung naming a full version matches only that version; a rung naming an alias matches any version of the alias's family. On a ticket attempt that does not match, the attempt fails with `reason: model_mismatch` and the model that ran is journaled as `model_ran`; a verdict carries `model_ran` when its model differs. `model_ran` and both reasons join the event table in the same commit.
- [ ] The not-served failure (exit 1, `is_error` with `subtype: success`, `api_error_status: 404`, the text "There's an issue with the selected model (<name>)") fails the attempt with `reason: model_not_served` and is never resumed or retried. It is not counted as a model refusal of the pacing module and does not pause the run.
- [ ] After a not-served failure the conductor holds every launch at that rung, and a tier up onto it waits too, while launches at other rungs continue. It opens one `human_only` decision ticket per held rung, under every autonomy, naming the rung, its model, and the refused name, and saying that the policy needs an edit. The hold lifts when that ticket is answered; replay rebuilds the hold.
- [ ] `wayline status` and the dashboard's ticket page show both models on a launch whose `model_ran` differs from its rung's (for example `r5 claude-opus-4-8 high, ran claude-opus-5`).
- [ ] Tests: the fake launcher scripted with a result whose `modelUsage` names another model and with the not-served envelope; each `LaunchRequest`'s environment asserted; recorded journals replay a rung held after a not-served failure while another rung keeps launching, and its decision ticket's answer lifting the hold, idempotence included. The research note's envelopes on the branch `research/model-versions` are the prior art.
- [ ] `python -m unittest` passes.
