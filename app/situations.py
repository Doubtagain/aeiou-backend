"""Situation catalog: YAML(official) + DB(user). 둘 다 같은 dict 스키마.

- 'official' 상황: content/situations/*.yaml로 정의, sync_situations_to_db에서 DB로 upsert.
  payload는 None (load_situation은 YAML을 직접 읽는다).
- 'user' 상황 (v3 Step 7): POST /situations/custom으로 생성, DB의 Situation.payload에
  YAML 동등 dict가 들어간다. YAML 파일은 만들지 않는다.

load_situation은 YAML → DB 순으로 lookup. load_all_situations는 두 소스를 합쳐 반환.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from sqlalchemy.orm import Session as OrmSession

from .config import SITUATIONS_DIR
from .db import session_scope
from .models import Situation


@lru_cache(maxsize=1)
def _load_yaml_all() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for path in sorted(SITUATIONS_DIR.glob("*.yaml")):
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        data["_yaml_path"] = str(path)
        data.setdefault("author", "official")
        out[data["id"]] = data
    return out


def _user_situations_from_db() -> list[dict]:
    """active=True 인 user 생성 상황을 모두 반환."""
    out: list[dict] = []
    with session_scope() as db:
        rows = (
            db.query(Situation)
            .filter(Situation.author == "user", Situation.active.is_(True))
            .all()
        )
        for r in rows:
            if not r.payload:
                continue
            data = dict(r.payload)
            data["id"] = r.id
            data["author"] = "user"
            out.append(data)
    return out


def load_all_situations() -> list[dict]:
    """YAML 카탈로그 + active user 생성 상황을 합쳐 반환."""
    return list(_load_yaml_all().values()) + _user_situations_from_db()


def load_situation(situation_id: str) -> dict:
    """YAML 우선 → DB(user) 폴백. 못 찾으면 KeyError."""
    yaml_sit = _load_yaml_all().get(situation_id)
    if yaml_sit is not None:
        return yaml_sit
    with session_scope() as db:
        row = db.get(Situation, situation_id)
        if row is not None and row.payload:
            data = dict(row.payload)
            data["id"] = row.id
            data["author"] = row.author or "user"
            return data
    raise KeyError(f"unknown situation: {situation_id}")


def goal_for(situation_id: str, goal_id: str) -> dict:
    for g in load_situation(situation_id).get("goal_options", []):
        if g["id"] == goal_id:
            return g
    raise KeyError(f"unknown goal '{goal_id}' for situation '{situation_id}'")


def sync_situations_to_db(db: OrmSession) -> None:
    """YAML 카탈로그를 DB의 'official' 행으로 upsert. user 행은 절대 건드리지 않음."""
    for sit in _load_yaml_all().values():
        existing = db.get(Situation, sit["id"])
        if existing is None:
            db.add(
                Situation(
                    id=sit["id"],
                    title=sit.get("title", sit["id"]),
                    yaml_path=sit.get("_yaml_path", ""),
                    active=True,
                    author="official",
                    payload=None,
                )
            )
        else:
            existing.title = sit.get("title", existing.title)
            existing.yaml_path = sit.get("_yaml_path", existing.yaml_path)
            # user→official 덮어쓰지 않음(이미 official이거나 신규일 때만 official 보장)
            if existing.author != "user":
                existing.author = "official"
    db.commit()


def insert_user_situation(db: OrmSession, payload: dict) -> Situation:
    """v3 Step 7: 사용자 맞춤 상황을 DB에 영속화하고 row를 반환."""
    sid = payload["id"]
    row = Situation(
        id=sid,
        title=payload.get("title", sid),
        yaml_path="",
        active=True,
        author="user",
        payload=payload,
    )
    db.add(row)
    db.commit()
    return row
