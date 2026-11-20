
import base64

import pytest
from cryptography.exceptions import InvalidTag

from app.core.encryption import encrypt_data, decrypt_data


def test_encrypt_decrypt_english():
    original = "MEDI personal health profile"
    encrypted = encrypt_data(original)

    assert encrypted != original
    assert decrypt_data(encrypted) == original


def test_encrypt_decrypt_bangla_unicode():
    original = "আমার ঘুম ৭ ঘণ্টা। আমি প্রতিদিন ২ লিটার পানি পান করি।"
    encrypted = encrypt_data(original)

    assert decrypt_data(encrypted) == original


def test_same_plaintext_produces_different_ciphertext():
    original = "MEDI security test"

    encrypted_one = encrypt_data(original)
    encrypted_two = encrypt_data(original)

    assert encrypted_one != encrypted_two
    assert decrypt_data(encrypted_one) == original
    assert decrypt_data(encrypted_two) == original


def test_tampered_ciphertext_is_rejected():
    encrypted = encrypt_data("Sensitive health information")
    raw = bytearray(base64.urlsafe_b64decode(encrypted))
    raw[-1] ^= 1

    tampered = base64.urlsafe_b64encode(raw).decode("ascii")

    with pytest.raises(InvalidTag):
        decrypt_data(tampered)


def test_empty_plaintext_is_rejected():
    with pytest.raises(ValueError):
        encrypt_data("")


def test_user_specific_aad():
    original = '{"sleep_hours": 7, "water_liters": 2}'
    user_aad = b"medi:health-profile:user-123"

    encrypted = encrypt_data(original, associated_data=user_aad)

    assert decrypt_data(
        encrypted,
        associated_data=user_aad,
    ) == original

    with pytest.raises(InvalidTag):
        decrypt_data(
            encrypted,
            associated_data=b"medi:health-profile:user-456",
        )


def test_wrong_aad_is_rejected():
    encrypted = encrypt_data(
        "private data",
        associated_data=b"user-A",
    )

    with pytest.raises(InvalidTag):
        decrypt_data(
            encrypted,
            associated_data=b"user-B",
        )


def test_malformed_ciphertext_is_rejected():
    with pytest.raises(ValueError):
        decrypt_data("not-valid-base64!!!")


def test_truncated_ciphertext_is_rejected():
    with pytest.raises(ValueError):
        decrypt_data("YWJj")


def test_associated_data_must_be_bytes():
    with pytest.raises(TypeError):
        encrypt_data("private data", associated_data="user-123")
