"""Free / Pro plans: the 10 MB upload limit, per-plan quotas, and the demo Pro switch."""

from datetime import datetime, timedelta, timezone

import pytest

import config
from services import plans
from tests.conftest import USER_A, USER_B, parse_ndjson, parse_sse

MB = 1024 * 1024


def upload(client, name, data):
    return client.http.post("/api/upload", files={"file": (name, data, "text/plain")})


def done(response):
    assert response.status_code == 200, response.text
    return parse_ndjson(response.text)[-1]


def make_pro(fake_db, user=USER_A, **extra):
    fake_db.update_profile(
        user,
        {
            "plan": "pro",
            "subscription_status": "active",
            "current_period_end": (datetime.now(timezone.utc) + timedelta(days=20)).isoformat(),
            **extra,
        },
    )


# ── the 10 MB limit ──────────────────────────────────────────────────

def test_free_plan_limit_defaults_to_10_mb():
    assert config.MAX_UPLOAD_BYTES == 10 * MB
    assert plans.limits_for(plans.FREE).max_upload_bytes == 10 * MB
    assert plans.limits_for(plans.PRO).max_upload_bytes == 50 * MB


def test_a_file_over_10_mb_is_refused_with_an_upgrade_offer(app_client, fake_db):
    r = upload(app_client, "big.txt", b"x" * (10 * MB + 1))
    assert r.status_code == 413
    detail = r.json()["detail"]
    assert detail["code"] == "file_too_large" and detail["upgrade"] is True and detail["plan"] == "free"
    assert "10 MB" in detail["message"] and "Pro" in detail["message"] and "50 MB" in detail["message"]
    assert not fake_db.documents


def test_a_file_at_exactly_10_mb_is_accepted(app_client):
    text = (b"word " * (2 * MB))[: 10 * MB]
    assert len(text) == 10 * MB
    assert upload(app_client, "edge.txt", text).status_code == 200  # accepted by the size check


def test_pro_users_can_upload_bigger_files(app_client, fake_db):
    make_pro(fake_db)
    body = (b"lorem ipsum dolor " * 1_000_000)[: 12 * MB]
    # Accepted by the size check (the stream starts); a 12 MB *text* file may still hit the page cap later.
    assert upload(app_client, "big.txt", body).status_code == 200


def test_pro_users_are_not_offered_an_upgrade_when_they_hit_the_ceiling(app_client, fake_db, monkeypatch):
    make_pro(fake_db)
    monkeypatch.setattr(config, "PRO_MAX_UPLOAD_BYTES", 1000)
    detail = upload(app_client, "big.txt", b"x" * 2000).json()["detail"]
    assert detail["upgrade"] is False and detail["plan"] == "pro" and "Upgrade" not in detail["message"]


def test_a_file_over_every_plans_limit_is_refused_before_it_is_read(app_client):
    r = app_client.http.post(
        "/api/upload",
        files={"file": ("a.txt", b"hi", "text/plain")},
        headers={"content-length": str(60 * MB)},
    )
    assert r.status_code == 413


def test_the_upload_ceiling_is_the_biggest_plan(monkeypatch):
    assert plans.largest_upload_bytes() == 50 * MB
    monkeypatch.setattr(config, "MAX_UPLOAD_BYTES", 80 * MB)
    assert plans.largest_upload_bytes() == 80 * MB


# ── per-plan quotas ──────────────────────────────────────────────────

def test_library_full_message_offers_pro_on_free_only(app_client, fake_db, monkeypatch):
    monkeypatch.setattr(config, "MAX_DOCS_PER_USER", 1)
    done(upload(app_client, "a.txt", b"some text here"))
    free = upload(app_client, "b.txt", b"some text here").json()["detail"]
    assert free["code"] == "library_full" and free["upgrade"] is True and "Pro" in free["message"]

    make_pro(fake_db)
    assert done(upload(app_client, "b.txt", b"some text here"))["type"] == "done"


def test_pro_gets_the_bigger_daily_question_allowance(app_client, fake_db, monkeypatch):
    done(upload(app_client, "a.txt", b"alpha beta gamma"))
    monkeypatch.setattr(config, "DAILY_QUERY_LIMIT", 1)

    def ask():
        return app_client.http.post("/api/query", json={"question": "alpha?"})

    assert ask().status_code == 200
    blocked = ask()
    assert blocked.status_code == 429
    assert blocked.json()["detail"]["upgrade"] is True and blocked.json()["detail"]["code"] == "daily_limit"

    make_pro(fake_db)
    assert ask().status_code == 200


def test_plans_are_per_user(app_client, fake_db):
    make_pro(fake_db, USER_A)
    assert app_client.http.get("/api/usage").json()["plan"] == "pro"
    app_client.as_user(USER_B)
    assert app_client.http.get("/api/usage").json()["plan"] == "free"


@pytest.mark.parametrize(
    "profile, expected",
    [
        (None, "free"),
        ({"plan": "free"}, "free"),
        ({"plan": "pro", "subscription_status": "active"}, "pro"),
        ({"plan": "pro", "subscription_status": "trialing"}, "pro"),
        ({"plan": "pro", "subscription_status": "past_due"}, "pro"),
        ({"plan": "pro", "subscription_status": "canceled"}, "free"),
        ({"plan": "pro", "subscription_status": "unpaid"}, "free"),
        ({"plan": "pro"}, "pro"),
    ],
)
def test_plan_of(profile, expected):
    assert plans.plan_of(profile) == expected


def test_a_lapsed_subscription_stops_counting_even_if_the_webhook_was_missed():
    now = datetime(2030, 1, 10, tzinfo=timezone.utc)
    inside_grace = {"plan": "pro", "subscription_status": "active", "current_period_end": "2030-01-08T00:00:00+00:00"}
    long_over = {"plan": "pro", "subscription_status": "active", "current_period_end": "2030-01-01T00:00:00+00:00"}
    assert plans.plan_of(inside_grace, now) == "pro"
    assert plans.plan_of(long_over, now) == "free"


def test_usage_reports_the_plan_and_its_limits(app_client, fake_db):
    free = app_client.http.get("/api/usage").json()
    assert free["plan"] == "free" and free["max_upload_bytes"] == 10 * MB
    assert free["documents"]["limit"] == config.MAX_DOCS_PER_USER

    make_pro(fake_db)
    pro = app_client.http.get("/api/usage").json()
    assert pro["plan"] == "pro" and pro["max_upload_bytes"] == 50 * MB
    assert pro["documents"]["limit"] == config.PRO_MAX_DOCS_PER_USER


def test_account_lists_what_pro_adds(app_client):
    body = app_client.http.get("/api/account").json()
    assert body["plan"] == "free" and body["billing"]["price_cents"] == 1000 and body["billing"]["currency"] == "usd"
    assert body["limits"]["free"]["max_upload_bytes"] == 10 * MB
    assert body["limits"]["pro"]["max_upload_bytes"] == 50 * MB


# ── the demo Pro switch (no payment provider) ────────────────────────

def test_switch_is_on_by_default(app_client):
    assert config.BILLING_DEMO_MODE is True
    body = app_client.http.get("/api/account").json()["billing"]
    assert body == {"available": True, "demo": True, "price_cents": 1000, "currency": "usd"}


def test_switching_to_pro_and_back(app_client):
    assert app_client.http.post("/api/billing/demo", json={"plan": "pro"}).status_code == 200
    assert app_client.http.get("/api/usage").json()["plan"] == "pro"
    info = app_client.http.get("/api/account").json()
    assert info["plan"] == "pro" and info["subscription"]["renews_at"]
    app_client.http.post("/api/billing/demo", json={"plan": "free"})
    assert app_client.http.get("/api/usage").json()["plan"] == "free"


def test_switching_off_hides_the_upgrade(app_client, fake_db, monkeypatch):
    monkeypatch.setattr(config, "BILLING_DEMO_MODE", False)
    assert app_client.http.get("/api/account").json()["billing"]["available"] is False
    r = app_client.http.post("/api/billing/demo", json={"plan": "pro"})
    assert r.status_code == 404 and fake_db.get_profile(USER_A) is None


def test_an_unknown_plan_is_rejected(app_client):
    assert app_client.http.post("/api/billing/demo", json={"plan": "enterprise"}).status_code == 422


def test_each_user_switches_only_their_own_plan(app_client):
    app_client.http.post("/api/billing/demo", json={"plan": "pro"})
    app_client.as_user(USER_B)
    assert app_client.http.get("/api/usage").json()["plan"] == "free"


def test_the_switch_requires_sign_in(app_client):
    import main

    main.app.dependency_overrides.clear()
    assert app_client.http.post("/api/billing/demo", json={"plan": "pro"}).status_code == 401


def test_the_plan_cannot_be_changed_through_settings_or_the_profile(app_client):
    app_client.http.put("/api/settings", json={"plan": "pro"})
    app_client.http.patch("/api/account", json={"display_name": "Sam", "plan": "pro"})
    assert app_client.http.get("/api/usage").json()["plan"] == "free"


def test_normal_questions_are_unaffected(app_client):
    done(upload(app_client, "a.txt", b"alpha beta gamma"))
    r = app_client.http.post("/api/query", json={"question": "alpha?"})
    assert [e["type"] for e in parse_sse(r.text)][-1] == "done"
