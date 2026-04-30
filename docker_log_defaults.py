#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from common import (
    FeatureResult,
    capture_snapshot,
    ensure_directory_path,
    ensure_linux,
    ensure_root,
    find_command,
    normalize_text,
    print_result,
    read_text_file,
    restore_snapshot,
    write_text_if_changed,
)

DOCKER_CONFIG_DIR = Path("/etc/docker")
DOCKER_DAEMON_CONFIG_PATH = DOCKER_CONFIG_DIR / "daemon.json"
DEFAULT_LOG_DRIVER = "json-file"
DEFAULT_LOG_OPTIONS = {
    "max-size": "10m",
    "max-file": "3",
}


def _docker_is_present() -> bool:
    try:
        find_command(["dockerd"])
        return True
    except RuntimeError:
        return DOCKER_CONFIG_DIR.exists()


def _load_daemon_config(config_path: Path) -> dict[str, object]:
    content = read_text_file(config_path, missing_ok=True, description="Docker daemon config")
    if content is None or not content.strip():
        return {}

    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Could not parse Docker daemon config at {config_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"Docker daemon config at {config_path} must contain a JSON object.")
    return data


def _render_daemon_config(config: dict[str, object]) -> str:
    return normalize_text(json.dumps(config, indent=2, sort_keys=True))


def _with_log_defaults(config: dict[str, object], result: FeatureResult) -> tuple[dict[str, object], bool]:
    updated = dict(config)
    changed = False
    log_driver = updated.get("log-driver")

    if log_driver not in (None, DEFAULT_LOG_DRIVER):
        result.add_warning(
            f"Docker log-driver is already set to {log_driver!r}; leaving existing logging config unchanged."
        )
        return updated, False

    if log_driver is None:
        updated["log-driver"] = DEFAULT_LOG_DRIVER
        changed = True

    raw_log_options = updated.get("log-opts", {})
    if not isinstance(raw_log_options, dict):
        raise RuntimeError("Docker daemon config 'log-opts' must be a JSON object when present.")

    log_options = dict(raw_log_options)
    for key, value in DEFAULT_LOG_OPTIONS.items():
        if key not in log_options:
            log_options[key] = value
            changed = True

    updated["log-opts"] = log_options
    return updated, changed


def configure_docker_log_defaults(
    *,
    dry_run: bool = False,
    config_path: Path = DOCKER_DAEMON_CONFIG_PATH,
) -> FeatureResult:
    ensure_linux()
    ensure_root(dry_run=dry_run)

    result = FeatureResult(name="docker-log-defaults")
    if not _docker_is_present():
        result.add_detail("Docker was not detected; no daemon log defaults are needed.")
        return result

    ensure_directory_path(config_path.parent, description="Docker config directory")
    snapshot = capture_snapshot(config_path)
    current_config = _load_daemon_config(config_path)
    desired_config, config_changed = _with_log_defaults(current_config, result)
    desired_content = _render_daemon_config(desired_config)
    file_needs_update = config_changed or (snapshot.content or "") != desired_content

    if dry_run:
        if file_needs_update:
            result.add_detail(f"Would write Docker log rotation defaults to {config_path}.")
            result.add_detail(
                "Would set missing defaults: log-driver=json-file, log-opts.max-size=10m, log-opts.max-file=3."
            )
            result.add_warning("Docker must be restarted later for daemon.json logging changes to apply.")
            result.changed = True
        else:
            result.add_detail(f"{config_path} already has the desired Docker log defaults.")
        return result

    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        if write_text_if_changed(config_path, desired_content, mode=0o644):
            result.add_detail(f"Wrote Docker log rotation defaults to {config_path}.")
            result.add_warning("Docker must be restarted later for daemon.json logging changes to apply.")
            result.changed = True
        else:
            result.add_detail(f"{config_path} already has the desired Docker log defaults.")
    except Exception:
        restore_snapshot(config_path, snapshot)
        raise

    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Add conservative Docker daemon log rotation defaults.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview Docker daemon log default changes without applying them.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = configure_docker_log_defaults(dry_run=args.dry_run)
        print_result(result)
        return 0
    except Exception as exc:  # pragma: no cover - CLI safety net
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
