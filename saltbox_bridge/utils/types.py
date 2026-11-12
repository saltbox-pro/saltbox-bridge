from __future__ import annotations

from typing import Literal

SslCertReqs = Literal['none', 'optional', 'required']

KeyType = Literal['ed25519', 'rsa', 'ecdsa', 'dsa']
