from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import httpx

from app import logging_config
from app.logging_config import scrub_event
from app.main import app
from app.pii import hash_user_id

REQ_ID = re.compile(r"^req-[0-9a-f]{8}$")


def _post_chat(payload: dict, headers: dict | None = None) -> httpx.Response:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post("/chat", json=payload, headers=headers or {})

    return asyncio.run(send())


def _read_events(log_path: Path) -> list[dict]:
    return [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]


PAYLOAD = {
    "user_id": "student-01",
    "session_id": "session-01",
    "feature": "qa",
    "message": "Explain observability",
}


def test_generates_correlation_id_and_returns_it(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(logging_config, "LOG_PATH", tmp_path / "logs.jsonl")

    response = _post_chat(PAYLOAD)

    assert response.status_code == 200
    cid = response.headers["x-request-id"]
    assert REQ_ID.match(cid)
    assert response.json()["correlation_id"] == cid
    assert float(response.headers["x-response-time-ms"]) >= 0


def test_reuses_incoming_request_id(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(logging_config, "LOG_PATH", tmp_path / "logs.jsonl")

    response = _post_chat(PAYLOAD, headers={"x-request-id": "req-deadbeef"})

    assert response.headers["x-request-id"] == "req-deadbeef"
    assert response.json()["correlation_id"] == "req-deadbeef"


def test_rejects_unsafe_incoming_request_id(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(logging_config, "LOG_PATH", tmp_path / "logs.jsonl")

    response = _post_chat(PAYLOAD, headers={"x-request-id": "a@b.vn\n{fake}"})

    assert REQ_ID.match(response.headers["x-request-id"])


def test_each_request_gets_its_own_id(monkeypatch, tmp_path: Path) -> None:
    log_path = tmp_path / "logs.jsonl"
    monkeypatch.setattr(logging_config, "LOG_PATH", log_path)

    first = _post_chat(PAYLOAD).headers["x-request-id"]
    second = _post_chat(PAYLOAD).headers["x-request-id"]

    assert first != second
    api_ids = {e["correlation_id"] for e in _read_events(log_path) if e.get("service") == "api"}
    assert api_ids == {first, second}


def test_api_logs_are_enriched(monkeypatch, tmp_path: Path) -> None:
    log_path = tmp_path / "logs.jsonl"
    monkeypatch.setattr(logging_config, "LOG_PATH", log_path)
    monkeypatch.setenv("APP_ENV", "test")

    cid = _post_chat(PAYLOAD).headers["x-request-id"]

    api_events = [e for e in _read_events(log_path) if e.get("service") == "api"]
    assert {e["event"] for e in api_events} == {"request_received", "response_sent"}
    for event in api_events:
        assert event["correlation_id"] == cid
        assert event["user_id_hash"] == hash_user_id("student-01")
        assert event["session_id"] == "session-01"
        assert event["feature"] == "qa"
        assert event["model"]
        assert event["env"] == "test"
        assert "student-01" not in json.dumps(event)
    response_sent = next(e for e in api_events if e["event"] == "response_sent")
    assert response_sent["prompt_name"] == "day13-chat"
    assert response_sent["prompt_version"] == "local-v1"


def test_pii_is_scrubbed_before_it_reaches_the_log_file(monkeypatch, tmp_path: Path) -> None:
    log_path = tmp_path / "logs.jsonl"
    monkeypatch.setattr(logging_config, "LOG_PATH", log_path)

    _post_chat(
        {
            "user_id": "student-01",
            "session_id": "sess-a@b.vn",
            "feature": "qa",
            "message": "Mail student@vinuni.edu.vn, phone 0987654321, card 4111 1111 1111 1111",
        }
    )

    raw = log_path.read_text(encoding="utf-8")
    for leaked in ("student@vinuni.edu.vn", "a@b.vn", "0987654321", "4111 1111 1111 1111"):
        assert leaked not in raw
    assert "[REDACTED_EMAIL]" in raw


def test_scrub_event_handles_nested_and_top_level_fields() -> None:
    event = {
        "event": "request_failed for a@b.vn",
        "session_id": "0987654321",
        "latency_ms": 12,
        "tool_success": False,
        "payload": {"detail": "card 4111111111111111", "items": ["001203004567", 3]},
    }

    out = scrub_event(None, "info", event)

    assert out["event"] == "request_failed for [REDACTED_EMAIL]"
    assert out["session_id"] == "[REDACTED_PHONE_VN]"
    assert out["latency_ms"] == 12
    assert out["tool_success"] is False
    assert out["payload"] == {
        "detail": "card [REDACTED_CREDIT_CARD]",
        "items": ["[REDACTED_CCCD]", 3],
    }
