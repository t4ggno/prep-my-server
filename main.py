#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Callable

from apt_ergonomics import configure_apt_ergonomics
from automatic_cleanup import configure_automatic_cleanup
from automatic_reboot import configure_automatic_reboot
from common import FeatureResult, ensure_linux, ensure_root, get_sudo_invoking_user, print_result
from config import (
    CONFIG_PATH,
    get_setting,
    known_config_keys,
    load_config,
    non_default_settings,
    non_default_task_states,
    render_config,
    save_config,
    set_config_value,
    set_task_enabled,
    task_default_enabled,
    task_is_enabled,
    unset_config_value,
    validate_config_task_names,
)
from docker_install import install_docker
from docker_log_defaults import configure_docker_log_defaults
from docker_nightly_restart import configure_docker_nightly_restart
from fail2ban_setup import configure_fail2ban
from firewall_baseline import configure_firewall_baseline
from logrotate_tuning import configure_logrotate_tuning
from motd_status import configure_motd_status
from packages_baseline import install_baseline_packages
from shell_convenience import configure_shell_convenience
from ssh_banner import configure_ssh_banner, resolve_banner_text
from ssh_hardening_audit import audit_ssh_hardening
from ssh_speedups import configure_ssh_speedups
from sudo_session import configure_sudo_session
from sysctl_tuning import configure_sysctl_tuning
from time_sync import configure_time_sync
from timezone_locale import configure_timezone_locale
from unattended_upgrades import enable_unattended_upgrades

TASK_NAMES: tuple[str, ...] = (
    "baseline-packages",
    "timezone-locale",
    "time-sync",
    "unattended-upgrades",
    "apt-ergonomics",
    "motd-status",
    "logrotate-tuning",
    "sysctl-tuning",
    "fail2ban-setup",
    "automatic-cleanup",
    "automatic-reboot",
    "docker-install",
    "docker-log-defaults",
    "docker-nightly-restart",
    "shell-convenience",
    "ssh-speedups",
    "ssh-hardening-audit",
    "sudo-session-cache",
    "ssh-login-banner",
    "firewall-baseline",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare a Debian/Ubuntu Linux server with baseline packages, locale and timezone, "
            "maintenance automation, scheduled reboots, scheduled Docker restarts, "
            "APT ergonomics, Docker, "
            "firewall setup, time sync, shell conveniences, and SSH improvements."
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
    parser.add_argument(
        "--config-file",
        type=Path,
        default=CONFIG_PATH,
        help=f"Global prep-my-server config file (default: {CONFIG_PATH.as_posix()}).",
    )
    parser.add_argument(
        "--show-config",
        action="store_true",
        help="Print the current global config and exit unless task names are also passed.",
    )
    parser.add_argument(
        "--list-config-keys",
        action="store_true",
        help="List supported config keys and exit unless task names are also passed.",
    )
    parser.add_argument(
        "--set-config",
        nargs=2,
        action="append",
        metavar=("KEY", "VALUE"),
        help="Persist a config value, for example: --set-config timezone-locale.keyboard-layout us",
    )
    parser.add_argument(
        "--unset-config",
        action="append",
        metavar="KEY",
        help="Remove a config override so the built-in default is used again.",
    )
    parser.add_argument(
        "--disable",
        action="append",
        choices=TASK_NAMES,
        metavar="TASK",
        help="Persistently disable a task in the default full run.",
    )
    parser.add_argument(
        "--enable",
        action="append",
        choices=TASK_NAMES,
        metavar="TASK",
        help="Persistently enable a task in the default full run.",
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
    docker_group = parser.add_mutually_exclusive_group()
    docker_group.add_argument(
        "--docker-user",
        help=(
            "Optionally add a user to the docker group after Docker is installed. "
            "Defaults to the user that invoked sudo when one can be detected."
        ),
    )
    docker_group.add_argument(
        "--no-docker-user",
        action="store_true",
        help="Do not add any user to the docker group after Docker is installed.",
    )
    parser.add_argument(
        "--timezone",
        help="Timezone for the timezone-locale task, for example: America/New_York.",
    )
    parser.add_argument(
        "--locale",
        help="Default locale for the timezone-locale task, for example: en_US.UTF-8.",
    )
    parser.add_argument(
        "--language",
        help="LANGUAGE value for the timezone-locale task, for example: en_US:en.",
    )
    parser.add_argument(
        "--lc-time",
        help="LC_TIME value for the timezone-locale task, for example: en_US.UTF-8.",
    )
    parser.add_argument(
        "--keyboard-model",
        help="XKBMODEL value for the timezone-locale task.",
    )
    parser.add_argument(
        "--keyboard-layout",
        help="XKBLAYOUT value for the timezone-locale task, for example: us.",
    )
    parser.add_argument(
        "--keyboard-variant",
        help="XKBVARIANT value for the timezone-locale task.",
    )
    parser.add_argument(
        "--keyboard-options",
        help="XKBOPTIONS value for the timezone-locale task.",
    )
    parser.add_argument(
        "--keyboard-backspace",
        help="BACKSPACE value for the timezone-locale task.",
    )
    parser.add_argument(
        "--reboot-on-calendar",
        help=(
            "systemd OnCalendar expression for automatic-reboot, "
            "for example: '*-*-* 03:30:00'."
        ),
    )
    parser.add_argument(
        "--reboot-randomized-delay-sec",
        help="systemd RandomizedDelaySec value for automatic-reboot, for example: 30m.",
    )
    parser.add_argument(
        "--docker-restart-on-calendar",
        help=(
            "systemd OnCalendar expression for docker-nightly-restart, "
            "for example: '*-*-* 04:30:00'."
        ),
    )
    parser.add_argument(
        "--docker-restart-randomized-delay-sec",
        help="systemd RandomizedDelaySec value for docker-nightly-restart, for example: 30m.",
    )
    return parser


def config_operations_requested(args: argparse.Namespace) -> bool:
    return bool(args.set_config or args.unset_config or args.disable or args.enable)


def apply_config_operations(args: argparse.Namespace, config: dict[str, object]) -> FeatureResult:
    result = FeatureResult(name="global-config")
    changed = False

    for task_name in args.disable or []:
        if set_task_enabled(config, task_name, False):
            changed = True
            result.add_detail(f"Disabled {task_name} in the default full run.")
        else:
            result.add_detail(f"{task_name} was already disabled in the default full run.")

    for task_name in args.enable or []:
        if set_task_enabled(config, task_name, True):
            changed = True
            result.add_detail(f"Enabled {task_name} in the default full run.")
        else:
            result.add_detail(f"{task_name} was already enabled in the default full run.")

    for key, value in args.set_config or []:
        if set_config_value(config, key, value, task_names=TASK_NAMES):
            changed = True
            result.add_detail(f"Set {key}.")
        else:
            result.add_detail(f"{key} already had the requested value.")

    for key in args.unset_config or []:
        if unset_config_value(config, key, task_names=TASK_NAMES):
            changed = True
            result.add_detail(f"Unset {key}.")
        else:
            result.add_detail(f"{key} was already using the built-in default.")

    if changed:
        result.changed = True
    elif not result.details:
        result.add_detail("No config updates were requested.")

    return result


def resolve_docker_group_user(args: argparse.Namespace, config: dict[str, object]) -> str | None:
    if args.no_docker_user:
        return None
    if args.docker_user is not None:
        return args.docker_user
    configured_user = get_setting(config, "docker-install.user")
    if configured_user:
        return str(configured_user)
    if not get_setting(config, "docker-install.auto-sudo-user"):
        return None
    return get_sudo_invoking_user()


def resolve_banner_text_from_config(args: argparse.Namespace, config: dict[str, object]) -> str:
    if args.banner_text is not None or args.banner_file is not None:
        return resolve_banner_text(args.banner_text, args.banner_file)

    banner_text = get_setting(config, "ssh-login-banner.banner-text")
    banner_file_value = get_setting(config, "ssh-login-banner.banner-file")
    if banner_text and banner_file_value:
        raise RuntimeError(
            "Configure either ssh-login-banner.banner-text or ssh-login-banner.banner-file, not both."
        )
    banner_file = Path(str(banner_file_value)) if banner_file_value else None
    return resolve_banner_text(str(banner_text) if banner_text else None, banner_file)


def arg_or_setting(args: argparse.Namespace, attr_name: str, config: dict[str, object], key: str) -> str:
    value = getattr(args, attr_name)
    if value is not None:
        return value
    configured_value = get_setting(config, key)
    return "" if configured_value is None else str(configured_value)


def build_tasks(
    args: argparse.Namespace,
    config: dict[str, object],
) -> dict[str, Callable[[], FeatureResult]]:
    docker_group_user = resolve_docker_group_user(args, config)
    return {
        "baseline-packages": lambda: install_baseline_packages(dry_run=args.dry_run),
        "timezone-locale": lambda: configure_timezone_locale(
            dry_run=args.dry_run,
            timezone=arg_or_setting(args, "timezone", config, "timezone-locale.timezone"),
            locale=arg_or_setting(args, "locale", config, "timezone-locale.locale"),
            language=arg_or_setting(args, "language", config, "timezone-locale.language"),
            lc_time=arg_or_setting(args, "lc_time", config, "timezone-locale.lc-time"),
            keyboard_model=arg_or_setting(
                args,
                "keyboard_model",
                config,
                "timezone-locale.keyboard-model",
            ),
            keyboard_layout=arg_or_setting(
                args,
                "keyboard_layout",
                config,
                "timezone-locale.keyboard-layout",
            ),
            keyboard_variant=arg_or_setting(
                args,
                "keyboard_variant",
                config,
                "timezone-locale.keyboard-variant",
            ),
            keyboard_options=arg_or_setting(
                args,
                "keyboard_options",
                config,
                "timezone-locale.keyboard-options",
            ),
            keyboard_backspace=arg_or_setting(
                args,
                "keyboard_backspace",
                config,
                "timezone-locale.keyboard-backspace",
            ),
        ),
        "unattended-upgrades": lambda: enable_unattended_upgrades(dry_run=args.dry_run),
        "apt-ergonomics": lambda: configure_apt_ergonomics(dry_run=args.dry_run),
        "motd-status": lambda: configure_motd_status(dry_run=args.dry_run),
        "logrotate-tuning": lambda: configure_logrotate_tuning(dry_run=args.dry_run),
        "sysctl-tuning": lambda: configure_sysctl_tuning(dry_run=args.dry_run),
        "fail2ban-setup": lambda: configure_fail2ban(dry_run=args.dry_run),
        "time-sync": lambda: configure_time_sync(dry_run=args.dry_run),
        "automatic-cleanup": lambda: configure_automatic_cleanup(dry_run=args.dry_run),
        "automatic-reboot": lambda: configure_automatic_reboot(
            dry_run=args.dry_run,
            on_calendar=arg_or_setting(
                args,
                "reboot_on_calendar",
                config,
                "automatic-reboot.on-calendar",
            ),
            randomized_delay_sec=arg_or_setting(
                args,
                "reboot_randomized_delay_sec",
                config,
                "automatic-reboot.randomized-delay-sec",
            ),
        ),
        "docker-install": lambda: install_docker(
            dry_run=args.dry_run,
            add_user_to_docker_group=docker_group_user,
        ),
        "docker-log-defaults": lambda: configure_docker_log_defaults(dry_run=args.dry_run),
        "docker-nightly-restart": lambda: configure_docker_nightly_restart(
            dry_run=args.dry_run,
            on_calendar=arg_or_setting(
                args,
                "docker_restart_on_calendar",
                config,
                "docker-nightly-restart.on-calendar",
            ),
            randomized_delay_sec=arg_or_setting(
                args,
                "docker_restart_randomized_delay_sec",
                config,
                "docker-nightly-restart.randomized-delay-sec",
            ),
        ),
        "shell-convenience": lambda: configure_shell_convenience(dry_run=args.dry_run),
        "ssh-speedups": lambda: configure_ssh_speedups(dry_run=args.dry_run),
        "ssh-hardening-audit": lambda: audit_ssh_hardening(dry_run=args.dry_run),
        "sudo-session-cache": lambda: configure_sudo_session(dry_run=args.dry_run),
        "ssh-login-banner": lambda: configure_ssh_banner(
            banner_text=resolve_banner_text_from_config(args, config),
            dry_run=args.dry_run,
        ),
        "firewall-baseline": lambda: configure_firewall_baseline(dry_run=args.dry_run),
    }


def select_task_names(args: argparse.Namespace, config: dict[str, object]) -> tuple[list[str], list[str]]:
    if args.tasks:
        return list(args.tasks), []

    selected = [task_name for task_name in TASK_NAMES if task_is_enabled(config, task_name)]
    skipped = [task_name for task_name in TASK_NAMES if not task_is_enabled(config, task_name)]
    return selected, skipped


def _enabled_label(enabled: bool) -> str:
    return "enabled" if enabled else "disabled"


def _format_config_value(value: object) -> str:
    return json.dumps(value, sort_keys=True)


def _format_key_values(values: dict[str, object]) -> str:
    if not values:
        return "none"
    return ", ".join(f"{key}={_format_config_value(value)}" for key, value in values.items())


def _format_task_states(task_states: dict[str, bool]) -> str:
    if not task_states:
        return "none"
    return ", ".join(f"{task_name}={_enabled_label(enabled)}" for task_name, enabled in task_states.items())


def _format_disabled_tasks(task_names: list[str]) -> str:
    if not task_names:
        return "none"
    return ", ".join(
        f"{task_name} ({'default' if not task_default_enabled(task_name) else 'config'})"
        for task_name in task_names
    )


def _format_default_disabled_feature_states(
    config: dict[str, object],
    selected_task_names: list[str],
    task_state_overrides: dict[str, bool],
) -> str:
    states: list[str] = []
    for task_name in TASK_NAMES:
        if task_default_enabled(task_name):
            continue
        enabled = task_is_enabled(config, task_name)
        source = "config override" if task_name in task_state_overrides else "default"
        selection = "selected" if task_name in selected_task_names else "not selected"
        states.append(f"{task_name}={_enabled_label(enabled)} ({source}; {selection})")
    return ", ".join(states) if states else "none"


def print_execution_config(
    args: argparse.Namespace,
    config: dict[str, object],
    selected_task_names: list[str],
    skipped_task_names: list[str],
) -> None:
    task_state_overrides = non_default_task_states(config, TASK_NAMES)
    setting_overrides = non_default_settings(config)

    print("Execution config:")
    if args.tasks:
        print(
            "  - Task selection: explicit ("
            + ", ".join(selected_task_names)
            + "); task enablement defaults are bypassed."
        )
    else:
        print(f"  - Disabled tasks: {_format_disabled_tasks(skipped_task_names)}")
    print(
        "  - Default-disabled features: "
        + _format_default_disabled_feature_states(
            config,
            selected_task_names,
            task_state_overrides,
        )
    )
    print(f"  - Non-default task enablement: {_format_task_states(task_state_overrides)}")
    print(f"  - Non-default settings: {_format_key_values(setting_overrides)}")
    print()


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.list_config_keys:
            print("Supported config keys:")
            for key in known_config_keys(TASK_NAMES):
                print(f"  - {key}")
            print()
            if not (args.show_config or config_operations_requested(args) or args.tasks):
                return 0

        config = load_config(args.config_file)

        config_result = None
        if config_operations_requested(args):
            config_result = apply_config_operations(args, config)

        validate_config_task_names(config, TASK_NAMES)

        if config_result is not None:
            if config_result.changed:
                if args.dry_run:
                    config_result.add_detail(f"Would write {args.config_file}.")
                else:
                    ensure_linux()
                    ensure_root()
                    save_config(config, args.config_file)
                    config_result.add_detail(f"Wrote {args.config_file}.")
            print_result(config_result)
            print()

        if args.show_config:
            print(f"Config file: {args.config_file.as_posix()}")
            print(render_config(config))
            print()

        if (args.list_config_keys or args.show_config or config_operations_requested(args)) and not args.tasks:
            return 0

        task_map = build_tasks(args, config)
        selected_task_names, skipped_task_names = select_task_names(args, config)
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    print_execution_config(args, config, selected_task_names, skipped_task_names)

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
