#!/usr/bin/env python3
from __future__ import annotations

import os
import platform
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence

DEFAULT_ENCODING = "utf-8"


class CommandError(RuntimeError):
    """Raised when an external command exits with a non-zero status."""


@dataclass
class FileSnapshot:
    existed: bool
    content: str | None = None
    mode: int | None = None


@dataclass
class FeatureResult:
    name: str
    changed: bool = False
    details: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_detail(self, message: str) -> None:
        self.details.append(message)

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)


def normalize_text(content: str) -> str:
    if not content:
        return content
    return content if content.endswith("\n") else f"{content}\n"


def ensure_linux() -> None:
    if platform.system().lower() != "linux":
        raise RuntimeError("This script is intended to run on Linux.")


def ensure_root(*, dry_run: bool = False) -> None:
    if dry_run:
        return

    geteuid = getattr(os, "geteuid", None)
    if geteuid is None:
        raise RuntimeError("This script must run on Linux with root privileges.")
    if geteuid() != 0:
        raise RuntimeError("Run this script as root, for example: sudo python3 main.py")


def format_command(command: Sequence[str]) -> str:
    return shlex.join([str(part) for part in command])


def find_command(candidates: Sequence[str]) -> str:
    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved

        candidate_path = Path(candidate)
        if candidate_path.is_absolute() and candidate_path.exists():
            return str(candidate_path)

    joined_candidates = ", ".join(candidates)
    raise RuntimeError(f"Required command not found. Checked: {joined_candidates}")


def ensure_apt_system() -> tuple[str, str]:
    apt_get = find_command(["apt-get"])
    dpkg_query = find_command(["dpkg-query"])
    return apt_get, dpkg_query


def package_is_installed(package: str, *, dpkg_query_path: str | None = None) -> bool:
    dpkg_query = dpkg_query_path or find_command(["dpkg-query"])
    success, output = try_run([dpkg_query, "-W", "-f=${Status}", package])
    return success and output.strip() == "install ok installed"


def get_missing_packages(
    packages: Sequence[str],
    *,
    dpkg_query_path: str | None = None,
) -> list[str]:
    return [
        package
        for package in packages
        if not package_is_installed(package, dpkg_query_path=dpkg_query_path)
    ]


def read_os_release(path: Path = Path("/etc/os-release")) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.exists():
        return data

    for raw_line in path.read_text(encoding=DEFAULT_ENCODING).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        parsed_value = value
        try:
            tokens = shlex.split(value, posix=True)
            if tokens:
                parsed_value = tokens[0]
        except ValueError:
            parsed_value = value.strip().strip('"')

        data[key] = parsed_value

    return data


def get_sudo_invoking_user() -> str | None:
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user and sudo_user != "root":
        return sudo_user
    return None


def _combine_output(stdout: str, stderr: str) -> str:
    parts = [segment.strip() for segment in (stdout, stderr) if segment and segment.strip()]
    return "\n".join(parts)


def run_checked(
    command: Sequence[str],
    *,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)

    completed = subprocess.run(
        [str(part) for part in command],
        text=True,
        capture_output=True,
        check=False,
        env=merged_env,
    )
    if completed.returncode != 0:
        output = _combine_output(completed.stdout, completed.stderr)
        if not output:
            output = f"Command exited with status {completed.returncode}."
        raise CommandError(f"Command failed: {format_command(command)}\n{output}")
    return completed


def try_run(
    command: Sequence[str],
    *,
    env: Mapping[str, str] | None = None,
) -> tuple[bool, str]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)

    completed = subprocess.run(
        [str(part) for part in command],
        text=True,
        capture_output=True,
        check=False,
        env=merged_env,
    )
    return completed.returncode == 0, _combine_output(completed.stdout, completed.stderr)


def is_systemd_available() -> bool:
    return shutil.which("systemctl") is not None and Path("/run/systemd/system").exists()


def capture_snapshot(path: Path) -> FileSnapshot:
    if not path.exists():
        return FileSnapshot(existed=False)

    return FileSnapshot(
        existed=True,
        content=path.read_text(encoding=DEFAULT_ENCODING),
        mode=path.stat().st_mode & 0o777,
    )


def restore_snapshot(path: Path, snapshot: FileSnapshot) -> None:
    if not snapshot.existed:
        path.unlink(missing_ok=True)
        return

    write_text_if_changed(path, snapshot.content or "", mode=snapshot.mode)


def write_text_if_changed(path: Path, content: str, *, mode: int | None = None) -> bool:
    existing_content = path.read_text(encoding=DEFAULT_ENCODING) if path.exists() else None
    existing_mode = (path.stat().st_mode & 0o777) if path.exists() else None

    content_changed = existing_content != content
    mode_changed = mode is not None and existing_mode != mode
    if not content_changed and not mode_changed:
        return False

    path.parent.mkdir(parents=True, exist_ok=True)

    if content_changed:
        file_descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
        try:
            with os.fdopen(file_descriptor, "w", encoding=DEFAULT_ENCODING, newline="") as handle:
                handle.write(content)
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    if mode is not None:
        os.chmod(path, mode)

    return True


def print_result(result: FeatureResult) -> None:
    status = "CHANGED" if result.changed else "OK"
    print(f"[{status}] {result.name}")
    for detail in result.details:
        print(f"  - {detail}")
    for warning in result.warnings:
        print(f"  ! {warning}")
