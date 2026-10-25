# 130 - Harness sessions without the owner's MCP servers

**What to build:** A session the harness launches starts no MCP server or plugin of the owner's.

On the toy's live run (ticket 122, `docs/verification/m8.md`), every verdict, decider, worker, and chat session started the owner's user-level MCP servers and plugins: `codex mcp-server`, the `llm-chat` server, and `npm exec @playwright/mcp@latest`, which fetches from the network at each start. `--disallowedTools mcp__*` refuses their tools but does not stop them starting. They cost start-up time on every session, and a server that fails to start or changes upstream is a harness session behaving differently on each machine.

- Every launch the harness builds (`launcher.build_argv`, the chat, the gates) passes `--strict-mcp-config` with an empty MCP config, or the narrowest flags the CLI offers to the same effect.
- The CLI flags are checked live once on the current Claude Code and recorded, the way the launch flags were in M0.

**Blocked by:** None - can start immediately.

**Status:** ready-for-agent

**GitHub:** [#337](https://github.com/Bernaljp/wayline/issues/337) (mirror; the local file is the source)

**Milestone:** after M8 (v1.1.x). **Spec:** Implementation Decision 4 (guards and permissions), 7 (the launcher); ticket 122's live record.

- [ ] The launch argv of a ticket, a verdict, the decider, and the chat carry the flag; a test reads each.
- [ ] A live launch on this workstation starts no MCP server process; recorded.
- [ ] `python -m unittest` passes.
