#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from common import (
    FeatureResult,
    capture_snapshot,
    ensure_apt_system,
    ensure_linux,
    ensure_root,
    find_command,
    format_command,
    get_missing_packages,
    is_systemd_available,
    normalize_text,
    print_result,
    restore_snapshot,
    run_checked,
    try_run,
    write_text_if_changed,
)

FAIL2BAN_CONFIG_PATH = Path("/etc/fail2ban/jail.d/90-prep-my-server.local")
FAIL2BAN_PACKAGE = ("fail2ban",)
FAIL2BAN_CONFIG = normalize_text(
    """# Managed by prep-my-server.
[DEFAULT]
bantime = 1h
findtime = 10m
maxretry = 5
ignoreip = 127.0.0.1/8 ::1

[sshd]
enabled = true"""
)


def _reload_fail2ban() -> tuple[bool, str]:
    attempted: list[str] = []

    if is_systemd_available():
        systemctl = find_command(["systemctl"])
        run_checked([systemctl, "enable", "fail2ban"])
        for command in (
            [systemctl, "reload", "fail2ban"],
            [systemctl, "restart", "fail2ban"],
            [systemctl, "start", "fail2ban"],
        ):
            success, output = try_run(command)
            attempted.append(f"{format_command(command)} -> {output if output else 'no output'}")
            if success:
                return True, ""
        return False, "\n".join(attempted)

    try:
        service_command = find_command(["service", "/usr/sbin/service", "/usr/bin/service"])
        for command in (
            [service_command, "fail2ban", "restart"],
            [service_command, "fail2ban", "start"],
        ):
            success, output = try_run(command)
            attempted.append(f"{format_command(command)} -> {output if output else 'no output'}")
            if success:
                return True, ""
    except RuntimeError:
        pass

    return False, "\n".join(attempted)


def configure_fail2ban(
    *,
    dry_run: bool = False,
    config_path: Path = FAIL2BAN_CONFIG_PATH,
) -> FeatureResult:
    ensure_linux()
    ensure_root(dry_run=dry_run)

    apt_get, dpkg_query = ensure_apt_system()
    missing_packages = get_missing_packages(FAIL2BAN_PACKAGE, dpkg_query_path=dpkg_query)
    try:
        fail2ban_client = find_command(["fail2ban-client"])
    except RuntimeError:
        fail2ban_client = "fail2ban-client"
    validate_command = [fail2ban_client, "-t"]

    config_snapshot = capture_snapshot(config_path)
    config_needs_update = (
        not config_snapshot.existed
        or config_snapshot.content != FAIL2BAN_CONFIG
        or config_snapshot.mode != 0o644
    )

    result = FeatureResult(name="fail2ban-setup")

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
            result.add_detail("Installed fail2ban.")
            result.changed = True
            fail2ban_client = find_command(["fail2ban-client"])
            validate_command = [fail2ban_client, "-t"]

    if dry_run:
        if config_needs_update:
            result.add_detail(f"Would write {config_path}.")
            result.changed = True
        else:
            result.add_detail(f"{config_path} already has the desired sshd jail settings.")
        result.add_detail(f"Would validate with: {format_command(validate_command)}")
        result.add_detail("Would enable and reload the fail2ban service.")
        result.add_warning(
            "Review ignoreip after deployment if you manage the server from a fixed office or home IP."
        )
        return result

    try:
        if write_text_if_changed(config_path, FAIL2BAN_CONFIG, mode=0o644):
            result.add_detail(f"Wrote {config_path}.")
            result.changed = True
        else:
            result.add_detail(f"{config_path} already has the desired sshd jail settings.")

        run_checked(validate_command)
        result.add_detail("Validated the Fail2Ban configuration with fail2ban-client -t.")
    except Exception:
        restore_snapshot(config_path, config_snapshot)
        raise

    reloaded, reload_output = _reload_fail2ban()
    if reloaded:
        result.add_detail("Enabled and reloaded the fail2ban service.")
    else:
        result.add_warning(
            "The configuration validated successfully, but fail2ban could not be enabled/reloaded automatically."
        )
        if reload_output:
            result.add_warning(reload_output)

    result.add_warning(
        "Review ignoreip after deployment if you manage the server from a fixed office or home IP."
    )
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Install Fail2Ban and enable a modest sshd jail override.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the Fail2Ban changes without applying them.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = configure_fail2ban(dry_run=args.dry_run)
        print_result(result)
        return 0
    except Exception as exc:  # pragma: no cover - CLI safety net
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
