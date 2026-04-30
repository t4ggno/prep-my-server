#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from common import (
    FeatureResult,
    capture_snapshot,
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

CLEANUP_SCRIPT_PATH = Path("/usr/local/sbin/prep-my-server-cleanup")
CLEANUP_SERVICE_PATH = Path("/etc/systemd/system/prep-my-server-cleanup.service")
CLEANUP_TIMER_PATH = Path("/etc/systemd/system/prep-my-server-cleanup.timer")
LOCAL_LOG_DIR = Path("/var/log/prep-my-server")
CLEANUP_SCRIPT_CONTENT = normalize_text(
    """#!/bin/sh
set -eu

log_dir=/var/log/prep-my-server
lock_file=/run/prep-my-server-cleanup.lock

mkdir -p "$log_dir"
exec >>"$log_dir/cleanup.log" 2>&1

if command -v flock >/dev/null 2>&1; then
    exec 9>"$lock_file"
    if ! flock -n 9; then
        printf '[%s] Another cleanup run is already active; exiting.\n' "$(date --iso-8601=seconds 2>/dev/null || date)"
        exit 0
    fi
fi

printf '[%s] Starting safe APT cleanup.\n' "$(date --iso-8601=seconds 2>/dev/null || date)"
apt-get -q -y autoclean
apt-get -q -y autoremove
printf '[%s] Safe APT cleanup finished.\n' "$(date --iso-8601=seconds 2>/dev/null || date)"
"""
)
CLEANUP_SERVICE_CONTENT = normalize_text(
    f"""[Unit]
Description=prep-my-server safe APT cleanup
Documentation=man:apt-get(8)

[Service]
Type=oneshot
ExecStart={CLEANUP_SCRIPT_PATH}
"""
)
CLEANUP_TIMER_CONTENT = normalize_text(
    """[Unit]
Description=Weekly prep-my-server safe APT cleanup

[Timer]
OnCalendar=weekly
RandomizedDelaySec=1h
Persistent=true

[Install]
WantedBy=timers.target
"""
)


def configure_automatic_cleanup(
    *,
    dry_run: bool = False,
    script_path: Path = CLEANUP_SCRIPT_PATH,
    service_path: Path = CLEANUP_SERVICE_PATH,
    timer_path: Path = CLEANUP_TIMER_PATH,
) -> FeatureResult:
    ensure_linux()
    ensure_root(dry_run=dry_run)

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
        or script_snapshot.content != CLEANUP_SCRIPT_CONTENT
        or script_snapshot.mode != 0o755
    )
    service_needs_update = (
        not service_snapshot.existed
        or service_snapshot.content != CLEANUP_SERVICE_CONTENT
        or service_snapshot.mode != 0o644
    )
    timer_needs_update = (
        not timer_snapshot.existed
        or timer_snapshot.content != CLEANUP_TIMER_CONTENT
        or timer_snapshot.mode != 0o644
    )

    result = FeatureResult(name="automatic-cleanup")

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
            result.add_detail(f"{script_path} already has the desired cleanup script.")
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
            result.add_warning("Systemd was not detected, so automatic scheduling would be skipped.")
        return result

    LOCAL_LOG_DIR.mkdir(parents=True, exist_ok=True)
    if log_dir_needs_update:
        result.add_detail(f"Created {LOCAL_LOG_DIR} for cleanup logs.")
        result.changed = True
    else:
        result.add_detail(f"{LOCAL_LOG_DIR} already exists for cleanup logs.")

    try:
        if write_text_if_changed(script_path, CLEANUP_SCRIPT_CONTENT, mode=0o755):
            result.add_detail(f"Wrote {script_path}.")
            result.changed = True
        else:
            result.add_detail(f"{script_path} already has the desired cleanup script.")

        run_checked(syntax_command)
        result.add_detail("Validated the cleanup shell script with sh -n.")

        if write_text_if_changed(service_path, CLEANUP_SERVICE_CONTENT, mode=0o644):
            result.add_detail(f"Wrote {service_path}.")
            result.changed = True
        else:
            result.add_detail(f"{service_path} already has the desired service unit.")

        if write_text_if_changed(timer_path, CLEANUP_TIMER_CONTENT, mode=0o644):
            result.add_detail(f"Wrote {timer_path}.")
            result.changed = True
        else:
            result.add_detail(f"{timer_path} already has the desired timer unit.")

        if systemctl:
            if systemd_analyze:
                run_checked([systemd_analyze, "verify", str(service_path), str(timer_path)])
                result.add_detail("Validated the cleanup systemd units with systemd-analyze verify.")
            run_checked([systemctl, "daemon-reload"])
            run_checked([systemctl, "enable", "--now", timer_path.name])
            result.add_detail("Enabled the weekly cleanup timer.")
        else:
            result.add_warning("Systemd was not detected, so the cleanup script was written but not scheduled.")
    except Exception:
        restore_snapshot(script_path, script_snapshot)
        restore_snapshot(service_path, service_snapshot)
        restore_snapshot(timer_path, timer_snapshot)
        raise

    result.add_detail(
        "The cleanup job uses apt-get autoclean and autoremove only; it deliberately avoids apt-get clean and purge-style removal."
    )
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Install a safe weekly APT cleanup timer.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the cleanup timer changes without applying them.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = configure_automatic_cleanup(dry_run=args.dry_run)
        print_result(result)
        return 0
    except Exception as exc:  # pragma: no cover - CLI safety net
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
