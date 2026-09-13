# 14 - The tick (verbatim prototype 29)

**What to build:** Every fifteen minutes the tick runs under the timer and does what a human would otherwise do: checks the login, reads the usage window, sees whether the conductor is alive, polls jobs and runs due machine checks and renders the report regardless of the window, sends due notifications, and relaunches the conductor when work remains and the window has reset or a decision was answered. The first criterion is the closed prototype ticket's Question, carried verbatim; the real `wayline tick` stands in for `tick.sh`.

**Blocked by:** 10 (Pacing and pause on usage limits), 13 (User units, run --detach, and the notifier), 54 (Hold only Fable launches while Fable's weekly window is spent)

**Status:** ready-for-agent

**GitHub:** [#15](https://github.com/Bernaljp/wayline/issues/15) (mirror; the local file is the source)

**Milestone:** M1 Frontier and windows. **Spec:** milestone M1 criterion 1; Implementation Decisions 7 (tick contract, login durability), 14 (`tick`, `heartbeat_stale_s`), 15 (the Fable line of `/usage` and the relaunch while Fable is spent).

- [ ] Carried verbatim from the closed prototype ticket 29 (Prototype: the tick):

  > Does a recurrent job relaunch work after a closed window and after an answered decision? Build a throwaway script that:
  >
  > 1. Installs a user timer (per the research note's recommendation) firing every minute for the test, running `tick.sh`.
  > 2. `tick.sh` reads an active-project pointer file, checks a conductor heartbeat file (pid plus timestamp), and exits if the conductor is alive; otherwise reads a `window.json` (`{"closed_until": <epoch>}`) and a `answers/` directory, and relaunches a dummy conductor (a script that appends a journal line and exits) when the window is open and work remains or an answer appeared.
  > 3. Sends one `notify-send` from the timer's unit.
  > 4. Simulates a closed window, waits for the reset, and shows the relaunch in the journal.
  > 5. Uninstalls the timer cleanly.
  >
  > Record what worked. The answer is the tick's contract (files it reads, conditions, actions) that M1 implements. Keep it under `.scratch/proto/tick/`.

  The real `wayline tick` under `wayline-tick.timer` stands in for `tick.sh`; the pointer is `~/.wayline/active`, the heartbeat is `research/conductor.json`, the window and the answers are read from the journal (the `paused` and `decision` events), and the timer is installed at one-minute cadence for the test and reset to `*:0/15` afterwards. On this machine `notify-send` exits 1 (no notification service), so the criterion is met when the notifier attempts it and falls through to `hermes send`, journaled as `notified` with the channel. Records go to `docs/verification/m1.md`.
- [ ] `wayline tick` runs under `flock -n ~/.wayline/tick.lock`, reads the active pointer and exits when there is none, runs `claude auth status` and reads `expiresAt` and `refreshTokenExpiresAt` from `~/.claude/.credentials.json`, opening a `human_only` decision ticket when the login is within `policy.tick.login_warning_days` (3) of expiry, reads `claude -p "/usage"`, its Fable line included through the parser of ticket 54, and journals `pacing` on change, and exits when the heartbeat pid is alive and `last_wave_at` is younger than `policy.heartbeat_stale_s`.
- [ ] Otherwise it polls jobs (the resources poller; a no-op until ticket 17), runs due machine checks, renders `REPORT.md` with a minimal renderer (frontier, open decision tickets, last events; replaced by ticket 40), sends due notifications, and relaunches the conductor as the `wayline-conductor` transient unit when work remains (a verdict queue that waits only on Fable counts once Fable's weekly window has reset) and the window is open (the last `paused.resets_at` has passed or the `/usage` reading is under the stop threshold) or a `decision` event appeared after the last `run_ended` or `paused`; when the subscription has lapsed it only polls jobs and exits.
- [ ] Tests call the tick function with a fake heartbeat, a fixture journal, a fake launcher, a fake notifier, and a fake clock, covering every branch of the contract, a verdict queue waiting only on Fable before and after Fable's reset included.
