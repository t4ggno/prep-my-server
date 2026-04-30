#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys

from common import (
    FeatureResult,
    ensure_apt_system,
    ensure_linux,
    ensure_root,
    format_command,
    get_missing_packages,
    print_result,
    run_checked,
)

BASELINE_PACKAGES: tuple[str, ...] = (
    "bash-completion",
    "ca-certificates",
    "curl",
    "dnsutils",
    "git",
    "htop",
    "iproute2",
    "iputils-ping",
    "jq",
    "less",
    "lsof",
    "ncdu",
    "netcat-openbsd",
    "ripgrep",
    "rsync",
    "socat",
    "sudo",
    "tmux",
    "tree",
    "unzip",
    "vim",
    "wget",
    "zip",
)


def install_baseline_packages(
    *,
    dry_run: bool = False,
    packages: tuple[str, ...] = BASELINE_PACKAGES,
) -> FeatureResult:
    ensure_linux()
    ensure_root(dry_run=dry_run)

    apt_get, dpkg_query = ensure_apt_system()
    missing_packages = get_missing_packages(packages, dpkg_query_path=dpkg_query)

    result = FeatureResult(name="baseline-packages")
    if not missing_packages:
        result.add_detail("All baseline packages are already installed.")
        return result

    update_command = [apt_get, "update"]
    install_command = [
        apt_get,
        "install",
        "-y",
        "--no-install-recommends",
        *missing_packages,
    ]

    result.add_detail(
        "Missing baseline packages: " + ", ".join(missing_packages)
    )

    if dry_run:
        result.changed = True
        result.add_detail(f"Would run: {format_command(update_command)}")
        result.add_detail(f"Would run: {format_command(install_command)}")
        return result

    run_checked(update_command)
    run_checked(install_command, env={"DEBIAN_FRONTEND": "noninteractive"})

    result.changed = True
    result.add_detail("Installed the missing baseline packages.")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Install a baseline set of Debian/Ubuntu server packages.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the package changes without applying them.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = install_baseline_packages(dry_run=args.dry_run)
        print_result(result)
        return 0
    except Exception as exc:  # pragma: no cover - CLI safety net
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
