#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from common import (
    FeatureResult,
    capture_snapshot,
    ensure_directory_path,
    ensure_linux,
    ensure_root,
    find_command,
    format_command,
    is_systemd_available,
    normalize_text,
    print_result,
    restore_snapshot,
    run_checked,
    write_text_if_changed,
)

REBOOT_SCRIPT_PATH = Path("/usr/local/sbin/prep-my-server-reboot")
REBOOT_SERVICE_PATH = Path("/etc/systemd/system/prep-my-server-reboot.service")
REBOOT_TIMER_PATH = Path("/etc/systemd/system/prep-my-server-reboot.timer")
LOCAL_LOG_DIR = Path("/var/log/prep-my-server")
DEFAULT_REBOOT_ON_CALENDAR = "*-*-* 03:30:00"
DEFAULT_REBOOT_RANDOMIZED_DELAY_SEC = "30m"
REBOOT_SCRIPT_CONTENT = normalize_text(
    """#!/bin/sh
set -eu

log_dir=/var/log/prep-my-server
lock_file=/run/prep-my-server-reboot.lock

mkdir -p "$log_dir"
exec >>"$log_dir/reboot.log" 2>&1

if command -v flock >/dev/null 2>&1; then
    exec 9>"$lock_file"
    if ! flock -n 9; then
        printf '[%s] Another reboot run is already active; exiting.\n' "$(date --iso-8601=seconds 2>/dev/null || date)"
        exit 0
    fi
fi

printf '[%s] Starting scheduled prep-my-server reboot.\n' "$(date --iso-8601=seconds 2>/dev/null || date)"

if command -v systemctl >/dev/null 2>&1; then
    exec systemctl reboot
fi

exec shutdown -r now 'prep-my-server scheduled reboot'
"""
)


def _require_non_empty(value: str, *, name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise RuntimeError(f"{name} cannot be empty.")
    return normalized


def _timer_content(*, on_calendar: str, randomized_delay_sec: str) -> str:
    return normalize_text(
        f"""[Unit]
Description=prep-my-server scheduled reboot

[Timer]
OnCalendar={on_calendar}
RandomizedDelaySec={randomized_delay_sec}
Persistent=false

[Install]
WantedBy=timers.target
"""
    )


def _service_content(*, script_path: Path) -> str:
    return normalize_text(
        f"""[Unit]
Description=prep-my-server scheduled reboot
Documentation=man:systemctl(1) man:shutdown(8)

[Service]
Type=oneshot
ExecStart={script_path}
"""
    )


def configure_automatic_reboot(
    *,
    dry_run: bool = False,
    script_path: Path = REBOOT_SCRIPT_PATH,
    service_path: Path = REBOOT_SERVICE_PATH,
    timer_path: Path = REBOOT_TIMER_PATH,
    on_calendar: str = DEFAULT_REBOOT_ON_CALENDAR,
    randomized_delay_sec: str = DEFAULT_REBOOT_RANDOMIZED_DELAY_SEC,
) -> FeatureResult:
    ensure_linux()
    ensure_root(dry_run=dry_run)
    ensure_directory_path(LOCAL_LOG_DIR, description="reboot log directory")

    on_calendar = _require_non_empty(on_calendar, name="on_calendar")
    randomized_delay_sec = _require_non_empty(
        randomized_delay_sec,
        name="randomized_delay_sec",
    )

    service_content = _service_content(script_path=script_path)
    timer_content = _timer_content(
        on_calendar=on_calendar,
        randomized_delay_sec=randomized_delay_sec,
    )

    sh_path = find_command(["sh"])
    systemctl = find_command(["systemctl"]) if is_systemd_available() else None
    systemd_analyze = find_command(["systemd-analyze"]) if is_systemd_available() else None
    syntax_command = [sh_path, "-n", str(script_path)]

    script_snapshot = capture_snapshot(script_path)
    service_snapshot = capture_snapshot(service_path)
    timer_snapshot = capture_snapshot(timer_path)
    log_dir_needs_update = not LOCAL_LOG_DIR.exists()

    script_needs_update = (
        not script_snapshot.existed
        or script_snapshot.content != REBOOT_SCRIPT_CONTENT
        or script_snapshot.mode != 0o755
    )
    service_needs_update = (
        not service_snapshot.existed
        or service_snapshot.content != service_content
        or service_snapshot.mode != 0o644
    )
    timer_needs_update = (
        not timer_snapshot.existed
        or timer_snapshot.content != timer_content
        or timer_snapshot.mode != 0o644
    )

    result = FeatureResult(name="automatic-reboot")

    if dry_run:
        if log_dir_needs_update:
            result.add_detail(f"Would create {LOCAL_LOG_DIR}.")
            result.changed = True
        else:
            result.add_detail(f"{LOCAL_LOG_DIR} already exists.")

        if script_needs_update:
            result.add_detail(f"Would write {script_path}.")
            result.changed = True
        else:
            result.add_detail(f"{script_path} already has the desired reboot script.")
        result.add_detail(f"Would validate with: {format_command(syntax_command)}")

        if service_needs_update:
            result.add_detail(f"Would write {service_path}.")
            result.changed = True
        else:
            result.add_detail(f"{service_path} already has the desired service unit.")

        if timer_needs_update:
            result.add_detail(f"Would write {timer_path}.")
            result.changed = True
        else:
            result.add_detail(f"{timer_path} already has the desired timer unit.")

        if systemctl:
            result.add_detail(f"Would run: {format_command([systemctl, 'daemon-reload'])}")
            result.add_detail(
                f"Would run: {format_command([systemctl, 'enable', '--now', timer_path.name])}"
            )
        else:
            result.add_warning("Systemd was not detected, so automatic reboot scheduling would be skipped.")
        result.add_detail(
            f"Configured reboot schedule: OnCalendar={on_calendar}, RandomizedDelaySec={randomized_delay_sec}."
        )
        return result

    LOCAL_LOG_DIR.mkdir(parents=True, exist_ok=True)
    if log_dir_needs_update:
        result.add_detail(f"Created {LOCAL_LOG_DIR} for reboot logs.")
        result.changed = True
    else:
        result.add_detail(f"{LOCAL_LOG_DIR} already exists for reboot logs.")

    try:
        if write_text_if_changed(script_path, REBOOT_SCRIPT_CONTENT, mode=0o755):
            result.add_detail(f"Wrote {script_path}.")
            result.changed = True
        else:
            result.add_detail(f"{script_path} already has the desired reboot script.")

        run_checked(syntax_command)
        result.add_detail("Validated the reboot shell script with sh -n.")

        if write_text_if_changed(service_path, service_content, mode=0o644):
            result.add_detail(f"Wrote {service_path}.")
            result.changed = True
        else:
            result.add_detail(f"{service_path} already has the desired service unit.")

        if write_text_if_changed(timer_path, timer_content, mode=0o644):
            result.add_detail(f"Wrote {timer_path}.")
            result.changed = True
        else:
            result.add_detail(f"{timer_path} already has the desired timer unit.")

        if systemctl:
            if systemd_analyze:
                run_checked([systemd_analyze, "verify", str(service_path), str(timer_path)])
                result.add_detail("Validated the reboot systemd units with systemd-analyze verify.")
            run_checked([systemctl, "daemon-reload"])
            run_checked([systemctl, "enable", "--now", timer_path.name])
            result.add_detail("Enabled the automatic reboot timer.")
        else:
            result.add_warning("Systemd was not detected, so the reboot script was written but not scheduled.")
    except Exception:
        restore_snapshot(script_path, script_snapshot)
        restore_snapshot(service_path, service_snapshot)
        restore_snapshot(timer_path, timer_snapshot)
        raise

    result.add_detail(
        f"Configured reboot schedule: OnCalendar={on_calendar}, RandomizedDelaySec={randomized_delay_sec}."
    )
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Install a scheduled automatic reboot timer.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the automatic reboot timer changes without applying them.",
    )
    parser.add_argument(
        "--on-calendar",
        default=DEFAULT_REBOOT_ON_CALENDAR,
        help=f"systemd OnCalendar expression for the reboot timer (default: {DEFAULT_REBOOT_ON_CALENDAR}).",
    )
    parser.add_argument(
        "--randomized-delay-sec",
        default=DEFAULT_REBOOT_RANDOMIZED_DELAY_SEC,
        help=(
            "systemd RandomizedDelaySec value for the reboot timer "
            f"(default: {DEFAULT_REBOOT_RANDOMIZED_DELAY_SEC})."
        ),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = configure_automatic_reboot(
            dry_run=args.dry_run,
            on_calendar=args.on_calendar,
            randomized_delay_sec=args.randomized_delay_sec,
        )
        print_result(result)
        return 0
    except Exception as exc:  # pragma: no cover - CLI safety net
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
