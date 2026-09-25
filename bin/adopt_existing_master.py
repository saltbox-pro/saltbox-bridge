#! /usr/bin/env python3

# Copyright 2025, 2026 Anton Karmanov, Daniil Chistyakov

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


"""
The script is a part of Salt.Box Bootstrapping

Requires python>=3.7.3
"""

from __future__ import annotations

import argparse
import dataclasses
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, NewType, Optional, TextIO, Union  # pyright: ignore[reportDeprecated]
from uuid import uuid4

try:
    import yaml
except ImportError:
    yaml = None

COLORS = {
    "INFO": "\033[32m",
    "PROMPT": "\033[36m",
    "DEBUG": "\033[33m",
    "WARN": "\033[38;5;208m",
    "ERROR": "\033[31m",
}

RESET = "\033[0m"
LOG_FILE = Path("/var/log/saltbox/bootstrap-log.txt")
LOG_TIMESTAMP_PATTERN = "%Y-%m-%d %H:%M:%S"

REDIS_WAIT_TIMEOUT_SEC = timedelta(seconds=120)
REDIS_WAIT_INTERVAL_SEC = timedelta(seconds=2)

SALTBOX_BRIDGE_ARCHIVE_URL = "https://dev.saltbox.pro/api/v4/projects/saltbox%2Fsaltbox-bridge/repository/archive.zip"
SALT_PIP_BINARY_PATH = Path("/opt/saltstack/salt/bin/pip3")
HTTP_TIMEOUT_SEC = 30
DEFAULT_MASTER_LOG_LEVEL = "warning"

BRIDGE_SYNC_TARGETS = {
    "engines": Path("/srv/salt_extmod/engines"),
    "runners": Path("/srv/salt_extmod/runners"),
    "pillar": Path("/srv/salt_extmod/pillar"),
    "master/salt_master_local": Path("/srv/salt_master_local"),
    "master/salt_local": Path("/srv/salt_local"),
}

BRIDGE_MASTER_CONFIG_SCALARS: Dict[str, Any] = {  # pyright: ignore[reportDeprecated]  # ruff: ignore[non-pep585-annotation]
    "auto_accept": True,
    "log_level_logfile": "quiet",
    "log_fmt_console": "%(asctime)s %(colorlevel)s %(colorname)s %(colormsg)s",
    "presence_events": True,
    "minion_data_cache": True,
    "job_cache": False,
    "minimum_auth_version": 2,
    "gpg_keydir": "/etc/salt/gpgkeys",
    "user": "root",
}

BRIDGE_MASTER_CONFIG_LIST_ITEMS: Dict[str, list] = {  # pyright: ignore[reportDeprecated, reportMissingTypeArgument]  # ruff: ignore[non-pep585-annotation]
    "module_dirs": ["/srv/salt_extmod/"],
    "file_ignore_glob": ["*/.git/*", "*.pyc", "*.swp"],
    "engines": [{"saltbox_delator": {}}, {"saltbox_agent": {}}, {"saltbox_job_runner": {}}],
    "ext_pillar": [{"core_pillar": {}}],
}

BRIDGE_FILE_ROOTS_BASE = ["/srv/salt_custom/", "/srv/salt_local/", "/srv/saltbox_salt/", "/srv/sshfs/"]

BRIDGE_SCHEDULE: Dict[str, Any] = {  # pyright: ignore[reportDeprecated]  # ruff: ignore[non-pep585-annotation]
    "saltbox_delator_cleanup": {
        "hours": 3,
        "function": "saltbox_delator.cleanup_expired_jobs",
    },
}

LOG_PAUSE_SECONDS = 0.5

DEBUG_ENABLED = False


def _color_supported(stream: TextIO) -> bool:
    return "NO_COLOR" not in os.environ and stream.isatty()


def log(msg: str, level: str = "INFO", pause: float = LOG_PAUSE_SECONDS) -> None:
    if level == "DEBUG" and not DEBUG_ENABLED:
        return

    stream = sys.stdout if level in ("INFO", "PROMPT") else sys.stderr
    timestamp = datetime.now(tz=timezone.utc).strftime(LOG_TIMESTAMP_PATTERN)

    prefix = "[Adopting]"
    lvl_tag = f"[{level}]"
    collored_lvl_tag = lvl_tag
    if _color_supported(stream):
        collored_lvl_tag = f"{COLORS.get(level, '')}{lvl_tag}{RESET}"

    print(f"[{timestamp}] {prefix} {collored_lvl_tag} {msg}", file=stream)
    try:
        log_pattern = f"[{timestamp}] {lvl_tag} {msg}\n"
        with LOG_FILE.open('a') as f:
            _ = f.write(f"{log_pattern}")
    except OSError:
        ...

    if pause != 0:
        time.sleep(pause)


def run_indented(cmd: list[str], **popen_kwargs) -> int:  # pyright: ignore[reportMissingParameterType]
    cmd_display = " ".join(cmd)
    border_char = "─"
    width = 80
    top_border = border_char * width

    print(f"\t┌{top_border}")
    print(f"\t│ {cmd_display}")
    print(f"\t├{top_border}")

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        **popen_kwargs,
    )
    if proc.stdout is None:
        msg = "Failed to open pipe to subprocess stdout"
        raise InstallerError(msg)
    for line in proc.stdout:
        print(f"\t│ {line.rstrip()}")
    _ = proc.wait()

    print(f"\t└{top_border}")
    return proc.returncode


@dataclasses.dataclass
class RedisConnectionInfo:
    host: str
    port: int
    username: str
    password: str


class InstallerError(RuntimeError):
    def __init__(self, message: Union[str, BaseException], details: Optional[str] = None) -> None:  # ruff: ignore[non-pep604-annotation-optional, non-pep604-annotation-union]
        super().__init__(message)
        self.details = details


class MasterId:
    _default_id_part: str = 'salt-master'
    id: str

    def __init__(self) -> None:
        self.id = f'{self._default_id_part}-{uuid4()}'


MASTER_ID = NewType("MASTER_ID", MasterId)


@dataclasses.dataclass
class Config:
    master_id: MASTER_ID
    release_tag: str
    saltbox_dir: Path
    master_bin: Path = Path('/etc/salt/master')
    ignore_version_check: bool = False


class ScriptConfigurator:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args: argparse.Namespace = args
        self.config: Config = Config(
            master_id=args.master_id,
            release_tag=args.release_tag,
            saltbox_dir=args.saltbox_dir,
            master_bin=args.master_bin,
            ignore_version_check=args.ignore_version_check
        )
        log(f"Resolved config: {self.config}", level="DEBUG")


def build_arg_parser() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    _ = parser.add_argument("--release-tag", dest="release_tag", required=True)
    _ = parser.add_argument("--master-bin", dest="master_bin", type=Path, required=True)
    _ = parser.add_argument("--saltbox-dir", dest="saltbox_dir", type=Path, required=True)
    _ = parser.add_argument("--master-id", dest="master_id", type=str, default=MasterId().id)
    _ = parser.add_argument("--ignore-version-check", dest="ignore_version_check", action="store_true", default=False)
    _ = parser.add_argument("--debug", dest="debug", action="store_true", default=False)

    return parser.parse_args()


def get_dotenv_var(saltbox_dir: Path, name: str) -> str:

    compose_dir: Path = saltbox_dir / "saltbox-compose"
    dotenv_tool: Path = compose_dir / "bin" / "dotenv_tool.sh"

    log(f"Reading dotenv variable '{name}' via '{dotenv_tool}'", level="DEBUG")

    if not dotenv_tool.exists():
        msg = f"'dotenv_tool.sh' not found at '{dotenv_tool}'"
        raise InstallerError(msg)

    cmd = ['bash', str(dotenv_tool), "get", name]
    try:
        proc = subprocess.run(
            cmd,
            cwd=compose_dir,
            check=True,
            capture_output=True,
            text=True
        )
    except subprocess.CalledProcessError as err:
        msg = f"Failed to read '{name}' from dotenv files"
        raise InstallerError(msg) from err

    value = proc.stdout.rstrip("\n")
    log(f"'{name}' = '{value}'", level="DEBUG")
    return value


def parse_redis_socket(socket_str: str) -> tuple[str, int]:
    if ':' in socket_str:
        host, port_str = socket_str.rsplit(":", 1)
        host = host or "127.0.0.1"
    elif socket_str.isdigit():
        host, port_str = "127.0.0.1", socket_str
    else:
        msg = f"Cannot determine port from Redis socket value: {socket_str}"
        raise InstallerError(msg)

    try:
        port = int(port_str)
    except ValueError as err:
        msg = f"Invalid Redis socket value: '{socket_str}'"
        raise InstallerError(msg) from err

    log(f"Parsed Redis socket '{socket_str}' as host='{host}', port={port}", level="DEBUG")
    return host, port


def get_redis_secret_password(saltbox_dir: Path) -> str:
    secret_path = saltbox_dir / "saltbox-compose" / "secrets" / "redis_salt_password"
    log(f"Reading Redis secret password from '{secret_path}'", level="DEBUG")
    if not secret_path.exists():
        msg = f"Redis secret file not found: '{secret_path}'"
        raise InstallerError(msg)
    return secret_path.read_text(encoding="utf-8").strip()


def load_redis_connection_info(saltbox_dir: Path) -> RedisConnectionInfo:
    log("Loading Redis connection info from the installed Salt.Box stack...")
    socket_str = get_dotenv_var(saltbox_dir, "REDIS_SALT_EXPOSE_SOCKET")
    host, port = parse_redis_socket(socket_str)
    username = get_dotenv_var(saltbox_dir, "REDIS_SALT_USERNAME")
    password = get_redis_secret_password(saltbox_dir)
    log(f"Redis connection info: host='{host}', port={port}, username='{username}'", level="DEBUG")
    return RedisConnectionInfo(host, port, username, password)


REDIS_CA_CERT_DESTINATION = Path("/etc/salt/ssl/redis-ca.crt")
REDIS_CA_CERT_CONTAINER_PATH = "redis-salt:/etc/redis/certs/ca.crt"


def copy_redis_ca_cert(saltbox_dir: Path) -> Path:
    compose_dir = saltbox_dir / "saltbox-compose"
    sb_compose_tool = compose_dir / "bin" / "sb-compose.sh"

    log(f"Copying Redis CA certificate from '{REDIS_CA_CERT_CONTAINER_PATH}' to '{REDIS_CA_CERT_DESTINATION}'...")

    if not sb_compose_tool.exists():
        msg = f"'sb-compose.sh' not found at '{sb_compose_tool}'"
        raise InstallerError(msg)

    try:
        REDIS_CA_CERT_DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    except OSError as err:
        msg = f"Failed to create directory '{REDIS_CA_CERT_DESTINATION.parent}'"
        raise InstallerError(msg) from err

    cmd = ["bash", str(sb_compose_tool), "cp", REDIS_CA_CERT_CONTAINER_PATH, str(REDIS_CA_CERT_DESTINATION)]
    if run_indented(cmd, cwd=compose_dir) != 0:
        msg = "Failed to copy Redis CA certificate from the 'redis-salt' container"
        raise InstallerError(msg)

    if not REDIS_CA_CERT_DESTINATION.is_file():
        msg = f"Redis CA certificate was not found at '{REDIS_CA_CERT_DESTINATION}' after copy"
        raise InstallerError(msg)

    log(f"Redis CA certificate copied to '{REDIS_CA_CERT_DESTINATION}'")
    return REDIS_CA_CERT_DESTINATION


def wait_for_redis(host: str, port: int, timeout: timedelta = REDIS_WAIT_TIMEOUT_SEC) -> None:
    log(f"Waiting for Redis at '{host}:{port}' to become available...")
    deadline = time.monotonic() + timeout.total_seconds()

    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=REDIS_WAIT_TIMEOUT_SEC.total_seconds() + 1):
                log(f"Redis at '{host}:{port}' is reachable")
                return
        except OSError as err:
            remaining = deadline - time.monotonic()
            log(f"Redis not reachable yet ({err}), retrying (timeout in {remaining:.0f}s)...", level="DEBUG")
            time.sleep(REDIS_WAIT_INTERVAL_SEC.total_seconds())

    msg = f"Timed out after {timeout}s waiting for Redis at '{host}:{port}'"
    raise InstallerError(msg)


def check_root() -> None:
    if os.getuid() != 0:
        msg = "This script must be run as root!"
        raise InstallerError(msg)
    log("Running as root", level="DEBUG")


def check_yaml_available() -> None:
    if yaml is None:
        msg = "PyYAML ('yaml' module) is not available for python3"
        details = "Install it via 'apt install python3-yaml' or 'pip3 install pyyaml' and re-run."
        raise InstallerError(msg, details=details)
    log("PyYAML is available", level="DEBUG")


def display_err_and_exit(err: InstallerError) -> None:
    log(str(err), level="ERROR")
    if err.details:
        log(err.details, level="ERROR")
    sys.exit(1)


MASTER_CONFIG_PATH = Path("/etc/salt/master")
SALTBOX_CONFIG_PATH = Path("/etc/salt/saltbox")
BACKUP_TIMESTAMP_PATTERN = "%Y%m%d-%H%M%S"

DEFAULT_SALTBOX_CONFIG: Dict[str, Any] = {  # pyright: ignore[reportDeprecated]  # ruff: ignore[non-pep585-annotation]
    "redis_ssl_use": True,
    "expire": 604800,
    "salt_conf_port": 1022,
    "salt_conf_custom_sync_on": False,
    "sshfs_port": 1022,
    "sshfs_sync_on": False,
}


def load_master_config() -> Dict[str, Any]:  # ruff: ignore[non-pep585-annotation]  # pyright: ignore[reportDeprecated]
    if not MASTER_CONFIG_PATH.exists():
        return {}

    try:
        return yaml.safe_load(MASTER_CONFIG_PATH.read_text(encoding="utf-8")) or {}  # pyright: ignore[reportOptionalMemberAccess]
    except yaml.YAMLError as err:  # pyright: ignore[reportOptionalMemberAccess]
        msg = f"Failed to parse existing '{MASTER_CONFIG_PATH}' as YAML"
        raise InstallerError(msg) from err


def resolve_master_id(candidate_id: str) -> str:
    check_yaml_available()

    existing_id = load_master_config().get("salt_box_master_id")
    if not existing_id or not isinstance(existing_id, str):
        return candidate_id

    log(f"Reusing existing Salt Master id '{existing_id}' found in '{MASTER_CONFIG_PATH}'"
            + f" (ignoring generated '{candidate_id}')")
    return existing_id


def backup_master_config() -> Path:
    if not MASTER_CONFIG_PATH.exists():
        msg = f"'{MASTER_CONFIG_PATH}' does not exist, nothing to back up"
        raise InstallerError(msg)

    timestamp = datetime.now(tz=timezone.utc).strftime(BACKUP_TIMESTAMP_PATTERN)
    backup_path = MASTER_CONFIG_PATH.with_name(f"{MASTER_CONFIG_PATH.name}.bak.{timestamp}")

    log(f"Backing up '{MASTER_CONFIG_PATH}' to '{backup_path}'...")
    try:
        _ = shutil.copy2(MASTER_CONFIG_PATH, backup_path)
    except OSError as err:
        msg = f"Failed to back up '{MASTER_CONFIG_PATH}'"
        raise InstallerError(msg) from err

    log(f"Backup created at '{backup_path}'")
    return backup_path


def download_bridge_archive(release_tag: str, destination_dir: Path) -> Path:
    params = urllib.parse.urlencode({"sha": release_tag})
    url = f"{SALTBOX_BRIDGE_ARCHIVE_URL}?{params}"
    log(f"Downloading 'saltbox-bridge' archive for ref '{release_tag}' from '{url}'...", level="DEBUG")

    parsed_url = urllib.parse.urlparse(url)
    if parsed_url.scheme not in ("http", "https"):
        msg = f"Refusing to open URL with unexpected scheme: '{url}'"
        raise InstallerError(msg)

    archive_path = destination_dir / f"saltbox-bridge-{release_tag}.zip"
    try:
        with urllib.request.urlopen(url, timeout=HTTP_TIMEOUT_SEC) as resp:  # ruff: ignore[suspicious-url-open-usage]
            _ = archive_path.write_bytes(resp.read())
    except urllib.error.HTTPError as err:
        if err.code == 404:
            msg = f"No 'saltbox-bridge' ref matching '{release_tag}' found (server returned 404)"
        else:
            msg = f"HTTP error while downloading 'saltbox-bridge' archive for ref '{release_tag}': {err}"
        raise InstallerError(msg) from err
    except urllib.error.URLError as err:
        msg = f"Network error while downloading 'saltbox-bridge' archive for ref '{release_tag}'"
        raise InstallerError(msg) from err

    if not zipfile.is_zipfile(archive_path):
        msg = f"Downloaded 'saltbox-bridge' archive for ref '{release_tag}' is not a valid zip file"
        raise InstallerError(msg)

    return archive_path


def extract_bridge_archive(archive_path: Path, destination_dir: Path) -> Path:
    with zipfile.ZipFile(archive_path) as archive:
        root_dir_name = archive.namelist()[0].split("/", maxsplit=1)[0]
        archive.extractall(path=destination_dir)

    repo_root = destination_dir / root_dir_name
    if not repo_root.is_dir():
        msg = f"Extracted 'saltbox-bridge' archive root not found: '{repo_root}'"
        raise InstallerError(msg)
    return repo_root


def prepare_bridge_sources(release_tag: str, tmp_dir: Path) -> Path:
    archive_path = download_bridge_archive(release_tag, tmp_dir)
    return extract_bridge_archive(archive_path, tmp_dir)


def install_bridge_package(repo_root: Path) -> None:
    log("Installing 'saltbox_bridge' package...")

    if not SALT_PIP_BINARY_PATH.is_file():
        msg = f"Salt pip3 binary not found: '{SALT_PIP_BINARY_PATH}'"
        raise InstallerError(msg)

    package_dir = repo_root / "saltbox_bridge"
    if not package_dir.is_dir():
        msg = f"'saltbox_bridge' package directory not found: '{package_dir}'"
        raise InstallerError(msg)

    cmd = [str(SALT_PIP_BINARY_PATH), "install", str(package_dir), "--upgrade"]
    if run_indented(cmd) != 0:
        msg = "Failed to install 'saltbox_bridge' package"
        raise InstallerError(msg)

    log("'saltbox_bridge' package installed successfully")


def sync_bridge_files(repo_root: Path) -> None:
    log("Syncing 'saltbox-bridge' engine/runner/pillar files...")

    for source_rel, destination in BRIDGE_SYNC_TARGETS.items():
        source = repo_root / source_rel
        if not source.is_dir():
            log(f"'{source}' not found in the archive, skipping", level="DEBUG")
            continue

        if destination.exists():
            shutil.rmtree(destination)
        try:
            _ = shutil.copytree(source, destination)
        except OSError as err:
            msg = f"Failed to sync '{source}' to '{destination}'"
            raise InstallerError(msg) from err
        log(f"Synced '{source}' -> '{destination}'", level="DEBUG")

    log("'saltbox-bridge' files synced successfully")


def merge_list_unique(existing: list, new_items: list) -> list:  # pyright: ignore[reportMissingTypeArgument]
    merged = list(existing)
    for item in new_items:
        if item not in merged:
            merged.append(item)
    return merged


def merge_master_config_dict(current: Dict[str, Any], master_id: str) -> Dict[str, Any]:  # ruff: ignore[non-pep585-annotation]  # pyright: ignore[reportDeprecated]
    merged = dict(current)

    for key, value in BRIDGE_MASTER_CONFIG_SCALARS.items():
        if key in merged and merged[key] != value:
            log(f"Overriding existing '{key}' master config value ('{merged[key]}' -> '{value}')", level="WARN")
        merged[key] = value

    merged["log_level"] = merged.get("log_level", DEFAULT_MASTER_LOG_LEVEL)
    merged["salt_box_master_id"] = master_id

    for key, items in BRIDGE_MASTER_CONFIG_LIST_ITEMS.items():
        merged[key] = merge_list_unique(merged.get(key, []), items)

    file_roots = dict(merged.get("file_roots") or {})
    file_roots["base"] = merge_list_unique(file_roots.get("base", []), BRIDGE_FILE_ROOTS_BASE)
    merged["file_roots"] = file_roots

    schedule = dict(merged.get("schedule") or {})
    schedule.update(BRIDGE_SCHEDULE)
    merged["schedule"] = schedule

    return merged


def merge_master_config(master_id: str) -> None:
    log(f"Merging bridge configuration into '{MASTER_CONFIG_PATH}'...")
    check_yaml_available()

    current = load_master_config()
    merged = merge_master_config_dict(current, master_id)

    try:
        rendered = yaml.safe_dump(merged, default_flow_style=False, sort_keys=False)  # pyright: ignore[reportOptionalMemberAccess]
        _ = MASTER_CONFIG_PATH.write_text(rendered, encoding="utf-8")
    except OSError as err:
        msg = f"Failed to write merged config to '{MASTER_CONFIG_PATH}'"
        raise InstallerError(msg) from err

    log(f"'{MASTER_CONFIG_PATH}' updated successfully")


def write_saltbox_config(redis_info: RedisConnectionInfo, ca_cert_path: Path) -> None:
    log(f"Writing '{SALTBOX_CONFIG_PATH}'...")
    check_yaml_available()

    config = dict(DEFAULT_SALTBOX_CONFIG)
    config["redis_host"] = redis_info.host
    config["redis_port"] = redis_info.port
    config["redis_username"] = redis_info.username
    config["redis_password"] = redis_info.password
    config["redis_ssl_ca_certs"] = str(ca_cert_path)
    config["salt_conf_server"] = redis_info.host
    config["sshfs_server"] = redis_info.host

    try:
        SALTBOX_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        rendered = yaml.safe_dump(config, default_flow_style=False, sort_keys=False)  # pyright: ignore[reportOptionalMemberAccess]
        _ = SALTBOX_CONFIG_PATH.write_text(rendered, encoding="utf-8")
    except OSError as err:
        msg = f"Failed to write '{SALTBOX_CONFIG_PATH}'"
        raise InstallerError(msg) from err

    log(f"'{SALTBOX_CONFIG_PATH}' written successfully")


def restart_master_service() -> None:
    service_name = "salt-master"

    log(f"Enabling '{service_name}' service...")
    if run_indented(["systemctl", "enable", service_name]) != 0:
        msg = f"Failed to enable '{service_name}' service"
        raise InstallerError(msg)

    log(f"Restarting '{service_name}' service...")
    if run_indented(["systemctl", "restart", service_name]) != 0:
        msg = f"Failed to restart '{service_name}' service"
        raise InstallerError(msg)

    if run_indented(["systemctl", "is-active", "--quiet", service_name]) != 0:
        msg = f"'{service_name}' service is not active after restart"
        raise InstallerError(msg)
    log(f"'{service_name}' service restarted successfully")


def adopt_master(config: Config) -> None:
    config.master_id = resolve_master_id(config.master_id)  # pyright: ignore[reportArgumentType, reportAttributeAccessIssue]
    log(f"Starting adoption of the existing Salt Master (id='{config.master_id}')...")

    redis_info = load_redis_connection_info(config.saltbox_dir)
    wait_for_redis(redis_info.host, redis_info.port)
    _ = backup_master_config()

    with tempfile.TemporaryDirectory() as tmp_dir_name:
        repo_root = prepare_bridge_sources(config.release_tag, Path(tmp_dir_name))
        install_bridge_package(repo_root)
        sync_bridge_files(repo_root)

    merge_master_config(config.master_id)  # pyright: ignore[reportArgumentType]
    ca_cert_path = copy_redis_ca_cert(config.saltbox_dir)
    write_saltbox_config(redis_info, ca_cert_path)
    restart_master_service()


def main() -> None:
    global DEBUG_ENABLED
    try:
        args: argparse.Namespace = build_arg_parser()
        DEBUG_ENABLED = args.debug  # pyright: ignore[reportConstantRedefinition]
        check_root()
        check_yaml_available()
        script_configurator = ScriptConfigurator(args=args)
        adopt_master(script_configurator.config)
        log("Salt Master adoption completed successfully")
    except InstallerError as err:
        display_err_and_exit(err)


if __name__ == '__main__':
    main()
