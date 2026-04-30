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
    is_systemd_available,
    print_result,
    run_checked,
    try_run,
)

SSHD_CONFIG_PATH = Path("/etc/ssh/sshd_config")
FIREWALL_PACKAGE = ("ufw",)
COMMON_SERVICE_RULES: tuple[tuple[tuple[str, ...], tuple[tuple[str, str, str], ...]], ...] = (
    (
        ("nginx.service", "apache2.service", "httpd.service", "caddy.service", "lighttpd.service"),
        (("80", "tcp", "web HTTP"), ("443", "tcp", "web HTTPS")),
    ),
    (
        ("bind9.service", "named.service", "unbound.service", "dnsmasq.service"),
        (("53", "tcp", "DNS TCP"), ("53", "udp", "DNS UDP")),
    ),
    (
        ("isc-dhcp-server.service", "kea-dhcp4-server.service"),
        (("67", "udp", "DHCP IPv4 server"),),
    ),
    (
        ("isc-dhcp-server6.service", "kea-dhcp6-server.service"),
        (("547", "udp", "DHCP IPv6 server"),),
    ),
)


def _service_is_active(systemctl: str, service_name: str) -> bool:
    success, _output = try_run([systemctl, "is-active", "--quiet", service_name])
    return success


def _validate_and_read_ssh_ports(sshd_config_path: Path = SSHD_CONFIG_PATH) -> list[int]:
    if not sshd_config_path.exists():
        raise RuntimeError(f"{sshd_config_path} does not exist; refusing to enable a firewall without SSH config validation.")

    sshd = find_command(["sshd", "/usr/sbin/sshd", "/usr/local/sbin/sshd"])
    run_checked([sshd, "-t", "-f", str(sshd_config_path)])
    effective_config = run_checked([sshd, "-T", "-f", str(sshd_config_path)]).stdout

    ports: set[int] = set()
    for raw_line in effective_config.splitlines():
        key, _separator, value = raw_line.partition(" ")
        if key.lower() != "port":
            continue
        try:
            port = int(value.strip())
        except ValueError as exc:
            raise RuntimeError(f"Could not parse SSH port from sshd -T output: {raw_line}") from exc
        if not 1 <= port <= 65535:
            raise RuntimeError(f"SSH port is outside the valid TCP port range: {port}")
        ports.add(port)

    if not ports:
        raise RuntimeError("Could not determine any SSH ports from sshd -T; refusing to enable the firewall.")

    return sorted(ports)


def _detect_common_service_rules() -> tuple[list[tuple[str, str, str]], list[str]]:
    if not is_systemd_available():
        return [], ["Systemd was not detected, so common service auto-detection was skipped."]

    systemctl = find_command(["systemctl"])
    rules: dict[tuple[str, str], str] = {}
    active_services: list[str] = []

    for service_names, service_rules in COMMON_SERVICE_RULES:
        active_group_services = [
            service_name
            for service_name in service_names
            if _service_is_active(systemctl, service_name)
        ]
        if not active_group_services:
            continue

        active_services.extend(active_group_services)
        for port, protocol, label in service_rules:
            rules[(port, protocol)] = label

    warnings: list[str] = []
    if not active_services:
        warnings.append("No common web, DNS, or DHCP services were detected as active.")

    return [
        (port, protocol, label)
        for (port, protocol), label in sorted(rules.items(), key=lambda item: (int(item[0][0]), item[0][1]))
    ], warnings


def _ufw_allow_command(ufw: str, port: str, protocol: str, label: str) -> list[str]:
    return [ufw, "allow", f"{port}/{protocol}", "comment", f"prep-my-server {label}"]


def configure_firewall_baseline(*, dry_run: bool = False) -> FeatureResult:
    ensure_linux()
    ensure_root(dry_run=dry_run)

    apt_get, dpkg_query = ensure_apt_system()
    missing_packages = get_missing_packages(FIREWALL_PACKAGE, dpkg_query_path=dpkg_query)
    ssh_ports = _validate_and_read_ssh_ports()
    service_rules, service_warnings = _detect_common_service_rules()

    try:
        ufw = find_command(["ufw"])
    except RuntimeError:
        ufw = "ufw"

    result = FeatureResult(name="firewall-baseline")
    for warning in service_warnings:
        result.add_warning(warning)

    ssh_rules = [(str(port), "tcp", "SSH") for port in ssh_ports]
    rules = [*ssh_rules, *service_rules]

    if dry_run:
        if missing_packages:
            result.add_detail(f"Would run: {format_command([apt_get, 'update'])}")
            result.add_detail(
                f"Would run: {format_command([apt_get, 'install', '-y', '--no-install-recommends', *missing_packages])}"
            )
            result.changed = True
        else:
            result.add_detail("ufw is already installed.")

        result.add_detail(
            "Validated SSH config and would keep SSH reachable on: "
            + ", ".join(f"{port}/tcp" for port in ssh_ports)
        )
        if service_rules:
            result.add_detail(
                "Would allow detected service ports: "
                + ", ".join(f"{port}/{protocol} ({label})" for port, protocol, label in service_rules)
            )

        for port, protocol, label in rules:
            result.add_detail(f"Would run: {format_command(_ufw_allow_command(ufw, port, protocol, label))}")
        result.add_detail(f"Would run: {format_command([ufw, 'default', 'deny', 'incoming'])}")
        result.add_detail(f"Would run: {format_command([ufw, 'default', 'allow', 'outgoing'])}")
        result.add_detail(f"Would run: {format_command([ufw, '--force', 'enable'])}")
        result.changed = True
        return result

    if missing_packages:
        run_checked([apt_get, "update"])
        run_checked(
            [apt_get, "install", "-y", "--no-install-recommends", *missing_packages],
            env={"DEBIAN_FRONTEND": "noninteractive"},
        )
        result.add_detail("Installed ufw.")
        result.changed = True

    ufw = find_command(["ufw"])
    result.add_detail(
        "Validated SSH config and keeping SSH reachable on: "
        + ", ".join(f"{port}/tcp" for port in ssh_ports)
    )
    if service_rules:
        result.add_detail(
            "Allowing detected service ports: "
            + ", ".join(f"{port}/{protocol} ({label})" for port, protocol, label in service_rules)
        )

    for port, protocol, label in rules:
        run_checked(_ufw_allow_command(ufw, port, protocol, label))

    run_checked([ufw, "default", "deny", "incoming"])
    run_checked([ufw, "default", "allow", "outgoing"])
    run_checked([ufw, "--force", "enable"])
    result.changed = True
    result.add_detail("Enabled ufw with default deny incoming and default allow outgoing.")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Install and enable a conservative UFW firewall baseline.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview firewall changes without applying them.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = configure_firewall_baseline(dry_run=args.dry_run)
        print_result(result)
        return 0
    except Exception as exc:  # pragma: no cover - CLI safety net
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
