#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys

from common import (
    FeatureResult,
    capture_snapshot,
    ensure_apt_system,
    ensure_linux,
    ensure_root,
    find_command,
    format_command,
    get_missing_packages,
    is_systemd_available,
    normalize_text,
    print_result,
    restore_snapshot,
    run_checked,
    try_run,
    write_text_if_changed,
)

TIMEZONE = "Europe/Berlin"
DEFAULT_LOCALE = "de_DE.UTF-8"
LOCALE_GEN_ENTRY = f"{DEFAULT_LOCALE} UTF-8"
LOCALE_GEN_PATH = Path("/etc/locale.gen")
LOCALE_DEFAULTS_CANDIDATES = (Path("/etc/locale.conf"), Path("/etc/default/locale"))
KEYBOARD_PATH = Path("/etc/default/keyboard")
TIMEZONE_PATH = Path("/etc/timezone")
ZONEINFO_ROOT = Path("/usr/share/zoneinfo")
SETUP_PACKAGES: tuple[str, ...] = (
    "console-setup",
    "keyboard-configuration",
    "locales",
)
KEYBOARD_CONTENT = normalize_text(
    '''# Managed by prep-my-server.
XKBMODEL="pc105"
XKBLAYOUT="de"
XKBVARIANT=""
XKBOPTIONS=""
BACKSPACE="guess"'''
)
_LOCALE_GEN_RE = re.compile(r"^\s*#?\s*de_DE\.UTF-8\s+UTF-8\s*$")


def _render_locale_gen(content: str) -> str:
    lines = content.splitlines()
    replaced = False

    for index, line in enumerate(lines):
        if _LOCALE_GEN_RE.match(line):
            lines[index] = LOCALE_GEN_ENTRY
            replaced = True
            break

    if not replaced:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(LOCALE_GEN_ENTRY)

    return normalize_text("\n".join(lines))


def _read_assignments(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value.strip().strip('"')
    return values


def _locale_defaults_path() -> Path:
    for candidate in LOCALE_DEFAULTS_CANDIDATES:
        if candidate.exists():
            return candidate
    return LOCALE_DEFAULTS_CANDIDATES[0]


def _locale_defaults_need_update(locale_defaults_path: Path) -> bool:
    current = _read_assignments(locale_defaults_path)
    return (
        current.get("LANG") != DEFAULT_LOCALE
        or current.get("LANGUAGE") != "de_DE:de"
        or current.get("LC_TIME") != DEFAULT_LOCALE
    )


def _current_timezone() -> str | None:
    if is_systemd_available():
        try:
            timedatectl = find_command(["timedatectl"])
        except RuntimeError:
            timedatectl = None
        if timedatectl:
            success, output = try_run(
                [timedatectl, "show", "--property=Timezone", "--value"]
            )
            if success and output.strip():
                return output.strip()

    if TIMEZONE_PATH.exists():
        return TIMEZONE_PATH.read_text(encoding="utf-8").strip() or None
    return None


def _set_timezone(*, dry_run: bool, result: FeatureResult) -> bool:
    current_timezone = _current_timezone()
    timezone_needs_update = current_timezone != TIMEZONE
    if not timezone_needs_update:
        result.add_detail(f"Timezone is already set to {TIMEZONE}.")
        return False

    if is_systemd_available():
        timedatectl = find_command(["timedatectl"])
        command = [timedatectl, "set-timezone", TIMEZONE]
        if dry_run:
            result.add_detail(f"Would run: {format_command(command)}")
            return True

        run_checked(command)
        result.add_detail(f"Set the system timezone to {TIMEZONE}.")
        return True

    timezone_file_content = normalize_text(TIMEZONE)
    timezone_target = ZONEINFO_ROOT / TIMEZONE
    if not timezone_target.exists():
        raise RuntimeError(f"Timezone data file not found: {timezone_target}")

    if dry_run:
        result.add_detail(f"Would write {TIMEZONE_PATH}.")
        result.add_detail(f"Would update /etc/localtime to point at {timezone_target}.")
        return True

    write_text_if_changed(TIMEZONE_PATH, timezone_file_content, mode=0o644)
    localtime_path = Path("/etc/localtime")
    if localtime_path.exists() or localtime_path.is_symlink():
        localtime_path.unlink()
    localtime_path.symlink_to(timezone_target)
    result.add_detail(f"Set the system timezone to {TIMEZONE}.")
    return True


def configure_timezone_locale(
    *,
    dry_run: bool = False,
    locale_gen_path: Path = LOCALE_GEN_PATH,
    keyboard_path: Path = KEYBOARD_PATH,
) -> FeatureResult:
    ensure_linux()
    ensure_root(dry_run=dry_run)

    apt_get, dpkg_query = ensure_apt_system()
    missing_packages = get_missing_packages(SETUP_PACKAGES, dpkg_query_path=dpkg_query)

    locale_defaults_path = _locale_defaults_path()
    locale_gen_snapshot = capture_snapshot(locale_gen_path)
    locale_defaults_snapshot = capture_snapshot(locale_defaults_path)
    keyboard_snapshot = capture_snapshot(keyboard_path)
    desired_locale_gen = _render_locale_gen(locale_gen_snapshot.content or "")
    locale_gen_needs_update = desired_locale_gen != (locale_gen_snapshot.content or "")
    keyboard_needs_update = (
        not keyboard_snapshot.existed
        or keyboard_snapshot.content != KEYBOARD_CONTENT
        or keyboard_snapshot.mode != 0o644
    )
    locale_defaults_needs_update = _locale_defaults_need_update(locale_defaults_path)

    result = FeatureResult(name="timezone-locale")

    if missing_packages:
        update_command = [apt_get, "update"]
        install_command = [
            apt_get,
            "install",
            "-y",
            "--no-install-recommends",
            *missing_packages,
        ]
        if dry_run:
            result.add_detail(
                "Would install locale/keyboard support packages: "
                + ", ".join(missing_packages)
            )
            result.add_detail(f"Would run: {format_command(update_command)}")
            result.add_detail(f"Would run: {format_command(install_command)}")
            result.changed = True
        else:
            run_checked(update_command)
            run_checked(install_command, env={"DEBIAN_FRONTEND": "noninteractive"})
            result.add_detail(
                "Installed locale/keyboard support packages: "
                + ", ".join(missing_packages)
            )
            result.changed = True

    if dry_run:
        if locale_gen_needs_update:
            result.add_detail(f"Would update {locale_gen_path} to ensure {LOCALE_GEN_ENTRY} is enabled.")
            result.changed = True
        else:
            result.add_detail(f"{locale_gen_path} already enables {LOCALE_GEN_ENTRY}.")

        if locale_defaults_needs_update:
            try:
                update_locale = find_command(["update-locale"])
            except RuntimeError:
                update_locale = "update-locale"
            command = [
                update_locale,
                "--locale-file",
                str(locale_defaults_path),
                f"LANG={DEFAULT_LOCALE}",
                "LANGUAGE=de_DE:de",
                f"LC_TIME={DEFAULT_LOCALE}",
            ]
            result.add_detail(f"Would run: {format_command(command)}")
            result.changed = True
        else:
            result.add_detail(f"Default locale already prefers {DEFAULT_LOCALE}.")

        if keyboard_needs_update:
            result.add_detail(f"Would write {keyboard_path} for a German QWERTZ console layout.")
            result.changed = True
        else:
            result.add_detail(f"{keyboard_path} already has the desired keyboard layout.")

        if _set_timezone(dry_run=True, result=result):
            result.changed = True

        try:
            setupcon = find_command(["setupcon"])
            result.add_detail(
                f"Would run: {format_command([setupcon, '--keyboard-only'])}"
            )
        except RuntimeError:
            result.add_warning("setupcon was not found; the keyboard layout would apply after the next reboot.")
        return result

    try:
        if locale_gen_needs_update:
            write_text_if_changed(locale_gen_path, desired_locale_gen, mode=0o644)
            result.add_detail(f"Updated {locale_gen_path} to enable {LOCALE_GEN_ENTRY}.")
            result.changed = True
        else:
            result.add_detail(f"{locale_gen_path} already enables {LOCALE_GEN_ENTRY}.")

        locale_gen = find_command(["locale-gen"])
        run_checked([locale_gen])
        result.add_detail(f"Generated locale data for {DEFAULT_LOCALE}.")

        if locale_defaults_needs_update:
            update_locale = find_command(["update-locale"])
            run_checked(
                [
                    update_locale,
                    "--locale-file",
                    str(locale_defaults_path),
                    f"LANG={DEFAULT_LOCALE}",
                    "LANGUAGE=de_DE:de",
                    f"LC_TIME={DEFAULT_LOCALE}",
                ]
            )
            result.add_detail(
                f"Set the default locale to {DEFAULT_LOCALE} via {locale_defaults_path}."
            )
            result.changed = True
        else:
            result.add_detail(f"Default locale already prefers {DEFAULT_LOCALE}.")

        if _set_timezone(dry_run=False, result=result):
            result.changed = True

        if keyboard_needs_update:
            write_text_if_changed(keyboard_path, KEYBOARD_CONTENT, mode=0o644)
            result.add_detail(f"Wrote {keyboard_path} for a German QWERTZ console layout.")
            result.changed = True
        else:
            result.add_detail(f"{keyboard_path} already has the desired keyboard layout.")

        try:
            setupcon = find_command(["setupcon"])
            run_checked([setupcon, "--keyboard-only"])
            result.add_detail("Applied the keyboard layout immediately with setupcon --keyboard-only.")
        except Exception as exc:
            result.add_warning(
                "Updated the keyboard configuration, but immediate setupcon application failed. "
                "The layout should still apply on the next reboot. "
                f"Details: {exc}"
            )
    except Exception:
        restore_snapshot(locale_gen_path, locale_gen_snapshot)
        restore_snapshot(locale_defaults_path, locale_defaults_snapshot)
        restore_snapshot(keyboard_path, keyboard_snapshot)
        raise

    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Set Europe/Berlin timezone, German locale, and German QWERTZ keyboard layout.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the locale and timezone changes without applying them.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = configure_timezone_locale(dry_run=args.dry_run)
        print_result(result)
        return 0
    except Exception as exc:  # pragma: no cover - CLI safety net
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
