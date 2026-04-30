#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys

from common import (
    FeatureResult,
    capture_snapshot,
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

SSHD_CONFIG_PATH = Path("/etc/ssh/sshd_config")
_INCLUDE_LINE_RE = re.compile(r"^\s*Include\b", re.IGNORECASE)
_MATCH_LINE_RE = re.compile(r"^\s*Match\b", re.IGNORECASE)
_DIRECTIVE_MAP: tuple[tuple[str, str], ...] = (
    ("UseDNS", "no"),
    ("GSSAPIAuthentication", "no"),
    ("ClientAliveInterval", "300"),
    ("ClientAliveCountMax", "2"),
    ("PrintMotd", "no"),
)
_DIRECTIVE_RE = re.compile(
    r"^\s*#?\s*(UseDNS|GSSAPIAuthentication|ClientAliveInterval|ClientAliveCountMax|PrintMotd)\b",
    re.IGNORECASE,
)


def _render_sshd_config(config_text: str) -> str:
    lines = config_text.splitlines()
    new_lines: list[str] = []
    block_inserted = False
    in_match_block = False

    for line in lines:
        stripped = line.lstrip()
        is_active_include = bool(_INCLUDE_LINE_RE.match(line)) and not stripped.startswith("#")
        is_active_match = bool(_MATCH_LINE_RE.match(line)) and not stripped.startswith("#")

        if (is_active_include or is_active_match) and not block_inserted:
            if new_lines and new_lines[-1].strip():
                new_lines.append("")
            new_lines.append("# Managed by prep-my-server")
            for directive, value in _DIRECTIVE_MAP:
                new_lines.append(f"{directive} {value}")
            block_inserted = True

        if not in_match_block and _DIRECTIVE_RE.match(line):
            continue

        new_lines.append(line)
        if is_active_match:
            in_match_block = True

    if not block_inserted:
        if new_lines and new_lines[-1].strip():
            new_lines.append("")
        new_lines.append("# Managed by prep-my-server")
        for directive, value in _DIRECTIVE_MAP:
            new_lines.append(f"{directive} {value}")

    return normalize_text("\n".join(new_lines))


def _reload_ssh_service() -> tuple[bool, str]:
    attempted: list[str] = []
    candidate_commands: list[list[str]] = []

    if is_systemd_available():
        systemctl = find_command(["systemctl"])
        candidate_commands.extend(
            [
                [systemctl, "reload", "ssh"],
                [systemctl, "reload", "sshd"],
            ]
        )

    try:
        service_command = find_command(["service", "/usr/sbin/service", "/usr/bin/service"])
        candidate_commands.extend(
            [
                [service_command, "ssh", "reload"],
                [service_command, "sshd", "reload"],
            ]
        )
    except RuntimeError:
        pass

    for command in candidate_commands:
        success, output = try_run(command)
        attempted.append(f"{format_command(command)} -> {output if output else 'no output'}")
        if success:
            return True, ""

    return False, "\n".join(attempted)


def configure_ssh_speedups(
    *,
    dry_run: bool = False,
    sshd_config_path: Path = SSHD_CONFIG_PATH,
) -> FeatureResult:
    ensure_linux()
    ensure_root(dry_run=dry_run)

    if not sshd_config_path.exists():
        raise RuntimeError(f"{sshd_config_path} does not exist.")

    sshd_binary = find_command(["sshd", "/usr/sbin/sshd", "/usr/local/sbin/sshd"])
    config_snapshot = capture_snapshot(sshd_config_path)
    desired_config = _render_sshd_config(config_snapshot.content or "")
    config_needs_update = desired_config != (config_snapshot.content or "")
    validate_command = [sshd_binary, "-t", "-f", str(sshd_config_path)]

    result = FeatureResult(name="ssh-speedups")
    if dry_run:
        if config_needs_update:
            result.add_detail(f"Would update {sshd_config_path}.")
            result.changed = True
        else:
            result.add_detail(f"{sshd_config_path} already has the desired speed-focused settings.")
        result.add_detail(f"Would validate with: {format_command(validate_command)}")
        result.add_detail("Would attempt to reload the SSH service (ssh or sshd).")
        return result

    try:
        if write_text_if_changed(
            sshd_config_path,
            desired_config,
            mode=config_snapshot.mode if config_snapshot.mode is not None else 0o600,
        ):
            result.add_detail(f"Updated {sshd_config_path}.")
            result.changed = True
        else:
            result.add_detail(f"{sshd_config_path} already has the desired speed-focused settings.")

        run_checked(validate_command)
    except Exception:
        restore_snapshot(sshd_config_path, config_snapshot)
        raise

    if config_needs_update:
        reloaded, reload_output = _reload_ssh_service()
        if reloaded:
            result.add_detail("Reloaded the SSH service so the new settings apply to fresh sessions.")
        else:
            result.add_warning(
                "The SSH configuration validated successfully, but automatic service reload did not succeed. Reload ssh or sshd manually."
            )
            if reload_output:
                result.add_warning(reload_output)

    result.add_detail(
        "Explicitly set UseDNS no, GSSAPIAuthentication no, short SSH client keepalives, and PrintMotd no to avoid duplicate MOTD output."
    )
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Apply a few safe SSH responsiveness and MOTD-friendly defaults.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the SSH configuration changes without applying them.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = configure_ssh_speedups(dry_run=args.dry_run)
        print_result(result)
        return 0
    except Exception as exc:  # pragma: no cover - CLI safety net
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
