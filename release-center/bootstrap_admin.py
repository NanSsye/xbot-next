"""Interactive first-time bootstrap; refuses to replace existing credentials."""
import getpass
import hashlib
import os
import secrets

password = getpass.getpass('Initial admin password: ')
if len(password) < 12:
    raise SystemExit('At least 12 characters required')
salt = secrets.token_bytes(24)
key = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 600000)
with os.fdopen(os.open('/etc/xbot-release-center.env', os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'w') as output:
    output.write(f'ADMIN_USER=nanssye\nADMIN_SALT={salt.hex()}\nADMIN_HASH={key.hex()}\n')
