
import base64
import hashlib
import hmac
import secrets


ITERATIONS = 600_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)

    password_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        ITERATIONS,
    )

    salt_encoded = base64.urlsafe_b64encode(salt).decode("ascii")
    hash_encoded = base64.urlsafe_b64encode(password_hash).decode("ascii")

    return f"pbkdf2_sha256${ITERATIONS}${salt_encoded}${hash_encoded}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations, salt_encoded, hash_encoded = stored_hash.split("$")

        if algorithm != "pbkdf2_sha256":
            return False

        rounds = int(iterations)

        if not 100_000 <= rounds <= 2_000_000:
            return False

        salt = base64.urlsafe_b64decode(salt_encoded)
        expected_hash = base64.urlsafe_b64decode(hash_encoded)

        actual_hash = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            rounds,
        )

        return hmac.compare_digest(actual_hash, expected_hash)

    except (ValueError, TypeError):
        return False
