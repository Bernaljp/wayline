# 107 - The rule from code to Methods

**What to build:** Methods and the code never drift apart, checked at each acceptance by parsers with no tokens. A Type-A check runs over the ticket's diff in `code/`:

- every developed method the diff adds or changes is named by a `code` tag in a current Methods passage. Code excludes plumbing, and anything else the worker says is not a method goes in the new result field `not_methods`, which the verifier judges;
- every used method the diff adds (a library call such as pysindy's SINDy) is named in a Methods passage, matched through an alias table;
- every non-default parameter the diff sets, and every sensitive default left unset (an unseeded random state, default solver tolerances), has a one-sentence reason in the new result field `parameters`. The worker also lists there the values the parsers cannot see. Code fills in each value and default, and the verifier's existing verdict judges the reasons.

A failure sends the worker back with the list. The parsers:

- Python: `ast` plus `inspect.signature`, run in the project's own environment so defaults come from the pinned versions. A default is marked "not checked" until that environment is installed;
- MATLAB: tree-sitter-matlab in the tools venv, with a documented-defaults table and backward slices to find a parameter's value. The same parse fills the code dossier's methods seam;
- any other language: a Sonnet reading of the changed files at acceptance, its items checked by grep, at about $0.40 per 1,000 lines, until that language's first project files an adapter as a harness ticket.

Code tickets' touch sets go under `code/` (85), so the diff is the ticket's diff there.

Not part of this ticket:

- generating Methods' parameter table, software versions, and citations;
- listing Methods-to-code gaps in the outline;
- the setup-time reading of inherited code.

  All three are 108's. The check over all of `code/` at the order is 119's.

**Blocked by:**
- 75 - The harness's tools (tree-sitter-matlab)
- 85 - The code repository
- 86 - Passages and the five sections

It blocks 108 and 119.

**Status:** done

**GitHub:** [#254](https://github.com/Bernaljp/wayline/issues/254) (mirror; the local file is the source)

**Milestone:** M8 A paper that grows with the work (v1.1.0). **Spec:** Implementation Decision 17 (Methods and the code: the rule from code to Methods, the parsers; sections and passages: the `code` tag; vocabulary the build adds: `result` gains `parameters` and `not_methods`), the schemas list; milestone M8 criterion 13; user story 150.

- [x] At acceptance, a ticket whose diff in `code/` adds or changes a developed method with no `code` tag naming it in a current Methods passage is sent back, and the message names the method. Plumbing is excluded by code. A method listed in `not_methods` passes the check and goes to the verifier's verdict.
- [x] A used method the diff adds that no Methods passage names through the alias table sends the ticket back.
- [x] Every non-default parameter set in the diff, and every sensitive default left unset, needs an entry in `parameters` with a one-sentence reason, or the ticket is sent back. Code fills each entry's value and default.
- [x] The verifier's verdict is given the `parameters` reasons and the `not_methods` list to judge, and its verdict schema carries that judgment.
- [x] The Python parser reads signatures through `inspect.signature` in the project's environment. With that environment not installed, a default is recorded as "not checked" and does not fail the check.
- [x] The MATLAB parser uses tree-sitter-matlab from the tools venv, the documented-defaults table, and backward slices, and fills the code dossier's methods entries for a MATLAB repository.
- [x] A changed file in another language gets one Sonnet reading at acceptance, with each item it names checked by grep in the file. Its cost is journaled with the ticket's usage.
- [x] The `result` schema gains `parameters` and `not_methods`.
- [x] Tests, Type-A functions over a worktree and a result, with the start-midway fixture's Python and MATLAB files (78):
  - an untagged developed method;
  - a used method missing from Methods;
  - an unexplained non-default;
  - an unseeded random state;
  - `not_methods`;
  - "not checked" defaults;
  - the Sonnet reading through the fake launcher;
  - the parsers through the tool runner's recordings.
- [x] The schemas list gains the `result` fields in the same commit as the code.
- [x] The changelog's `## Unreleased` section describes the rule from code to Methods.
- [x] `python -m unittest` passes.
