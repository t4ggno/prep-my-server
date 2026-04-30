#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from email.utils import format_datetime
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import zipapp
from pathlib import Path

from common import format_command, read_text_file

APP_NAME = "prep-my-server"
DEFAULT_VERSION = "0.1.0"
DEFAULT_DEB_MAINTAINER = "GitHub Actions <41898282+github-actions[bot]@users.noreply.github.com>"
DEFAULT_PYINSTALLER_RUNTIME_TMPDIR = "/var/tmp"
MODULE_FILES = (
    "automatic_cleanup.py",
    "common.py",
    "docker_install.py",
    "fail2ban_setup.py",
    "logrotate_tuning.py",
    "main.py",
    "motd_status.py",
    "packages_baseline.py",
    "shell_convenience.py",
    "ssh_banner.py",
    "ssh_speedups.py",
    "sudo_session.py",
    "sysctl_tuning.py",
    "timezone_locale.py",
    "unattended_upgrades.py",
)
ENTRYPOINT = "from main import main\nraise SystemExit(main())\n"


def _combine_output(stdout: str, stderr: str) -> str:
    parts = [segment.strip() for segment in (stdout, stderr) if segment and segment.strip()]
    return "\n".join(parts)


def _validated_non_empty(value: str, *, option_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise RuntimeError(f"{option_name} cannot be empty.")
    return normalized


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build release artifacts for prep-my-server: a zipapp, a self-contained "
            "Linux executable, or a Debian package."
        )
    )
    parser.add_argument(
        "artifact",
        choices=("pyz", "pyinstaller", "deb"),
        help="Artifact to build.",
    )
    parser.add_argument(
        "--version",
        default=DEFAULT_VERSION,
        help=f"Version to embed in the artifact metadata (default: {DEFAULT_VERSION}).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("dist"),
        help="Directory where build outputs should be written (default: dist).",
    )
    parser.add_argument(
        "--python",
        default="/usr/bin/python3",
        help="Interpreter path to embed in the generated zipapp shebang and Debian launcher.",
    )
    parser.add_argument(
        "--runtime-tmpdir",
        default=DEFAULT_PYINSTALLER_RUNTIME_TMPDIR,
        help=(
            "Extraction base directory baked into the self-contained Linux executable "
            f"(default: {DEFAULT_PYINSTALLER_RUNTIME_TMPDIR})."
        ),
    )
    parser.add_argument(
        "--maintainer",
        default=DEFAULT_DEB_MAINTAINER,
        help=(
            "Maintainer to embed in Debian package metadata, for example: "
            "'Jane Doe <jane@example.com>'."
        ),
    )
    return parser


def project_root() -> Path:
    return Path(__file__).resolve().parent


def stage_application(stage_dir: Path) -> None:
    root = project_root()
    missing_modules = [module_name for module_name in MODULE_FILES if not (root / module_name).is_file()]
    if missing_modules:
        raise RuntimeError(
            "Cannot stage the application because these source files are missing or not regular files: "
            + ", ".join(missing_modules)
        )

    for module_name in MODULE_FILES:
        shutil.copy2(root / module_name, stage_dir / module_name)

    (stage_dir / "__main__.py").write_text(ENTRYPOINT, encoding="utf-8")


def build_pyz(*, output_dir: Path, interpreter: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{APP_NAME}.pyz"

    with tempfile.TemporaryDirectory(prefix=f"{APP_NAME}-zipapp-") as temp_dir:
        stage_dir = Path(temp_dir) / APP_NAME
        stage_dir.mkdir(parents=True, exist_ok=True)
        stage_application(stage_dir)
        zipapp.create_archive(
            stage_dir,
            target=output_path,
            interpreter=interpreter,
            compressed=True,
        )

    if os_supports_posix_permissions():
        output_path.chmod(output_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    return output_path


def os_supports_posix_permissions() -> bool:
    return hasattr(stat, "S_IXUSR") and os.name == "posix"


def ensure_linux_platform(*, purpose: str) -> None:
    if not sys.platform.startswith("linux"):
        raise RuntimeError(f"{purpose} requires Linux (Debian/Ubuntu or WSL is fine).")


def build_pyinstaller(*, output_dir: Path, runtime_tmpdir: str) -> Path:
    ensure_linux_platform(
        purpose=(
            "Building the self-contained Linux executable with PyInstaller "
            "(PyInstaller is not a cross-compiler)"
        )
    )

    try:
        import PyInstaller.__main__ as pyinstaller_main
    except ImportError as exc:
        raise RuntimeError(
            "PyInstaller is not installed. Install it on the Linux build machine with "
            "'python -m pip install pyinstaller'."
        ) from exc

    output_dir.mkdir(parents=True, exist_ok=True)
    root = project_root()

    with tempfile.TemporaryDirectory(prefix=f"{APP_NAME}-pyinstaller-") as temp_dir:
        temp_path = Path(temp_dir)
        build_args = [
            str(root / "main.py"),
            "--onefile",
            "--name",
            APP_NAME,
            "--paths",
            str(root),
            "--distpath",
            str(output_dir.resolve()),
            "--workpath",
            str(temp_path / "build"),
            "--specpath",
            str(temp_path / "spec"),
            "--noconfirm",
            "--clean",
        ]
        if runtime_tmpdir:
            build_args.extend(["--runtime-tmpdir", runtime_tmpdir])

        pyinstaller_main.run(build_args)

    output_path = output_dir / APP_NAME
    if not output_path.exists():
        raise RuntimeError(f"PyInstaller did not produce the expected executable at {output_path}.")

    if os_supports_posix_permissions():
        output_path.chmod(output_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    return output_path


def ensure_linux_with_debian_build_tools() -> str:
    ensure_linux_platform(purpose="Building a .deb")

    required_commands = {
        "dpkg-buildpackage": "dpkg-dev",
        "dh": "debhelper",
        "dh_python3": "dh-python",
        "fakeroot": "fakeroot",
    }
    missing_packages = [
        package_name
        for command_name, package_name in required_commands.items()
        if shutil.which(command_name) is None
    ]
    if missing_packages:
        missing = ", ".join(sorted(set(missing_packages)))
        raise RuntimeError(
            "Debian build tools are missing. Install these packages on the build machine: "
            f"{missing}."
        )

    dpkg_buildpackage = shutil.which("dpkg-buildpackage")
    assert dpkg_buildpackage is not None
    return dpkg_buildpackage


def write_debian_changelog(*, changelog_path: Path, version: str, maintainer: str) -> None:
    changelog_path.write_text(
        textwrap.dedent(
            f"""\
            {APP_NAME} ({version}) unstable; urgency=medium

              * Release {version}.

             -- {maintainer}  {format_datetime(datetime.now(timezone.utc))}
            """
        ),
        encoding="utf-8",
    )


def rewrite_debian_control_maintainer(*, control_path: Path, maintainer: str) -> None:
    control_content = read_text_file(
        control_path,
        description="Debian control file",
    )
    assert control_content is not None
    lines = control_content.splitlines()
    rewritten_lines: list[str] = []
    replaced = False

    for line in lines:
        if line.startswith("Maintainer: "):
            rewritten_lines.append(f"Maintainer: {maintainer}")
            replaced = True
        else:
            rewritten_lines.append(line)

    if not replaced:
        raise RuntimeError(f"Could not find a Maintainer field in {control_path}.")

    control_path.write_text("\n".join(rewritten_lines) + "\n", encoding="utf-8")


def build_deb(*, output_dir: Path, version: str, interpreter: str, maintainer: str) -> Path:
    dpkg_buildpackage = ensure_linux_with_debian_build_tools()
    if interpreter != "/usr/bin/python3":
        raise RuntimeError(
            "Debian packages should use /usr/bin/python3 so the packaged dependency matches the launcher."
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    root = project_root()
    if not (root / "debian").exists():
        raise RuntimeError("The repository is missing the debian/ packaging directory.")

    with tempfile.TemporaryDirectory(prefix=f"{APP_NAME}-deb-") as temp_dir:
        temp_path = Path(temp_dir)
        source_root = temp_path / f"{APP_NAME}-{version}"
        shutil.copytree(
            root,
            source_root,
            ignore=shutil.ignore_patterns(
                ".git",
                ".mypy_cache",
                ".pytest_cache",
                "__pycache__",
                "build",
                "dist",
                "*.deb",
                "*.pyc",
                "*.pyo",
                "*.pyz",
            ),
        )

        debian_dir = source_root / "debian"
        write_debian_changelog(
            changelog_path=debian_dir / "changelog",
            version=version,
            maintainer=maintainer,
        )
        rewrite_debian_control_maintainer(
            control_path=debian_dir / "control",
            maintainer=maintainer,
        )

        for executable_path in (debian_dir / "rules", debian_dir / APP_NAME):
            if not executable_path.is_file():
                raise RuntimeError(
                    f"Expected Debian packaging helper file at {executable_path}, but it was missing."
                )
            executable_path.chmod(
                executable_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
            )

        build_command = [dpkg_buildpackage, "-us", "-uc", "-b"]
        completed = subprocess.run(
            build_command,
            cwd=source_root,
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            output = _combine_output(completed.stdout, completed.stderr)
            if not output:
                output = f"Command exited with status {completed.returncode}."
            raise RuntimeError(f"Command failed: {format_command(build_command)}\n{output}")

        built_packages = sorted(temp_path.glob(f"{APP_NAME}_{version}_*.deb"))
        if not built_packages:
            raise RuntimeError("dpkg-buildpackage did not produce a .deb artifact.")

        built_package = next(
            (candidate for candidate in built_packages if candidate.name.endswith("_all.deb")),
            built_packages[0],
        )
        output_path = output_dir / built_package.name
        shutil.copy2(built_package, output_path)
        return output_path


def main() -> int:
    args = build_parser().parse_args()

    try:
        if args.artifact == "pyz":
            interpreter = _validated_non_empty(args.python, option_name="--python")
            output_path = build_pyz(output_dir=args.output_dir, interpreter=interpreter)
        elif args.artifact == "pyinstaller":
            output_path = build_pyinstaller(
                output_dir=args.output_dir,
                runtime_tmpdir=args.runtime_tmpdir,
            )
        else:
            version = _validated_non_empty(args.version, option_name="--version")
            interpreter = _validated_non_empty(args.python, option_name="--python")
            maintainer = _validated_non_empty(args.maintainer, option_name="--maintainer")
            output_path = build_deb(
                output_dir=args.output_dir,
                version=version,
                interpreter=interpreter,
                maintainer=maintainer,
            )
    except Exception as exc:  # pragma: no cover - CLI safety net
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())