from app.api import auth


def test_token_roundtrip_and_expiry():
    token = auth.make_token("secret", expires_ts=1000)
    assert auth.verify_token("secret", token, now_ts=999)
    assert not auth.verify_token("secret", token, now_ts=1000)


def test_token_rejects_tamper():
    token = auth.make_token("secret", expires_ts=1000)
    assert not auth.verify_token("other", token, now_ts=1)
    assert not auth.verify_token("secret", token + "x", now_ts=1)
    assert not auth.verify_token("secret", "bad", now_ts=1)


def test_limiter_blocks_after_five_attempts():
    limiter = auth.LoginLimiter(max_attempts=5, window_sec=60)
    for _ in range(5):
        assert limiter.allow("1.1.1.1", now=100)
    assert not limiter.allow("1.1.1.1", now=101)
    assert limiter.allow("2.2.2.2", now=101)
    assert limiter.allow("1.1.1.1", now=200)
