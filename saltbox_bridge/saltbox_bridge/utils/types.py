from __future__ import annotations

from typing import Literal

SslCertReqs = Literal['none', 'optional', 'required']

SaltTgtType = Literal[
    'glob', 'pcre', 'list', 'grain', 'grain_pcre', 'pillar', 'pillar_pcre', 'nodegroup', 'range', 'compound', 'ipcidr'
]

KeyType = Literal['ed25519', 'rsa', 'ecdsa', 'dsa']
