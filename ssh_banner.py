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
    read_text_file,
    restore_snapshot,
    run_checked,
    try_run,
    write_text_if_changed,
)

DEFAULT_BANNER_TEXT = normalize_text(
    """***************************************************************************
* Authorized access only.                                                *
* If this is not your server, this is your cue to leave.                  *
* Activity may be monitored, logged, and explained to future you.         *
* Unauthorized access is not a clever shortcut. Disconnect now.           *
***************************************************************************"""
)
BANNER_FILE_PATH = Path("/etc/issue.net")
SSHD_CONFIG_PATH = Path("/etc/ssh/sshd_config")
_BANNER_LINE_RE = re.compile(r"^\s*#?\s*Banner\b", re.IGNORECASE)
_INCLUDE_LINE_RE = re.compile(r"^\s*Include\b", re.IGNORECASE)
_MATCH_LINE_RE = re.compile(r"^\s*Match\b", re.IGNORECASE)


def resolve_banner_text(banner_text: str | None, banner_file: Path | None) -> str:
    if banner_file is not None:
        resolved_text = normalize_text(
            read_text_file(
                banner_file,
                description="SSH banner input file",
            )
            or ""
        )
    elif banner_text is not None:
        resolved_text = normalize_text(banner_text)
    else:
        resolved_text = DEFAULT_BANNER_TEXT

    if not resolved_text.strip():
        raise RuntimeError("SSH banner text cannot be empty.")

    return resolved_text


def render_sshd_config_with_banner(config_text: str, banner_path: Path) -> str:
    lines = config_text.splitlines()
    new_lines: list[str] = []
    banner_inserted = False
    in_match_block = False

    for line in lines:
        stripped = line.lstrip()
        is_active_include = bool(_INCLUDE_LINE_RE.match(line)) and not stripped.startswith("#")
        is_active_match = bool(_MATCH_LINE_RE.match(line)) and not stripped.startswith("#")

        if (is_active_include or is_active_match) and not banner_inserted:
            if new_lines and new_lines[-1].strip():
                new_lines.append("")
            new_lines.append("# Managed by prep-my-server")
            new_lines.append(f"Banner {banner_path}")
            banner_inserted = True

        if not in_match_block and not is_active_match and _BANNER_LINE_RE.match(line):
            if not banner_inserted:
                new_lines.append(f"Banner {banner_path}")
                banner_inserted = True
            continue

        new_lines.append(line)
        if is_active_match:
            in_match_block = True

    if not banner_inserted:
        if new_lines and new_lines[-1].strip():
            new_lines.append("")
        new_lines.append("# Managed by prep-my-server")
        new_lines.append(f"Banner {banner_path}")

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

    service_command_candidates = ["service", "/usr/sbin/service", "/usr/bin/service"]
    try:
        service_command = find_command(service_command_candidates)
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
        attempted.append(
            f"{format_command(command)} -> {output if output else 'no output'}"
        )
        if success:
            return True, ""

    return False, "\n".join(attempted)


def configure_ssh_banner(
    *,
    banner_text: str,
    dry_run: bool = False,
    banner_path: Path = BANNER_FILE_PATH,
    sshd_config_path: Path = SSHD_CONFIG_PATH,
) -> FeatureResult:
    ensure_linux()
    ensure_root(dry_run=dry_run)

    if not sshd_config_path.exists():
        raise RuntimeError(f"{sshd_config_path} does not exist.")

    sshd_binary = find_command(["sshd", "/usr/sbin/sshd", "/usr/local/sbin/sshd"])
    result = FeatureResult(name="ssh-login-banner")

    config_snapshot = capture_snapshot(sshd_config_path)
    banner_snapshot = capture_snapshot(banner_path)

    desired_banner_text = normalize_text(banner_text)
    desired_config_text = render_sshd_config_with_banner(
        config_snapshot.content or "",
        banner_path,
    )

    banner_needs_update = (
        not banner_snapshot.existed
        or banner_snapshot.content != desired_banner_text
        or banner_snapshot.mode != 0o644
    )
    config_needs_update = desired_config_text != (config_snapshot.content or "")
    validation_command = [sshd_binary, "-t", "-f", str(sshd_config_path)]
    reload_needed = banner_needs_update or config_needs_update

    if dry_run:
        if banner_needs_update:
            result.add_detail(f"Would write banner text to {banner_path}.")
            result.changed = True
        else:
            result.add_detail(f"{banner_path} already has the desired banner text.")

        if config_needs_update:
            result.add_detail(f"Would update {sshd_config_path} to set Banner {banner_path}.")
            result.changed = True
        else:
            result.add_detail(f"{sshd_config_path} already points Banner at {banner_path}.")

        result.add_detail(f"Would validate with: {format_command(validation_command)}")
        if reload_needed:
            result.add_detail("Would attempt to reload the SSH service (ssh or sshd).")
        return result

    if banner_needs_update:
        write_text_if_changed(banner_path, desired_banner_text, mode=0o644)
        result.changed = True
        result.add_detail(f"Wrote {banner_path}.")
    else:
        result.add_detail(f"{banner_path} already has the desired banner text.")

    if config_needs_update:
        target_mode = config_snapshot.mode if config_snapshot.mode is not None else 0o600
        write_text_if_changed(sshd_config_path, desired_config_text, mode=target_mode)
        result.changed = True
        result.add_detail(f"Updated {sshd_config_path}.")
    else:
        result.add_detail(f"{sshd_config_path} already points Banner at {banner_path}.")

    try:
        run_checked(validation_command)
    except Exception:
        restore_snapshot(sshd_config_path, config_snapshot)
        restore_snapshot(banner_path, banner_snapshot)
        raise

    if reload_needed:
        reloaded, reload_output = _reload_ssh_service()
        if reloaded:
            result.add_detail("Reloaded the SSH service so the banner is live for new logins.")
        else:
            result.add_warning(
                "The SSH configuration validated successfully, but automatic service reload did not succeed. "
                "Reload ssh or sshd manually."
            )
            if reload_output:
                result.add_warning(reload_output)

    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Configure an SSH pre-login banner.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the banner changes without writing them.",
    )
    banner_group = parser.add_mutually_exclusive_group()
    banner_group.add_argument(
        "--banner-text",
        help="Custom SSH banner text.",
    )
    banner_group.add_argument(
        "--banner-file",
        type=Path,
        help="Read banner text from a file.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        banner_text = resolve_banner_text(args.banner_text, args.banner_file)
        result = configure_ssh_banner(banner_text=banner_text, dry_run=args.dry_run)
        print_result(result)
        return 0
    except Exception as exc:  # pragma: no cover - CLI safety net
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
