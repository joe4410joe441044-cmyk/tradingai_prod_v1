import hashlib
import hmac
import os

CREDENTIAL_HASH_PREFIX = "pbkdf2:sha256:"


def hash_operator_credential(credential: str) -> str:
    iterations = 600_000
    salt = os.urandom(32)
    key = hashlib.pbkdf2_hmac(
        "sha256",
        credential.encode("utf-8"),
        salt,
        iterations,
    )
    return f"pbkdf2:sha256:{iterations}${salt.hex()}${key.hex()}"


def verify_operator_credential(
    credential: str,
    stored_hash: str,
) -> bool:
    if not stored_hash.startswith(CREDENTIAL_HASH_PREFIX):
        return False
    try:
        _, _, params = stored_hash.partition(":")
        algo, _, rest = params.partition(":")
        if algo != "sha256":
            return False
        iter_str, _, remainder = rest.partition("$")
        salt_hex, _, key_hex = remainder.partition("$")
        iterations = int(iter_str)
        salt = bytes.fromhex(salt_hex)
        expected_key = bytes.fromhex(key_hex)
    except (ValueError, TypeError):
        return False
    derived = hashlib.pbkdf2_hmac(
        "sha256",
        credential.encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(derived, expected_key)


class OperatorAuthenticator:
    def __init__(self, credential_hash: str):
        if not credential_hash or not credential_hash.startswith(CREDENTIAL_HASH_PREFIX):
            raise ValueError("credential_hash must be a valid pbkdf2 hash")
        self._hash = credential_hash

    def authenticate(self, credential: str) -> bool:
        if not credential:
            return False
        return verify_operator_credential(credential, self._hash)
