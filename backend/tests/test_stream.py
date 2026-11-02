import json

from fastapi.testclient import TestClient

from app.main import app


def _collect_events(response) -> list[dict]:
    events = []
    for line in response.iter_lines():
        if line.startswith("data:"):
            events.append(json.loads(line[5:]))
    return events


def test_chat_stream_emits_tokens_and_done():
    with TestClient(app) as client:
        with client.stream(
            "POST",
            "/api/chat/stream",
            json={"session_id": "stream1", "message": "스트림 테스트"},
        ) as r:
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("text/event-stream")
            events = _collect_events(r)

        types = [e["type"] for e in events]
        assert types[-1] == "done"
        text = "".join(e["content"] for e in events if e["type"] == "token")
        assert "스트림 테스트" in text


def test_chat_stream_keeps_multi_turn_history():
    with TestClient(app) as client:
        with client.stream(
            "POST",
            "/api/chat/stream",
            json={"session_id": "stream2", "message": "첫 질문"},
        ) as r:
            _collect_events(r)
        with client.stream(
            "POST",
            "/api/chat/stream",
            json={"session_id": "stream2", "message": "둘째 질문"},
        ) as r:
            _collect_events(r)

        h = client.get("/api/history/stream2")
        humans = [
            m for m in h.json()["data"]["messages"] if m["role"] == "human"
        ]
        assert len(humans) == 2
