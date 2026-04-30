#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from common import (
    FeatureResult,
    ensure_linux,
    ensure_root,
    find_command,
    format_command,
    normalize_text,
    print_result,
    run_checked,
    write_text_if_changed,
)

PROFILE_SNIPPET_PATH = Path("/etc/profile.d/90-prep-my-server.sh")
PROFILE_SNIPPET_CONTENT = normalize_text(
    """# Managed by prep-my-server.
case "$-" in
    *i*) ;;
    *) return 0 2>/dev/null || exit 0 ;;
esac

export EDITOR=vim
export VISUAL=vim
export PAGER=less
export LESS=-FRX
export HISTSIZE=50000
export HISTFILESIZE=100000
export HISTCONTROL=ignoredups:erasedups
export HISTTIMEFORMAT='%F %T '

if [ -n "${BASH_VERSION:-}" ]; then
    shopt -s histappend cmdhist checkwinsize

    alias ..='cd ..'
    alias l='ls -CF --color=auto'
    alias la='ls -A --color=auto'
    alias ll='ls -alF --color=auto'

    if [ -r /usr/share/bash-completion/bash_completion ]; then
        . /usr/share/bash-completion/bash_completion
    fi
fi
"""
)


def configure_shell_convenience(
    *,
    dry_run: bool = False,
    profile_snippet_path: Path = PROFILE_SNIPPET_PATH,
) -> FeatureResult:
    ensure_linux()
    ensure_root(dry_run=dry_run)

    sh_path = find_command(["sh"])
    bash_path = find_command(["bash"])
    syntax_commands = [
        [sh_path, "-n", str(profile_snippet_path)],
        [bash_path, "-n", str(profile_snippet_path)],
    ]
    snippet_needs_update = (
        not profile_snippet_path.exists()
        or profile_snippet_path.read_text(encoding="utf-8") != PROFILE_SNIPPET_CONTENT
    )

    result = FeatureResult(name="shell-convenience")
    if dry_run:
        if snippet_needs_update:
            result.add_detail(f"Would write {profile_snippet_path}.")
            result.changed = True
        else:
            result.add_detail(f"{profile_snippet_path} already has the desired shell defaults.")
        for command in syntax_commands:
            result.add_detail(f"Would validate with: {format_command(command)}")
        return result

    if write_text_if_changed(profile_snippet_path, PROFILE_SNIPPET_CONTENT, mode=0o644):
        result.add_detail(f"Wrote {profile_snippet_path}.")
        result.changed = True
    else:
        result.add_detail(f"{profile_snippet_path} already has the desired shell defaults.")

    for command in syntax_commands:
        run_checked(command)
    result.add_detail("Validated the profile snippet with both sh -n and bash -n.")
    result.add_detail(
        "The convenience settings live in /etc/profile.d, which Bash login shells load via /etc/profile."
    )
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Install a small /etc/profile.d shell convenience snippet.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the profile snippet changes without applying them.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = configure_shell_convenience(dry_run=args.dry_run)
        print_result(result)
        return 0
    except Exception as exc:  # pragma: no cover - CLI safety net
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
