# 15 — OPEN-4 Language

Type: grilling
Status: resolved
Blocked by: None
Brief: OPEN-4, Section 5.3

## Question

Python 3.12 standard library for the programs (default), or Node?

Facts: Python 3.12.3 and Node 22.22.3 are both installed. Workflow scripts must be JavaScript regardless; the dashboard front end is vanilla JavaScript regardless.

Default: Python standard library for `conductor`, `resources`, `tick`, `tickets`, `worker`, `registry`, `dossier`, `kb`, `scout`, `gates`, `provenance`, `ledger`, `evolve`, `figures`, `docs`, `dashboard`; JavaScript only where the runtime demands it.

Sub-question: ticket frontmatter format. The brief shows YAML, but YAML parsing is not in the standard library. Options: (a) a restricted flat YAML subset written by code and parsed by a small in-house parser; (b) a fenced JSON block at the top of the ticket file; (c) TOML frontmatter read with `tomllib` (stdlib, read-only) and written by a small serializer. Default: (a), because tickets stay readable and `graph.json` remains the machine truth.

## Answer

Resolved 2026-09-11 by the owner in a batch grilling round (all defaults confirmed unless stated).

Python 3.12 standard library for every program; JavaScript only for Workflow scripts and the dashboard front end. Ticket frontmatter is a restricted flat YAML subset written by code and parsed by a small in-house parser; `graph.json` remains the machine truth.
