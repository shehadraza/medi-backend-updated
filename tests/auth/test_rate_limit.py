from app.modules.auth.rate_limit import _digest, _window_start


def test_digest_is_stable_and_keyed():
    assert _digest("login", "Person@Example.com") == _digest("login", "person@example.com")
    assert _digest("login", "person@example.com") != _digest("forgot", "person@example.com")


def test_window_start_aligns_to_window():
    assert _window_start(125, 60) == 120
    assert _window_start(180, 60) == 180
