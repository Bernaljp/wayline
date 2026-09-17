# 01 - Model versions the subscription serves: names, windows, and retirement

Ticket: [Bernaljp/wayline #130](https://github.com/Bernaljp/wayline/issues/130), child of the map
[Finer difficulty tiers using more model versions](https://github.com/Bernaljp/wayline/issues/129).

- **Claude Code version:** 2.1.274 (`claude --version`), binary at `/home/bernaljp/.local/share/claude/versions/2.1.274`.
- **Date of the probes:** 2026-09-17, between 15:46 and 16:40 Asia/Riyadh.
- **Account:** the owner's subscription, `apiKeySource: "none"` in every `init` envelope, `overageStatus: "rejected"` with `overageDisabledReason: "org_level_disabled"` (no paid overage, as decision 15 already records).
- **How the probes were run:** from `/tmp/mv-probe.Wt1q` (outside `~/.claude` and outside the repository, so no project `CLAUDE.md` loads), one turn each:
  `claude -p --model <name> --output-format stream-json --verbose --max-turns 1 "Reply with the word ok."`
- **Window at the start:** `Current session: 20%`, `Current week (all models): 30%`, `Current week (Fable): 39%`, so the Fable probes were allowed (the ticket's skip rule is 80%).

## 1. The names the account accepts

Aliases, from `claude -p "/model"` (it answers non-interactively, no turn on a model):

```
Current model: `Opus 5 (1M context)` (effort: high)
Usage: /model <name>. Available: sonnet, opus, haiku, fable, best, sonnet[1m], opus[1m], fable[1m], opusplan, default, or a full model ID.
```

`claude --help` says `--model` takes "an alias for the latest model (e.g. 'fable', 'opus', or 'sonnet') or a model's full name (e.g. 'claude-fable-5')".

| Name probed | Accepted | `init`/`result` model | Window counted | Notes |
| --- | --- | --- | --- | --- |
| `fable` | yes | `claude-fable-5-1` | five_hour, seven_day, **seven_day_overage_included** | the alias is Fable **5.1**, not 5.0 |
| `claude-fable-5-1` | yes | `claude-fable-5-1` | same as above | Fable 5.1 |
| `claude-fable-5` | yes | `claude-fable-5` | same as above | Fable 5.0, the version the owner named |
| `claude-fable-5-0` | no | echoed, then 404 | none | not a name |
| `fable-5` | no | echoed, then 404 | none | bare short forms are not names |
| `best` | yes | `claude-fable-5-1` | Fable window | alias for the best family, resolves to Fable |
| `opus` | yes | `claude-opus-5` | five_hour, seven_day | |
| `claude-opus-5` | yes | `claude-opus-5` | five_hour, seven_day | |
| `claude-opus-4-8` | yes | `claude-opus-4-8` | five_hour, seven_day | Opus 4.8, the version the owner named |
| `claude-opus-4-7` | yes | `claude-opus-4-7` | five_hour, seven_day | |
| `claude-opus-4-6` | yes | `claude-opus-4-6` | five_hour, seven_day | |
| `claude-opus-4-5` | yes | `claude-opus-4-5` (assistant messages say `claude-opus-4-5-20251101`) | five_hour, seven_day | |
| `claude-opus-4-5-20251101` | yes | `claude-opus-4-5-20251101` | five_hour, seven_day | the dated id works too |
| `claude-opus-4-1`, `claude-opus-4-1-20250805`, `claude-opus-4-0`, `claude-opus-4-20250514` | yes, but **silently remapped** | `claude-opus-5` | five_hour, seven_day | the CLI rewrites retired Opus 4 and 4.1 ids to the current Opus before the request; `init` already says `claude-opus-5` |
| `claude-opus-4` | no | echoed, then 404 | none | |
| `sonnet` | yes | `claude-sonnet-5` | five_hour, seven_day | |
| `claude-sonnet-5` | yes | `claude-sonnet-5` | five_hour, seven_day | |
| `claude-sonnet-4-6` | yes | `claude-sonnet-4-6` | five_hour, seven_day | |
| `claude-sonnet-4-5` | yes | `claude-sonnet-4-5` (assistant: `claude-sonnet-4-5-20250929`) | five_hour, seven_day | |
| `claude-sonnet-4-5-20250929` | yes | `claude-sonnet-4-5-20250929` | five_hour, seven_day | |
| `claude-sonnet-4-0`, `claude-sonnet-4`, `claude-sonnet-4-20250514` | no | echoed, then 404 | none | retired; no remap for Sonnet 4 |
| `haiku` | yes | `claude-haiku-4-5-20251001` | five_hour, seven_day | the alias resolves to the dated id |
| `claude-haiku-4-5` | yes | `claude-haiku-4-5` | five_hour, seven_day | |
| `claude-haiku-4-5-20251001` | yes | `claude-haiku-4-5-20251001` | five_hour, seven_day | |
| `claude-3-7-sonnet-20250219`, `claude-3-5-haiku-20241022` | no | echoed, then 404 | none | retired 2026-02-19; the CLI also prints an end-of-life warning on stderr |
| `claude-mythos-5`, `claude-mythos-5-1`, `mythos` | no | echoed, then 404 | none | in the CLI's catalog, not served to this account |
| `default` | yes | `claude-opus-5[1m]` | five_hour, seven_day | the account's configured default, 1M context |
| `opus[1m]` | yes | `claude-opus-5[1m]` | five_hour, seven_day | |
| `claude-opus-4-8[1m]` | yes | `claude-opus-4-8[1m]` (assistant: `claude-opus-4-8`) | five_hour, seven_day | a versioned name takes the `[1m]` suffix |
| `claude-sonnet-4-6[1m]` | no | 429, `rate_limit_event` with `status: rejected` | none | "API Error: Usage credits required for 1M context - turn on usage credits at claude.ai/sett..." |
| `claude-haiku-4-5[1m]` | no | 400 | none | "The long context beta is not yet available for this subscription." |
| `opusplan` | yes | `claude-sonnet-5` | five_hour, seven_day | in `-p` it runs the Sonnet resolver; Opus is for plan mode |
| `Claude-Opus-4-8` | yes | `Claude-Opus-4-8` (assistant: `claude-opus-4-8`) | five_hour, seven_day | **case-insensitive**, and the envelope echoes the spelling given |
| `claude-opus-4.8`, `opus-4-8`, `sonnet-4-6` | no | echoed, then 404 | none | dots and bare short forms are not names |
| `claude-opus-9-9` | no | echoed, then 404 | none | the bogus-name control |

**Rungs actually available to the harness**, newest first per family:

`claude-fable-5-1` (alias `fable`, `best`), `claude-fable-5`, `claude-opus-5` (alias `opus`), `claude-opus-4-8`, `claude-opus-4-7`, `claude-opus-4-6`, `claude-opus-4-5`, `claude-sonnet-5` (alias `sonnet`), `claude-sonnet-4-6`, `claude-sonnet-4-5`, `claude-haiku-4-5` (alias `haiku`). Eleven rungs across four families.

**No alias exists for an older version.** Every alias (`sonnet`, `opus`, `haiku`, `fable`, `best`, `default`, `opusplan`, and their `[1m]` forms) points at the newest served model of its family or at the account's configured default. An older version is named in full, never by alias. The CLI does carry env vars that repoint a family alias, `ANTHROPIC_DEFAULT_FABLE_MODEL`, `ANTHROPIC_DEFAULT_OPUS_MODEL`, `ANTHROPIC_DEFAULT_SONNET_MODEL`, `ANTHROPIC_DEFAULT_HAIKU_MODEL` (strings in the 2.1.274 bundle), but the harness names versions on `--model` and needs none of them.

## 2. What an unknown, retired, or not-served name returns

Identical shape for all three, which is the good news for the harness: one failure to recognize.

```json
{"type": "result", "subtype": "success", "is_error": true, "duration_ms": 856, "num_turns": 1,
 "result": "There's an issue with the selected model (claude-opus-9-9). It may not exist or you may not have access to it. Run --model to pick a different model.",
 "session_id": "c434eb79-483f-4fae-bf56-b89ffc0e5b78", "total_cost_usd": 0.0009530000000000001}
```

- **Exit code:** 1.
- **`is_error`:** `true`, while `subtype` stays `"success"`. A reader that keys on `subtype` alone misses this.
- **`api_error_status`:** 404 (the `[1m]` refusals differ: 400 for Haiku's long-context beta, 429 for the Sonnet 1M credit refusal).
- **Text:** `There's an issue with the selected model (<name>). It may not exist or you may not have access to it. Run --model to pick a different model.` The name is echoed exactly as given.
- **Assistant message:** one message with `"model": "<synthetic>"` carrying that text.
- **Cost:** about $0.00094 of `claude-haiku-4-5-20251001`, the preflight call the CLI makes before the session model is used. `modelUsage` holds only Haiku, which is a clean test: no entry for the requested model means the model never ran.
- **`init` envelope:** still emitted, with `"model": "<the name as given>"`. The `init` model is **not** proof the model exists.
- **`rate_limit_event`:** still emitted, `status: allowed`, the normal windows. A 404 costs no window.
- **stderr:** `[claude-code:unrecognized_model] {"model":"claude-opus-9-9","query_source":"sdk"}` for a name the CLI's own catalog does not hold. For a name in the catalog but retired (`claude-sonnet-4-0`, `claude-3-7-sonnet-20250219`), stderr instead carries the deprecation warning: `The model 'claude-sonnet-4-0' is deprecated and will reach end-of-life on June 15th, 2026 / Please migrate to a newer model. Visit https://docs.anthropic.com/en/docs/resources/model-deprecations ...`. Both still 404.

**A retired name can be rescued.** `--fallback-model` fires on a not-found primary, and the stream says so:

```json
{"type":"system","subtype":"model_fallback","uuid":"ddb27a89-...","trigger":"model_not_found",
 "original_model":"claude-opus-9-9","fallback_model":"claude-opus-4-8",
 "content":"Switched to Opus 4.8 because claude-opus-9-9 is not available","session_id":"7d6f4427-..."}
```

`claude -p --model claude-opus-9-9 --fallback-model claude-opus-4-8` exits 0, runs on Opus 4.8, and `modelUsage` holds `claude-opus-4-8`. This is a cheap safety net for a rung the subscription stops serving, and it is a different trigger from the overload case; decision 15's finding that `--fallback-model` does not fire on a Fable weekly refusal still stands.

**The legacy remap is a trap.** `claude-opus-4-1` and `claude-opus-4-20250514` are retired on the API (see section 5), yet they exit 0 and run on `claude-opus-5`, silently and at Opus 5 prices. The bundle holds the list and the switch:

```js
var ASe=["claude-opus-4-20250514","claude-opus-4-1-20250805","claude-opus-4-0","claude-opus-4-1"];
function iTe(e){return ASe.includes(e)}
function bYe(){return!a.CLAUDE_CODE_DISABLE_LEGACY_MODEL_REMAP}
```

So a harness that validates a policy's model names by "did it exit 0" would accept `claude-opus-4-1` as a rung and get Opus 5. The check that catches it is `init.model` (or `modelUsage`) differing from the name asked for.

## 3. Which window each version counts against

`/usage` on this account prints three lines, and only Fable has a line of its own:

```
Current session: 20% used - resets Sep 17, 6:30pm (Asia/Riyadh)
Current week (all models): 30% used - resets Sep 23, 5am (Asia/Riyadh)
Current week (Fable): 39% used - resets Sep 23, 4:59am (Asia/Riyadh)
```

Every request emits a `rate_limit_event` for the preflight Haiku call with two windows. A Fable request emits a **second** event that adds the Fable window:

```json
{"status":"allowed","rateLimitType":"five_hour","overageStatus":"rejected","overageDisabledReason":"org_level_disabled","isUsingOverage":false,
 "unifiedWindows":{"five_hour":{"utilization":0.21,"resetsAt":1789659000},
                   "seven_day":{"utilization":0.3,"resetsAt":1790128800},
                   "seven_day_overage_included":{"utilization":0.39,"resetsAt":1790128800}}}
```

**An older Fable counts in the Fable week.** `claude-fable-5` and `claude-fable-5-1` both returned `seven_day_overage_included: {utilization: 0.39}`, the same 39% the `/usage` Fable line showed. Falling back from Fable 5.1 to Fable 5.0 buys nothing on that window, which settles the tempting idea of a "cheaper Fable rung".

Opus 4.5 through 5, Sonnet 4.5 through 5, and Haiku 4.5 all returned `five_hour` and `seven_day` only, never `seven_day_overage_included`. So every non-Fable version, old or new, shares the all-models week, exactly as decision 15 says, and no older version has a window of its own.

`rateLimitType` was `five_hour` on every allowed event, whatever the model. The only `rejected` event in this run came from the Sonnet 1M refusal, and it carried no `unifiedWindows` at all: `{"status":"rejected","resetsAt":1790812800,"overageDisabledReason":"org_level_disabled","isUsingOverage":false}`.

Four Fable calls (two on 5.1, one on 5.0, one through `best`) moved `Current week (Fable)` from 39% to 39%: the line is integer percent, so a one-turn probe is below its resolution. The all-models week moved 30% to 31% over the whole probe run of about 45 calls.

## 4. `--effort` and `--fallback-model` with versioned names

**`--effort` is accepted for every version at every level.** Probed and all exit 0 with no warning: `claude-opus-4-8` low and max, `claude-opus-4-7` xhigh, `claude-opus-4-6` xhigh and max, `claude-opus-4-5` high, `claude-sonnet-4-6` xhigh, `claude-sonnet-4-5` medium, `claude-sonnet-5` max, `claude-haiku-4-5` low, `claude-fable-5` low, `claude-fable-5-1` max.

Accepted is not the same as honored. An unknown level is the only thing the CLI complains about:

```
Warning: Unknown --effort value 'ultra' - ignoring it and using the default effort. Valid values: low, medium, high, xhigh, max.
```

The bundle's catalog says which versions really take effort. A version whose `capabilities` lack `"effort"` ignores the flag silently, and one whose capabilities lack `"xhigh_effort"` ignores `xhigh` silently:

| Version | effort | max | xhigh | default effort | effort cost index (low/medium/high/xhigh/max) |
| --- | --- | --- | --- | --- | --- |
| claude-fable-5-1 | yes | yes | yes | high | 0.75 / 0.86 / 1 / 1.38 / 1.74 |
| claude-fable-5 | yes | yes | yes | high | 0.6 / 0.77 / 1 / 1.74 / 1.91 |
| claude-opus-5 | yes | yes | yes | high | 0.67 / 0.76 / 1 / 1.6 / 1.7 |
| claude-opus-4-8 | yes | yes | yes | high | 0.72 / 0.9 / 1 / 1.65 / 1.88 |
| claude-opus-4-7 | yes | yes | yes | xhigh | not in the catalog entry |
| claude-opus-4-6 | yes | yes | **no** | not set | not in the catalog entry |
| claude-opus-4-5 | **no** | no | no | not set | not applicable |
| claude-sonnet-5 | yes | yes | yes | high | 0.47 / 0.74 / 1 / 2.41 / 5.59 |
| claude-sonnet-4-6 | yes | yes | **no** | not set | not in the catalog entry |
| claude-sonnet-4-5 | **no** | no | no | not set | not applicable |
| claude-haiku-4-5 | **no** | no | no | not supported (docs) | not applicable |

Source: the model catalog embedded in the 2.1.274 bundle, for example
`{id:"claude-opus-4-8",family:"opus",display_name:"Opus 4.8",...,capabilities:["effort","max_effort","xhigh_effort","adaptive_thinking","mid_conv_system","mid_conv_tool_change","context_management","fast_mode","lean_prompt"],default_effort:"high",effort_cost_index:{low:0.72,medium:0.9,high:1,xhigh:1.65,max:1.88}}`,
and the guard `if(n.includes("claude-3-")||n==="claude-opus-4-0"||n==="claude-opus-4-1"||n==="claude-opus-4-5"||n==="claude-opus-4-6"||n==="claude-sonnet-4-0"||n==="claude-sonnet-4-5"||n==="claude-sonnet-4-6"||n==="claude-haiku-4-5")return!1;` inside the `xhigh_effort` check. The docs agree: Haiku 4.5's default effort is "Not supported".

The `effort_cost_index` is the most useful number here for finer tiers: within a version, `max` costs 1.7 to 1.9 times `high` on Opus and Fable, but 5.6 times on Sonnet 5, so "Sonnet at max" is a poor rung.

**`--fallback-model` accepts versioned names.** The parser took `claude-opus-4-8`, the comma list `claude-opus-4-8,claude-sonnet-4-5`, `claude-fable-5`, and even the nonsense `not-a-model-xyz` (no validation at parse time; the primary ran and the fallback was never reached). Only the not-found case above proved a fallback actually firing.

## 5. Published deprecation and retirement

From [Model deprecations](https://platform.claude.com/docs/en/about-claude/model-deprecations), read 2026-09-17. Nothing the account serves is deprecated; every served version has a "not sooner than" retirement commitment, and Anthropic promises at least 60 days' notice.

| API model name | State | Deprecated | Tentative retirement |
| --- | --- | --- | --- |
| claude-fable-5-1 | Active | N/A | Not sooner than September 1, 2027 |
| claude-fable-5 | Active | N/A | Not sooner than June 9, 2027 |
| claude-opus-5 | Active | N/A | Not sooner than July 24, 2027 |
| claude-opus-4-8 | Active | N/A | Not sooner than May 28, 2027 |
| claude-opus-4-7 | Active | N/A | Not sooner than April 16, 2027 |
| claude-opus-4-6 | Active | N/A | Not sooner than February 5, 2027 |
| claude-opus-4-5-20251101 | Active | N/A | Not sooner than November 24, 2026 |
| claude-sonnet-5 | Active | N/A | Not sooner than June 30, 2027 |
| claude-sonnet-4-6 | Active | N/A | Not sooner than February 17, 2027 |
| claude-sonnet-4-5-20250929 | Active | N/A | Not sooner than September 29, 2026 |
| claude-haiku-4-5-20251001 | Active | N/A | Not sooner than October 15, 2026 |
| claude-opus-4-1-20250805 | Retired | June 5, 2026 | August 5, 2026 (replacement `claude-opus-4-8`) |
| claude-opus-4-20250514 | Retired | April 14, 2026 | June 15, 2026 (replacement `claude-opus-4-8`) |
| claude-sonnet-4-20250514 | Retired | April 14, 2026 | June 15, 2026 (replacement `claude-sonnet-4-6`) |
| claude-3-7-sonnet-20250219 | Retired | October 28, 2025 | February 19, 2026 |
| claude-3-5-haiku-20241022 | Retired | December 19, 2025 | February 19, 2026 |

The two nearest dates matter for the rung table: **claude-sonnet-4-5-20250929 from September 29, 2026** (twelve days after this note) and **claude-haiku-4-5-20251001 from October 15, 2026**. Both are "not sooner than", not scheduled retirements, but a rung table that leans on Sonnet 4.5 or Haiku 4.5 is the first to need re-checking.

Also from the docs, for the amendment's cost and context work ([Models overview](https://platform.claude.com/docs/en/about-claude/models/overview), read 2026-09-17): Fable 5.1 is $10/$50 per MTok, Opus 5 $5/$25, Sonnet 5 $2/$10, Haiku 4.5 $1/$5. Context windows are 1M for Fable 5.1, Fable 5, Opus 5, Opus 4.8, Opus 4.7 and Sonnet 5; 200K for Opus 4.6, Opus 4.5, Sonnet 4.6, Sonnet 4.5 and Haiku 4.5 (bundle `context.window`, confirmed by the `contextWindow` field in each probe's `modelUsage`). The docs list Fable 5, Opus 4.8, 4.7, 4.6, 4.5, Sonnet 4.6 and Sonnet 4.5 as "Legacy models (still available)", which is the state before Deprecated: no updates, may be deprecated later.

## 6. What this hands the map

1. Eleven named rungs exist, and every one of them is spelled in full on `--model`; no alias reaches an older version.
2. A Fable rung below Fable 5.1 does not dodge the Fable week. `claude-fable-5` counts in `seven_day_overage_included` exactly as 5.1 does, so the fallback ladder's only real step out of the Fable window is still Opus.
3. The cheap steps the map was looking for are inside Opus and Sonnet: Opus 5 to Opus 4.8 to 4.7 to 4.6 to 4.5, and Sonnet 5 to 4.6 to 4.5, all on the all-models week, with effort as a second axis on the versions that take it.
4. Validating a policy's names is cheap and safe: a 404 probe costs $0.0009 of Haiku and no window. The check must compare `init.model` (or `modelUsage`) against the name asked for, because a retired Opus 4 or 4.1 name exits 0 on Opus 5.
5. A version the subscription stops serving has a machine-readable rescue: `--fallback-model <versioned name>` plus the `system` / `model_fallback` envelope with `trigger: "model_not_found"`.
6. Effort is not uniform. `xhigh` is silently ignored on Opus 4.6 and Sonnet 4.6, and effort entirely on Opus 4.5, Sonnet 4.5 and Haiku 4.5, so a rung table keyed on (version, effort) needs the capability column above.

## Sources

- Live probes, Claude Code 2.1.274, 2026-09-17, raw streams under `/tmp/mv-probe.Wt1q/out/` (not committed; the excerpts above are verbatim).
- `claude --help`, `claude -p "/model"`, `claude -p "/usage"`, same date and version.
- The model catalog and gating code inside the 2.1.274 bundle (`/home/bernaljp/.local/share/claude/versions/2.1.274`), read with `strings`.
- [Model deprecations](https://platform.claude.com/docs/en/about-claude/model-deprecations), read 2026-09-17.
- [Models overview](https://platform.claude.com/docs/en/about-claude/models/overview), read 2026-09-17.
- Prior art in the harness: spec decision 15 and the research note on `research/fable-weekly-window`.
