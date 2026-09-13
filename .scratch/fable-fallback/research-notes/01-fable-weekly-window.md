# Fable's weekly window: what the harness can read before and at a refusal

## Answer

1. No. `rate_limit_event`s recorded on allowed sessions for Haiku, Sonnet, and Opus carry `unifiedWindows` with only `five_hour` and `seven_day` (both `{utilization, resetsAt}`). None of them include a `seven_day_overage_included` key. That key appears only on the event that actually rejects a Fable request. So pacing cannot watch Fable's window from an arbitrary non-Fable session's `rate_limit_event`; the only live signal for Fable's window is a `rate_limit_event` emitted on a Fable-model request itself (allowed or rejected). Verified live and from recorded streams.

2. `seven_day_overage_included` is the 7-day window that tracks the Fable usage that is included in the plan's Fable allowance (Max/premium-seat plans get up to 50% of the weekly limit on Fable at no extra cost; Pro/standard-seat plans get none included and must pay credits from the first token). Once that window's utilization reaches 1.0, the account would need "extra usage" (overage, billed at API rates) to keep going. `overageStatus: "rejected"` means the request to draw on overage/usage credits was rejected; `overageDisabledReason: "org_level_disabled"` means overage is disabled at the org level for this account; `isUsingOverage: false` confirms no money was spent. Usage credits/extra usage is a Team- and seat-based-Enterprise-only feature that only an org Owner/Primary Owner can turn on; individual Pro/Max subscribers (this account) have no self-serve setting to enable it. So no, there is no setting on this account that could let a Fable session continue by spending money — the account is not eligible for that feature at all, independent of the `org_level_disabled` flag. From docs, corroborated by the binary's `org_level_disabled` string and the live `overageStatus`/`isUsingOverage` fields.

3. The observed spent-state line is `Current week (Fable): 100% used · resets Sep 16, 5am (Asia/Riyadh)`. A regex that sits beside the two in the spec: `Current week \(Fable\): (\d+)% used · resets (.+?) \(`. The binary builds this line from the same generic per-window renderer as "Current week (all models)" and the observed "Current week (Sonnet only)" line (template: `` `Current week (${s.scope.model.display_name})` `` combined with a shared `"% used"` / `` \xB7 resets `` formatter), so the 0%-used and partial-percent states are expected to use the identical text shape with a different percentage and reset time — this is from-binary inference, not observed, and is marked unverified.

4. The refused session's shape (both the pre-recorded stream and a fresh live reproduction agree): `result` text is `"You've reached your Fable limit. Switch to another model, or manage usage credits at claude.ai/settings/usage?from=cc_cli_limit_message, to continue."`; `subtype: "success"` (not an error subtype, despite `is_error: true`); `terminal_reason: "api_error"`; `is_error: true`; `api_error_status: 429`; process exit code `1`; stderr empty. Of the harness's three hit-limit signals: (a) a `rate_limit_event` with `status: "rejected"` — yes, present, catches it; (b) a `result` with `api_error_status: 429` — yes, present, catches it; (c) a non-zero exit whose stderr or result text contains "hit your" and "limit" — the result text says "reached your Fable limit", not "hit your ... limit", so this substring match does NOT catch it as worded (needs "reached your" and "limit", not "hit your"). Verified live (both the recorded fixture and a fresh reproduction match exactly on `result`, `subtype`, `terminal_reason`, `is_error`, `api_error_status`, exit code, stderr).

5. No. `claude -p --model fable --fallback-model opus` still ends in the same Fable rejection: `rate_limit_event` fires with `status: "rejected"`, exit code 1, and every "model" field in the stream is `claude-fable-5-1` or `<synthetic>` — no Opus request was ever made, no fallback fired, and cost was $0. This confirms (for this refusal type at least) the part of research note 02 that says `--fallback-model` does not fire on a usage-limit rejection. Verified live.

6. (a) Yes, delegating to a Fable subagent from an allowed Haiku parent reproduces the exact same refusal inside the parent's own stream: the subagent's turn carries `subagent_type: "probe"` and `parent_tool_use_id` set, its "assistant" turn text is the identical "You've reached your Fable limit..." message, `error: "rate_limit"`, and a `system`/`task_updated` event marks the task `"status": "failed"` with an `error` string that also names the model `claude-fable-5-1` and the same rate_limit/429 detail. Critically, the *parent's own* `result` is unaffected: `is_error: false`, `terminal_reason: "completed"` — the parent session finishes normally, reporting that its subagent failed. No standalone `rate_limit_event` block was attached only to the subagent block; the one and only rejected `rate_limit_event` appears at the top level of the shared stream. (b) Not run — skipped to conserve the live-launch budget once (a) had already answered the core question (whether a subagent's Fable refusal propagates); marked unverified/not attempted, not contradicted.

7. No alias and no effort level escapes the window: `--model fable`, `--model 'fable[1m]'`, and `--model fable --effort low` all produced the identical two-event pattern (`five_hour`/`seven_day` allowed, then `seven_day_overage_included` rejected) and the identical refusal result. All three were free (no tokens, `total_cost_usd` in the low-cent range for the initial routing check only, well under a cent, and $0 on the direct `fable` runs). Fable's window resets at `resetsAt: 1789524000` = 2026-09-16 02:00:00 UTC, the *same* instant as the all-models `seven_day` window's `resetsAt` (also 1789524000). So Fable's weekly window and the all-models weekly window share one reset instant on this account — they are two separately-tracked utilization counters (Fable capped by its own included-allowance window) that reset together, not two independently-scheduled windows. Verified live.

## Findings

### 1. Do allowed sessions on other models carry Fable's window?

Recorded streams, `grep -rl --include=stream.jsonl rate_limit_event /tmp/wayline-*`, found 30 files. The three from `/tmp/wayline-ticket40-live2-9wzbrtg_/*/research/sessions/classifier/1/stream.jsonl` (model `claude-haiku-4-5-20251001`, confirmed via `grep -o '"model":"[^"]*"'`) and the sibling `writer` stream in `opus-writer` all show the same shape, e.g.:

```
{"type":"rate_limit_event","rate_limit_info":{"status":"allowed","resetsAt":1789255200,"rateLimitType":"five_hour","overageStatus":"rejected","overageDisabledReason":"org_level_disabled","isUsingOverage":false,"unifiedWindows":{"five_hour":{"utilization":0.18,"resetsAt":1789255200},"seven_day":{"utilization":0.64,"resetsAt":1789524000}}}}
```

No `seven_day_overage_included` key. Confirmed live: `claude -p "Reply with the word ok" --model haiku --effort low --output-format stream-json --verbose < /dev/null` (exit 0, result "ok", cost $0.019) produced:

```
{"type":"rate_limit_event","rate_limit_info":{"status":"allowed","resetsAt":1789294800,"rateLimitType":"five_hour","overageStatus":"rejected","overageDisabledReason":"org_level_disabled","isUsingOverage":false,"unifiedWindows":{"five_hour":{"utilization":0.23,"resetsAt":1789294800},"seven_day":{"utilization":0.7,"resetsAt":1789524000}}}}
```

Status: verified-live (both recorded and fresh).

### 2. Meaning of `seven_day_overage_included`, `overageStatus`, `overageDisabledReason`, `isUsingOverage`, and any money-spending path

- `support.claude.com/en/articles/15424964-claude-fable-models-on-your-plan` (WebFetch summary/quote): "you can use up to 50% of your weekly usage limits on Fable models at no extra cost" on Max/premium-Team/premium-Enterprise seats; once that 50% is used, "keep using Fable models with usage credits, or switch to another model." On Pro/standard-Team/standard-Enterprise seats: "Fable 5 and Fable 5.1 aren't included in your plan's usage limits. You can use them with usage credits" (no included allowance at all). This matches the field name: `seven_day_overage_included` = the 7-day window whose spend is *included* in the plan before overage would apply.
- `support.claude.com/en/articles/12005970-additional-usage-for-claude-for-work-team-and-enterprise-plans` (WebFetch summary/quote): usage credits/"extra usage" let Team and seat-based Enterprise members keep working past their included limits, billed at standard API rates; only Team/Enterprise Owners or Primary Owners can enable it; "Individual Pro/Max subscribers cannot self-enable usage credits" — "Once personal plan users hit their weekly limits, they must wait for the limits to reset — they cannot continue working by paying extra." This is from-docs (fetched summary, not a raw HTML dump), so treat the exact wording as paraphrase-level accurate, not a verbatim byte-for-byte quote.
- Live: the account's own recorded and live `rate_limit_info` consistently show `overageStatus: "rejected"`, `overageDisabledReason: "org_level_disabled"`, `isUsingOverage: false` on every Fable rejection observed (recorded fixture and three fresh live runs). Binary: `grep -a -o` for `overage` timed out in the sandboxed grep tool via a regex complexity error, so no additional binary strings were pulled beyond what the docs and live JSON already show.
- Conclusion: no setting can make a Fable session continue by spending money on this account, because usage credits are not an individual-plan feature at all — this is stronger than "the org disabled it," but the observed `org_level_disabled` reason is consistent with that. Status: from-docs (meaning/plan mechanics) + verified-live (the JSON fields as they appear for this account).

### 3. The `/usage` Fable line in each state

Live, right now: `claude -p "/usage" --output-format json` (`num_turns: 0`, `total_cost_usd: 0`) returned in `result`:

```
Current session: 24% used · resets Sep 13, 1:20pm (Asia/Riyadh)
Current week (all models): 71% used · resets Sep 16, 5am (Asia/Riyadh)
Current week (Fable): 100% used · resets Sep 16, 5am (Asia/Riyadh)
```

(Percentages ticked up slightly from the ticket's snapshot — 70%→71% all-models — consistent with the live test sessions run during this investigation.)

Regex for the Fable line, matching the shape of the other two lines already in the spec: `Current week \(Fable\): (\d+)% used · resets (.+?) \(`.

Binary evidence for the template (from `strings`/`grep -a -o` against `/home/bernaljp/.local/share/claude/versions/2.1.270`):

```
Current week (${s.scope.model.display_name})
```
in context:
```
.map((s)=>({title:`Current week (${s.scope.model.display_name})`,displayName:s.scope.model.display_name,limit:{utilization:s.percent,resets_at:s.resets_at}}))
```

and a live-observed sibling line for a *different* model window, `Current week (Sonnet only)`, confirms the same title template renders for any per-model window, with a shared percent/reset formatter (also seen as `` \xB7 resets ${Xu(s.resets_at,!0,!0,!0)} `` in the binary). 0%-used and partial states were not observed live (the account's Fable window is currently pinned at 100%) — these are unverified, inferred only from the shared template/formatter code path.

### 4. Full shape of the refused session

Recorded: `/tmp/wayline-ticket40-live-c2ivbjm_/ended-run/research/sessions/writer/1/stream.jsonl`. Live reproduction: `claude -p "Reply with the word ok" --model fable --output-format stream-json --verbose < /dev/null > fable-refused.jsonl 2> fable-refused.err.txt; echo "exit=$?"` gave `exit=1`, empty stderr, and:

```
result: "You've reached your Fable limit. Switch to another model, or manage usage credits at claude.ai/settings/usage?from=cc_cli_limit_message, to continue."
subtype: "success"
terminal_reason: "api_error"
is_error: true
api_error_status: 429
```

byte-for-byte identical result text and field shape to the recorded fixture (and to the `resume-1` continuation of that same recorded session, which repeats the same rejection).

Signal check against the spec's three hit-limit detectors:
- `rate_limit_event` with `status: "rejected"` — present (`{"type":"rate_limit_event","rate_limit_info":{"status":"rejected", ...`). Catches it.
- `result` with `api_error_status: 429` — present. Catches it.
- non-zero exit + stderr/result containing "hit your" and "limit" — exit is non-zero (1) and "limit" is present, but the text says "You've reached your Fable limit", not "hit your ... limit" — the literal two-substring rule as stated ("hit your" and "limit") does NOT match this wording. This is a gap in the spec's third detector for Fable specifically (still fine, since detectors 1 and 2 both catch it).

Status: verified-live.

### 5. `--fallback-model opus` on a Fable launch

`claude -p "Reply with the word ok" --model fable --fallback-model opus --output-format stream-json --verbose < /dev/null` → exit 1, `total_cost_usd: 0`. The stream's only non-rejected/non-synthetic `"model"` value is `claude-fable-5-1`; no Opus request appears anywhere in the stream. The `rate_limit_event` and `result` are identical in shape to the plain Fable refusal (question 4). So `--fallback-model` did not fire on this weekly-limit rejection — it costs nothing to confirm and it corrects nothing in note 02's specific claim here (note 02 already said fallback-model doesn't fire on usage limits; this is now verified-live for the Fable weekly-window case specifically, not just asserted from docs).

### 6. Fable subagent refusal inside an allowed parent

(a) `claude -p "Delegate this exactly to the probe agent and report back what it said: reply with the word ok" --model haiku --effort low --agents '{"probe": {"description": "probe", "prompt": "Reply ok", "model": "fable"}}' --output-format stream-json --verbose < /dev/null` → exit 0.

The subagent's assistant turn (tagged `"subagent_type":"probe"`, `"parent_tool_use_id":"toolu_01FJCdsSU9wkfWtpX5ybCRuW"`) carries the identical refusal text and `"error":"rate_limit"`. A `system`/`task_updated` event follows: `{"status":"failed", ..., "error":"Agent terminated early due to an API error: You've reached your Fable limit. ... (error type rate_limit, HTTP 429, ... model sent to the API: claude-fable-5-1)"}`, then a `task_notification` with the same `status: "failed"`. The parent's own final `result` block: `is_error: false`, `terminal_reason: "completed"`, `subtype: "success"`, text: "The probe agent failed due to a rate limit: I've reached the Fable model limit. ... You may need to switch to another model or manage usage credits...". So the parent session is not itself terminated or marked as errored by its subagent's Fable refusal — the parent sees it as a normal (if unsuccessful) tool/task result and finishes cleanly. A pacing/watchdog that only checks the *parent's* top-level `is_error`/`terminal_reason` would miss this refusal entirely; it has to also scan for `subagent_type` + `error: "rate_limit"` on nested assistant turns, or for `task_updated`/`task_notification` events with `status: "failed"` whose `error` text names Fable.

(b) Not attempted — skipped after (a) already gave a clear, directly-relevant answer (the propagation behavior), to keep total live launches near the ~10 cap. Unverified for the Workflow `agent()` path specifically.

### 7. Alias/effort escape and reset-time comparison

Three separate live refusals, all showing the identical two-`rate_limit_event` pattern (allowed `five_hour`/`seven_day`, then rejected `seven_day_overage_included`) and identical `result` text/`api_error_status: 429`/exit 1:

- `--model fable` (question 4/5 baseline)
- `--model 'fable[1m]'`
- `--model fable --effort low`

None escaped. Sample event from the `fable[1m]` run:
```
{"status":"rejected","resetsAt":1789524000,"rateLimitType":"seven_day_overage_included", ..., "unifiedWindows":{"five_hour":{...},"seven_day":{...},"seven_day_overage_included":{"utilization":1,"resetsAt":1789524000}}}
```

Reset-time comparison: `date -u -d @1789524000` → `Wed Sep 16 02:00:00 AM UTC 2026`. Both the all-models `seven_day` window and the Fable `seven_day_overage_included` window carry `resetsAt: 1789524000` in every event observed (recorded and live) — they reset at the same instant on this account, even though they are tracked as separate utilization counters (one hits 100% while the other sits at 0.64–0.70). The live `/usage` text agrees: both "Current week (all models)" and "Current week (Fable)" show "resets Sep 16, 5am (Asia/Riyadh)".

### Correction to research note 02

`.scratch/harness/issues/02-unattended-auth-and-usage-limits.md` (line 21) states: "Session and weekly limits are shared across models anyway." This is wrong for Fable specifically: Fable has its own `seven_day_overage_included` utilization counter, distinct from the all-models `seven_day` counter (0.64–0.70 vs 1.0 in every sample above), even though the two counters happen to reset at the same instant on this account. The note's adjacent claim ("`--fallback-model` never fires on rate or usage limits") is confirmed correct, now verified live for the Fable weekly-window case specifically (question 5 above), not just asserted from docs.

## Unverified items

- The exact `/usage` text for Fable at 0% used and at a partial percentage (e.g. 45%) — the account's Fable window is pinned at 100% for the whole investigation window, so only the spent-state text was observed. The 0%/partial text is inferred from the shared per-model-window template in the binary, not observed.
- Question 6(b), the Workflow `agent()` refusal on Fable — not attempted, to stay within the live-launch budget once 6(a) answered the core propagation question.
- Whether any other, non-account-visible org setting could enable overage (e.g., a Team/Enterprise org owner's console toggle) — not testable from this individual account; answered from docs only, not from a live account that has such a toggle.
