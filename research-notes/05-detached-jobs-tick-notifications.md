# 05: Detached jobs, the tick, and notifications under systemd

Ticket: `.scratch/harness/issues/05-detached-jobs-tick-notifications.md`. Brief: Sections 9.3, 9.6, 9.8.
Verified on this workstation on 2026-09-11: Ubuntu, systemd 255 (255.4-1ubuntu8.15), `Linger=yes`, one RTX 3090,
128 cores, 1007 GB RAM. Every claim below cites a man page section or the command whose raw output is in the
"Raw outputs" section at the end. Temporary units were named `sdr-test-*` and `sdr-tick-test*`; all were removed
(audit in Raw outputs, block R9). The user crontab and `hermes-gateway.service` were not touched.

## Answer

### A1. Job launch line

```
systemd-run --user --unit=sdr-job-<id> --slice=sdr-jobs --remain-after-exit --expand-environment=no \
  -p CPUAffinity=<cores> -p MemoryMax=<bytes or 64G> -p MemorySwapMax=0 -p TimeoutStopSec=30 \
  -p WorkingDirectory=<abs project dir> \
  -p StandardOutput=append:<abs log path> -p StandardError=append:<same log path> \
  -E CUDA_VISIBLE_DEVICES=<ids> -E PYTHONUNBUFFERED=1 \
  <abs interpreter> <script> <args>
```

Decisions baked into that line:

- Do not pass `--collect`. It sets `CollectMode=inactive-or-failed`, which unloads the unit the moment it fails, so
  the poller sees `LoadState=not-found`, `Result=success`, `ExecMainStatus=0` for a job that exited 3 or was OOM
  killed (observed, R3 and R4). The manual says results "are flushed out immediately after the unit completed"
  under that mode (systemd.unit(5), CollectMode=). With the default `CollectMode=inactive` a failed unit stays
  loaded until `reset-failed` (systemctl(1), reset-failed), which is what a poller needs.
- `--remain-after-exit` keeps a successful job loaded as `ActiveState=active SubState=exited` with
  `ExecMainStatus=0`, so success is observable too (R2). Without it a successful unit unloads at once.
- `--expand-environment=no`, because the manager otherwise expands `$VAR` and `$$` in the command line
  (systemd-run(1): "dollar characters which should not be expanded need to be escaped as `$$`"). With expansion on,
  my `taskset -cp $$` received a literal `$` (R2, log line `taskset: invalid PID argument`).
- `CPUAffinity=` is the pinning knob available to the user manager. `AllowedCPUs=` needs the cpuset controller and
  the user manager here is delegated only `cpu memory pids` (R5, `cgroup.controllers`). Affinity was verified inside
  the unit: `Cpus_allowed_list: 0-7` (R8). systemd.exec(5) CPUAffinity= takes indices or ranges, comma or space
  separated.
- `MemoryMax=` works in the user manager (memory controller is delegated, R5) and is the thing that produces
  `Result=oom-kill` (R6). systemd.resource-control(5) recommends `MemoryHigh=` as the main control and `MemoryMax=`
  as the last line of defense; for a batch job we want the hard kill, so set `MemoryMax=` and leave `MemoryHigh=`
  unset. `MemorySwapMax=0` prevents the job from swapping instead of dying.
- `--slice=sdr-jobs` groups every job under one transient slice so `systemctl --user stop sdr-jobs.slice` kills all
  of them (systemd-run(1) --slice=).
- `StandardOutput=append:` requires an absolute path and appends (systemd.exec(5) StandardOutput=). Point stderr at
  the same file so CUDA tracebacks land where the OOM grep looks. The journal also gets the manager's own lines
  (`journalctl --user -u sdr-job-<id>`), which is where "A process of this unit has been killed by the OOM killer"
  appears (R6).
- `-E NAME=VALUE` sets a unit environment variable (systemd-run(1) --setenv=); `Environment=CUDA_VISIBLE_DEVICES=0`
  shows up in `systemctl --user show` (R6) and the process saw it (R8).
- `WorkingDirectory=` defaults to the user's home for a user manager (systemd.exec(5)), so always set it.
- The unit name must be unique among loaded units; `systemd-run` fails if it already exists. Use the job id.

### A2. Poll line and how to read it

```
systemctl --user show sdr-job-<id>.service -p LoadState,ActiveState,SubState,Result,ExecMainCode,ExecMainStatus
```

`show` is the documented machine-readable interface (systemctl(1), show). Decode in this order:

| Observation | Meaning |
|---|---|
| `LoadState=not-found` | Unit is gone: never launched, or already cleaned. Do not infer success. Consult `jobs/<id>.json` and the log. |
| `ActiveState=active SubState=running` | Running. |
| `ActiveState=active SubState=exited Result=success ExecMainCode=1 ExecMainStatus=0` | Exited 0 (only visible with `--remain-after-exit`, R2). |
| `ActiveState=failed Result=exit-code ExecMainCode=1 ExecMainStatus=N` | Process exited with code N (R3, N=3). |
| `ActiveState=failed Result=oom-kill ExecMainCode=2 ExecMainStatus=9` | Host memory cgroup kill (R6). |
| `ActiveState=failed Result=signal ExecMainCode=2 ExecMainStatus=<signo>` | Killed by a signal other than a clean stop. |
| `Result=success` after `systemctl --user stop` | SIGTERM/SIGINT/SIGHUP/SIGPIPE exits count as success (systemd.exec(5), Table 6). |

`ExecMainCode` is the wait(2) class of the main process: 1 = exited, 2 = killed by signal, 3 = dumped core; this
matches `$EXIT_CODE` in systemd.exec(5) ("exited", "killed", "dumped") and both 1 and 2 were observed (R2, R6).
`Result` values are the `$SERVICE_RESULT` set in systemd.exec(5) Table 5: success, protocol, timeout, exit-code,
signal, core-dump, watchdog, oom-kill, start-limit-hit, resources.

`systemctl --user is-active` and `is-failed` return exit codes for shell use (systemctl(1)), but `show` gives all
five fields in one call, so use `show` from Python.

### A3. OOM discrimination rule

1. If `Result=oom-kill`: the host RAM limit (`MemoryMax=`) or the kernel OOM killer hit the unit. The main process
   dies with SIGKILL (`ExecMainCode=2 ExecMainStatus=9`) and writes nothing to its log (R6: `oom2.log` was empty).
   Retry with a smaller host footprint (fewer dataloader workers, smaller in-memory dataset) or a larger `MemoryMax=`.
   GPU memory is invisible to cgroups, so a CUDA OOM never yields this result.
2. Else if `Result=exit-code`: read the tail of the log (last 64 KB is enough) and match CUDA OOM signatures:
   `CUDA out of memory`, `torch.OutOfMemoryError`, `torch.cuda.OutOfMemoryError`, `CUDA_ERROR_OUT_OF_MEMORY`,
   `cudaErrorMemoryAllocation`, `RESOURCE_EXHAUSTED` (JAX and TensorFlow), `CUBLAS_STATUS_ALLOC_FAILED`,
   `CUDNN_STATUS_ALLOC_FAILED`. A Python uncaught exception exits 1, so `ExecMainStatus=1` plus a match means GPU
   OOM; retry with the smaller GPU footprint (batch size, precision, model shard).
3. Else if `Result=exit-code` without a match: real failure, mark the job failed and attach the log tail.
4. `Result=signal` with `ExecMainStatus=9` and no `oom-kill`: somebody killed it (our own `kill --signal=SIGKILL`,
   or a user). Treat as cancelled, not OOM.

The signature list comes from the framework error strings, not from a man page; keep it in one table in
`resources.py` so it can grow.

### A4. Kill and cleanup

- Graceful: `systemctl --user stop sdr-job-<id>.service`. Sends `KillSignal=` (default SIGTERM) to the whole cgroup
  (default `KillMode=control-group`), then SIGKILL after `TimeoutStopSec=` (systemd.kill(5), KillMode=, KillSignal=).
  The launch line sets `TimeoutStopSec=30` so a hung job cannot hold a slot for the 90 s default.
- Immediate: `systemctl --user kill --signal=SIGKILL sdr-job-<id>.service` (systemctl(1), kill, --signal=,
  --kill-whom= defaults to all processes of the unit).
- Everything: `systemctl --user stop sdr-jobs.slice`.
- Cleanup after reading the result: `systemctl --user reset-failed sdr-job-<id>.service` for a failed unit
  (systemctl(1), reset-failed; verified R6, `LoadState=not-found` afterwards) and `systemctl --user stop
  sdr-job-<id>.service` for a successful remain-after-exit unit (R2). Both return nonzero if the unit is already
  gone, which is harmless; ignore that error.
- `stop` on a `--remain-after-exit` unit that already exited just unloads it; it does not restart anything.

### A5. Fallback without a user manager (`setsid`/`nohup`)

```
setsid nohup env CUDA_VISIBLE_DEVICES=<ids> taskset -c <cores> \
  sh -c '<abs interpreter> <script> <args>; echo $? > <abs jobs dir>/<id>.exit' \
  >> <abs log path> 2>&1 < /dev/null &
echo $! > <abs jobs dir>/<id>.pid
```

Poll: `<id>.exit` exists means finished with that code; otherwise `kill -0 $(cat <id>.pid)` says alive. Kill:
`kill -TERM -- -$(cat <id>.pid)` (the `setsid` process is its own process group leader), then `kill -KILL`.

What it loses relative to `systemd-run --user`: no `MemoryMax=` and no `Result=oom-kill` (a kernel OOM kill is only
visible in `dmesg`, which needs root here), no cgroup-wide kill (children that `setsid` again escape the group), no
manager-recorded exit status (the `.exit` file is the substitute and is missing if the shell itself is killed), pid
reuse ambiguity, no journal, and no `CPUAffinity` beyond what `taskset` sets on the initial process. It does survive
logout: `KillUserProcesses=no` is the default and is not overridden in `/etc/systemd/logind.conf` (R7,
logind.conf(5)). Use it only when `systemctl --user` cannot reach a manager (`XDG_RUNTIME_DIR` unset, e.g. under a
`sudo -u` shell).

### A6. Tick installation recommendation

Recommendation: a persistent `.timer` and `.service` pair in `~/.config/systemd/user`, installed by `init`, not a
transient timer and not a crontab line.

- Survives reboot: `loginctl enable-linger` means "a user manager is spawned for the user at boot and kept around
  after logouts" (loginctl(1)), and `Linger=yes` here; `timers.target` is active in this user manager (R9). Timer
  units enabled into `timers.target.wants` start with the manager.
- A transient timer (`systemd-run --user --on-calendar=`) works (R10) but transient units live only in the manager's
  memory (systemd-run(1) DESCRIPTION; the unit vanished after `stop`, R10), so it dies with the manager at reboot.
  Keep it only for tests.
- A crontab line survives reboot too (cron runs at boot), but the crontab is shared with TradingAgents (R1, four
  lines), `crontab -e` replaces the whole file, so install and uninstall need marker-line surgery, and cron gives no
  single-instance guarantee and no manager environment (`DBUS_SESSION_BUS_ADDRESS`), so the tick would need `flock`
  and an explicit bus address. Nothing recommends it over the unit pair.
- Single instance: "in case the unit to activate is already active at the time the timer elapses it is not
  restarted, but simply left running. There is no concept of spawning new service instances in this case"
  (systemd.timer(5), DESCRIPTION). A service unit is one cgroup, so an overrunning tick makes the next elapse a
  no-op. Keep `sdr tick` itself idempotent and add `flock -n <state dir>/tick.lock` inside it anyway so `sdr tick`
  run by hand cannot overlap the timer's run.
- `Persistent=true` triggers a missed run right after boot (systemd.timer(5), Persistent=) and stores a stamp
  under `~/.local/share/systemd/timers/` (R11); `systemctl --user clean --what=state` removes it (same section).
- `OnCalendar=*:0/15` normalizes to `*-*-* *:00/15:00` (R10). `AccuracySec=1min` is the default and is fine.

Unit files `init` writes:

```
# ~/.config/systemd/user/sdr-tick.service
[Unit]
Description=SpecDrivenResearch tick
[Service]
Type=oneshot
ExecStart=<abs interpreter> -m sdr tick
WorkingDirectory=<abs harness dir>
RuntimeMaxSec=20min
StandardOutput=append:<abs state dir>/tick.log
StandardError=append:<abs state dir>/tick.log

# ~/.config/systemd/user/sdr-tick.timer
[Unit]
Description=SpecDrivenResearch tick timer
[Timer]
OnCalendar=*:0/15
Persistent=true
AccuracySec=1min
[Install]
WantedBy=timers.target
```

Install (verified R11, `enabled`, `active`, next elapse listed):

```
systemctl --user daemon-reload
systemctl --user enable --now sdr-tick.timer
systemctl --user list-timers sdr-tick.timer     # sanity check
```

Uninstall (verified R11, directory back to only `hermes-gateway.service` and `default.target.wants`):

```
systemctl --user disable --now sdr-tick.timer
systemctl --user stop sdr-tick.service            # if a tick is mid-run
systemctl --user clean --what=state sdr-tick.timer
rm -f ~/.config/systemd/user/sdr-tick.service ~/.config/systemd/user/sdr-tick.timer
systemctl --user daemon-reload
systemctl --user reset-failed sdr-tick.timer sdr-tick.service 2>/dev/null || true
```

`enable` creates `timers.target.wants/sdr-tick.timer` and `disable` removes exactly that symlink (systemctl(1),
enable and disable); no other unit or the crontab is involved.

### A7. Notification recipe

From a unit, `notify-send` needs nothing extra: the user manager's environment block already contains
`DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/176816/bus` and `XDG_RUNTIME_DIR=/run/user/176816`
(`systemctl --user show-environment`, R1) and a unit inherits both (R7, `env` inside a unit). `DISPLAY` is not
needed; `notify-send` talks D-Bus (notify-send --help, R1).

What is missing today is the receiver: `org.freedesktop.Notifications` has no owner and no activatable service on
this bus (`busctl --user call ... NameHasOwner` returns `false`, R7), because the owner is logged in over SSH only
(sessions 1506 and 1507 are pts; seat0 belongs to gdm's greeter, R7). `notify-send` therefore exits 1 with
`GDBus.Error:org.freedesktop.DBus.Error.ServiceUnknown` both from the shell and from inside a unit (R7). When a GNOME
session is logged in at seat0, gnome-shell owns that name on the same `/run/user/176816/bus` and the same command
works. So the recipe is:

```
notify-send -a sdr -u normal "<summary>" "<body>"          # exit 0: delivered; exit 1: no daemon
```

and on nonzero exit fall through to the phone path, which does exist:

```
/home/bernaljp/.hermes/hermes-agent/venv/bin/python -m hermes_cli.main send --to telegram --subject "[sdr]" "<text>"
```

`hermes send` "reuses the gateway's platform credentials, no LLM, no agent loop, no running gateway required for
bot-token platforms like Telegram"; exit codes 0 ok, 1 delivery error, 2 usage error (`hermes send --help`, R12).
Telegram is the configured platform (gateway journal lines, R12). Wrap both in one `notify(event, text)` in the
harness that logs the event to the journal first, tries `notify-send`, then `hermes send` if the hermes venv exists,
and never raises. Do not depend on hermes being installed: `init` detects it and records the path in `harness.json`.

`agentPushNotifEnabled: true` in `~/.claude/settings.json` is not reusable. It gates Claude Code's internal
`PushNotificationTool`, described in the binary as "Send a notification to the user via their terminal and, when
Remote Control is connected, also push to their mobile device", and it reports `disabledReason: "no_transport"`
without Remote Control (R13). It is a model tool, not a shell command, and works only while a Claude Code session
with Remote Control is running, which is exactly when the tick is not needed.

### A8. GPU and CPU queries for the reservation logic

```
nvidia-smi --query-gpu=index,uuid,memory.total,memory.used,memory.free,utilization.gpu,utilization.memory --format=csv,noheader,nounits
# 0, GPU-0095fb8d-af69-ff0f-6b06-da1a9a89fc7f, 24576, 86, 24170, 0, 0        (MiB, MiB, MiB, %, %)
nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader,nounits   # per process, MiB
```

Field meanings from `nvidia-smi --help-query-gpu`: `memory.free` is total free memory, `memory.used` is memory
allocated by active contexts, `utilization.gpu` is the percent of the last sample period (1 s to 1/6 s) with a kernel
executing, `utilization.memory` the same for device memory traffic, and `index` "can change at each boot", so record
the `uuid` in `jobs/<id>.json` and map it back to an index at launch. Add `-i <index>` to target one GPU.

CPU load: read `/proc/loadavg`; the first field is the 1-minute run-queue average, the fourth is
`runnable/total` scheduling entities (proc_loadavg(5)); compare against `nproc` (128). Also readable:
`/proc/pressure/cpu` gives PSI `some avg10` as a percentage of time tasks waited for CPU (R14). RAM:
`free -b` column 7 (`available`, 1.07e12 bytes now) or `MemAvailable` in `/proc/meminfo`. Disk: `df -B1 --output=avail
/home` (1.08e13 bytes now). A free slot is: `memory.free >= need + reserve`, `utilization.gpu < threshold` for two
consecutive samples, and `loadavg1 + cores_needed <= nproc - reserved_cores`.

## Details and sources

### D1. Why `--collect` breaks polling

Three runs of a job that does `exit 3` (R3):

| Options | After exit |
|---|---|
| `--collect --remain-after-exit` | `LoadState=not-found Result=success ExecMainStatus=0` |
| `--collect` only | same |
| neither (default `CollectMode=inactive`) | `LoadState=loaded ActiveState=failed Result=exit-code ExecMainCode=1 ExecMainStatus=3` |

`--remain-after-exit` only keeps a unit that succeeded; a failed unit goes to `failed`, and `inactive-or-failed`
unloads it. systemd-run(1) `--collect` says: "Unload the transient unit after it completed, even if it failed."

### D2. OOM kill observed

`MemoryMax=64M MemorySwapMax=0` with a Python allocating 1 GiB (R6): journal shows "A process of this unit has been
killed by the OOM killer", "Main process exited, code=killed, status=9/KILL", "Failed with result 'oom-kill'";
`show` gives `Result=oom-kill ExecMainCode=2 ExecMainStatus=9 OOMPolicy=stop MemoryMax=67108864`. The log file is
empty. `OOMPolicy=stop` is the default (`DefaultOOMPolicy=stop` in system.conf, systemd.service(5) OOMPolicy=), so
the whole unit stops when any process is OOM killed. `systemd-oomd` is active on the host as well; a kill by oomd
also reports `oom-kill` (systemd.service(5) OOMPolicy= covers both the kernel and systemd-oomd).

### D3. Timer facts

- systemd.timer(5), Persistent=: "the service unit is triggered immediately if it would have been triggered at least
  once during the time when the timer was inactive ... Use `systemctl clean --what=state` ... before uninstalling".
- systemd.timer(5), AccuracySec=: default 1 min; the expiry is placed in a window `[OnCalendar, +AccuracySec]`.
- systemd.time(7): `*:0/15` style calendar expressions; `minutely`, `hourly` shortcuts.
- systemd-run(1): `--on-calendar=` "is a shortcut for `--timer-property=OnCalendar=`", creates a transient timer
  plus service; `--timer-property=` can add `Persistent=true` but the timer is still transient.
- systemctl(1), `--now`: with `enable` also starts, with `disable` also stops.

### D4. Notification bus facts

- `systemctl --user show-environment` (R1) lists `DBUS_SESSION_BUS_ADDRESS` and `XDG_RUNTIME_DIR`; systemd.exec(5)
  "Environment Variables in Spawned Processes" says services inherit the manager's environment block.
- `busctl --user list` (R7): `org.gnome.Shell.Notifications` is activatable but that activation needs gnome-shell,
  which is not running for this user; `org.freedesktop.Notifications` is absent.
- `notify-send --help` (R1): options `-u`, `-t`, `-a`, `-i`, `-c`, `-e`, `-h`, `-p`, `-r`, `-w`, `-A`. The notify-send
  build here has no `--help` text about the bus; it simply uses the session bus.

### D5. Slice note

The transient `sdr-jobs.slice` stays `loaded` but `inactive` after its last child is gone (R9); this is harmless
and it is reused by the next launch. `systemctl --user stop sdr-jobs.slice` is the kill-all.

## Raw outputs

R1. System state (`systemctl --version`, `loginctl show-user`, `systemctl --user show-environment`, `crontab -l`):

```
systemd 255 (255.4-1ubuntu8.15)
Linger=yes  State=active  Service=user@176816.service  RuntimePath=/run/user/176816
show-environment: HOME, LANG, LOGNAME, PATH, SHELL, USER, XDG_RUNTIME_DIR=/run/user/176816,
  DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/176816/bus, SSH_AUTH_SOCK, ...
user timers: snap.firmware-updater.firmware-notifier.timer, launchpadlib-cache-clean.timer (no sdr-* before or after)
crontab -l: 4 TradingAgents lines (14:45 and 23:05 weekdays, @reboot, Sat 09:00); md5 3fab9374... unchanged after the work
```

R2. Sleep job with `--collect --remain-after-exit`, polled every second:

```
systemd-run --user --collect --unit=sdr-test-2083247 -p CPUAffinity=0-7 -E CUDA_VISIBLE_DEVICES=0 \
  -p StandardOutput=append:.../test.log -p StandardError=append:.../test.log -p WorkingDirectory=... \
  --remain-after-exit /bin/sh -c 'echo start ...; taskset -cp $$; sleep 5; echo done'
Running as unit: sdr-test-2083247.service; invocation ID: 8939...
polls 1-5: ActiveState=active SubState=running MainPID=2083251 Result=success ExecMainCode=0 ExecMainStatus=0 CPUAffinity=0-7
polls 6-8: ActiveState=active SubState=exited  MainPID=0 ExecMainCode=1 ExecMainStatus=0 Result=success
test.log: "start pid=$ cwd=/home/bernaljp/.claude/jobs/5a78b0a6/tmp/05 CUDA=0" / "taskset: invalid PID argument: '$'" / "done"
ExecStart=... start_time=[20:11:47] stop_time=[20:11:52] pid=2083251 code=exited status=0
systemctl --user stop -> rc=0, then LoadState=not-found
```

R3. Exit 3 variants:

```
--collect --remain-after-exit: Result=success ExecMainPID=0 ExecMainCode=0 ExecMainStatus=0 LoadState=not-found; is-failed -> "inactive" rc=4
--collect only:                Result=success ExecMainCode=0 ExecMainStatus=0 LoadState=not-found
no --collect:                  Result=exit-code ExecMainCode=1 ExecMainStatus=3 LoadState=loaded ActiveState=failed SubState=failed
                               reset-failed -> LoadState=not-found
```

R4. OOM with `--collect`: `Result=success ... LoadState=not-found`, journal still shows "Failed with result 'oom-kill'".

R5. Controllers and OOM policy:

```
/sys/fs/cgroup/user.slice/user-176816.slice/user@176816.service/cgroup.controllers: cpu memory pids
cgroup.subtree_control: cpu memory pids
systemctl is-active systemd-oomd: active
/etc/systemd/system.conf: #DefaultOOMPolicy=stop (default)
```

R6. OOM without `--collect`:

```
systemd-run --user --unit=sdr-test-oom2-2085440 --slice=sdr-jobs -p MemoryMax=64M -p MemorySwapMax=0 -p CPUAffinity=0-7 \
  -E CUDA_VISIBLE_DEVICES=0 -p WorkingDirectory=... -p StandardOutput=append:.../oom2.log -p StandardError=append:.../oom2.log \
  --remain-after-exit /usr/bin/python3 -c '<allocate 64 x 16 MiB>'
show: Result=oom-kill OOMPolicy=stop ExecMainPID=2085443 ExecMainCode=2 ExecMainStatus=9 Slice=sdr-jobs.slice
      MemoryMax=67108864 MemorySwapMax=0 Environment=CUDA_VISIBLE_DEVICES=0 CPUAffinity=0-7 LoadState=loaded ActiveState=failed SubState=failed
oom2.log: (empty)
journal: Started ... / A process of this unit has been killed by the OOM killer. / Main process exited, code=killed, status=9/KILL / Failed with result 'oom-kill'.
reset-failed rc=0 -> LoadState=not-found
```

R7. Environment inside a unit, notify-send, sessions, logind:

```
systemd-run --user --quiet --wait --pipe --collect /usr/bin/env | grep ...:
  HOME=/home/bernaljp PATH=/usr/local/sbin:...:/snap/bin USER=bernaljp XDG_RUNTIME_DIR=/run/user/176816
  DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/176816/bus MANAGERPID=4105 INVOCATION_ID=...
  (no DISPLAY, no WAYLAND_DISPLAY)
systemd-run --user --wait --pipe --collect /usr/bin/notify-send -a sdr-test -u normal "SDR test" "...":
  GDBus.Error:org.freedesktop.DBus.Error.ServiceUnknown: The name org.freedesktop.Notifications was not provided by any .service files
  Finished with result: exit-code / Main processes terminated with: code=exited/status=1
same via -p StandardOutput=append: -> Result=exit-code ExecMainCode=1 ExecMainStatus=1, same error text in notify.log
notify-send from the interactive shell: same error, rc=1
busctl --user call org.freedesktop.DBus /org/freedesktop/DBus org.freedesktop.DBus NameHasOwner s org.freedesktop.Notifications -> b false
busctl --user list --activatable | grep -i notif: org.gnome.Shell.Notifications (activatable), org.x.StatusNotifierWatcher
loginctl list-sessions: 1506 pts/0 active, 1507 pts/6 active, 1378 and 668 closing (bernaljp); c1 gdm seat0 tty1
who: bernaljp pts/0 and pts/6 from 10.185.133.107
/etc/systemd/logind.conf: #KillUserProcesses=no ; logind.conf(5): "Defaults to no"
```

R8. Affinity verified with expansion off:

```
systemd-run --user --quiet --wait --pipe --collect -p CPUAffinity=0-7 -E CUDA_VISIBLE_DEVICES=0 --expand-environment=no /bin/sh -c '...'
CUDA_VISIBLE_DEVICES=0
pid 2088772's current affinity list: 0-7
Cpus_allowed_list: 0-7
0::/user.slice/user-176816.slice/user@176816.service/app.slice/sdr-test-aff-2088769.service
```

R9. Cleanup audit: `systemctl --user list-units --all 'sdr-*'` -> 0 units; `sdr-jobs.slice` LoadState=loaded
ActiveState=inactive; no sdr timers; `~/.config/systemd/user` contains only `default.target.wants/` and
`hermes-gateway.service`; `~/.local/share/systemd/timers` (created by the Persistent=true test, empty) removed;
`hermes-gateway.service` active; the two pre-existing failed units (`xdg-desktop-portal*.service`) were failed before
this work; `timers.target` and `default.target` active.

R10. Transient timer:

```
systemd-run --user --on-calendar='*:0/15' --unit=sdr-tick-test-2085939 -p StandardOutput=append:.../tick.log /bin/sh -c 'echo tick $(date)'
Running timer as unit: sdr-tick-test-2085939.timer / Will run service as unit: sdr-tick-test-2085939.service
list-timers: NEXT Fri 2026-09-11 20:15:00 +03  LEFT 1min 56s  UNIT sdr-tick-test-2085939.timer  ACTIVATES sdr-tick-test-2085939.service
show: TimersCalendar={ OnCalendar=*-*-* *:00/15:00 ; next_elapse=... } AccuracyUSec=1min Persistent=no ActiveState=active
after stop: timer LoadState=not-found, service LoadState=not-found
```

R11. Persistent pair (files written to `~/.config/systemd/user/sdr-tick-test.{service,timer}`, then removed):

```
systemctl --user daemon-reload && systemctl --user enable --now sdr-tick-test.timer
Created symlink ~/.config/systemd/user/timers.target.wants/sdr-tick-test.timer -> ~/.config/systemd/user/sdr-tick-test.timer
is-enabled: enabled   is-active: active   list-timers: NEXT 20:15:00 +03
systemctl --user start sdr-tick-test.service -> tick-persistent.log: "persistent tick Fri Sep 11 08:13:13 PM +03 2026"
systemctl --user disable --now sdr-tick-test.timer -> Removed ".../timers.target.wants/sdr-tick-test.timer"
clean --what=state, rm files, daemon-reload -> LoadState=not-found; timers.target.wants/ gone
```

R12. Hermes (read only, help text and unit status; config and .env not read):

```
hermes gateway --help: Manage the messaging gateway (Telegram, Discord, WhatsApp, Weixin, and more); subcommands run/start/stop/restart/status/install/uninstall/list/setup
hermes send --help: "Pipe text from any shell script to any messaging platform Hermes is already configured for. Reuses the gateway's
  platform credentials (~/.hermes/.env + ~/.hermes/config.yaml), no LLM, no agent loop, no running gateway required for bot-token
  platforms like Telegram/Discord/Slack/Signal."  -t/--to TARGET (telegram, telegram:<chat_id>, discord:#ops, ...), -s/--subject, -f/--file, -l/--list, -q, --json
  Exit codes: 0 ok, 1 delivery/backend error, 2 usage error.
hermes gateway status: hermes-gateway.service active (running) since Sep 05; journal shows gateway.platforms.telegram reconnect warnings,
  so Telegram is the configured platform; "Systemd linger is enabled (service survives logout)".
```

R13. Claude Code binary (`/home/bernaljp/.local/share/claude/versions/2.1.268`, string search):

```
settings schema: agentPushNotifEnabled: "Allow Claude to push proactive mobile notifications";
                 inputNeededNotifEnabled: "Push to mobile when a permission prompt or question is waiting"
PushNotificationTool: "Send a notification to the user via their terminal and, when Remote Control is connected, also push to their mobile device"
  result fields: pushSent, localSent, disabledReason:"no_transport"
gate: TZ() = feature flag tengu_kairos_push_notifications && agentPushNotifEnabled
preferences endpoint: /api/claude_code/notification/preferences
```

R14. Load and hardware readings:

```
/proc/loadavg: 1.10 0.47 0.22 2/2449 2086675      nproc: 128
/proc/pressure/cpu: some avg10=0.00 avg60=0.00 avg300=0.00 total=178970456 / full ...
free -b available: 1068203200512     df -B1 --output=avail /home: 10765606739968
nvidia-smi --query-gpu=index,uuid,memory.free,memory.used,memory.total,utilization.gpu,utilization.memory,temperature.gpu,power.draw:
  0, GPU-0095fb8d-af69-ff0f-6b06-da1a9a89fc7f, 24170, 86, 24576, 0, 0, 32, 18.02
nvidia-smi --query-compute-apps=pid,process_name,used_memory: (no compute processes)
```
