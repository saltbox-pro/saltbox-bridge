from __future__ import annotations

import os
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile

import yaml  # type: ignore[import-untyped]


def render_configs(templates: Path, ca_certificate: str, destination: Path) -> None:
    host = os.environ['SALTBOX_IP']
    master_id = os.environ['SALT_MASTER_ID']
    overrides = {
        'master': {
            'id': master_id,
            'salt_box_master_id': master_id,
            'user': 'root',
            'log_level': os.environ['SALT_MASTER_LOG_LEVEL'],
        },
        'minion': {'log_level': os.environ['SALT_MINION_LOG_LEVEL']},
        'saltbox': {
            'redis_host': host,
            'redis_port': int(os.environ['REDIS_PORT']),
            'redis_username': os.environ['REDIS_USERNAME'],
            'redis_password': os.environ['REDIS_PASSWORD'],
            'redis_ssl_ca_certs': ca_certificate,
            'salt_conf_server': host,
            'sshfs_server': host,
            'salt_conf_custom_sync_on': True,
            'sshfs_sync_on': True,
        },
    }
    rendered = {}
    for name, settings in overrides.items():
        template = templates / f'{name}.conf.tpl'
        config = yaml.safe_load(template.read_text(encoding='utf-8'))
        config.update(settings)
        rendered[name] = yaml.safe_dump(config, sort_keys=False, allow_unicode=True)

    for name, content in rendered.items():
        with NamedTemporaryFile(mode='w', encoding='utf-8', dir=destination, delete=False) as tmp:
            path = Path(tmp.name)
            try:
                _ = tmp.write(content)
                tmp.flush()
            except OSError:
                path.unlink(missing_ok=True)
                raise
        try:
            if name != 'saltbox':
                path.chmod(0o644)
            _ = path.replace(destination / name)
        finally:
            path.unlink(missing_ok=True)


if __name__ == '__main__':
    render_configs(Path(
       sys.argv[1]),
       sys.argv[2],
       Path(sys.argv[3])
    )
