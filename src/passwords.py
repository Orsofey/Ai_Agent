"""Accept old PBKDF2 hashes for explicitly imported local accounts."""
import hashlib
import re
import secrets
from werkzeug.security import check_password_hash


def matches(stored, password):
    if re.fullmatch(r'[0-9a-f]{32}\$[0-9a-f]{64}', stored):
        salt, digest = stored.split('$',1)
        value = hashlib.pbkdf2_hmac('sha256',password.encode(),salt.encode(),120000).hex()
        return secrets.compare_digest(value,digest)
    return check_password_hash(stored,password)
