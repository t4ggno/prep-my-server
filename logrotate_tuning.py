#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from common import (
    FeatureResult,
    ensure_apt_system,
    ensure_linux,
    ensure_root,
    find_command,
    format_command,
    get_missing_packages,
    normalize_text,
    print_result,
    run_checked,
    write_text_if_changed,
)

LOG_DIRECTORY = Path("/var/log/prep-my-server")
LOGROTATE_CONFIG_PATH = Path("/etc/logrotate.d/prep-my-server-local-logs")
LOGROTATE_PACKAGE = ("logrotate",)
LOGROTATE_CONFIG = normalize_text(
    f"""# Managed by prep-my-server.
# This intentionally targets only the local automation log directory so it does not
# interfere with distro-managed logrotate stanzas.
{LOG_DIRECTORY}/*.log {{
    daily
    rotate 14
    missingok
    notifempty
    compress
    delaycompress
    dateext
    create 0640 root root
}}
"""
)


def configure_logrotate_tuning(
    *,
    dry_run: bool = False,
    log_directory: Path = LOG_DIRECTORY,
    config_path: Path = LOGROTATE_CONFIG_PATH,
) -> FeatureResult:
    ensure_linux()
    ensure_root(dry_run=dry_run)

    apt_get, dpkg_query = ensure_apt_system()
    missing_packages = get_missing_packages(LOGROTATE_PACKAGE, dpkg_query_path=dpkg_query)
    config_needs_update = (
        not config_path.exists()
        or config_path.read_text(encoding="utf-8") != LOGROTATE_CONFIG
    )
    directory_needs_update = not log_directory.exists()

    result = FeatureResult(name="logrotate-tuning")

    if missing_packages:
        update_command = [apt_get, "update"]
        install_command = [
            apt_get,
            "install",
            "-y",
            "--no-install-recommends",
            *missing_packages,
        ]
        if dry_run:
            result.add_detail(f"Would run: {format_command(update_command)}")
            result.add_detail(f"Would run: {format_command(install_command)}")
            result.changed = True
        else:
            run_checked(update_command)
            run_checked(install_command, env={"DEBIAN_FRONTEND": "noninteractive"})
            result.add_detail("Installed logrotate.")
            result.changed = True

    try:
        logrotate = find_command(["logrotate"])
    except RuntimeError:
        logrotate = "logrotate"
    validate_command = [logrotate, "--debug", str(config_path)]

    if dry_run:
        if directory_needs_update:
            result.add_detail(f"Would create {log_directory}.")
            result.changed = True
        else:
            result.add_detail(f"{log_directory} already exists.")

        if config_needs_update:
            result.add_detail(f"Would write {config_path}.")
            result.changed = True
        else:
            result.add_detail(f"{config_path} already has the desired policy.")

        result.add_detail(f"Would validate with: {format_command(validate_command)}")
        return result

    logrotate = find_command(["logrotate"])
    validate_command = [logrotate, "--debug", str(config_path)]

    log_directory.mkdir(parents=True, exist_ok=True)
    if directory_needs_update:
        result.add_detail(f"Created {log_directory} for local automation logs.")
        result.changed = True
    else:
        result.add_detail(f"{log_directory} already exists.")

    if write_text_if_changed(config_path, LOGROTATE_CONFIG, mode=0o644):
        result.add_detail(f"Wrote {config_path}.")
        result.changed = True
    else:
        result.add_detail(f"{config_path} already has the desired policy.")

    run_checked(validate_command)
    result.add_detail("Validated the logrotate policy with logrotate --debug.")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a safe logrotate policy for local prep-my-server logs.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the logrotate changes without applying them.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = configure_logrotate_tuning(dry_run=args.dry_run)
        print_result(result)
        return 0
    except Exception as exc:  # pragma: no cover - CLI safety net
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
