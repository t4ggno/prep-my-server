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
export GIT_PAGER=less
export LESS=-FRX
export SYSTEMD_PAGER=cat
export SYSTEMD_COLORS=1
export HISTSIZE=50000
export HISTFILESIZE=100000
export HISTCONTROL=ignoredups:erasedups
export HISTTIMEFORMAT='%F %T '

if [ -n "${BASH_VERSION:-}" ]; then
    shopt -s histappend cmdhist checkwinsize

    alias ..='cd ..'
    alias grep='grep --color=auto'
    alias l='ls -CF --color=auto'
    alias la='ls -A --color=auto'
    alias ll='ls -alF --color=auto'
    alias df='df -h'
    alias du='du -h'
    alias free='free -h'
    alias ports='ss -tulpn'
    alias please='sudo'

    bind 'set completion-ignore-case on' 2>/dev/null || true
    bind 'set show-all-if-ambiguous on' 2>/dev/null || true
    bind 'set colored-stats on' 2>/dev/null || true

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
    syntax_commands = [[sh_path, "-n", str(profile_snippet_path)]]
    try:
        bash_path = find_command(["bash"])
    except RuntimeError:
        bash_path = None
    if bash_path:
        syntax_commands.append([bash_path, "-n", str(profile_snippet_path)])

    snippet_snapshot = capture_snapshot(profile_snippet_path)
    snippet_needs_update = (
        not snippet_snapshot.existed
        or snippet_snapshot.content != PROFILE_SNIPPET_CONTENT
        or snippet_snapshot.mode != 0o644
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
        if bash_path is None:
            result.add_warning(
                "bash was not found, so bash-specific syntax validation would be skipped. The profile snippet still remains sh-compatible."
            )
        return result

    try:
        if write_text_if_changed(profile_snippet_path, PROFILE_SNIPPET_CONTENT, mode=0o644):
            result.add_detail(f"Wrote {profile_snippet_path}.")
            result.changed = True
        else:
            result.add_detail(f"{profile_snippet_path} already has the desired shell defaults.")

        for command in syntax_commands:
            run_checked(command)
    except Exception:
        restore_snapshot(profile_snippet_path, snippet_snapshot)
        raise

    if bash_path:
        result.add_detail("Validated the profile snippet with both sh -n and bash -n.")
    else:
        result.add_detail("Validated the profile snippet with sh -n.")
    result.add_detail(
        "The convenience settings live in /etc/profile.d, which Bash login shells load via /etc/profile."
    )
    if bash_path is None:
        result.add_warning(
            "bash was not found, so only sh -n validation was run. The snippet still keeps bash-specific behavior behind a BASH_VERSION guard."
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
