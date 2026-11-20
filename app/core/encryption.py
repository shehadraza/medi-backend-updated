
import base64
import binascii
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings


NONCE_SIZE = 12
TAG_SIZE = 16


def get_encryption_key() -> bytes:
    key = settings.ENCRYPTION_KEY

    if not key:
        raise RuntimeError("ENCRYPTION_KEY is not configured.")

    try:
        decoded = base64.b64decode(
            key.encode("ascii"),
            altchars=b"-_",
            validate=True,
        )
    except (ValueError, UnicodeEncodeError, binascii.Error) as exc:
        raise RuntimeError("Invalid ENCRYPTION_KEY.") from exc

    if len(decoded) != 32:
        raise RuntimeError(
            "ENCRYPTION_KEY must decode to exactly 32 bytes."
        )

    return decoded


def encrypt_data(
    plaintext: str,
    associated_data: bytes | None = None,
) -> str:
    if not isinstance(plaintext, str) or not plaintext:
        raise ValueError("Plaintext cannot be empty.")

    if associated_data is not None and not isinstance(associated_data, bytes):
        raise TypeError("associated_data must be bytes or None.")

    nonce = os.urandom(NONCE_SIZE)

    encrypted = AESGCM(get_encryption_key()).encrypt(
        nonce,
        plaintext.encode("utf-8"),
        associated_data,
    )

    return base64.urlsafe_b64encode(
        nonce + encrypted
    ).decode("ascii")


def decrypt_data(
    ciphertext: str,
    associated_data: bytes | None = None,
) -> str:
    if not isinstance(ciphertext, str) or not ciphertext:
        raise ValueError("Ciphertext cannot be empty.")

    if associated_data is not None and not isinstance(associated_data, bytes):
        raise TypeError("associated_data must be bytes or None.")

    try:
        raw = base64.b64decode(
            ciphertext.encode("ascii"),
            altchars=b"-_",
            validate=True,
        )
    except (ValueError, UnicodeEncodeError, binascii.Error) as exc:
        raise ValueError("Invalid ciphertext encoding.") from exc

    if len(raw) < NONCE_SIZE + TAG_SIZE:
        raise ValueError("Invalid ciphertext length.")

    nonce = raw[:NONCE_SIZE]
    encrypted = raw[NONCE_SIZE:]

    try:
        decrypted = AESGCM(get_encryption_key()).decrypt(
            nonce,
            encrypted,
            associated_data,
        )
    except InvalidTag:
        raise

    return decrypted.decode("utf-8")


def encrypt_bytes(
    plaintext: bytes,
    associated_data: bytes | None = None,
) -> bytes:
    if not isinstance(plaintext, bytes) or not plaintext:
        raise ValueError("Plaintext bytes cannot be empty.")

    if associated_data is not None and not isinstance(associated_data, bytes):
        raise TypeError("associated_data must be bytes or None.")

    nonce = os.urandom(NONCE_SIZE)

    encrypted = AESGCM(get_encryption_key()).encrypt(
        nonce,
        plaintext,
        associated_data,
    )

    return nonce + encrypted


def decrypt_bytes(
    ciphertext: bytes,
    associated_data: bytes | None = None,
) -> bytes:
    if not isinstance(ciphertext, bytes):
        raise TypeError("Ciphertext must be bytes.")

    if len(ciphertext) < NONCE_SIZE + TAG_SIZE:
        raise ValueError("Invalid ciphertext length.")

    if associated_data is not None and not isinstance(associated_data, bytes):
        raise TypeError("associated_data must be bytes or None.")

    nonce = ciphertext[:NONCE_SIZE]
    encrypted = ciphertext[NONCE_SIZE:]

    return AESGCM(get_encryption_key()).decrypt(
        nonce,
        encrypted,
        associated_data,
    )
