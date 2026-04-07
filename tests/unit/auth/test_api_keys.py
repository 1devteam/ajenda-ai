from backend.auth.api_keys import ApiKeyHasher


def test_api_key_hasher_verifies_plaintext() -> None:
    hasher = ApiKeyHasher()
    plaintext = hasher.generate_plaintext()
    hashed = hasher.hash_secret(plaintext)
    assert hasher.verify(plaintext=plaintext, hashed_secret=hashed) is True


def test_api_key_hasher_rejects_wrong_secret() -> None:
    hasher = ApiKeyHasher()
    hashed = hasher.hash_secret("correct")
    assert hasher.verify(plaintext="wrong", hashed_secret=hashed) is False
