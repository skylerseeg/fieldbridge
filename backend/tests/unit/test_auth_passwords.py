import bcrypt

from app.core.auth import hash_password, verify_password


def test_long_passwords_hash_and_verify_with_bcrypt_limit():
    password = "a" * 80

    hashed = hash_password(password)

    assert verify_password(password, hashed)


def test_existing_passlib_bcrypt_hashes_with_truncated_password_still_verify():
    password = "b" * 90
    passlib_compatible_hash = bcrypt.hashpw(
        password.encode("utf-8")[:72],
        bcrypt.gensalt(),
    ).decode("utf-8")

    assert verify_password(password, passlib_compatible_hash)


def test_malformed_hash_returns_false():
    assert not verify_password("password", "not-a-bcrypt-hash")
