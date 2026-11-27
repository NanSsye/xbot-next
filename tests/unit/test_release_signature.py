import base64
import hashlib

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from xbot.services.release_signature import verify_release


def test_release_identity_and_contents_are_bound():
    key = Ed25519PrivateKey.generate()
    payload = b'fixture'
    digest = hashlib.sha256(payload).hexdigest()
    signature = key.sign(f'xbot-release-v1\nplugin\nfixture\n1\n{digest}'.encode())
    item = dict(Kind='plugin', Name='fixture', Version='1', Digest=digest,
                Signature=base64.b64encode(signature).decode())
    verify_release(item, payload, key.public_key())
    for patch in [dict(Kind='framework'), dict(Name='other'), dict(Version='2'), dict(Signature='')]:
        with pytest.raises(ValueError):
            verify_release(item | patch, payload, key.public_key())
    with pytest.raises(ValueError):
        verify_release(item, b'changed', key.public_key())
