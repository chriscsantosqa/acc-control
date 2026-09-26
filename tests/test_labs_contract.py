import time

from coc import labs


def test_labs_user_id_requires_canonical_uuid():
    assert labs.valid_labs_user_id("550e8400-e29b-41d4-a716-446655440000") is True
    assert labs.valid_labs_user_id("550E8400-E29B-41D4-A716-446655440000") is True
    assert labs.valid_labs_user_id("not-a-uuid") is False
    assert labs.valid_labs_user_id("550e8400e29b41d4a716446655440000") is False
    assert labs.valid_labs_user_id(None) is False


def test_state_is_browser_bound_and_one_time():
    session = {}
    labs.begin(session)
    state = session["labs_state"]
    assert labs.take_state(session, state) is True
    assert labs.take_state(session, state) is False


def test_state_expires_after_ttl():
    session = {"labs_state": "x" * 24, "labs_state_at": int(time.time()) - labs.STATE_TTL_S - 1}
    assert labs.take_state(session, "x" * 24) is False
    assert "labs_state" not in session
    assert "labs_state_at" not in session


def test_access_until_requires_matching_active_product_and_zoned_future_date():
    now = 1_700_000_000
    valid = {"product": "coc-control", "active": True, "accessUntil": "2099-01-01T00:00:00Z"}
    assert labs.access_until(valid, now=now) is not None
    assert labs.access_until({**valid, "product": "outro"}, now=now) is None
    assert labs.access_until({**valid, "active": False}, now=now) is None
    assert labs.access_until({**valid, "accessUntil": "2099-01-01T00:00:00"}, now=now) is None
    assert labs.access_until({**valid, "accessUntil": "invalid"}, now=now) is None


def test_owner_access_is_preserved_and_manual_suspension_blocks_subscriber():
    assert labs.has_access({"role": "owner"}) is True
    user = {"role": "subscriber", "access_until": int(time.time()) + 3600, "suspended_at": 1}
    assert labs.has_access(user) is False
