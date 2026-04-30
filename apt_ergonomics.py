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
    normalize_text,
    package_is_installed,
    print_result,
    restore_snapshot,
    run_checked,
    write_text_if_changed,
)

APT_DEFAULTS_PATH = Path("/etc/apt/apt.conf.d/90prep-my-server-ergonomics")
NEEDRESTART_CONFIG_PATH = Path("/etc/needrestart/conf.d/90-prep-my-server.conf")
APT_DEFAULTS_CONTENT = normalize_text(
    """// Managed by prep-my-server.
// Prefer dpkg's default action for conffile prompts and keep the local file
// when no default is available. This keeps routine upgrades non-interactive.
Dpkg::Options {
    "--force-confdef";
    "--force-confold";
};
APT::Get::Show-Upgraded "true";
APT::Color "1";"""
)
NEEDRESTART_CONFIG_CONTENT = normalize_text(
    """# Managed by prep-my-server.
# Restart affected services automatically after library upgrades and skip
# interactive kernel/microcode reminder prompts.
$nrconf{restart} = 'a';
$nrconf{kernelhints} = 0;
$nrconf{ucodehints} = 0;
1;"""
)


def configure_apt_ergonomics(
    *,
    dry_run: bool = False,
    apt_defaults_path: Path = APT_DEFAULTS_PATH,
    needrestart_config_path: Path = NEEDRESTART_CONFIG_PATH,
) -> FeatureResult:
    ensure_linux()
    ensure_root(dry_run=dry_run)

    _apt_get, dpkg_query = ensure_apt_system()
    apt_config = find_command(["apt-config"])
    try:
        perl = find_command(["perl"])
    except RuntimeError:
        perl = None

    needrestart_installed = package_is_installed(
        "needrestart",
        dpkg_query_path=dpkg_query,
    )
    apt_snapshot = capture_snapshot(apt_defaults_path)
    needrestart_snapshot = capture_snapshot(needrestart_config_path)

    apt_needs_update = (
        not apt_snapshot.existed
        or apt_snapshot.content != APT_DEFAULTS_CONTENT
        or apt_snapshot.mode != 0o644
    )
    needrestart_needs_update = (
        not needrestart_snapshot.existed
        or needrestart_snapshot.content != NEEDRESTART_CONFIG_CONTENT
        or needrestart_snapshot.mode != 0o644
    )

    apt_validate_command = [apt_config, "dump"]
    needrestart_validate_command = (
        [perl, "-c", str(needrestart_config_path)] if perl else None
    )
    result = FeatureResult(name="apt-ergonomics")

    if dry_run:
        if apt_needs_update:
            result.add_detail(f"Would write {apt_defaults_path}.")
            result.changed = True
        else:
            result.add_detail(f"{apt_defaults_path} already has the desired APT defaults.")
        result.add_detail(
            f"Would validate APT configuration with: {format_command(apt_validate_command)}"
        )

        if needrestart_needs_update:
            result.add_detail(f"Would write {needrestart_config_path}.")
            result.changed = True
        else:
            result.add_detail(
                f"{needrestart_config_path} already has the desired needrestart defaults."
            )
        if needrestart_validate_command:
            result.add_detail(
                f"Would validate needrestart config syntax with: {format_command(needrestart_validate_command)}"
            )
        else:
            result.add_warning(
                "perl was not found, so needrestart config syntax validation would be skipped."
            )
        if not needrestart_installed:
            result.add_detail(
                "needrestart is not installed right now; the drop-in will apply if it is installed later."
            )
        return result

    try:
        if write_text_if_changed(apt_defaults_path, APT_DEFAULTS_CONTENT, mode=0o644):
            result.add_detail(f"Wrote {apt_defaults_path}.")
            result.changed = True
        else:
            result.add_detail(f"{apt_defaults_path} already has the desired APT defaults.")

        run_checked(apt_validate_command)
        result.add_detail("Validated the APT configuration with apt-config dump.")

        if write_text_if_changed(
            needrestart_config_path,
            NEEDRESTART_CONFIG_CONTENT,
            mode=0o644,
        ):
            result.add_detail(f"Wrote {needrestart_config_path}.")
            result.changed = True
        else:
            result.add_detail(
                f"{needrestart_config_path} already has the desired needrestart defaults."
            )

        if needrestart_validate_command:
            run_checked(needrestart_validate_command)
            result.add_detail("Validated the needrestart drop-in with perl -c.")
        else:
            result.add_warning(
                "perl was not found, so needrestart config syntax validation was skipped."
            )
    except Exception:
        restore_snapshot(apt_defaults_path, apt_snapshot)
        restore_snapshot(needrestart_config_path, needrestart_snapshot)
        raise

    if not needrestart_installed:
        result.add_detail(
            "needrestart is not installed right now; the drop-in will apply if it is installed later."
        )
    result.add_detail(
        "Routine APT upgrades now prefer non-interactive conffile handling and automatic needrestart service restarts."
    )
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Install APT and needrestart defaults that reduce routine upgrade prompts.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the APT ergonomics changes without applying them.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = configure_apt_ergonomics(dry_run=args.dry_run)
        print_result(result)
        return 0
    except Exception as exc:  # pragma: no cover - CLI safety net
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
