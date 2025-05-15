from __future__ import annotations

import logging
from pathlib import Path

from pydantic import DirectoryPath
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict, YamlConfigSettingsSource

from saltbox_bridge.utils.ssh import ensure_ssh_key
from saltbox_bridge.utils.types import SslCertReqs

LOGGER = logging.getLogger(__name__)


class FaststreamRedisConf:
    def __init__(
        self,
        url: str,
        username: str,
        password: str,
        ssl_cert_reqs: SslCertReqs = 'required',
        ssl_ca_certs: str | None = None,
    ):
        self.url = url
        self.username = username
        self.password = password
        self.ssl_cert_reqs = ssl_cert_reqs
        self.ssl_ca_certs = ssl_ca_certs


class Settings(BaseSettings):
    # Redis
    redis_host: str = 'localhost'
    redis_port: int = 6379
    redis_username: str
    redis_password: str
    redis_db: int = 0
    redis_ssl_use: bool = True
    redis_ssl_cert_reqs: SslCertReqs = 'required'
    redis_ssl_ca_certs: str | None = None

    # General Salt.Box
    var_dir: DirectoryPath = Path('/var/lib/saltbox-bridge/')
    expire: int | None = 604800
    max_count_of_gather_minions: int = 100

    # Salt master GitFS
    gitfs_server: str
    gitfs_port: int = 22
    gitfs_user: str = 'git'

    # SSHFS replication
    sshfs_sync_on: bool = True
    sshfs_server: str | None = None
    sshfs_port: int = 22
    sshfs_user: str | None = None
    sshfs_source: Path = Path('/srv/sshfs/')
    sshfs_destination: Path = Path('/srv/sshfs/')

    # GPG
    gpg_key_length: int = 4096
    gog_key_name_real: str = 'Saltbox master - {master}'
    gpg_key_email: str = '{master}@saltbox.pro'
    gpg_key_comment: str = 'This is a certificate for saltbox services'

    model_config = SettingsConfigDict(yaml_file='/etc/salt/saltbox')

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (YamlConfigSettingsSource(settings_cls),)

    @property
    def redis_protocol(self) -> str:
        return 'rediss' if self.redis_ssl_use else 'redis'

    @property
    def faststream_redis_conf(self) -> FaststreamRedisConf:
        return FaststreamRedisConf(
            url=f'{self.redis_protocol}://{self.redis_host}:{self.redis_port}',
            username=self.redis_username,
            password=self.redis_password,
            ssl_cert_reqs=self.redis_ssl_cert_reqs,
            ssl_ca_certs=self.redis_ssl_ca_certs,
        )


SETTINGS = Settings()


class Hierarhy:
    """
    File hierarhy

    Paths are not directly configurable with config file.
    Directories are guaranted to be created and have correct mode.
    """

    SSH_DIR_MODE: int = 0o700
    GPG_DIR_MODE: int = 0o700

    def __init__(self) -> None:
        self.var_dir: Path = SETTINGS.var_dir
        # Place to keep SSH client files
        self.ssh_dir: Path = self.var_dir / 'ssh'
        self.gpg_dir: Path = self.var_dir / 'gpg'
        self.gitfs_privkey: Path = self.ssh_dir / 'saltbox_ed25519'
        self.gitfs_pubkey: Path = self.ssh_dir / 'saltbox_ed25519.pub'
        self.sshfs_privkey: Path = self.gitfs_privkey
        self.sshfs_pubkey: Path = self.gitfs_pubkey

        self._make_dirs()
        self._ensure_keys()

    def _make_dirs(self) -> None:
        if not self.gpg_dir.exists():
            LOGGER.info('Creating directory for GPG keys: %s', self.gpg_dir)
            self.gpg_dir.mkdir(parents=True)
        self.gpg_dir.chmod(self.GPG_DIR_MODE)
        if not self.ssh_dir.exists():
            LOGGER.info('Creating directory for SSH client files: %s', self.ssh_dir)
            self.ssh_dir.mkdir(parents=True)
        self.ssh_dir.chmod(self.SSH_DIR_MODE)

    def _ensure_keys(self) -> None:
        ensure_ssh_key(self.gitfs_privkey)
        ensure_ssh_key(self.sshfs_privkey)


HIERARHY = Hierarhy()
