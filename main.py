#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Callable

from automatic_cleanup import configure_automatic_cleanup
from common import FeatureResult, print_result
from docker_install import install_docker
from fail2ban_setup import configure_fail2ban
from logrotate_tuning import configure_logrotate_tuning
from motd_status import configure_motd_status
from packages_baseline import install_baseline_packages
from shell_convenience import configure_shell_convenience
from ssh_banner import configure_ssh_banner, resolve_banner_text
from ssh_speedups import configure_ssh_speedups
from sudo_session import configure_sudo_session
from sysctl_tuning import configure_sysctl_tuning
from timezone_locale import configure_timezone_locale
from unattended_upgrades import enable_unattended_upgrades

TASK_NAMES: tuple[str, ...] = (
    "baseline-packages",
    "timezone-locale",
    "unattended-upgrades",
    "motd-status",
    "logrotate-tuning",
    "sysctl-tuning",
    "fail2ban-setup",
    "automatic-cleanup",
    "docker-install",
    "shell-convenience",
    "ssh-speedups",
    "sudo-session-cache",
    "ssh-login-banner",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare a Debian/Ubuntu Linux server with baseline packages, locale and timezone, "
            "maintenance automation, Docker, shell conveniences, and SSH improvements."
        ),
    )
    parser.add_argument(
        "tasks",
        nargs="*",
        choices=TASK_NAMES,
        help="Optional task names to run. When omitted, all tasks run in the default order.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the work without changing the server.",
    )
    banner_group = parser.add_mutually_exclusive_group()
    banner_group.add_argument(
        "--banner-text",
        help="Custom SSH banner text.",
    )
    banner_group.add_argument(
        "--banner-file",
        type=Path,
        help="Read the SSH banner text from a file.",
    )
    parser.add_argument(
        "--docker-user",
        help=(
            "Optionally add a user to the docker group after Docker is installed. "
            "Omit this to keep Docker root-only."
        ),
    )
    return parser


def build_tasks(args: argparse.Namespace) -> dict[str, Callable[[], FeatureResult]]:
    return {
        "baseline-packages": lambda: install_baseline_packages(dry_run=args.dry_run),
        "timezone-locale": lambda: configure_timezone_locale(dry_run=args.dry_run),
        "unattended-upgrades": lambda: enable_unattended_upgrades(dry_run=args.dry_run),
        "motd-status": lambda: configure_motd_status(dry_run=args.dry_run),
        "logrotate-tuning": lambda: configure_logrotate_tuning(dry_run=args.dry_run),
        "sysctl-tuning": lambda: configure_sysctl_tuning(dry_run=args.dry_run),
        "fail2ban-setup": lambda: configure_fail2ban(dry_run=args.dry_run),
        "automatic-cleanup": lambda: configure_automatic_cleanup(dry_run=args.dry_run),
        "docker-install": lambda: install_docker(
            dry_run=args.dry_run,
            add_user_to_docker_group=args.docker_user,
        ),
        "shell-convenience": lambda: configure_shell_convenience(dry_run=args.dry_run),
        "ssh-speedups": lambda: configure_ssh_speedups(dry_run=args.dry_run),
        "sudo-session-cache": lambda: configure_sudo_session(dry_run=args.dry_run),
        "ssh-login-banner": lambda: configure_ssh_banner(
            banner_text=resolve_banner_text(args.banner_text, args.banner_file),
            dry_run=args.dry_run,
        ),
    }


def main() -> int:
    args = build_parser().parse_args()
    task_map = build_tasks(args)
    selected_task_names = list(args.tasks) if args.tasks else list(TASK_NAMES)

    had_error = False
    for task_name in selected_task_names:
        task = task_map[task_name]
        try:
            result = task()
            print_result(result)
            print()
        except Exception as exc:  # pragma: no cover - CLI safety net
            had_error = True
            print(f"[ERROR] {task_name}: {exc}", file=sys.stderr)
            print(file=sys.stderr)

    if had_error:
        print("Finished with one or more errors.", file=sys.stderr)
        return 1

    print("All requested tasks completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
