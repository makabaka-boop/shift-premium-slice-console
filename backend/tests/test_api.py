"""HTTP-level checks: 422 contract, exact fraction payload, CORS preflight."""

from __future__ import annotations

from fractions import Fraction

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _payload(**overrides) -> dict:
    payload = {
        "start": "2026-09-25T22:00",
        "end": "2026-09-26T06:00",
        "baseRateCents": 1000,
        "rules": [
            {
                "id": "night",
                "weekdays": [0, 1, 2, 3, 4, 5, 6],
                "startMinute": 22 * 60,
                "endMinute": 6 * 60,
                "priority": 1,
                "basisPoints": 13_000,
            },
            {
                "id": "special",
                "weekdays": [5],
                "startMinute": 0,
                "endMinute": 4 * 60,
                "priority": 2,
                "basisPoints": 20_000,
            },
        ],
    }
    payload.update(overrides)
    return payload


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_happy_path_exact_fraction_and_segments():
    r = client.post("/api/slice", json=_payload())
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["totalMinutes"] == 480

    # segments: 22:00-24:00 night | 00:00-04:00 special | 04:00-06:00 night
    assert [s["ruleId"] for s in data["segments"]] == [
        "night",
        "special",
        "night",
    ]
    assert [s["minutes"] for s in data["segments"]] == [120, 240, 120]
    # midnight boundary present even though winner is 'night' across it
    assert data["segments"][0]["end"] == "2026-09-26T00:00"
    assert data["segments"][1]["start"] == "2026-09-26T00:00"

    total = Fraction(data["totalPay"]["numerator"], data["totalPay"]["denominator"])
    assert total == Fraction(1000, 600_000) * (
        240 * 13_000 + 240 * 20_000
    )
    # irreducible
    seg_sum = sum(
        (Fraction(s["pay"]["numerator"], s["pay"]["denominator"]) for s in data["segments"]),
        Fraction(0),
    )
    assert seg_sum == total
    assert data["totalPay"]["denominator"] == total.denominator

    # per-minute audit trail present and internally consistent
    minutes = data["minutes"]
    assert len(minutes) == 480
    assert minutes[0]["ruleId"] == "night"
    assert minutes[120]["ruleId"] == "special"
    assert minutes[360]["ruleId"] == "night"
    assert all(m["basisPoints"] >= 10_000 for m in minutes)


def test_baseline_null_rule_id():
    payload = _payload(rules=[])
    r = client.post("/api/slice", json=payload)
    assert r.status_code == 200
    for seg in r.json()["segments"]:
        assert seg["ruleId"] is None
        assert seg["basisPoints"] == 10_000


def test_invalid_date_returns_422():
    r = client.post("/api/slice", json=_payload(start="2026-02-29T22:00"))
    assert r.status_code == 422


def test_empty_weekdays_returns_422():
    bad = _payload()
    bad["rules"][0]["weekdays"] = []
    r = client.post("/api/slice", json=bad)
    assert r.status_code == 422


def test_bad_interval_returns_422():
    r = client.post(
        "/api/slice",
        json=_payload(end="2026-09-25T22:00"),
    )
    assert r.status_code == 422


def test_over_36h_returns_422():
    r = client.post(
        "/api/slice",
        json=_payload(
            start="2026-09-23T00:00", end="2026-09-24T12:01"
        ),
    )
    assert r.status_code == 422


def test_duplicate_ids_422():
    bad = _payload()
    bad["rules"][1]["id"] = "night"
    r = client.post("/api/slice", json=bad)
    assert r.status_code == 422


def test_non_positive_rate_422():
    r = client.post("/api/slice", json=_payload(baseRateCents=-5))
    assert r.status_code == 422


def test_cors_preflight_allowed():
    r = client.options(
        "/api/slice",
        headers={
            "Origin": "http://localhost:8080",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert r.status_code in (200, 204)
