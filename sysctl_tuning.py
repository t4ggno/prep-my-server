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
    normalize_text,
    print_result,
    restore_snapshot,
    run_checked,
    write_text_if_changed,
)

SYSCTL_CONFIG_PATH = Path("/etc/sysctl.d/90-prep-my-server.conf")
SYSCTL_CONFIG = normalize_text(
    """# Managed by prep-my-server.
# Conservative sysctl tuning for better interactive and service ergonomics.
fs.inotify.max_user_instances = 1024
fs.inotify.max_user_watches = 524288
net.core.somaxconn = 4096
net.ipv4.tcp_keepalive_time = 600
net.ipv4.tcp_keepalive_intvl = 60
net.ipv4.tcp_keepalive_probes = 5
vm.swappiness = 10
vm.vfs_cache_pressure = 50"""
)


def configure_sysctl_tuning(
    *,
    dry_run: bool = False,
    config_path: Path = SYSCTL_CONFIG_PATH,
) -> FeatureResult:
    ensure_linux()
    ensure_root(dry_run=dry_run)

    sysctl = find_command(["sysctl", "/usr/sbin/sysctl", "/sbin/sysctl"])
    config_snapshot = capture_snapshot(config_path)
    config_needs_update = (
        not config_snapshot.existed
        or config_snapshot.content != SYSCTL_CONFIG
        or config_snapshot.mode != 0o644
    )
    apply_command = [sysctl, "-p", str(config_path)]

    result = FeatureResult(name="sysctl-tuning")
    if dry_run:
        if config_needs_update:
            result.add_detail(f"Would write {config_path}.")
            result.changed = True
        else:
            result.add_detail(f"{config_path} already has the desired sysctl settings.")
        result.add_detail(f"Would run: {format_command(apply_command)}")
        return result

    try:
        if write_text_if_changed(config_path, SYSCTL_CONFIG, mode=0o644):
            result.add_detail(f"Wrote {config_path}.")
            result.changed = True
        else:
            result.add_detail(f"{config_path} already has the desired sysctl settings.")

        run_checked(apply_command)
    except Exception:
        restore_snapshot(config_path, config_snapshot)
        raise

    result.add_detail("Applied the sysctl settings from the local drop-in.")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Write a conservative sysctl tuning drop-in and apply it.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the sysctl changes without applying them.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = configure_sysctl_tuning(dry_run=args.dry_run)
        print_result(result)
        return 0
    except Exception as exc:  # pragma: no cover - CLI safety net
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
