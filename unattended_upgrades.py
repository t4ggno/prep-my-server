#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from common import (
    FeatureResult,
    ensure_linux,
    ensure_root,
    find_command,
    format_command,
    is_systemd_available,
    normalize_text,
    print_result,
    run_checked,
    write_text_if_changed,
)

APT_OVERRIDE_PATH = Path("/etc/apt/apt.conf.d/99prep-my-server-auto-upgrades")
APT_OVERRIDE_CONTENT = normalize_text(
    """// Managed by prep-my-server.
APT::Periodic::Update-Package-Lists \"1\";
APT::Periodic::Unattended-Upgrade \"1\";"""
)


def enable_unattended_upgrades(
    *,
    dry_run: bool = False,
    override_path: Path = APT_OVERRIDE_PATH,
) -> FeatureResult:
    ensure_linux()
    ensure_root(dry_run=dry_run)

    try:
        apt_get = find_command(["apt-get"])
    except RuntimeError as exc:
        raise RuntimeError(
            "This unattended-upgrades helper targets Debian/Ubuntu systems that provide apt-get."
        ) from exc

    result = FeatureResult(name="unattended-upgrades")

    if dry_run:
        result.changed = True
        result.add_detail(f"Would run: {format_command([apt_get, 'update'])}")
        result.add_detail(
            f"Would run: {format_command([apt_get, 'install', '-y', 'unattended-upgrades'])}"
        )
    else:
        run_checked([apt_get, "update"])
        run_checked(
            [apt_get, "install", "-y", "unattended-upgrades"],
            env={"DEBIAN_FRONTEND": "noninteractive"},
        )
        result.changed = True
        result.add_detail("Installed or confirmed the unattended-upgrades package.")

    override_needs_update = not override_path.exists() or (
        override_path.read_text(encoding="utf-8") != APT_OVERRIDE_CONTENT
    )
    if dry_run:
        if override_needs_update:
            result.add_detail(f"Would write {override_path}.")
            result.changed = True
        else:
            result.add_detail(f"{override_path} already has the desired settings.")
    else:
        file_changed = write_text_if_changed(override_path, APT_OVERRIDE_CONTENT, mode=0o644)
        if file_changed:
            result.add_detail(f"Wrote {override_path}.")
            result.changed = True
        else:
            result.add_detail(f"{override_path} already has the desired settings.")

    if is_systemd_available():
        systemctl = find_command(["systemctl"])
        command = [systemctl, "enable", "--now", "apt-daily.timer", "apt-daily-upgrade.timer"]
        if dry_run:
            result.add_detail(f"Would run: {format_command(command)}")
        else:
            run_checked(command)
            result.add_detail("Enabled apt-daily.timer and apt-daily-upgrade.timer.")
            result.changed = True
    else:
        result.add_warning(
            "Systemd was not detected, so timer enablement was skipped. The APT config was still written."
        )

    result.add_detail(
        "Left the distro-managed 50unattended-upgrades policy intact so the default allowed origins stay in place."
    )
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Enable unattended upgrades on Debian/Ubuntu systems.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview commands and file changes without applying them.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = enable_unattended_upgrades(dry_run=args.dry_run)
        print_result(result)
        return 0
    except Exception as exc:  # pragma: no cover - CLI safety net
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
