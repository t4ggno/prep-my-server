#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import re
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
    try_run,
    write_text_if_changed,
)

DOCKER_PRUNE_SCRIPT_PATH = Path("/usr/local/sbin/prep-my-server-docker-prune")
DOCKER_PRUNE_SERVICE_PATH = Path("/etc/systemd/system/prep-my-server-docker-prune.service")
DOCKER_PRUNE_TIMER_PATH = Path("/etc/systemd/system/prep-my-server-docker-prune.timer")
LOCAL_LOG_DIR = Path("/var/log/prep-my-server")
DEFAULT_DOCKER_PRUNE_ON_CALENDAR = "weekly"
DEFAULT_DOCKER_PRUNE_RANDOMIZED_DELAY_SEC = "1h"
DEFAULT_DOCKER_PRUNE_UNTIL = "168h"
_SAFE_ENV_VALUE_RE = re.compile(r"^[A-Za-z0-9_.:+/@-]+$")
DOCKER_PRUNE_SCRIPT_CONTENT = normalize_text(
    """#!/bin/sh
set -eu

log_dir=/var/log/prep-my-server
lock_file=/run/prep-my-server-docker-prune.lock
prune_until="${PREP_MY_SERVER_DOCKER_PRUNE_UNTIL:-168h}"

mkdir -p "$log_dir"
exec >>"$log_dir/docker-prune.log" 2>&1

if command -v flock >/dev/null 2>&1; then
    exec 9>"$lock_file"
    if ! flock -n 9; then
        printf '[%s] Another Docker prune run is already active; exiting.\n' "$(date --iso-8601=seconds 2>/dev/null || date)"
        exit 0
    fi
fi

if ! command -v docker >/dev/null 2>&1; then
    printf '[%s] docker command not found; skipping scheduled prune.\n' "$(date --iso-8601=seconds 2>/dev/null || date)"
    exit 0
fi

if ! docker info >/dev/null 2>&1; then
    printf '[%s] Docker is not reachable; skipping scheduled prune.\n' "$(date --iso-8601=seconds 2>/dev/null || date)"
    exit 0
fi

printf '[%s] Starting Docker system prune for unused objects older than %s.\n' "$(date --iso-8601=seconds 2>/dev/null || date)" "$prune_until"
docker system prune --force --filter "until=$prune_until"
printf '[%s] Docker system prune finished.\n' "$(date --iso-8601=seconds 2>/dev/null || date)"
"""
)


def _require_non_empty(value: str, *, name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise RuntimeError(f"{name} cannot be empty.")
    return normalized


def _require_single_line_systemd_value(value: str, *, name: str) -> str:
    normalized = _require_non_empty(value, name=name)
    if any(character in normalized for character in ("\r", "\n", "\x00")):
        raise RuntimeError(f"{name} cannot contain newlines or NUL bytes.")
    return normalized


def _require_safe_environment_value(value: str, *, name: str) -> str:
    normalized = _require_single_line_systemd_value(value, name=name)
    if not _SAFE_ENV_VALUE_RE.fullmatch(normalized):
        raise RuntimeError(
            f"{name} can contain only letters, digits, and these characters: _ . : + / @ -"
        )
    if normalized.startswith("-"):
        raise RuntimeError(f"{name} cannot start with '-'.")
    return normalized


def _validate_timer_values(
    *,
    on_calendar: str,
    randomized_delay_sec: str,
    result: FeatureResult,
) -> None:
    try:
        systemd_analyze = find_command(["systemd-analyze"])
    except RuntimeError:
        result.add_warning(
            "systemd-analyze was not found, so timer expression validation was limited to basic single-line checks."
        )
        return

    run_checked([systemd_analyze, "calendar", on_calendar])
    run_checked([systemd_analyze, "timespan", randomized_delay_sec])
    result.add_detail(
        "Validated the Docker prune timer schedule with systemd-analyze calendar and timespan."
    )


def _docker_service_is_loaded(*, systemctl: str | None) -> bool | None:
    if systemctl is None:
        return None

    success, output = try_run([systemctl, "show", "-p", "LoadState", "--value", "docker.service"])
    if not success:
        return False
    return output.strip() == "loaded"


def _timer_content(*, on_calendar: str, randomized_delay_sec: str) -> str:
    return normalize_text(
        f"""[Unit]
Description=prep-my-server Docker prune

[Timer]
OnCalendar={on_calendar}
RandomizedDelaySec={randomized_delay_sec}
Persistent=true

[Install]
WantedBy=timers.target
"""
    )


def _service_content(*, script_path: Path, prune_until: str) -> str:
    return normalize_text(
        f"""[Unit]
Description=prep-my-server Docker prune
Documentation=man:docker-system-prune(1)
After=docker.service

[Service]
Type=oneshot
Environment=PREP_MY_SERVER_DOCKER_PRUNE_UNTIL={prune_until}
ExecStart={script_path}
"""
    )


def configure_docker_prune_timer(
    *,
    dry_run: bool = False,
    script_path: Path = DOCKER_PRUNE_SCRIPT_PATH,
    service_path: Path = DOCKER_PRUNE_SERVICE_PATH,
    timer_path: Path = DOCKER_PRUNE_TIMER_PATH,
    on_calendar: str = DEFAULT_DOCKER_PRUNE_ON_CALENDAR,
    randomized_delay_sec: str = DEFAULT_DOCKER_PRUNE_RANDOMIZED_DELAY_SEC,
    prune_until: str = DEFAULT_DOCKER_PRUNE_UNTIL,
) -> FeatureResult:
    ensure_linux()
    ensure_root(dry_run=dry_run)
    ensure_directory_path(LOCAL_LOG_DIR, description="Docker prune log directory")

    on_calendar = _require_single_line_systemd_value(on_calendar, name="on_calendar")
    randomized_delay_sec = _require_single_line_systemd_value(
        randomized_delay_sec,
        name="randomized_delay_sec",
    )
    prune_until = _require_safe_environment_value(prune_until, name="prune_until")

    service_content = _service_content(script_path=script_path, prune_until=prune_until)
    timer_content = _timer_content(
        on_calendar=on_calendar,
        randomized_delay_sec=randomized_delay_sec,
    )

    sh_path = find_command(["sh"])
    systemctl = find_command(["systemctl"]) if is_systemd_available() else None
    try:
        systemd_analyze = find_command(["systemd-analyze"]) if is_systemd_available() else None
    except RuntimeError:
        systemd_analyze = None
    syntax_command = [sh_path, "-n", str(script_path)]

    script_snapshot = capture_snapshot(script_path)
    service_snapshot = capture_snapshot(service_path)
    timer_snapshot = capture_snapshot(timer_path)
    log_dir_needs_update = not LOCAL_LOG_DIR.exists()
    docker_service_loaded = _docker_service_is_loaded(systemctl=systemctl)

    script_needs_update = (
        not script_snapshot.existed
        or script_snapshot.content != DOCKER_PRUNE_SCRIPT_CONTENT
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

    result = FeatureResult(name="docker-prune-timer")
    _validate_timer_values(
        on_calendar=on_calendar,
        randomized_delay_sec=randomized_delay_sec,
        result=result,
    )

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
            result.add_detail(f"{script_path} already has the desired Docker prune script.")
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
            result.add_warning("Systemd was not detected, so Docker prune scheduling would be skipped.")
        if docker_service_loaded is False:
            result.add_warning(
                "docker.service is not currently installed; scheduled runs would skip until Docker is installed and reachable."
            )
        result.add_detail(
            f"Configured Docker prune schedule: OnCalendar={on_calendar}, RandomizedDelaySec={randomized_delay_sec}, until={prune_until}."
        )
        result.add_detail(
            "The scheduled prune would skip runs when Docker is missing or unreachable and does not prune volumes."
        )
        return result

    LOCAL_LOG_DIR.mkdir(parents=True, exist_ok=True)
    if log_dir_needs_update:
        result.add_detail(f"Created {LOCAL_LOG_DIR} for Docker prune logs.")
        result.changed = True
    else:
        result.add_detail(f"{LOCAL_LOG_DIR} already exists for Docker prune logs.")

    try:
        if write_text_if_changed(script_path, DOCKER_PRUNE_SCRIPT_CONTENT, mode=0o755):
            result.add_detail(f"Wrote {script_path}.")
            result.changed = True
        else:
            result.add_detail(f"{script_path} already has the desired Docker prune script.")

        run_checked(syntax_command)
        result.add_detail("Validated the Docker prune shell script with sh -n.")

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
                result.add_detail("Validated the Docker prune systemd units with systemd-analyze verify.")
            run_checked([systemctl, "daemon-reload"])
            run_checked([systemctl, "enable", "--now", timer_path.name])
            result.add_detail("Enabled the Docker prune timer.")
        else:
            result.add_warning(
                "Systemd was not detected, so the Docker prune script was written but not scheduled."
            )
    except Exception:
        restore_snapshot(script_path, script_snapshot)
        restore_snapshot(service_path, service_snapshot)
        restore_snapshot(timer_path, timer_snapshot)
        raise

    if docker_service_loaded is False:
        result.add_warning(
            "docker.service is not currently installed; scheduled runs will skip until Docker is installed and reachable."
        )
    result.add_detail(
        f"Configured Docker prune schedule: OnCalendar={on_calendar}, RandomizedDelaySec={randomized_delay_sec}, until={prune_until}."
    )
    result.add_detail("The scheduled prune skips runs when Docker is missing or unreachable and does not prune volumes.")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Install a scheduled Docker system prune timer.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the Docker prune timer changes without applying them.",
    )
    parser.add_argument(
        "--on-calendar",
        default=DEFAULT_DOCKER_PRUNE_ON_CALENDAR,
        help=(
            "systemd OnCalendar expression for the Docker prune timer "
            f"(default: {DEFAULT_DOCKER_PRUNE_ON_CALENDAR})."
        ),
    )
    parser.add_argument(
        "--randomized-delay-sec",
        default=DEFAULT_DOCKER_PRUNE_RANDOMIZED_DELAY_SEC,
        help=(
            "systemd RandomizedDelaySec value for the Docker prune timer "
            f"(default: {DEFAULT_DOCKER_PRUNE_RANDOMIZED_DELAY_SEC})."
        ),
    )
    parser.add_argument(
        "--prune-until",
        default=DEFAULT_DOCKER_PRUNE_UNTIL,
        help=(
            "Docker prune 'until' filter value for keeping recent unused objects "
            f"(default: {DEFAULT_DOCKER_PRUNE_UNTIL})."
        ),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = configure_docker_prune_timer(
            dry_run=args.dry_run,
            on_calendar=args.on_calendar,
            randomized_delay_sec=args.randomized_delay_sec,
            prune_until=args.prune_until,
        )
        print_result(result)
        return 0
    except Exception as exc:  # pragma: no cover - CLI safety net
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
