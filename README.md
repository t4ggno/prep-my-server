# prep-my-server

`prep-my-server` is a small Linux server preparation toolkit for Debian and Ubuntu hosts.
It bundles a set of opinionated, mostly idempotent setup steps behind one command so you can bring a fresh server to a usable baseline without clicking through a mental checklist every single time.

It can:

- install a baseline package set
- set timezone, locale, and keyboard defaults
- persist global task and setting overrides in `/etc/prep-my-server/config.json`
- enable unattended upgrades
- reduce routine APT and `needrestart` prompts
- add a cached login status block for `update-motd`
- add log rotation for its own local logs
- apply conservative `sysctl` tuning
- install and configure Fail2Ban for SSH
- schedule safe weekly APT cleanup
- schedule automatic server reboots
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
- The top-level default run adds the user that invoked `sudo` to the `docker` group when it can detect one; pass `--no-docker-user` to skip that.
- The `automatic-reboot` task is disabled in the default full run. When enabled, it defaults to a daily check at `03:30` with up to `30m` randomized delay and reboots only if `/var/run/reboot-required` exists.
- The `timezone-locale` task still defaults to **`Europe/Berlin`**, **`de_DE.UTF-8`**, and a **German QWERTZ** keyboard layout, but those values can be changed via CLI flags or global config.
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

When you run `main.py` **without positional tasks**, it executes enabled tasks in this order:

1. `baseline-packages`
2. `timezone-locale`
3. `unattended-upgrades`
4. `apt-ergonomics`
5. `motd-status`
6. `logrotate-tuning`
7. `sysctl-tuning`
8. `fail2ban-setup`
9. `automatic-cleanup`
10. `automatic-reboot`
11. `docker-install`
12. `shell-convenience`
13. `ssh-speedups`
14. `sudo-session-cache`
15. `ssh-login-banner`

`automatic-reboot` is disabled by default in the full run. Enable it persistently with `--enable automatic-reboot`, or run it for one invocation by passing `automatic-reboot` as an explicit task.

If you pass one or more task names, only those tasks run. Explicit positional task names are treated as an override for that invocation, so they can run even if a task is disabled in the global default-run config.

Before running tasks, the command prints a short execution config summary showing disabled tasks, whether `automatic-reboot` is enabled for default full runs, non-default task enablement, and non-default persistent settings.

The top-level CLI keeps going even if one task fails; it reports the error, continues with later tasks, and returns exit code `1` at the end if any task failed.

## Global config

The top-level command reads persistent overrides from:

```text
/etc/prep-my-server/config.json
```

The config file is optional. When it does not exist, the built-in defaults are used. Config commands write only the overrides you choose.

Examples:

```bash
# Run the normal full bundle, but skip unattended upgrades from now on.
sudo prep-my-server --disable unattended-upgrades

# Re-enable it later.
sudo prep-my-server --enable unattended-upgrades

# Enable the reboot-required timer in future default runs.
sudo prep-my-server --enable automatic-reboot

# Use an American keyboard layout in future default runs.
sudo prep-my-server --set-config timezone-locale.keyboard-layout us

# Change the automatic reboot schedule for future default runs.
sudo prep-my-server --set-config automatic-reboot.on-calendar 'Sat *-*-* 04:00:00'

# Use US locale defaults too.
sudo prep-my-server --set-config timezone-locale.locale en_US.UTF-8
sudo prep-my-server --set-config timezone-locale.language en_US:en
sudo prep-my-server --set-config timezone-locale.lc-time en_US.UTF-8

# Return one value to the built-in default.
sudo prep-my-server --unset-config timezone-locale.keyboard-layout

# Inspect current overrides and supported keys.
sudo prep-my-server --show-config
prep-my-server --list-config-keys
```

You can also use `--set-config tasks.unattended-upgrades.enabled false`; `--disable unattended-upgrades` is just the shorter form.

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
- `apt-ergonomics`
- `motd-status`
- `logrotate-tuning`
- `sysctl-tuning`
- `fail2ban-setup`
- `automatic-cleanup`
- `automatic-reboot`
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
| `--config-file FILE` | Use a different config file path instead of `/etc/prep-my-server/config.json`. |
| `--show-config` | Print the current global config and exit unless task names are also passed. |
| `--list-config-keys` | List supported config keys and exit unless task names are also passed. |
| `--set-config KEY VALUE` | Persist a config value. Can be repeated. |
| `--unset-config KEY` | Remove a config override so the built-in default is used again. Can be repeated. |
| `--disable TASK` | Persistently disable a task in the default full run. Can be repeated. |
| `--enable TASK` | Persistently enable a task in the default full run. Can be repeated. |
| `--banner-text TEXT` | Use custom SSH banner text. Only matters when `ssh-login-banner` runs. Mutually exclusive with `--banner-file`. |
| `--banner-file FILE` | Read SSH banner text from a file. Only matters when `ssh-login-banner` runs. Mutually exclusive with `--banner-text`. |
| `--docker-user USER` | After Docker installation, add `USER` to the `docker` group. If omitted, the full main flow uses the user that invoked `sudo` when one can be detected. Only matters when `docker-install` runs. |
| `--no-docker-user` | Do not add any user to the `docker` group. Only matters when `docker-install` runs. |
| `--timezone TIMEZONE` | Override the timezone for this run of `timezone-locale`. |
| `--locale LOCALE` | Override the default locale for this run of `timezone-locale`. |
| `--language LANGUAGE` | Override the `LANGUAGE` value for this run of `timezone-locale`. |
| `--lc-time LC_TIME` | Override the `LC_TIME` value for this run of `timezone-locale`. |
| `--keyboard-model MODEL` | Override `XKBMODEL` for this run of `timezone-locale`. |
| `--keyboard-layout LAYOUT` | Override `XKBLAYOUT` for this run of `timezone-locale`. |
| `--keyboard-variant VARIANT` | Override `XKBVARIANT` for this run of `timezone-locale`. |
| `--keyboard-options OPTIONS` | Override `XKBOPTIONS` for this run of `timezone-locale`. |
| `--keyboard-backspace VALUE` | Override `BACKSPACE` for this run of `timezone-locale`. |
| `--reboot-on-calendar EXPR` | Override the systemd `OnCalendar` expression for this run of `automatic-reboot`. |
| `--reboot-randomized-delay-sec VALUE` | Override `RandomizedDelaySec` for this run of `automatic-reboot`. |

Supported persistent setting keys:

- `timezone-locale.timezone`
- `timezone-locale.locale`
- `timezone-locale.language`
- `timezone-locale.lc-time`
- `timezone-locale.keyboard-model`
- `timezone-locale.keyboard-layout`
- `timezone-locale.keyboard-variant`
- `timezone-locale.keyboard-options`
- `timezone-locale.keyboard-backspace`
- `docker-install.user`
- `docker-install.auto-sudo-user`
- `ssh-login-banner.banner-text`
- `ssh-login-banner.banner-file`
- `automatic-reboot.on-calendar`
- `automatic-reboot.randomized-delay-sec`
- `tasks.<task-name>.enabled`

## Task reference

This is the practical "what does it actually touch?" section.

### `baseline-packages`

Installs a baseline set of common server tools if they are missing:

- `bash-completion`
- `ca-certificates`
- `curl`
- `dnsutils`
- `git`
- `htop`
- `iproute2`
- `iputils-ping`
- `jq`
- `less`
- `lsof`
- `ncdu`
- `netcat-openbsd`
- `ripgrep`
- `rsync`
- `socat`
- `sudo`
- `tmux`
- `tree`
- `unzip`
- `vim`
- `wget`
- `zip`

Behavior:

- runs `apt-get update`
- installs only missing packages
- uses `--no-install-recommends`

### `timezone-locale`

Applies timezone, locale, and console keyboard defaults.

Built-in defaults:

- timezone: `Europe/Berlin`
- locale: `de_DE.UTF-8`
- language preference: `de_DE:de`
- `LC_TIME`: `de_DE.UTF-8`
- keyboard layout: German QWERTZ (`de`)

Common US override:

```bash
sudo prep-my-server --set-config timezone-locale.keyboard-layout us
sudo prep-my-server --set-config timezone-locale.locale en_US.UTF-8
sudo prep-my-server --set-config timezone-locale.language en_US:en
sudo prep-my-server --set-config timezone-locale.lc-time en_US.UTF-8
```

Behavior:

- installs `console-setup`, `keyboard-configuration`, and `locales` if needed
- ensures the configured locale is enabled in `/etc/locale.gen`
- runs `locale-gen`
- updates `/etc/locale.conf` or `/etc/default/locale`
- updates `/etc/default/keyboard`
- sets the timezone with `timedatectl` when available, otherwise updates `/etc/timezone` and `/etc/localtime`
- applies the keyboard layout immediately with `setupcon --keyboard-only` when possible

If you do **not** want the built-in locale/keyboard defaults, change the config values or skip this task.

### `unattended-upgrades`

Enables automatic APT upgrades while leaving the distro-managed policy file in place.

Behavior:

- installs `unattended-upgrades` if missing
- writes `/etc/apt/apt.conf.d/99prep-my-server-auto-upgrades`
- enables `apt-daily.timer` and `apt-daily-upgrade.timer` when `systemd` is available

Written config:

- `APT::Periodic::Update-Package-Lists "1";`
- `APT::Periodic::Unattended-Upgrade "1";`

### `apt-ergonomics`

Adds small APT and `needrestart` drop-ins that make routine upgrades less interactive.

Behavior:

- writes `/etc/apt/apt.conf.d/90prep-my-server-ergonomics`
- writes `/etc/needrestart/conf.d/90-prep-my-server.conf`
- validates APT configuration with `apt-config dump`
- validates the `needrestart` drop-in with `perl -c` when Perl is available

Managed settings:

- asks `dpkg` to use the default conffile action when available
- keeps the locally installed conffile when no default action is available
- shows upgraded packages during `apt-get upgrade`
- enables colored APT output
- makes `needrestart` restart affected services automatically
- disables interactive kernel and microcode reminder prompts from `needrestart`

If `needrestart` is not installed yet, the drop-in is still written and will apply if the package is installed later.

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
- reboot-required status
- failed systemd unit count
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

### `automatic-reboot`

Installs a scheduled automatic reboot timer. This task is disabled in the top-level default full run unless you enable it with config or select it explicitly.

Built-in defaults:

- default full-run state: disabled
- `OnCalendar=*-*-* 03:30:00`
- `RandomizedDelaySec=30m`

Behavior:

- creates `/usr/local/sbin/prep-my-server-reboot`
- writes `/etc/systemd/system/prep-my-server-reboot.service`
- writes `/etc/systemd/system/prep-my-server-reboot.timer`
- creates `/var/log/prep-my-server`
- logs reboot attempts to `/var/log/prep-my-server/reboot.log`
- validates timer values with `systemd-analyze calendar` and `systemd-analyze timespan` when available
- validates the shell script and, when available, validates the systemd units
- enables the timer when `systemd` is available
- the timer only reboots when `/var/run/reboot-required` exists; otherwise it logs and exits

You can change the schedule with either CLI overrides for one run:

```bash
sudo prep-my-server --reboot-on-calendar 'Sat *-*-* 04:00:00' --reboot-randomized-delay-sec 15m automatic-reboot
```

Or persistent config:

```bash
sudo prep-my-server --enable automatic-reboot
sudo prep-my-server --set-config automatic-reboot.on-calendar 'Sat *-*-* 04:00:00'
sudo prep-my-server --set-config automatic-reboot.randomized-delay-sec 15m
```

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

When `docker-install` runs through the top-level `main.py` flow, it defaults to adding the user that invoked `sudo` when one can be detected. Pass `--no-docker-user` to keep Docker root-only.

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
- `GIT_PAGER=less`
- `LESS=-FRX`
- `SYSTEMD_PAGER=cat`
- `SYSTEMD_COLORS=1`
- bigger shell history
- history timestamps
- handy Bash aliases like `l`, `la`, `ll`, `..`, `ports`, and `please`
- human-readable `df`, `du`, and `free` aliases
- case-insensitive Bash completion when readline supports it
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

If you do not pass a custom banner, the default text is a direct authorized-access warning with a little dry humor.

## Direct helper scripts and their parameters

You can run each helper directly instead of using `main.py`.
All helper scripts support `-h` / `--help`.

### Helpers with only `--dry-run`

These scripts accept just one operational flag besides help:

| Script | Meaning of `--dry-run` |
| --- | --- |
| `packages_baseline.py` | Preview package installation changes. |
| `unattended_upgrades.py` | Preview unattended-upgrade changes. |
| `apt_ergonomics.py` | Preview APT and needrestart ergonomics changes. |
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

### `timezone_locale.py`

Parameters:

| Option | Meaning |
| --- | --- |
| `--dry-run` | Preview locale, timezone, and keyboard changes. |
| `--timezone TIMEZONE` | Timezone to set. |
| `--locale LOCALE` | Locale to generate and set. |
| `--language LANGUAGE` | `LANGUAGE` value to set. |
| `--lc-time LC_TIME` | `LC_TIME` value to set. |
| `--keyboard-model MODEL` | `XKBMODEL` value to set. |
| `--keyboard-layout LAYOUT` | `XKBLAYOUT` value to set. |
| `--keyboard-variant VARIANT` | `XKBVARIANT` value to set. |
| `--keyboard-options OPTIONS` | `XKBOPTIONS` value to set. |
| `--keyboard-backspace VALUE` | `BACKSPACE` value to set. |

Example:

```bash
sudo python3 timezone_locale.py --keyboard-layout us --locale en_US.UTF-8 --language en_US:en --lc-time en_US.UTF-8
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

### `automatic_reboot.py`

Parameters:

| Option | Meaning |
| --- | --- |
| `--dry-run` | Preview automatic reboot timer changes. |
| `--on-calendar EXPR` | systemd `OnCalendar` expression for the reboot timer. |
| `--randomized-delay-sec VALUE` | systemd `RandomizedDelaySec` value for the reboot timer. |

Example:

```bash
sudo python3 automatic_reboot.py --on-calendar '*-*-* 03:30:00' --randomized-delay-sec 30m
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

- `pyz` - build an executable zipapp
- `pyinstaller` - build a self-contained Linux executable
- `deb` - build a Debian package

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

- The toolkit is designed to be **idempotent**: rerunning it should mostly result in "already configured" outcomes instead of duplicate configuration.
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

Persistently skip unattended upgrades in the default full run:

```bash
sudo python3 main.py --disable unattended-upgrades
```

Use an American keyboard layout in future default runs:

```bash
sudo python3 main.py --set-config timezone-locale.keyboard-layout us
```

Change the automatic reboot interval to weekly on Saturday night:

```bash
sudo python3 main.py --enable automatic-reboot
sudo python3 main.py --set-config automatic-reboot.on-calendar 'Sat *-*-* 04:00:00'
```

Skip the locale/timezone task for one invocation by choosing only the tasks you want:

```bash
sudo python3 main.py baseline-packages unattended-upgrades motd-status fail2ban-setup
```

Show help:

```bash
python3 main.py --help
python3 ssh_banner.py --help
python3 build_artifacts.py --help
```
