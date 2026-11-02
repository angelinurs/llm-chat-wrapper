from fastapi.testclient import TestClient

from app.main import app


def test_multi_turn_chat_and_history():
    with TestClient(app) as client:
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["success"] is True

        r1 = client.post(
            "/api/chat", json={"session_id": "t1", "message": "안녕하세요"}
        )
        assert r1.status_code == 200
        body1 = r1.json()
        assert body1["success"] is True and body1["code"] == "OK"
        assert body1["data"]["reply"]

        r2 = client.post(
            "/api/chat", json={"session_id": "t1", "message": "두 번째 질문"}
        )
        assert r2.status_code == 200

        # 멀티턴: 같은 thread_id 이력에 human 메시지 2개가 쌓여야 한다
        h = client.get("/api/history/t1")
        assert h.status_code == 200
        humans = [
            m for m in h.json()["data"]["messages"] if m["role"] == "human"
        ]
        assert len(humans) == 2
