from __future__ import annotations

import logging
from typing import Any

from salt.client import Caller  # type: ignore
from salt.config import minion_config  # type: ignore
from saltbox_bridge_messages import BridgeSyncDoneMessage, MasterSyncStatus

from saltbox_bridge.config import HIERARHY, SETTINGS
from saltbox_bridge.exceptions import SaltCallerTypeError
from saltbox_bridge.utils.core_connector import CoreConnector
from saltbox_bridge.utils.system import utc_now

logger = logging.getLogger(__name__)


def get_salt_caller() -> Caller:
    opts = minion_config('/etc/salt/minion')
    opts['file_client'] = 'local'
    return Caller(mopts=opts)


def get_state_apply_error(data: list[str] | dict[str, dict[str, Any]]) -> list[str]:
    """
    Proccess return dict from salt state.apply function, return errors
    """
    if isinstance(data, list):
        return ['\n'.join(data)]
    elif isinstance(data, dict):
        errors = []
        for key, val in data.items():
            if not val['result']:
                comment = val.get('comment', 'COMMENT IS MISSING')
                errors.append(f'{key}: {comment}')
        return errors
    else:
        msg = f'Unexpected return type {type(data)}'  # type: ignore[unreachable]
        raise SaltCallerTypeError(msg)


class SaltCaller:
    def __init__(self, core_connector: CoreConnector) -> None:
        self.core_connector = core_connector

    @property
    def caller(self) -> Caller:
        # Caller shall be instantiated before every `cmd()` call
        return get_salt_caller()

    async def sync_saltbox(self) -> None:
        state_name = 'sync_saltbox'
        logger.info('Starting %s', state_name)
        pillar = {
            'ssh_dir': str(HIERARHY.ssh_dir),
            'sshfs_sync_on': SETTINGS.sshfs_sync_on,
            'sshfs_server': SETTINGS.sshfs_server,
            'sshfs_port': SETTINGS.sshfs_port,
            'sshfs_user': SETTINGS.sshfs_user,
            'sshfs_privkey': str(HIERARHY.sshfs_privkey),
            'sshfs_pubkey': str(HIERARHY.sshfs_pubkey),
            'salt_conf_server': SETTINGS.salt_conf_server,
            'salt_conf_port': SETTINGS.salt_conf_port,
            'salt_conf_user': SETTINGS.salt_conf_user,
            'salt_conf_privkey': str(HIERARHY.salt_conf_privkey),
            'salt_conf_pubkey': str(HIERARHY.salt_conf_pubkey),
            'salt_conf_custom_sync_on': SETTINGS.salt_conf_custom_sync_on,
        }
        ret = self.caller.cmd('state.apply', state_name, pillar=pillar)
        logger.info('Finished %s', state_name)
        if (errors := get_state_apply_error(ret)) is not None:
            for msg in errors:
                logger.error(msg)
        notification = BridgeSyncDoneMessage(
            master=self.core_connector.master_id,
            status=MasterSyncStatus.SUCCEED if not errors else MasterSyncStatus.ERROR,
            time=utc_now(),
        )
        await self.core_connector.send_messagee(message=notification, message_tag='sync_saltbox_done')

    async def sync_templates(self) -> BridgeSyncDoneMessage:
        """Temporary implementation of templates sync for new module realization"""
        state_name = 'sync_saltbox'
        logger.info('Starting %s', state_name)
        pillar = {
            'ssh_dir': str(HIERARHY.ssh_dir),
            'sshfs_sync_on': SETTINGS.sshfs_sync_on,
            'sshfs_server': SETTINGS.sshfs_server,
            'sshfs_port': SETTINGS.sshfs_port,
            'sshfs_user': SETTINGS.sshfs_user,
            'sshfs_privkey': str(HIERARHY.sshfs_privkey),
            'sshfs_pubkey': str(HIERARHY.sshfs_pubkey),
            'salt_conf_server': SETTINGS.salt_conf_server,
            'salt_conf_port': SETTINGS.salt_conf_port,
            'salt_conf_user': SETTINGS.salt_conf_user,
            'salt_conf_privkey': str(HIERARHY.salt_conf_privkey),
            'salt_conf_pubkey': str(HIERARHY.salt_conf_pubkey),
            'salt_conf_custom_sync_on': SETTINGS.salt_conf_custom_sync_on,
        }
        ret = self.caller.cmd('state.apply', state_name, pillar=pillar)
        logger.info('Finished %s', state_name)
        if (errors := get_state_apply_error(ret)) is not None:
            for msg in errors:
                logger.error(msg)
        return BridgeSyncDoneMessage(
            master=self.core_connector.master_id,
            status=MasterSyncStatus.SUCCEED if not errors else MasterSyncStatus.ERROR,
            time=utc_now(),
        )

    async def ping(self) -> BridgeSyncDoneMessage:
        """Temporary implementation of ping"""
        logger.info('Ping')

        ret = self.caller.cmd('cmd.run', 'echo "pong"')
        logger.info('Pong is: %s', ret)
        msg = ret if ret == 'pong' else 'not pong'
        return BridgeSyncDoneMessage(
            master=self.core_connector.master_id,
            status=MasterSyncStatus.SUCCEED if msg == 'pong' else MasterSyncStatus.ERROR,
            time=utc_now(),
        )

    def encrypt_data(
        self,
        text: str,
        recipients: str | list[str] | None = None,
        gnupghome: str = '/etc/salt/gpgkeys',
    ) -> Any:
        kwargs: dict[str, Any] = {'text': text, 'gnupghome': gnupghome, 'bare': True}
        if recipients:
            kwargs['recipients'] = recipients

        return self.caller.cmd('gpg.encrypt', **kwargs)
