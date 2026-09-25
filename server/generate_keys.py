"""Создать пару ключей Ed25519 для подписи лицензий.

Закрытый ключ — только на сервере (переменная LICENSE_PRIVATE_KEY).
Открытый ключ — в приложение: файл license.json рядом с программой или src/license_config.py.
"""
import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

key = Ed25519PrivateKey.generate()
private = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
print('LICENSE_PRIVATE_KEY=' + base64.b64encode(private).decode())
print('PUBLIC_KEY (в приложение) =', base64.b64encode(public).decode())
