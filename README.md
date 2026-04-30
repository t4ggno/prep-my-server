# prep-my-server

`prep-my-server` is a small Linux server preparation toolkit for Debian and Ubuntu hosts.
It bundles a set of opinionated, mostly idempotent setup steps behind one command so you can bring a fresh server to a usable baseline without clicking through a mental checklist every single time.

It can:

- install a baseline package set
- set timezone, locale, and keyboard defaults
- enable unattended upgrades
- add a cached login status block for `update-motd`
- add log rotation for its own local logs
- apply conservative `sysctl` tuning
- install and configure Fail2Ban for SSH
- schedule safe weekly APT cleanup
- install Docker from Docker's official repository
- add shell convenience defaults
- apply a few SSH responsiveness tweaks
- keep `sudo` authentication for the life of a terminal session
- configure an SSH pre-login banner

## What this tool targets

This project is designed for:

- **Linux only**
- **Debian/Ubuntu servers**
- **Python 3.10+**
- **root or `sudo` execution for real changes**

Important notes:

- The scripts intentionally refuse to run on non-Linux systems.
- Most tasks assume an APT-based system.
- The Docker helper supports hosts whose `/etc/os-release` reports `ID=debian` or `ID=ubuntu`.
- The `timezone-locale` task is opinionated: it sets **`Europe/Berlin`**, **`de_DE.UTF-8`**, and a **German QWERTZ** keyboard layout.
- A dry run still needs to run on Linux, but it skips privileged writes.

## Quick start on Linux

If you prefer to browse release assets manually, use:

- <https://github.com/t4ggno/prep-my-server/releases/latest>

### Download the latest standalone Linux binary

If you want the self-contained Linux executable for **amd64 / x86_64** systems:

```bash
wget -O prep-my-server https://github.com/t4ggno/prep-my-server/releases/latest/download/prep-my-server-linux-amd64
chmod +x prep-my-server

sudo ./prep-my-server --dry-run
sudo ./prep-my-server
```

This is the easiest option when you want a single binary and do not want to install Python first.

### Run from source

If you want to run directly from the repository:

```bash
git clone https://github.com/t4ggno/prep-my-server.git
cd prep-my-server

sudo python3 main.py --dry-run
sudo python3 main.py
```

If you only want specific steps instead of the full bundle:

```bash
sudo python3 main.py baseline-packages unattended-upgrades fail2ban-setup
```

If you want Docker installed and a user added to the `docker` group:

```bash
sudo python3 main.py docker-install --docker-user alice
```

If you want a custom SSH banner from a file:

```bash
sudo python3 main.py ssh-login-banner --banner-file ./banner.txt
```

### Install the latest `.deb` package

If you want the Debian package from the latest release:

```bash
wget -O prep-my-server.deb https://github.com/t4ggno/prep-my-server/releases/latest/download/prep-my-server.deb
sudo apt install ./prep-my-server.deb

sudo prep-my-server --dry-run
sudo prep-my-server
```

The installed `prep-my-server` launcher uses the same CLI options as `main.py`.

### Download the latest `.pyz` artifact

If you prefer the Python zipapp release artifact:

```bash
wget -O prep-my-server.pyz https://github.com/t4ggno/prep-my-server/releases/latest/download/prep-my-server.pyz
chmod +x prep-my-server.pyz

sudo ./prep-my-server.pyz --dry-run
sudo ./prep-my-server.pyz
```

## What happens when you run `main.py`

When you run `main.py` **without positional tasks**, it executes all tasks in this order:

1. `baseline-packages`
2. `timezone-locale`
3. `unattended-upgrades`
4. `motd-status`
5. `logrotate-tuning`
6. `sysctl-tuning`
7. `fail2ban-setup`
8. `automatic-cleanup`
9. `docker-install`
10. `shell-convenience`
11. `ssh-speedups`
12. `sudo-session-cache`
13. `ssh-login-banner`

If you pass one or more task names, only those tasks run.

The top-level CLI keeps going even if one task fails; it reports the error, continues with later tasks, and returns exit code `1` at the end if any task failed.

## Main command parameters

These options apply to `main.py`, the packaged `prep-my-server` launcher, and the `.pyz` artifact.

### Positional arguments

| Argument | Meaning |
| --- | --- |
| `tasks` | Optional list of task names to run. If omitted, all tasks run in the default order shown above. |

Supported task names:

- `baseline-packages`
- `timezone-locale`
- `unattended-upgrades`
- `motd-status`
- `logrotate-tuning`
- `sysctl-tuning`
- `fail2ban-setup`
- `automatic-cleanup`
- `docker-install`
- `shell-convenience`
- `ssh-speedups`
- `sudo-session-cache`
- `ssh-login-banner`

### Options

| Option | Meaning |
| --- | --- |
| `-h`, `--help` | Show help and exit. |
| `--dry-run` | Preview actions without changing the server. |
| `--banner-text TEXT` | Use custom SSH banner text. Only matters when `ssh-login-banner` runs. Mutually exclusive with `--banner-file`. |
| `--banner-file FILE` | Read SSH banner text from a file. Only matters when `ssh-login-banner` runs. Mutually exclusive with `--banner-text`. |
| `--docker-user USER` | After Docker installation, add `USER` to the `docker` group. Only matters when `docker-install` runs. |

## Task reference

This is the practical “what does it actually touch?” section.

### `baseline-packages`

Installs a baseline set of common server tools if they are missing:

- `bash-completion`
- `ca-certificates`
- `curl`
- `git`
- `htop`
- `jq`
- `less`
- `lsof`
- `ncdu`
- `rsync`
- `tmux`
- `tree`
- `unzip`
- `vim`
- `wget`

Behavior:

- runs `apt-get update`
- installs only missing packages
- uses `--no-install-recommends`

### `timezone-locale`

Applies opinionated regional defaults for this toolkit's preferred environment:

- timezone: `Europe/Berlin`
- locale: `de_DE.UTF-8`
- language preference: `de_DE:de`
- `LC_TIME`: `de_DE.UTF-8`
- keyboard layout: German QWERTZ

Behavior:

- installs `console-setup`, `keyboard-configuration`, and `locales` if needed
- ensures `de_DE.UTF-8 UTF-8` is enabled in `/etc/locale.gen`
- runs `locale-gen`
- updates `/etc/locale.conf` or `/etc/default/locale`
- updates `/etc/default/keyboard`
- sets the timezone with `timedatectl` when available, otherwise updates `/etc/timezone` and `/etc/localtime`
- applies the keyboard layout immediately with `setupcon --keyboard-only` when possible

If you do **not** want German locale/keyboard defaults, skip this task.

### `unattended-upgrades`

Enables automatic APT upgrades while leaving the distro-managed policy file in place.

Behavior:

- installs `unattended-upgrades` if missing
- writes `/etc/apt/apt.conf.d/99prep-my-server-auto-upgrades`
- enables `apt-daily.timer` and `apt-daily-upgrade.timer` when `systemd` is available

Written config:

- `APT::Periodic::Update-Package-Lists "1";`
- `APT::Periodic::Unattended-Upgrade "1";`

### `motd-status`

Adds a small cached `update-motd` status block for interactive logins.

Behavior:

- writes `/usr/local/libexec/prep-my-server-motd-status`
- writes `/etc/update-motd.d/60-prep-my-server-status`
- validates both shell scripts
- renders the status once during setup
- caches output for **5 minutes** under `/run/prep-my-server/motd-status.cache`

The status output includes:

- hostname
- IP addresses
- uptime
- load average
- memory usage
- root filesystem usage
- pending APT upgrades

### `logrotate-tuning`

Creates a dedicated logrotate policy for this toolkit's own local logs.

Behavior:

- installs `logrotate` if missing
- creates `/var/log/prep-my-server`
- writes `/etc/logrotate.d/prep-my-server-local-logs`
- validates with `logrotate --debug`

Policy details:

- rotates `daily`
- keeps `14` archives
- compresses rotated logs
- uses `dateext`
- creates log files as `0640 root root`

### `sysctl-tuning`

Writes a conservative sysctl drop-in and applies it immediately.

Behavior:

- writes `/etc/sysctl.d/90-prep-my-server.conf`
- runs `sysctl -p /etc/sysctl.d/90-prep-my-server.conf`

Managed settings:

- `fs.inotify.max_user_instances = 1024`
- `fs.inotify.max_user_watches = 524288`
- `net.core.somaxconn = 4096`
- `net.ipv4.tcp_keepalive_time = 600`
- `net.ipv4.tcp_keepalive_intvl = 60`
- `net.ipv4.tcp_keepalive_probes = 5`
- `vm.swappiness = 10`
- `vm.vfs_cache_pressure = 50`

### `fail2ban-setup`

Installs Fail2Ban and enables a modest SSH jail override.

Behavior:

- installs `fail2ban` if missing
- writes `/etc/fail2ban/jail.d/90-prep-my-server.local`
- validates configuration with `fail2ban-client -t`
- tries to enable/reload Fail2Ban automatically

Managed settings:

- `bantime = 1h`
- `findtime = 10m`
- `maxretry = 5`
- `ignoreip = 127.0.0.1/8 ::1`
- `[sshd] enabled = true`

Recommendation: review `ignoreip` after deployment if you usually connect from a fixed trusted IP.

### `automatic-cleanup`

Installs a safe weekly APT cleanup job.

Behavior:

- creates `/usr/local/sbin/prep-my-server-cleanup`
- writes `/etc/systemd/system/prep-my-server-cleanup.service`
- writes `/etc/systemd/system/prep-my-server-cleanup.timer`
- creates `/var/log/prep-my-server`
- validates the shell script and, when available, validates the systemd units
- enables the timer when `systemd` is available

Important detail: this cleanup is intentionally conservative.
It runs:

- `apt-get autoclean`
- `apt-get autoremove`

It deliberately does **not** run `apt-get clean` and does not do purge-style removal.

### `docker-install`

Installs Docker from Docker's official APT repository.

Behavior:

- removes conflicting container-related packages if present:
  - `containerd`
  - `docker-compose`
  - `docker-compose-v2`
  - `docker-doc`
  - `docker.io`
  - `podman-docker`
  - `runc`
- installs prerequisites if needed:
  - `ca-certificates`
  - `curl`
- downloads Docker's GPG key to `/etc/apt/keyrings/docker.asc`
- writes `/etc/apt/sources.list.d/docker.sources`
- installs:
  - `docker-ce`
  - `docker-ce-cli`
  - `containerd.io`
  - `docker-buildx-plugin`
  - `docker-compose-plugin`
- enables `docker.service` and `containerd.service` when `systemd` is available
- optionally adds a user to the `docker` group

Security note: published Docker container ports can bypass host firewall rules such as UFW or firewalld unless you manage Docker networking explicitly.

### `shell-convenience`

Adds a small login-shell profile snippet.

Behavior:

- writes `/etc/profile.d/90-prep-my-server.sh`
- validates with `sh -n`
- also validates with `bash -n` when Bash is installed

It sets:

- `EDITOR=vim`
- `VISUAL=vim`
- `PAGER=less`
- `LESS=-FRX`
- bigger shell history
- history timestamps
- handy Bash aliases like `l`, `la`, `ll`, and `..`
- Bash completion when available

### `ssh-speedups`

Applies a few safe SSH defaults for responsiveness and cleaner login output.

Behavior:

- updates `/etc/ssh/sshd_config`
- validates with `sshd -t -f /etc/ssh/sshd_config`
- reloads the SSH service when possible

Managed directives:

- `UseDNS no`
- `GSSAPIAuthentication no`
- `ClientAliveInterval 300`
- `ClientAliveCountMax 2`
- `PrintMotd no`

`PrintMotd no` avoids duplicate MOTD output when `update-motd` is in use.

### `sudo-session-cache`

Configures `sudo` to stay authenticated for the life of the current terminal session.

Behavior:

- writes `/etc/sudoers.d/90-prep-my-server-session-auth`
- validates the sudoers config with `visudo -cf /etc/sudoers`

Managed settings:

- `Defaults timestamp_timeout=-1`
- `Defaults timestamp_type=tty`

This keeps the sudo credential cache tied to the current TTY instead of using a normal time-based expiry.

### `ssh-login-banner`

Configures an SSH pre-login banner.

Behavior:

- writes banner text to `/etc/issue.net`
- updates `/etc/ssh/sshd_config` to use `Banner /etc/issue.net`
- validates the SSH configuration
- reloads the SSH service when possible

If you do not pass a custom banner, the default text is a standard authorized-access warning banner.

## Direct helper scripts and their parameters

You can run each helper directly instead of using `main.py`.
All helper scripts support `-h` / `--help`.

### Helpers with only `--dry-run`

These scripts accept just one operational flag besides help:

| Script | Meaning of `--dry-run` |
| --- | --- |
| `packages_baseline.py` | Preview package installation changes. |
| `timezone_locale.py` | Preview locale, timezone, and keyboard changes. |
| `unattended_upgrades.py` | Preview unattended-upgrade changes. |
| `motd_status.py` | Preview MOTD script changes. |
| `logrotate_tuning.py` | Preview logrotate changes. |
| `sysctl_tuning.py` | Preview sysctl changes. |
| `fail2ban_setup.py` | Preview Fail2Ban changes. |
| `automatic_cleanup.py` | Preview cleanup timer changes. |
| `shell_convenience.py` | Preview shell profile changes. |
| `ssh_speedups.py` | Preview SSH tuning changes. |
| `sudo_session.py` | Preview sudoers changes. |

Example:

```bash
sudo python3 fail2ban_setup.py --dry-run
```

### `docker_install.py`

Parameters:

| Option | Meaning |
| --- | --- |
| `--dry-run` | Preview Docker installation changes. |
| `--add-user-to-docker-group USER` | Add `USER` to the `docker` group after installation. |

Example:

```bash
sudo python3 docker_install.py --add-user-to-docker-group alice
```

### `ssh_banner.py`

Parameters:

| Option | Meaning |
| --- | --- |
| `--dry-run` | Preview banner changes. |
| `--banner-text TEXT` | Use inline custom banner text. |
| `--banner-file FILE` | Read banner text from a file. |

`--banner-text` and `--banner-file` are mutually exclusive.

Example:

```bash
sudo python3 ssh_banner.py --banner-file ./banner.txt
```

## Artifact builder (optional)

Most end users can ignore this section.
It exists for people who want to build a distributable artifact from the repository.

`build_artifacts.py` supports these artifact types:

- `pyz` — build an executable zipapp
- `pyinstaller` — build a self-contained Linux executable
- `deb` — build a Debian package

Parameters:

| Option / Argument | Meaning |
| --- | --- |
| `artifact` | One of `pyz`, `pyinstaller`, or `deb`. |
| `--version VERSION` | Version embedded in artifact metadata. Default: `0.1.0`. |
| `--output-dir DIR` | Output directory. Default: `dist`. |
| `--python PATH` | Interpreter path embedded into the zipapp shebang and Debian launcher. Default: `/usr/bin/python3`. |
| `--runtime-tmpdir DIR` | Extraction base directory baked into the PyInstaller executable. Default: `/var/tmp`. |
| `--maintainer TEXT` | Maintainer string for Debian package metadata. |

Examples:

```bash
python3 build_artifacts.py pyz
python3 build_artifacts.py pyinstaller
python3 build_artifacts.py deb --version 1.0.0
```

Notes:

- PyInstaller builds must be created on Linux.
- Debian package builds require Debian packaging tools such as `dpkg-buildpackage`, `debhelper`, `dh-python`, and `fakeroot`.
- The Debian package expects `/usr/bin/python3`.

## Safety and behavior notes

- The toolkit is designed to be **idempotent**: rerunning it should mostly result in “already configured” outcomes instead of duplicate configuration.
- Several tasks validate generated config before reloading services.
- Several file-writing tasks snapshot existing files and restore them if validation fails.
- If `systemd` is not available, related files may still be written, but timers/services may not be enabled automatically.
- For changes that affect SSH or sudo behavior, review the README and dry-run output carefully before applying them to a remote production host.

## Handy examples

Run everything in preview mode:

```bash
sudo python3 main.py --dry-run
```

Run everything for real:

```bash
sudo python3 main.py
```

Run only Docker setup and shell conveniences:

```bash
sudo python3 main.py docker-install shell-convenience --docker-user alice
```

Skip the German locale/timezone task by choosing only the tasks you want:

```bash
sudo python3 main.py baseline-packages unattended-upgrades motd-status fail2ban-setup
```

Show help:

```bash
python3 main.py --help
python3 ssh_banner.py --help
python3 build_artifacts.py --help
```
