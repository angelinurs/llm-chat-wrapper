from fastapi.testclient import TestClient

from app.main import app


def test_validation_error_format():
    with TestClient(app) as client:
        r = client.post("/api/chat", json={"session_id": "t1"})  # message 누락
        assert r.status_code == 422
        body = r.json()
        assert body["success"] is False
        assert body["code"] == "COMMON_001"
        assert body["data"]  # 필드별 상세 오류


def test_http_error_format():
    with TestClient(app) as client:
        r = client.get("/api/no-such-route")
        assert r.status_code == 404
        body = r.json()
        assert body["success"] is False
        assert body["code"] == "COMMON_002"


def test_llm_service_error_returns_502(monkeypatch):
    with TestClient(app) as client:

        async def boom(*args, **kwargs):
            raise RuntimeError("model down")

        monkeypatch.setattr(app.state.graph, "ainvoke", boom)
        r = client.post("/api/chat", json={"session_id": "t1", "message": "hi"})
        assert r.status_code == 502
        body = r.json()
        assert body["success"] is False
        assert body["code"] == "LLM_001"
        assert "model down" in body["message"]


def test_unhandled_exception_returns_500(monkeypatch):
    with TestClient(app, raise_server_exceptions=False) as client:

        async def boom(*args, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(app.state.graph, "aget_state", boom)
        r = client.get("/api/history/t1")
        assert r.status_code == 500
        body = r.json()
        assert body["success"] is False
        assert body["code"] == "COMMON_003"
