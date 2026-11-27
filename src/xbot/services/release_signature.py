"""Verify the identity of an official release before using its contents."""

import base64
import binascii
import hashlib
import re

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


def verify_release(item: dict, payload: bytes, public_key: Ed25519PublicKey) -> None:
    fields = [item.get(k) for k in ('Kind', 'Name', 'Version', 'Digest')]
    if not all(isinstance(value, str) for value in fields):
        raise ValueError('发行信息不完整')
    kind, name, version, digest = fields
    if kind not in {'plugin', 'skill', 'framework'} or not all(
        re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,79}', v) for v in (name, version)
    ):
        raise ValueError('发行标识无效')
    if hashlib.sha256(payload).hexdigest() != digest:
        raise ValueError('发行包摘要不符')
    message = '\n'.join(['xbot-release-v1', *fields]).encode('ascii')
    try:
        signature = base64.b64decode(item.get('Signature', ''), validate=True)
        public_key.verify(signature, message)
    except (InvalidSignature, binascii.Error, TypeError, ValueError) as exc:
        raise ValueError('发行签名无效') from exc
