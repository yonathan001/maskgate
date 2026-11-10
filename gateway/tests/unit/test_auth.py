from app.core.auth import constant_time_compare, generate_api_key, hash_key


def test_hash_key_is_sha256() -> None:
    raw_key = "test_key_123"
    hashed = hash_key(raw_key)
    assert len(hashed) == 64
    assert hashed == hash_key(raw_key)
    assert hashed != hash_key("different_key")


def test_generate_api_key() -> None:
    raw, prefix, key_hash = generate_api_key("mg_live_")
    assert raw.startswith("mg_live_")
    assert prefix == raw[:8]
    assert key_hash == hash_key(raw)


def test_constant_time_compare() -> None:
    assert constant_time_compare("secret_string", "secret_string") is True
    assert constant_time_compare("secret_string", "wrong_string") is False
