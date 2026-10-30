import pytest
from fastapi import HTTPException

from services import rate_limit


@pytest.fixture(autouse=True)
def _clean():
    rate_limit.reset()
    yield
    rate_limit.reset()


def test_allows_up_to_the_limit_then_blocks():
    for _ in range(3):
        rate_limit.check_rate_limit("k", 3, 60, now=100.0)
    with pytest.raises(HTTPException) as exc:
        rate_limit.check_rate_limit("k", 3, 60, now=101.0)
    assert exc.value.status_code == 429
    assert int(exc.value.headers["Retry-After"]) >= 1


def test_window_slides_so_old_hits_expire():
    for _ in range(2):
        rate_limit.check_rate_limit("k", 2, 10, now=0.0)
    with pytest.raises(HTTPException):
        rate_limit.check_rate_limit("k", 2, 10, now=5.0)
    rate_limit.check_rate_limit("k", 2, 10, now=11.0)  # first hits are > 10s old


def test_keys_are_independent():
    rate_limit.check_rate_limit("a", 1, 60, now=0.0)
    rate_limit.check_rate_limit("b", 1, 60, now=0.0)
    with pytest.raises(HTTPException):
        rate_limit.check_rate_limit("a", 1, 60, now=1.0)


def test_non_positive_limit_disables_the_check():
    for _ in range(50):
        rate_limit.check_rate_limit("k", 0, 60, now=0.0)


def test_retry_after_reflects_remaining_window():
    rate_limit.check_rate_limit("k", 1, 60, now=0.0)
    with pytest.raises(HTTPException) as exc:
        rate_limit.check_rate_limit("k", 1, 60, now=50.0)
    assert 10 <= int(exc.value.headers["Retry-After"]) <= 12
