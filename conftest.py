"""Ensure the project root is importable as the `app` package during tests."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Tests must never touch real external APIs.
os.environ.setdefault("USE_MOCKS", "1")

# Tests use a throwaway SQLite file, not the project's aeiou.db.
os.environ.setdefault(
    "DATABASE_URL", "sqlite:///" + os.path.join(tempfile.gettempdir(), "aeiou_test.db")
)


def pytest_sessionstart(session):  # noqa: ARG001
    """v3: 스키마가 자주 변하는 PoC라 매 테스트 세션 시작에 drop_all → create_all.
    이전 실행의 옛 컬럼이 캐싱돼 SELECT가 실패하는 사고를 방지한다.
    """
    # 임포트 시점이 환경변수 적용 후가 되도록 함수 안에서.
    from app.db import engine  # noqa: PLC0415
    from app.models import Base  # noqa: PLC0415

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
