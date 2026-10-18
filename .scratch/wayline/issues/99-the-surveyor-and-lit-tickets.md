# 99 - The surveyor and lit tickets

**What to build:** The literature is searched mid-run for each objective the Introduction does not yet cover. A `lit` ticket runs on the new **surveyor** role (`sonnet medium`, kinds `["lit"]`, tools Read, Glob, Grep, `wayline scout`, `wayline consult`), so the state of the art keeps up with the questions at little cost.

The surveyor searches with `wayline scout search "<query>"` and by the works that cite a seed. Code asks arXiv, Crossref, and Europe PMC for free, and OpenAlex sparingly: code counts the day's 100 requests, at USD 0.001 each. A search is always live, never cached, and capped at 20 a ticket. A `lit` ticket returns Introduction passages tagged at `#abstract`, its `references`, and proposals.

The planner cuts a `lit` ticket:

- at specify, one per open objective with no Introduction passage carrying a `ref` tag, merging objectives that share a literature;
- when an objective is added or reframed: the spec amendment of "92 - Spec amendments" is followed by a `lit` ticket when no Introduction passage with a `ref` tag covers the new objective;
- on a worker's proposal or the owner's word.

Position's `missing_prior_work` is scouted at setup and handed to the first `lit` tickets.

Not part of this ticket:

- `wayline scout <identifier>` and the check at acceptance, which are "98 - References during a ticket";
- References' rendering, which is "105 - References rendered and important ones raised".

**Blocked by:** 81 - Specify and the plan name objectives; 92 - Spec amendments; 98 - References during a ticket. It blocks 122.

**Status:** ready-for-agent

**GitHub:** [#246](https://github.com/Bernaljp/wayline/issues/246) (mirror; the local file is the source)

**Milestone:** M8 A paper that grows with the work (v1.1.0). **Spec:** Implementation Decision 17 (A reference found during a ticket: the surveyor, `wayline scout search`, cutting `lit` tickets; How objectives change: a `lit` ticket after an amendment); Implementation Decision 1 (the verb table: `scout search`); Implementation Decision 14 (the policy table: the surveyor role at `sonnet medium`, 20 searches a ticket, 100 OpenAlex requests a day); Implementation Decision 10 (position's `missing_prior_work`, the planner); M8 criterion 11; user story 145.

- [ ] `roles/surveyor` exists with kinds `["lit"]`, `sonnet medium`, and the tools Read, Glob, Grep, `wayline scout`, and `wayline consult`. Its prompt asks for Introduction passages tagged at `#abstract`, `references`, and proposals, and `KIND_ROLE` routes `lit` to it.
- [ ] `wayline scout search "<query>"` asks arXiv, Crossref, and Europe PMC, and OpenAlex only within the day's 100 requests that code counts. It is always live, capped at 20 per ticket, and can list the works citing a seed.
- [ ] At specify, the planner cuts one `lit` ticket per open objective lacking an Introduction passage with a `ref` tag, merging objectives that share a literature. A spec amendment for an added or reframed objective is followed by one when that objective is uncovered. A worker's proposal or the owner's word also cuts one.
- [ ] Position's `missing_prior_work` is scouted at setup and handed to the first `lit` tickets.
- [ ] Tests through the fetch seam's recordings for `scout search` (each service, the OpenAlex day count, the per-ticket cap, citing works); the fake launcher scripting a surveyor result; journal replay for `lit` tickets cut at specify and after an amendment.
- [ ] Decision 1's verb table gains `scout search`, and decision 14's policy table the surveyor role and the caps, in the same commit as their code.
- [ ] The CHANGELOG's `## Unreleased` entry and the documentation site describe the surveyor.
- [ ] `python -m unittest` passes.
