#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence

from common import normalize_text, read_text_file, write_text_if_changed

CONFIG_PATH = Path("/etc/prep-my-server/config.json")
CONFIG_VERSION = 1
SETTING_DEFAULTS: dict[str, Any] = {
    "timezone-locale.timezone": "Europe/Berlin",
    "timezone-locale.locale": "de_DE.UTF-8",
    "timezone-locale.language": "de_DE:de",
    "timezone-locale.lc-time": "de_DE.UTF-8",
    "timezone-locale.keyboard-model": "pc105",
    "timezone-locale.keyboard-layout": "de",
    "timezone-locale.keyboard-variant": "",
    "timezone-locale.keyboard-options": "",
    "timezone-locale.keyboard-backspace": "guess",
    "docker-install.user": None,
    "docker-install.auto-sudo-user": True,
    "ssh-login-banner.banner-text": None,
    "ssh-login-banner.banner-file": None,
    "automatic-reboot.on-calendar": "*-*-* 03:30:00",
    "automatic-reboot.randomized-delay-sec": "30m",
}
BOOLEAN_SETTING_KEYS = {
    "docker-install.auto-sudo-user",
}
OPTIONAL_STRING_SETTING_KEYS = {
    "docker-install.user",
    "ssh-login-banner.banner-text",
    "ssh-login-banner.banner-file",
}
_NULL_VALUES = {"", "default", "none", "null", "unset"}
_TRUE_VALUES = {"1", "true", "yes", "on", "enable", "enabled"}
_FALSE_VALUES = {"0", "false", "no", "off", "disable", "disabled"}


def empty_config() -> dict[str, Any]:
    return {"version": CONFIG_VERSION, "tasks": {}, "settings": {}}


def _coerce_bool(value: Any, *, key: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _TRUE_VALUES:
            return True
        if normalized in _FALSE_VALUES:
            return False
    raise RuntimeError(
        f"{key} expects a boolean value. Use one of: true, false, yes, no, on, off, 1, 0."
    )


def _normalize_optional_string(value: Any, *, key: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise RuntimeError(f"{key} expects a string value or null.")

    normalized = value.strip()
    if normalized.lower() in _NULL_VALUES:
        return None
    return normalized


def _normalize_setting_value(key: str, value: Any) -> Any:
    if key in BOOLEAN_SETTING_KEYS:
        return _coerce_bool(value, key=key)
    if key in OPTIONAL_STRING_SETTING_KEYS:
        return _normalize_optional_string(value, key=key)
    if not isinstance(value, str):
        raise RuntimeError(f"{key} expects a string value.")
    return value


def normalize_config(config: Any) -> dict[str, Any]:
    if not isinstance(config, dict):
        raise RuntimeError("The prep-my-server config file must contain a JSON object.")

    normalized = empty_config()
    raw_tasks = config.get("tasks", {})
    raw_settings = config.get("settings", {})
    if not isinstance(raw_tasks, dict):
        raise RuntimeError("The prep-my-server config 'tasks' value must be a JSON object.")
    if not isinstance(raw_settings, dict):
        raise RuntimeError("The prep-my-server config 'settings' value must be a JSON object.")

    tasks: dict[str, Any] = {}
    for task_name, task_config in raw_tasks.items():
        key = f"tasks.{task_name}.enabled"
        if isinstance(task_config, dict):
            task_normalized: dict[str, Any] = {}
            if "enabled" in task_config:
                task_normalized["enabled"] = _coerce_bool(task_config["enabled"], key=key)
            tasks[task_name] = task_normalized
        else:
            tasks[task_name] = {"enabled": _coerce_bool(task_config, key=key)}

    settings: dict[str, Any] = {}
    for key, value in raw_settings.items():
        if key not in SETTING_DEFAULTS:
            raise RuntimeError(f"Unknown config setting '{key}'.")
        settings[key] = _normalize_setting_value(key, value)

    normalized["version"] = int(config.get("version", CONFIG_VERSION))
    normalized["tasks"] = tasks
    normalized["settings"] = settings
    return normalized


def load_config(config_path: Path = CONFIG_PATH) -> dict[str, Any]:
    content = read_text_file(
        config_path,
        missing_ok=True,
        description="prep-my-server config",
    )
    if content is None:
        return empty_config()

    try:
        return normalize_config(json.loads(content))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Could not parse prep-my-server config at {config_path}: {exc}") from exc


def save_config(config: dict[str, Any], config_path: Path = CONFIG_PATH) -> bool:
    normalized = normalize_config(config)
    content = normalize_text(json.dumps(normalized, indent=2, sort_keys=True))
    return write_text_if_changed(config_path, content, mode=0o644)


def _parse_optional_string(raw_value: str) -> str | None:
    normalized = raw_value.strip()
    if normalized.lower() in _NULL_VALUES:
        return None
    return normalized


def _task_enabled_key_parts(key: str) -> str | None:
    prefix = "tasks."
    suffix = ".enabled"
    if key.startswith(prefix) and key.endswith(suffix):
        task_name = key[len(prefix) : -len(suffix)]
        return task_name or None
    return None


def known_config_keys(task_names: Sequence[str]) -> list[str]:
    task_keys = [f"tasks.{task_name}.enabled" for task_name in task_names]
    return sorted([*SETTING_DEFAULTS.keys(), *task_keys])


def validate_config_key(key: str, task_names: Sequence[str]) -> None:
    task_name = _task_enabled_key_parts(key)
    if task_name is not None:
        if task_name not in task_names:
            raise RuntimeError(f"Unknown task '{task_name}' in config key '{key}'.")
        return

    if key not in SETTING_DEFAULTS:
        known = ", ".join(known_config_keys(task_names))
        raise RuntimeError(f"Unknown config key '{key}'. Known keys: {known}")


def validate_config_task_names(config: dict[str, Any], task_names: Sequence[str]) -> None:
    known_tasks = set(task_names)
    unknown_tasks = sorted(
        task_name
        for task_name in normalize_config(config)["tasks"]
        if task_name not in known_tasks
    )
    if unknown_tasks:
        raise RuntimeError(
            "Unknown task name in prep-my-server config: " + ", ".join(unknown_tasks)
        )


def set_config_value(
    config: dict[str, Any],
    key: str,
    raw_value: str,
    *,
    task_names: Sequence[str],
) -> bool:
    validate_config_key(key, task_names)
    task_name = _task_enabled_key_parts(key)
    if task_name is not None:
        return set_task_enabled(config, task_name, _coerce_bool(raw_value, key=key))

    settings = normalize_config(config)["settings"]
    if key in BOOLEAN_SETTING_KEYS:
        value: Any = _coerce_bool(raw_value, key=key)
    elif key in OPTIONAL_STRING_SETTING_KEYS:
        value = _parse_optional_string(raw_value)
    else:
        value = raw_value

    if settings.get(key) == value:
        return False
    settings[key] = value
    config["settings"] = settings
    return True


def unset_config_value(
    config: dict[str, Any],
    key: str,
    *,
    task_names: Sequence[str],
) -> bool:
    task_name = _task_enabled_key_parts(key)
    if task_name is not None:
        tasks = config.get("tasks", {})
        task_exists = isinstance(tasks, dict) and task_name in tasks
        if task_name not in task_names and not task_exists:
            raise RuntimeError(f"Unknown task '{task_name}' in config key '{key}'.")
        return unset_task_enabled(config, task_name)

    validate_config_key(key, task_names)
    settings = normalize_config(config)["settings"]
    if key not in settings:
        return False
    del settings[key]
    config["settings"] = settings
    return True


def unset_task_enabled(config: dict[str, Any], task_name: str) -> bool:
    tasks = config.get("tasks", {})
    if not isinstance(tasks, dict):
        raise RuntimeError("The prep-my-server config 'tasks' value must be a JSON object.")
    if task_name not in tasks:
        return False
    del tasks[task_name]
    config["tasks"] = tasks
    return True


def set_task_enabled(config: dict[str, Any], task_name: str, enabled: bool) -> bool:
    tasks = normalize_config(config)["tasks"]
    current = tasks.get(task_name)
    if isinstance(current, dict) and current.get("enabled") == enabled:
        return False
    tasks[task_name] = {"enabled": enabled}
    config["tasks"] = tasks
    return True


def task_is_enabled(config: dict[str, Any], task_name: str) -> bool:
    task_config = normalize_config(config)["tasks"].get(task_name, {})
    if not isinstance(task_config, dict):
        return _coerce_bool(task_config, key=f"tasks.{task_name}.enabled")
    if "enabled" not in task_config:
        return True
    return _coerce_bool(task_config["enabled"], key=f"tasks.{task_name}.enabled")


def get_setting(config: dict[str, Any], key: str) -> Any:
    settings = normalize_config(config)["settings"]
    if key in settings:
        return settings[key]
    return SETTING_DEFAULTS[key]


def render_config(config: dict[str, Any]) -> str:
    return json.dumps(normalize_config(config), indent=2, sort_keys=True)
