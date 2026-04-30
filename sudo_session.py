#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from common import (
    FeatureResult,
    capture_snapshot,
    ensure_linux,
    ensure_root,
    find_command,
    format_command,
    normalize_text,
    print_result,
    restore_snapshot,
    run_checked,
    write_text_if_changed,
)

SUDOERS_DROPIN_PATH = Path("/etc/sudoers.d/90-prep-my-server-session-auth")
SUDOERS_DROPIN_CONTENT = normalize_text(
    """# Managed by prep-my-server.
Defaults timestamp_timeout=-1
Defaults timestamp_type=tty"""
)


def configure_sudo_session(
    *,
    dry_run: bool = False,
    sudoers_dropin_path: Path = SUDOERS_DROPIN_PATH,
) -> FeatureResult:
    ensure_linux()
    ensure_root(dry_run=dry_run)

    visudo = find_command(["visudo", "/usr/sbin/visudo"])
    result = FeatureResult(name="sudo-session-cache")

    snapshot = capture_snapshot(sudoers_dropin_path)
    target_mode = 0o440
    file_needs_update = (
        not snapshot.existed
        or snapshot.content != SUDOERS_DROPIN_CONTENT
        or snapshot.mode != target_mode
    )

    validation_command = [visudo, "-cf", "/etc/sudoers"]
    if dry_run:
        if file_needs_update:
            result.add_detail(f"Would write {sudoers_dropin_path}.")
            result.changed = True
        else:
            result.add_detail(f"{sudoers_dropin_path} already has the desired settings.")
        result.add_detail(f"Would validate with: {format_command(validation_command)}")
        result.add_detail(
            "This uses timestamp_type=tty so the sudo cache stays tied to the active terminal session."
        )
        return result

    write_text_if_changed(sudoers_dropin_path, SUDOERS_DROPIN_CONTENT, mode=target_mode)
    try:
        run_checked(validation_command)
    except Exception:
        restore_snapshot(sudoers_dropin_path, snapshot)
        raise

    result.changed = file_needs_update
    if file_needs_update:
        result.add_detail(f"Wrote and validated {sudoers_dropin_path}.")
    else:
        result.add_detail(f"Validated the existing {sudoers_dropin_path} configuration.")
    result.add_detail(
        "Configured sudo for one authentication per terminal session with no time-based expiry."
    )
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Configure sudo to keep authentication for the life of the terminal session.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the sudoers change without writing it.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = configure_sudo_session(dry_run=args.dry_run)
        print_result(result)
        return 0
    except Exception as exc:  # pragma: no cover - CLI safety net
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
