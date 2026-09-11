# 38 — OPEN-21 Dashboard exposure

Type: grilling
Status: resolved
Blocked by: None
Brief: OPEN-21, Section 9.9

## Question

Localhost plus SSH tunnel (default), or bind to the LAN with a token; never without one.

Default: bind `127.0.0.1`, print the `ssh -L` line at start; `serve --bind 0.0.0.0` requires a random token in the URL and keeps the action set limited to the ledger's own functions. Confirm.

## Answer

Resolved 2026-09-11 by the owner in a batch grilling round (all defaults confirmed unless stated).

Bind `127.0.0.1` and print the `ssh -L` line at start. `serve --bind 0.0.0.0` requires a random URL token and keeps the action set limited to the ledger's own functions.
