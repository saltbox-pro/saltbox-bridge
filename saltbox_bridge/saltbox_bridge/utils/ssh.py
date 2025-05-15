import logging
import subprocess
from pathlib import Path

from saltbox_bridge.utils.types import KeyType

LOGGER = logging.getLogger(__name__)


def ensure_ssh_key(privkey_file: Path, key_type: KeyType = 'ed25519') -> None:
    """
    Ensure a pair of private and public key files exists.

    Directory of privkey_file must exists.
    """
    if privkey_file.exists():
        return

    cmd = ['ssh-keygen', '-t', key_type, '-N', '', '-f', str(privkey_file)]

    # TODO: Check if cmd is safe
    subprocess.run(cmd, stdin=subprocess.DEVNULL, check=True)  # noqa: S603

    LOGGER.info('SSH key generated: %s', privkey_file)
