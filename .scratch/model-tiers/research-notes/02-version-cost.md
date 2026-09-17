# 02 - What each model version costs of the usage windows

Ticket: [Bernaljp/wayline #131](https://github.com/Bernaljp/wayline/issues/131), child of the map
[Finer difficulty tiers using more model versions](https://github.com/Bernaljp/wayline/issues/129).
Blocked by, and built on, [Model versions the subscription serves](https://github.com/Bernaljp/wayline/issues/130)
and its note `01-model-versions.md` on the branch `research/model-versions`.

- **Claude Code version:** 2.1.274, binary at `/home/bernaljp/.local/share/claude/versions/2.1.274`.
- **Date:** 2026-09-17, about 17:20 to 17:35 Asia/Riyadh.
- **Account:** the owner's subscription. No paid overage (`overageStatus: "rejected"`, `overageDisabledReason: "org_level_disabled"`).
- **Windows before the probe:** `Current session: 26%`, `Current week (all models): 31%`, `Current week (Fable): 39%`. Fable was well under the ticket's 80% skip rule, so both Fable rungs were probed.
- **Total spend of the live probe:** about **$1.90** of list-price token value across eleven runs, of which $0.77 was Fable.

## The short answer

1. **Per-token price does not step by version inside a family.** All five served Opus versions are $5 / $25 per MTok. Both Fable versions are $10 / $50. There is no cheaper Opus rung and no cheaper Fable rung on price. The only price step inside a family runs the wrong way: Sonnet 4.6 and Sonnet 4.5 are **$3 / $15**, more expensive than Sonnet 5 at **$2 / $10**.
2. **On an identical task the cost does step by version, but the step comes from the tokenizer and the prompt variant, not from price.** Measured, Opus 4.7 is the most expensive Opus rung (1.29x Opus 5), Opus 4.6 and Opus 4.5 the cheapest (0.64x Opus 5), and Opus 4.8 sits level with Opus 5 (1.02x).
3. **Window utilization is not reported finely enough to resolve any of this.** `rate_limit_event` gives `utilization` to two decimals, which is 1% of a window. Eleven matched short tasks, about $1.90 of list value, moved the five-hour window by one reported step and the all-models week by none. A single short task is roughly an order of magnitude below the resolution of one step.
4. **What the measurement can still establish** is the token counts and the list-price valuation the CLI itself computes, which are exact, per model, and reproducible. Those are the numbers the rung table should be built on.

## 1. The model catalog in the installed CLI, verbatim

The 2.1.274 bundle carries a model catalog with a `pricing_tiers` map and a per-model `effort_cost_index`. Read with `strings` from the binary above.

### The price tiers

```
pricing_tiers:{tier_2_10:{input:2,output:10,cache_write_5m:2.5,cache_write_1h:4,cache_read:0.2,web_search:0.01},tier_3_15:{input:3,output:15,cache_write_5m:3.75,cache_write_1h:6,cache_read:0.3,web_search:0.01},tier_5_25:{input:5,output:25,cache_write_5m:6.25,cache_write_1h:10,cache_read:0.5,web_search:0.01},tier_15_75:{input:15,output:75,cache_write_5m:18.75,cache_write_1h:30,cache_read:1.5,web_search:0.01},tier_10_50:{input:10,output:50,cache_write_5m:12.5,cache_write_1h:20,cache_read:1,web_search:0.01},tier_10_50_cache_read_0_25:{input:10,output:50,cache_write_5m:12.5,cache_write_1h:20,cache_read:0.25,web_search:0.01},haiku_35:{input:0.8,output:4,cache_write_5m:1,cache_write_1h:1.6,cache_read:0.08,web_search:0.01},haiku_45:{input:1,output:5,cache_write_5m:1.25,cache_write_1h:2,cache_read:0.1,web_search:0.01}}
```

All figures are USD per million tokens. They match Anthropic's published pricing page exactly (section 3), so the CLI's `total_cost_usd` is a faithful list-price valuation of the tokens a run spent.

### The eleven served entries, verbatim

```
{id:"claude-haiku-4-5",family:"haiku",display_name:"Haiku 4.5",knowledge_cutoff:"February 2025",provider_ids:{first_party:"claude-haiku-4-5-20251001",bedrock:"us.anthropic.claude-haiku-4-5-20251001-v1:0",vertex:"claude-haiku-4-5@20251001",foundry:"claude-haiku-4-5",anthropic_aws:"claude-haiku-4-5-20251001",anthropic_google_cloud:"claude-haiku-4-5-20251001",mantle:"anthropic.claude-haiku-4-5",gateway:"claude-haiku-4-5-20251001"},vertex_region_env_var:"VERTEX_REGION_CLAUDE_HAIKU_4_5",context:{window:200000,supports_1m_suffix:!0},max_output_tokens:{default:32000,upper:64000},pricing:"haiku_45",capabilities:["context_management"],advisor_rank:1}

{id:"claude-sonnet-4-5",family:"sonnet",display_name:"Sonnet 4.5",knowledge_cutoff:"January 2025",provider_ids:{first_party:"claude-sonnet-4-5-20250929",...},eager_input_streaming:{vertex:!0},vertex_region_env_var:"VERTEX_REGION_CLAUDE_4_5_SONNET",fallback_3p:"claude-sonnet-4-0",context:{window:200000,supports_1m_beta:!0,supports_1m_suffix:!0},max_output_tokens:{default:32000,upper:64000},pricing:"tier_3_15",capabilities:["context_management"]}

{id:"claude-sonnet-4-6",family:"sonnet",display_name:"Sonnet 4.6",knowledge_cutoff:"August 2025",...,fallback_3p:"claude-sonnet-4-5",context:{window:200000,supports_1m_beta:!0,supports_1m_suffix:!0},max_output_tokens:{default:32000,upper:128000},pricing:"tier_3_15",capabilities:["effort","max_effort","adaptive_thinking","context_management"],advisor_rank:2}

{id:"claude-sonnet-5",family:"sonnet",display_name:"Sonnet 5",knowledge_cutoff:"January 2026",...,fallback_3p:"claude-sonnet-4-6",context:{window:1e6,native_1m:!0,native_1m_3p:{bedrock:!0,vertex:!0,foundry:!0},supports_1m_beta:!0},max_output_tokens:{default:64000,upper:128000},pricing:"tier_2_10",capabilities:["effort","max_effort","xhigh_effort","adaptive_thinking","mid_conv_system","context_management"],default_effort:"high",effort_cost_index:{low:0.47,medium:0.74,high:1,xhigh:2.41,max:5.59},image_limits:{maxWidth:2000,maxHeight:2000},advisor_rank:3}

{id:"claude-opus-4-5",family:"opus",display_name:"Opus 4.5",knowledge_cutoff:"May 2025",provider_ids:{first_party:"claude-opus-4-5-20251101",...},fallback_3p:"claude-opus-4-1",context:{window:200000,supports_1m_suffix:!0},max_output_tokens:{default:32000,upper:64000},pricing:"tier_5_25",capabilities:["context_management"]}

{id:"claude-opus-4-6",family:"opus",display_name:"Opus 4.6",knowledge_cutoff:"May 2025",...,fallback_3p:"claude-opus-4-5",context:{window:200000,supports_1m_beta:!0,supports_1m_suffix:!0},max_output_tokens:{default:64000,upper:128000},pricing:"tier_5_25",capabilities:["effort","max_effort","adaptive_thinking","context_management"],advisor_rank:3}

{id:"claude-opus-4-7",family:"opus",display_name:"Opus 4.7",knowledge_cutoff:"January 2026",...,fallback_3p:"claude-opus-4-6",context:{window:1e6,native_1m:!0,supports_1m_beta:!0,supports_1m_suffix:!0},max_output_tokens:{default:64000,upper:128000},pricing:"tier_5_25",capabilities:["effort","max_effort","xhigh_effort","adaptive_thinking","context_management"],default_effort:"xhigh",image_limits:{maxWidth:2000,maxHeight:2000},advisor_rank:4}

{id:"claude-opus-4-8",family:"opus",display_name:"Opus 4.8",knowledge_cutoff:"January 2026",...,fallback_3p:"claude-opus-4-7",context:{window:1e6,native_1m:!0,supports_1m_beta:!0,supports_1m_suffix:!0},max_output_tokens:{default:64000,upper:128000},pricing:"tier_5_25",capabilities:["effort","max_effort","xhigh_effort","adaptive_thinking","mid_conv_system","mid_conv_tool_change","context_management","fast_mode","lean_prompt"],default_effort:"high",effort_cost_index:{low:0.72,medium:0.9,high:1,xhigh:1.65,max:1.88},image_limits:{maxWidth:2000,maxHeight:2000},advisor_rank:4}

{id:"claude-opus-5",family:"opus",display_name:"Opus 5",knowledge_cutoff:"May 2026",...,fallback_3p:"claude-opus-4-8",context:{window:1e6,native_1m:!0,supports_1m_beta:!0,supports_1m_suffix:!0},max_output_tokens:{default:64000,upper:128000},pricing:"tier_5_25",capabilities:["effort","max_effort","xhigh_effort","adaptive_thinking","mid_conv_system","mid_conv_tool_change","context_management","thinking_disabled_effort_cap","fast_mode","lean_prompt","refusal_fallback","opus_5_prompt_bundle"],default_effort:"high",effort_cost_index:{low:0.67,medium:0.76,high:1,xhigh:1.6,max:1.7},image_limits:{maxWidth:2000,maxHeight:2000},advisor_rank:4}

{id:"claude-fable-5",family:"fable",display_name:"Fable 5",knowledge_cutoff:"January 2026",...,fallback_3p:"claude-opus-5",context:{window:1e6,native_1m:!0,supports_1m_beta:!0},max_output_tokens:{default:64000,upper:128000},pricing:"tier_10_50",capabilities:["effort","max_effort","xhigh_effort","adaptive_thinking","rejects_disabled_thinking","mid_conv_system","mid_conv_tool_change","context_management","lean_prompt","fable_5_mitigations","refusal_fallback"],default_effort:"high",effort_cost_index:{low:0.6,medium:0.77,high:1,xhigh:1.74,max:1.91},image_limits:{maxWidth:2000,maxHeight:2000},advisor_rank:5}

{id:"claude-fable-5-1",family:"fable",display_name:"Fable 5.1",knowledge_cutoff:"June 2026",...,fallback_3p:"claude-fable-5",context:{window:1e6,native_1m:!0,supports_1m_beta:!0},max_output_tokens:{default:64000,upper:128000},pricing:"tier_10_50_cache_read_0_25",capabilities:["effort","max_effort","xhigh_effort","adaptive_thinking","rejects_disabled_thinking","mid_conv_system","mid_conv_tool_change","per_turn_effort","context_management","lean_prompt","fable_5_mitigations","refusal_fallback","fable_5_1_prompt_bundle"],default_effort:"high",effort_cost_index:{low:0.75,medium:0.86,high:1,xhigh:1.38,max:1.74},image_limits:{maxWidth:2000,maxHeight:2000},advisor_rank:5}
```

The `provider_ids` maps and a few unchanged fields are elided with `...` for length; the pricing, capability, effort and context fields are verbatim. The two Mythos entries in the catalog are not served to this account (note 01) and are left out.

### What `effort_cost_index` means

It is a table of **relative estimated cost by effort level, normalized within one model** so that the model's `high` level is 1. The CLI uses it in exactly one place, the effort picker, through:

```js
function j7e(h,v){if(!S_(h))return null;let O=Jl(We(h))?.effort_cost_index;if(!O)return null;let Q=O[v],ne=O[XO(h)];if(Q===void 0||!ne)return null;return Q/ne}
function pEt(h){if(h<0.1)return`~${Math.max(0.01,Math.round(h*100)/100).toFixed(2)}x`;let v=Math.round(h*10)/10;return Number.isInteger(v)?`~${v.toFixed(0)}x`:`~${v.toFixed(1)}x`}
```

and the label `` `${pEt(u)} the estimated cost of ${o} (the default)` ``, that is, "~1.7x the estimated cost of high (the default)". Three consequences for the map:

- **It is a within-model axis only.** Every model that has one is normalized to `high = 1`, so the index says nothing about Opus versus Sonnet versus Fable. Using it across models would be wrong.
- **It is not used for window accounting anywhere in the CLI.** It is a display estimate for the picker, nothing more. The windows are metered server side.
- **It is missing on Opus 4.7, Opus 4.6, Sonnet 4.6, Opus 4.5, Sonnet 4.5 and Haiku 4.5.** On those versions the picker shows no multiplier, and on the last three the effort flag is ignored entirely (note 01).

| Version | default effort | low | medium | high | xhigh | max |
| --- | --- | --- | --- | --- | --- | --- |
| claude-fable-5-1 | high | 0.75 | 0.86 | 1 | 1.38 | 1.74 |
| claude-fable-5 | high | 0.6 | 0.77 | 1 | 1.74 | 1.91 |
| claude-opus-5 | high | 0.67 | 0.76 | 1 | 1.6 | 1.7 |
| claude-opus-4-8 | high | 0.72 | 0.9 | 1 | 1.65 | 1.88 |
| claude-opus-4-7 | xhigh | no index in the catalog entry | | | | |
| claude-opus-4-6 | not set | no index; `xhigh` silently ignored | | | | |
| claude-opus-4-5 | not set | no effort support | | | | |
| claude-sonnet-5 | high | 0.47 | 0.74 | 1 | **2.41** | **5.59** |
| claude-sonnet-4-6 | not set | no index; `xhigh` silently ignored | | | | |
| claude-sonnet-4-5 | not set | no effort support | | | | |
| claude-haiku-4-5 | not supported | no effort support | | | | |

The one striking number is Sonnet 5 at `max`, an estimated **5.59x** its own `high`. Sonnet 5 at `max` costs an estimated 5.59 x 0.50 = **2.8x Opus 5 at high** on this account's measured baseline, so it is a worse rung than Opus 5 on both cost and, presumably, capability. Sonnet at `max` should not be a rung. By the same arithmetic, Opus 5 at `xhigh` (1.6x) and Fable 5.1 at `low` (0.75x of Fable high, so about 1.54x Opus 5) are the two interesting effort rungs between Opus 5 and Fable 5.1.

## 2. The live matched measurement

**Method.** A `mktemp -d` scratch directory under `/tmp`, outside the repository and outside `~/.claude`, holding five files of fixed sizes (275, 830, 1200, 2100 and 4500 bytes). One run per version, in this order, all with the same arguments:

```
claude -p "List the three largest files in this directory with their byte sizes, then stop." \
  --model <version> --effort high --max-turns 3 \
  --output-format stream-json --verbose --allowedTools Bash,Glob,Read
```

Every run exited 0, took exactly 2 turns, and answered correctly. `--effort high` is honored on the six versions that support effort and ignored on the rest, so the effort axis is matched where it exists. `claude -p "/usage"` ran once before and once after the batch.

### Token counts and list-price cost, main model only

`modelUsage` also holds the CLI's Haiku preflight call ($0.00097 on every run, identical across versions); it is excluded from the "main" figures and included in `total_cost_usd`.

| Version | input | 1h cache write | cache read | output | thinking | main $ | `total_cost_usd` | api ms |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| claude-haiku-4-5 | 18 | 10,066 | 38,610 | 1,216 | 1,063 | 0.030091 | 0.031064 | 15,118 |
| claude-sonnet-4-5 | 18 | 9,540 | 38,610 | 692 | 508 | 0.079257 | 0.080230 | 16,548 |
| claude-sonnet-4-6 | 4 | 9,233 | 38,066 | 228 | 31 | 0.070250 | 0.071223 | 6,682 |
| claude-sonnet-5 | 4 | 19,557 | 59,829 | 185 | 0 | 0.092052 | 0.093025 | 6,498 |
| claude-opus-4-5 | 18 | 9,222 | 38,607 | 243 | 73 | 0.117689 | 0.118652 | 7,570 |
| claude-opus-4-6 | 4 | 9,326 | 38,671 | 186 | 31 | 0.117265 | 0.118238 | 8,020 |
| claude-opus-4-7 | 7 | 20,056 | 60,196 | 254 | 37 | 0.237043 | 0.238016 | 7,214 |
| claude-opus-4-8 | 4 | 16,253 | 39,297 | 239 | 0 | 0.188173 | 0.189146 | 17,401 |
| claude-opus-5 | 4 | 15,888 | 38,826 | 212 | 0 | 0.183613 | 0.184586 | 5,443 |
| claude-fable-5 | 4 | 17,175 | 40,197 | 177 | 0 | 0.392587 | 0.393560 | 5,353 |
| claude-fable-5-1 | 34 | 17,797 | 41,488 | 221 | 0 | 0.377702 | 0.378675 | 6,170 |

Recomputing each row by hand from the published price table reproduces the reported `costUSD` to the last decimal, using the **1 hour** cache write price (every run's `cache_creation` was entirely `ephemeral_1h_input_tokens`). So `total_cost_usd` is a straightforward list-price valuation and can be trusted as a cost proxy.

**Output is not where the money goes.** Output tokens are 2% to 20% of the cost of a run (2.0% on Sonnet 5, 20.2% on Haiku 4.5, under 6% on every Opus and Fable rung); the prompt side, dominated by the 1 hour cache write of the CLI's system prompt and tool definitions, is the rest. For the harness this means cost per task is set mostly by how many prompt tokens a version bills, not by how much it writes.

### The table the ticket asks for: cost per equal task

| Rung | main $ on the matched task | x Opus 5 | x the family's newest | Confidence |
| --- | --- | --- | --- | --- |
| claude-haiku-4-5 | 0.0301 | **0.16x** | 1.00x (newest) | High |
| claude-sonnet-4-6 | 0.0703 | **0.38x** | 0.76x | High on this task, medium as a general rule |
| claude-sonnet-4-5 | 0.0793 | **0.43x** | 0.86x | High on this task, medium as a general rule |
| claude-sonnet-5 | 0.0921 | **0.50x** | 1.00x (newest) | High |
| claude-opus-4-6 | 0.1173 | **0.64x** | 0.64x | High on this task, medium as a general rule |
| claude-opus-4-5 | 0.1177 | **0.64x** | 0.64x | High on this task, medium as a general rule |
| claude-opus-5 | 0.1836 | **1.00x** | 1.00x (newest) | High |
| claude-opus-4-8 | 0.1882 | **1.02x** | 1.02x | High |
| claude-opus-4-7 | 0.2370 | **1.29x** | 1.29x | High |
| claude-fable-5-1 | 0.3777 | **2.06x** | 1.00x (newest) | High |
| claude-fable-5 | 0.3926 | **2.14x** | 1.04x | High |

Single run per version, no repeats, so the third decimal is noise; the ordering and the ratios to two significant figures are solid because the dominant term (the cached prompt) is deterministic and the run shape (2 turns, same answer) was identical.

### Why the cost steps inside Opus and Sonnet exist at all

Per-token price is flat inside Opus and inside Fable, and runs backwards inside Sonnet, so the measured steps have to come from elsewhere. The prompt-side token counts show exactly where, and they fall into three clean groups:

| Group | prompt-side tokens on the identical task | Members |
| --- | --- | --- |
| Old tokenizer, full prompt | 47,303 to 48,694 | Haiku 4.5, Sonnet 4.5, Sonnet 4.6, Opus 4.5, Opus 4.6 |
| New tokenizer, lean prompt | 54,718 to 59,319 | Opus 4.8, Opus 5, Fable 5, Fable 5.1 |
| New tokenizer, full prompt | 79,390 to 80,259 | Sonnet 5, Opus 4.7 |

Two independent mechanisms:

- **The tokenizer.** Anthropic's pricing page states that "Claude 4.7 and later models and Claude Mythos Preview use a newer tokenizer ... This tokenizer produces approximately 30% more tokens for the same text. ... Claude Sonnet 4.6 and earlier models use the previous tokenizer." Measured here, the same CLI prompt bills about **65% more** tokens on the new tokenizer when the prompt is otherwise the same (Opus 4.7 at 80,259 against Opus 4.6 at 48,001). That is well above the 30% figure, because the CLI's prompt is heavy in code, JSON schemas and punctuation rather than prose.
- **The lean prompt.** The catalog's `lean_prompt` capability is held by exactly Opus 4.8, Opus 5, Fable 5 and Fable 5.1, and exactly those four land in the middle group. The shorter prompt roughly cancels the new tokenizer's inflation, leaving them about 15% above the old-tokenizer group instead of 65%.

This is the useful structural fact for the map: **a version's cost on an identical task is set by its price tier, its tokenizer and whether it gets the lean prompt.** Version recency by itself does not make a rung cheaper, and on Opus 4.7 and Sonnet 5 it makes one more expensive.

### Whether utilization resolves the difference

**No.** Every `rate_limit_event` in the batch reported `utilization` to two decimals:

```json
{"five_hour":{"utilization":0.26,"resetsAt":1789659000},"seven_day":{"utilization":0.31,"resetsAt":1790128800}}
```

That is 1% of a window, and `/usage` prints the same value as an integer percent. Across the whole batch:

| Window | before | after | events during the batch |
| --- | --- | --- | --- |
| five_hour | 0.26 | 0.27 | 0.26 on the first nine runs, 0.27 from the tenth |
| seven_day (all models) | 0.31 | 0.31 | 0.31 throughout, no change |
| seven_day_overage_included (Fable) | 0.39 | 0.40 | 0.39 on both Fable runs, 0.40 only at the closing `/usage` |

Eleven matched tasks worth about $1.90 of list value moved the five-hour window by one reported step and the all-models week by none. A single short task is therefore roughly an order of magnitude below the resolution of one reported step, and the eleven versions differ from each other by far less than the whole batch. Worse, the account had other sessions running concurrently (`/usage` reported 2,377 requests in the last 24 hours), so even the two one-point moves cannot be attributed to the probe.

**What the measurement can still establish**, and does:

- The exact token counts each version bills for an identical piece of work, which are deterministic and reproducible.
- The list-price valuation of those tokens, verified against the published price table to the last decimal.
- The ordering and the ratios in the table above, which is what a rung table needs.
- The three-group tokenizer and prompt structure, which explains the ordering and lets it be predicted for a version the harness has not probed.

To measure a window delta directly one would need to burn one whole percent of a window on a single version with no other session running, about 50 to 100 of these tasks per version, which is far outside "keep total spend tiny" and would also be confounded by the owner's concurrent work. The list-price valuation is the right proxy and should be used instead.

## 3. Anthropic's published per-token prices

From [Pricing](https://platform.claude.com/docs/en/about-claude/pricing), read 2026-09-17. USD per million tokens.

| Version | Base input | 5m cache write | 1h cache write | Cache read | Output |
| --- | --- | --- | --- | --- | --- |
| Claude Fable 5.1 | $10 | $12.50 | $20 | **$0.25** | $50 |
| Claude Fable 5 | $10 | $12.50 | $20 | $1.00 | $50 |
| Claude Opus 5 | $5 | $6.25 | $10 | $0.50 | $25 |
| Claude Opus 4.8 | $5 | $6.25 | $10 | $0.50 | $25 |
| Claude Opus 4.7 | $5 | $6.25 | $10 | $0.50 | $25 |
| Claude Opus 4.6 | $5 | $6.25 | $10 | $0.50 | $25 |
| Claude Opus 4.5 | $5 | $6.25 | $10 | $0.50 | $25 |
| Claude Sonnet 5 | $2 | $2.50 | $4 | $0.20 | $10 |
| Claude Sonnet 4.6 | **$3** | $3.75 | $6 | $0.30 | **$15** |
| Claude Sonnet 4.5 | **$3** | $3.75 | $6 | $0.30 | **$15** |
| Claude Haiku 4.5 | $1 | $1.25 | $2 | $0.10 | $5 |

Notes that bear on the rung table:

- **Only four price levels serve eleven rungs**, or five counting the Sonnet split. Nine of the eleven rungs share a price with at least one neighbour.
- **Sonnet 5's $2 / $10 is now permanent.** The page carries a note that the increase to $3 / $15 previously scheduled for 2026-09-01 will not happen. So Sonnet 4.6 and 4.5 stay 1.5x Sonnet 5's per-token price indefinitely.
- **Fable 5.1's cache reads are 0.025x base ($0.25) against Fable 5's 0.1x ($1).** In an agent session, where cache reads dominate, this makes the older Fable the **more expensive** rung, which the measurement confirms (0.3926 against 0.3777).
- Fast mode on Opus 5 and Opus 4.8 is priced at $10 / $50, that is Fable prices. The harness does not use it and should not.
- The Batch API's 50% discount and `inference_geo` multipliers do not apply to a Claude Code subscription session.

Per-token price alone, cheapest first: Haiku 4.5 ($1 / $5) < Sonnet 5 ($2 / $10) < Sonnet 4.6 = Sonnet 4.5 ($3 / $15) < Opus 4.5 = 4.6 = 4.7 = 4.8 = 5 ($5 / $25) < Fable 5.1 = Fable 5 ($10 / $50, 5.1 cheaper on cache reads).

## 4. Does an older version count against the windows at a lower rate?

**No, and there is no per-version window weight anywhere to be found.**

- **The catalog holds no window weight.** `effort_cost_index` is the only cost-like number in it, it is within-model and normalized to `high = 1`, and its only reader is the effort picker's label.
- **The windows are family scoped at most, never version scoped.** The CLI's own label map is `FD={five_hour:"session limit",seven_day:"weekly limit",seven_day_opus:"Opus limit",seven_day_sonnet:"Sonnet limit",seven_day_overage_included:"Fable limit",overage:"usage credit limit"}`. The `/usage` view builds the model-specific line from a server-supplied `rate_limits.model_scoped` array whose entries are `weekly_scoped` with a `scope.model.display_name` described in the bundle as "Server-supplied label for the model bucket (e.g. 'Fable')". On this account that label is `Fable`, the family, not `Fable 5.1`, and a GrowthBook allowlist ("usage: overage-included models allowlist") decides which labels get a line.
- **Both Fable versions land in the same bucket at the same reading.** Note 01 established this, and this probe repeats it: both Fable runs reported `seven_day_overage_included: {utilization: 0.39}`, the same value the `/usage` Fable line showed, and no non-Fable run reported that window at all.
- **Anthropic's own wording is token and cost shaped, not version shaped.** The Claude Code help centre article says only that "Opus costs several times more per turn than Sonnet, and Sonnet more than Haiku". Nothing published names a version-level rate.

So the answer to the ticket's third bullet is: **by tokens, at the family's price**. An older version counts at the same rate as the newest of its family, and what actually differs between versions is how many tokens they bill for the same work, which is the tokenizer and prompt effect measured above. A design that hopes an older version is discounted against the window has no support.

## 5. The cost ordering of the candidate rungs

Cheapest first, by measured cost on an identical task, with the ratio to Opus 5, the harness's current tier-3 model:

1. **claude-haiku-4-5** at 0.16x. Confidence high.
2. **claude-sonnet-4-6** at 0.38x. Confidence high for this task shape.
3. **claude-sonnet-4-5** at 0.43x. Confidence high for this task shape.
4. **claude-sonnet-5** at 0.50x. Confidence high.
5. **claude-opus-4-6** at 0.64x and **claude-opus-4-5** at 0.64x, indistinguishable from each other. Confidence high for this task shape.
6. **claude-opus-5** at 1.00x. Reference.
7. **claude-opus-4-8** at 1.02x, indistinguishable from Opus 5. Confidence high.
8. **claude-opus-4-7** at 1.29x, the most expensive Opus. Confidence high.
9. **claude-fable-5-1** at 2.06x. Confidence high.
10. **claude-fable-5** at 2.14x, the most expensive rung served. Confidence high.

What the map should take from this:

- **Three rungs are dominated and should be dropped.** Opus 4.7 costs 1.29x Opus 5 and is an older model, so it is worse on both axes. Fable 5 costs more than Fable 5.1, does not dodge the Fable week (note 01), and is older. Sonnet 4.5 costs 1.13x Sonnet 4.6 and is older. Each is dominated by a neighbour on cost and, by recency, presumably on quality too. The ticket's own standard, "kept only if it sits between its neighbours on cost and quality", rules all three out on cost alone, pending the quality ticket.
- **Opus 4.8 is not a cheaper rung than Opus 5.** At 1.02x it is a quality rung, not a cost rung. If the map wants a step below Opus 5 inside Opus, that step is **Opus 4.6** at 0.64x, and Opus 4.6 and Opus 4.5 are the same price so only one of them earns a place.
- **The genuine cost ladder has five distinct steps**, not eleven: Haiku 4.5 (0.16x), Sonnet 4.6 or Sonnet 5 (0.38x to 0.50x), Opus 4.6 (0.64x), Opus 5 (1.00x), Fable 5.1 (2.06x). Everything else is within noise of one of these or dominated.
- **Effort is the second axis, and it is a real one where it exists.** Opus 5 at `low` is an estimated 0.67x Opus 5 at `high`, or 0.67x on the scale above, sitting neatly between Opus 4.6 and Opus 5; Opus 5 at `xhigh` is 1.6x, between Opus 5 and Fable 5.1; Fable 5.1 at `low` is 1.54x on the same scale. Sonnet 5 at `max`, at an estimated 5.59x its own `high`, is worse than Fable 5.1 and must not be a rung.
- **Every one of these estimates is a token-and-price estimate, never a window reading.** Any spec text should say that the harness orders rungs by list-price valuation of tokens, because the window is not reported finely enough to order them any other way.

## 6. Caveats

- One run per version, one task shape, one day. The task was deliberately tiny, so the CLI's fixed system prompt dominated the cost. On a task with a large working context the ratios would shift towards the pure per-token price table, which flattens the Opus rungs further and makes the tokenizer effect larger, not smaller.
- The harness's own prompts are larger than the CLI's default, so the prompt-side dominance holds a fortiori; that is the direction the harness lives in.
- The account had concurrent sessions throughout. No window delta is attributed to the probe.
- Quality is out of scope here; it is [the sibling ticket](https://github.com/Bernaljp/wayline/issues/132). A rung's place is only settled when both this ordering and that one agree.

## Sources

- Live matched probe, Claude Code 2.1.274, 2026-09-17, raw streams under `/tmp/vc-probe.ji3f2itl/out/` (not committed; the figures above are read from the `result` envelopes).
- The model catalog and effort-picker code inside the 2.1.274 bundle, read with `strings` from `/home/bernaljp/.local/share/claude/versions/2.1.274`.
- `claude -p "/usage"`, same date and version.
- [Pricing](https://platform.claude.com/docs/en/about-claude/pricing), read 2026-09-17.
- [Models overview](https://platform.claude.com/docs/en/about-claude/models/overview), read 2026-09-17.
- [Models, usage, and limits in Claude Code](https://support.claude.com/en/articles/14552983-models-usage-and-limits-in-claude-code), read 2026-09-17.
- Sibling note `01-model-versions.md` on the branch `research/model-versions`, and spec decision 15.
