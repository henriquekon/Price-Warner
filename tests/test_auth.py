from engine.auth import hash_password, verify_password


def test_password_hash_and_verify():
    password = "testing-password-123"
    hashed = hash_password(password)
    assert password not in hashed
    assert verify_password(password, hashed)
    assert not verify_password("incorrect-password", hashed)


def test_password_minimum_length():
    import pytest
    with pytest.raises(ValueError):
        hash_password("too-short")


def test_invalid_password_hash_rejected():
    assert not verify_password("testing-password-123", "invalid")
