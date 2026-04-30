#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys

from common import (
    FeatureResult,
    ensure_apt_system,
    ensure_linux,
    ensure_root,
    find_command,
    format_command,
    is_systemd_available,
    package_is_installed,
    print_result,
    run_checked,
    try_run,
)

TIMESYNCD_PACKAGE = "systemd-timesyncd"
CHRONY_PACKAGE = "chrony"


def _systemd_unit_needs_enable_or_start(systemctl: str, unit_name: str) -> bool:
    enabled, _enabled_output = try_run([systemctl, "is-enabled", "--quiet", unit_name])
    active, _active_output = try_run([systemctl, "is-active", "--quiet", unit_name])
    return not (enabled and active)


def _timedatectl_summary() -> str | None:
    try:
        timedatectl = find_command(["timedatectl"])
    except RuntimeError:
        return None

    success, output = try_run(
        [
            timedatectl,
            "show",
            "--property=NTP",
            "--property=NTPSynchronized",
            "--property=Timezone",
        ]
    )
    if not success or not output.strip():
        return None

    values: dict[str, str] = {}
    for raw_line in output.splitlines():
        key, separator, value = raw_line.partition("=")
        if separator:
            values[key] = value

    parts = []
    for key in ("NTP", "NTPSynchronized", "Timezone"):
        if key in values:
            parts.append(f"{key}={values[key]}")
    return ", ".join(parts) if parts else None


def configure_time_sync(*, dry_run: bool = False) -> FeatureResult:
    ensure_linux()
    ensure_root(dry_run=dry_run)

    apt_get, dpkg_query = ensure_apt_system()
    chrony_installed = package_is_installed(CHRONY_PACKAGE, dpkg_query_path=dpkg_query)
    timesyncd_installed = package_is_installed(TIMESYNCD_PACKAGE, dpkg_query_path=dpkg_query)
    install_timesyncd = not chrony_installed and not timesyncd_installed
    preferred_unit = "chrony.service" if chrony_installed else "systemd-timesyncd.service"

    result = FeatureResult(name="time-sync")
    if not is_systemd_available():
        result.add_warning("Systemd was not detected, so automatic time sync service enablement was skipped.")
        return result

    systemctl = find_command(["systemctl"])
    timedatectl = None
    try:
        timedatectl = find_command(["timedatectl"])
    except RuntimeError:
        pass

    if dry_run:
        if install_timesyncd:
            result.add_detail(f"Would run: {format_command([apt_get, 'update'])}")
            result.add_detail(
                f"Would run: {format_command([apt_get, 'install', '-y', '--no-install-recommends', TIMESYNCD_PACKAGE])}"
            )
            result.changed = True
        else:
            result.add_detail(
                f"Time sync package already present: {CHRONY_PACKAGE if chrony_installed else TIMESYNCD_PACKAGE}."
            )

        if _systemd_unit_needs_enable_or_start(systemctl, preferred_unit):
            result.add_detail(f"Would run: {format_command([systemctl, 'enable', '--now', preferred_unit])}")
            result.changed = True
        else:
            result.add_detail(f"{preferred_unit} is already enabled and active.")

        if timedatectl:
            result.add_detail(f"Would run: {format_command([timedatectl, 'set-ntp', 'true'])}")
        status = _timedatectl_summary()
        if status:
            result.add_detail(f"Current timedatectl status: {status}.")
        return result

    if install_timesyncd:
        run_checked([apt_get, "update"])
        run_checked(
            [apt_get, "install", "-y", "--no-install-recommends", TIMESYNCD_PACKAGE],
            env={"DEBIAN_FRONTEND": "noninteractive"},
        )
        result.add_detail(f"Installed {TIMESYNCD_PACKAGE}.")
        result.changed = True
        preferred_unit = "systemd-timesyncd.service"

    if _systemd_unit_needs_enable_or_start(systemctl, preferred_unit):
        run_checked([systemctl, "enable", "--now", preferred_unit])
        result.add_detail(f"Enabled and started {preferred_unit}.")
        result.changed = True
    else:
        result.add_detail(f"{preferred_unit} is already enabled and active.")

    if timedatectl:
        run_checked([timedatectl, "set-ntp", "true"])
        result.add_detail("Enabled NTP synchronization with timedatectl.")

    status = _timedatectl_summary()
    if status:
        result.add_detail(f"timedatectl status: {status}.")

    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Ensure a system time synchronization service is installed and enabled.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview time synchronization changes without applying them.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = configure_time_sync(dry_run=args.dry_run)
        print_result(result)
        return 0
    except Exception as exc:  # pragma: no cover - CLI safety net
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
