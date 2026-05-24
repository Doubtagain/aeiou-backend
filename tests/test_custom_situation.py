"""v3 Step 7: POST /situations/custom + 라우트 통합 + 폴백·게이트."""
import os
import asyncio

from fastapi.testclient import TestClient

from app.content.generator import generate_situation
from app.conversation.llm import MockLLM
from app.main import app


def test_generate_situation_returns_valid_config():
    sit = asyncio.run(
        generate_situation(
            "비기술 임원에게 5분 안에 신규 결제 기능을 피칭해야 한다",
            category_hint="presentation",
            llm=MockLLM(),
        )
    )
    # 필수 필드
    assert sit["id"] and sit["title"]
    assert sit["category"] in {"emotional", "interview", "presentation", "business"}
    assert isinstance(sit["goal_options"], list) and sit["goal_options"]
    assert sit["author"] == "user"
    assert sit["category"] == "presentation"


def test_premium_gate_blocks_without_header_or_env(monkeypatch):
    # 환경에서 프리미엄 비활성 + 헤더 없음 → 402
    monkeypatch.setattr("app.routes.content.settings.enable_premium", False)
    with TestClient(app) as c:
        r = c.post(
            "/situations/custom",
            json={"description": "테스트", "category_hint": "interview"},
        )
        assert r.status_code == 402


def test_premium_header_allows(monkeypatch):
    monkeypatch.setattr("app.routes.content.settings.enable_premium", False)
    with TestClient(app) as c:
        r = c.post(
            "/situations/custom",
            json={"description": "동료의 업무 인수인계 받기", "category_hint": "business"},
            headers={"X-Premium": "true"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["author"] == "user"
        assert body["category"] == "business"
        # 카탈로그 조회 author=user 필터에 포함되는지
        r2 = c.get("/situations?author=user")
        assert r2.status_code == 200
        assert any(s["id"] == body["id"] for s in r2.json())
        # author=official에는 안 보임
        r3 = c.get("/situations?author=official")
        assert all(s["id"] != body["id"] for s in r3.json())


def test_enable_premium_env_allows(monkeypatch):
    monkeypatch.setattr("app.routes.content.settings.enable_premium", True)
    with TestClient(app) as c:
        r = c.post(
            "/situations/custom",
            json={"description": "친구와의 오해를 풀어야 한다"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["author"] == "user"
