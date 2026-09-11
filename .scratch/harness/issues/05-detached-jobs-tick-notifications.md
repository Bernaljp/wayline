# 05 — Detached jobs, the tick, and notifications under systemd

Type: research
Status: resolved
Blocked by: None
Brief: Sections 9.3, 9.6, 9.8; OPEN-15; fog: the detached job runner and the tick

## Question

Verified facts about this workstation: Ubuntu with systemd 255, `loginctl show-user` reports `Linger=yes`, one NVIDIA RTX 3090 (24576 MiB), 128 CPU cores, 1007 GB RAM, 11 TB on `/home`, a user crontab already in use by another project, `notify-send`, `setsid`, `nohup`, `tmux` present, `hermes-gateway.service` running as a user unit.

1. The exact `systemd-run --user` invocation for a detached job pinned to GPU ids and CPU cores: `--unit`, `--collect`, `-p CPUAffinity=`, `-E CUDA_VISIBLE_DEVICES=`, `-p MemoryMax=`, `-p WorkingDirectory=`, `-p StandardOutput=append:<log>` and `StandardError`, `--remain-after-exit`; how to poll state and exit code (`systemctl --user show -p ActiveState,SubState,Result,ExecMainStatus,ExecMainCode`); how to tell a CUDA out-of-memory (string in the log, exit code) from a cgroup kill (`Result=oom-kill`); how to kill and clean up. The `setsid`/`nohup` fallback and what it loses.
2. For the tick: a transient timer (`systemd-run --user --on-calendar`) versus a persistent `.timer` and `.service` pair in `~/.config/systemd/user` versus a crontab line. Which survives reboot with linger, how `init` would install it and `uninstall` remove it without touching the other project's crontab, and how to guarantee a single tick instance.
3. How a headless unit sends a desktop notification (`DBUS_SESSION_BUS_ADDRESS`, `XDG_RUNTIME_DIR` under the user manager; `notify-send`), and whether `agentPushNotifEnabled` in `~/.claude/settings.json` or the running `hermes-gateway.service` offers a phone push path worth reusing.
4. `nvidia-smi` queries for free memory and utilization per GPU, and a CPU load reading, for the reservation logic.

Verify by running a 5-second `systemd-run --user` sleep job, polling it, reading its exit code, and sending one `notify-send` from a unit.

Deliverable: `research-notes/05-detached-jobs-tick-notifications.md`.

## Answer

Launch: `systemd-run --user --unit=sdr-job-<id> --slice=sdr-jobs --remain-after-exit --expand-environment=no -p CPUAffinity=<cores> -p MemoryMax=<bytes> -p MemorySwapMax=0 -p TimeoutStopSec=30 -p WorkingDirectory=<dir> -p StandardOutput=append:<log> -p StandardError=append:<log> -E CUDA_VISIBLE_DEVICES=<ids> <cmd>`. Do not pass `--collect`: it unloads a failed unit before the poller can read it (a job that exited 3 showed `Result=success`, `LoadState=not-found`). `AllowedCPUs=` is unavailable (user manager has only cpu, memory, pids controllers); `CPUAffinity=` was verified inside the unit.
Poll: `systemctl --user show sdr-job-<id>.service -p LoadState,ActiveState,SubState,Result,ExecMainCode,ExecMainStatus`. Success = `active/exited, Result=success, ExecMainStatus=0`; exit N = `failed, Result=exit-code, ExecMainCode=1, ExecMainStatus=N`.
OOM rule: `Result=oom-kill` (with `ExecMainCode=2 ExecMainStatus=9`, empty log) is the host RAM cgroup kill, verified with `MemoryMax=64M`; `Result=exit-code` plus a CUDA OOM string in the log tail (`CUDA out of memory`, `torch.OutOfMemoryError`, `CUDA_ERROR_OUT_OF_MEMORY`, `RESOURCE_EXHAUSTED`) is GPU OOM. GPU memory never produces `oom-kill`.
Kill: `systemctl --user stop <unit>` (SIGTERM then SIGKILL after TimeoutStopSec) or `systemctl --user kill --signal=SIGKILL <unit>`; all jobs: `systemctl --user stop sdr-jobs.slice`; cleanup: `reset-failed` for failed units, `stop` for finished remain-after-exit units.
Fallback: `setsid nohup env CUDA_VISIBLE_DEVICES=.. taskset -c .. sh -c 'cmd; echo $? > <id>.exit' >> log 2>&1 < /dev/null &`; loses MemoryMax, the oom-kill signal, cgroup-wide kill, and manager-recorded exit status. Survives logout because KillUserProcesses=no.
Tick: persistent `sdr-tick.timer` + `sdr-tick.service` (Type=oneshot, `OnCalendar=*:0/15`, `Persistent=true`, `WantedBy=timers.target`) in `~/.config/systemd/user`; survives reboot because Linger=yes starts the user manager at boot. A transient `--on-calendar` timer dies with the manager; a crontab line would need marker surgery on the shared TradingAgents crontab plus flock. Install: write files, `systemctl --user daemon-reload`, `systemctl --user enable --now sdr-tick.timer`. Uninstall: `systemctl --user disable --now sdr-tick.timer`, `stop sdr-tick.service`, `clean --what=state sdr-tick.timer`, rm the two files, `daemon-reload`. Single instance is guaranteed by systemd.timer(5): an already active unit is left running, not restarted; add `flock -n` inside `sdr tick` for manual runs.
Notifications: units inherit `DBUS_SESSION_BUS_ADDRESS` and `XDG_RUNTIME_DIR` from the user manager, so `notify-send -a sdr "<summary>" "<body>"` needs no extra env, but today it exits 1 (`org.freedesktop.Notifications` has no owner: the user is logged in over SSH only). It works once a GNOME session is open at seat0. Phone path: `~/.hermes/hermes-agent/venv/bin/python -m hermes_cli.main send --to telegram --subject "[sdr]" "<text>"` (no running gateway needed, exit 0/1/2; Telegram is configured). `agentPushNotifEnabled` only gates Claude Code's internal PushNotificationTool, which needs Remote Control; not reusable from a script.
Queries: `nvidia-smi --query-gpu=index,uuid,memory.total,memory.used,memory.free,utilization.gpu,utilization.memory --format=csv,noheader,nounits` (MiB and percent; record the uuid, index can change per boot); `nvidia-smi --query-compute-apps=pid,used_memory ...` per process; CPU load from `/proc/loadavg` field 1 against `nproc`=128, PSI from `/proc/pressure/cpu`; RAM from `free -b` available; disk from `df -B1 --output=avail /home`.
Full note with sources and raw outputs: research-notes/05-detached-jobs-tick-notifications.md
