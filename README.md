# prep-my-server

`prep-my-server` helps you turn a fresh Debian or Ubuntu server into a usable baseline with one command.

It focuses on the boring-but-important first setup steps: packages, locale/timezone, updates, Docker, SSH quality-of-life tweaks, Fail2Ban, light maintenance automation, and a few convenience defaults.

## What it does

- installs a practical baseline of admin tools
- sets timezone, locale, and keyboard defaults
- enables unattended upgrades and smoother APT behavior
- adds Fail2Ban and safe SSH quality-of-life tweaks
- installs Docker and applies sane Docker log defaults
- adds MOTD status, shell conveniences, log rotation, and sysctl tuning
- can optionally enable scheduled reboots, nightly Docker restarts, and a conservative firewall baseline

## Best fit

- Linux only
- Debian or Ubuntu hosts
- run with `sudo` or as `root` for real changes
- start with `--dry-run` first, especially on remote servers

Release downloads: <https://github.com/t4ggno/prep-my-server/releases/latest>

## Install

### Recommended: standalone binary

```bash
wget -O prep-my-server https://github.com/t4ggno/prep-my-server/releases/latest/download/prep-my-server-linux-amd64
chmod +x prep-my-server
sudo ./prep-my-server --dry-run
```

### Debian package

```bash
wget -O prep-my-server.deb https://github.com/t4ggno/prep-my-server/releases/latest/download/prep-my-server.deb
sudo apt install ./prep-my-server.deb
sudo prep-my-server --dry-run
```

### From a checkout

```bash
git clone https://github.com/t4ggno/prep-my-server.git
cd prep-my-server
sudo python3 main.py --dry-run
```

If you run from source, replace `prep-my-server` in the examples below with `python3 main.py`.

## Quick start

Preview the default full run:

```bash
sudo prep-my-server --dry-run
```

Apply the default full run:

```bash
sudo prep-my-server
```

Run only a few tasks:

```bash
sudo prep-my-server baseline-packages unattended-upgrades fail2ban-setup
```

Install Docker and add a user to the Docker group:

```bash
sudo prep-my-server docker-install --docker-user alice
```

Add a custom SSH banner:

```bash
sudo prep-my-server ssh-login-banner --banner-file ./banner.txt
```

## Default behavior

The default full run includes:

- core packages and baseline server setup
- timezone, locale, and keyboard configuration
- time sync, unattended upgrades, and APT quality-of-life tweaks
- MOTD status, shell conveniences, log rotation, and sysctl tuning
- Fail2Ban, SSH improvements, SSH hardening audit, and sudo session caching
- Docker installation and Docker log defaults

Disabled by default unless you explicitly enable them:

- `automatic-reboot`
- `docker-nightly-restart`
- `firewall-baseline`

Built-in defaults:

- timezone: `Europe/Berlin`
- locale: `en_US.UTF-8`
- language: `en_US:en`
- `LC_TIME`: `en_US.UTF-8`
- keyboard layout: German QWERTZ (`de`)

When Docker is installed through the full run, `prep-my-server` tries to add the user that invoked `sudo` to the `docker` group. Use `--no-docker-user` if you want Docker to stay root-only.

## Run specific tasks

Pass task names after the command to run only those parts.

### Base system

- `baseline-packages`
- `timezone-locale`
- `time-sync`
- `unattended-upgrades`
- `apt-ergonomics`
- `automatic-cleanup`

### Server polish

- `motd-status`
- `logrotate-tuning`
- `sysctl-tuning`
- `shell-convenience`

### SSH and security

- `fail2ban-setup`
- `ssh-speedups`
- `ssh-hardening-audit`
- `sudo-session-cache`
- `ssh-login-banner`
- `firewall-baseline`

### Docker and scheduled maintenance

- `docker-install`
- `docker-log-defaults`
- `docker-nightly-restart`
- `automatic-reboot`

## Common customizations

Persistent settings live in `/etc/prep-my-server/config.json`.

Use a US keyboard layout in future runs:

```bash
sudo prep-my-server --set-config timezone-locale.keyboard-layout us
```

Switch the locale back to German:

```bash
sudo prep-my-server --set-config timezone-locale.locale de_DE.UTF-8
sudo prep-my-server --set-config timezone-locale.language de_DE:de
sudo prep-my-server --set-config timezone-locale.lc-time de_DE.UTF-8
```

Override the timezone for one run only:

```bash
sudo prep-my-server --timezone America/New_York timezone-locale
```

Skip a task in future default runs:

```bash
sudo prep-my-server --disable unattended-upgrades
```

Enable scheduled reboots:

```bash
sudo prep-my-server --enable automatic-reboot
sudo prep-my-server --set-config automatic-reboot.on-calendar 'Sat *-*-* 04:00:00'
```

Enable nightly Docker restarts:

```bash
sudo prep-my-server --enable docker-nightly-restart
sudo prep-my-server docker-nightly-restart --dry-run
```

Enable the conservative firewall baseline:

```bash
sudo prep-my-server --enable firewall-baseline
sudo prep-my-server firewall-baseline --dry-run
```

Inspect or clean up config:

```bash
sudo prep-my-server --show-config
prep-my-server --list-config-keys
sudo prep-my-server --unset-config timezone-locale.keyboard-layout
```

## Safety notes

- Start with `--dry-run`, especially on remote systems.
- The tool is designed to be idempotent, so re-running it should mostly confirm state instead of duplicating changes.
- The top-level command keeps going after a task error and exits non-zero at the end if anything failed.
- Review SSH, sudo, and firewall changes carefully before applying them to a server you can only reach over the network.
- Docker-published ports can bypass host firewalls such as UFW unless you manage Docker networking deliberately.

## Need the full CLI?

```bash
prep-my-server --help
```
