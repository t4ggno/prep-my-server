#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from common import (
    FeatureResult,
    ensure_directory_path,
    ensure_apt_system,
    ensure_linux,
    ensure_root,
    find_command,
    format_command,
    get_missing_packages,
    is_systemd_available,
    normalize_text,
    package_is_installed,
    print_result,
    read_text_file,
    read_os_release,
    run_checked,
    write_text_if_changed,
)

DOCKER_KEYRING_DIR = Path("/etc/apt/keyrings")
DOCKER_KEYRING_PATH = DOCKER_KEYRING_DIR / "docker.asc"
DOCKER_SOURCE_PATH = Path("/etc/apt/sources.list.d/docker.sources")
DOCKER_PACKAGES: tuple[str, ...] = (
    "docker-ce",
    "docker-ce-cli",
    "containerd.io",
    "docker-buildx-plugin",
    "docker-compose-plugin",
)
DOCKER_PREREQUISITES: tuple[str, ...] = (
    "ca-certificates",
    "curl",
)
CONFLICTING_PACKAGES: tuple[str, ...] = (
    "containerd",
    "docker-compose",
    "docker-compose-v2",
    "docker-doc",
    "docker.io",
    "podman-docker",
    "runc",
)


def _docker_repo_family() -> tuple[str, str]:
    os_release = read_os_release()
    distro_id = os_release.get("ID", "")
    distro_like = os_release.get("ID_LIKE", "")
    codename = os_release.get("VERSION_CODENAME", "")
    ubuntu_codename = os_release.get("UBUNTU_CODENAME", "")

    if distro_id == "ubuntu":
        resolved_codename = ubuntu_codename or codename
        if not resolved_codename:
            raise RuntimeError("Could not determine an Ubuntu release codename from /etc/os-release.")
        return "ubuntu", resolved_codename

    if distro_id == "debian":
        if not codename:
            raise RuntimeError("Could not determine VERSION_CODENAME from /etc/os-release.")
        return "debian", codename

    if "ubuntu" in distro_like.split() or "debian" in distro_like.split():
        raise RuntimeError(
            "This helper intentionally refuses to guess Docker repository codenames for Debian/Ubuntu derivatives. "
            "Run it on a host whose /etc/os-release ID is exactly 'debian' or 'ubuntu', or add derivative-specific mapping first."
        )

    if not codename:
        raise RuntimeError("Could not determine VERSION_CODENAME from /etc/os-release.")

    raise RuntimeError(
        "This Docker installer currently supports Debian and Ubuntu systems only."
    )


def _docker_source_content(*, repo_family: str, codename: str, architecture: str) -> str:
    return normalize_text(
        f"""Types: deb
URIs: https://download.docker.com/linux/{repo_family}
Suites: {codename}
Components: stable
Architectures: {architecture}
Signed-By: {DOCKER_KEYRING_PATH}"""
    )


def _normalize_docker_group_user(user_name: str | None) -> str | None:
    if user_name is None:
        return None

    normalized = user_name.strip()
    if not normalized:
        raise RuntimeError("The Docker group user name cannot be empty or whitespace.")
    if normalized == "root":
        raise RuntimeError(
            "Refusing to add root to the docker group because root already has Docker access."
        )

    try:
        import pwd
    except ImportError:
        return normalized

    try:
        pwd.getpwnam(normalized)
    except KeyError as exc:
        raise RuntimeError(f"User '{normalized}' does not exist on this system.") from exc

    return normalized


def install_docker(
    *,
    dry_run: bool = False,
    add_user_to_docker_group: str | None = None,
) -> FeatureResult:
    ensure_linux()
    ensure_root(dry_run=dry_run)
    ensure_directory_path(DOCKER_KEYRING_DIR, description="Docker keyring directory")

    docker_group_user = _normalize_docker_group_user(add_user_to_docker_group)

    apt_get, dpkg_query = ensure_apt_system()
    architecture = run_checked([find_command(["dpkg"]), "--print-architecture"]).stdout.strip()
    repo_family, codename = _docker_repo_family()
    source_content = _docker_source_content(
        repo_family=repo_family,
        codename=codename,
        architecture=architecture,
    )

    prerequisite_packages = get_missing_packages(
        DOCKER_PREREQUISITES,
        dpkg_query_path=dpkg_query,
    )
    docker_packages = get_missing_packages(DOCKER_PACKAGES, dpkg_query_path=dpkg_query)
    conflicting_packages = [
        package
        for package in CONFLICTING_PACKAGES
        if package_is_installed(package, dpkg_query_path=dpkg_query)
    ]
    if DOCKER_KEYRING_PATH.exists() and DOCKER_KEYRING_PATH.is_dir():
        raise RuntimeError(
            f"Expected Docker repository key file at {DOCKER_KEYRING_PATH}, but found a directory."
        )

    source_needs_update = (
        read_text_file(
            DOCKER_SOURCE_PATH,
            missing_ok=True,
            description="Docker APT source file",
        )
        != source_content
    )
    key_needs_update = not DOCKER_KEYRING_PATH.exists() or DOCKER_KEYRING_PATH.stat().st_size == 0

    result = FeatureResult(name="docker-install")

    if dry_run:
        if conflicting_packages:
            result.add_detail(
                "Would remove conflicting container packages: " + ", ".join(conflicting_packages)
            )
            result.changed = True

        if prerequisite_packages:
            result.add_detail(
                "Would install Docker repository prerequisites: "
                + ", ".join(prerequisite_packages)
            )
            result.add_detail(f"Would run: {format_command([apt_get, 'update'])}")
            result.add_detail(
                f"Would run: {format_command([apt_get, 'install', '-y', '--no-install-recommends', *prerequisite_packages])}"
            )
            result.changed = True

        if key_needs_update:
            result.add_detail(f"Would download Docker's GPG key to {DOCKER_KEYRING_PATH}.")
            result.changed = True
        else:
            result.add_detail(f"{DOCKER_KEYRING_PATH} already exists.")

        if source_needs_update:
            result.add_detail(f"Would write {DOCKER_SOURCE_PATH}.")
            result.changed = True
        else:
            result.add_detail(f"{DOCKER_SOURCE_PATH} already has the desired Docker repository entry.")

        if docker_packages:
            result.add_detail("Would install Docker packages: " + ", ".join(docker_packages))
            result.changed = True
        else:
            result.add_detail("Docker Engine packages are already installed.")

        if is_systemd_available():
            systemctl = find_command(["systemctl"])
            result.add_detail(
                f"Would run: {format_command([systemctl, 'enable', '--now', 'docker.service', 'containerd.service'])}"
            )
        else:
            result.add_warning(
                "Systemd was not detected, so Docker services would not be enabled automatically."
            )
        if docker_group_user:
            result.add_detail(
                f"Would add {docker_group_user} to the docker group for passwordless docker CLI access."
            )
            result.changed = True
        result.add_warning(
            "Docker-published container ports bypass UFW/firewalld rules unless you manage them explicitly via Docker's iptables integration."
        )
        return result

    curl = find_command(["curl"])

    if conflicting_packages:
        run_checked([apt_get, "remove", "-y", *conflicting_packages], env={"DEBIAN_FRONTEND": "noninteractive"})
        result.add_detail(
            "Removed conflicting container packages: " + ", ".join(conflicting_packages)
        )
        result.changed = True

    if prerequisite_packages:
        run_checked([apt_get, "update"])
        run_checked(
            [apt_get, "install", "-y", "--no-install-recommends", *prerequisite_packages],
            env={"DEBIAN_FRONTEND": "noninteractive"},
        )
        result.add_detail(
            "Installed Docker repository prerequisites: " + ", ".join(prerequisite_packages)
        )
        result.changed = True

    DOCKER_KEYRING_DIR.mkdir(parents=True, exist_ok=True)
    DOCKER_KEYRING_DIR.chmod(0o755)
    if key_needs_update:
        run_checked(
            [
                curl,
                "-fsSL",
                f"https://download.docker.com/linux/{repo_family}/gpg",
                "-o",
                str(DOCKER_KEYRING_PATH),
            ]
        )
        DOCKER_KEYRING_PATH.chmod(0o644)
        result.add_detail(f"Downloaded Docker's repository key to {DOCKER_KEYRING_PATH}.")
        result.changed = True
    else:
        result.add_detail(f"{DOCKER_KEYRING_PATH} already exists.")

    if write_text_if_changed(DOCKER_SOURCE_PATH, source_content, mode=0o644):
        result.add_detail(f"Wrote {DOCKER_SOURCE_PATH}.")
        result.changed = True
    else:
        result.add_detail(f"{DOCKER_SOURCE_PATH} already has the desired Docker repository entry.")

    if source_needs_update or prerequisite_packages or key_needs_update:
        run_checked([apt_get, "update"])

    if docker_packages:
        run_checked(
            [apt_get, "install", "-y", *DOCKER_PACKAGES],
            env={"DEBIAN_FRONTEND": "noninteractive"},
        )
        result.add_detail("Installed Docker Engine, containerd, buildx, and Compose plugin.")
        result.changed = True
    else:
        result.add_detail("Docker Engine packages are already installed.")

    if is_systemd_available():
        systemctl = find_command(["systemctl"])
        run_checked([systemctl, "enable", "--now", "docker.service", "containerd.service"])
        result.add_detail("Enabled and started docker.service and containerd.service.")
    else:
        result.add_warning(
            "Systemd was not detected, so Docker services were installed but not enabled automatically."
        )

    if docker_group_user:
        groupadd = find_command(["groupadd"])
        usermod = find_command(["usermod"])
        run_checked([groupadd, "-f", "docker"])
        run_checked([usermod, "-aG", "docker", docker_group_user])
        result.add_detail(
            f"Added {docker_group_user} to the docker group. They must log out and back in for it to apply."
        )
        result.changed = True

    result.add_warning(
        "Docker-published container ports bypass UFW/firewalld rules unless you manage them explicitly via Docker's iptables integration."
    )
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Install Docker from Docker's official Debian/Ubuntu APT repository.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the Docker installation steps without applying them.",
    )
    parser.add_argument(
        "--add-user-to-docker-group",
        metavar="USER",
        help="Optionally add a user to the docker group after installation.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = install_docker(
            dry_run=args.dry_run,
            add_user_to_docker_group=args.add_user_to_docker_group,
        )
        print_result(result)
        return 0
    except Exception as exc:  # pragma: no cover - CLI safety net
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
