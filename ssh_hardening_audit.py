#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from common import (
    FeatureResult,
    ensure_linux,
    find_command,
    print_result,
    run_checked,
)

SSHD_CONFIG_PATH = Path("/etc/ssh/sshd_config")


def _effective_sshd_config(sshd_config_path: Path) -> dict[str, list[str]]:
    if not sshd_config_path.exists():
        raise RuntimeError(f"{sshd_config_path} does not exist.")

    sshd = find_command(["sshd", "/usr/sbin/sshd", "/usr/local/sbin/sshd"])
    run_checked([sshd, "-t", "-f", str(sshd_config_path)])
    output = run_checked([sshd, "-T", "-f", str(sshd_config_path)]).stdout

    values: dict[str, list[str]] = {}
    for raw_line in output.splitlines():
        key, _separator, value = raw_line.partition(" ")
        if not key:
            continue
        values.setdefault(key.lower(), []).append(value.strip())
    return values


def _first(config: dict[str, list[str]], key: str, default: str = "unknown") -> str:
    values = config.get(key.lower())
    if not values:
        return default
    return values[0]


def audit_ssh_hardening(
    *,
    dry_run: bool = False,
    sshd_config_path: Path = SSHD_CONFIG_PATH,
) -> FeatureResult:
    ensure_linux()

    result = FeatureResult(name="ssh-hardening-audit")
    if dry_run:
        result.add_detail("Would validate SSH configuration and report hardening findings.")

    config = _effective_sshd_config(sshd_config_path)
    result.add_detail(f"Validated {sshd_config_path} with sshd -t and read effective settings with sshd -T.")

    permit_root_login = _first(config, "permitrootlogin")
    password_authentication = _first(config, "passwordauthentication")
    pubkey_authentication = _first(config, "pubkeyauthentication")
    permit_empty_passwords = _first(config, "permitemptypasswords")
    kbd_interactive_authentication = _first(config, "kbdinteractiveauthentication")
    ports = config.get("port", ["22"])

    if permit_root_login == "yes":
        result.add_warning("PermitRootLogin is yes. Prefer no or prohibit-password once a non-root admin path is confirmed.")
    else:
        result.add_detail(f"PermitRootLogin is {permit_root_login}.")

    if password_authentication == "yes":
        result.add_warning("PasswordAuthentication is yes. Prefer key-only SSH once all admins have working keys.")
    else:
        result.add_detail(f"PasswordAuthentication is {password_authentication}.")

    if kbd_interactive_authentication == "yes":
        result.add_warning("KbdInteractiveAuthentication is yes. This can still permit PAM-backed password-style login.")
    else:
        result.add_detail(f"KbdInteractiveAuthentication is {kbd_interactive_authentication}.")

    if pubkey_authentication != "yes":
        result.add_warning("PubkeyAuthentication is not yes. Key-based SSH should normally stay enabled.")
    else:
        result.add_detail("PubkeyAuthentication is enabled.")

    if permit_empty_passwords == "yes":
        result.add_warning("PermitEmptyPasswords is yes. This should be disabled.")
    else:
        result.add_detail(f"PermitEmptyPasswords is {permit_empty_passwords}.")

    result.add_detail("Effective SSH ports: " + ", ".join(sorted(set(ports), key=int)))
    result.add_detail("This task is audit-only and does not edit SSH configuration.")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit conservative SSH hardening settings without changing SSH config.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show that the SSH hardening audit would run.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = audit_ssh_hardening(dry_run=args.dry_run)
        print_result(result)
        return 0
    except Exception as exc:  # pragma: no cover - CLI safety net
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
