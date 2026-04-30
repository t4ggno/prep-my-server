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

MOTD_RENDERER_PATH = Path("/usr/local/libexec/prep-my-server-motd-status")
MOTD_FRAGMENT_PATH = Path("/etc/update-motd.d/60-prep-my-server-status")
CACHE_MAX_AGE_SECONDS = 300
MOTD_RENDERER_CONTENT = normalize_text(
    """#!/bin/sh
set -eu

command_exists() {
    command -v "$1" >/dev/null 2>&1
}

trim_spaces() {
    awk '{$1=$1; print}'
}

host_name="$(hostname 2>/dev/null || echo unknown)"
ip_addresses="$(hostname -I 2>/dev/null | trim_spaces || true)"
if [ -z "$ip_addresses" ] && command_exists ip; then
    ip_addresses="$(ip -brief address show scope global up 2>/dev/null | awk '{print $3}' | paste -sd ' ' - || true)"
fi
[ -n "$ip_addresses" ] || ip_addresses="n/a"

if command_exists uptime; then
    uptime_human="$(uptime -p 2>/dev/null || uptime 2>/dev/null || echo n/a)"
    load_average="$(uptime 2>/dev/null | awk -F'load average: ' 'NF > 1 {print $2}' || echo n/a)"
else
    uptime_human="n/a"
    load_average="n/a"
fi

if command_exists free; then
    memory_usage="$(free -h 2>/dev/null | awk '/^Mem:/ {print $3 " / " $2}' || echo n/a)"
else
    memory_usage="n/a"
fi

if command_exists df; then
    disk_usage="$(df -h / 2>/dev/null | awk 'NR == 2 {print $3 " used / " $2 " (" $5 ")"}' || echo n/a)"
else
    disk_usage="n/a"
fi

updates_pending="n/a"
if command_exists apt-get; then
    updates_pending="$(apt-get -s upgrade 2>/dev/null | awk '/^Inst / {count++} END {print count + 0}')"
fi

printf '\n'
printf 'Server status\n'
printf '-------------\n'
printf 'Host: %s\n' "$host_name"
printf 'IPs: %s\n' "$ip_addresses"
printf 'Uptime: %s\n' "$uptime_human"
printf 'Load: %s\n' "$load_average"
printf 'Memory: %s\n' "$memory_usage"
printf 'Disk (/): %s\n' "$disk_usage"
printf 'Pending APT upgrades: %s\n' "$updates_pending"
"""
)
MOTD_FRAGMENT_CONTENT = normalize_text(
    f"""#!/bin/sh
set -eu

cache_dir=/run/prep-my-server
cache_file="$cache_dir/motd-status.cache"
max_age={CACHE_MAX_AGE_SECONDS}
renderer={MOTD_RENDERER_PATH}

mkdir -p "$cache_dir"

cache_mtime=0
if [ -f "$cache_file" ]; then
    cache_mtime="$(stat -c %Y "$cache_file" 2>/dev/null || echo 0)"
fi

now="$(date +%s)"
age=$((now - cache_mtime))

if [ ! -s "$cache_file" ] || [ "$age" -ge "$max_age" ]; then
    tmp_file="$(mktemp "$cache_dir/motd-status.XXXXXX")"
    if "$renderer" >"$tmp_file" 2>/dev/null; then
        mv "$tmp_file" "$cache_file"
    else
        rm -f "$tmp_file"
    fi
fi

if [ -s "$cache_file" ]; then
    cat "$cache_file"
else
    "$renderer" || true
fi
"""
)


def configure_motd_status(
    *,
    dry_run: bool = False,
    renderer_path: Path = MOTD_RENDERER_PATH,
    fragment_path: Path = MOTD_FRAGMENT_PATH,
) -> FeatureResult:
    ensure_linux()
    ensure_root(dry_run=dry_run)

    sh_path = find_command(["sh"])
    renderer_snapshot = capture_snapshot(renderer_path)
    fragment_snapshot = capture_snapshot(fragment_path)
    renderer_needs_update = (
        not renderer_snapshot.existed
        or renderer_snapshot.content != MOTD_RENDERER_CONTENT
        or renderer_snapshot.mode != 0o755
    )
    fragment_needs_update = (
        not fragment_snapshot.existed
        or fragment_snapshot.content != MOTD_FRAGMENT_CONTENT
        or fragment_snapshot.mode != 0o755
    )

    renderer_syntax_command = [sh_path, "-n", str(renderer_path)]
    fragment_syntax_command = [sh_path, "-n", str(fragment_path)]

    result = FeatureResult(name="motd-status")
    if dry_run:
        if renderer_needs_update:
            result.add_detail(f"Would write {renderer_path}.")
            result.changed = True
        else:
            result.add_detail(f"{renderer_path} already has the desired MOTD renderer.")

        if fragment_needs_update:
            result.add_detail(f"Would write {fragment_path}.")
            result.changed = True
        else:
            result.add_detail(f"{fragment_path} already has the desired update-motd fragment.")

        result.add_detail(f"Would validate with: {format_command(renderer_syntax_command)}")
        result.add_detail(f"Would validate with: {format_command(fragment_syntax_command)}")
        return result

    try:
        if renderer_needs_update:
            write_text_if_changed(renderer_path, MOTD_RENDERER_CONTENT, mode=0o755)
            result.add_detail(f"Wrote {renderer_path}.")
            result.changed = True
        else:
            result.add_detail(f"{renderer_path} already has the desired MOTD renderer.")

        if fragment_needs_update:
            write_text_if_changed(fragment_path, MOTD_FRAGMENT_CONTENT, mode=0o755)
            result.add_detail(f"Wrote {fragment_path}.")
            result.changed = True
        else:
            result.add_detail(f"{fragment_path} already has the desired update-motd fragment.")

        run_checked(renderer_syntax_command)
        run_checked(fragment_syntax_command)
        run_checked([str(fragment_path)])
        result.add_detail("Validated the MOTD scripts and rendered the status output once.")
    except Exception:
        restore_snapshot(renderer_path, renderer_snapshot)
        restore_snapshot(fragment_path, fragment_snapshot)
        raise

    result.add_detail(
        "The update-motd fragment caches its output for 5 minutes so SSH logins stay snappy."
    )
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Install a small cached MOTD status block using update-motd.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the MOTD file changes without applying them.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = configure_motd_status(dry_run=args.dry_run)
        print_result(result)
        return 0
    except Exception as exc:  # pragma: no cover - CLI safety net
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
