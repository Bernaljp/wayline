# 13 - User units, run --detach, and the notifier

**What to build:** `wayline init` installs the tick timer, the tick service, and the dashboard service under the owner's systemd user manager once per machine (and removes exactly them on request), `wayline run --detach` starts the conductor as a transient unit that survives the shell, and one notifier function reaches the owner: it journals first, tries `notify-send`, then `hermes send` to Telegram when the hermes interpreter was detected, and never raises.

**Blocked by:** 09 (Resume from the journal, heartbeat, control events, and worker re-adoption), 11 (Read-only dashboard: transport, tabs, journal tail, overview (verbatim prototype 36))

**Status:** ready-for-agent

**GitHub:** [#14](https://github.com/Bernaljp/wayline/issues/14) (mirror; the local file is the source)

**Milestone:** M1 Frontier and windows. **Spec:** Implementation Decisions 7 (units, notifier, login durability), 5 (process); research-notes 05 A6 and A7.

- [ ] `init` writes `wayline-tick.service`, `wayline-tick.timer`, and `wayline-dashboard.service` into `~/.config/systemd/user/` exactly as Implementation Decisions 7 gives them (absolute interpreter and harness paths, `EnvironmentFile=-<home>/.wayline/env`, `OnCalendar=*:0/15`, `Persistent=true`, `Restart=on-failure` on the dashboard), runs `daemon-reload` and `enable --now` on the timer and the dashboard, and is idempotent; `init --uninstall-units` disables and removes exactly those three units and cleans the timer's persistent stamp, touching nothing else (the crontab is never read or written).
- [ ] `wayline run --detach` launches `systemd-run --user --unit=wayline-conductor -p WorkingDirectory=<harness> <python> -m wayline run --resume ...` without `--collect`; `wayline run` (foreground) prints the dashboard address and starts `wayline-dashboard.service` when it is not active.
- [ ] `notify(event, text)` journals `notified` first, runs `notify-send -a wayline -u normal "<summary>" "<body>"`, falls through on a nonzero exit to `<hermes_python> -m hermes_cli.main send --to telegram --subject "[wayline]" "<text>"` when `harness.json.notify.hermes_python` is set, records the channel and exit code in the event, and never raises.
- [ ] `init` detects `~/.hermes/hermes-agent/venv/bin/python` and records it under `notify.hermes_python`; `init` offers to write `~/.wayline/env` (mode 0600) from `claude setup-token` and explains that it is loaded only by the units.
- [ ] Tests fake the subprocesses for the units and the notifier; live: `systemctl --user list-timers wayline-tick.timer` shows the timer enabled and active, the dashboard service is active, one notification reaches the owner's phone, and the uninstall leaves the user unit directory as it was, all recorded in `docs/verification/m1.md`.
