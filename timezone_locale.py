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
    read_text_file,
    restore_snapshot,
    run_checked,
    try_run,
    write_text_if_changed,
)

TIMEZONE = "Europe/Berlin"
DEFAULT_LOCALE = "de_DE.UTF-8"
DEFAULT_LANGUAGE = "de_DE:de"
DEFAULT_LC_TIME = DEFAULT_LOCALE
DEFAULT_KEYBOARD_MODEL = "pc105"
DEFAULT_KEYBOARD_LAYOUT = "de"
DEFAULT_KEYBOARD_VARIANT = ""
DEFAULT_KEYBOARD_OPTIONS = ""
DEFAULT_KEYBOARD_BACKSPACE = "guess"
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


def _require_non_empty(value: str, *, name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise RuntimeError(f"{name} cannot be empty.")
    return normalized


def _validated_timezone_target(timezone: str) -> Path:
    if any(character in timezone for character in ("\r", "\n", "\x00")):
        raise RuntimeError("timezone cannot contain newlines or NUL bytes.")

    timezone_path = Path(timezone)
    if timezone_path.is_absolute():
        raise RuntimeError("timezone must be a zoneinfo name, not an absolute path.")
    if any(part in (".", "..") for part in timezone_path.parts):
        raise RuntimeError("timezone cannot contain '.' or '..' path components.")

    try:
        zoneinfo_root = ZONEINFO_ROOT.resolve(strict=True)
        timezone_target = (ZONEINFO_ROOT / timezone_path).resolve(strict=True)
    except FileNotFoundError as exc:
        raise RuntimeError(f"Timezone data file not found: {ZONEINFO_ROOT / timezone_path}") from exc

    try:
        timezone_target.relative_to(zoneinfo_root)
    except ValueError as exc:
        raise RuntimeError(
            f"Timezone data file must stay below {ZONEINFO_ROOT}: {ZONEINFO_ROOT / timezone_path}"
        ) from exc

    if not timezone_target.is_file():
        raise RuntimeError(f"Timezone data path is not a file: {ZONEINFO_ROOT / timezone_path}")

    return ZONEINFO_ROOT / timezone_path


def _locale_gen_entry(locale: str) -> str:
    return f"{locale} UTF-8"


def _locale_gen_re(locale: str) -> re.Pattern[str]:
    return re.compile(rf"^\s*#?\s*{re.escape(locale)}\s+UTF-8\s*$")


def _keyboard_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _keyboard_content(
    *,
    model: str,
    layout: str,
    variant: str,
    options: str,
    backspace: str,
) -> str:
    return normalize_text(
        f'''# Managed by prep-my-server.
XKBMODEL="{_keyboard_value(model)}"
XKBLAYOUT="{_keyboard_value(layout)}"
XKBVARIANT="{_keyboard_value(variant)}"
XKBOPTIONS="{_keyboard_value(options)}"
BACKSPACE="{_keyboard_value(backspace)}"'''
    )


def _render_locale_gen(content: str, *, locale: str) -> str:
    locale_gen_entry = _locale_gen_entry(locale)
    locale_gen_re = _locale_gen_re(locale)
    lines = content.splitlines()
    replaced = False

    for index, line in enumerate(lines):
        if locale_gen_re.match(line):
            lines[index] = locale_gen_entry
            replaced = True
            break

    if not replaced:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(locale_gen_entry)

    return normalize_text("\n".join(lines))


def _read_assignments(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    content = read_text_file(path, missing_ok=True, description="locale defaults file")
    if content is None:
        return values

    for raw_line in content.splitlines():
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


def _locale_defaults_need_update(
    locale_defaults_path: Path,
    *,
    locale: str,
    language: str,
    lc_time: str,
) -> bool:
    current = _read_assignments(locale_defaults_path)
    return (
        current.get("LANG") != locale
        or current.get("LANGUAGE") != language
        or current.get("LC_TIME") != lc_time
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

    timezone_content = read_text_file(TIMEZONE_PATH, missing_ok=True, description="timezone file")
    if timezone_content is not None:
        return timezone_content.strip() or None
    return None


def _set_timezone(*, timezone: str, dry_run: bool, result: FeatureResult) -> bool:
    timezone_target = _validated_timezone_target(timezone)
    current_timezone = _current_timezone()
    timezone_needs_update = current_timezone != timezone
    if not timezone_needs_update:
        result.add_detail(f"Timezone is already set to {timezone}.")
        return False

    if is_systemd_available():
        timedatectl = find_command(["timedatectl"])
        command = [timedatectl, "set-timezone", timezone]
        if dry_run:
            result.add_detail(f"Would run: {format_command(command)}")
            return True

        run_checked(command)
        result.add_detail(f"Set the system timezone to {timezone}.")
        return True

    timezone_file_content = normalize_text(timezone)
    if dry_run:
        result.add_detail(f"Would write {TIMEZONE_PATH}.")
        result.add_detail(f"Would update /etc/localtime to point at {timezone_target}.")
        return True

    write_text_if_changed(TIMEZONE_PATH, timezone_file_content, mode=0o644)
    localtime_path = Path("/etc/localtime")
    temporary_localtime_path = localtime_path.with_name(".localtime.prep-my-server.tmp")
    if temporary_localtime_path.exists() or temporary_localtime_path.is_symlink():
        temporary_localtime_path.unlink()
    temporary_localtime_path.symlink_to(timezone_target)
    temporary_localtime_path.replace(localtime_path)
    result.add_detail(f"Set the system timezone to {timezone}.")
    return True


def configure_timezone_locale(
    *,
    dry_run: bool = False,
    locale_gen_path: Path = LOCALE_GEN_PATH,
    keyboard_path: Path = KEYBOARD_PATH,
    timezone: str = TIMEZONE,
    locale: str = DEFAULT_LOCALE,
    language: str = DEFAULT_LANGUAGE,
    lc_time: str = DEFAULT_LC_TIME,
    keyboard_model: str = DEFAULT_KEYBOARD_MODEL,
    keyboard_layout: str = DEFAULT_KEYBOARD_LAYOUT,
    keyboard_variant: str = DEFAULT_KEYBOARD_VARIANT,
    keyboard_options: str = DEFAULT_KEYBOARD_OPTIONS,
    keyboard_backspace: str = DEFAULT_KEYBOARD_BACKSPACE,
) -> FeatureResult:
    ensure_linux()
    ensure_root(dry_run=dry_run)

    timezone = _require_non_empty(timezone, name="timezone")
    locale = _require_non_empty(locale, name="locale")
    language = _require_non_empty(language, name="language")
    lc_time = _require_non_empty(lc_time, name="lc_time")
    keyboard_model = _require_non_empty(keyboard_model, name="keyboard_model")
    keyboard_layout = _require_non_empty(keyboard_layout, name="keyboard_layout")
    keyboard_backspace = _require_non_empty(keyboard_backspace, name="keyboard_backspace")
    locale_gen_entry = _locale_gen_entry(locale)
    keyboard_content = _keyboard_content(
        model=keyboard_model,
        layout=keyboard_layout,
        variant=keyboard_variant,
        options=keyboard_options,
        backspace=keyboard_backspace,
    )

    apt_get, dpkg_query = ensure_apt_system()
    missing_packages = get_missing_packages(SETUP_PACKAGES, dpkg_query_path=dpkg_query)

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

    locale_defaults_path = _locale_defaults_path()
    locale_gen_snapshot = capture_snapshot(locale_gen_path)
    locale_defaults_snapshot = capture_snapshot(locale_defaults_path)
    keyboard_snapshot = capture_snapshot(keyboard_path)
    desired_locale_gen = _render_locale_gen(locale_gen_snapshot.content or "", locale=locale)
    locale_gen_needs_update = desired_locale_gen != (locale_gen_snapshot.content or "")
    keyboard_needs_update = (
        not keyboard_snapshot.existed
        or keyboard_snapshot.content != keyboard_content
        or keyboard_snapshot.mode != 0o644
    )
    locale_defaults_needs_update = _locale_defaults_need_update(
        locale_defaults_path,
        locale=locale,
        language=language,
        lc_time=lc_time,
    )

    if dry_run:
        if locale_gen_needs_update:
            result.add_detail(f"Would update {locale_gen_path} to ensure {locale_gen_entry} is enabled.")
            result.changed = True
        else:
            result.add_detail(f"{locale_gen_path} already enables {locale_gen_entry}.")

        if locale_defaults_needs_update:
            try:
                update_locale = find_command(["update-locale"])
            except RuntimeError:
                update_locale = "update-locale"
            command = [
                update_locale,
                "--locale-file",
                str(locale_defaults_path),
                f"LANG={locale}",
                f"LANGUAGE={language}",
                f"LC_TIME={lc_time}",
            ]
            result.add_detail(f"Would run: {format_command(command)}")
            result.changed = True
        else:
            result.add_detail(f"Default locale already prefers {locale}.")

        if keyboard_needs_update:
            result.add_detail(f"Would write {keyboard_path} for keyboard layout {keyboard_layout}.")
            result.changed = True
        else:
            result.add_detail(f"{keyboard_path} already has the desired keyboard layout.")

        if _set_timezone(timezone=timezone, dry_run=True, result=result):
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
            result.add_detail(f"Updated {locale_gen_path} to enable {locale_gen_entry}.")
            result.changed = True
        else:
            result.add_detail(f"{locale_gen_path} already enables {locale_gen_entry}.")

        locale_gen = find_command(["locale-gen"])
        run_checked([locale_gen])
        result.add_detail(f"Generated locale data for {locale}.")

        if locale_defaults_needs_update:
            update_locale = find_command(["update-locale"])
            run_checked(
                [
                    update_locale,
                    "--locale-file",
                    str(locale_defaults_path),
                    f"LANG={locale}",
                    f"LANGUAGE={language}",
                    f"LC_TIME={lc_time}",
                ]
            )
            result.add_detail(
                f"Set the default locale to {locale} via {locale_defaults_path}."
            )
            result.changed = True
        else:
            result.add_detail(f"Default locale already prefers {locale}.")

        if keyboard_needs_update:
            write_text_if_changed(keyboard_path, keyboard_content, mode=0o644)
            result.add_detail(f"Wrote {keyboard_path} for keyboard layout {keyboard_layout}.")
            result.changed = True
        else:
            result.add_detail(f"{keyboard_path} already has the desired keyboard layout.")

        if _set_timezone(timezone=timezone, dry_run=False, result=result):
            result.changed = True

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
        description="Set timezone, locale, and console keyboard layout.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the locale and timezone changes without applying them.",
    )
    parser.add_argument(
        "--timezone",
        default=TIMEZONE,
        help=f"Timezone to set (default: {TIMEZONE}).",
    )
    parser.add_argument(
        "--locale",
        default=DEFAULT_LOCALE,
        help=f"Default locale to generate and set (default: {DEFAULT_LOCALE}).",
    )
    parser.add_argument(
        "--language",
        default=DEFAULT_LANGUAGE,
        help=f"LANGUAGE value to set (default: {DEFAULT_LANGUAGE}).",
    )
    parser.add_argument(
        "--lc-time",
        default=DEFAULT_LC_TIME,
        help=f"LC_TIME value to set (default: {DEFAULT_LC_TIME}).",
    )
    parser.add_argument(
        "--keyboard-model",
        default=DEFAULT_KEYBOARD_MODEL,
        help=f"XKBMODEL value to set (default: {DEFAULT_KEYBOARD_MODEL}).",
    )
    parser.add_argument(
        "--keyboard-layout",
        default=DEFAULT_KEYBOARD_LAYOUT,
        help=f"XKBLAYOUT value to set (default: {DEFAULT_KEYBOARD_LAYOUT}).",
    )
    parser.add_argument(
        "--keyboard-variant",
        default=DEFAULT_KEYBOARD_VARIANT,
        help="XKBVARIANT value to set.",
    )
    parser.add_argument(
        "--keyboard-options",
        default=DEFAULT_KEYBOARD_OPTIONS,
        help="XKBOPTIONS value to set.",
    )
    parser.add_argument(
        "--keyboard-backspace",
        default=DEFAULT_KEYBOARD_BACKSPACE,
        help=f"BACKSPACE value to set (default: {DEFAULT_KEYBOARD_BACKSPACE}).",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = configure_timezone_locale(
            dry_run=args.dry_run,
            timezone=args.timezone,
            locale=args.locale,
            language=args.language,
            lc_time=args.lc_time,
            keyboard_model=args.keyboard_model,
            keyboard_layout=args.keyboard_layout,
            keyboard_variant=args.keyboard_variant,
            keyboard_options=args.keyboard_options,
            keyboard_backspace=args.keyboard_backspace,
        )
        print_result(result)
        return 0
    except Exception as exc:  # pragma: no cover - CLI safety net
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
