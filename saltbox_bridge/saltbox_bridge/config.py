from __future__ import annotations

from pathlib import Path

from pydantic import DirectoryPath, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from saltbox_bridge.utils.types import SslCertReqs


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
    redis_host: str = Field(alias='REDIS_HOST', default='localhost')
    redis_port: int = Field(alias='REDIS_PORT', default=6379)
    redis_username: str = Field(alias='REDIS_USERNAME')
    redis_password: str = Field(alias='REDIS_PASSWORD')
    redis_db: int = Field(alias='REDIS_DB', default=0)
    redis_ssl_use: bool = Field(alias='REDIS_SSL_USE', default=True)
    redis_ssl_cert_reqs: SslCertReqs = Field(alias='REDIS_SSL_CERT_REQS', default='required')
    redis_ssl_ca_certs: str | None = Field(alias='REDIS_SSL_CA_CERTS', default=None)

    # Salt box
    var_dir: DirectoryPath = Path('/var/lib/saltbox-bridge/')
    expire: int | None = Field(alias='EXPIRE', default=604800)
    max_count_of_gather_minions: int = Field(alias='MAX_COUNT_OF_GATHER_MINIONS', default=100)

    # GPG
    gpg_key_length: int = 4096
    gog_key_name_real: str = 'Saltbox master - {master}'
    gpg_key_email: str = '{master}@saltbox.pro'
    gpg_key_comment: str = 'This is a certificate for saltbox services'

    model_config = SettingsConfigDict(env_file='/etc/salt/saltbox.conf')

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


SETTINGS = Settings()  # type: ignore
