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
    try_run,
    write_text_if_changed,
)

JOURNALD_CONFIG_DIR = Path("/etc/systemd/journald.conf.d")
JOURNALD_CONFIG_PATH = JOURNALD_CONFIG_DIR / "90-prep-my-server.conf"
JOURNALD_CONFIG = normalize_text(
    """# Managed by prep-my-server.
# Keep the system journal persistent but bounded so it remains useful without
# letting logs grow unbounded on small servers.
[Journal]
Storage=persistent
Compress=yes
SystemMaxUse=1G
RuntimeMaxUse=256M
MaxRetentionSec=1month
"""
)


def configure_journald_tuning(
    *,
    dry_run: bool = False,
    config_path: Path = JOURNALD_CONFIG_PATH,
) -> FeatureResult:
    ensure_linux()
    ensure_root(dry_run=dry_run)
    ensure_directory_path(config_path.parent, description="journald drop-in directory")

    systemctl = find_command(["systemctl"]) if is_systemd_available() else None
    try:
        systemd_analyze = find_command(["systemd-analyze"]) if is_systemd_available() else None
    except RuntimeError:
        systemd_analyze = None

    config_snapshot = capture_snapshot(config_path)
    directory_needs_update = not config_path.parent.exists()
    config_needs_update = (
        not config_snapshot.existed
        or config_snapshot.content != JOURNALD_CONFIG
        or config_snapshot.mode != 0o644
    )
    validate_command = (
        [systemd_analyze, "cat-config", "systemd/journald.conf"]
        if systemd_analyze
        else None
    )
    restart_command = [systemctl, "restart", "systemd-journald.service"] if systemctl else None

    result = FeatureResult(name="journald-tuning")

    if dry_run:
        if directory_needs_update:
            result.add_detail(f"Would create {config_path.parent}.")
            result.changed = True
        else:
            result.add_detail(f"{config_path.parent} already exists.")

        if config_needs_update:
            result.add_detail(f"Would write {config_path}.")
            result.changed = True
        else:
            result.add_detail(f"{config_path} already has the desired journald policy.")

        if validate_command:
            result.add_detail(f"Would validate with: {format_command(validate_command)}")
        else:
            result.add_warning(
                "systemd-analyze was not found, so journald config validation would be skipped."
            )

        if restart_command and config_needs_update:
            result.add_detail(f"Would run: {format_command(restart_command)}")
        elif not restart_command:
            result.add_warning(
                "Systemd was not detected, so the journald drop-in would apply after systemd-journald reads it later."
            )
        return result

    if directory_needs_update:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        result.add_detail(f"Created {config_path.parent}.")
        result.changed = True
    else:
        result.add_detail(f"{config_path.parent} already exists.")

    try:
        config_changed = write_text_if_changed(config_path, JOURNALD_CONFIG, mode=0o644)
        if config_changed:
            result.add_detail(f"Wrote {config_path}.")
            result.changed = True
        else:
            result.add_detail(f"{config_path} already has the desired journald policy.")

        if validate_command:
            run_checked(validate_command)
            result.add_detail("Validated the journald configuration with systemd-analyze cat-config.")
        else:
            result.add_warning(
                "systemd-analyze was not found, so journald config validation was skipped."
            )
    except Exception:
        restore_snapshot(config_path, config_snapshot)
        raise

    if restart_command and config_changed:
        restarted, restart_output = try_run(restart_command)
        if restarted:
            result.add_detail("Restarted systemd-journald so the policy is active now.")
        else:
            result.add_warning(
                "The journald drop-in was written, but systemd-journald could not be restarted automatically."
            )
            if restart_output:
                result.add_warning(restart_output)
    elif restart_command:
        result.add_detail("systemd-journald already has the desired persisted policy.")
    else:
        result.add_warning(
            "Systemd was not detected, so the journald drop-in will apply after systemd-journald reads it later."
        )

    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Write a bounded persistent journald policy.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the journald changes without applying them.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = configure_journald_tuning(dry_run=args.dry_run)
        print_result(result)
        return 0
    except Exception as exc:  # pragma: no cover - CLI safety net
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
