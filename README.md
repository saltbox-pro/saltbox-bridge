<div align = right>

&ensp;[<kbd> <br> EN <br> </kbd>](./README.md)&ensp;
&ensp;[<kbd> <br> RU <br> </kbd>](./README_RU.md)&ensp;

</div>

---

# Salt.Box Bridge

## Table of Contents

- **[Description](#description)**
- **[Salt files hierarchy](#salt-files-hierarchy)**
- **[Installing a secondary Salt Master](#installing-a-secondary-salt-master)**
  - [Requirements](#requirements)
  - [Quick start](#quick-start)
  - [What it does](#what-it-does)
  - [Interactive prompts](#interactive-prompts)
  - [Re-running the script](#re-running-the-script)
- **[Adopting an existing Salt Master](#adopting-an-existing-salt-master)**
  - [Requirements](#requirements-1)
  - [Usage](#usage)
  - [What it does](#what-it-does-1)
- **[Installing Salt Evil Minions](#installing-salt-evil-minions)**
  - [Requirements](#requirements-2)
  - [Quick start](#quick-start-1)
  - [What it does](#what-it-does-2)
  - [Interactive prompts](#interactive-prompts-1)
- **[Development](#development)**


## Description
Bridge component is a set of additional SaltStack modules to connect Salt
master to Salt.Box

Currently supported salt-master versions:
- 3008.3

## Salt files hierarchy

- `/srv/salt_custom/` is for user's custom files managed with Salt.Box File
  Browser
- `/srv/saltbox_salt/` is a part of Salt.Box system to replicate states from
packages
- `/srv/salt_local/` is for local Salt.Box states and modules
- `/srv/salt_master_local/` is for the Master local minion Salt.Box service states and
modules
- `/srv/salt_extmod/` is for "external modules". There are some distributed
  with this repository. It is possible to put some custom modules here also
- `/srv/sshfs/` for files to serve both as `ssh://` and `salt://`
- `/srv/roster/` is for the Salt SSH `roster` file of this master. It is
  created from a template on the first start, edited locally on the master,
  not synced with Salt.Box and not served via `salt://`
- `/srv/migrator/` – directory of Salt files related to the migration process, accessible
  via the filebrowser when `FILEBROWSER_MIGRATOR_SOURCE_ENABLED` flag is enabled

## Installing a secondary Salt Master

The [`bin/install_master.sh`](./bin/install_master.sh) script installs Salt
and connects a new, independent `salt-master` to SaltBox via Redis. Use it to
attach a master running on its own host so it shares job data with the main SaltBox instance,
without that host's minion being managed by SaltBox master.

For a fully manual, step-by-step walkthrough of the same process see the
[Salt.Box user documentation](https://saltbox.pro/docs/next/administration/master_install).

### Requirements

- A host with network access to the SaltBox Redis instance by **IP address**,
  hostnames are not accepted by the script's prompts, and its port, `6379`
  by default
- The `redis-ca.crt` authority certificate issued by the SaltBox instance.
  Obtain it from the SaltBox side with
  [Salt.Box Compose](https://dev.saltbox.pro/saltbox/saltbox-compose), for example:

  ```bash
  sudo ./bin/sb-compose.sh cp redis-salt:/etc/redis/certs/ca.crt ./redis-ca.crt
  ```

> **ATTENTION!** The script must be run as root. It installs system packages,
> writes to `/etc/salt/`, `/etc/apt/`, and enables the `salt-master` systemd
> service

### Quick start

The script is self-contained and can be copied on its own to the target
host: it clones the rest of `saltbox-bridge` itself into a `saltbox-bridge/`
directory next to its own location.

```bash
sudo ./bin/install_master.sh
```

Use `--en_locale` or `--ru_locale` to select the language of interactive
prompts and log messages, Russian is the default. Use `-h`/`--help` to print
the full option list and a summary of what the script does.

```bash
sudo ./bin/install_master.sh --en_locale
```

### What it does

1. Installs the `redis-ca.crt` certificate, auto-detected next to the script
   or at a path you provide, to `/etc/salt/ssl/redis-ca.crt`.
2. Checks connectivity to the SaltBox Redis instance at the IP address and
   port you provide
3. Installs required system packages: `curl`, `git`, `rsync`, `gettext` and
   others
4. Installs Salt from the official APT repository
5. Creates the [Salt files hierarchy](#salt-files-hierarchy) directories
6. Clones or updates the [`saltbox-bridge`](https://dev.saltbox.pro/saltbox/saltbox-bridge)
   repository next to the script
7. Syncs Bridge files into the Salt directories above and installs the Bridge
   Python package
8. Renders `/etc/salt/master`, `/etc/salt/minion`, and `/etc/salt/saltbox`
   from the Bridge [`master/templates/`](./master/templates) files, filled in
   with the SaltBox connection details
9. Enables and restarts the `salt-master` service
10. Disables `salt-minion`, since a secondary master does not run its own minion

### Interactive prompts

During the run you will be asked to:

- provide the `redis-ca.crt` certificate: either let the script search the
  current directory automatically, or specify a path
- provide the SaltBox IP address and Redis port
- choose a Salt master ID, `master-<timestamp>` by default, and a log level
  for the master and the minion, chosen separately on a `0`–`9` scale as
  described in [Salt logging
  levels](https://docs.saltproject.io/en/latest/ref/configuration/logging/index.html),
  `1`/`info` by default
- provide the Redis username, `redis` by default, and password used by the
  `saltbox` config

> **NOTE:** If a local copy of `saltbox-bridge` already exists next to the
> script, you will be asked whether to reuse it or re-clone. Re-cloning
> **PERMANENTLY DELETES** the local copy, and you will be warned separately
> if it has uncommitted changes

### Re-running the script

**The script is safe to re-run**: package installation and directory creation are
idempotent, and configs are fully re-rendered from the Bridge templates each
time.

Re-running is the **recommended** way to pick up updated Bridge templates
or to change the master ID, log levels, or Redis credentials.

## Adopting an existing Salt Master

The [`bin/adopt_existing_master.py`](./bin/adopt_existing_master.py) script
connects an already running `salt-master` that has its own existing config
and minions to SaltBox, merging in only the settings Bridge needs instead of
replacing the master config wholesale. It is meant to be run by the Salt.Box
bootstrap installer rather than invoked by hand, since it expects a local
SaltBox Compose checkout to already exist alongside it.

### Requirements

- Root access on the host that already runs the `salt-master` to adopt
- A local `saltbox-compose` checkout under the directory passed as
  `--saltbox-dir`, used to read the Redis connection details and CA
  certificate
- PyYAML installed for the Python interpreter running the script

### Usage

```bash
sudo python3 ./bin/adopt_existing_master.py \
  --release-tag RELEASE_TAG \
  --master-bin /etc/salt/master \
  --saltbox-dir /path/to/saltbox
```

- `--release-tag`: the `saltbox-bridge` release to download and install
  Bridge files from
- `--master-bin`: path to the existing Salt master config file to adopt
- `--saltbox-dir`: directory containing the `saltbox-compose` checkout to
  read connection details from
- `--master-id`: Salt Master id to use, a generated one by default. An
  existing `salt_box_master_id` already configured in `/etc/salt/saltbox`
  always takes priority
- `--ignore-version-check`, `--debug`: optional flags

### What it does

1. Reads the Redis connection details, host, port, username, password
   secret, from the local `saltbox-compose` checkout
2. Waits for the Redis instance to become reachable
3. Backs up the existing `/etc/salt/master` config with a timestamp suffix
4. Downloads the `saltbox-bridge` release archive for the given release tag,
   installs the Bridge Python package, and syncs Bridge files into the Salt
   directories
5. Resolves the Salt Master id, reusing one already configured in
   `/etc/salt/saltbox` if present
6. Merges the Bridge-required settings into the existing master config
   instead of overwriting it
7. Copies the Redis CA certificate and writes `/etc/salt/saltbox` with the
   connection details
8. Enables and restarts the `salt-master` service

## Installing Salt Evil Minions

The [`bin/install_evil.sh`](./bin/install_evil.sh) script installs and starts
[Salt Evil Minions](https://dev.saltbox.pro/saltbox/saltbox-evil-minions), a
configurable number of evil minions connecting to a real `salt-master`.

The script is independent of `install_master.sh` and does not clone or
install `saltbox-bridge`: it only needs the Salt onedir runtime to already
be present on the host.

### Requirements

- The Salt onedir runtime already installed at
  `/opt/saltstack/salt/bin/python3`, for example via `install_master.sh`, or
  a regular `salt-minion`/`salt-master` package
- The **IP address** of the target master, accessible from this host via ports `4505`/`4506`

> **ATTENTION!** The script must be run as root. It writes to
> `/etc/salt/minion.d/`, `/etc/systemd/system/`, `/etc/evil-minions.env`, and
> enables the `evil-minions` and `evil-minions-restart.timer` systemd units

### Quick start

```bash
sudo ./bin/install_evil.sh
```

Use `--en_locale` or `--ru_locale` to select the language of interactive
prompts and log messages, Russian is the default. Use `-h`/`--help` to print
the full option list and a summary of what the script does.

```bash
sudo ./bin/install_evil.sh --en_locale
```

### What it does

1. Verifies that the Salt onedir runtime is present at
   `/opt/saltstack/salt/bin/python3`
2. Asks which master IP address evil-minions should connect to and how many
   evil minions to run
3. Writes `/etc/salt/minion.d/master.conf` and `/etc/salt/minion.d/waiting.conf`
   overrides
4. Clones the [`saltbox-evil-minions`](https://dev.saltbox.pro/saltbox/saltbox-evil-minions)
   repository to `/opt/saltstack/evil-minions`
5. Installs its systemd units, `evil-minions.service`,
   `evil-minions-restart.service` and `evil-minions-restart.timer`, and its
   `/etc/evil-minions.env` env file
6. Asks for the evil-minions log level
7. Enables and restarts the `evil-minions` and `evil-minions-restart.timer`
   services

### Interactive prompts

During the run you will be asked to:

- choose the target master address, either the local master on this host,
  `127.0.0.1`, or a custom **IP address**
- specify the number of evil minions to run, `100` by default
- choose a log level for evil-minions on a `1`-`5` scale, `INFO`, `WARNING`,
  `ERROR`, `CRITICAL` or `DEBUG`, `1`/`INFO` by default

> **NOTE:** re-running the script re-clones `saltbox-evil-minions`, deleting
> any local copy, and re-renders the minion overrides, systemd units, and env
> file

## Development

```bash
uv sync --project saltbox_bridge --extra dev,salt
```
